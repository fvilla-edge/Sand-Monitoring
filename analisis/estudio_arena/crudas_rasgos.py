#!/usr/bin/env python3
"""
crudas_rasgos.py — rasgos de la señal CRUDA por evento (docs/plan_modelo_arena.md sec.11):
¿los golpes del 2-3/10 se parecen a la arena del 21/9?

Entradas:
  - eventos del modo evento (evento_*.bin int16 + .json, 70 ms a 3.906 MHz, disparados con
    kurtosis >= 5 sobre la señal filtrada en la FPGA), y
  - opcional, capturas largas del 21/9 (campo_con_arena_*.bin, otra cadena): se cortan
    en ventanas de 50 ms, se calcula la kurtosis filtrada (50-400 kHz, igual que revisar.py) y
    se toman como "eventos" las que dan k >= 5 (mismo disparo), con 10 ms de margen.

Rasgos por evento (sobre la ventana completa del archivo):
  - filtrada 50-400 kHz: kurtosis, rms, pico, factor de cresta
  - cruda: fraccion de potencia por banda (Welch), centroide espectral 20 kHz-1.95 MHz,
    saturacion (muestras en el maximo del ADC)
  - impactos: envolvente (Hilbert, suavizada 10 us) de la filtrada; cruces de 6x la mediana con
    tiempo muerto de 100 us; duracion y frecuencia dominante del impacto mas fuerte

Salida: CSV con una fila por evento (--salida) y resumen por grupo en pantalla.

Uso:
    .venv/bin/python analisis/estudio_arena/crudas_rasgos.py CARPETA_EVENTOS --salida rasgos.csv [--crudas-21sep CARPETA]
"""
import argparse, csv, glob, json, os, sys
import datetime as D
import numpy as np
from scipy.signal import butter, sosfilt, welch, hilbert

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from revisar import _leer_canales_bin   # noqa: E402

FS = 3906250.0
HUSO = D.timedelta(hours=-3)
BANDA_FILTRO = (50_000, 400_000)       # revisar.py
BANDAS = [(1e3, 20e3), (20e3, 50e3), (50e3, 100e3), (100e3, 200e3), (200e3, 400e3),
          (400e3, 800e3), (800e3, 1.95e6)]
UMBRAL_K = 5.0
VENT = int(0.050 * FS)
MARGEN = int(0.010 * FS)
SOS = butter(4, BANDA_FILTRO, btype='band', fs=FS, output='sos')


def kurt(x):
    x = x - x.mean()
    m2 = np.mean(x ** 2)
    return float(np.mean(x ** 4) / m2 ** 2) if m2 > 0 else np.nan


