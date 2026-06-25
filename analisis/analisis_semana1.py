#!/usr/bin/env python3
"""
analisis_semana1.py — Analisis de capturas HDF5 del sistema de deteccion de arena.
Genera espectrogramas, comparaciones de senal y boxplots de metricas.

Uso:
  python3 analisis_semana1.py --dir capturas/semana2
  python3 analisis_semana1.py --sync
"""
import argparse
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, spectrogram

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
F_LOW  = 100_000
F_HIGH = 450_000
ORD    = 4

RPi_HOST   = 'root@192.168.0.55'
RPi_SRC    = '/root/captura_*.h5'
OUTPUT_DIR = Path(__file__).parent / 'outputs'

CONDICION_COLOR = {
    'reposo':       '#2196F3',
    'flujo_limpio': '#4CAF50',
    'baja':         '#FFC107',
    'media':        '#FF9800',
    'alta':         '#F44336',
}
ORDEN_CONDICION = ['reposo', 'flujo_limpio', 'baja', 'media', 'alta']


# ---------------------------------------------------------------------------
# I/O — carga bajo demanda para no saturar RAM con datasets grandes
# ---------------------------------------------------------------------------
def sincronizar_desde_rpi(dest_dir: Path):
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
    """Carga solo metadatos y metricas. La senal raw se lee bajo demanda."""
    archivos = sorted(capturas_dir.glob('*.h5'))
    if not archivos:
        print(f'No se encontraron archivos .h5 en {capturas_dir}')
        sys.exit(1)

    capturas = []
    for ruta in archivos:
        with h5py.File(ruta, 'r') as f:
            mets = {k: float(f['metricas'][k][()]) for k in f['metricas']}
            mets['conteo_eventos'] = int(f['metricas']['conteo_eventos'][()])
            attrs = dict(f.attrs)
        capturas.append({
            'archivo':   ruta.name,
            'ruta':      ruta,
            'metricas':  mets,
            'attrs':     attrs,
            'condicion': str(attrs.get('condicion', 'desconocido')),
            'fs':        float(attrs.get('fs_ef_hz', 1953125.0)),
        })
        print(f'  Cargado: {ruta.name}  ({attrs.get("condicion")})')

    return capturas


def _raw(cap: dict, n: int | None = None) -> np.ndarray:
    """Lee la senal raw de un HDF5. Si n es entero lee solo los primeros n samples."""
    with h5py.File(cap['ruta'], 'r') as f:
        return f['raw_signal'][:n] if n else f['raw_signal'][:]


def _filtro_bp(fs):
    nyq = fs / 2.0
    return butter(ORD, [F_LOW / nyq, F_HIGH / nyq], btype='band')


