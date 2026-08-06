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

Uso:
    .venv/bin/python publicar_losant.py [puerto]

Por defecto se resuelve solo (ver puerto.py) — pasar un puerto explícito
solo hace falta si el ESP32 no aparece con el VID:PID esperado.
"""

import sys
import time

import serial
from losantmqtt import Device

sys.path.insert(0, "/root/scripts_campo_comun")
import cfg  # noqa: E402 (import tardio, necesita el sys.path de arriba)

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
# se reintenta.
REINTENTO_CONEXION_S = 30

# Cada cuánto se publica un informe mientras la conexión sigue en pie,
# ademas del que dispara el evento connect/reconnect. Configurable en
# config_campo.json, en minutos (unidad de campo), convertido acá a
# segundos para comparar contra time.monotonic().
INTERVALO_INFORME_S = cfg.obtener("panel_solar.informe_intervalo_min") * 60

_decoder = SerialDecoder(DEVICES)
_ultima_lectura = {}      # address -> (rssi, data), la más reciente decodificada
_pendientes = set()       # addresses a informar en cuanto llegue una lectura nueva
_ultima_publicacion = {}  # address -> time.monotonic() de la última vez que se publicó


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
    return dispositivo


def _publicar_informe(dispositivo, address, rssi, data):
    # Solo se manda lo que está en ATRIBUTOS; el resto de los campos que
    # trae el anuncio Bluetooth se descarta.
    estado = {clave: valor for clave, valor in data.items() if clave in ATRIBUTOS}
    if not estado:
        return
    estado["rssi"] = rssi
    dispositivo.send_state(estado)
    _pendientes.discard(address)
    _ultima_publicacion[address] = time.monotonic()
    print(f"Informe publicado ({address}): {estado}")


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
            device.loop(timeout=0.1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCortado por el usuario.")
