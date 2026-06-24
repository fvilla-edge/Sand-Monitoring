#!/usr/bin/env python3
"""
capturar.py — Adquisicion acustica con Red Pitaya STEMlab 125-14 + VS150-RI.
Guarda la senal raw y metricas basicas en un archivo HDF5.

Uso:
  python3 capturar.py --condicion reposo
  python3 capturar.py --condicion baja --masa_g 2.0 --caudal 0.5 --tamanio_mm 0.4
"""
import sys
import time
import argparse
import datetime

import numpy as np
import h5py
from scipy.signal import butter, filtfilt
from scipy.stats import kurtosis as sp_kurtosis

sys.path.insert(0, '/opt/redpitaya/lib/python')
import rp

# ---------------------------------------------------------------------------
# Configuracion de adquisicion
# ---------------------------------------------------------------------------
FS_BASE   = 125_000_000      # Hz — clock base Red Pitaya
DEC_ENUM  = rp.RP_DEC_64     # decimacion 64 -> fs_ef = 1 953 125 Hz
DEC_VAL   = 64
FS_EF     = FS_BASE / DEC_VAL
BUF_SIZE  = 16_384           # muestras por buffer (hardware fijo)
N_BUFFERS = 100              # buffers consecutivos -> ~838 ms de senal total
CANAL     = rp.RP_CH_1
DCPL      = rp.RP_DC
GAIN      = rp.RP_GAIN_5X    # HV jumper -> +/- 20 V rango
SENSOR    = 'VS150-RI'

# Banda del sensor VS150-RI
F_LOW  = 100_000   # Hz
F_HIGH = 450_000   # Hz
ORD    = 4         # orden del filtro Butterworth pasa-banda

UMBRAL_SIGMA = 3.0   # multiplo de sigma para conteo de eventos


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------
def _crear_filtro():
    nyq = FS_EF / 2.0
    return butter(ORD, [F_LOW / nyq, F_HIGH / nyq], btype='band')


def _calcular_metricas(senal, b, a):
    """Filtra en la banda 100-450 kHz y calcula metricas. No genera graficos."""
    sf = filtfilt(b, a, senal.astype(np.float64))

    rms    = float(np.sqrt(np.mean(sf ** 2)))
    energy = float(np.sum(sf ** 2))
    peak   = float(np.max(np.abs(sf)))
    kurt   = float(sp_kurtosis(sf, fisher=False))  # gaussiana pura -> 3.0
    crest  = float(peak / rms) if rms > 1e-12 else 0.0

    thr       = UMBRAL_SIGMA * float(np.std(sf))
    sobre_thr = (np.abs(sf) > thr).astype(np.uint8)
    eventos   = int(np.sum(np.diff(sobre_thr) > 0))

    return {
        'rms':            np.float64(rms),
        'energia':        np.float64(energy),
        'kurtosis':       np.float64(kurt),
        'crest_factor':   np.float64(crest),
        'conteo_eventos': np.int64(eventos),
    }


def _adquirir(n_buffers):
    """Captura n_buffers x BUF_SIZE muestras. Devuelve array float32 concatenado."""
    # Configurar una sola vez antes del loop
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(DEC_ENUM)
    rp.rp_AcqSetAC_DC(CANAL, DCPL)
    rp.rp_AcqSetGain(CANAL, GAIN)
    rp.rp_AcqSetTriggerDelay(0)

    buf_np   = np.zeros(BUF_SIZE, dtype=np.float32)
    segmentos = []

    for i in range(n_buffers):
        rp.rp_AcqStart()
        time.sleep(0.005)
        rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_NOW)

        while not rp.rp_AcqGetBufferFillState()[1]:
            pass

        rp.rp_AcqGetOldestDataVNP(CANAL, buf_np)
        segmentos.append(buf_np.copy())

        if (i + 1) % 10 == 0:
            print(f'  {i+1}/{n_buffers} buffers', flush=True)

    return np.concatenate(segmentos)


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------
def capturar(condicion, masa_g=-1.0, tamanio_mm=-1.0, caudal_Ls=-1.0):
    ts    = datetime.datetime.now()
    ts_s  = ts.strftime('%Y%m%d_%H%M%S')
    fname = f'captura_{condicion}_{ts_s}.h5'
    duracion_ms = N_BUFFERS * BUF_SIZE / FS_EF * 1000

    print(f'\n=== CAPTURA ===')
    print(f'  condicion  : {condicion}')
    print(f'  masa_g     : {masa_g}')
    print(f'  tamanio_mm : {tamanio_mm}')
    print(f'  caudal_Ls  : {caudal_Ls}')
    print(f'  fs_ef_hz   : {FS_EF:.0f} Hz')
    print(f'  n_muestras : {N_BUFFERS * BUF_SIZE}  ({duracion_ms:.1f} ms)')
    print(f'  archivo    : {fname}\n')

    rp.rp_Init()
    try:
        senal = _adquirir(N_BUFFERS)
    finally:
        rp.rp_Release()

    b, a = _crear_filtro()
    print('Calculando metricas...', flush=True)
    mets = _calcular_metricas(senal, b, a)

    print('Guardando HDF5...', flush=True)
    with h5py.File(fname, 'w') as f:
        f.create_dataset('raw_signal', data=senal,
                         compression='gzip', compression_opts=4)

        grp = f.create_group('metricas')
        for k, v in mets.items():
            grp.create_dataset(k, data=v)

        f.attrs.update({
            'condicion':    condicion,
            'sensor':       SENSOR,
            'decimacion':   DEC_VAL,
            'fs_hz':        FS_BASE,
            'fs_ef_hz':     FS_EF,
            'n_muestras':   len(senal),
            'n_buffers':    N_BUFFERS,
            'fecha':        ts.strftime('%Y-%m-%d %H:%M:%S'),
            'masa_arena_g': masa_g,
            'tamanio_mm':   tamanio_mm,
            'caudal_Ls':    caudal_Ls,
            'f_low_hz':     F_LOW,
            'f_high_hz':    F_HIGH,
            'gain':         'HV_20V',
        })

    print(f'\n[OK] {fname}')
    print(f'  RMS          = {mets["rms"]:.6f} V')
    print(f'  kurtosis     = {mets["kurtosis"]:.2f}')
    print(f'  crest_factor = {mets["crest_factor"]:.2f}')
    print(f'  eventos      = {mets["conteo_eventos"]}')
    return fname


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    p = argparse.ArgumentParser(
        description='Captura acustica HDF5 — Red Pitaya + VS150-RI')
    p.add_argument('--condicion', required=True,
                   choices=['reposo', 'flujo_limpio', 'baja', 'media', 'alta'],
                   help='Etiqueta de la condicion experimental')
    p.add_argument('--masa_g',     type=float, default=-1.0,
                   help='Masa de arena inyectada [g]. -1 si no aplica.')
    p.add_argument('--tamanio_mm', type=float, default=-1.0,
                   help='Tamanio de particula [mm]. -1 si no aplica.')
    p.add_argument('--caudal_Ls',  type=float, default=-1.0,
                   help='Caudal de fluido [L/s]. -1 si no aplica.')
    args = p.parse_args()

    capturar(
        condicion  = args.condicion,
        masa_g     = args.masa_g,
        tamanio_mm = args.tamanio_mm,
        caudal_Ls  = args.caudal_Ls,
    )
