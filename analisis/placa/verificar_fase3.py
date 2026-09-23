#!/usr/bin/env python3
"""verificar_fase3.py — verifica una corrida de la Fase 3 del modo evento
(capturar_eventos --prueba-pulsos N --pulso-loopback-digital) contra la
cantidad conocida de pulsos del generador.

Criterios (cada uno es un "tiene que dar"):
  1. Todo pulso emitido aparece en al menos un evento guardado, ENTERO dentro
     del archivo (ventana + margen).
  2. Ningun evento guardado queda sin pulso adentro (seria una ventana cruda
     que no corresponde a lo que vio la FPGA).
  3. Posicion del pulso respecto de la ventana "oficial" (sin margen): mide el
     corrimiento entre las fronteras de ventana de la FPGA y las del buffer
     propio. Tiene que quedar holgadamente dentro del margen.

Los pulsos se identifican por su indice absoluto en el stream propio
(`indice_inicio` + posicion en el archivo): dos eventos que ven el mismo
pulso (p.ej. uno cerca del borde, marcado en dos ventanas) se agrupan.

NO se usa el indice del DAC como verdad de tiempo: el streaming de DAC por
red mete silencios cuando no le llegan datos a tiempo y los pulsos salen
corridos respecto de lo programado (visto en HW, 2026-09-23) — el espaciado
entre pulsos se informa solo como dato.

Uso:
  python3 verificar_fase3.py <carpeta_eventos> <pulsos.csv> [--periodo-s 2.37]
"""
import argparse
import csv
import glob
import json
import os
import sys

import numpy as np

LARGO_PULSO = 400      # muestras ADC (~781 muestras DAC a 7.8125 MHz)
PICO_MINIMO = 500      # cuentas sobre la linea de base para considerar que hay pulso
AGRUPAR = 2000         # muestras: dos eventos con el pulso a menos de esto son el mismo pulso


def cargar(carpeta):
    eventos = []
    for js in sorted(glob.glob(os.path.join(carpeta, 'evento_*.json'))):
        with open(js) as f:
            e = json.load(f)
        x = np.fromfile(js[:-5] + '.bin', dtype='<i2').astype(np.float64)
        a = np.abs(x - np.median(x))
        p = int(np.argmax(a))
        e['archivo'] = os.path.basename(js[:-5])
        e['largo'] = len(x)
        e['pico'] = float(a[p])
        e['inicio_pulso'] = int(np.argmax(a > 0.2 * a[p])) if a[p] >= PICO_MINIMO else None
        eventos.append(e)
    return eventos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('carpeta')
    ap.add_argument('pulsos_csv')
    ap.add_argument('--periodo-s', type=float, default=2.37)
    args = ap.parse_args()

    with open(args.pulsos_csv) as f:
        n_pulsos = sum(1 for _ in csv.DictReader(f))
    eventos = cargar(args.carpeta)
    if not eventos:
        sys.exit('sin eventos')
    e0 = eventos[0]
    fs, ventana, margen = e0['fs_hz'], e0['ventana_muestras'], e0['margen_muestras']
    print(f'pulsos emitidos: {n_pulsos} | eventos guardados: {len(eventos)} | ventana={ventana} '
          f'margen={margen} ({margen / fs * 1e3:.1f} ms) muestras')

    con = [e for e in eventos if e['inicio_pulso'] is not None]
    sin = [e for e in eventos if e['inicio_pulso'] is None]
    # los eventos sin pulso ANTERIORES al primer pulso son el transitorio de
    # activar el loopback digital (la entrada del ADC salta de golpe), no del
    # sistema: se informan aparte
    primer = min((e['indice_inicio'] for e in con), default=None)
    arranque = [e for e in sin if primer is not None and e['indice_inicio'] < primer]
    sin = [e for e in sin if e not in arranque]
    for e in con:
        e['abs'] = e['indice_inicio'] + e['inicio_pulso']
        e['entero'] = e['largo'] - e['inicio_pulso'] >= LARGO_PULSO and e['inicio_pulso'] > 0
        e['rel'] = e['inicio_pulso'] - e['inicio_ventana_en_archivo']  # respecto de la ventana oficial

    # agrupar por pulso
    grupos = []
    for e in sorted(con, key=lambda e: e['abs']):
        if grupos and e['abs'] - grupos[-1][-1]['abs'] <= AGRUPAR:
            grupos[-1].append(e)
        else:
            grupos.append([e])
    enteros = [g for g in grupos if any(e['entero'] for e in g)]

    ok1 = len(enteros) == n_pulsos
    ok2 = not sin
    print()
    print(f'1. pulsos vistos enteros: {len(enteros)}/{n_pulsos}  -> {"OK" if ok1 else "FALLA"}')
    print(f'   pulsos vistos en total (incluye partidos): {len(grupos)} | '
          f'vistos en 2+ eventos: {sum(1 for g in grupos if len(g) > 1)}')
    for g in grupos:
        if not any(e['entero'] for e in g):
            print(f'   PARTIDO: {[x["archivo"] for x in g]} inicio={[x["inicio_pulso"] for x in g]}')
    print(f'2. eventos sin pulso: {len(sin)}  -> {"OK" if ok2 else "FALLA"}'
          f'   (+{len(arranque)} antes del primer pulso: transitorio del loopback, no cuenta)')
    for e in sin:
        print(f'   {e["archivo"]}: kurtosis_fpga={e["kurtosis"]:.1f} pico={e["pico"]:.0f}')

    # 3. posicion respecto de la ventana oficial, usando el evento "principal"
    # de cada pulso (el de mayor kurtosis)
    rel = np.array([max(g, key=lambda e: e['kurtosis'])['rel'] for g in grupos])
    fuera_antes = int((rel < 0).sum())
    fuera_despues = int((rel + LARGO_PULSO > ventana).sum())
    peor = max(-rel.min(), rel.max() + LARGO_PULSO - ventana, 0)
    ok3 = peor < margen
    print(f'3. inicio del pulso respecto de la ventana oficial: min={rel.min()} max={rel.max()} '
          f'(ventana 0..{ventana})')
    print(f'   pulsos que caen en el margen: antes={fuera_antes} despues={fuera_despues} | '
          f'peor desborde={peor} muestras ({peor / fs * 1e3:.2f} ms) de {margen} de margen  '
          f'-> {"OK" if ok3 else "FALLA"}')
    hist, _ = np.histogram(rel, bins=10, range=(0, ventana))
    print(f'   cobertura de posiciones (deciles de la ventana): {" ".join(str(h) for h in hist)}')
    print(f'   eventos marcados con_hueco: {sum(1 for e in eventos if e.get("con_hueco"))}')

    # dato informativo: espaciado real entre pulsos
    abs_g = np.array([g[0]['abs'] for g in grupos], dtype=np.float64)
    if len(abs_g) > 1:
        esp = np.diff(abs_g) / fs
        print(f'   (info) espaciado entre pulsos: mediana={np.median(esp):.4f}s '
              f'min={esp.min():.4f}s max={esp.max():.4f}s (programado {args.periodo_s}s)')
        raros = [(i, d) for i, d in enumerate(esp) if abs(d - args.periodo_s) > 0.05]
        for i, d in raros:
            print(f'   (info) intervalo raro entre pulso {i + 1} y {i + 2}: {d:.4f}s '
                  f'(= {d / args.periodo_s:.2f} periodos) — el DAC por red emitio corrido/de mas/de menos')
    print()
    print('RESULTADO:', 'OK' if (ok1 and ok2 and ok3) else 'FALLA')


if __name__ == '__main__':
    main()
