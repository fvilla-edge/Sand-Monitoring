#!/usr/bin/env python3
"""
capturar_campo.py — Loop continuo de captura raw con escritura en streaming.
Campo: Red Pitaya STEMlab 125-14 + VS150-RI, guarda HDF5 en storage externo.

Uso:
  # Corre indefinidamente hasta Ctrl+C, chunks de 1 minuto
  python3 capturar_campo.py --condicion reposo

  # 2 horas total, chunks de 10 minutos
  python3 capturar_campo.py --condicion con_arena --duracion_total 120 --duracion_chunk 10

  # Cambia decimacion y directorio
  python3 capturar_campo.py --condicion reposo --decimacion 64 --directorio /mnt/usb
"""
import sys
import time
import argparse
import datetime
import math
import os
import signal
import shutil
import threading
import queue

import numpy as np
import h5py

sys.path.insert(0, '/opt/redpitaya/lib/python')
import rp

FS_BASE      = 125_000_000   # Hz — clock base Red Pitaya
BUF_SIZE     = 16_384        # muestras por buffer (fijo en hardware)
WRITE_BLOCK  = 256           # buffers hardware por bloque de escritura (~1s a dec=32)
ESPACIO_MIN  = 200 * 1024 * 1024  # 200 MB — detiene la captura si queda menos
CANAL  = rp.RP_CH_1
DCPL   = rp.RP_DC
GAIN   = rp.RP_GAIN_5X
SENSOR = 'VS150-RI'

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

def _handle_stop(sig, frame):
    global _stop
    _stop = True
    print('\n[!] Señal recibida — cerrando chunk actual y deteniendo...', flush=True)

signal.signal(signal.SIGINT,  _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)


def _configurar_adc(dec_enum):
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(dec_enum)
    rp.rp_AcqSetAC_DC(CANAL, DCPL)
    rp.rp_AcqSetGain(CANAL, GAIN)
    rp.rp_AcqSetTriggerDelay(0)


def _capturar_buffer(buf_np):
    rp.rp_AcqStart()
    rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_NOW)
    while not rp.rp_AcqGetBufferFillState()[1]:
        pass
    rp.rp_AcqGetOldestDataVNP(CANAL, buf_np)


def _capturar_chunk_streaming(condicion, dec_enum, decimacion, fs_ef,
                               n_buffers, fname, chunk_num, usar_compresion=False):
    """Captura n_buffers con escritura HDF5 en thread separado (doble buffer).

    El thread writer escribe mientras capture llena el siguiente bloque.
    Con sin-compresion el writer termina en ~350ms vs ~1900ms de captura,
    así que nunca bloquea la captura. Eficiencia esperada: ~57%.
    """
    H5_CHUNK = WRITE_BLOCK * BUF_SIZE  # 4,194,304 muestras = 16 MB float32
    ts = datetime.datetime.now()

    buf_np = np.zeros(BUF_SIZE, dtype=np.float32)

    # Pool de 3 buffers numpy pre-asignados.
    # Capture llena uno, writer escribe otro, tercero de reserva.
    # Con write (351ms) << capture (1897ms), free_q nunca bloquea.
    N_BUFS = 3
    pool    = [np.zeros(H5_CHUNK, dtype=np.float32) for _ in range(N_BUFS)]
    free_q  = queue.SimpleQueue()
    write_q = queue.SimpleQueue()
    for b in pool:
        free_q.put(b)

    write_err   = [None]
    write_total = [0]  # muestras escritas a disco (actualizado por writer)

    def writer():
        try:
            with h5py.File(fname, 'w') as f:
                comp_kw = {'compression': 'gzip', 'compression_opts': 1} if usar_compresion else {}
                ds = f.create_dataset(
                    'raw_signal',
                    shape=(0,), maxshape=(None,),
                    dtype=np.float32,
                    chunks=(H5_CHUNK,),
                    **comp_kw,
                )
                while True:
                    item = write_q.get()
                    if item is None:
                        break
                    data, size = item
                    offset    = write_total[0]
                    nuevo_len = offset + size
                    ds.resize((nuevo_len,))
                    ds[offset:nuevo_len] = data if size == H5_CHUNK else data[:size]
                    f.flush()
                    write_total[0] += size
                    free_q.put(data)   # devolver buffer al pool

                duracion_real = write_total[0] / fs_ef
                f.attrs.update({
                    'condicion':   condicion,
                    'sensor':      SENSOR,
                    'decimacion':  decimacion,
                    'fs_base_hz':  FS_BASE,
                    'fs_ef_hz':    fs_ef,
                    'n_muestras':  write_total[0],
                    'duracion_s':  duracion_real,
                    'chunk_num':   chunk_num,
                    'fecha':       ts.strftime('%Y-%m-%d %H:%M:%S'),
                    'gain':        'HV_20V',
                    'compresion':  'gzip-1' if usar_compresion else 'ninguna',
                })
        except Exception as e:
            write_err[0] = e

    t_writer = threading.Thread(target=writer, daemon=True)
    t_writer.start()

    buf_idx    = 0
    n_enviados = 0
    active     = free_q.get()   # tomar primer buffer del pool
    t_inicio   = time.perf_counter()

    _configurar_adc(dec_enum)

    try:
        for i in range(n_buffers):
            if _stop:
                break
            if write_err[0]:
                raise write_err[0]

            _capturar_buffer(buf_np)
            active[buf_idx * BUF_SIZE:(buf_idx + 1) * BUF_SIZE] = buf_np
            buf_idx += 1

            if buf_idx == WRITE_BLOCK:
                write_q.put((active, H5_CHUNK))
                n_enviados += 1
                active  = free_q.get()   # obtener buffer libre (casi nunca bloquea)
                buf_idx = 0

                senal_s    = n_enviados * H5_CHUNK / fs_ef
                reloj_s    = time.perf_counter() - t_inicio
                eficiencia = senal_s / reloj_s * 100
                print(f'  chunk {chunk_num:04d} | señal {senal_s:.1f}s '
                      f'| reloj {reloj_s:.1f}s | eficiencia {eficiencia:.0f}%',
                      flush=True)

    finally:
        if buf_idx > 0 and not write_err[0]:
            write_q.put((active, buf_idx * BUF_SIZE))
        else:
            free_q.put(active)   # devolver buffer no usado

        write_q.put(None)        # sentinel: writer cierra el archivo
        t_writer.join()

        if write_err[0]:
            raise write_err[0]

    reloj_total    = time.perf_counter() - t_inicio
    total_muestras = write_total[0]
    duracion_real  = total_muestras / fs_ef
    eficiencia     = duracion_real / reloj_total * 100 if reloj_total > 0 else 0
    size_mb        = os.path.getsize(fname) / 1e6
    print(f'  [OK] {os.path.basename(fname)}  '
          f'({duracion_real:.1f}s señal | {reloj_total:.1f}s reloj | '
          f'{eficiencia:.0f}% eficiencia | {size_mb:.1f} MB)',
          flush=True)
    return total_muestras


