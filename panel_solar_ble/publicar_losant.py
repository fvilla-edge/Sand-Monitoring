"""
Publica por MQTT en Losant los datos del SmartSolar recibidos vía el
ESP32 (que escanea BLE y manda la manufacturer data cruda por USB serial,
ver esp32_victron_scan/), desencriptando acá (la Red Pitaya) en vez de
escuchar Bluetooth directo — adaptado de publicar_losant.py del proyecto
en la notebook (`BLe panel solar/`), que sí escucha Bluetooth en vivo.

Uso:
    .venv/bin/python publicar_losant.py [puerto]

Por defecto usa /dev/ttyACM0.
"""

import sys
import time

import serial
from losantmqtt import Device

from config import DEVICES
# Device ID, Access Key y Access Secret del dispositivo en Losant.
from losant_config import ACCESS_KEY, ACCESS_SECRET, DEVICE_ID
from victron_scanner import SerialDecoder

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
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

# Cada cuántos segundos se publica un estado por MQTT. El ESP32 sigue
# mandando datos cada 1-3s; publicar tan seguido no aporta y consume
# rápido la cuota mensual de mensajes de Losant.
INTERVALO_PUBLICACION = 30

# Representa el dispositivo dentro de Losant. Todavía no conecta nada acá,
# solo queda armado con las credenciales.
device = Device(DEVICE_ID, ACCESS_KEY, ACCESS_SECRET)

_decoder = SerialDecoder(DEVICES)
_last_sent = {}


def publicar(address, rssi, data):
    ahora = time.monotonic()
    if ahora - _last_sent.get(address, 0) < INTERVALO_PUBLICACION:
        return

    # Solo se manda lo que está en ATRIBUTOS; el resto de los campos que
    # trae el anuncio Bluetooth se descarta.
    estado = {clave: valor for clave, valor in data.items() if clave in ATRIBUTOS}
    if estado and device.is_connected():
        estado["rssi"] = rssi
        device.send_state(estado)
        _last_sent[address] = ahora
        print(f"Publicado: {estado}")


def procesar_linea(linea):
    resultado = _decoder.procesar_linea(linea)
    if resultado is None:
        return
    address, rssi, data = resultado
    publicar(address, rssi, data)


def main():
    print("Conectando a Losant...")
    # blocking=False: la conexión se establece en segundo plano, sin
    # trabar la lectura del puerto serie mientras se conecta.
    device.connect(blocking=False)
    print(f"Leyendo {PUERTO} @ {BAUDRATE}... Ctrl+C para salir")
    with serial.Serial(PUERTO, BAUDRATE, timeout=1) as ser:
        while True:
            linea = ser.readline().decode(errors="replace").strip()
            if linea:
                procesar_linea(linea)
            # device.loop() mantiene viva la conexión MQTT y efectivamente
            # envía lo que send_state dejó pendiente. Sin este llamado
            # periódico, send_state no llega a salir por la red. Se llama
            # una vez por vuelta (cada ~1s, por el timeout del serial de
            # arriba) en vez de necesitar un sleep propio.
            device.loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCortado por el usuario.")
