"""
Resuelve qué puerto serial usar para hablar con el ESP32 puente BLE→USB.

Antes se usaba /dev/ttyACM0 a secas, pero ese nombre lo asigna el kernel
por orden de enumeración: si el día de mañana hay otro dispositivo serial
USB conectado a la misma placa, ttyACM0 puede terminar siendo el otro
dispositivo y no el ESP32.

Se resuelve en cambio por VID:PID (303a:1001, "Espressif USB JTAG/serial
debug unit", genérico a cualquier ESP32-C3 en modo USB-CDC) vía el symlink
que udev arma solo en /dev/serial/by-id/ — confirmado en la placa real.
No depende del número de serie (MAC) de este módulo puntual, así que sigue
sirviendo si se reemplaza el ESP32 por otro.
"""

import glob
import sys

_PATRON_BY_ID = "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_*-if00"
_FALLBACK = "/dev/ttyACM0"


def resolver_puerto():
    """Puerto pasado por línea de comandos, o resuelto por VID:PID, o el fallback."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    encontrados = sorted(glob.glob(_PATRON_BY_ID))
    return encontrados[0] if encontrados else _FALLBACK