def rasgos(x_int16):
    x = x_int16.astype(np.float64)
    x -= x.mean()
    y = sosfilt(SOS, x)
    r = {}
    r['kurt'] = kurt(y)
    r['rms'] = float(np.sqrt(np.mean(y ** 2)))
    r['pico'] = float(np.max(np.abs(y)))
    r['cresta'] = r['pico'] / r['rms'] if r['rms'] > 0 else np.nan
    r['satur'] = float(np.mean(np.abs(x_int16.astype(np.int32)) >= 8150))  # ADC 14 bits (+-8191)
    f, P = welch(x, fs=FS, nperseg=4096)
    tot = P[(f >= BANDAS[0][0]) & (f < BANDAS[-1][1])].sum()
    for lo, hi in BANDAS:
        r['b_%d_%d' % (lo / 1e3, hi / 1e3)] = float(P[(f >= lo) & (f < hi)].sum() / tot)
    m = (f >= 20e3) & (f < 1.95e6)
    r['centroide_khz'] = float((f[m] * P[m]).sum() / P[m].sum() / 1e3)
    # impactos sobre la envolvente de la filtrada
    env = np.abs(hilbert(y))
    k = int(10e-6 * FS)
    env = np.convolve(env, np.ones(k) / k, mode='same')
    thr = 6 * np.median(env)
    arriba = env > thr
    cruces = np.flatnonzero(arriba[1:] & ~arriba[:-1]) + 1
    muerto = int(100e-6 * FS)
    hits, ultimo = [], -muerto
    for c in cruces:
        if c - ultimo >= muerto:
            hits.append(c)
        ultimo = c
    r['impactos'] = len(hits)
    i = int(np.argmax(env))
    a = i
    while a > 0 and env[a] > thr:
        a -= 1
    b = i
    while b < len(env) - 1 and env[b] > env[i] * 0.1:   # caida a -20 dB
        b += 1
    r['dur_impacto_ms'] = (b - a) / FS * 1e3
    # espectro del impacto mas fuerte menos el fondo del propio evento (bloques de 1 ms)
    blk = int(1e-3 * FS)
    nb = len(x) // blk
    from scipy.signal import periodogram
    fb, Pb = periodogram(x[:nb * blk].reshape(nb, blk), fs=FS, axis=1, window='hann')
    fondo = np.median(Pb, axis=0)
    exc = np.clip(Pb[min(i // blk, nb - 1)] - fondo, 0, None)
    mm = (fb >= 20e3) & (fb < 1.95e6)
    te = exc[mm].sum()
    def frac(lo, hi):
        return float(exc[(fb >= lo) & (fb < hi)].sum() / te) if te > 0 else np.nan
    r['imp_20_100'] = frac(20e3, 100e3)
    r['imp_100_400'] = frac(100e3, 400e3)
    r['imp_400_1950'] = frac(400e3, 1.95e6)
    r['imp_centroide_khz'] = float((fb[mm] * exc[mm]).sum() / te / 1e3) if te > 0 else np.nan
    r['imp_snr_db'] = float(10 * np.log10(Pb[min(i // blk, nb - 1)][mm].sum() / fondo[mm].sum()))
    r['f_impacto_khz'] = float(fb[mm][np.argmax(exc[mm])] / 1e3) if te > 0 else np.nan
    return r


def grupo(t_local):
    d, h = t_local.date(), t_local.hour
    if d == D.date(2026, 9, 21):
        return 'arena_21sep' if h < 14 else 'tarde_21sep'
    if d == D.date(2026, 10, 3) and 12 <= h < 18:
        return 'golpes_sab'
    if d == D.date(2026, 10, 2) and 15 <= h < 18:
        return 'golpes_vie'
    if h >= 22 or h < 6:
        return 'noche'
    return 'dia_otro'


def eventos_modo(carpeta):
    for js in sorted(glob.glob(os.path.join(carpeta, 'evento_*.json'))):
        b = js[:-5] + '.bin'
        if not os.path.exists(b):
            continue
        try:
            j = json.load(open(js))
        except ValueError:
            continue
        x = np.fromfile(b, dtype='<i2')
        if len(x) != j['muestras']:
            continue
        t = D.datetime.fromisoformat(j['timestamp_iso']).replace(tzinfo=None) + HUSO
        yield dict(origen=os.path.basename(b), t_local=t, con_hueco=j.get('con_hueco', False),
                   window_count=j['window_count'], area_fpga=j['area'], k_fpga=j['kurtosis']), x


def eventos_21sep(carpeta):
    for b in sorted(glob.glob(os.path.join(carpeta, 'campo_*.bin'))):
        ch0, _, meta = _leer_canales_bin(__import__('pathlib').Path(b))
        t0 = D.datetime.strptime(os.path.basename(b).split('_')[3] + os.path.basename(b).split('_')[4],
                                 '%Y%m%d%H%M%S') + HUSO
        y = sosfilt(SOS, ch0.astype(np.float64) - ch0.mean())
        n = len(y) // VENT
        for w in range(1, n - 1):
            yw = y[w * VENT:(w + 1) * VENT]
            k = kurt(yw)
            if k >= UMBRAL_K:
                x = ch0[w * VENT - MARGEN:(w + 1) * VENT + MARGEN]
                yield dict(origen='%s#%d' % (os.path.basename(b), w),
                           t_local=t0 + D.timedelta(seconds=w * 0.05), con_hueco=False,
                           window_count=-1, area_fpga=np.nan, k_fpga=k), x


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('eventos'); ap.add_argument('--salida', required=True)
    ap.add_argument('--crudas-21sep', help='capturas largas campo_*.bin (otra cadena de medicion; opcional)')
    ap.add_argument('--max-por-grupo', type=int, default=0, help='0 = todos')
    a = ap.parse_args()
    filas, cuenta = [], {}
    fuentes = [eventos_modo(a.eventos)] + ([eventos_21sep(a.crudas_21sep)] if a.crudas_21sep else [])
    for fuente in fuentes:
        for meta, x in fuente:
            g = grupo(meta['t_local'])
            if a.max_por_grupo and cuenta.get(g, 0) >= a.max_por_grupo:
                continue
            cuenta[g] = cuenta.get(g, 0) + 1
            fila = dict(meta, grupo=g, t_local=meta['t_local'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
            fila.update(rasgos(x))
            filas.append(fila)
    with open(a.salida, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader(); w.writerows(filas)
    print('%d eventos -> %s' % (len(filas), a.salida))
    nombres = [k for k in filas[0] if k not in ('origen', 't_local', 'con_hueco', 'grupo', 'window_count')]
    grupos = ['arena_21sep', 'tarde_21sep', 'golpes_sab', 'golpes_vie', 'dia_otro', 'noche']
    print('\nmediana por grupo (sin eventos con hueco); n = eventos')
    print('%-16s' % 'rasgo' + ''.join('%13s' % g for g in grupos))
    sel = {g: [r for r in filas if r['grupo'] == g and not r['con_hueco']] for g in grupos}
    print('%-16s' % 'n' + ''.join('%13d' % len(sel[g]) for g in grupos))
    for k in nombres:
        print('%-16s' % k + ''.join('%13.4g' % (np.median([r[k] for r in sel[g]]) if sel[g] else np.nan) for g in grupos))


if __name__ == '__main__':
    main()
