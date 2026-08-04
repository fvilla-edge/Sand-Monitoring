"""
Muestra por pantalla, en vivo, los datos del SmartSolar recibidos vía el
ESP32 (que escanea BLE y manda la manufacturer data cruda por USB serial,
ver esp32_victron_scan/). Mismo formato y throttling que leer_smartsolar.py,
pero desencriptando en la PC en vez de leer Bluetooth directamente.

Uso:
    .venv/bin/python leer_smartsolar_serial.py [puerto]

Por defecto usa /dev/ttyACM0.
"""

import re
import sys
import time
from datetime import datetime

import serial

from config import DEVICES
from victron_ble.devices import detect_device_type
from victron_ble.exceptions import AdvertisementKeyMissingError, UnknownDeviceError
from victron_scanner import parsed_to_dict

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
BAUDRATE = 115200

# Cada cuántos segundos se muestra por pantalla un mismo dispositivo.
# El ESP32 sigue mandando datos seguido igual; esto solo frena la impresión.
INTERVALO_PANTALLA = 20

UNIDADES = {
    "battery_voltage": "V",
    "battery_charging_current": "A",
    "solar_power": "W",
    "yield_today": "Wh",
    "external_device_load": "A",
}

LINEA_RE = re.compile(r"MAC=([0-9a-f:]+) RSSI=(-?\d+) LEN=(\d+) DATA=([0-9A-Fa-f]+)")

_device_keys = {mac.lower(): key for mac, key in DEVICES.items()}
_known_devices = {}
_last_shown = {}


def mostrar(address, rssi, data):
    ahora = time.monotonic()
    if ahora - _last_shown.get(address, 0) < INTERVALO_PANTALLA:
        return
    _last_shown[address] = ahora

    hora = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{hora}] {address}  RSSI: {rssi} dBm")
    for clave, valor in data.items():
        unidad = UNIDADES.get(clave, "")
        print(f"    {clave}: {valor} {unidad}".rstrip())


def procesar_linea(linea):
    m = LINEA_RE.search(linea)
    if not m:
        return

    address = m.group(1).lower()
    rssi = int(m.group(2))
    raw = bytes.fromhex(m.group(4))

    if address not in _device_keys:
        return

    # Los primeros 2 bytes son el Company ID (0x02E1); victron-ble espera
    # el payload sin eso, igual que bleak se lo entrega.
    payload = raw[2:]

    if address not in _known_devices:
        device_klass = detect_device_type(payload)
        if not device_klass:
            return
        _known_devices[address] = device_klass(_device_keys[address])

    try:
        parsed = _known_devices[address].parse(payload)
    except AdvertisementKeyMissingError:
        return
    except UnknownDeviceError:
        return

    mostrar(address, rssi, parsed_to_dict(parsed))


def main():
    print(f"Leyendo {PUERTO} @ {BAUDRATE} (una lectura por pantalla cada {INTERVALO_PANTALLA}s)... Ctrl+C para salir")
    with serial.Serial(PUERTO, BAUDRATE, timeout=1) as ser:
        while True:
            linea = ser.readline().decode(errors="replace").strip()
            if linea:
                procesar_linea(linea)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCortado por el usuario.")
