#!/usr/bin/env python3
"""
resumen_modo_evento.py — "anotador" del reporte a Losant del modo evento.

Cada minuto resume las filas nuevas del CSV de ventanas que escribe
capturar_eventos (docs/modo_evento.md) y deja el resumen como un archivo
chico en /mnt/usb/losant_pendientes/<t_ms>.json, haya o no internet. El
"cartero" (panel_solar_ble/publicar_losant.py, la unica conexion MQTT al
Device) los manda a Losant con su hora original cuando hay conexion y los
borra. Asi el buffer nocturno (sin Starlink) no es un caso aparte: de
noche simplemente se acumulan archivos.

No sabe nada de MQTT ni del ESP32, y no toca capturar_eventos: solo lee el
CSV y el log de reinicios del supervisor.

Cuidados de carga (en NOCHE1, 2026-09-25, hasta un `ls` periodico coincidia
con perdidas de muestras):
  - proceso persistente con Nice=10 (ver el .service), no uno nuevo por minuto;
  - lectura incremental del CSV (solo los bytes nuevos desde el minuto anterior);
  - nunca lista la carpeta de eventos (puede tener decenas de miles de archivos):
    el nombre del CSV sale de la hora UTC.

Uso:
    python3 resumen_modo_evento.py [--pendientes /mnt/usb/losant_pendientes]
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/root/scripts_campo_comun")
import cfg  # noqa: E402 (import tardio, necesita el sys.path de arriba)

SERVICIO = "modo-evento"
INTERVALO_S = 60
# Resumenes que se guardan en RAM si /mnt/usb no esta montado (nunca a la SD):
# 1440 = un dia de minutos. Pasado eso se descartan los mas viejos.
MAX_EN_RAM = 1440
LOG_REINICIOS = os.path.join(cfg.obtener("rutas.log_dir"), "modo_evento_reinicios.log")
# La crea/borra capturar_eventos al pausar/reanudar la señal cruda por espacio
BANDERA_CRUDA_PAUSADA = "/run/modo-evento/cruda_pausada"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def estado_servicio():
    """(activo, destino, umbral) leidos de systemd: siguen solos un cambio de
    Environment= o de drop-in en modo-evento.service."""
    try:
        salida = subprocess.run(
            ["systemctl", "show", "-p", "ActiveState", "-p", "Environment", SERVICIO],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return False, None, None
    activo, env = False, {}
    for linea in salida.splitlines():
        clave, _, valor = linea.partition("=")
        if clave == "ActiveState":
            activo = valor == "active"
        elif clave == "Environment":
            for par in valor.split():
                k, _, v = par.partition("=")
                env[k] = v
    try:
        umbral = float(env["UMBRAL"])
    except (KeyError, ValueError):
        umbral = None
    return activo, env.get("DESTINO"), umbral


def ruta_csv(destino, hora):
    return os.path.join(destino, f"ventanas_{hora:%Y%m%d_%H}.csv")


class LectorCSV:
    """Lee solo las filas nuevas de los CSV por hora, siguiendo la rotacion."""

    def __init__(self):
        self.destino = None
        self.hora = None      # datetime UTC truncado a la hora del CSV en curso
        self.offset = 0
        self.ultima_fila = None  # (t_utc_ms, area, kurtosis) de la ultima fila ok vista

    def _arrancar(self, destino, ahora):
        # Arranca al final del CSV actual: el primer resumen cubre el primer
        # minuto de este proceso, no la historia. Se siembra ultima_fila con
        # la cola del archivo para que me_seg_sin_datos tenga sentido de entrada.
        self.destino = destino
        self.hora = ahora.replace(minute=0, second=0, microsecond=0)
        ruta = ruta_csv(destino, self.hora)
        try:
            tam = os.path.getsize(ruta)
            with open(ruta, "rb") as f:
                f.seek(max(0, tam - 4096))
                for fila in self._parsear(f.read().decode(errors="replace").splitlines()[1:]):
                    if fila[4] == "ok":
                        self.ultima_fila = (fila[1], fila[2], fila[3])
            self.offset = tam
        except OSError:
            self.offset = 0

    @staticmethod
    def _parsear(lineas):
        for linea in lineas:
            partes = linea.split(",")
            if len(partes) != 6 or partes[0] == "window_count":
                continue
            try:
                wc, t_ms = int(partes[0]), int(partes[1])
                area = float(partes[2]) if partes[2] else None
                kurt = float(partes[3]) if partes[3] else None
            except ValueError:
                continue
            yield wc, t_ms, area, kurt, partes[4]

    def _leer_archivo(self, ruta):
        try:
            tam = os.path.getsize(ruta)
        except OSError:
            return []
        if tam < self.offset:   # archivo recreado: empezar de cero
            self.offset = 0
        if tam == self.offset:
            return []
        with open(ruta, "rb") as f:
            f.seek(self.offset)
            datos = f.read(tam - self.offset)
        # solo lineas completas: una fila a medio escribir queda para el minuto que viene
        corte = datos.rfind(b"\n") + 1
        self.offset += corte
        return list(self._parsear(datos[:corte].decode(errors="replace").splitlines()))

    def filas_nuevas(self, destino, ahora):
        if destino != self.destino:
            self._arrancar(destino, ahora)
            return []
        hora_actual = ahora.replace(minute=0, second=0, microsecond=0)
        filas = self._leer_archivo(ruta_csv(destino, self.hora))
        if hora_actual != self.hora:
            # rotacion: se termino de leer la hora anterior, pasar a la actual.
            # Si hubo un salto de varias horas (placa apagada) no se recorren
            # las intermedias: el resumen es del ultimo minuto, no un historico.
            self.hora, self.offset = hora_actual, 0
            filas += self._leer_archivo(ruta_csv(destino, self.hora))
        for fila in filas:
            if fila[4] == "ok":
                self.ultima_fila = (fila[1], fila[2], fila[3])
        return filas


class Contadores:
    """Eventos del dia (UTC), persistidos en el USB para sobrevivir a un reinicio
    de este proceso."""

    def __init__(self, ruta):
        self.ruta = ruta
        self.dia, self.eventos = None, 0
        try:
            with open(ruta) as f:
                datos = json.load(f)
            self.dia, self.eventos = datos["dia"], int(datos["eventos"])
        except (OSError, ValueError, KeyError):
            pass

    def sumar(self, dia, n):
        if dia != self.dia:
            self.dia, self.eventos = dia, 0
        self.eventos += n
        try:
            tmp = self.ruta + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"dia": self.dia, "eventos": self.eventos}, f)
            os.replace(tmp, self.ruta)
        except OSError:
            pass   # sin USB: se sigue contando en RAM


def reinicios_hoy(dia):
    """Caidas del dia (UTC) segun el supervisor: toda terminacion que no sea la
    parada limpia (resultado=success). Las lineas sin_usb no cuentan: son
    arranques rechazados, no caidas."""
    n = 0
    try:
        with open(LOG_REINICIOS) as f:
            for linea in f:
                if linea.startswith(dia) and "resultado=" in linea and "resultado=success" not in linea:
                    n += 1
    except OSError:
        return None
    return n


def resumir(filas, lector, contadores, activo, umbral, ahora):
    ok = [f for f in filas if f[4] == "ok" and f[3] is not None]
    kurts = [f[3] for f in ok]
    areas = [f[2] for f in ok if f[2] is not None]
    en_umbral = sum(1 for k in kurts if umbral is not None and k >= umbral)
    dia = ahora.strftime("%Y-%m-%d")
    contadores.sumar(dia, en_umbral)

    t_ms = int(ahora.timestamp() * 1000)
    # Atributos del Device en Losant (mismo nombre). "Ventana" = 50 ms de señal;
    # en un minuto hay ~1200.
    data = {
        # true si el servicio de medicion (modo-evento) esta corriendo
        "me_activo": activo,
        # ventanas medidas en el ultimo minuto (~1200 si todo anda bien)
        "me_ventanas_1min": len(filas),
        # ventanas que el programa no llego a leer en el ultimo minuto (lo normal es 0)
        "me_ventanas_saltadas_1min": sum(1 for f in filas if f[4] != "ok"),
        # ventanas sobre el umbral en el dia (UTC) = eventos guardados en el USB.
        # Cota superior: no descuenta los que capturar_eventos descarte por cola llena
        "me_eventos_hoy": contadores.eventos,
    }
    if lector.ultima_fila is not None:
        # segundos desde la ultima ventana medida: señal de vida (lo normal es <2)
        data["me_seg_sin_datos"] = max(0.0, round((t_ms - lector.ultima_fila[0]) / 1000, 1))
    if ok:
        ultima = ok[-1]
        data.update({
            # kurtosis de la ultima ventana (reposo ~3; arena = picos, sube)
            "kurt_ultima": round(ultima[3], 3),
            # kurtosis mas alta del ultimo minuto: no se pierde un pase breve entre reportes
            "kurt_max_1min": round(max(kurts), 3),
            # ventanas del ultimo minuto con kurtosis >= umbral (guardadas como evento)
            "ventanas_umbral_1min": en_umbral,
        })
        if ultima[2] is not None:
            # area (energia de la señal) de la ultima ventana (reposo ~0.52 en HV)
            data["area_ultima"] = round(ultima[2], 4)
        if areas:
            # area tipica del ultimo minuto (la mediana ignora picos sueltos)
            data["area_mediana_1min"] = round(statistics.median(areas), 4)
            # area mas alta del ultimo minuto
            data["area_max_1min"] = round(max(areas), 4)
    # true si capturar_eventos pauso la señal cruda de los eventos por poco
    # espacio en el USB (el registro de ventanas sigue igual)
    data["me_cruda_pausada"] = os.path.exists(BANDERA_CRUDA_PAUSADA)
    reinicios = reinicios_hoy(dia)
    if reinicios is not None:
        # veces que se cayo la medicion en el dia (UTC) y el supervisor la relanzo
        data["me_reinicios_hoy"] = reinicios
    try:
        # espacio libre en el disco USB, en MB
        data["usb_libre_mb"] = shutil.disk_usage("/mnt/usb").free // (1024 * 1024)
    except OSError:
        pass
    return {"time": t_ms, "data": data}


def guardar(pendientes_dir, en_ram, resumen):
    """Deja el resumen en el USB (archivo atomico por minuto). Sin USB montado
    lo guarda en RAM y lo baja apenas vuelva: nunca escribe en la SD."""
    en_ram.append(resumen)
    del en_ram[:-MAX_EN_RAM]
    if not os.path.ismount("/mnt/usb"):
        return
    try:
        os.makedirs(pendientes_dir, exist_ok=True)
        while en_ram:
            r = en_ram[0]
            final = os.path.join(pendientes_dir, f"{r['time']}.json")
            tmp = final + ".tmp"
            with open(tmp, "w") as f:
                json.dump(r, f, separators=(",", ":"))
            os.replace(tmp, final)
            en_ram.pop(0)
    except OSError as exc:
        log(f"no se pudo guardar en {pendientes_dir} ({exc}), queda en RAM ({len(en_ram)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pendientes", default="/mnt/usb/losant_pendientes",
                    help="carpeta de resumenes a mandar (default /mnt/usb/losant_pendientes)")
    args = ap.parse_args()

    lector = LectorCSV()
    contadores = Contadores(os.path.join(args.pendientes, ".contadores.json"))
    en_ram = []
    log(f"Anotador del modo evento: un resumen cada {INTERVALO_S}s en {args.pendientes}")
    proximo = time.monotonic()
    while True:
        ahora = datetime.now(timezone.utc)
        activo, destino, umbral = estado_servicio()
        filas = lector.filas_nuevas(destino, ahora) if destino else []
        resumen = resumir(filas, lector, contadores, activo, umbral, ahora)
        guardar(args.pendientes, en_ram, resumen)
        log(f"resumen: {resumen['data']}")
        # monotonic: un salto de reloj por NTP (sin RTC) no adelanta ni frena el ciclo
        proximo += INTERVALO_S
        time.sleep(max(1.0, proximo - time.monotonic()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
