#!/usr/bin/env python3
"""
capturar_campo.py — Paso 1: captura un unico chunk de senal cruda.
Campo: Red Pitaya STEMlab 125-14 + VS150-RI, guarda HDF5 en storage externo.

Uso:
  python3 capturar_campo.py --condicion reposo
  python3 capturar_campo.py --condicion con_arena --decimacion 64 --duracion 5
  python3 capturar_campo.py --condicion reposo --directorio /mnt/usb
"""
import sys
import time
import argparse
import datetime
import math
import os

import numpy as np
import h5py

sys.path.insert(0, '/opt/redpitaya/lib/python')
import rp

FS_BASE  = 125_000_000   # Hz — clock base Red Pitaya
BUF_SIZE = 16_384        # muestras por buffer (fijo en hardware)
CANAL    = rp.RP_CH_1
DCPL     = rp.RP_DC
GAIN     = rp.RP_GAIN_5X  # HV jumper -> +/- 20 V
SENSOR   = 'VS150-RI'

DEC_MAP = {
    1:  rp.RP_DEC_1,
    2:  rp.RP_DEC_2,
    4:  rp.RP_DEC_4,
    8:  rp.RP_DEC_8,
    16: rp.RP_DEC_16,
    32: rp.RP_DEC_32,
    64: rp.RP_DEC_64,
}


def _adquirir_chunk(dec_enum, n_buffers):
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(dec_enum)
    rp.rp_AcqSetAC_DC(CANAL, DCPL)
    rp.rp_AcqSetGain(CANAL, GAIN)
    rp.rp_AcqSetTriggerDelay(0)

    buf_np    = np.zeros(BUF_SIZE, dtype=np.float32)
    segmentos = []

    for i in range(n_buffers):
        rp.rp_AcqStart()
        time.sleep(0.005)
        rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_NOW)

        while not rp.rp_AcqGetBufferFillState()[1]:
            pass

        rp.rp_AcqGetOldestDataVNP(CANAL, buf_np)
        segmentos.append(buf_np.copy())

        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{n_buffers} buffers capturados', flush=True)

    return np.concatenate(segmentos)


def capturar_chunk(condicion, decimacion, duracion_s, directorio):
    if decimacion not in DEC_MAP:
        sys.exit(f'Error: decimacion {decimacion} no valida. Opciones: {sorted(DEC_MAP)}')

    fs_ef         = FS_BASE / decimacion
    n_buffers     = math.ceil(duracion_s * fs_ef / BUF_SIZE)
    duracion_real = n_buffers * BUF_SIZE / fs_ef

    ts    = datetime.datetime.now()
    ts_s  = ts.strftime('%Y%m%d_%H%M%S')
    fname = os.path.join(directorio, f'campo_{condicion}_{ts_s}.h5')

    print(f'\n=== CAPTURA CAMPO ===')
    print(f'  condicion   : {condicion}')
    print(f'  decimacion  : {decimacion}  ->  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  duracion    : {duracion_real:.3f} s  ({n_buffers} buffers)')
    print(f'  muestras    : {n_buffers * BUF_SIZE:,}')
    print(f'  archivo     : {fname}\n')

    rp.rp_Init()
    try:
        senal = _adquirir_chunk(DEC_MAP[decimacion], n_buffers)
    finally:
        rp.rp_Release()

    print('Guardando HDF5...', flush=True)
    with h5py.File(fname, 'w') as f:
        f.create_dataset('raw_signal', data=senal,
                         compression='gzip', compression_opts=1)
        f.attrs.update({
            'condicion':  condicion,
            'sensor':     SENSOR,
            'decimacion': decimacion,
            'fs_base_hz': FS_BASE,
            'fs_ef_hz':   fs_ef,
            'n_muestras': len(senal),
            'n_buffers':  n_buffers,
            'duracion_s': duracion_real,
            'fecha':      ts.strftime('%Y-%m-%d %H:%M:%S'),
            'gain':       'HV_20V',
        })

    size_mb = os.path.getsize(fname) / 1e6
    print(f'\n[OK] {fname}  ({size_mb:.1f} MB)')
    return fname


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Captura campo — chunk unico de senal cruda')
    p.add_argument('--condicion',  required=True, choices=['reposo', 'con_arena'],
                   help='Condicion actual: reposo (sin arena) o con_arena')
    p.add_argument('--decimacion', type=int, default=32,
                   help='Factor de decimacion (default: 32 -> 3.906 MHz)')
    p.add_argument('--duracion',   type=float, default=10.0,
                   help='Duracion del chunk en segundos (default: 10)')
    p.add_argument('--directorio', default='/mnt/usb',
                   help='Directorio de salida, ej. /mnt/usb (default: /mnt/usb)')
    args = p.parse_args()

    os.makedirs(args.directorio, exist_ok=True)
    capturar_chunk(args.condicion, args.decimacion, args.duracion, args.directorio)
