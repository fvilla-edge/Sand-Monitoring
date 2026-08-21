#!/usr/bin/env python3
"""Prueba aislada del RTC DS3231 por I2C. No toca systemd, ntpsec ni nada mas del sistema."""

import argparse
import datetime
import sys

try:
    from smbus2 import SMBus
except ImportError:
    print("ERROR: falta el modulo 'smbus2' (python3 -m pip install smbus2)", file=sys.stderr)
    sys.exit(1)

REG_SECONDS = 0x00
REG_MINUTES = 0x01
REG_HOURS = 0x02
REG_DAY = 0x03
REG_DATE = 0x04
REG_MONTH = 0x05
REG_YEAR = 0x06
REG_TEMP_MSB = 0x11
REG_TEMP_LSB = 0x12


def bcd_a_dec(valor):
    return (valor // 16) * 10 + (valor % 16)


def dec_a_bcd(valor):
    return (valor // 10) * 16 + (valor % 10)


def detectar(bus, addr):
    try:
        bus.read_byte_data(addr, REG_SECONDS)
    except OSError as e:
        print(f"ERROR: no se detecto el DS3231 en bus {bus.channel if hasattr(bus, 'channel') else '?'} "
              f"direccion 0x{addr:02x} ({e}). Revisar cableado (VCC/GND/SDA/SCL) y 'i2cdetect -y <bus>'.",
              file=sys.stderr)
        return False
    return True


def leer_hora(bus, addr):
    datos = bus.read_i2c_block_data(addr, REG_SECONDS, 7)
    segundos = bcd_a_dec(datos[0] & 0x7F)
    minutos = bcd_a_dec(datos[1] & 0x7F)
    horas = bcd_a_dec(datos[2] & 0x3F)
    dia_mes = bcd_a_dec(datos[4] & 0x3F)
    mes = bcd_a_dec(datos[5] & 0x1F)
    anio = 2000 + bcd_a_dec(datos[6])
    return datetime.datetime(anio, mes, dia_mes, horas, minutos, segundos)


def escribir_hora(bus, addr, momento):
    datos = [
        dec_a_bcd(momento.second),
        dec_a_bcd(momento.minute),
        dec_a_bcd(momento.hour),
        dec_a_bcd(momento.isoweekday()),
        dec_a_bcd(momento.day),
        dec_a_bcd(momento.month),
        dec_a_bcd(momento.year - 2000),
    ]
    bus.write_i2c_block_data(addr, REG_SECONDS, datos)


def leer_temperatura(bus, addr):
    msb = bus.read_byte_data(addr, REG_TEMP_MSB)
    lsb = bus.read_byte_data(addr, REG_TEMP_LSB)
    entero = msb if msb < 128 else msb - 256
    fraccion = (lsb >> 6) * 0.25
    return entero + fraccion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, default=1, help="numero de bus I2C (default: 1)")
    parser.add_argument("--addr", type=lambda x: int(x, 0), default=0x68,
                         help="direccion I2C del DS3231 (default: 0x68)")
    parser.add_argument("--set", action="store_true",
                         help="escribir la hora actual del sistema al RTC antes de leer")
    args = parser.parse_args()

    with SMBus(args.bus) as bus:
        if not detectar(bus, args.addr):
            sys.exit(1)
        print(f"DS3231 detectado en bus {args.bus}, direccion 0x{args.addr:02x}")

        if args.set:
            ahora = datetime.datetime.now()
            escribir_hora(bus, args.addr, ahora)
            print(f"Hora del sistema escrita al RTC: {ahora.isoformat(timespec='seconds')}")

        hora_rtc = leer_hora(bus, args.addr)
        hora_sistema = datetime.datetime.now()
        diferencia = abs((hora_rtc - hora_sistema).total_seconds())

        print(f"Hora del RTC:      {hora_rtc.isoformat(timespec='seconds')}")
        print(f"Hora del sistema:  {hora_sistema.isoformat(timespec='seconds')}")
        print(f"Diferencia:        {diferencia:.1f} s")

        temperatura = leer_temperatura(bus, args.addr)
        print(f"Temperatura interna del DS3231: {temperatura:.2f} C")

        if diferencia > 2:
            print("ADVERTENCIA: diferencia mayor a 2s entre RTC y sistema.", file=sys.stderr)


if __name__ == "__main__":
    main()
