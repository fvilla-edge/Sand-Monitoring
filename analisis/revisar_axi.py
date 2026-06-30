#!/usr/bin/env python3
"""
Lee archivos .bin generados por capture_axi y calcula las mismas metricas
que revisar_campo.py (kurtosis, crest factor, fraccion_activa).

Uso:
  python3 revisar_axi.py captura_axi.bin
  python3 revisar_axi.py /ruta/al/archivo.bin
"""
import struct
import sys
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy import signal
from scipy.stats import kurtosis

# Header identico al struct FileHeader de capture_axi.cpp
HEADER_FMT  = '<4sIIIIIqBB6s'
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 40 bytes
assert HEADER_SIZE == 40, f"Header size inesperado: {HEADER_SIZE}"

ADC_BITS = 14
V_RANGE  = 20.0   # ±20V con gain 5X (modo HV)

WINDOW_SEG  = 0.05   # ventana 50 ms para kurtosis (igual que Python)
KURT_UMBRAL = 20.0   # umbral para fraccion_activa


def load_bin(path):
    with open(path, 'rb') as f:
        raw = f.read(HEADER_SIZE)
        fields = struct.unpack(HEADER_FMT, raw)
    magic, version, fs, dec, n_samples, channels, timestamp, gain, coupling, _ = fields

    if magic != b'SNDM':
        raise ValueError(f"Archivo invalido: magic={magic} (esperado b'SNDM')")

    with open(path, 'rb') as f:
        f.seek(HEADER_SIZE)
        raw_data = f.read()

    data_int16 = np.frombuffer(raw_data, dtype=np.int16)

    # Convertir a voltaje (14 bits firmado, rango ±V_RANGE)
    volts = data_int16.astype(np.float32) / (2 ** (ADC_BITS - 1)) * V_RANGE

    return {
        'path':      path,
        'fs':        fs,
        'dec':       dec,
        'n_samples': n_samples,
        'channels':  channels,
        'timestamp': timestamp,
        'gain':      gain,
        'data':      volts,
    }


def calcular_metricas(data, fs):
    win = int(WINDOW_SEG * fs)
    n_win = len(data) // win
    kurts  = np.array([kurtosis(data[i*win:(i+1)*win]) for i in range(n_win)])
    crests = np.array([
        np.max(np.abs(data[i*win:(i+1)*win])) / (np.std(data[i*win:(i+1)*win]) + 1e-10)
        for i in range(n_win)
    ])
    fa = float(np.mean(kurts > KURT_UMBRAL))
    return kurts, crests, fa


def main(path):
    info = load_bin(path)
    fs   = info['fs']
    data = info['data']
    n    = info['n_samples']
    dur  = n / fs

    print(f"\nArchivo  : {path}")
    print(f"fs       = {fs} Hz | dec = {info['dec']} | {n} muestras | {dur:.2f} s")
    print(f"Canales  : {info['channels']}")
    print(f"Voltaje  : [{data.min():.3f}, {data.max():.3f}] V")
    print(f"RMS      : {np.sqrt(np.mean(data**2)):.4f} V")

    kurts, crests, fa = calcular_metricas(data, fs)
    print(f"\nKurtosis : media={kurts.mean():.1f} | max={kurts.max():.1f}")
    print(f"Crest    : media={crests.mean():.1f}")
    print(f"FA (k>20): {fa:.3f} ({fa*100:.1f}%)")

    # --- Plots ---
    t = np.arange(len(data)) / fs
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(Path(path).name)

    ax = axes[0, 0]
    ax.plot(t, data, lw=0.3)
    ax.set_xlabel('Tiempo (s)')
    ax.set_ylabel('Voltaje (V)')
    ax.set_title('Señal cruda CH1')

    ax = axes[0, 1]
    freqs, psd = signal.welch(data, fs=fs, nperseg=4096)
    ax.semilogy(freqs / 1e3, psd)
    ax.set_xlabel('Frecuencia (kHz)')
    ax.set_ylabel('PSD (V²/Hz)')
    ax.set_title('Espectro de potencia')
    ax.axvline(150, color='r', ls='--', lw=0.8, label='150 kHz resonancia')
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    t_win = np.arange(len(kurts)) * WINDOW_SEG
    ax.plot(t_win, kurts)
    ax.axhline(KURT_UMBRAL, color='r', ls='--', label=f'umbral={KURT_UMBRAL}')
    ax.set_xlabel('Tiempo (s)')
    ax.set_ylabel('Kurtosis')
    ax.set_title(f'Kurtosis por ventana — FA={fa:.2f}')
    ax.legend()

    ax = axes[1, 1]
    ax.scatter(crests, kurts, alpha=0.4, s=10)
    ax.set_xlabel('Crest factor')
    ax.set_ylabel('Kurtosis')
    ax.set_title('Kurtosis vs Crest factor')

    plt.tight_layout()
    out_png = str(path).replace('.bin', '_analisis.png')
    plt.savefig(out_png, dpi=150)
    print(f"\nGrafico  : {out_png}")
    plt.show()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