def main():
    p = argparse.ArgumentParser(description='Captura campo — loop continuo streaming')
    p.add_argument('--condicion',      required=True, choices=['reposo', 'con_arena'])
    p.add_argument('--decimacion',     type=int,   default=32,
                   help='Factor de decimacion (default: 32 -> 3.906 MHz)')
    p.add_argument('--duracion_chunk', type=float, default=1.0,
                   help='Minutos por chunk/archivo (default: 1)')
    p.add_argument('--duracion_total', type=float, default=None,
                   help='Duracion total de la sesion en minutos. Sin limite si no se indica.')
    p.add_argument('--directorio',     default='/mnt/usb',
                   help='Directorio de salida (default: /mnt/usb)')
    p.add_argument('--compresion',     action='store_true', default=False,
                   help='Activar compresion gzip-1 (menor tamaño, menor eficiencia)')
    args = p.parse_args()

    if args.decimacion not in DEC_MAP:
        sys.exit(f'Error: decimacion {args.decimacion} no valida. Opciones: {sorted(DEC_MAP)}')

    dec_enum         = DEC_MAP[args.decimacion]
    fs_ef            = FS_BASE / args.decimacion
    chunk_s          = args.duracion_chunk * 60.0
    total_s          = args.duracion_total * 60.0 if args.duracion_total else None
    n_buffers_chunk  = math.ceil(chunk_s * fs_ef / BUF_SIZE)

    os.makedirs(args.directorio, exist_ok=True)

    print(f'\n=== CAPTURA CAMPO — LOOP CONTINUO ===')
    print(f'  condicion      : {args.condicion}')
    print(f'  decimacion     : {args.decimacion}  ->  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  compresion     : {"gzip-1" if args.compresion else "ninguna (mas eficiente)"}')
    print(f'  duracion chunk : {args.duracion_chunk} min  ({n_buffers_chunk} buffers)')
    if total_s:
        n_chunks_est = math.ceil(total_s / chunk_s)
        print(f'  duracion total : {args.duracion_total} min  (~{n_chunks_est} chunks)')
    else:
        print(f'  duracion total : indefinida  (Ctrl+C para detener)')
    print(f'  directorio     : {args.directorio}')
    print(f'  Presiona Ctrl+C para detener ordenadamente.\n')

    rp.rp_Init()

    chunk_num        = 1
    tiempo_capturado = 0.0

    try:
        while not _stop:
            # Chequeamos si ya llegamos al tiempo total
            if total_s and tiempo_capturado >= total_s:
                print('\n[OK] Tiempo total de sesion alcanzado.')
                break

            # Chequeamos espacio disponible en el storage
            libre = shutil.disk_usage(args.directorio).free
            if libre < ESPACIO_MIN:
                print(f'\n[!] Espacio insuficiente ({libre / 1e6:.0f} MB libres). Deteniendo.')
                break

            # Calculamos cuantos buffers para este chunk
            # (puede ser menor en el ultimo si hay duracion_total)
            if total_s:
                tiempo_restante = total_s - tiempo_capturado
                n_buf = min(n_buffers_chunk,
                            math.ceil(tiempo_restante * fs_ef / BUF_SIZE))
            else:
                n_buf = n_buffers_chunk

            ts_s  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = os.path.join(
                args.directorio,
                f'campo_{args.condicion}_{ts_s}_{chunk_num:04d}.h5'
            )

            print(f'\n--- Chunk {chunk_num:04d} | {libre / 1e9:.2f} GB libres ---', flush=True)

            muestras = _capturar_chunk_streaming(
                args.condicion, dec_enum, args.decimacion, fs_ef,
                n_buf, fname, chunk_num,
                usar_compresion=args.compresion,
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
