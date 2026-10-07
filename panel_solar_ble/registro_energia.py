"""
Registro local de energia (docs/plan_perfiles_energia.md, etapa 1).

publicar_losant.py le pasa cada lectura que descifra del SmartSolar y este
modulo deja una fila por minuto (promedio del minuto) en un CSV por hora,
haya o no internet: de noche, sin Starlink, es la unica forma de saber que
pasa con la bateria. Mas adelante (etapa 2) de estos CSV salen el SOC, el
balance diario y la autonomia.

- Archivo: <carpeta>/energia_AAAAMMDD_HH.csv (hora UTC, igual que los CSV
  del modo evento). Carpeta en el USB si hay disco montado; si no, en la SD.
- Cada fila se escribe con fsync: el corte por baja tension de la salida
  LOAD del MPPT apaga la placa sin aviso.
- Una lectura con algun valor imposible se descarta entera (se vieron en
  Losant 231 V con 514 kWh, o 44,9 A de carga: el descifrado de una linea
  serie corrupta). Se cuentan aparte en la fila.
- Un minuto sin ninguna lectura no deja fila: el hueco en el CSV es el dato
  (sin ESP32, o placa apagada).

Columnas: ver COLUMNAS. Corrientes en A, potencias en W, energia en Wh.
battery_charging_current es la corriente NETA de la bateria (lo que da el
cargador menos lo que consume LOAD; verificado con datos_campo/bateria.csv),
positiva cargando y negativa descargando.
"""
import os
import subprocess
import time
from datetime import datetime, timezone

COLUMNAS = (
    "hora_utc",          # inicio del minuto, ISO UTC
    "hora_confiable",    # 1 si NTP sincronizado o RTC DS3231 restaurado en este boot
    "lecturas",          # lecturas validas promediadas en el minuto
    "descartadas",       # lecturas con algun valor fuera de rango
    "v_bat",             # tension de bateria, promedio
    "v_bat_min",
    "i_bat",             # corriente neta de bateria, promedio (+ carga, - descarga)
    "i_carga",           # salida LOAD, promedio
    "i_carga_max",
    "p_panel",           # potencia del panel, promedio
    "yield_hoy_wh",      # ultimo valor del minuto ("dia solar" del MPPT, pasos de 10 Wh)
    "estado_carga",      # ultimo valor del minuto (off/bulk/absorption/float...)
    "error_cargador",    # ultimo valor del minuto
    "starlink",          # estado del rele segun starlink_remoto (on/off), sin leer HW
)

# Rangos validos (bateria LiFePO4 12 V, MPPT 75/15, panel 120 W). Fuera de
# esto la lectura es basura, no un valor raro de verdad.
RANGOS = {
    "battery_voltage": (9.0, 16.0),
    "battery_charging_current": (-20.0, 20.0),
    "external_device_load": (0.0, 15.0),
    "solar_power": (0.0, 150.0),
    "yield_today": (0.0, 2000.0),
}

RTC_FLAG_OK = "/run/rtc_ds3231_ok"   # lo deja rtc_ds3231/restaurar_hora.sh
NTP_RECHEQUEO_S = 600                # timedatectl levanta timedated por dbus: no cada minuto


def disco_montado(punto="/mnt/usb"):
    """True si punto es un disco de verdad (no la carpeta de la SD ni un tmpfs).
    Misma regla que scripts_campo/resumen_modo_evento.py."""
    if not os.path.ismount(punto):
        return False
    tipo = None
    try:
        with open("/proc/mounts") as f:
            for linea in f:   # el ultimo montaje sobre el punto es el que se ve
                partes = linea.split()
                if len(partes) > 2 and partes[1] == punto:
                    tipo = partes[2]
    except OSError:
        pass
    return tipo != "tmpfs"


def lectura_valida(data):
    """True si todos los campos numericos presentes estan en rango y estan
    los dos imprescindibles (tension y corriente)."""
    if "battery_voltage" not in data or "battery_charging_current" not in data:
        return False
    for clave, (minimo, maximo) in RANGOS.items():
        valor = data.get(clave)
        if valor is None:
            continue
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return False
        if not minimo <= valor <= maximo:
            return False
    return True


class _RelojConfiable:
    def __init__(self):
        self._ntp = False
        self._ultimo_chequeo = None

    def __call__(self):
        if os.path.exists(RTC_FLAG_OK):
            return True
        ahora = time.monotonic()
        if self._ultimo_chequeo is None or ahora - self._ultimo_chequeo >= NTP_RECHEQUEO_S:
            self._ultimo_chequeo = ahora
            try:
                r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                                   capture_output=True, text=True, timeout=10)
                self._ntp = r.stdout.strip() == "yes"
            except (OSError, subprocess.SubprocessError):
                self._ntp = False
        return self._ntp


