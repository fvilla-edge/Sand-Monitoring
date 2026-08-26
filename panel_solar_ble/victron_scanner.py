"""
Escaneo Bluetooth compartido para dispositivos Victron (Instant Readout).
Centraliza la detección de modelo, desencriptado y armado de los datos en
un diccionario, para que cada script (mostrar por pantalla, publicar por
MQTT, etc.) solo se ocupe de qué hacer con esos datos.
"""

import inspect
import re
import struct
from enum import Enum

from victron_ble.devices import DeviceData, detect_device_type
from victron_ble.exceptions import (
    AdvertisementKeyMismatchError,
    AdvertisementKeyMissingError,
    UnknownDeviceError,
)

LINEA_SERIAL_RE = re.compile(r"MAC=([0-9a-f:]+) RSSI=(-?\d+) LEN=(\d+) DATA=([0-9A-Fa-f]+)")


def parsed_to_dict(parsed: DeviceData) -> dict:
    """
    Cada anuncio trae métodos get_xxx() (get_battery_voltage, get_solar_power,
    etc.), distintos según el modelo detectado. Esta función los recorre
    todos automáticamente en vez de listarlos a mano uno por uno.
    """
    data = {}
    for name, method in inspect.getmembers(parsed, predicate=inspect.ismethod):
        if name.startswith("get_"):
            value = method()
            if isinstance(value, Enum):
                value = value.name.lower()
            if value is not None:
                data[name[4:]] = value
    return data


class SerialDecoder:
    """
    Desencripta las líneas que manda el ESP32 (ver esp32_victron_scan/) por
    USB serial: `MAC=... RSSI=... LEN=... DATA=<hex>`. Mismo desencriptado
    que VictronScanner pero sin escuchar Bluetooth directo — para equipos
    (como la Red Pitaya) sin soporte de BLE propio.
    """

    def __init__(self, device_keys: dict):
        self._device_keys = {k.lower(): v for k, v in device_keys.items()}
        self._known_devices = {}

    def procesar_linea(self, linea: str):
        """Devuelve (address, rssi, data) o None si la línea no aporta nada."""
        m = LINEA_SERIAL_RE.search(linea)
        if not m:
            return None

        address = m.group(1).lower()
        if address not in self._device_keys:
            return None

        rssi = int(m.group(2))

        # Línea recibida por USB serial del ESP32 — puede llegar cortada o
        # con bits corruptos (timeout de pyserial a mitad de un byte hex,
        # firmware de un modelo mas nuevo con codigos que esta version de
        # victron-ble no reconoce). Cualquiera de estos errores significa
        # "la linea no aporta nada", igual que un LINEA_SERIAL_RE que no
        # matchea — no que haya que tirar abajo el proceso entero.
        try:
            raw = bytes.fromhex(m.group(4))
            # Los primeros 2 bytes son el Company ID (0x02E1); victron-ble
            # espera el payload sin eso, igual que bleak se lo entrega.
            payload = raw[2:]

            if address not in self._known_devices:
                device_klass = detect_device_type(payload)
                if not device_klass:
                    return None
                self._known_devices[address] = device_klass(self._device_keys[address])

            parsed = self._known_devices[address].parse(payload)
        except (struct.error, ValueError, AdvertisementKeyMismatchError,
                AdvertisementKeyMissingError, UnknownDeviceError):
            return None

        return address, rssi, parsed_to_dict(parsed)


def __getattr__(name):
    # Import diferido: BaseScanner (y por lo tanto bleak) solo hace falta
    # para quien realmente escucha Bluetooth en vivo (leer_smartsolar.py,
    # publicar_losant.py). leer_smartsolar_serial.py solo usa
    # parsed_to_dict y no debe arrastrar bleak (pesado de compilar en ARM
    # sin wheel precompilado, ver esp32_victron_scan/).
    if name != "VictronScanner":
        raise AttributeError(name)

    from victron_ble.scanner import BaseScanner

    class VictronScanner(BaseScanner):
        """
        BaseScanner escucha todos los anuncios Bluetooth del aire y se queda
        solo con los que traen el Company ID 0x02E1 (Victron Energy). Esta
        clase además filtra por las direcciones en device_keys y llama a
        on_data(address, ble_device, advertisement, data) con los valores ya
        desencriptados.
        """

        def __init__(self, device_keys: dict, on_data):
            super().__init__()
            # Direcciones MAC en minúscula -> clave de encriptación.
            self._device_keys = {k.lower(): v for k, v in device_keys.items()}
            # Una vez identificado el modelo de un dispositivo, queda guardado el
            # decodificador ya armado con su clave, para no rearmarlo en cada
            # anuncio (el modelo no cambia).
            self._known_devices = {}
            self._on_data = on_data

        def callback(self, ble_device, raw_data, advertisement):
            address = ble_device.address.lower()

            # Se ignora cualquier equipo Victron que no sea el buscado (por si
            # hay más de uno cerca y no está en config.py).
            if address not in self._device_keys:
                return

            if address not in self._known_devices:
                # El paquete cifrado trae, sin descifrar, un byte que indica el
                # tipo de producto (MPPT, BMV, shunt, etc.). detect_device_type
                # lee ese byte y elige la clase Python que sabe interpretar los
                # campos de ESE modelo.
                device_klass = detect_device_type(raw_data)
                if not device_klass:
                    return
                self._known_devices[address] = device_klass(self._device_keys[address])

            try:
                # parse() desencripta el payload (AES-CTR con la clave de 16
                # bytes) y separa los campos (voltaje, corriente, etc.)
                parsed = self._known_devices[address].parse(raw_data)
            except AdvertisementKeyMissingError:
                # La clave en config.py no es la correcta para este dispositivo.
                return
            except UnknownDeviceError:
                # Se descifró pero el modelo no tiene parser conocido en esta
                # versión de victron-ble.
                return

            data = parsed_to_dict(parsed)
            self._on_data(address, ble_device, advertisement, data)

    return VictronScanner
