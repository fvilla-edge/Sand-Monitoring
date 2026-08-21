#!/usr/bin/env python3
"""Prueba aislada del RTC DS3231 por I2C. No toca systemd, ntpsec ni nada mas del sistema."""

import argparse
import datetime
import sys

try:
    import ds3231
except ImportError:
    print("ERROR: no se encontro ds3231.py (debe estar en la misma carpeta)", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, default=0, help="numero de bus I2C (default: 0)")
    parser.add_argument("--addr", type=lambda x: int(x, 0), default=0x68,
                         help="direccion I2C del DS3231 (default: 0x68)")
    parser.add_argument("--set", action="store_true",
                         help="escribir la hora actual del sistema al RTC antes de leer")
    args = parser.parse_args()

    with ds3231.abrir_bus(args.bus) as bus:
        if not ds3231.detectar(bus, args.addr):
            print(f"ERROR: no se detecto el DS3231 en bus {args.bus} direccion 0x{args.addr:02x}. "
                  f"Revisar cableado (VCC/GND/SDA/SCL) y 'i2cdetect -y {args.bus}'.", file=sys.stderr)
            sys.exit(1)
        print(f"DS3231 detectado en bus {args.bus}, direccion 0x{args.addr:02x}")

        if args.set:
            ahora = datetime.datetime.now()
            ds3231.escribir_hora(bus, args.addr, ahora)
            print(f"Hora del sistema escrita al RTC: {ahora.isoformat(timespec='seconds')}")

        hora_rtc = ds3231.leer_hora(bus, args.addr)
        hora_sistema = datetime.datetime.now()
        diferencia = abs((hora_rtc - hora_sistema).total_seconds())

        print(f"Hora del RTC:      {hora_rtc.isoformat(timespec='seconds')}")
        print(f"Hora del sistema:  {hora_sistema.isoformat(timespec='seconds')}")
        print(f"Diferencia:        {diferencia:.1f} s")

        temperatura = ds3231.leer_temperatura(bus, args.addr)
        print(f"Temperatura interna del DS3231: {temperatura:.2f} C")

        if diferencia > 2:
            print("ADVERTENCIA: diferencia mayor a 2s entre RTC y sistema.", file=sys.stderr)


if __name__ == "__main__":
    main()
