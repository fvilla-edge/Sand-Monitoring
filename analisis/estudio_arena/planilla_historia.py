#!/usr/bin/env python3
"""
planilla_historia.py — modelos SIN sensor, solo con la planilla del pozo
(docs/plan_modelo_arena.md sec.10). Es la vara que el sensor tiene que superar.

1. Intervalos entre purgas de toda la historia (desde 18/8): horas, kg, orificio,
   presion boca de pozo y linea, horas en control de separador (caudal de
   liquidos > 0) y caudal medio en control.
2. Desde el ultimo cambio de orificio (20/64, 23/9 09:30) compara, prediciendo
   cada intervalo SOLO con los anteriores (prequential):
     constante, solo horas, ultima tasa, tasa de las ultimas 24 h,
     decaimiento exponencial, decaimiento + horas en control.

La columna "Produccion solidos kg/hora" de la planilla NO se usa: es la purga
repartida hacia atras entre las horas del intervalo (10 kg / 18 h = 0.56).

Uso:
    .venv/bin/python analisis/estudio_arena/planilla_historia.py PLANILLA.csv [--tabla]
"""
import argparse, csv, re, datetime as D
import numpy as np
from scipy.optimize import curve_fit

CAMBIO_CHOKE = D.datetime(2026, 9, 23, 10)   # 20/64 desde 23/9 09:30 local (planilla)
MIN_PREVIOS = 8                              # intervalos antes de empezar a predecir


def num(s):
    try:
        return float(s.replace('.', '').replace(',', '.')) if s not in ('', '-') else np.nan
    except ValueError:
        return np.nan


def leer_filas(planilla):
    filas = []
    for x in list(csv.reader(open(planilla, encoding='utf-8', errors='replace')))[12:]:
        try:
            t = D.datetime.strptime(x[0], '%d-%m-%y %H:%M')
        except ValueError:
            continue
        filas.append(dict(t=t, orif=num(x[1]), pb=num(x[2]), pl=num(x[4]), liq=num(x[10]), c=x[36]))
    return filas


def leer(planilla):
    filas = leer_filas(planilla)
    purgas = []
    for i, x in enumerate(filas):
        if re.search('purga', x['c'], re.I):
            m = re.findall(r'(\d+)\s*kg', x['c'], re.I)
            kg = float(m[0]) if m else (0.0 if re.search('sin aporte', x['c'], re.I) else np.nan)
            purgas.append((i, kg))
    inter = []
    for (i0, _), (i1, kg) in zip(purgas, purgas[1:]):
        seg = filas[i0 + 1:i1 + 1]
        h = (filas[i1]['t'] - filas[i0]['t']).total_seconds() / 3600
        if h <= 0:
            continue
        ctrl = [s['liq'] for s in seg if s['liq'] > 0]
        inter.append(dict(ini=filas[i0]['t'], fin=filas[i1]['t'], h=h, kg=kg,
                          orif64=np.nanmean([s['orif'] for s in seg]) / 25.4 * 64,
                          pb=np.nanmean([s['pb'] for s in seg]), pl=np.nanmean([s['pl'] for s in seg]),
                          hctrl=len(ctrl), liq=np.mean(ctrl) if ctrl else np.nan))
    return inter


def m_exp(X, A, tau):
    t, h = X
    return A * np.exp(-t / tau) * h


def m_exp_ctrl(X, A, tau, fc):
    t, h, hc = X
    return A * np.exp(-t / tau) * ((h - hc) + fc * hc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('planilla'); ap.add_argument('--tabla', action='store_true')
    a = ap.parse_args()
    inter = leer(a.planilla)
    if a.tabla:
        print('inicio       fin             h    kg  kg/h orif/64 pBoca  pLin hctrl liq m3/h')
        for o in inter:
            print('%s  %s %5.1f %5.0f %5.2f %5.1f %6.0f %5.0f %3d %6.2f' % (
                o['ini'].strftime('%d/%m %H:%M'), o['fin'].strftime('%d/%m %H:%M'), o['h'], o['kg'],
                o['kg'] / o['h'], o['orif64'], o['pb'], o['pl'], o['hctrl'], o['liq']))
    con_kg = [o for o in inter if not np.isnan(o['kg'])]
    print('%d intervalos con kg; %d con arena; arena total %.0f kg' % (
        len(con_kg), sum(o['kg'] > 0 for o in con_kg), sum(o['kg'] for o in con_kg)))

    I = [o for o in con_kg if o['ini'] > CAMBIO_CHOKE]
    t = np.array([((o['ini'] - CAMBIO_CHOKE).total_seconds() / 3600 + o['h'] / 2) / 24 for o in I])
    h = np.array([o['h'] for o in I]); kg = np.array([o['kg'] for o in I]); hc = np.array([o['hctrl'] for o in I])
    print('\nDesde el orificio 20/64 (%s): %d intervalos' % (CAMBIO_CHOKE.strftime('%d/%m %H:%M'), len(I)))
    c = kg[hc >= 4] / h[hc >= 4]; s = kg[hc <= 1] / h[hc <= 1]
    print('  kg/h con >= 4 h de control: media %.2f (n=%d)   con <= 1 h: media %.2f (n=%d)' % (c.mean(), len(c), s.mean(), len(s)))
    pe = curve_fit(m_exp_ctrl, (t, h, hc), kg, p0=[3, 5, .5], bounds=([0, .5, 0], [50, 100, 3]))[0]
    print('  ajuste con todo: %.2f kg/h * exp(-dias/%.1f), fraccion en horas de control %.2f' % tuple(pe))

    def exp_c(i):
        p = curve_fit(m_exp_ctrl, (t[:i], h[:i], hc[:i]), kg[:i], p0=[3, 5, .5],
                      bounds=([0, .5, 0], [50, 100, 3]), maxfev=20000)[0]
        return m_exp_ctrl((t[i], h[i], hc[i]), *p)
    modelos = {
        'constante (media previa)': lambda i: kg[:i].mean(),
        'solo horas (tasa previa)': lambda i: kg[:i].sum() / h[:i].sum() * h[i],
        'ultima tasa * horas': lambda i: kg[i - 1] / h[i - 1] * h[i],
        'tasa ultimas 24 h * horas': lambda i: kg[i - 2:i].sum() / h[i - 2:i].sum() * h[i],
        'decaimiento exp': lambda i: m_exp((t[i], h[i]), *curve_fit(m_exp, (t[:i], h[:i]), kg[:i], p0=[3, 5], maxfev=20000)[0]),
        'decaimiento exp + control': exp_c,
    }
    print('\nPrequential (cada intervalo con los anteriores), error medio absoluto:')
    print('  %-28s %8s %14s' % ('modelo', 'todos', 'desde 29/9'))
    pred = {}
    for nom, f in modelos.items():
        p = np.array([f(i) for i in range(MIN_PREVIOS, len(I))]); pred[nom] = p
        e = np.abs(p - kg[MIN_PREVIOS:])
        print('  %-28s %6.1f kg %10.1f kg' % (nom, e.mean(), e[-7:].mean()))
    print('\nUltimos 7 (los que tienen sensor):')
    print('  fin         real ' + ' '.join('%8s' % n.split()[0][:8] for n in modelos))
    for j in range(len(I) - 7, len(I)):
        print('  %s %5.0f ' % (I[j]['fin'].strftime('%d/%m %H:%M'), kg[j]) +
              ' '.join('%8.1f' % pred[n][j - MIN_PREVIOS] for n in modelos))


if __name__ == '__main__':
    main()
