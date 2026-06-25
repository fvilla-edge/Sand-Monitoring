#!/usr/bin/env python3
"""
analisis_semana2.py — Metricas escalares + metricas temporales (fraccion activa).
Lee raw_signal de a un archivo a la vez para no saturar RAM.

Uso:
  python3 analisis/analisis_semana2.py --dir capturas/semana2
"""
import argparse
import sys
from pathlib import Path

import h5py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.signal import butter, filtfilt
from scipy.stats import kurtosis as sp_kurtosis

OUTPUT_DIR = Path(__file__).parent / 'outputs_semana2'

F_LOW  = 100_000
F_HIGH = 450_000
ORD    = 4

VENTANA_S   = 0.05   # 50 ms por ventana
UMBRAL_KURT = 20.0   # umbral kurtosis por ventana para considerarla "activa"

CONDICION_COLOR = {
    'reposo': '#2196F3',
    'baja':   '#FFC107',
    'media':  '#FF9800',
    'alta':   '#F44336',
}
ORDEN = ['reposo', 'baja', 'media', 'alta']


# ---------------------------------------------------------------------------
# Carga — scalars del HDF5, sin raw_signal
# ---------------------------------------------------------------------------
def cargar(capturas_dir: Path) -> list[dict]:
    archivos = sorted(capturas_dir.glob('*.h5'))
    if not archivos:
        print(f'No se encontraron .h5 en {capturas_dir}')
        sys.exit(1)

    datos = []
    for ruta in archivos:
        with h5py.File(ruta, 'r') as f:
            mets  = {k: float(f['metricas'][k][()]) for k in f['metricas']}
            mets['conteo_eventos'] = int(f['metricas']['conteo_eventos'][()])
            attrs = dict(f.attrs)
        datos.append({
            'archivo':   ruta.name,
            'ruta':      ruta,
            'condicion': str(attrs.get('condicion', 'desconocido')),
            'masa_g':    float(attrs.get('masa_arena_g', -1.0)),
            'fs':        float(attrs.get('fs_ef_hz', 1_953_125.0)),
            'metricas':  mets,
        })
    return datos


def agregar_rms_diferencial(datos: list[dict]):
    baseline = float(np.median(
        [d['metricas']['rms'] for d in datos if d['condicion'] == 'reposo']
    ))
    for d in datos:
        rms = d['metricas']['rms']
        d['metricas']['rms_diferencial'] = float(
            np.sqrt(max(0.0, rms**2 - baseline**2)) / baseline
        )
    return baseline


# ---------------------------------------------------------------------------
# Metricas temporales — lee raw_signal de a un archivo
# ---------------------------------------------------------------------------
def calcular_metricas_temporales(datos: list[dict]):
    """
    Filtra la senal (misma banda que capturar.py) y divide en ventanas de
    VENTANA_S segundos. Guarda fraccion_activa y el array de kurtosis por
    ventana (kurts_por_ventana) para el grafico de timeline.
    """
    print(f'\nMetricas temporales (ventana={VENTANA_S*1000:.0f}ms, umbral_kurt={UMBRAL_KURT:.0f}):')

    for d in datos:
        fs        = d['fs']
        nyq       = fs / 2.0
        b, a      = butter(ORD, [F_LOW / nyq, F_HIGH / nyq], btype='band')
        n_ventana = int(VENTANA_S * fs)

        with h5py.File(d['ruta'], 'r') as f:
            sig = f['raw_signal'][:].astype(np.float64)

        sf = filtfilt(b, a, sig)
        del sig

        n_vent  = len(sf) // n_ventana
        bloques = sf[:n_vent * n_ventana].reshape(n_vent, n_ventana)
        kurts   = np.array([float(sp_kurtosis(row, fisher=False)) for row in bloques])
        del sf, bloques

        n_act = int(np.sum(kurts > UMBRAL_KURT))
        d['metricas']['fraccion_activa'] = float(n_act / n_vent)
        d['kurts_por_ventana']           = kurts

        print(f'  {d["archivo"]}  {d["condicion"]:<8}  '
              f'{n_act:>3}/{n_vent} ventanas activas  '
              f'({n_act / n_vent * 100:.0f}%)')


