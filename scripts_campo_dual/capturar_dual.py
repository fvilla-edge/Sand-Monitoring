#!/usr/bin/env python3
"""
capturar_dual.py — Loop continuo de captura DUAL canal con escritura en streaming.
CH1 (IN1, sensor codo) + CH2 (IN2, sensor referencia) guardados sincronicos en HDF5.

Uso:
  python3 capturar_dual.py --condicion reposo
  python3 capturar_dual.py --condicion con_arena --duracion_total 30 --duracion_chunk 2
  python3 capturar_dual.py --condicion reposo --directorio /mnt/usb

Conectar:
  IN1 -> CH1 -> sensor codo (medicion)
  IN2 -> CH2 -> sensor referencia (ruido de linea)
"""
import sys
import time
import argparse
import datetime
import math
import os
import signal
import shutil

import numpy as np
import h5py

sys.path.insert(0, '/opt/redpitaya/lib/python')
import rp

FS_BASE     = 125_000_000
BUF_SIZE    = 16_384
WRITE_BLOCK = 256
ESPACIO_MIN = 400 * 1024 * 1024  # 400 MB minimo — doble que campo simple (dos canales)
DCPL        = rp.RP_DC
GAIN        = rp.RP_GAIN_5X
SENSOR      = 'VS150-RI'

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
    print('\n[!] Ctrl+C recibido — cerrando chunk actual y deteniendo...', flush=True)

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


def _capturar_chunk_streaming(condicion, dec_enum, decimacion, fs_ef,
                               n_buffers, fname, chunk_num):
    h5_chunk_size = WRITE_BLOCK * BUF_SIZE
    ts = datetime.datetime.now()

    buf1 = np.zeros(BUF_SIZE,      dtype=np.float32)
    buf2 = np.zeros(BUF_SIZE,      dtype=np.float32)
    blq1 = np.zeros(h5_chunk_size, dtype=np.float32)
    blq2 = np.zeros(h5_chunk_size, dtype=np.float32)
    buf_idx        = 0
    total_muestras = 0

    _configurar_ambos(dec_enum)

    with h5py.File(fname, 'w') as f:
        ds1 = f.create_dataset(
            'raw_ch1',
            shape=(0,), maxshape=(None,),
            dtype=np.float32,
            chunks=(h5_chunk_size,),
            compression='gzip', compression_opts=1,
        )
        ds2 = f.create_dataset(
            'raw_ch2',
            shape=(0,), maxshape=(None,),
            dtype=np.float32,
            chunks=(h5_chunk_size,),
            compression='gzip', compression_opts=1,
        )

        for i in range(n_buffers):
            if _stop:
                break

            _capturar_buffer(buf1, buf2)
            blq1[buf_idx * BUF_SIZE:(buf_idx + 1) * BUF_SIZE] = buf1
            blq2[buf_idx * BUF_SIZE:(buf_idx + 1) * BUF_SIZE] = buf2
            buf_idx += 1

            if buf_idx == WRITE_BLOCK:
                nuevo_len = total_muestras + h5_chunk_size
                ds1.resize((nuevo_len,))
                ds2.resize((nuevo_len,))
                ds1[total_muestras:nuevo_len] = blq1
                ds2[total_muestras:nuevo_len] = blq2
                f.flush()
                total_muestras = nuevo_len
                buf_idx = 0
                elapsed = total_muestras / fs_ef
                print(f'  chunk {chunk_num:04d} | {elapsed:.1f} s capturados', flush=True)

        # Vuelca lo que quedo en el bloque parcial
        if buf_idx > 0:
            restantes = buf_idx * BUF_SIZE
            nuevo_len = total_muestras + restantes
            ds1.resize((nuevo_len,))
            ds2.resize((nuevo_len,))
            ds1[total_muestras:nuevo_len] = blq1[:restantes]
            ds2[total_muestras:nuevo_len] = blq2[:restantes]
            f.flush()
            total_muestras = nuevo_len

        duracion_real = total_muestras / fs_ef
        f.attrs.update({
            'condicion':   condicion,
            'sensor':      SENSOR,
            'decimacion':  decimacion,
            'fs_base_hz':  FS_BASE,
            'fs_ef_hz':    fs_ef,
            'n_muestras':  total_muestras,
            'duracion_s':  duracion_real,
            'chunk_num':   chunk_num,
            'fecha':       ts.strftime('%Y-%m-%d %H:%M:%S'),
            'gain':        'HV_20V',
            'canal_ch1':   'IN1 — sensor codo (medicion)',
            'canal_ch2':   'IN2 — sensor referencia (ruido de linea)',
        })

    size_mb = os.path.getsize(fname) / 1e6
    print(f'  [OK] {os.path.basename(fname)}  '
          f'({duracion_real:.2f} s | {total_muestras:,} muestras x2 | {size_mb:.1f} MB)',
          flush=True)
    return total_muestras


