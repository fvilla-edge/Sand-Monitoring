"""
Escaneo Bluetooth compartido para dispositivos Victron (Instant Readout).
Centraliza la detección de modelo, desencriptado y armado de los datos en
un diccionario, para que cada script (mostrar por pantalla, publicar por
MQTT, etc.) solo se ocupe de qué hacer con esos datos.
"""

import inspect
from enum import Enum

from victron_ble.devices import DeviceData, detect_device_type
from victron_ble.exceptions import AdvertisementKeyMissingError, UnknownDeviceError


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
