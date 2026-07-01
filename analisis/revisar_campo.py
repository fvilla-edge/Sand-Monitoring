#!/usr/bin/env python3
"""
revisar_campo.py — Revision rapida de capturas de campo en PC.

Acepta:
  - Archivos .bin (capturar_campo_stream.py — int16 raw, requiere session_info.json)
  - Directorios   (busca campo_*.bin recursivamente)

Calcula kurtosis, crest factor, fraccion_activa y rms_diferencial sobre la
senal filtrada (100-450 kHz). rms_diferencial usa como baseline la mediana
del RMS de las capturas 'reposo' presentes en el mismo lote (formula Gao 2015,
ver analisis/INTERPRETACION_RESULTADOS.md) — si el lote no tiene ninguna
captura reposo, se muestra N/A.

Uso:
  .venv/bin/python3 analisis/revisar_campo.py /mnt/usb/
  .venv/bin/python3 analisis/revisar_campo.py campo_reposo_*.bin campo_con_arena_*.bin
"""
import re
import sys
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt
from scipy.stats import kurtosis as scipy_kurtosis

BANDA_LOW   = 100_000   # Hz
BANDA_HIGH  = 450_000   # Hz
FILTRO_ORD  = 4
FA_WINDOW_S = 0.050     # 50 ms por ventana
FA_THRESH   = 20        # kurtosis Pearson > 20 → ventana activa

V_REF = 20.0            # ±20V con jumper HV y gain A_1_20


def _bandpass(signal, fs):
    sos = butter(FILTRO_ORD, [BANDA_LOW, BANDA_HIGH], btype='band', fs=fs, output='sos')
    return sosfilt(sos, signal)


def _fraccion_activa(sig, fs):
    n_win   = int(fs * FA_WINDOW_S)
    n_total = len(sig) // n_win
    if n_total == 0:
        return 0.0
    mat = sig[:n_total * n_win].reshape(n_total, n_win)
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2  = np.mean(mat ** 2, axis=1)
    m4  = np.mean(mat ** 4, axis=1)
    kurt_w = m4 / np.where(m2 > 0, m2 ** 2, 1e-30)
    return float(np.mean(kurt_w > FA_THRESH) * 100)


def _calcular_bin(ruta):
    ruta = Path(ruta)
    m = re.match(r'campo_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
    if m:
        info_path = ruta.parent / f'session_{m.group(1)}_{m.group(2)}_info.json'
    else:
        info_path = ruta.parent / 'session_info.json'
    if not info_path.exists():
        info_path = ruta.parent / 'session_info.json'
    if not info_path.exists():
        raise FileNotFoundError(f"No se encontro JSON de sesion en {ruta.parent}")

    with open(info_path) as f:
        info = json.load(f)

    fs    = float(info['fs_hz'])
    cond  = str(info.get('condicion', '?'))
    chunk = _chunk_num_from_nombre(ruta.stem)

    raw    = np.fromfile(ruta, dtype='<i2')
    signal = raw.astype(np.float32) * (V_REF / 32767.0)
    dur_s  = len(signal) / fs
    return signal, fs, cond, dur_s, chunk


def _chunk_num_from_nombre(stem):
    parts = stem.rsplit('_', 1)
    try:
        return int(parts[-1])
    except ValueError:
        return 0


def _calcular(ruta):
    ruta = Path(ruta)
    if ruta.suffix != '.bin':
        raise ValueError(f"Formato no soportado: {ruta.suffix}")
    signal, fs, cond, dur_s, chunk = _calcular_bin(ruta)

    size  = ruta.stat().st_size / 1e6
    sig_f = _bandpass(signal, fs)
    rms   = float(np.sqrt(np.mean(sig_f ** 2)))
    pico  = float(np.max(np.abs(sig_f)))
    kurt  = float(scipy_kurtosis(sig_f, fisher=False))
    cf    = float(pico / rms) if rms > 0 else 0.0
    fa    = _fraccion_activa(sig_f, fs)

    return {
        'archivo':  ruta.name,
        'cond':     cond,
        'chunk':    chunk,
        'dur_min':  dur_s / 60,
        'rms':      rms,
        'kurt':     kurt,
        'crest':    cf,
        'fa_pct':   fa,
        'size_mb':  size,
    }


def _agregar_rms_diferencial(resultados):
    reposo_rms = [r['rms'] for r in resultados if r['cond'] == 'reposo']
    if not reposo_rms:
        for r in resultados:
            r['rms_dif'] = None
        return None

    baseline = float(np.median(reposo_rms))
    for r in resultados:
        r['rms_dif'] = float(np.sqrt(max(0.0, r['rms'] ** 2 - baseline ** 2)) / baseline)
    return baseline


def _detectar(r):
    if r['kurt'] > 20 or r['fa_pct'] > 5:
        return '*** ARENA ***'
    return 'reposo'


def _recopilar_rutas(args):
    rutas = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            rutas.extend(sorted(p.glob('campo_*.bin')))
        elif p.exists():
            rutas.append(p)
        else:
            print(f'[!] No encontrado: {a}')
    return rutas


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    rutas = _recopilar_rutas(sys.argv[1:])
    if not rutas:
        print('[!] No se encontraron archivos .bin de campo')
        sys.exit(1)

    resultados = []
    for ruta in rutas:
        print(f'  leyendo {ruta.name} ...', end='\r', flush=True)
        try:
            resultados.append(_calcular(ruta))
        except Exception as e:
            print(f'[ERROR] {ruta.name}: {e}')

    if not resultados:
        return

    baseline = _agregar_rms_diferencial(resultados)
    if baseline is None:
        print('[!] Ningun archivo con condicion "reposo" en el lote — rms_diferencial se muestra como N/A')

    ancho = max(len(r['archivo']) for r in resultados)
    sep   = '-' * (ancho + 68)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'chunk':>5}  "
              f"{'dur':>5}  {'kurt':>7}  {'crest':>6}  {'fa%':>5}  {'rms_dif':>7}  {'MB':>6}  deteccion")
    print(f'\n{sep}')
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar(r)
        rd  = f"{r['rms_dif']:>7.2f}" if r['rms_dif'] is not None else f"{'N/A':>7}"
        print(
            f"{r['archivo']:<{ancho}}  "
            f"{r['cond']:<10}  "
            f"{r['chunk']:>5}  "
            f"{r['dur_min']:>4.1f}m  "
            f"{r['kurt']:>7.1f}  "
            f"{r['crest']:>6.1f}  "
            f"{r['fa_pct']:>4.1f}%  "
            f"{rd}  "
            f"{r['size_mb']:>6.1f}  "
            f"{det}"
        )

    print(sep)

    n_arena  = sum(1 for r in resultados if _detectar(r) != 'reposo')
    n_reposo = len(resultados) - n_arena
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_reposo} en reposo')
    print()
    print('  Referencia: kurtosis reposo ~3 | arena >20  |  fa% reposo 0% | arena >25%')
    print('  rms_diferencial (informativo, no afecta deteccion): sqrt(max(0,rms²-baseline²))/baseline,')
    print('  baseline = mediana RMS de "reposo" en el lote | <0.1 insignificante | 0.1-0.4 leve | >0.4 significativo')


if __name__ == '__main__':
    main()