def main():
    p = argparse.ArgumentParser(description='Captura dual CH1+CH2 — loop continuo streaming')
    p.add_argument('--condicion',      required=True, choices=['reposo', 'con_arena'])
    p.add_argument('--decimacion',     type=int,   default=32,
                   help='Factor de decimacion (default: 32 -> 3.906 MHz)')
    p.add_argument('--duracion_chunk', type=float, default=1.0,
                   help='Minutos por chunk/archivo (default: 1)')
    p.add_argument('--duracion_total', type=float, default=None,
                   help='Duracion total en minutos. Sin limite si no se indica.')
    p.add_argument('--directorio',     default='/mnt/usb',
                   help='Directorio de salida (default: /mnt/usb)')
    args = p.parse_args()

    if args.decimacion not in DEC_MAP:
        sys.exit(f'Error: decimacion {args.decimacion} no valida. Opciones: {sorted(DEC_MAP)}')

    dec_enum        = DEC_MAP[args.decimacion]
    fs_ef           = FS_BASE / args.decimacion
    chunk_s         = args.duracion_chunk * 60.0
    total_s         = args.duracion_total * 60.0 if args.duracion_total else None
    n_buffers_chunk = math.ceil(chunk_s * fs_ef / BUF_SIZE)

    os.makedirs(args.directorio, exist_ok=True)

    print(f'\n=== CAPTURA DUAL CH1+CH2 — LOOP CONTINUO ===')
    print(f'  condicion      : {args.condicion}')
    print(f'  decimacion     : {args.decimacion}  ->  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  duracion chunk : {args.duracion_chunk} min  ({n_buffers_chunk} buffers)')
    if total_s:
        n_chunks_est = math.ceil(total_s / chunk_s)
        print(f'  duracion total : {args.duracion_total} min  (~{n_chunks_est} chunks)')
    else:
        print(f'  duracion total : indefinida  (Ctrl+C para detener)')
    print(f'  directorio     : {args.directorio}')
    print(f'  CH1 = IN1  (sensor codo / medicion)')
    print(f'  CH2 = IN2  (sensor referencia / ruido de linea)')
    print(f'  Storage aprox  : ~{args.duracion_chunk * 432:.0f} MB/chunk  (2 canales a dec={args.decimacion})')
    print(f'  Presiona Ctrl+C para detener ordenadamente.\n')

    rp.rp_Init()

    chunk_num        = 1
    tiempo_capturado = 0.0

    try:
        while not _stop:
            if total_s and tiempo_capturado >= total_s:
                print('\n[OK] Tiempo total de sesion alcanzado.')
                break

            libre = shutil.disk_usage(args.directorio).free
            if libre < ESPACIO_MIN:
                print(f'\n[!] Espacio insuficiente ({libre / 1e6:.0f} MB libres). Deteniendo.')
                break

            if total_s:
                tiempo_restante = total_s - tiempo_capturado
                n_buf = min(n_buffers_chunk,
                            math.ceil(tiempo_restante * fs_ef / BUF_SIZE))
            else:
                n_buf = n_buffers_chunk

            ts_s  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = os.path.join(
                args.directorio,
                f'dual_{args.condicion}_{ts_s}_{chunk_num:04d}.h5'
            )

            print(f'\n--- Chunk {chunk_num:04d} | {libre / 1e9:.2f} GB libres ---', flush=True)

            muestras = _capturar_chunk_streaming(
                args.condicion, dec_enum, args.decimacion, fs_ef,
                n_buf, fname, chunk_num,
            )

            tiempo_capturado += muestras / fs_ef
            chunk_num += 1

    finally:
        rp.rp_Release()
        print(f'\n=== SESION TERMINADA ===')
        print(f'  Chunks guardados  : {chunk_num - 1}')
        print(f'  Tiempo capturado  : {tiempo_capturado/60:.2f} min  ({tiempo_capturado:.0f} s)')
        print(f'  Directorio        : {args.directorio}')


if __name__ == '__main__':
    main()
