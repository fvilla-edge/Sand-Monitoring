#!/usr/bin/env python3
"""
test_dual_adc.py — Verificacion doble canal ADC, solo consola, sin guardar.
Paso 1 etapa dual: confirmar que IN1 (CH1) e IN2 (CH2) capturan correctamente.

Uso:
  python3 test_dual_adc.py
  python3 test_dual_adc.py --decimacion 32 --intervalo 5

Conectar:
  IN1 -> sensor codo (medicion)
  IN2 -> sensor referencia (ruido de linea)
"""
import sys
import time
import argparse
import signal

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
import rp

FS_BASE  = 125_000_000
BUF_SIZE = 16_384
DCPL     = rp.RP_DC
GAIN     = rp.RP_GAIN_5X

DEC_MAP = {
    1:  rp.RP_DEC_1,
    2:  rp.RP_DEC_2,
    4:  rp.RP_DEC_4,
    8:  rp.RP_DEC_8,
    16: rp.RP_DEC_16,
    32: rp.RP_DEC_32,
    64: rp.RP_DEC_64,
}

_stop = False

def _handle_sigint(sig, frame):
    global _stop
    _stop = True
    print('\n[!] Ctrl+C — deteniendo...', flush=True)

signal.signal(signal.SIGINT, _handle_sigint)


def _configurar_ambos(dec_enum):
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(dec_enum)
    for ch in (rp.RP_CH_1, rp.RP_CH_2):
        rp.rp_AcqSetAC_DC(ch, DCPL)
        rp.rp_AcqSetGain(ch, GAIN)
    rp.rp_AcqSetTriggerDelay(0)


def _capturar_buffer(buf1, buf2):
    rp.rp_AcqStart()
    time.sleep(0.005)
    rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_NOW)
    while not rp.rp_AcqGetBufferFillState()[1]:
        pass
    rp.rp_AcqGetOldestDataVNP(rp.RP_CH_1, buf1)
    rp.rp_AcqGetOldestDataVNP(rp.RP_CH_2, buf2)


def _stats(arr):
    rms = float(np.sqrt(np.mean(arr**2)))
    pico = float(np.max(np.abs(arr)))
    return rms, pico


def main():
    p = argparse.ArgumentParser(description='Test doble ADC — solo consola')
    p.add_argument('--decimacion', type=int, default=32,
                   help='Factor de decimacion (default: 32 -> 3.9 MHz)')
    p.add_argument('--intervalo',  type=int, default=10,
                   help='Buffers entre cada impresion (default: 10)')
    args = p.parse_args()

    if args.decimacion not in DEC_MAP:
        sys.exit(f'Decimacion {args.decimacion} no valida. Opciones: {sorted(DEC_MAP)}')

    dec_enum = DEC_MAP[args.decimacion]
    fs_ef    = FS_BASE / args.decimacion

    buf1 = np.zeros(BUF_SIZE, dtype=np.float32)
    buf2 = np.zeros(BUF_SIZE, dtype=np.float32)

    rp.rp_Init()
    _configurar_ambos(dec_enum)

    print(f'\n=== TEST DOBLE ADC ===')
    print(f'  decimacion : {args.decimacion}  ->  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  intervalo  : imprime cada {args.intervalo} buffers')
    print(f'  CH1 = IN1  (sensor codo / medicion)')
    print(f'  CH2 = IN2  (sensor referencia / ruido de linea)')
    print(f'  Ctrl+C para detener\n')
    print(f"{'Buf':>6}  {'--- CH1 (codo) ---':^23}  {'--- CH2 (ref) ---':^23}")
    print(f"{'':>6}  {'RMS [V]':>10}  {'Pico [V]':>10}  {'RMS [V]':>10}  {'Pico [V]':>10}")
    print('-' * 62)

    n = 0
    try:
        while not _stop:
            _capturar_buffer(buf1, buf2)
            n += 1

            if n % args.intervalo == 0:
                r1, p1 = _stats(buf1)
                r2, p2 = _stats(buf2)
                print(f'{n:>6}  {r1:>10.5f}  {p1:>10.5f}  {r2:>10.5f}  {p2:>10.5f}',
                      flush=True)
    finally:
        rp.rp_Release()
        print(f'\nTotal buffers capturados: {n}')


if __name__ == '__main__':
    main()
