#!/usr/bin/env python3
"""verificar_etapaB.py — compara lo que guardo el modo evento al reproducir
por el DAC (loopback digital) un tramo de señal REAL, contra el pipeline de
software (area_kurtosis.py) corrido sobre ese mismo tramo.

Para cada evento guardado por el hardware:
  1. se ubica su ventana oficial dentro del tramo original (correlacion; el
     DAC por red mete silencios, asi que cada evento se ubica por separado,
     no con un desplazamiento unico),
  2. se calcula la kurtosis en software sobre EXACTAMENTE esas muestras
     (pasabanda de area_kurtosis.py aplicado al tramo entero, para no meter
     el transitorio de arranque del filtro), con la media restada (criterio
     de software) y con media=0 (aproximacion de la FPGA), y se compara con
     la kurtosis que dio la FPGA.

Sensibilidad: con la grilla de ventanas del hardware (fase tomada de los
eventos ubicados), se listan las ventanas que el software marca >= umbral y
se busca si el hardware guardo un evento ahi (perdidos), y los eventos del
hardware en ventanas que el software no marca (sobrantes).

Uso:
  python3 verificar_etapaB.py <tramo.bin int16> <carpeta_eventos> [--umbral 5]
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from area_kurtosis import _filtrar_pasabanda

FS = 3906250.0


def kurt(v, restar_media):
    v = v.astype(np.float64)
    if restar_media:
        v = v - v.mean()
    m2 = np.mean(v ** 2)
    return float(np.mean(v ** 4) / m2 ** 2) if m2 > 0 else float('nan')


def ubicar(x, pedazo, centro, radio):
    """indice de x donde mejor calza `pedazo`, buscando en [centro-radio, centro+radio]."""
    a = max(0, centro - radio)
    b = min(len(x), centro + radio + len(pedazo))
    seg = x[a:b]
    if len(seg) < len(pedazo):
        return None, 0.0
    p = pedazo - pedazo.mean()
    n = 1 << int(np.ceil(np.log2(len(seg) + len(p))))
    c = np.fft.irfft(np.fft.rfft(seg - seg.mean(), n) * np.conj(np.fft.rfft(p, n)), n)[:len(seg) - len(p) + 1]
    k = int(np.argmax(c))
    ref = seg[k:k + len(p)]
    r = float(np.corrcoef(ref, pedazo)[0, 1])
    return a + k, r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tramo')
    ap.add_argument('carpeta')
    ap.add_argument('--umbral', type=float, default=5.0)
    args = ap.parse_args()

    x = np.fromfile(args.tramo, dtype='<i2').astype(np.float64)
    y = _filtrar_pasabanda(x, FS).astype(np.float64)
    eventos = []
    for js in sorted(glob.glob(os.path.join(args.carpeta, 'evento_*.json'))):
        with open(js) as f:
            e = json.load(f)
        e['x'] = np.fromfile(js[:-5] + '.bin', dtype='<i2').astype(np.float64)
        e['archivo'] = os.path.basename(js[:-5])
        eventos.append(e)
    if not eventos:
        sys.exit('sin eventos')
    N = eventos[0]['ventana_muestras']
    print(f'tramo: {len(x)} muestras ({len(x) / FS:.1f}s, {len(x) // N} ventanas) | eventos del hardware: {len(eventos)}')

    # ubicar cada evento: el primero contra todo el tramo, los demas cerca de
    # donde predice el anterior (mismo avance en el stream), refinando
    ubicados, previo = [], None
    for e in eventos:
        ofi = e['x'][e['inicio_ventana_en_archivo']:e['inicio_ventana_en_archivo'] + N]
        huella = ofi[:65536] if len(ofi) >= 65536 else ofi
        if previo is None:
            pos, r = ubicar(x, huella, len(x) // 2, len(x))
        else:
            pred = previo[1] + (e['indice_inicio'] - previo[0]['indice_inicio'])
            pos, r = ubicar(x, huella, pred, int(0.5 * FS))
            if r < 0.9:  # el DAC pudo meter un silencio largo: buscar en todo el tramo
                pos, r = ubicar(x, huella, len(x) // 2, len(x))
        e['pos'], e['corr'] = pos, r
        if pos is not None and r >= 0.9:
            previo = (e, pos)
            ubicados.append(e)
    print(f'eventos ubicados en el tramo (correlacion >= 0.9): {len(ubicados)}/{len(eventos)}')
    for e in eventos:
        if e not in ubicados:
            print(f'  NO UBICADO {e["archivo"]}: corr={e["corr"]:.2f} kurt_fpga={e["kurtosis"]:.1f} '
                  f'(¿silencio del DAC o fuera del tramo?)')

    # kurtosis FPGA vs software sobre las mismas muestras
    print()
    print('=== KURTOSIS FPGA vs SOFTWARE, mismas muestras ===')
    filas = []
    for e in ubicados:
        seg = y[e['pos']:e['pos'] + N]
        if len(seg) < N:
            continue
        filas.append((e, kurt(seg, True), kurt(seg, False)))
    kf = np.array([f[0]['kurtosis'] for f in filas])
    ks = np.array([f[1] for f in filas])
    k0 = np.array([f[2] for f in filas])
    rel = (kf - k0) / k0
    print(f'{len(filas)} eventos | kurt_fpga {kf.min():.1f}..{kf.max():.1f} | '
          f'error relativo FPGA vs software(media=0): mediana={np.median(np.abs(rel)) * 100:.1f}% '
          f'p90={np.percentile(np.abs(rel), 90) * 100:.1f}% max={np.abs(rel).max() * 100:.1f}%')
    print(f'software media=0 vs media restada: mediana dif={np.median(np.abs(k0 - ks) / ks) * 100:.2f}%')
    peores = sorted(filas, key=lambda f: -abs(f[0]['kurtosis'] - f[2]) / f[2])[:5]
    for e, s, z in peores:
        print(f'  {e["archivo"]}: fpga={e["kurtosis"]:.2f} sw(media=0)={z:.2f} sw(media restada)={s:.2f}')

    # sensibilidad sobre la grilla del hardware
    print()
    print(f'=== SENSIBILIDAD (umbral {args.umbral}) sobre la grilla de ventanas del hardware ===')
    fase = int(np.median([e['pos'] % N for e in ubicados]))
    inicios = np.arange(fase, len(y) - N + 1, N)
    k_grilla = np.array([kurt(y[i:i + N], True) for i in inicios])
    marcadas = inicios[k_grilla >= args.umbral]
    pos_hw = np.array(sorted(e['pos'] for e in ubicados))
    perdidas = [(i, k) for i, k in zip(inicios, k_grilla) if k >= args.umbral and
                (len(pos_hw) == 0 or np.min(np.abs(pos_hw - i)) > N // 4)]
    sobrantes = [e for e in ubicados if np.min(np.abs(marcadas - e['pos'])) > N // 4] if len(marcadas) else ubicados
    print(f'ventanas del tramo que el software marca >= {args.umbral}: {len(marcadas)} | '
          f'eventos del hardware ubicados: {len(ubicados)}')
    print(f'marcadas por software SIN evento del hardware (perdidas): {len(perdidas)}')
    for i, k in perdidas[:10]:
        print(f'  ventana en t={i / FS:.3f}s kurt_sw={k:.2f}')
    print(f'eventos del hardware en ventanas que el software NO marca (sobrantes): {len(sobrantes)}')
    for e in sobrantes[:10]:
        print(f'  {e["archivo"]}: t={e["pos"] / FS:.3f}s kurt_fpga={e["kurtosis"]:.2f}')
    fase_std = np.std([((e['pos'] - fase + N // 2) % N) - N // 2 for e in ubicados])
    print(f'(info) desvio de la fase de grilla entre eventos: {fase_std:.0f} muestras '
          f'— distinto de ~0 = el DAC metio silencios y la grilla se corrio')


if __name__ == '__main__':
    main()
