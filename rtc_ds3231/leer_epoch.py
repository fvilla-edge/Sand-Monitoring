#!/usr/bin/env python3
"""Imprime por stdout el epoch Unix (UTC) leido del RTC DS3231. Exit!=0 si no responde."""

import argparse
import calendar
import sys

import ds3231


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--addr", type=lambda x: int(x, 0), required=True)
    args = parser.parse_args()

    try:
        with ds3231.abrir_bus(args.bus) as bus:
            if not ds3231.detectar(bus, args.addr):
                print(f"ERROR: no se detecto el DS3231 en bus {args.bus} direccion 0x{args.addr:02x}",
                      file=sys.stderr)
                sys.exit(1)
            hora_rtc = ds3231.leer_hora(bus, args.addr)
    except OSError as e:
        print(f"ERROR: fallo de I2C leyendo el RTC ({e})", file=sys.stderr)
        sys.exit(1)

    print(calendar.timegm(hora_rtc.timetuple()))


if __name__ == "__main__":
    main()
