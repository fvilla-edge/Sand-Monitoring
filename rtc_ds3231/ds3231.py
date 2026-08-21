"""Lectura/escritura del RTC DS3231 por I2C via smbus2. Sin dependencias del proyecto."""

import datetime

from smbus2 import SMBus

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
    except OSError:
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


def abrir_bus(numero):
    return SMBus(numero)
