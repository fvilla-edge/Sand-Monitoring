"""
Publica por MQTT en Losant un informe del estado del SmartSolar cada vez
que la placa recupera conexión a internet, recibido vía el ESP32 (que
escanea BLE y manda la manufacturer data cruda por USB serial, ver
esp32_victron_scan/), desencriptando acá (la Red Pitaya) — adaptado de
publicar_losant.py del proyecto en la notebook (`BLe panel solar/`), que
sí escucha Bluetooth directo.

Publica un informe en dos casos, mientras haya conexión con Losant:
- Apenas se detecta conexión real (eventos "connect"/"reconnect" de
  losantmqtt, que disparan justo cuando el cliente MQTT logra
  conectarse — es la señal más directa de "hay internet y llega a
  destino", no una aproximación tipo ping).
- Cada `panel_solar.informe_intervalo_min` (config_campo.json) mientras
  la conexión se mantenga en pie, para tener un reporte de batería
  periódico y no solo en el instante de conectar.
No publica más seguido que eso: no hay streaming cada N segundos fijo.

Además, en ese mismo evento connect/reconnect, publica un informe de
telemetría del dish Starlink (GPS + estado del link, ver
`starlink_api/`) — una sola vez por conexión, sin repetición periódica.
Va al mismo Device de Losant que el panel solar (a propósito, ver
`losant_config.py`): por eso vive en este mismo proceso en vez de un
servicio separado, no se puede tener dos conexiones MQTT distintas con
el mismo Device ID al mismo tiempo.

Tambien es el "cartero" del reporte del modo evento: manda a Losant, con
su hora original, los resumenes por minuto que deja
scripts_campo/resumen_modo_evento.py en /mnt/usb/losant_pendientes/ (de
noche, sin Starlink, se acumulan y salen al reconectar). El ESP32 es
opcional: sin el, todo lo demas sigue funcionando.

Uso:
    .venv/bin/python publicar_losant.py [puerto]

Por defecto se resuelve solo (ver puerto.py) — pasar un puerto explícito
solo hace falta si el ESP32 no aparece con el VID:PID esperado.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import paho.mqtt.client as mqtt
import serial
from losantmqtt import Device

sys.path.insert(0, "/root/scripts_campo_comun")
import cfg  # noqa: E402 (import tardio, necesita el sys.path de arriba)

sys.path.insert(0, "/root/starlink_api")
from starlink_get_location import (  # noqa: E402 (import tardio, necesita el sys.path de arriba)
    HARDCODED_TELEMETRY,
    build_telemetry_payload,
    to_losant_data,
)

from config import DEVICES
# Device ID, Access Key y Access Secret del dispositivo en Losant.
from losant_config import ACCESS_KEY, ACCESS_SECRET, DEVICE_ID
from puerto import resolver_puerto
from victron_scanner import SerialDecoder

BAUDRATE = 115200
# Sin ESP32 (placa de pruebas, o si se muere en campo) el proceso sigue igual
# (reporte del modo evento, Starlink, device_state) y reintenta abrir el
# puerto cada tanto — antes el while True vivia dentro de serial.Serial() y
# sin ESP32 no arrancaba nada.
REINTENTO_SERIAL_S = 60

# Atributos que interesa mandar a Losant. Hay que crear cada uno como
# "Attribute" del dispositivo en Losant, con este mismo nombre.
ATRIBUTOS = {
    "battery_voltage",
    "battery_charging_current",
    "solar_power",
    "yield_today",
    "external_device_load",
    "charge_state",
    "charger_error",
    "model_name",
}

# Direcciones conocidas (en minúscula) — para saber qué dispositivos hay
# que informar apenas se detecta conexión, aunque todavía no haya llegado
# ninguna lectura por serial.
DIRECCIONES = {d.lower() for d in DEVICES}

# Si el intento de conexión falla (sin red todavía — lo normal la mayor
# parte del día, fuera de la ventana de Starlink), cada cuántos segundos
# se reintenta. Configurable en config_campo.json.
REINTENTO_CONEXION_S = cfg.obtener("panel_solar.reintento_conexion_s")

# Cada cuánto se publica un informe mientras la conexión sigue en pie,
# ademas del que dispara el evento connect/reconnect. Configurable en
# config_campo.json, en minutos (unidad de campo), convertido acá a
# segundos para comparar contra time.monotonic().
INTERVALO_INFORME_S = cfg.obtener("panel_solar.informe_intervalo_min") * 60

# Telemetría del dish Starlink (ver starlink_api/) — "hardcoded" para probar
# la integración sin estar conectado a la antena, "live" para hablar de
# verdad con el dish por gRPC. Leído una sola vez al importar (igual que
# REINTENTO_CONEXION_S/INTERVALO_INFORME_S arriba).
MODO_STARLINK = cfg.obtener("starlink_api.modo")
HOST_DISH_STARLINK = cfg.obtener("starlink_api.host")
TIMEOUT_DISH_STARLINK = cfg.obtener("starlink_api.timeout_s")

# Comando "capturar" recibido por MQTT (ver COMANDOS.md para la cadena
# equivalente corrida a mano). Rutas absolutas porque este proceso corre con
# WorkingDirectory=/root/panel_solar_ble (ver el .service), no en la raíz del
# repo — los mismos "/root/..." que ya usa el sys.path.insert de arriba.
SCRIPT_REPETIR_CAPTURA = "/root/scripts_campo_comun/repetir_captura.sh"
SCRIPT_RELANZAR_CAPTURA = "/root/scripts_campo_comun/relanzar_captura.sh"
SCRIPT_CAPTURAR_STREAM = "/root/scripts_campo/capturar_stream.py"

# USB donde caen las capturas (mismo default que usa capturar_stream.py para
# --directorio, ver config_campo.json: captura_defaults.directorio). Se
# reporta su espacio libre a Losant porque capturar_stream.py ya corta una
# captura en curso al quedarse sin espacio (ver ESPACIO_MIN ahi), pero eso
# solo queda en el log local de la placa — sin esto no hay forma de verlo
# remoto antes de que pase.
DIRECTORIO_CAPTURA = cfg.obtener("captura_defaults.directorio")

# Resumenes por minuto del modo evento, que deja el "anotador"
# (scripts_campo/resumen_modo_evento.py) haya o no internet: este proceso es
# el "cartero" que los manda con su hora original y los borra. De noche (sin
# Starlink) se acumulan y salen al reconectar.
PENDIENTES_DIR = "/mnt/usb/losant_pendientes"
# Losant limita a 30 mensajes cada 15s por Device: 1 por segundo deja margen
# para el resto de los informes. Una noche (~900 resumenes) se pone al dia en
# ~15 min.
PENDIENTES_INTERVALO_S = 1.0
# Cada cuanto se vuelve a mirar la carpeta cuando la cola en memoria esta vacia.
PENDIENTES_RELISTAR_S = 10.0
SERVICIO_MODO_EVENTO = "modo-evento"

# Defaults = la invocación que más se repite en campo (ver COMANDOS.md), para
# que un comando "capturar" sin payload (o con payload parcial) siga siendo
# útil. Todo override por payload es opcional.
DEFAULTS_CAPTURA = {
    "repeticiones": 20,
    "minutos": 0.5,
    "condicion": "reposo",
    "pad": "42",
    "pozo": "1",
    "duracion_chunk": 0.5,
    "canales": 1,
    "decimacion": 32,
}

_decoder = SerialDecoder(DEVICES)
_ultima_lectura = {}      # address -> (rssi, data), la más reciente decodificada
_pendientes = set()       # addresses a informar en cuanto llegue una lectura nueva
_ultima_publicacion = {}  # address -> time.monotonic() de la última vez que se publicó
_proceso_captura = None   # Popen de la captura "capturar" en curso, o None
_estado_equipo = "standby"  # ultimo valor de "device_state" confirmado publicado a Losant
_ultimo_envio_estado = 0.0  # time.monotonic() del ultimo publish exitoso (cambio o refresco periodico)
_ultimo_envio_disco = 0.0   # time.monotonic() del ultimo publish exitoso de espacio libre en el USB
_cola_pendientes = []       # nombres de archivo en PENDIENTES_DIR por mandar, del mas viejo al mas nuevo
_ultimo_listado = 0.0       # time.monotonic() del ultimo listado de PENDIENTES_DIR
_ultimo_pendiente = 0.0     # time.monotonic() del ultimo resumen mandado
_modo_evento_cache = (0.0, False)  # (time.monotonic() del chequeo, activo)
_esp32_avisado = False      # ya se aviso que no hay ESP32 (se vuelve a avisar si aparece y se pierde)


def _crear_dispositivo():
    """
    Arma un Device nuevo de losantmqtt con los observers ya enganchados.

    Se usa tanto al arrancar como para reintentar tras un connect()
    fallido: la librería deja `_mqtt_client` asignado (truthy) apenas
    arranca el intento, aunque el connect() sincrono de más adentro tire
    una excepción por falta de red — un segundo llamado a connect() sobre
    el MISMO objeto no reintenta nada (corta antes, ve _mqtt_client ya
    puesto). Por eso, ante una excepción, se descarta el objeto y se arma
    uno de cero en vez de reintentar sobre el mismo.
    """
    dispositivo = Device(DEVICE_ID, ACCESS_KEY, ACCESS_SECRET)
    dispositivo.add_event_observer("connect", _al_conectar)
    dispositivo.add_event_observer("reconnect", _al_conectar)
    dispositivo.add_event_observer("command", _al_recibir_comando)
    return dispositivo


def _publicar_informe(dispositivo, address, rssi, data):
    # Solo se manda lo que está en ATRIBUTOS; el resto de los campos que
    # trae el anuncio Bluetooth se descarta.
    estado = {clave: valor for clave, valor in data.items() if clave in ATRIBUTOS}
    if not estado:
        return
    estado["rssi"] = rssi
    try:
        dispositivo.send_state(estado)
    except Exception as exc:
        # Sin capturar acá, una falla de publish tira abajo el while True de
        # main() entero (Restart=always relanza recien 10s despues). No se
        # toca _pendientes/_ultima_publicacion: asi la proxima linea serial
        # o el chequeo periodico reintentan solos.
        print(f"Panel solar: no se pudo publicar el informe ({address}): {exc}", file=sys.stderr)
        return
    _pendientes.discard(address)
    _ultima_publicacion[address] = time.monotonic()
    print(f"Informe publicado ({address}): {estado}")


def _publicar_starlink(dispositivo):
    # Amplio a propósito: este proceso también sostiene el reporte de panel
    # solar (Restart=always, crítico en campo) — una falla del lado Starlink
    # (dish inalcanzable, cambio de esquema gRPC, lo que sea) nunca debe
    # tirar abajo ni bloquear el resto del proceso. Se manda igual un informe
    # con "starlink_error" en vez de nada: en campo, sin SSH a mano, es la
    # única forma de enterarse de que algo falló. None en el próximo connect
    # exitoso, para que el dashboard no quede con un error viejo.
    try:
        if MODO_STARLINK == "live":
            payload = build_telemetry_payload(HOST_DISH_STARLINK, TIMEOUT_DISH_STARLINK)
        else:
            payload = HARDCODED_TELEMETRY
        estado = to_losant_data(payload)
        estado["starlink_error"] = None
    except Exception as exc:
        estado = {"starlink_error": str(exc)}
        print(f"Starlink: no se pudo obtener telemetria ({exc})", file=sys.stderr)

    try:
        dispositivo.send_state(estado)
        print(f"Informe Starlink publicado: {estado}")
    except Exception as exc:
        print(f"Starlink: no se pudo publicar el informe a Losant ({exc})", file=sys.stderr)


def _capturar(payload):
    # Probado antes contra un Device de prueba separado (comandos_losant/,
    # ver la rama comandos-losant-test) con un script dummy en vez de la
    # cadena real, para validar el guard/no-bloqueo sin tocar este proceso
    # ni el hardware de captura.
    global _proceso_captura
    if _proceso_captura is not None and _proceso_captura.poll() is None:
        print("Comando 'capturar' ignorado: ya hay una captura en curso.")
        return
    if _modo_evento_activo(forzar=True):
        # El streaming-server acepta UN solo cliente: lanzar capturar_stream
        # con el modo evento corriendo tiraria abajo la medicion continua.
        print("Comando 'capturar' ignorado: el modo evento esta activo "
              "(systemctl disable --now modo-evento para capturar a mano).")
        return

    parametros = {**DEFAULTS_CAPTURA, **payload}
    argv = [
        "bash", SCRIPT_REPETIR_CAPTURA,
        str(parametros["repeticiones"]),
        str(parametros["minutos"]),
        SCRIPT_RELANZAR_CAPTURA,
        SCRIPT_CAPTURAR_STREAM,
        "--condicion", str(parametros["condicion"]),
        "--pad", str(parametros["pad"]),
        "--pozo", str(parametros["pozo"]),
        "--duracion_chunk", str(parametros["duracion_chunk"]),
        "--canales", str(parametros["canales"]),
        "--decimacion", str(parametros["decimacion"]),
    ]
    print(f"Lanzando captura: {argv}")
    # Popen (no .run()) a propósito: bloquear acá colgaría el reporte de
    # panel solar/Starlink durante toda la captura, que puede durar minutos.
    _proceso_captura = subprocess.Popen(argv)


def _hay_captura_externa():
    """True si hay un capturar_stream.py corriendo que este servicio no lanzo
    el mismo (ej. relanzado a mano por SSH, o via repetir_captura.sh) —
    _proceso_captura solo cubre la captura disparada por el comando remoto
    "capturar" de Losant, asi que sin esto una captura manual queda sin
    reportarse nunca como "capturing"."""
    try:
        return subprocess.run(
            ["pgrep", "-f", "capturar_stream.py"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


def _modo_evento_activo(forzar=False):
    """True si modo-evento.service esta activo. Cacheado 10s: se consulta en
    cada vuelta del loop (~1s) y no hace falta un systemctl por segundo."""
    global _modo_evento_cache
    ahora = time.monotonic()
    if not forzar and ahora - _modo_evento_cache[0] < 10:
        return _modo_evento_cache[1]
    try:
        activo = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICIO_MODO_EVENTO],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        activo = False
    _modo_evento_cache = (ahora, activo)
    return activo


def _revisar_estado_captura(dispositivo):
    # Se llama en cada vuelta del loop principal (~1s, ver main()) en vez de
    # publicar directo desde _capturar(): evita duplicar la lógica de
    # publicación acá y en el arranque, y detecta tanto el inicio como el
    # fin de la captura desde un único lugar. Se re-publica igual, aunque no
    # haya cambio, cada INTERVALO_INFORME_S (mismo intervalo que el resto de
    # los informes) — evita quedar reportando un valor viejo para siempre si
    # el servicio se reinicia a mitad de una captura real (el proceso nuevo
    # arranca sin forma de reengancharse al subprocess anterior). Si el
    # send_state falla, ni _estado_equipo ni _ultimo_envio_estado se
    # actualizan y el próximo tick reintenta solo (mismo patrón que
    # _publicar_informe).
    global _estado_equipo, _ultimo_envio_estado
    if not dispositivo.is_connected():
        return
    en_curso = (_proceso_captura is not None and _proceso_captura.poll() is None) or _hay_captura_externa()
    if en_curso:
        deseado = "capturing"
    elif _modo_evento_activo():
        deseado = "modo_evento"
    else:
        deseado = "standby"
    ahora = time.monotonic()
    if deseado == _estado_equipo and ahora - _ultimo_envio_estado < INTERVALO_INFORME_S:
        return
    try:
        dispositivo.send_state({"device_state": deseado})
        print(f"Estado del equipo publicado: {deseado}")
        _estado_equipo = deseado
        _ultimo_envio_estado = ahora
    except Exception as exc:
        print(f"Estado equipo: no se pudo publicar ({exc})", file=sys.stderr)


def _revisar_espacio_disco(dispositivo):
    # Se llama en cada vuelta del loop principal (~1s, ver main()), igual que
    # _revisar_estado_captura, pero sin gate de "solo si cambio": el espacio
    # libre es una magnitud continua (baja de a poco durante una captura), no
    # un estado discreto, asi que alcanza con re-publicar cada
    # INTERVALO_INFORME_S. _ultimo_envio_disco arranca en 0.0 a proposito
    # (mismo truco que _ultimo_envio_estado): el primer tick despues de
    # conectar ya dispara el primer publish, sin esperar el intervalo entero.
    global _ultimo_envio_disco
    if not dispositivo.is_connected():
        return
    ahora = time.monotonic()
    if ahora - _ultimo_envio_disco < INTERVALO_INFORME_S:
        return
    try:
        libre_mb = shutil.disk_usage(DIRECTORIO_CAPTURA).free // (1024 * 1024)
        dispositivo.send_state({"usb_libre_mb": libre_mb})
        print(f"Espacio libre en USB publicado: {libre_mb} MB")
        _ultimo_envio_disco = ahora
    except Exception as exc:
        # Mismo criterio que el resto: no capturar mas arriba (tiraria abajo
        # el while True de main()), y no tocar _ultimo_envio_disco para que
        # el proximo tick reintente solo.
        print(f"Espacio USB: no se pudo publicar ({exc})", file=sys.stderr)


def _publicar_estado_con_hora(dispositivo, data, tiempo_ms):
    """Igual que dispositivo.send_state(data, tiempo_ms), pero devuelve si el
    publish salio de verdad. send_state() de losantmqtt devuelve SIEMPRE False
    con paho 1.6: compara MQTT_ERR_SUCCESS == MQTTMessageInfo, y esa clase no
    define __eq__ (visto 2026-09-25 contra el Device de prueba). Aca se mira
    el rc del MQTTMessageInfo, mismo topic y payload que arma send_state."""
    cliente = dispositivo._mqtt_client
    if not cliente:
        return False
    payload = json.dumps({"time": tiempo_ms, "data": data}, sort_keys=True)
    info = cliente.publish(dispositivo._state_topic(), payload)
    return info.rc == mqtt.MQTT_ERR_SUCCESS


def _enviar_pendientes(dispositivo):
    # Se llama en cada vuelta del loop principal (~1s). Manda de a un resumen
    # por PENDIENTES_INTERVALO_S, del mas viejo al mas nuevo, con su hora
    # original (Losant lo ubica en el minuto en que se midio, no en el que
    # llego). QoS 0 (decision del usuario, 2026-09-25): se borra el archivo
    # cuando el publish da rc OK, o sea cuando el mensaje salio de la
    # placa — no hay confirmacion de que llego. Un resumen ilegible se aparta
    # a .malos/ para no trabar la cola.
    global _cola_pendientes, _ultimo_listado, _ultimo_pendiente
    if not dispositivo.is_connected():
        return
    ahora = time.monotonic()
    if ahora - _ultimo_pendiente < PENDIENTES_INTERVALO_S:
        return
    if not _cola_pendientes:
        if ahora - _ultimo_listado < PENDIENTES_RELISTAR_S:
            return
        _ultimo_listado = ahora
        try:
            nombres = [n for n in os.listdir(PENDIENTES_DIR) if n.endswith(".json") and n[0].isdigit()]
        except OSError:
            return   # sin USB o sin carpeta todavia
        _cola_pendientes = sorted(nombres, key=lambda n: int(n.split(".")[0]))
        if not _cola_pendientes:
            return
    nombre = _cola_pendientes[0]
    ruta = os.path.join(PENDIENTES_DIR, nombre)
    try:
        with open(ruta) as f:
            resumen = json.load(f)
        tiempo, data = int(resumen["time"]), resumen["data"]
    except FileNotFoundError:
        _cola_pendientes.pop(0)
        return
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Pendiente ilegible {nombre} ({exc}), se aparta a .malos/", file=sys.stderr)
        try:
            os.makedirs(os.path.join(PENDIENTES_DIR, ".malos"), exist_ok=True)
            os.replace(ruta, os.path.join(PENDIENTES_DIR, ".malos", nombre))
        except OSError:
            pass
        _cola_pendientes.pop(0)
        return
    _ultimo_pendiente = ahora
    try:
        enviado = _publicar_estado_con_hora(dispositivo, data, tiempo)
    except Exception as exc:
        print(f"Pendiente {nombre}: no se pudo publicar ({exc})", file=sys.stderr)
        return
    if not enviado:
        return   # sin conexion en el medio: queda en la cola, se reintenta
    try:
        os.remove(ruta)
    except OSError:
        pass
    _cola_pendientes.pop(0)
    if not _cola_pendientes:
        print(f"Resumenes del modo evento al dia (ultimo {nombre})")


def _al_recibir_comando(dispositivo, comando):
    nombre = comando["name"].lower()
    payload = comando.get("payload") or {}
    if nombre == "capturar":
        _capturar(payload)
    else:
        print(f"Comando desconocido ignorado: nombre={nombre!r} payload={payload}")


def _al_conectar(dispositivo):
    print("Conectado a Losant.")
    if _ultima_lectura:
        for address, (rssi, data) in list(_ultima_lectura.items()):
            _publicar_informe(dispositivo, address, rssi, data)
    else:
        # No hay lectura todavía (recién arrancado, el ESP32 no mandó
        # nada aún) - se marca pendiente y se informa con la próxima
        # línea que llegue por serial (ver procesar_linea).
        _pendientes.update(DIRECCIONES)
    _publicar_starlink(dispositivo)


def procesar_linea(linea, device):
    resultado = _decoder.procesar_linea(linea)
    if resultado is None:
        return
    address, rssi, data = resultado
    _ultima_lectura[address] = (rssi, data)
    if address in _pendientes and device.is_connected():
        _publicar_informe(device, address, rssi, data)


def revisar_periodico(device):
    # Si nunca se publicó nada para esta dirección todavía (recién
    # conectado, el evento connect ya se encargó o está pendiente en
    # procesar_linea), no hay nada que este chequeo deba adelantar.
    if not device.is_connected():
        return
    ahora = time.monotonic()
    for address, (rssi, data) in list(_ultima_lectura.items()):
        ultima = _ultima_publicacion.get(address)
        if ultima is not None and ahora - ultima >= INTERVALO_INFORME_S:
            _publicar_informe(device, address, rssi, data)


def _abrir_serial():
    """Abre el puerto del ESP32, o None si no esta (se reintenta desde main).
    Avisa solo el primer fallo de cada racha: sin ESP32 (placa de pruebas)
    seria una linea por minuto en un journal de 5MB que vive en RAM."""
    global _esp32_avisado
    puerto = resolver_puerto()
    try:
        ser = serial.Serial(puerto, BAUDRATE, timeout=1)
    except (serial.SerialException, OSError) as exc:
        if not _esp32_avisado:
            print(f"ESP32 no disponible en {puerto} ({exc}), sigo sin panel solar; "
                  f"reintento cada {REINTENTO_SERIAL_S}s sin volver a avisar", file=sys.stderr)
            _esp32_avisado = True
        return None
    print(f"Leyendo {puerto} @ {BAUDRATE}")
    _esp32_avisado = False
    return ser


def main():
    device = _crear_dispositivo()
    proximo_intento = 0.0
    ser = _abrir_serial()
    proximo_serial = time.monotonic() + REINTENTO_SERIAL_S

    print(f"Informa por MQTT al conectar y cada {INTERVALO_INFORME_S // 60} min mientras "
          f"siga conectado; resumenes del modo evento desde {PENDIENTES_DIR}... Ctrl+C para salir")
    while True:
        ahora = time.monotonic()
        if not device.is_connected() and ahora >= proximo_intento:
            try:
                device.connect(blocking=False)
            except OSError as e:
                print(f"Sin red todavía ({e}), reintento en {REINTENTO_CONEXION_S}s...")
                device = _crear_dispositivo()
            proximo_intento = ahora + REINTENTO_CONEXION_S

        if ser is None and ahora >= proximo_serial:
            ser = _abrir_serial()
            proximo_serial = ahora + REINTENTO_SERIAL_S
        if ser is not None:
            try:
                linea = ser.readline().decode(errors="replace").strip()
            except (serial.SerialException, OSError) as exc:
                # ESP32 desenchufado en marcha: seguir sin el y reintentar
                print(f"ESP32: se perdio el puerto ({exc}), sigo sin panel solar", file=sys.stderr)
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                proximo_serial = ahora + REINTENTO_SERIAL_S
                linea = ""
            if linea:
                procesar_linea(linea, device)
        else:
            # sin ESP32 el readline(timeout=1) ya no marca el paso del loop
            time.sleep(0.9)

        revisar_periodico(device)
        _revisar_estado_captura(device)
        _revisar_espacio_disco(device)
        _enviar_pendientes(device)
        try:
            device.loop(timeout=0.1)
        except Exception as exc:
            # losantmqtt tira Exception pelada (no OSError) para
            # credenciales invalidas/revocadas — la lanza desde adentro
            # de este loop, no de connect(). Es permanente, no de red,
            # pero se trata igual que el OSError de arriba: descartar el
            # dispositivo y reintentar mas tarde, para no crashear el
            # proceso entero ni quemar reintentos cada iteracion.
            print(f"Losant: conexion abortada ({exc}), reintento en {REINTENTO_CONEXION_S}s...",
                  file=sys.stderr)
            device = _crear_dispositivo()
            proximo_intento = time.monotonic() + REINTENTO_CONEXION_S


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCortado por el usuario.")
