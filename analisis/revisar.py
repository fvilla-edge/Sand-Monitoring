#!/usr/bin/env python3
"""
revisar.py — Revision rapida de capturas de campo en PC (mono o dual).

Acepta:
  - Archivos .bin (capturar_stream.py, requiere session_*_info.json)
  - Directorios   (busca campo_*.bin recursivamente)

La cantidad de canales se detecta por archivo leyendo "canales" (1 o 2) del
JSON de sesion — no hace falta indicarlo por linea de comandos. Un mismo lote
puede mezclar capturas mono y dual: se muestran en tablas separadas.

Mono: kurtosis, crest factor, fraccion_activa y rms_diferencial sobre la
senal filtrada (100-450 kHz).

Dual (CH1 codo / CH2 referencia): mismas metricas por canal mas
kurtosis_diff (k1-k2) y rms_ratio (CH1/CH2) para separar arena de ruido de
linea comun a ambos sensores.

rms_diferencial usa como baseline la mediana del RMS de las capturas 'reposo'
del mismo canal presentes en el lote (formula Gao 2015, ver
analisis/INTERPRETACION_RESULTADOS.md) — si el lote no tiene ninguna captura
reposo, se muestra N/A.

Uso:
  .venv/bin/python3 analisis/revisar.py /mnt/usb/stream_adc/
  .venv/bin/python3 analisis/revisar.py campo_reposo_*.bin campo_con_arena_*.bin

NOTA DE FORMATO (2026-07-08): el .bin del streaming-server en modo FILE NO es
raw plano — es un tren de segmentos [header][datos canal0][datos canal1]
[marcador fin, 12 bytes 0xFF]. Confirmado por un mantenedor de Red Pitaya en
github.com/RedPitaya/RedPitaya/issues/337 (los "picos periodicos" que se
venian investigando como posible defecto de hardware en IN1 eran bytes del
header leidos como si fueran muestras). El layout exacto del header (112
bytes, sizeCh[4] en offset 4) fue reconstruido a mano contra archivos reales
de esta placa (Ecosystem 3.00-e00665135) porque no coincide con el struct
`CBinInfo::BinHeader` publicado en el repo de Red Pitaya (esa version da 144
bytes) — reversear con archivos propios en vez de confiar en el struct
publicado si esto se repite en otra placa/ecosistema. Ver `_leer_canales_bin`
mas abajo.
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

# Formato real de los .bin en modo FILE (ver nota arriba) — reconstruido
# empiricamente, validado byte a byte (walk completo del archivo, 0
# desajustes de marcador) contra capturas mono y dual reales.
#
# El tamaño de header NO es una constante unica — cambia segun el firmware:
# los archivos de antes de la migracion a Release_2026.1 (2026-07-07, ej.
# los del 2026-07-06) usan 112 bytes; los de 2026.1 en adelante (confirmado
# con dos capturas frescas del 2026-07-08, mono y dual, walk limpio de punta
# a punta en ambas) usan 144 bytes — que ademas coincide con el struct
# `CBinInfo::BinHeader` publicado en el repo de Red Pitaya, a diferencia del
# de 112 que no esta en ningun lado publicado. Por eso se autodetecta por
# archivo en vez de asumir uno fijo — un mismo lote de revisar.py puede
# mezclar capturas de antes y despues de la migracion.
_HEADER_SIZES_CONOCIDOS = (144, 112)   # probar 144 primero (firmware vigente)
_MARKER      = b'\xff' * 12  # fin de segmento
_OFF_SIZE_CH = 4              # offset del array sizeCh[4] (uint32 LE) dentro del header


def _detectar_header_size(f, tam):
    """Prueba los tamaños de header conocidos contra el primer segmento del
    archivo y devuelve el que hace calzar el marcador de fin de segmento."""
    for candidato in _HEADER_SIZES_CONOCIDOS:
        if candidato + 12 > tam:
            continue
        f.seek(0)
        header = f.read(candidato)
        size_ch = np.frombuffer(header, dtype='<u4', count=4, offset=_OFF_SIZE_CH)
        marker_off = candidato + int(size_ch.sum())
        if marker_off + 12 > tam:
            continue
        f.seek(marker_off)
        if f.read(12) == _MARKER:
            return candidato
    raise ValueError(
        f'no se pudo determinar el tamaño de header del formato FILE '
        f'(probados: {_HEADER_SIZES_CONOCIDOS}) — ¿archivo de un firmware nuevo?')


def _leer_canales_bin(ruta):
    """
    Recorre el archivo segmento por segmento (header + datos + marcador) y
    devuelve (ch0, ch1) como arrays int16 con SOLO muestras reales — sin los
    bytes de header/marcador mezclados adentro (ver nota de formato arriba).

    ch0/ch1 corresponden a los canales tal cual los arma el streaming-server
    (indice 0 = IN1, indice 1 = IN2, orden fijo — no hay interleaving por
    muestra como se penso antes, cada canal es un bloque contiguo dentro del
    segmento). En mono, ch1 queda vacio.

    Si el ultimo segmento quedo truncado (sesion cortada a mitad de escritura)
    se corta ahi y se avisa por stderr, en vez de fallar o inventar datos.
    """
    ch0_partes, ch1_partes = [], []
    tam = ruta.stat().st_size
    with open(ruta, 'rb') as f:
        header_size = _detectar_header_size(f, tam)
        pos = 0
        n_seg = 0
        while pos + header_size <= tam:
            f.seek(pos)
            header = f.read(header_size)
            size_ch0, size_ch1, size_ch2, size_ch3 = np.frombuffer(
                header, dtype='<u4', count=4, offset=_OFF_SIZE_CH)
            fin_datos = pos + header_size + int(size_ch0) + int(size_ch1) + int(size_ch2) + int(size_ch3)
            if fin_datos + 12 > tam:
                print(f'[!] {ruta.name}: segmento {n_seg} truncado al final del archivo, se descarta', file=sys.stderr)
                break
            f.seek(pos + header_size)
            ch0_partes.append(f.read(int(size_ch0)))
            ch1_partes.append(f.read(int(size_ch1)))
            f.seek(fin_datos)
            marcador = f.read(12)
            if marcador != _MARKER:
                print(f'[!] {ruta.name}: marcador invalido en segmento {n_seg} (offset {fin_datos}), '
                      f'se corta la lectura ahi', file=sys.stderr)
                break
            pos = fin_datos + 12
            n_seg += 1

    ch0 = np.frombuffer(b''.join(ch0_partes), dtype='<i2')
    ch1 = np.frombuffer(b''.join(ch1_partes), dtype='<i2')
    return ch0, ch1


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


def _chunk_num_from_nombre(stem):
    try:
        return int(stem.rsplit('_', 1)[-1])
    except ValueError:
        return 0


def _cargar_info(ruta):
    """Busca el JSON de sesion de `ruta`, con fallback para capturas viejas
    (pre session_{condicion}_{ts}_info.json, ver memoria del proyecto)."""
    m = re.match(r'campo_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
    info_path = None
    if m:
        candidato = ruta.parent / f'session_{m.group(1)}_{m.group(2)}_info.json'
        if candidato.exists():
            info_path = candidato
    if info_path is None:
        info_path = ruta.parent / 'session_info.json'
    if not info_path.exists():
        raise FileNotFoundError(f"No se encontro JSON de sesion en {ruta.parent}")
    with open(info_path) as f:
        return json.load(f)


def _calcular_mono(ruta, info):
    fs    = float(info['fs_hz'])
    cond  = str(info.get('condicion', '?'))
    chunk = _chunk_num_from_nombre(ruta.stem)

    raw, _ = _leer_canales_bin(ruta)
    signal = raw.astype(np.float32) * (V_REF / 32767.0)
    dur_s  = len(signal) / fs
    size   = ruta.stat().st_size / 1e6

    sig_f = _bandpass(signal, fs)
    rms   = float(np.sqrt(np.mean(sig_f ** 2)))
    pico  = float(np.max(np.abs(sig_f)))
    kurt  = float(scipy_kurtosis(sig_f, fisher=False))
    cf    = float(pico / rms) if rms > 0 else 0.0
    fa    = _fraccion_activa(sig_f, fs)

    return {
        'archivo': ruta.name, 'cond': cond, 'chunk': chunk, 'dur_min': dur_s / 60,
        'rms': rms, 'kurt': kurt, 'crest': cf, 'fa_pct': fa, 'size_mb': size,
    }


def _calcular_dual(ruta, info):
    dec  = int(info.get('decimacion', 64))
    fs   = float(info.get('fs_hz_por_canal', 125_000_000 / dec))
    cond = str(info.get('condicion', '?'))

    ch1_i16, ch2_i16 = _leer_canales_bin(ruta)

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
    fa1  = _fraccion_activa(f1, fs)
    fa2  = _fraccion_activa(f2, fs)

    return {
        'archivo': ruta.name, 'cond': cond, 'chunk': chunk, 'dur_min': dur_s / 60,
        'rms1': rms1, 'rms2': rms2, 'k1': k1, 'k2': k2, 'dk': k1 - k2,
        'fa1': fa1, 'fa2': fa2, 'rms_r': rms1 / rms2 if rms2 > 0 else 0.0,
        'size_mb': size,
    }


def _calcular(ruta):
    ruta = Path(ruta)
    if ruta.suffix != '.bin':
        raise ValueError(f"Formato no soportado: {ruta.suffix}")
    info    = _cargar_info(ruta)
    canales = int(info.get('canales', 1))
    r = _calcular_dual(ruta, info) if canales == 2 else _calcular_mono(ruta, info)
    r['canales'] = canales
    return r


def _agregar_rms_diferencial_mono(resultados):
    reposo_rms = [r['rms'] for r in resultados if r['cond'] == 'reposo']
    if not reposo_rms:
        for r in resultados:
            r['rms_dif'] = None
        return None

    baseline = float(np.median(reposo_rms))
    for r in resultados:
        r['rms_dif'] = float(np.sqrt(max(0.0, r['rms'] ** 2 - baseline ** 2)) / baseline)
    return baseline


def _agregar_rms_diferencial_dual(resultados):
    reposo1 = [r['rms1'] for r in resultados if r['cond'] == 'reposo']
    reposo2 = [r['rms2'] for r in resultados if r['cond'] == 'reposo']
    if not reposo1 or not reposo2:
        for r in resultados:
            r['rd1'] = None
            r['rd2'] = None
        return None, None

    base1 = float(np.median(reposo1))
    base2 = float(np.median(reposo2))
    for r in resultados:
        r['rd1'] = float(np.sqrt(max(0.0, r['rms1'] ** 2 - base1 ** 2)) / base1)
        r['rd2'] = float(np.sqrt(max(0.0, r['rms2'] ** 2 - base2 ** 2)) / base2)
    return base1, base2


def _detectar_mono(r):
    if r['kurt'] > 20 or r['fa_pct'] > 5:
        return '*** ARENA ***'
    return 'reposo'


def _detectar_dual(r):
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
            rutas.extend(sorted(p.glob('campo_*.bin')))
        elif p.exists():
            rutas.append(p)
        else:
            print(f'[!] No encontrado: {a}')
    return rutas


def _mostrar_mono(resultados):
    baseline = _agregar_rms_diferencial_mono(resultados)
    if baseline is None:
        print('[!] Ningun archivo con condicion "reposo" en el lote — rms_diferencial se muestra como N/A')

    ancho = max(len(r['archivo']) for r in resultados)
    sep   = '-' * (ancho + 68)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'chunk':>5}  "
              f"{'dur':>5}  {'kurt':>7}  {'crest':>6}  {'fa%':>5}  {'rms_dif':>7}  {'MB':>6}  deteccion")
    print(f'\n=== MONO ({len(resultados)} archivos) ===')
    print(sep)
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar_mono(r)
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
    n_arena  = sum(1 for r in resultados if _detectar_mono(r) != 'reposo')
    n_reposo = len(resultados) - n_arena
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_reposo} en reposo')
    print()
    print('  Referencia: kurtosis reposo ~3 | arena >20  |  fa% reposo 0% | arena >25%')
    print('  rms_diferencial (informativo, no afecta deteccion): sqrt(max(0,rms²-baseline²))/baseline,')
    print('  baseline = mediana RMS de "reposo" en el lote | <0.1 insignificante | 0.1-0.4 leve | >0.4 significativo')


def _mostrar_dual(resultados):
    base1, base2 = _agregar_rms_diferencial_dual(resultados)
    if base1 is None:
        print('[!] Ningun archivo con condicion "reposo" en el lote — rd1/rd2 se muestran como N/A')

    ancho = max(len(r['archivo']) for r in resultados)
    sep   = '-' * (ancho + 88)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'ck':>5}  {'dur':>5}  "
              f"{'k1':>7}  {'k2':>7}  {'dk':>7}  "
              f"{'fa1%':>5}  {'fa2%':>5}  {'rms_r':>6}  {'rd1':>6}  {'rd2':>6}  {'MB':>6}  deteccion")
    print(f'\n=== DUAL ({len(resultados)} archivos) ===')
    print(sep)
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar_dual(r)
        rd1 = f"{r['rd1']:>6.2f}" if r['rd1'] is not None else f"{'N/A':>6}"
        rd2 = f"{r['rd2']:>6.2f}" if r['rd2'] is not None else f"{'N/A':>6}"
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
            f"{rd1}  "
            f"{rd2}  "
            f"{r['size_mb']:>6.1f}  "
            f"{det}"
        )

    print(sep)
    n_arena  = sum(1 for r in resultados if _detectar_dual(r) == '*** ARENA ***')
    n_ruido  = sum(1 for r in resultados if _detectar_dual(r) == 'RUIDO COMUN')
    n_reposo = len(resultados) - n_arena - n_ruido
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_ruido} ruido comun | {n_reposo} en reposo')
    print()
    print('  Referencia reposo: k1~3, k2~3, dk~0, fa1%~0, fa2%~0, rms_r~1')
    print('  Referencia arena:  k1>20, k2~3, dk>>0, fa1%>25, rms_r>1')
    print('  rd1/rd2 (informativo, no afecta deteccion): rms_diferencial por canal,')
    print('  baseline = mediana RMS de "reposo" del mismo canal en el lote | <0.1 insignificante | 0.1-0.4 leve | >0.4 significativo')
    print('  ch1=IN1, ch2=IN2 por construccion del formato (ver _leer_canales_bin) — ya no depende de pares/impares.')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    rutas = _recopilar_rutas(sys.argv[1:])
    if not rutas:
        print('[!] No se encontraron archivos campo_*.bin')
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

    mono = [r for r in resultados if r['canales'] == 1]
    dual = [r for r in resultados if r['canales'] == 2]

    if mono:
        _mostrar_mono(mono)
    if dual:
        _mostrar_dual(dual)


if __name__ == '__main__':
    main()