class RegistroEnergia:
    def __init__(self, dir_usb, dir_sd, state_file, punto_usb="/mnt/usb",
                 reloj_confiable=None, ahora=time.time):
        self.dir_usb = dir_usb
        self.dir_sd = dir_sd
        self.state_file = state_file
        self.punto_usb = punto_usb
        self._reloj_confiable = reloj_confiable or _RelojConfiable()
        self._ahora = ahora
        self._minuto = None   # minuto (epoch // 60) que se esta juntando
        self._validas = []
        self._descartadas = 0

    def agregar(self, data):
        """Suma una lectura descifrada (dict de victron_scanner.parsed_to_dict).
        Devuelve True si de paso cerro y escribio el minuto anterior."""
        escribio = self.tick()
        if self._minuto is None:
            self._minuto = int(self._ahora() // 60)
        if lectura_valida(data):
            self._validas.append(data)
        else:
            self._descartadas += 1
        return escribio

    def tick(self):
        """Llamar seguido (cada vuelta del loop): cierra el minuto que ya paso
        aunque no lleguen mas lecturas. Devuelve True si escribio una fila."""
        if self._minuto is None:
            return False
        if int(self._ahora() // 60) != self._minuto:
            return self.cerrar_minuto()
        return False

    def cerrar_minuto(self):
        """Escribe la fila del minuto en curso. True si escribio."""
        minuto, validas, descartadas = self._minuto, self._validas, self._descartadas
        self._minuto, self._validas, self._descartadas = None, [], 0
        if minuto is None or (not validas and not descartadas):
            return False
        self._escribir(self._fila(minuto, validas, descartadas), minuto)
        return True

    def _fila(self, minuto, validas, descartadas):
        inicio = datetime.fromtimestamp(minuto * 60, tz=timezone.utc)

        def valores(clave):
            return [float(d[clave]) for d in validas if d.get(clave) is not None]

        def prom(clave):
            v = valores(clave)
            return f"{sum(v) / len(v):.3f}" if v else ""

        def extremo(clave, fn):
            v = valores(clave)
            return f"{fn(v):.3f}" if v else ""

        def ultimo(clave):
            for d in reversed(validas):
                if d.get(clave) is not None:
                    return str(d[clave])
            return ""

        return {
            "hora_utc": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hora_confiable": "1" if self._reloj_confiable() else "0",
            "lecturas": str(len(validas)),
            "descartadas": str(descartadas),
            "v_bat": prom("battery_voltage"),
            "v_bat_min": extremo("battery_voltage", min),
            "i_bat": prom("battery_charging_current"),
            "i_carga": prom("external_device_load"),
            "i_carga_max": extremo("external_device_load", max),
            "p_panel": prom("solar_power"),
            "yield_hoy_wh": ultimo("yield_today"),
            "estado_carga": ultimo("charge_state"),
            "error_cargador": ultimo("charger_error"),
            "starlink": self._estado_starlink(),
        }

    def _estado_starlink(self):
        try:
            with open(self.state_file) as f:
                return f.read().strip()
        except OSError:
            return ""

    def carpeta(self):
        return self.dir_usb if disco_montado(self.punto_usb) else self.dir_sd

    @staticmethod
    def _termina_en_salto(ruta):
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                return True
            f.seek(-1, os.SEEK_END)
            return f.read(1) == b"\n"

    def _escribir(self, fila, minuto):
        carpeta = self.carpeta()
        os.makedirs(carpeta, exist_ok=True)
        inicio = datetime.fromtimestamp(minuto * 60, tz=timezone.utc)
        ruta = os.path.join(carpeta, f"energia_{inicio:%Y%m%d_%H}.csv")
        # vacio = un corte justo despues de crearlo: va el encabezado igual
        nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
        linea = ",".join(fila[c] for c in COLUMNAS) + "\n"
        if not nuevo and not self._termina_en_salto(ruta):
            # un apagon dejo la ultima linea por la mitad: que la fila nueva
            # no se pegue a ese pedazo (se pierde solo la linea cortada)
            linea = "\n" + linea
        with open(ruta, "a") as f:
            if nuevo:
                f.write(",".join(COLUMNAS) + "\n")
            f.write(linea)
            f.flush()
            os.fsync(f.fileno())
        if nuevo:
            # que la entrada del archivo nuevo tambien sobreviva un corte
            fd = os.open(carpeta, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
