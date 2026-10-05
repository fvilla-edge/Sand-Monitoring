#!/usr/bin/env python3
"""
sensor_vs_referencia.py — paso 1 de docs/plan_modelo_arena.md sec.10: ¿el sensor
explica lo que le erra la mejor referencia SIN sensor?

Referencia: tasa de las ultimas 24 h (2 intervalos previos de la planilla) x horas.
Residuo = kg real - referencia. Para cada medida simple del sensor por intervalo
(sobre todas las horas y solo sobre las horas FUERA de control de separador,
porque en control casi no llega arena al BBS):
  - correlacion de Spearman con el residuo y p exacto por permutacion,
  - LOO de "referencia + c + beta * medida" contra la referencia sola.
Con 7 intervalos y ~10 medidas, un p < 0.05 suelto puede ser azar.

Uso:
    .venv/bin/python analisis/estudio_arena/sensor_vs_referencia.py PLANILLA.csv CARPETA_CSV [...]
"""
import argparse, itertools, os, sys
import datetime as D
import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(__file__))
from metricas_purgas import leer_ventanas
import planilla_historia as ph

HUSO = D.timedelta(hours=-3)
MEDIANA_ACTIVA = 2.978          # umbral_reposo.py


def medidas(T, K, t0, t1, fuera):
    """t0, t1 locales; fuera = mascara de ventanas fuera de control."""
    a = (t0 - HUSO).replace(tzinfo=D.timezone.utc).timestamp()
    b = (t1 - HUSO).replace(tzinfo=D.timezone.utc).timestamp()
    m = (T >= a) & (T < b)
    res, cob = {}, m.sum() * 0.05 / 3600
    for suf, mm in (('', m), (' fuera', m & fuera)):
        k = K[mm]
        res['n k>3.5' + suf] = (k > 3.5).sum()
        res['n k>3.05' + suf] = (k > 3.05).sum()
        res['n k>10' + suf] = (k > 10).sum()
        mi = (T[mm] // 60).astype(np.int64)
        if len(mi):
            u, inv = np.unique(mi, return_inverse=True)
            orden = np.argsort(inv, kind='stable')
            med = [np.median(x) for x in np.split(k[orden], np.cumsum(np.bincount(inv))[:-1])]
            res['min activos' + suf] = int((np.array(med) > MEDIANA_ACTIVA).sum())
        else:
            res['min activos' + suf] = 0
    return res, cob


def p_perm(x, y):
    r0 = abs(spearmanr(x, y)[0])
    rs = [abs(spearmanr(x, np.array(p))[0]) for p in itertools.permutations(y)]
    return np.mean(np.array(rs) >= r0 - 1e-12)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('planilla'); ap.add_argument('carpetas', nargs='+')
    a = ap.parse_args()
    inter = [o for o in ph.leer(a.planilla) if not np.isnan(o['kg'])]
    filas = ph.leer_filas(a.planilla)
    T, _, K = leer_ventanas(a.carpetas)
    # control: la fila de la hora H (liq > 0) cubre la hora local [H-1, H)
    ctrl_ini = [((f['t'] - D.timedelta(hours=1)) - HUSO).replace(tzinfo=D.timezone.utc).timestamp()
                for f in filas if f['liq'] > 0]
    fuera = ~np.isin((T // 3600).astype(np.int64), (np.array(ctrl_ini) // 3600).astype(np.int64))
    t_ini = (D.datetime.fromtimestamp(T[0], D.timezone.utc) + HUSO).replace(tzinfo=None)

    filas_out = []
    for i in range(2, len(inter)):
        o = inter[i]
        if o['ini'] < t_ini:
            continue
        prev = inter[i - 2:i]
        ref = sum(p['kg'] for p in prev) / sum(p['h'] for p in prev) * o['h']
        med, cob = medidas(T, K, o['ini'], o['fin'], fuera)
        if cob < 0.9 * o['h']:
            continue
        filas_out.append(dict(o=o, ref=ref, res=o['kg'] - ref, **med))
    n = len(filas_out)
    kg = np.array([f['o']['kg'] for f in filas_out]); ref = np.array([f['ref'] for f in filas_out])
    res = kg - ref
    nombres = [k for k in filas_out[0] if k not in ('o', 'ref', 'res')]
    print('%d intervalos completos con sensor\n' % n)
    print('fin          kg   ref  resid ' + ' '.join('%9s' % k.replace(' fuera', '*')[:9] for k in nombres))
    for f in filas_out:
        print('%s %4.0f %5.1f %6.1f ' % (f['o']['fin'].strftime('%d/%m %H:%M'), f['o']['kg'], f['ref'], f['res']) +
              ' '.join('%9d' % f[k] for k in nombres))
    print('(* = solo horas fuera de control de separador)\n')
    print('referencia sola: error medio %.2f kg' % np.mean(np.abs(res)))
    print('%-22s %8s %7s %14s' % ('medida', 'rho', 'p', 'LOO ref+sensor'))
    for k in nombres:
        x = np.array([f[k] for f in filas_out], float)
        if np.ptp(x) == 0:
            continue
        rho = spearmanr(x, res)[0]
        e = []
        for j in range(n):
            s = np.arange(n) != j
            beta, c = np.polyfit(x[s], res[s], 1)
            e.append(abs(res[j] - (c + beta * x[j])))
        print('%-22s %8.2f %7.3f %11.2f kg' % (k, rho, p_perm(x, res), np.mean(e)))


if __name__ == '__main__':
    main()
