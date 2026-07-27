#!/usr/bin/env python3
"""
graficar.py — Graficos de barras para demo, mismas metricas que revisar.py
(kurtosis, rms_diferencial, crest factor). No reemplaza revisar.py (que sigue
siendo la fuente de verdad en texto) — esto es solo la vista grafica.

Uso:
  .venv/bin/python3 analisis/graficar.py datos_campo/
  .venv/bin/python3 analisis/graficar.py campo_reposo_*.bin campo_con_arena_*.bin

Guarda un PNG por grupo (mono/dual) en analisis/outputs/graficos/.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from revisar import (
    _calcular, _recopilar_rutas,
    _agregar_rms_diferencial_mono, _agregar_rms_diferencial_dual,
    _detectar_mono, _detectar_dual,
)

COLOR_REPOSO = '#2a78d6'   # categorical slot 1 (blue)
COLOR_ARENA  = '#eb6834'   # categorical slot 2 (orange)
COLOR_RUIDO  = '#e34948'   # categorical slot 8 (red) — RUIDO COMUN, solo dual
COLOR_CH2    = '#1baf7a'   # categorical slot 3 (aqua) — canal 2 en dual
INK_MUTED    = '#898781'
INK_SECOND   = '#52514e'

OUT_DIR = Path(__file__).parent / 'outputs' / 'graficos'


def _quitar_bordes(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='x', labelsize=8)


def _color_mono(r):
    return COLOR_REPOSO if _detectar_mono(r) == 'reposo' else COLOR_ARENA


def _color_dual(r):
    det = _detectar_dual(r)
    if det == '*** ARENA ***':
        return COLOR_ARENA
    if det == 'RUIDO COMUN':
        return COLOR_RUIDO
    return COLOR_REPOSO


def _graficar_mono(resultados):
    modo = _agregar_rms_diferencial_mono(resultados) is not None
    resultados = sorted(resultados, key=lambda r: (r['cond'], r['archivo']))
    etiquetas = [f"{r['cond']}\n#{r['chunk']:04d}" for r in resultados]
    colores   = [_color_mono(r) for r in resultados]
    x = range(len(resultados))

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(13, 5))
    fig.suptitle('Deteccion de arena — mono (azul=reposo, naranja=arena)', fontsize=12)

    ax1.bar(x, [r['kurt'] for r in resultados], color=colores)
    ax1.axhline(20, color=INK_SECOND, linestyle='--', linewidth=1.5)
    ax1.text(0, 20, ' umbral arena', color=INK_SECOND, fontsize=8, va='bottom')
    ax1.set_title('Kurtosis')

    ax2.bar(x, [r['crest'] for r in resultados], color=colores)
    ax2.set_title('Crest factor')
    ax2.text(0.02, 0.95, 'referencia reposo: ~5-6', transform=ax2.transAxes,
              fontsize=8, color=INK_MUTED, va='top')

    rd_vals = [r['rms_dif'] if r['rms_dif'] is not None else 0 for r in resultados]
    ax3.bar(x, rd_vals, color=colores)
    ax3.axhline(0.1, color=INK_MUTED, linestyle=':', linewidth=1)
    ax3.axhline(0.4, color=INK_MUTED, linestyle=':', linewidth=1)
    ax3.set_title('RMS diferencial')
    if not modo:
        ax3.text(0.02, 0.95, 'sin "reposo" en el lote: N/A -> 0', transform=ax3.transAxes,
                  fontsize=8, color=INK_MUTED, va='top')

    for ax in (ax1, ax2, ax3):
        ax.set_xticks(list(x))
        ax.set_xticklabels(etiquetas)
        _quitar_bordes(ax)

    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / 'metricas_mono.png'
    fig.savefig(out, dpi=150)
    print(f'[OK] {out}')


def _graficar_dual(resultados):
    _, _, modo = _agregar_rms_diferencial_dual(resultados)
    resultados = sorted(resultados, key=lambda r: (r['cond'], r['chunk']))
    etiquetas = [f"{r['cond']}\n#{r['chunk']:04d}" for r in resultados]
    x = range(len(resultados))
    ancho = 0.35

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle('Deteccion de arena — dual (ch1=codo, ch2=referencia)', fontsize=12)

    ax1.bar([i - ancho/2 for i in x], [r['k1'] for r in resultados], ancho, color=COLOR_REPOSO, label='ch1')
    ax1.bar([i + ancho/2 for i in x], [r['k2'] for r in resultados], ancho, color=COLOR_CH2, label='ch2')
    ax1.axhline(20, color=INK_SECOND, linestyle='--', linewidth=1.5)
    ax1.set_title('Kurtosis')
    ax1.legend(fontsize=8)

    ax2.bar([i - ancho/2 for i in x], [r['cf1'] for r in resultados], ancho, color=COLOR_REPOSO, label='ch1')
    ax2.bar([i + ancho/2 for i in x], [r['cf2'] for r in resultados], ancho, color=COLOR_CH2, label='ch2')
    ax2.set_title('Crest factor')
    ax2.legend(fontsize=8)

    rd1 = [r['rd1'] if r['rd1'] is not None else 0 for r in resultados]
    rd2 = [r['rd2'] if r['rd2'] is not None else 0 for r in resultados]
    ax3.bar([i - ancho/2 for i in x], rd1, ancho, color=COLOR_REPOSO, label='ch1')
    ax3.bar([i + ancho/2 for i in x], rd2, ancho, color=COLOR_CH2, label='ch2')
    ax3.axhline(0.1, color=INK_MUTED, linestyle=':', linewidth=1)
    ax3.axhline(0.4, color=INK_MUTED, linestyle=':', linewidth=1)
    ax3.set_title('RMS diferencial')
    ax3.legend(fontsize=8)
    if modo == 'in-session':
        ax3.text(0.02, 0.95, 'sin "reposo" en el lote: fallback in-session', transform=ax3.transAxes,
                  fontsize=8, color=INK_MUTED, va='top')

    for ax in (ax1, ax2, ax3):
        ax.set_xticks(list(x))
        ax.set_xticklabels(etiquetas)
        _quitar_bordes(ax)

    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / 'metricas_dual.png'
    fig.savefig(out, dpi=150)
    print(f'[OK] {out}')


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
        try:
            resultados.append(_calcular(ruta))
        except Exception as e:
            print(f'[ERROR] {ruta.name}: {e}')

    if not resultados:
        return

    mono = [r for r in resultados if r['canales'] == 1]
    dual = [r for r in resultados if r['canales'] == 2]

    if mono:
        _graficar_mono(mono)
    if dual:
        _graficar_dual(dual)


if __name__ == '__main__':
    main()
