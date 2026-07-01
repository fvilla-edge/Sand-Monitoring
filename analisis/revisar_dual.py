#!/usr/bin/env python3
"""
revisar_dual.py — Revision rapida de capturas dual canal (CH1 + CH2) en PC.

Acepta archivos .bin de capturar_dual_stream.py: raw int16 LE, CH1 y CH2
intercalados por muestra en un solo archivo (asi los escribe el
streaming-server con los 2 canales activos — no hay opcion de archivos
separados). Requiere el session_dual_*_info.json en el mismo directorio.

Mapeo de canales (ver session_dual_*_info.json, campo "mapeo_canales"):
  CH1 (codo)       = posiciones impares (datos[1::2])
  CH2 (referencia) = posiciones pares   (datos[0::2])
Confirmado con golpe fisico en el cable IN1 sin sensor conectado (2026-07-01).
PENDIENTE re-confirmar con el sensor VS150-RI puesto.

Calcula kurtosis, crest factor y fraccion_activa sobre cada canal filtrado
(100-450 kHz) y metricas diferenciales para separar arena de ruido de linea
comun.

Uso:
  .venv/bin/python3 analisis/revisar_dual.py /mnt/usb/stream_dual/
  .venv/bin/python3 analisis/revisar_dual.py dual_reposo_*.bin dual_con_arena_*.bin

Metricas:
  k1 / k2      : kurtosis CH1 (codo) y CH2 (referencia)
  dk           : k1 - k2  (positivo -> evento localizado en codo)
  fa1% / fa2%  : fraccion ventanas activas (kurt > 20) por canal
  rms_r        : RMS_CH1 / RMS_CH2  (>1 -> exceso de energia en codo)
  deteccion    : ARENA si k1>20 y k1 > 3*k2 | ruido si ambos altos | reposo
"""
import re
import sys
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt
from scipy.stats import kurtosis as scipy_kurtosis

BANDA_LOW   = 100_000
BANDA_HIGH  = 450_000
FILTRO_ORD  = 4
FA_WINDOW_S = 0.050
FA_THRESH   = 20

V_REF = 20.0   # ±20V con jumper HV y gain A_1_20


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


def _buscar_info(ruta):
    m = re.match(r'dual_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
    if m:
        info_path = ruta.parent / f'session_dual_{m.group(1)}_{m.group(2)}_info.json'
        if info_path.exists():
            return info_path
    raise FileNotFoundError(f"No se encontro JSON de sesion para {ruta.name}")


def _chunk_num_from_nombre(stem):
    try:
        return int(stem.rsplit('_', 1)[-1])
    except ValueError:
        return 0


def _calcular(ruta):
    ruta = Path(ruta)
    info_path = _buscar_info(ruta)
    with open(info_path) as f:
        info = json.load(f)

    dec  = int(info.get('decimacion', 64))
    fs   = float(info.get('fs_hz_por_canal', 125_000_000 / dec))
    cond = str(info.get('condicion', '?'))
    mapeo = info.get('mapeo_canales', {})
    ch1_pares = mapeo.get('ch1_posiciones', 'impares').startswith('par')

    raw = np.fromfile(ruta, dtype='<i2')
    if ch1_pares:
        ch1_i16, ch2_i16 = raw[0::2], raw[1::2]
    else:
        ch1_i16, ch2_i16 = raw[1::2], raw[0::2]

    ch1 = ch1_i16.astype(np.float32) * (V_REF / 32767.0)
    ch2 = ch2_i16.astype(np.float32) * (V_REF / 32767.0)
    dur_s = len(ch1) / fs
    chunk = _chunk_num_from_nombre(ruta.stem)
    size  = ruta.stat().st_size / 1e6

    f1 = _bandpass(ch1, fs)
    f2 = _bandpass(ch2, fs)

    rms1 = float(np.sqrt(np.mean(f1 ** 2)))
    rms2 = float(np.sqrt(np.mean(f2 ** 2)))
    k1   = float(scipy_kurtosis(f1, fisher=False))
    k2   = float(scipy_kurtosis(f2, fisher=False))
    cf1  = float(np.max(np.abs(f1)) / rms1) if rms1 > 0 else 0.0
    cf2  = float(np.max(np.abs(f2)) / rms2) if rms2 > 0 else 0.0
    fa1  = _fraccion_activa(f1, fs)
    fa2  = _fraccion_activa(f2, fs)

    return {
        'archivo':  ruta.name,
        'cond':     cond,
        'chunk':    chunk,
        'dur_min':  dur_s / 60,
        'k1':       k1,
        'k2':       k2,
        'dk':       k1 - k2,
        'cf1':      cf1,
        'cf2':      cf2,
        'fa1':      fa1,
        'fa2':      fa2,
        'rms_r':    rms1 / rms2 if rms2 > 0 else 0.0,
        'size_mb':  size,
    }


def _detectar(r):
    k1, k2 = r['k1'], r['k2']
    if k1 > 20 and k2 > 20:
        return 'RUIDO COMUN'   # ambos canales impulsivos -> no es arena localizada
    if k1 > 20 and k1 > 3 * k2:
        return '*** ARENA ***'
    return 'reposo'


def _recopilar_rutas(args):
    rutas = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            rutas.extend(sorted(p.glob('dual_*.bin')))
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
        print('[!] No se encontraron archivos dual_*.bin')
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

    ancho = max(len(r['archivo']) for r in resultados)
    sep   = '-' * (ancho + 72)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'ck':>5}  {'dur':>5}  "
              f"{'k1':>7}  {'k2':>7}  {'dk':>7}  "
              f"{'fa1%':>5}  {'fa2%':>5}  {'rms_r':>6}  {'MB':>6}  deteccion")
    print(f'\n{sep}')
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar(r)
        print(
            f"{r['archivo']:<{ancho}}  "
            f"{r['cond']:<10}  "
            f"{r['chunk']:>5}  "
            f"{r['dur_min']:>4.1f}m  "
            f"{r['k1']:>7.1f}  "
            f"{r['k2']:>7.1f}  "
            f"{r['dk']:>7.1f}  "
            f"{r['fa1']:>4.1f}%  "
            f"{r['fa2']:>4.1f}%  "
            f"{r['rms_r']:>6.2f}  "
            f"{r['size_mb']:>6.1f}  "
            f"{det}"
        )

    print(sep)

    n_arena  = sum(1 for r in resultados if _detectar(r) == '*** ARENA ***')
    n_ruido  = sum(1 for r in resultados if _detectar(r) == 'RUIDO COMUN')
    n_reposo = len(resultados) - n_arena - n_ruido
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_ruido} ruido comun | {n_reposo} en reposo')
    print()
    print('  Referencia reposo: k1~3, k2~3, dk~0, fa1%~0, fa2%~0, rms_r~1')
    print('  Referencia arena:  k1>20, k2~3, dk>>0, fa1%>25, rms_r>1')
    print('  [!] Mapeo CH1/CH2 confirmado por golpe en cable sin sensor (2026-07-01) —')
    print('      pendiente re-confirmar con el sensor VS150-RI puesto.')


if __name__ == '__main__':
    main()
