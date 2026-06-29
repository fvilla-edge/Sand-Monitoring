#!/usr/bin/env python3
"""
test_scpi_adc.py — Test basico ADC via SCPI desde la PC.
Paso 2 etapa SCPI: confirmar que CH1 y CH2 se leen correctamente por red.

Uso:
  .venv/bin/python3 SCPI/test_scpi_adc.py
  .venv/bin/python3 SCPI/test_scpi_adc.py --ip 192.168.0.55 --decimacion 32 --n 10
"""
import sys
import time
import argparse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from redpitaya_scpi_core import scpi

FS_BASE  = 125_000_000
BUF_SIZE = 16_384

DEC_MAP = {1: 1, 2: 2, 4: 4, 8: 8, 16: 16, 32: 32, 64: 64}


def _setup(rp, dec):
    """Configura el ADC una sola vez antes del loop."""
    rp.tx_txt('ACQ:RST')
    rp.tx_txt(f'ACQ:DEC {dec}')
    rp.tx_txt('ACQ:DATA:FORMAT BIN')
    rp.tx_txt('ACQ:DATA:UNITS VOLTS')


def _leer_buffer_dual(rp):
    """Lee un buffer de CH1 y CH2. Requiere _setup() previo."""
    rp.tx_txt('ACQ:START')
    rp.tx_txt('ACQ:TRIG NOW')

    while True:
        rp.tx_txt('ACQ:TRIG:STAT?')
        if rp.rx_txt() == 'TD':
            break

    rp.tx_txt('ACQ:SOUR1:DATA:OLD:N? 16384')
    raw1 = rp.rx_arb()
    rp.tx_txt('ACQ:SOUR2:DATA:OLD:N? 16384')
    raw2 = rp.rx_arb()

    ch1 = np.frombuffer(raw1, dtype='>f4').astype(np.float32)
    ch2 = np.frombuffer(raw2, dtype='>f4').astype(np.float32)
    return ch1, ch2


def _stats(arr):
    rms  = float(np.sqrt(np.mean(arr ** 2)))
    pico = float(np.max(np.abs(arr)))
    return rms, pico


def main():
    p = argparse.ArgumentParser(description='Test ADC dual via SCPI')
    p.add_argument('--ip',         default='192.168.0.55')
    p.add_argument('--decimacion', type=int, default=32)
    p.add_argument('--n',          type=int, default=5,
                   help='Cantidad de buffers a leer (default: 5)')
    args = p.parse_args()

    if args.decimacion not in DEC_MAP:
        sys.exit(f'Decimacion invalida. Opciones: {sorted(DEC_MAP)}')

    fs_ef = FS_BASE / args.decimacion

    print(f'\n=== TEST ADC SCPI ===')
    print(f'  RP IP      : {args.ip}:5000')
    print(f'  decimacion : {args.decimacion}  ->  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  buffers    : {args.n}  ({BUF_SIZE} muestras c/u = {BUF_SIZE/fs_ef*1000:.1f} ms)')
    print()

    rp = scpi(args.ip, timeout=10)
    time.sleep(0.5)
    _setup(rp, args.decimacion)

    print(f"{'Buf':>4}  {'--- CH1 ---':^23}  {'--- CH2 ---':^23}  {'tiempo':>7}")
    print(f"{'':>4}  {'RMS [V]':>10}  {'Pico [V]':>10}  {'RMS [V]':>10}  {'Pico [V]':>10}  {'[ms]':>7}")
    print('-' * 72)

    tiempos = []
    for i in range(args.n):
        t0 = time.perf_counter()
        ch1, ch2 = _leer_buffer_dual(rp)
        dt = (time.perf_counter() - t0) * 1000

        r1, p1 = _stats(ch1)
        r2, p2 = _stats(ch2)
        tiempos.append(dt)

        print(f'{i+1:>4}  {r1:>10.5f}  {p1:>10.5f}  {r2:>10.5f}  {p2:>10.5f}  {dt:>7.1f}')

    rp.close()

    buf_ms   = BUF_SIZE / fs_ef * 1000
    prom_ms  = np.mean(tiempos)
    efic     = buf_ms / prom_ms * 100
    print('-' * 72)
    print(f'\n  Tiempo por buffer: {prom_ms:.1f} ms promedio')
    print(f'  Señal por buffer:  {buf_ms:.1f} ms')
    print(f'  Eficiencia:        {efic:.0f}%  ({prom_ms/buf_ms:.1f}x slower)')


if __name__ == '__main__':
    main()
