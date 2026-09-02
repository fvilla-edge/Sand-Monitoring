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

Uso:
    .venv/bin/python publicar_losant.py [puerto]

Por defecto se resuelve solo (ver puerto.py) — pasar un puerto explícito
solo hace falta si el ESP32 no aparece con el VID:PID esperado.
"""

import shutil
import subprocess
import sys
import time

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

PUERTO = resolver_puerto()
BAUDRATE = 115200

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
    en_curso = _proceso_captura is not None and _proceso_captura.poll() is None
    deseado = "capturing" if en_curso else "standby"
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


def main():
    device = _crear_dispositivo()
    proximo_intento = 0.0

    print(f"Leyendo {PUERTO} @ {BAUDRATE}. Informa por MQTT al conectar y cada "
          f"{INTERVALO_INFORME_S // 60} min mientras siga conectado... Ctrl+C para salir")
    with serial.Serial(PUERTO, BAUDRATE, timeout=1) as ser:
        while True:
            ahora = time.monotonic()
            if not device.is_connected() and ahora >= proximo_intento:
                try:
                    device.connect(blocking=False)
                except OSError as e:
                    print(f"Sin red todavía ({e}), reintento en {REINTENTO_CONEXION_S}s...")
                    device = _crear_dispositivo()
                proximo_intento = ahora + REINTENTO_CONEXION_S

            linea = ser.readline().decode(errors="replace").strip()
            if linea:
                procesar_linea(linea, device)

            revisar_periodico(device)
            _revisar_estado_captura(device)
            _revisar_espacio_disco(device)
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
