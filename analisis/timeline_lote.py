#!/usr/bin/env python3
"""
timeline_lote.py — Señal completa de un lote (varias capturas seguidas del
mismo tipo), pegadas en el tiempo real, para ver como sube y baja la
kurtosis y encontrar los momentos exactos en que paso arena.

revisar.py da una fila por archivo (kurtosis global de ese chunk solo).
Este script en cambio calcula kurtosis por ventana de 50ms (mismo criterio
que "fraccion_activa" de revisar.py) DENTRO de cada archivo, y pega esas
ventanas de todos los archivos del lote en un solo eje de tiempo absoluto
real — usando timeCapture del header (reloj de HW, no el reloj del
software) para ubicar cada archivo, asi que el hueco real entre chunks
(recarga de bitstream, ~1-2s) tambien queda representado como un corte en
la linea, no disimulado.

Un "lote" = todas las repeticiones de un mismo tipo de captura (mismo
mono/dual + decimacion) tomadas de manera seguida. Pasar solo las carpetas
de UN lote a la vez — si se mezclan mono y dual en el mismo llamado, cada
uno se grafica por separado, pero si se mezclan dos decimaciones distintas
del mismo tipo (mono_dec32 + mono_dec64) van a quedar pegadas en la misma
linea aunque sean sesiones distintas (no se detecta ese caso).

Uso:
  .venv/bin/python3 analisis/timeline_lote.py "carpeta con lote"/*_mono_dec32/
  .venv/bin/python3 analisis/timeline_lote.py "carpeta con lote"/*_dual_dec64/

Guarda un PNG por lote (mono o dual) en analisis/outputs/timeline_lote/ con
dos paneles — kurtosis y rms_diferencial, mismo baseline y formula que
revisar.py (mediana del RMS de los archivos 'reposo' del lote) — e imprime
en texto los tramos donde la kurtosis supero el umbral de arena (hora real
ART = UTC-3, la placa corre en UTC) con duracion y kurtosis pico.
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).parent))
from revisar import (  # noqa: E402
    _leer_canales_bin, _bandpass, _cargar_info, _recopilar_rutas,
    FA_WINDOW_S, FA_THRESH, V_REF,
)

ART = timezone(timedelta(hours=-3))

OUT_DIR = Path(__file__).parent / 'outputs' / 'timeline_lote'

COLOR_K1 = '#2a78d6'
COLOR_K2 = '#1baf7a'
COLOR_ARENA = '#eb6834'
INK_MUTED = '#898781'
INK_SECOND = '#52514e'


def _metricas_por_ventana(sig_f, fs):
    """Kurtosis y RMS por ventana de FA_WINDOW_S (mismas ventanas que
    _fraccion_activa de revisar.py) pero devolviendo el array completo en
    vez de solo el % de ventanas activas."""
    n_win = int(fs * FA_WINDOW_S)
    n_total = len(sig_f) // n_win
    if n_total == 0:
        return np.array([]), np.array([])
    mat = sig_f[:n_total * n_win].reshape(n_total, n_win)
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2 = np.mean(mat ** 2, axis=1)
    m4 = np.mean(mat ** 4, axis=1)
    kurt_w = m4 / np.where(m2 > 0, m2 ** 2, 1e-30)
    rms_w = np.sqrt(m2)
    return kurt_w, rms_w


def _t_inicio_archivo(ruta, info, meta):
    """Hora real de inicio del archivo. Preferido: timeCapture del header
    (reloj de HW, header 144 bytes). Fallback: fecha_inicio del JSON de
    sesion (reloj de software, se pisa al arrancar el proceso, menos
    preciso — puede estar unos ms/s adelantado respecto al primer dato
    real, ver relanzar_captura.sh/capturar_stream.py)."""
    if meta.get('t_inicio_ns') is not None:
        return datetime.fromtimestamp(meta['t_inicio_ns'] / 1e9, tz=timezone.utc)
    fecha = info.get('fecha_inicio')
    if not fecha:
        raise ValueError(f'{ruta.name}: sin timeCapture (header viejo) ni fecha_inicio en el JSON')
    dt = datetime.fromisoformat(fecha)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # la placa corre en Etc/UTC
    return dt


def _leer_lote(rutas):
    """Devuelve, por archivo en orden cronologico: (t_inicio, kurt_por_canal,
    rms_por_canal, canales, dur_real_s). kurt/rms_por_canal es una lista de
    1 array (mono) o 2 arrays (dual)."""
    items = []
    for ruta in rutas:
        info = _cargar_info(ruta)
        canales = int(info.get('canales', 1))
        ch0, ch1, meta = _leer_canales_bin(ruta)
        t_inicio = _t_inicio_archivo(ruta, info, meta)

        if canales == 2:
            fs = float(info.get('fs_hz_por_canal', 125_000_000 / int(info.get('decimacion', 64))))
            señales = [ch0, ch1]
        else:
            fs = float(info['fs_hz'])
            señales = [ch0]

        kurts, rmss = [], []
        for s in señales:
            sig = s.astype(np.float32) * (V_REF / 32767.0)
            sig_f = _bandpass(sig, fs)
            k, r = _metricas_por_ventana(sig_f, fs)
            kurts.append(k)
            rmss.append(r)

        # RMS del archivo entero por canal, derivado de las ventanas (RMS al
        # cuadrado promedia igual que promediar el cuadrado por ventana, ya
        # que todas duran lo mismo) — evita volver a filtrar toda la señal
        # de nuevo solo para el baseline de rms_diferencial.
        rms_archivo = [float(np.sqrt(np.mean(r ** 2))) if len(r) else 0.0 for r in rmss]

        items.append({
            'archivo': ruta.name, 't_inicio': t_inicio, 'canales': canales,
            'cond': str(info.get('condicion', '?')),
            'fs': fs, 'kurt': kurts, 'rms': rmss, 'rms_archivo': rms_archivo,
            'dur_real_s': meta.get('dur_real_s'),
        })

    items.sort(key=lambda it: it['t_inicio'])
    return items


def _armar_serie(items, canal_idx):
    """Concatena las ventanas de todos los archivos en un solo eje de tiempo
    absoluto, con un NaN en cada hueco real entre archivos (para que la
    linea se corte ahi en vez de unir dos momentos que no se grabaron)."""
    tiempos, kurt, rms = [], [], []
    huecos = []
    t_fin_anterior = None

    for it in items:
        k = it['kurt'][canal_idx]
        if len(k) == 0:
            continue
        t0 = it['t_inicio']
        t_ventanas = [t0 + timedelta(seconds=j * FA_WINDOW_S) for j in range(len(k))]
        t_fin = t_ventanas[-1] + timedelta(seconds=FA_WINDOW_S)

        if t_fin_anterior is not None:
            hueco_s = (t0 - t_fin_anterior).total_seconds()
            huecos.append((t_fin_anterior, t0, hueco_s))
            medio = t_fin_anterior + (t0 - t_fin_anterior) / 2
            tiempos.append(medio)
            kurt.append(np.nan)
            rms.append(np.nan)

        tiempos.extend(t_ventanas)
        kurt.extend(k.tolist())
        rms.extend(it['rms'][canal_idx].tolist())
        t_fin_anterior = t_fin

    return tiempos, np.array(kurt), np.array(rms), huecos


# Un grano de arena golpea el sensor en una sola ventana de 50ms — sin
# fusionar, cada golpe aislado sale como su propio "tramo" de 0.1s y un lote
# de varios minutos termina con decenas de eventos inmanejables. Se fusionan
# tramos activos separados por menos de esto (silencio real, no un hueco
# entre archivos) en un solo evento — representa "una racha de arena", no
# cada grano individual. Ajustable si hace falta mas/menos granularidad.
TOLERANCIA_FUSION_S = 2.0


def _tramos_activos(tiempos, kurt, umbral=FA_THRESH, tolerancia_s=TOLERANCIA_FUSION_S):
    """Corridas de ventanas con kurtosis > umbral, fusionando corridas
    separadas por menos de `tolerancia_s` de silencio REAL (sin NaN de por
    medio — un hueco entre archivos nunca se fusiona, aunque sea mas corto
    que la tolerancia, porque ahi no hay dato, no hay forma de saber si
    siguio activo). Devuelve lista de (t_ini, t_fin, dur_s, kurt_pico)."""
    activo = kurt > umbral  # NaN (hueco) da False, nunca cuenta como activo
    tramos = []
    i = 0
    n = len(activo)
    while i < n:
        if not activo[i]:
            i += 1
            continue
        j = i
        while j < n and activo[j]:
            j += 1
        t_ini = tiempos[i]
        t_fin = tiempos[j - 1] + timedelta(seconds=FA_WINDOW_S)
        pico = float(np.max(kurt[i:j]))

        hay_hueco_previo = tramos and np.isnan(kurt[tramos[-1][4]:i]).any()
        if tramos and not hay_hueco_previo and (t_ini - tramos[-1][1]).total_seconds() <= tolerancia_s:
            t_ini_prev, _t_fin_prev, _dur_prev, pico_prev, _j_prev = tramos[-1]
            tramos[-1] = (t_ini_prev, t_fin, (t_fin - t_ini_prev).total_seconds(),
                          max(pico_prev, pico), j)
        else:
            tramos.append((t_ini, t_fin, (t_fin - t_ini).total_seconds(), pico, j))
        i = j

    return [t[:4] for t in tramos]


def _baseline_lote(items, canal_idx):
    """Mismo criterio que revisar.py: mediana del RMS (por archivo) de las
    capturas 'reposo' del lote. Si el lote entero es 'reposo' (caso comun
    acá, todavia no se separaron condiciones), coincide con la mediana de
    todos los archivos. Si el lote no tiene NINGUN archivo 'reposo' (ej. un
    lote armado solo con 'con_arena'), cae a la mediana de todo el lote como
    aproximacion — mismo espiritu que el fallback in-session de revisar.py,
    marcado como tal para no confundirlo con un baseline real."""
    reposo = [it['rms_archivo'][canal_idx] for it in items if it['cond'] == 'reposo']
    if reposo:
        return float(np.median(reposo)), 'reposo'
    todos = [it['rms_archivo'][canal_idx] for it in items]
    return float(np.median(todos)), 'sin "reposo" en el lote, aproximado con la mediana del lote entero'


def _rms_diferencial(rms, baseline):
    if baseline <= 0:
        return np.full_like(rms, np.nan)
    return np.sqrt(np.maximum(0.0, rms ** 2 - baseline ** 2)) / baseline


def _reportar_tramos(nombre_canal, tramos):
    if not tramos:
        print(f'  [{nombre_canal}] ningun tramo con kurtosis > {FA_THRESH} — reposo de punta a punta')
        return
    print(f'  [{nombre_canal}] {len(tramos)} tramo(s) con arena:')
    for t_ini, t_fin, dur_s, pico in tramos:
        ini_art = t_ini.astimezone(ART).strftime('%H:%M:%S')
        fin_art = t_fin.astimezone(ART).strftime('%H:%M:%S')
        print(f'      {ini_art} - {fin_art} ART  ({dur_s:5.1f}s, kurtosis pico {pico:7.1f})')


def _graficar(nombre_lote, items, canales):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, (ax_k, ax_r) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    t0_total = items[0]['t_inicio'].astimezone(ART)
    t1_total = (items[-1]['t_inicio'] + timedelta(seconds=items[-1].get('dur_real_s') or 60)).astimezone(ART)
    fig.suptitle(
        f'Timeline {nombre_lote} — {t0_total.strftime("%Y-%m-%d %H:%M")} a '
        f'{t1_total.strftime("%H:%M")} ART ({len(items)} archivos)', fontsize=12)

    huecos_totales = []
    notas_baseline = []
    print(f'\n=== {nombre_lote} ===')
    if canales == 2:
        canales_info = [(0, COLOR_K1, 'ch1 (codo)'), (1, COLOR_K2, 'ch2 (referencia)')]
        for idx, color, etiqueta in canales_info:
            tiempos, kurt, rms, huecos = _armar_serie(items, idx)
            huecos_totales = huecos  # mismos huecos para ambos canales
            ax_k.plot(tiempos, kurt, color=color, linewidth=0.8, label=etiqueta)

            baseline, modo = _baseline_lote(items, idx)
            rms_dif = _rms_diferencial(rms, baseline)
            ax_r.plot(tiempos, rms_dif, color=color, linewidth=0.8, label=etiqueta)
            notas_baseline.append(f'{etiqueta}: baseline={baseline:.4f}V ({modo})')

            tramos = _tramos_activos(tiempos, kurt)
            for t_ini, t_fin, _dur, _pico in tramos:
                ax_k.axvspan(t_ini, t_fin, color=COLOR_ARENA, alpha=0.25, linewidth=0)
                ax_r.axvspan(t_ini, t_fin, color=COLOR_ARENA, alpha=0.25, linewidth=0)
            _reportar_tramos(etiqueta, tramos)
        ax_k.legend(fontsize=9)
        ax_r.legend(fontsize=9)
    else:
        tiempos, kurt, rms, huecos = _armar_serie(items, 0)
        huecos_totales = huecos
        ax_k.plot(tiempos, kurt, color=COLOR_K1, linewidth=0.8)

        baseline, modo = _baseline_lote(items, 0)
        rms_dif = _rms_diferencial(rms, baseline)
        ax_r.plot(tiempos, rms_dif, color=COLOR_K1, linewidth=0.8)
        notas_baseline.append(f'baseline={baseline:.4f}V ({modo})')

        tramos = _tramos_activos(tiempos, kurt)
        for t_ini, t_fin, _dur, _pico in tramos:
            ax_k.axvspan(t_ini, t_fin, color=COLOR_ARENA, alpha=0.25, linewidth=0)
            ax_r.axvspan(t_ini, t_fin, color=COLOR_ARENA, alpha=0.25, linewidth=0)
        _reportar_tramos('mono', tramos)

    ax_k.axhline(FA_THRESH, color=INK_SECOND, linestyle='--', linewidth=1, label=f'umbral arena ({FA_THRESH})')
    ax_k.set_yscale('symlog', linthresh=10)
    ax_k.set_ylabel('kurtosis (escala log)')
    ax_k.spines['top'].set_visible(False)
    ax_k.spines['right'].set_visible(False)

    ax_r.axhline(0.1, color=INK_MUTED, linestyle=':', linewidth=1)
    ax_r.axhline(0.4, color=INK_MUTED, linestyle=':', linewidth=1)
    ax_r.set_ylabel('rms diferencial')
    ax_r.set_xlabel('hora (ART)')
    ax_r.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S', tz=ART))
    ax_r.spines['top'].set_visible(False)
    ax_r.spines['right'].set_visible(False)
    ax_r.text(0.01, 0.02, ' | '.join(notas_baseline), transform=ax_r.transAxes,
              fontsize=8, color=INK_MUTED, va='bottom')

    dur_huecos = sum(h[2] for h in huecos_totales)
    if huecos_totales:
        ax_k.text(0.01, 0.98,
                  f'{len(huecos_totales)} huecos entre archivos (recarga de bitstream), '
                  f'{dur_huecos:.1f}s sin datos en total — no representan reposo confirmado',
                  transform=ax_k.transAxes, fontsize=8, color=INK_MUTED, va='top')

    fig.tight_layout()
    out = OUT_DIR / f'{nombre_lote}.png'
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'\n[OK] {out}')
    for nota in notas_baseline:
        print(f'  rms_diferencial {nota}')
    if huecos_totales:
        print(f'  Huecos entre archivos: {len(huecos_totales)}, {dur_huecos:.1f}s sin datos en total '
              f'(recarga de bitstream entre chunks — no es reposo confirmado, es tiempo sin medir).')


def _etiqueta_lote(prefijo, primero, ultimo):
    m1 = re.search(r'(\d{8}_\d{6})', primero)
    m2 = re.search(r'(\d{8}_\d{6})', ultimo)
    ini = m1.group(1) if m1 else primero
    fin = m2.group(1)[-6:] if m2 else ultimo
    return f'{prefijo}_{ini}_a_{fin}'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    rutas = sorted(_recopilar_rutas(sys.argv[1:]), key=lambda p: p.name)
    if not rutas:
        print('[!] No se encontraron archivos campo_*.bin')
        sys.exit(1)

    print(f'  leyendo {len(rutas)} archivos...')
    items = _leer_lote(rutas)

    mono = [it for it in items if it['canales'] == 1]
    dual = [it for it in items if it['canales'] == 2]

    if mono:
        etiqueta = _etiqueta_lote('mono', mono[0]['archivo'], mono[-1]['archivo'])
        _graficar(etiqueta, mono, canales=1)
    if dual:
        etiqueta = _etiqueta_lote('dual', dual[0]['archivo'], dual[-1]['archivo'])
        _graficar(etiqueta, dual, canales=2)


if __name__ == '__main__':
    main()