# ---------------------------------------------------------------------------
# Tabla resumen
# ---------------------------------------------------------------------------
def imprimir_tabla(datos: list[dict], baseline_rms: float):
    METS = ['kurtosis', 'crest_factor', 'fraccion_activa', 'rms_diferencial']
    print(f'\nBaseline RMS (reposo): {baseline_rms * 1000:.3f} mV\n')

    por_cond = {c: [] for c in ORDEN}
    for d in datos:
        if d['condicion'] in por_cond:
            por_cond[d['condicion']].append(d)

    header = f'{"Condicion":<10} {"n":>3}  ' + \
             '  '.join(f'{m[:16]:>18}' for m in METS)
    sep = '-' * len(header)
    print(sep)
    print(header)
    print(sep)
    for cond in ORDEN:
        rows = por_cond.get(cond, [])
        if not rows:
            continue
        line = f'{cond:<10} {len(rows):>3}  '
        for m in METS:
            vals = [r['metricas'][m] for r in rows]
            line += f'  {np.mean(vals):>9.2f}±{np.std(vals):<6.2f}'
        print(line)
    print(sep)


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------
def plot_boxplots(datos: list[dict], out_dir: Path):
    METS   = ['kurtosis',  'crest_factor', 'fraccion_activa']
    LABELS = ['Kurtosis',  'Crest Factor', 'Fraccion activa\n(% tiempo con arena)']
    LOG    = [True,         False,          False]

    por_cond = {c: {m: [] for m in METS} for c in ORDEN}
    for d in datos:
        c = d['condicion']
        if c in por_cond:
            for m in METS:
                por_cond[c][m].append(d['metricas'][m])

    presentes = [c for c in ORDEN if por_cond[c][METS[0]]]

    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    for ax, met, label, use_log in zip(axes, METS, LABELS, LOG):
        datos_plot = [por_cond[c][met] for c in presentes]
        colors     = [CONDICION_COLOR[c] for c in presentes]

        bp = ax.boxplot(datos_plot, patch_artist=True, tick_labels=presentes,
                        flierprops=dict(marker='o', markersize=5, alpha=0.6))
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.75)

        if use_log:
            ax.set_yscale('log')
            ax.yaxis.set_major_formatter(ticker.LogFormatterSciNotation())

        ax.set_title(label, fontsize=11, fontweight='bold')
        ax.tick_params(axis='x', rotation=20)
        ax.grid(True, alpha=0.3, axis='y', which='both')

    fig.suptitle('Metricas por condicion — semana 2 (n=10 por clase)',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = out_dir / 'boxplots_semana2.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_timeline(datos: list[dict], out_dir: Path):
    """
    Kurtosis por ventana a lo largo del tiempo — una captura representativa
    por condicion (la mas cercana a la mediana de fraccion_activa de su clase).
    Muestra claramente bursts cortos vs actividad sostenida.
    """
    # Elegir representante: archivo con fraccion_activa mas cercana a la mediana
    por_cond: dict[str, list] = {c: [] for c in ORDEN}
    for d in datos:
        if d['condicion'] in por_cond and 'kurts_por_ventana' in d:
            por_cond[d['condicion']].append(d)

    representantes = []
    for cond in ORDEN:
        grupo = por_cond[cond]
        if not grupo:
            continue
        mediana = float(np.median([g['metricas']['fraccion_activa'] for g in grupo]))
        rep = min(grupo, key=lambda x: abs(x['metricas']['fraccion_activa'] - mediana))
        representantes.append(rep)

    n = len(representantes)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3 * n), sharex=False)
    if n == 1:
        axes = [axes]

    for ax, d in zip(axes, representantes):
        kurts    = d['kurts_por_ventana']
        n_vent   = len(kurts)
        t_centro = (np.arange(n_vent) + 0.5) * VENTANA_S  # tiempo al centro de cada ventana [s]
        color    = CONDICION_COLOR.get(d['condicion'], 'gray')
        frac     = d['metricas']['fraccion_activa']

        ax.bar(t_centro, kurts, width=VENTANA_S * 0.9,
               color=color, alpha=0.8, linewidth=0)
        ax.axhline(UMBRAL_KURT, color='black', linewidth=1.2,
                   linestyle='--', label=f'umbral = {UMBRAL_KURT:.0f}')
        ax.set_ylabel('Kurtosis', fontsize=9)
        ax.set_title(
            f'{d["condicion"]}  |  fraccion activa = {frac*100:.0f}%  '
            f'({d["archivo"]})',
            fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')
        ax.legend(fontsize=8, loc='upper right')

    axes[-1].set_xlabel('Tiempo [s]')
    fig.suptitle(
        f'Kurtosis por ventana ({VENTANA_S*1000:.0f} ms) — un archivo representativo por condicion',
        fontsize=11, fontweight='bold')
    plt.tight_layout()
    out = out_dir / 'timeline_kurtosis.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


def plot_scatter_masa(datos: list[dict], out_dir: Path):
    con_masa = [d for d in datos if d['masa_g'] >= 0]
    if len(con_masa) < 2:
        return

    masas  = np.array([d['masa_g'] for d in con_masa])
    conds  = [d['condicion']        for d in con_masa]
    colors = [CONDICION_COLOR.get(c, 'gray') for c in conds]

    METS   = ['kurtosis',  'fraccion_activa', 'rms_diferencial']
    LABELS = ['Kurtosis',  'Fraccion activa', 'RMS diferencial']
    LOG    = [True,         False,             True]

    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    for ax, met, label, use_log in zip(axes, METS, LABELS, LOG):
        vals = np.array([d['metricas'][met] for d in con_masa])
        ax.scatter(masas, vals, c=colors, s=60, zorder=3, alpha=0.8,
                   edgecolors='white', linewidths=0.4)
        for masa_val in np.unique(masas):
            idx = masas == masa_val
            ax.plot(masa_val, np.median(vals[idx]), marker='D', color='black',
                    markersize=9, zorder=4, alpha=0.6)
        if use_log:
            ax.set_yscale('log')
        ax.set_xlabel('Masa de arena [g]')
        ax.set_ylabel(label)
        ax.set_title(label, fontsize=10, fontweight='bold')
        ax.set_xticks([0, 3, 10, 25])
        ax.grid(True, alpha=0.3, which='both')

    handles = [plt.Line2D([0], [0], marker='o', color='w',
                          markerfacecolor=CONDICION_COLOR[c], markersize=9, label=c)
               for c in ORDEN if c in set(conds)]
    handles.append(plt.Line2D([0], [0], marker='D', color='black',
                               markersize=9, label='mediana', alpha=0.6))
    fig.legend(handles=handles, loc='lower center', ncol=len(handles),
               fontsize=9, bbox_to_anchor=(0.5, -0.04))

    fig.suptitle('Metricas vs masa de arena — semana 2', fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = out_dir / 'scatter_masa_semana2.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Guardado: {out.name}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dir', default='capturas/semana2',
                   help='Directorio con archivos .h5 (default: capturas/semana2)')
    args = p.parse_args()

    capturas_dir = Path(args.dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f'Cargando desde: {capturas_dir}')
    datos = cargar(capturas_dir)
    print(f'  {len(datos)} capturas cargadas')

    baseline = agregar_rms_diferencial(datos)
    calcular_metricas_temporales(datos)
    imprimir_tabla(datos, baseline)

    print('\nGenerando graficos...')
    plot_boxplots(datos, OUTPUT_DIR)
    plot_timeline(datos, OUTPUT_DIR)
    plot_scatter_masa(datos, OUTPUT_DIR)

    print(f'\nOutputs en: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
