#!/usr/bin/env python3
"""
acumulado_lote.py — Señal completa de un lote (varias capturas seguidas del
mismo tipo) pegadas en el tiempo real, con la banda/umbral UNIFICADOS de
revisar.py (50-400kHz, kurtosis>=6 — importados directo de revisar.py, asi
que si esa banda vuelve a cambiar este script la sigue sin tocar nada acá).

Dos paneles por lote (mono o dual), mismo eje de tiempo absoluto real:
  - kurtosis por ventana de FA_WINDOW_S (50ms).
  - acumulado: suma corrida del área bajo la curva de |señal filtrada|
    (Riemann, ventanas de FA_WINDOW_S), contando SOLO las ventanas con
    kurtosis>=FA_THRESH — mismo criterio que la pestaña "Acumulado" de
    ver_forma_onda.py, pero pegando todos los archivos del lote en un solo
    acumulado corrido en vez de reiniciar por archivo.

(Tuvo un tercer panel de rms_diferencial autocalibrado — sacado a pedido
del usuario porque no aportaba nada por encima del acumulado; la funcion
que lo calculaba tambien se borro, ver git history si hace falta
recuperarla.)

Un "lote" = todas las repeticiones de un mismo tipo de captura (mismo
mono/dual + decimacion) tomadas de manera seguida. Pasar solo las carpetas
de UN lote a la vez — si se mezclan mono y dual en el mismo llamado, cada
uno se grafica por separado, pero si se mezclan dos decimaciones distintas
del mismo tipo (mono_dec32 + mono_dec64) van a quedar pegadas en la misma
linea aunque sean sesiones distintas (no se detecta ese caso).

Uso:
  .venv/bin/python3 analisis/lote/acumulado_lote.py "carpeta con lote"/*_mono_dec32/
  .venv/bin/python3 analisis/lote/acumulado_lote.py "carpeta con lote"/*_dual_dec64/

Guarda un PNG por lote (mono o dual) en analisis/outputs/acumulado_lote/ con
los dos paneles, e imprime en texto los tramos donde la kurtosis supero el
umbral de arena (hora real ART = UTC-3, la placa corre en UTC) con duracion
y kurtosis pico, mas el total acumulado por canal.

Filtrado: sosfilt (causal, un solo pase) via _bandpass de revisar.py — NO
sosfiltfilt (zero-phase) como ver_forma_onda.py. Se sigue el criterio de
revisar.py (la referencia real de la banda/umbral unificados, ya migrada) en
vez del de ver_forma_onda.py: procesar un lote entero de varios archivos
grandes con filtfilt duplica el costo de filtrado sin cambiar la
clasificacion de forma relevante para esta vista (kurtosis/area por ventana
de 50ms, no la forma de onda punto a punto).

"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# matplotlib (con backend Agg, headless) se importa recien adentro de
# _graficar — NO al nivel de modulo, porque ver_acumulado_lote.py importa
# las funciones de calculo de este archivo (_leer_lote, _armar_serie, etc.)
# para su propia ventana interactiva con backend TkAgg, y matplotlib.use()
# solo puede fijarse una vez por proceso: si este modulo lo fijara a Agg al
# importarse, pisaria el TkAgg que la GUI necesita para el canvas embebido.

sys.path.insert(0, str(Path(__file__).parent.parent))  # analisis/ (donde vive revisar.py)
from revisar import (  # noqa: E402
    _leer_canales_bin, _cargar_info, _recopilar_rutas, _bandpass,
    FA_WINDOW_S, FA_THRESH, V_REF,
)

# Etiqueta de lote reutiliza el mismo regex que timeline_lote.py.
import re  # noqa: E402

ART = timezone(timedelta(hours=-3))

OUT_DIR = Path(__file__).parent.parent / 'outputs' / 'acumulado_lote'

COLOR_K1 = '#2a78d6'
COLOR_K2 = '#1baf7a'
INK_MUTED = '#898781'


def _metricas_por_ventana(sig_f, fs, ventana_s=FA_WINDOW_S):
    """(kurt_w, area_w) por ventana de ventana_s — kurt_w con el mismo
    criterio que _metricas_por_ventana de revisar.py, mas area_w (area bajo
    la curva de |sig_f|, Riemann: area_i = mean(|x|)*ventana_s = sum(|x|)/fs
    — misma formula que _area_por_ventana de ver_forma_onda.py) para el
    panel de acumulado. area_w se calcula ANTES de restar la media (es el
    area de la señal filtrada real, no de la señal centrada que usa kurt)."""
    n_win = int(fs * ventana_s)
    n_total = len(sig_f) // n_win
    if n_total == 0:
        return np.array([]), np.array([])
    mat = sig_f[:n_total * n_win].reshape(n_total, n_win)
    area_w = np.mean(np.abs(mat), axis=1) * ventana_s
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2 = np.mean(mat ** 2, axis=1)
    m4 = np.mean(mat ** 4, axis=1)
    kurt_w = m4 / np.where(m2 > 0, m2 ** 2, 1e-30)
    return kurt_w, area_w


def _t_inicio_archivo(ruta, info, meta):
    """Hora real de inicio del archivo. Preferido: timeCapture del header
    (reloj de HW, header 144 bytes). Fallback: fecha_inicio del JSON de
    sesion (reloj de software, se pisa al arrancar el proceso, menos
    preciso — puede estar unos ms/s adelantado respecto al primer dato
    real, ver relanzar_captura.sh/capturar_stream.py). Identico a
    timeline_lote.py."""
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
    """Devuelve, por archivo en orden cronologico: t_inicio, kurt/area por
    canal (lista de 1 array mono o 2 dual) y dur_real_s."""
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

        kurts, areas = [], []
        for s in señales:
            sig = s.astype(np.float32) * (V_REF / 32767.0)
            sig_f = _bandpass(sig, fs)
            k, a = _metricas_por_ventana(sig_f, fs)
            kurts.append(k)
            areas.append(a)

        items.append({
            'archivo': ruta.name, 't_inicio': t_inicio, 'canales': canales,
            'cond': str(info.get('condicion', '?')), 'decimacion': info.get('decimacion'),
            'fs': fs, 'kurt': kurts, 'area': areas,
            'dur_real_s': meta.get('dur_real_s'),
        })

    items.sort(key=lambda it: it['t_inicio'])
    return items


def _armar_serie(items, canal_idx):
    """Concatena las ventanas de todos los archivos en un solo eje de tiempo
    absoluto, con un NaN en cada hueco real entre archivos (para que
    kurtosis se corte ahi en vez de unir dos momentos que no se grabaron).
    area tambien lleva NaN en el hueco por consistencia de indices con kurt,
    pero no afecta el acumulado: el cumsum del panel de acumulado descarta
    el area de cualquier ventana con kurt<FA_THRESH (NaN incluido, `nan >=
    FA_THRESH` da False) via np.where, asi que un hueco aporta 0 al
    acumulado sin necesidad de un caso especial."""
    tiempos, kurt, area = [], [], []
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
            area.append(np.nan)

        tiempos.extend(t_ventanas)
        kurt.extend(k.tolist())
        area.extend(it['area'][canal_idx].tolist())
        t_fin_anterior = t_fin

    return tiempos, np.array(kurt), np.array(area), huecos


# Un grano de arena golpea el sensor en una sola ventana de 50ms — sin
# fusionar, cada golpe aislado sale como su propio "tramo" de 0.1s y un lote
# de varios minutos termina con decenas de eventos inmanejables. Se fusionan
# tramos activos separados por menos de esto (silencio real, no un hueco
# entre archivos) en un solo evento — representa "una racha de arena", no
# cada grano individual. Identico a timeline_lote.py.
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


def _acumulado(kurt, area, umbral=FA_THRESH):
    """Suma corrida del area de las ventanas con kurtosis>=umbral (huecos y
    ventanas de fondo aportan 0) — mismo criterio que _crear_tab_acumulado
    de ver_forma_onda.py, pegado en un solo acumulado para todo el lote en
    vez de reiniciar por archivo."""
    mask = kurt >= umbral
    area_contada = np.where(mask, area, 0.0)
    return np.cumsum(area_contada, dtype=np.float64), mask


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
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, (ax_k, ax_a) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    t0_total = items[0]['t_inicio'].astimezone(ART)
    t1_total = (items[-1]['t_inicio'] + timedelta(seconds=items[-1].get('dur_real_s') or 60)).astimezone(ART)
    fig.suptitle(
        f'Acumulado {nombre_lote} — {t0_total.strftime("%Y-%m-%d %H:%M")} a '
        f'{t1_total.strftime("%H:%M")} ART ({len(items)} archivos, banda 50-400kHz, umbral kurtosis {FA_THRESH})',
        fontsize=12)

    huecos_totales = []
    notas_acumulado = []
    print(f'\n=== {nombre_lote} ===')
    if canales == 2:
        canales_info = [(0, COLOR_K1, 'ch1 (codo)'), (1, COLOR_K2, 'ch2 (referencia)')]
        for idx, color, etiqueta in canales_info:
            tiempos, kurt, area, huecos = _armar_serie(items, idx)
            huecos_totales = huecos  # mismos huecos para ambos canales
            ax_k.plot(tiempos, kurt, color=color, linewidth=0.8, label=etiqueta)

            acumulado, mask = _acumulado(kurt, area)
            ax_a.step(tiempos, acumulado, where='post', color=color, linewidth=1.2, label=etiqueta)
            n_contadas = int(np.nansum(mask))
            n_total = int((~np.isnan(kurt)).sum())
            total_v = acumulado[-1] if len(acumulado) else 0.0
            notas_acumulado.append(
                f'{etiqueta}: {n_contadas}/{n_total} ventanas ({100 * n_contadas / n_total:.1f}%) — total {total_v:.4f} V·s'
                if n_total else f'{etiqueta}: sin ventanas'
            )

            tramos = _tramos_activos(tiempos, kurt)
            _reportar_tramos(etiqueta, tramos)
        ax_k.legend(fontsize=9)
        ax_a.legend(fontsize=9)
    else:
        tiempos, kurt, area, huecos = _armar_serie(items, 0)
        huecos_totales = huecos
        ax_k.plot(tiempos, kurt, color=COLOR_K1, linewidth=0.8)

        acumulado, mask = _acumulado(kurt, area)
        ax_a.step(tiempos, acumulado, where='post', color=COLOR_K1, linewidth=1.2)
        n_contadas = int(np.nansum(mask))
        n_total = int((~np.isnan(kurt)).sum())
        total_v = acumulado[-1] if len(acumulado) else 0.0
        notas_acumulado.append(
            f'{n_contadas}/{n_total} ventanas ({100 * n_contadas / n_total:.1f}%) — total {total_v:.4f} V·s'
            if n_total else 'sin ventanas'
        )

        tramos = _tramos_activos(tiempos, kurt)
        _reportar_tramos('mono', tramos)

    ax_k.set_yscale('symlog', linthresh=10)
    ax_k.set_ylabel('kurtosis (escala log)')
    ax_k.spines['top'].set_visible(False)
    ax_k.spines['right'].set_visible(False)

    ax_a.set_ylabel('área acumulada (V·s)')
    ax_a.set_xlabel('hora (ART)')
    ax_a.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S', tz=ART))
    ax_a.grid(True, alpha=0.3)
    ax_a.spines['top'].set_visible(False)
    ax_a.spines['right'].set_visible(False)
    ax_a.text(0.01, 0.98, ' | '.join(notas_acumulado), transform=ax_a.transAxes,
              fontsize=8, color=INK_MUTED, va='top')

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
    for nota in notas_acumulado:
        print(f'  acumulado (kurtosis>={FA_THRESH}) {nota}')
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
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)

    rutas = sorted(_recopilar_rutas(argv), key=lambda p: p.name)
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