def calcular_rms_diferencial(capturas: list[dict]):
    """Agrega rms_diferencial: sqrt(max(0, rms²-baseline²)) / baseline (Gao 2015)."""
    reposo = [c for c in capturas if c['condicion'] == 'reposo']
    baseline = float(np.median([c['metricas']['rms'] for c in reposo])) if reposo \
               else float(min(c['metricas']['rms'] for c in capturas))

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
    """Primeros 2 ms — una captura representativa por condicion."""
    por_cond: dict[str, dict] = {}
    for cap in capturas:
        if cap['condicion'] not in por_cond:
            por_cond[cap['condicion']] = cap

    representativas = [por_cond[c] for c in ORDEN_CONDICION if c in por_cond]
    n = len(representativas)
    fig, axes = plt.subplots(n, 1, figsize=(14, 2.5 * n), sharex=False)
    if n == 1:
        axes = [axes]

    for ax, cap in zip(axes, representativas):
        fs     = cap['fs']
        n_show = int(0.002 * fs)
        raw    = _raw(cap, n_show)
        t_ms   = np.arange(len(raw)) / fs * 1000
        color  = CONDICION_COLOR.get(cap['condicion'], 'gray')
        ax.plot(t_ms, raw, color=color, linewidth=0.5, alpha=0.9)
        ax.set_ylabel('V', fontsize=9)
        ax.set_title(
            f'{cap["condicion"]}  |  RMS={cap["metricas"]["rms"]:.4f} V'
            f'  kurtosis={cap["metricas"]["kurtosis"]:.2f}  ({cap["archivo"]})',
            fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Tiempo [ms]')
    fig.suptitle('Senal raw — primeros 2 ms (una captura por condicion)',
                 fontsize=11, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'senal_raw.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_fft_comparativa(capturas: list[dict], output_dir: Path):
    """Max-hold spectrum: maximo de cada bin sobre toda la captura (equivalente GUI web)."""
    nperseg  = 2048
    noverlap = int(nperseg * 0.75)

    fig, ax = plt.subplots(figsize=(14, 6))

    for cap in capturas:
        sig  = _raw(cap).astype(np.float64)
        f, _, Sxx = spectrogram(sig, fs=cap['fs'], nperseg=nperseg,
                                 noverlap=noverlap, scaling='density')
        del sig
        Sxx_db_max = 10 * np.log10(Sxx.max(axis=1) + 1e-20)
        del Sxx
        mask  = f <= 600_000
        color = CONDICION_COLOR.get(cap['condicion'], 'gray')
        ax.plot(f[mask] / 1000, Sxx_db_max[mask],
                color=color, label=cap['condicion'], linewidth=0.8, alpha=0.7)

    ax.axvspan(F_LOW / 1000, F_HIGH / 1000, alpha=0.08, color='yellow',
               label='Banda sensor 100-450 kHz')
    ax.axvline(F_LOW  / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
    ax.axvline(F_HIGH / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
    ax.set_xlabel('Frecuencia [kHz]')
    ax.set_ylabel('PSD pico [dB/Hz]')
    ax.set_title('Espectro pico (max-hold) — maximo por bin sobre toda la captura',
                 fontweight='bold')

    # Leyenda sin duplicados
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    ax.legend([h for h, l in zip(handles, labels) if not (l in seen or seen.add(l))],
              [l for l in labels if l not in seen or not seen.add(l)], fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = output_dir / 'fft_comparativa.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_espectrograma(capturas: list[dict], output_dir: Path):
    """Espectrograma STFT con escala compartida. Dos pasadas para no saturar RAM."""
    nperseg  = 512
    noverlap = int(nperseg * 0.75)

    # Pasada 1: solo stats para determinar escala
    reposo_median = None
    global_max    = -np.inf
    for cap in capturas:
        sig  = _raw(cap).astype(np.float64)
        f, _, Sxx = spectrogram(sig, fs=cap['fs'], nperseg=nperseg,
                                 noverlap=noverlap, scaling='density')
        del sig
        f_mask = f <= 600_000
        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        del Sxx
        if cap['condicion'] == 'reposo' and reposo_median is None:
            reposo_median = float(np.median(Sxx_db))
        global_max = max(global_max, float(Sxx_db.max()))
        del Sxx_db

    vmin = (reposo_median - 3) if reposo_median is not None else (global_max - 60)
    vmax = global_max

    # Pasada 2: plotear
    n_cols = min(len(capturas), 4)
    n_rows = (len(capturas) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols,
                              figsize=(6 * n_cols, 3.5 * n_rows), squeeze=False)

    for idx, cap in enumerate(capturas):
        sig  = _raw(cap).astype(np.float64)
        f, t, Sxx = spectrogram(sig, fs=cap['fs'], nperseg=nperseg,
                                 noverlap=noverlap, scaling='density')
        del sig
        f_mask = f <= 600_000
        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        del Sxx

        ax = axes[idx // n_cols][idx % n_cols]
        im = ax.pcolormesh(t * 1000, f[f_mask] / 1000, Sxx_db,
                           shading='gouraud', cmap='inferno', vmin=vmin, vmax=vmax)
        del Sxx_db
        ax.axhline(F_LOW  / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
        ax.axhline(F_HIGH / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
        ax.set_ylabel('Frec. [kHz]', fontsize=7)
        ax.set_xlabel('Tiempo [ms]', fontsize=7)
        ax.set_title(f'{cap["condicion"]}  kurt={cap["metricas"]["kurtosis"]:.1f}\n'
                     f'{cap["archivo"]}', fontsize=6)
        plt.colorbar(im, ax=ax, label='dB/Hz')

    for idx in range(len(capturas), n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    fig.suptitle(f'Espectrogramas STFT  |  escala [{vmin:.0f}, {vmax:.0f}] dB/Hz',
                 fontsize=10, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'espectrogramas.png'
    plt.savefig(out, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_espectrograma_peak(capturas: list[dict], output_dir: Path):
    """Espectrograma centrado en el instante de maxima energia. Dos pasadas."""
    nperseg   = 512
    noverlap  = int(nperseg * 0.75)
    VENTANA_S = 0.5

    # Pasada 1: encontrar t_pico y stats de escala
    picos      = []
    vmin_stats = []
    global_max = -np.inf

    for cap in capturas:
        sig  = _raw(cap).astype(np.float64)
        f, t, Sxx = spectrogram(sig, fs=cap['fs'], nperseg=nperseg,
                                 noverlap=noverlap, scaling='density')
        del sig
        banda    = (f >= F_LOW) & (f <= F_HIGH)
        idx_pico = int(np.argmax(Sxx[banda, :].sum(axis=0)))
        t_pico   = float(t[idx_pico])
        picos.append(t_pico)

        f_mask = f <= 600_000
        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        del Sxx
        if cap['condicion'] == 'reposo':
            vmin_stats.append(float(np.median(Sxx_db)))
        global_max = max(global_max, float(Sxx_db.max()))
        del Sxx_db

    vmin = (np.median(vmin_stats) - 3) if vmin_stats else (global_max - 60)
    vmax = global_max

    # Pasada 2: plotear ventana alrededor del pico
    n_cols = min(len(capturas), 4)
    n_rows = (len(capturas) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols,
                              figsize=(6 * n_cols, 3.5 * n_rows), squeeze=False)

    for idx, (cap, t_pico) in enumerate(zip(capturas, picos)):
        sig  = _raw(cap).astype(np.float64)
        f, t, Sxx = spectrogram(sig, fs=cap['fs'], nperseg=nperseg,
                                 noverlap=noverlap, scaling='density')
        del sig

        t_ini  = max(0, t_pico - VENTANA_S / 2)
        t_fin  = min(float(t[-1]), t_pico + VENTANA_S / 2)
        t_mask = (t >= t_ini) & (t <= t_fin)
        f_mask = f <= 600_000

        Sxx_db = 10 * np.log10(Sxx[f_mask, :] + 1e-20)
        del Sxx
        t_rel  = (t[t_mask] - t_pico) * 1000

        ax = axes[idx // n_cols][idx % n_cols]
        im = ax.pcolormesh(t_rel, f[f_mask] / 1000, Sxx_db[:, t_mask],
                           shading='gouraud', cmap='inferno', vmin=vmin, vmax=vmax)
        del Sxx_db
        ax.axhline(F_LOW  / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
        ax.axhline(F_HIGH / 1000, color='cyan', linewidth=0.8, linestyle='--', alpha=0.7)
        ax.axvline(0, color='white', linewidth=0.8, linestyle=':', alpha=0.7)
        ax.set_ylabel('Frec. [kHz]', fontsize=7)
        ax.set_xlabel('t relativo [ms]', fontsize=7)
        ax.set_title(f'{cap["condicion"]}  t={t_pico*1000:.0f}ms  '
                     f'kurt={cap["metricas"]["kurtosis"]:.1f}\n{cap["archivo"]}',
                     fontsize=6)
        plt.colorbar(im, ax=ax, label='dB/Hz')

    for idx in range(len(capturas), n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    fig.suptitle(f'Espectrograma PICO (±250 ms)  |  escala [{vmin:.0f}, {vmax:.0f}] dB/Hz',
                 fontsize=10, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'espectrograma_peak.png'
    plt.savefig(out, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_boxplots_metricas(capturas: list[dict], output_dir: Path):
    """Boxplot de cada metrica agrupada por condicion."""
    METRICAS = ['rms', 'rms_diferencial', 'energia', 'kurtosis', 'crest_factor']
    LABELS   = ['RMS [V]', 'RMS dif.', 'Energia [V²]', 'Kurtosis', 'Crest Factor']

    por_cond: dict[str, dict] = {}
    for cap in capturas:
        cond = cap['condicion']
        if cond not in por_cond:
            por_cond[cond] = {m: [] for m in METRICAS}
        for m in METRICAS:
            por_cond[cond][m].append(cap['metricas'][m])

    condiciones = [c for c in ORDEN_CONDICION if c in por_cond] or list(por_cond)

    fig, axes = plt.subplots(1, len(METRICAS), figsize=(4 * len(METRICAS), 5))
    for ax, met, label in zip(axes, METRICAS, LABELS):
        datos  = [por_cond[c][met] for c in condiciones]
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


def plot_scatter_masa(capturas: list[dict], output_dir: Path):
    """Kurtosis, crest factor y RMS diferencial vs masa de arena [g]."""
    con_masa = [c for c in capturas if float(c['attrs'].get('masa_arena_g', -1)) >= 0]
    if len(con_masa) < 2:
        print('  Scatter masa omitido (necesita al menos 2 capturas con --masa_g)')
        return

    METRICAS = [('kurtosis', 'Kurtosis'),
                ('crest_factor', 'Crest Factor'),
                ('rms_diferencial', 'RMS diferencial [adim]')]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (met, label) in zip(axes, METRICAS):
        masas  = [float(c['attrs']['masa_arena_g']) for c in con_masa]
        vals   = [c['metricas'][met] for c in con_masa]
        colors = [CONDICION_COLOR.get(c['condicion'], 'gray') for c in con_masa]
        ax.scatter(masas, vals, c=colors, s=50, zorder=3, alpha=0.8)
        ax.set_xlabel('Masa de arena [g]')
        ax.set_ylabel(label)
        ax.set_title(label, fontsize=10)
        ax.grid(True, alpha=0.3)

    fig.suptitle('Metricas vs masa de arena — validacion de monotonicidad',
                 fontsize=11, fontweight='bold')
    plt.tight_layout()
    out = output_dir / 'scatter_masa.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def imprimir_tabla_metricas(capturas: list[dict]):
    METRICAS = ['rms', 'rms_diferencial', 'energia', 'kurtosis', 'crest_factor', 'conteo_eventos']
    header   = f'{"Archivo":<45} {"Condicion":<14} ' + \
               ' '.join(f'{m[:7]:>10}' for m in METRICAS)
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
    p.add_argument('--dir',  default=str(Path(__file__).parent.parent / 'capturas' / 'semana1'),
                   help='Directorio con archivos .h5')
    p.add_argument('--sync', action='store_true',
                   help='Sincronizar desde Red Pitaya antes de analizar')
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
    plot_scatter_masa(capturas, OUTPUT_DIR)

    if len(capturas) > 1:
        plot_boxplots_metricas(capturas, OUTPUT_DIR)

    print(f'\nOutputs en: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
