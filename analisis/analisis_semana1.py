#!/usr/bin/env python3
"""
analisis_semana1.py — Analisis de capturas HDF5 del sistema de deteccion de arena.
Genera espectrogramas, comparaciones de senal y boxplots de metricas.

Uso:
  python3 analisis_semana1.py                     # lee todos los .h5 de ../capturas/
  python3 analisis_semana1.py --dir /ruta/custom  # directorio alternativo
  python3 analisis_semana1.py --sync              # copia primero desde Red Pitaya

Para sincronizar capturas desde la Red Pitaya:
  scp root@192.168.0.55:/root/captura_*.h5 ../capturas/
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import butter, filtfilt, spectrogram

# ---------------------------------------------------------------------------
# Constantes — deben coincidir con capturar.py
# ---------------------------------------------------------------------------
F_LOW  = 100_000   # Hz
F_HIGH = 450_000   # Hz
ORD    = 4

RPi_HOST    = 'root@192.168.0.55'
RPi_SRC     = '/root/captura_*.h5'
OUTPUT_DIR  = Path(__file__).parent / 'outputs'

CONDICION_COLOR = {
    'reposo':      '#2196F3',   # azul
    'flujo_limpio':'#4CAF50',   # verde
    'baja':        '#FFC107',   # amarillo
    'media':       '#FF9800',   # naranja
    'alta':        '#F44336',   # rojo
}

ORDEN_CONDICION = ['reposo', 'flujo_limpio', 'baja', 'media', 'alta']


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def sincronizar_desde_rpi(dest_dir: Path):
    """Copia archivos .h5 desde la Red Pitaya via scp."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = ['sshpass', '-p', 'edge1234', 'scp', '-o', 'StrictHostKeyChecking=no',
           f'{RPi_HOST}:{RPi_SRC}', str(dest_dir)]
    print(f'Sincronizando desde {RPi_HOST}:{RPi_SRC}...')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'  Advertencia: {result.stderr.strip()}')
    else:
        print('  OK')


def cargar_capturas(capturas_dir: Path) -> list[dict]:
    """Carga todos los archivos .h5 del directorio y devuelve lista de dicts."""
    archivos = sorted(capturas_dir.glob('*.h5'))
    if not archivos:
        print(f'No se encontraron archivos .h5 en {capturas_dir}')
        sys.exit(1)

    capturas = []
    for ruta in archivos:
        with h5py.File(ruta, 'r') as f:
            raw = f['raw_signal'][:]
            mets = {k: float(f['metricas'][k][()]) for k in f['metricas']}
            mets['conteo_eventos'] = int(f['metricas']['conteo_eventos'][()])
            attrs = dict(f.attrs)
        capturas.append({
            'archivo':   ruta.name,
            'raw':       raw,
            'metricas':  mets,
            'attrs':     attrs,
            'condicion': str(attrs.get('condicion', 'desconocido')),
            'fs':        float(attrs.get('fs_ef_hz', 1953125.0)),
        })
        print(f'  Cargado: {ruta.name}  ({attrs.get("condicion")})')

    return capturas


def _filtro_bp(fs):
    nyq = fs / 2.0
    return butter(ORD, [F_LOW / nyq, F_HIGH / nyq], btype='band')


