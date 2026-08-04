"""
Muestra por pantalla, en vivo, los datos del SmartSolar recibidos vía el
ESP32 (que escanea BLE y manda la manufacturer data cruda por USB serial,
ver esp32_victron_scan/). Desencripta acá (en quien lea este puerto —
la Red Pitaya, en este proyecto) en vez de escuchar Bluetooth directo.

Uso:
    .venv/bin/python leer_smartsolar_serial.py [puerto]

Por defecto usa /dev/ttyACM0.
"""

import sys
import time
from datetime import datetime

import serial

from config import DEVICES
from victron_scanner import SerialDecoder

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

_decoder = SerialDecoder(DEVICES)
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
    resultado = _decoder.procesar_linea(linea)
    if resultado is None:
        return
    address, rssi, data = resultado
    mostrar(address, rssi, data)


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
