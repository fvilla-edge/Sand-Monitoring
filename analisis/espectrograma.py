#!/usr/bin/env python3
"""
espectrograma.py — Espectrograma STFT de capturas de campo (.bin) para visualizacion en PC.

Acepta archivos .bin de capturar_stream.py (int16 raw, requiere
session_info.json en el mismo directorio, mismo formato que revisar.py).

Por defecto grafica todo el archivo, banda 0-600 kHz (marca con lineas
punteadas la banda del sensor 100-450 kHz), ventana Hann con 50% de solape.
Ajustar --nperseg/--overlap/--duracion segun lo que se necesite ver.

Uso:
  .venv/bin/python3 analisis/espectrograma.py capturas/datos_campo/*.bin
  .venv/bin/python3 analisis/espectrograma.py archivo.bin --nperseg 4096 --duracion 10
"""
import re
import sys
import json
import argparse
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

BANDA_LOW  = 100_000   # Hz — banda del sensor VS150-RI
BANDA_HIGH = 450_000   # Hz
V_REF      = 20.0      # +-20V con jumper HV y gain A_1_20

OUTPUT_DIR = Path(__file__).parent / 'outputs'


def _cargar_bin(ruta: Path):
    m = re.match(r'campo_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
    if m:
        info_path = ruta.parent / f'session_{m.group(1)}_{m.group(2)}_info.json'
    else:
        info_path = ruta.parent / 'session_info.json'
    if not info_path.exists():
        raise FileNotFoundError(f"No se encontro JSON de sesion en {ruta.parent}")

    with open(info_path) as f:
        info = json.load(f)

    fs   = float(info['fs_hz'])
    cond = str(info.get('condicion', '?'))

    raw    = np.fromfile(ruta, dtype='<i2')
    signal = raw.astype(np.float64) * (V_REF / 32767.0)
    return signal, fs, cond


def _recortar(signal, fs, inicio_s, duracion_s):
    i0 = int(inicio_s * fs)
    i1 = len(signal) if duracion_s is None else min(len(signal), i0 + int(duracion_s * fs))
    return signal[i0:i1]


def _procesar(ruta: Path, nperseg, overlap, fmin, fmax, inicio_s, duracion_s, outdir):
    signal, fs, cond = _cargar_bin(ruta)
    dur_total = len(signal) / fs
    sig = _recortar(signal, fs, inicio_s, duracion_s)
    del signal
    dur_proc = len(sig) / fs

    noverlap = int(nperseg * overlap)
    f, t, Sxx = spectrogram(sig, fs=fs, window='hann', nperseg=nperseg,
                             noverlap=noverlap, scaling='density')
    del sig

    mask   = (f >= fmin) & (f <= fmax)
    Sxx_db = 10 * np.log10(Sxx[mask, :] + 1e-20)
    del Sxx
    f_mask = f[mask]

    delta_f = fs / nperseg
    delta_t = nperseg / fs

    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.pcolormesh(t, f_mask / 1000, Sxx_db, shading='auto', cmap='inferno')
    ax.axhline(BANDA_LOW / 1000,  color='cyan', linewidth=0.8, linestyle='--', alpha=0.8)
    ax.axhline(BANDA_HIGH / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.8)
    ax.set_xlabel('Tiempo [s]')
    ax.set_ylabel('Frecuencia [kHz]')
    ax.set_title(
        f'{ruta.name}  |  cond={cond}  |  {dur_proc:.1f}s procesados de {dur_total:.1f}s\n'
        f'nperseg={nperseg}  overlap={overlap*100:.0f}%  '
        f'Δf={delta_f:.1f} Hz  Δt={delta_t*1000:.3f} ms  '
        f'matriz={Sxx_db.shape[0]}x{Sxx_db.shape[1]}',
        fontsize=9)
    plt.colorbar(im, ax=ax, label='dB/Hz')
    plt.tight_layout()

    out = outdir / f'espectrograma_{cond}_{ruta.stem}.png'
    plt.savefig(out, dpi=130, bbox_inches='tight')
    plt.close(fig)

    print(f'  {ruta.name}: fs={fs/1e6:.4f}MHz  dur_total={dur_total:.1f}s  '
          f'dur_procesada={dur_proc:.1f}s  Δf={delta_f:.1f}Hz  Δt={delta_t*1000:.3f}ms  '
          f'matriz={Sxx_db.shape[0]}x{Sxx_db.shape[1]}  -> {out.name}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rutas', nargs='+', help='Archivos .bin o directorios con campo_*.bin')
    ap.add_argument('--nperseg', type=int, default=4096, help='Puntos por ventana FFT (default 4096)')
    ap.add_argument('--overlap', type=float, default=0.5, help='Fraccion de solape 0-1 (default 0.5)')
    ap.add_argument('--fmin', type=float, default=0, help='Frecuencia minima a graficar en Hz (default 0)')
    ap.add_argument('--fmax', type=float, default=600_000, help='Frecuencia maxima a graficar en Hz (default 600000)')
    ap.add_argument('--inicio', type=float, default=0.0, help='Segundo de inicio dentro del archivo (default 0)')
    ap.add_argument('--duracion', type=float, default=None, help='Segundos a procesar desde --inicio (default: todo el archivo)')
    ap.add_argument('--outdir', type=str, default=str(OUTPUT_DIR), help='Directorio de salida (default analisis/outputs)')
    args = ap.parse_args()

    rutas = []
    for a in args.rutas:
        p = Path(a)
        if p.is_dir():
            rutas.extend(sorted(p.glob('campo_*.bin')))
        elif p.exists():
            rutas.append(p)
        else:
            print(f'[!] No encontrado: {a}')

    if not rutas:
        print('[!] No se encontraron archivos .bin de campo')
        sys.exit(1)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for ruta in rutas:
        try:
            _procesar(ruta, args.nperseg, args.overlap, args.fmin, args.fmax,
                       args.inicio, args.duracion, outdir)
        except Exception as e:
            print(f'[ERROR] {ruta.name}: {e}')


if __name__ == '__main__':
    main()