def calcular_rms_diferencial(capturas: list[dict]):
    """Agrega rms_diferencial a cada captura: sqrt(max(0, rms² − baseline²)) / baseline.

    Baseline = mediana RMS de las capturas de reposo. Si no hay reposo, usa el
    minimo RMS del set. Formula de Gao 2015, adimensional y robusta a cambios
    de ganancia o caudal.
    """
    reposo = [c for c in capturas if c['condicion'] == 'reposo']
    if reposo:
        baseline = float(np.median([c['metricas']['rms'] for c in reposo]))
    else:
        baseline = float(min(c['metricas']['rms'] for c in capturas))

    for cap in capturas:
        rms = cap['metricas']['rms']
        cap['metricas']['rms_diferencial'] = float(
            np.sqrt(max(0.0, rms**2 - baseline**2)) / baseline
        )

    print(f'  Baseline RMS (reposo): {baseline * 1000:.3f} mV')


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------
def plot_senal_raw(capturas: list[dict], output_dir: Path):
    """Primeros 2ms de senal raw para cada condicion."""
    fig, axes = plt.subplots(len(capturas), 1,
                              figsize=(14, 2.5 * len(capturas)),
                              sharex=False)
    if len(capturas) == 1:
        axes = [axes]

    for ax, cap in zip(axes, capturas):
        fs  = cap['fs']
        raw = cap['raw']
        n_show = min(int(0.002 * fs), len(raw))   # 2 ms
        t_ms = np.arange(n_show) / fs * 1000
        cond = cap['condicion']
        color = CONDICION_COLOR.get(cond, 'gray')
        ax.plot(t_ms, raw[:n_show], color=color, linewidth=0.5, alpha=0.9)
        ax.set_ylabel('V', fontsize=9)
        ax.set_title(f'{cap["archivo"]}  |  RMS={cap["metricas"]["rms"]:.4f} V'
                     f'  kurtosis={cap["metricas"]["kurtosis"]:.2f}', fontsize=9)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Tiempo [ms]')
    fig.suptitle('Senal raw — primeros 2 ms', fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'senal_raw.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_espectrograma(capturas: list[dict], output_dir: Path):
    """Espectrograma STFT para cada captura con escala de color compartida."""
    nperseg  = 512
    noverlap = int(nperseg * 0.75)

    # Primera pasada: calcular todos los espectrogramas y determinar rango global
    espectros = []
    for cap in capturas:
        fs  = cap['fs']
        sig = cap['raw'].astype(np.float64)
        f, t, Sxx = spectrogram(sig, fs=fs, nperseg=nperseg, noverlap=noverlap,
                                 scaling='density')
        f_mask = f <= 600_000
        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        espectros.append((f[f_mask], t, Sxx_db))

    # Escala compartida anclada al ruido base:
    # vmin = mediana del reposo (piso de ruido), vmax = max global (eventos de arena)
    reposo_idx = next((i for i, c in enumerate(capturas) if c['condicion'] == 'reposo'), 0)
    vmin = float(np.median(espectros[reposo_idx][2])) - 3
    vmax = float(max(s[2].max() for s in espectros))

    n_cols = min(len(capturas), 3)
    n_rows = (len(capturas) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols,
                              figsize=(7 * n_cols, 4 * n_rows), squeeze=False)

    for idx, (cap, (f_v, t_v, Sxx_db)) in enumerate(zip(capturas, espectros)):
        ax   = axes[idx // n_cols][idx % n_cols]
        cond = cap['condicion']
        im   = ax.pcolormesh(t_v * 1000, f_v / 1000, Sxx_db,  # t_v ya en segundos
                             shading='gouraud', cmap='inferno',
                             vmin=vmin, vmax=vmax)
        ax.axhline(F_LOW  / 1000, color='cyan', linewidth=0.9,
                   linestyle='--', alpha=0.8, label='100 kHz')
        ax.axhline(F_HIGH / 1000, color='cyan', linewidth=0.9,
                   linestyle='--', alpha=0.8, label='450 kHz')
        ax.set_ylabel('Frecuencia [kHz]')
        ax.set_xlabel('Tiempo [ms]')
        ax.set_title(f'{cond} — kurtosis={cap["metricas"]["kurtosis"]:.1f}\n'
                     f'{cap["archivo"]}', fontsize=8)
        plt.colorbar(im, ax=ax, label='dB/Hz')

    for idx in range(len(capturas), n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    fig.suptitle(f'Espectrogramas STFT  |  escala compartida [{vmin:.0f}, {vmax:.0f}] dB/Hz',
                 fontsize=11, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'espectrogramas.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_fft_comparativa(capturas: list[dict], output_dir: Path):
    """Espectro max-hold: maximo de cada bin de frecuencia sobre toda la captura.

    Equivalente al display de pico del GUI web de Red Pitaya. Un evento breve
    de arena (200 ms en 2.5 s) queda completamente visible porque se toma el
    maximo en lugar del promedio.
    """
    nperseg  = 2048
    noverlap = int(nperseg * 0.75)

    fig, ax = plt.subplots(figsize=(14, 6))

    for cap in capturas:
        fs   = cap['fs']
        sig  = cap['raw'].astype(np.float64)
        f, _, Sxx = spectrogram(sig, fs=fs, nperseg=nperseg, noverlap=noverlap,
                                 scaling='density')

        Sxx_db_max = 10 * np.log10(Sxx.max(axis=1) + 1e-20)

        mask  = f <= 600_000
        cond  = cap['condicion']
        color = CONDICION_COLOR.get(cond, 'gray')
        ax.plot(f[mask] / 1000, Sxx_db_max[mask],
                color=color, label=cond, linewidth=1.0, alpha=0.9)

    ax.axvspan(F_LOW / 1000, F_HIGH / 1000, alpha=0.08, color='yellow',
               label='Banda sensor 100-450 kHz')
    ax.axvline(F_LOW  / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
    ax.axvline(F_HIGH / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
    ax.set_xlabel('Frecuencia [kHz]')
    ax.set_ylabel('PSD pico [dB/Hz]')
    ax.set_title('Espectro pico (max-hold) — maximo por bin sobre toda la captura',
                 fontweight='bold')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = output_dir / 'fft_comparativa.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_boxplots_metricas(capturas: list[dict], output_dir: Path):
    """Boxplot de cada metrica agrupada por condicion."""
    METRICAS = ['rms', 'rms_diferencial', 'energia', 'kurtosis', 'crest_factor', 'conteo_eventos']
    LABELS   = ['RMS [V]', 'RMS dif. [adim]', 'Energia [V^2]', 'Kurtosis', 'Crest Factor', 'Eventos']

    # Agrupar por condicion
    por_condicion: dict[str, dict] = {}
    for cap in capturas:
        cond = cap['condicion']
        if cond not in por_condicion:
            por_condicion[cond] = {m: [] for m in METRICAS}
        for m in METRICAS:
            por_condicion[cond][m].append(cap['metricas'][m])

    condiciones = [c for c in ORDEN_CONDICION if c in por_condicion]
    if not condiciones:
        condiciones = list(por_condicion.keys())

    fig, axes = plt.subplots(1, len(METRICAS), figsize=(4 * len(METRICAS), 5))
    if len(METRICAS) == 1:
        axes = [axes]

    for ax, metrica, label in zip(axes, METRICAS, LABELS):
        datos = [por_condicion[c][metrica] for c in condiciones]
        colors = [CONDICION_COLOR.get(c, 'gray') for c in condiciones]

        bp = ax.boxplot(datos, patch_artist=True, tick_labels=condiciones)
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax.set_title(label, fontsize=10)
        ax.tick_params(axis='x', rotation=30)
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle('Metricas por condicion', fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'boxplots_metricas.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_espectrograma_peak(capturas: list[dict], output_dir: Path):
    """Espectrograma centrado en el instante de maxima energia por captura.

    Muestra una ventana de +/-250 ms alrededor del momento de mayor actividad
    en la banda 100-450 kHz — equivalente a la vista instantanea del GUI web.
    """
    nperseg  = 512
    noverlap = int(nperseg * 0.75)
    VENTANA_S = 0.5   # ventana total: pico -/+ 250 ms

    espectros_peak = []
    for cap in capturas:
        fs  = cap['fs']
        sig = cap['raw'].astype(np.float64)
        f, t, Sxx = spectrogram(sig, fs=fs, nperseg=nperseg, noverlap=noverlap,
                                 scaling='density')

        # Energia en la banda del sensor por trama de tiempo
        banda = (f >= F_LOW) & (f <= F_HIGH)
        energia_t = Sxx[banda, :].sum(axis=0)
        idx_pico  = int(np.argmax(energia_t))
        t_pico    = t[idx_pico]

        t_ini  = max(0, t_pico - VENTANA_S / 2)
        t_fin  = min(t[-1], t_pico + VENTANA_S / 2)
        t_mask = (t >= t_ini) & (t <= t_fin)

        f_mask = f <= 600_000
        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        espectros_peak.append({
            'f':      f[f_mask],
            't':      t[t_mask],
            'Sxx_db': Sxx_db[:, t_mask],
            't_pico': t_pico,
        })

    reposo_idx = next((i for i, c in enumerate(capturas) if c['condicion'] == 'reposo'), 0)
    vmin = float(np.median(espectros_peak[reposo_idx]['Sxx_db'])) - 3
    vmax = float(max(ep['Sxx_db'].max() for ep in espectros_peak))

    n_cols = min(len(capturas), 3)
    n_rows = (len(capturas) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols,
                              figsize=(7 * n_cols, 4 * n_rows), squeeze=False)

    for idx, (cap, ep) in enumerate(zip(capturas, espectros_peak)):
        ax   = axes[idx // n_cols][idx % n_cols]
        cond = cap['condicion']
        t_rel = (ep['t'] - ep['t_pico']) * 1000   # ms relativo al pico

        im = ax.pcolormesh(t_rel, ep['f'] / 1000, ep['Sxx_db'],
                           shading='gouraud', cmap='inferno',
                           vmin=vmin, vmax=vmax)
        ax.axhline(F_LOW  / 1000, color='cyan', linewidth=0.9,
                   linestyle='--', alpha=0.8, label='100 kHz')
        ax.axhline(F_HIGH / 1000, color='cyan', linewidth=0.9,
                   linestyle='--', alpha=0.8, label='450 kHz')
        ax.axvline(0, color='white', linewidth=0.8, linestyle=':', alpha=0.7)
        ax.set_ylabel('Frecuencia [kHz]')
        ax.set_xlabel('Tiempo relativo al pico [ms]')
        ax.set_title(
            f'{cond}  t_pico={ep["t_pico"]*1000:.0f} ms  '
            f'kurtosis={cap["metricas"]["kurtosis"]:.1f}\n{cap["archivo"]}',
            fontsize=8)
        plt.colorbar(im, ax=ax, label='dB/Hz')

    for idx in range(len(capturas), n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    fig.suptitle(
        f'Espectrograma PICO  (±250 ms alrededor del maximo de energia en banda)'
        f'  |  escala [{vmin:.0f}, {vmax:.0f}] dB/Hz',
        fontsize=11, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'espectrograma_peak.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def imprimir_tabla_metricas(capturas: list[dict]):
    """Imprime tabla resumen de metricas en consola."""
    METRICAS = ['rms', 'rms_diferencial', 'energia', 'kurtosis', 'crest_factor', 'conteo_eventos']
    header = f'{"Archivo":<45} {"Condicion":<14} ' + ' '.join(f'{m[:7]:>10}' for m in METRICAS)
    print('\n' + '=' * len(header))
    print(header)
    print('=' * len(header))
    for cap in capturas:
        vals = [cap['metricas'][m] for m in METRICAS]
        row  = f'{cap["archivo"]:<45} {cap["condicion"]:<14} '
        row += ' '.join(f'{v:>10.4g}' for v in vals)
        print(row)
    print('=' * len(header))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dir',  default=str(Path(__file__).parent.parent / 'capturas'),
                   help='Directorio con archivos .h5')
    p.add_argument('--sync', action='store_true',
                   help='Sincronizar capturas desde Red Pitaya antes de analizar')
    args = p.parse_args()

    capturas_dir = Path(args.dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.sync:
        sincronizar_desde_rpi(capturas_dir)

    print(f'\nCargando capturas desde: {capturas_dir}')
    capturas = cargar_capturas(capturas_dir)
    print(f'Total: {len(capturas)} captura(s)\n')

    calcular_rms_diferencial(capturas)
    imprimir_tabla_metricas(capturas)

    print('\nGenerando graficos...')
    plot_senal_raw(capturas, OUTPUT_DIR)
    plot_fft_comparativa(capturas, OUTPUT_DIR)
    plot_espectrograma(capturas, OUTPUT_DIR)
    plot_espectrograma_peak(capturas, OUTPUT_DIR)

    if len(capturas) > 1:
        plot_boxplots_metricas(capturas, OUTPUT_DIR)
    else:
        print('  Boxplot omitido (necesita mas de 1 captura)')

    print(f'\nOutputs en: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
