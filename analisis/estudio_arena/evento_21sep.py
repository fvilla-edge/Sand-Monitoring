#!/usr/bin/env python3
"""
evento_21sep.py — paso 2 de docs/plan_modelo_arena.md sec.10: ¿hubo precursores
del evento de 500 kg (purga 21/9 20:00 local)?

1. Planilla: purgas con 0 kg seguidas (desde que aparece arena, 13/9).
2. Sensor: ventanas con kurtosis extrema (> 100, 200, 300) por hora en los paquetes
   del 21-22/9 (cadena de software, capturas "con arena": hay sesgo de seleccion
   en CUANDO se grabo) contra los CSV continuos de la FPGA (29/9 en adelante).

Uso:
    .venv/bin/python analisis/estudio_arena/evento_21sep.py PLANILLA.csv CARPETA_PAQUETES CARPETA_CSV [...]
"""
import argparse, collections, glob, json, os, re, sys
import datetime as D
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from metricas_purgas import leer_ventanas
import planilla_historia as ph

HUSO = D.timedelta(hours=-3)
UMBRALES = (100, 200, 300)
INICIO_ARENA = D.datetime(2026, 9, 13, 8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('planilla'); ap.add_argument('paquetes'); ap.add_argument('carpetas', nargs='+')
    a = ap.parse_args()

    I = [o for o in ph.leer(a.planilla) if not np.isnan(o['kg']) and o['ini'] >= INICIO_ARENA]
    print('1. Planilla desde %s: %d intervalos, %d con 0 kg' % (INICIO_ARENA.strftime('%d/%m'), len(I), sum(o['kg'] == 0 for o in I)))
    for x, y, z in zip(I, I[1:], I[2:]):
        if x['kg'] == 0 and y['kg'] == 0:
            print('   dos ceros seguidos: %s -> %s (%.0f h), siguiente purga %s: %.0f kg' % (
                x['ini'].strftime('%d/%m %H:%M'), y['fin'].strftime('%d/%m %H:%M'),
                x['h'] + y['h'], z['fin'].strftime('%d/%m %H:%M'), z['kg']))

    print('\n2. Paquetes (por minuto grabado, hora local):')
    por = collections.defaultdict(lambda: [0] * len(UMBRALES) + [0.0])
    for f in glob.glob(os.path.join(a.paquetes, '*.json')):
        t = D.datetime.strptime(re.search(r'(\d{8}_\d{6})', f).group(1), '%Y%m%d_%H%M%S') + HUSO
        c = [c for c in json.load(open(f))['canales'] if c['canal'] == 'IN1'][0]
        k = np.array(c['kurtosis'], float)
        p = por[t.replace(minute=0, second=0)]
        for i, u in enumerate(UMBRALES):
            p[i] += int((k > u).sum())
        p[-1] += len(k) * 0.05 / 60
    print('   hora      min  ' + '  '.join('k>%d/min' % u for u in UMBRALES))
    for t in sorted(por):
        p = por[t]
        print('   %s %4.0f  ' % (t.strftime('%d/%m %H'), p[-1]) + '  '.join('%8.2f' % (p[i] / p[-1]) for i in range(len(UMBRALES))))

    T, _, K = leer_ventanas(a.carpetas)
    _, inv = np.unique((T // 3600).astype(np.int64), return_inverse=True)
    print('\n3. CSV FPGA continuos: %.0f h' % (inv.max() + 1))
    for u in UMBRALES:
        c = np.bincount(inv, K > u)
        print('   k>%d: horas con >= 1 / >= 3 ventanas: %d / %d; maximo en una hora %d' % (u, (c >= 1).sum(), (c >= 3).sum(), c.max()))


if __name__ == '__main__':
    main()
