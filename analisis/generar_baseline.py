#!/usr/bin/env python3
"""
generar_baseline.py — arma analisis/baseline_confirmado.json a partir de un
lote de capturas donde se CONFIRMO por otra via (reporte de produccion del
pozo, certeza operativa, etc.) que no habia arena — no alcanza con que la
carpeta/JSON diga condicion "reposo": eso es solo una etiqueta puesta al
lanzar la captura, no una confirmacion (ver sec.151 de la memoria del
proyecto: un lote entero etiquetado "reposo" resulto caer dentro de una
hora de produccion real segun el reporte del pozo).

Agrupa por (canales, decimacion) — cada combinacion encontrada arma su
propia entrada en el JSON ("mono_dec32", "dual_dec64", etc.) con la
mediana del RMS (señal filtrada 100-450kHz) de esos archivos. revisar.py
y timeline_lote.py usan esas entradas via --baseline en vez de calcular
un baseline por lote cuando la (canales, decimacion) esta cubierta ahi.

Antes de escribir nada, verifica que NINGUN archivo pasado haya sido
detectado como arena/ruido (revisar.py::_detectar_mono/_detectar_dual) —
si alguno lo fue, aborta sin tocar el JSON: ese archivo no deberia estar
en un lote que se va a usar como cero confirmado.

Si ya existe analisis/baseline_confirmado.json, actualiza (agrega o
sobreescribe) solo las claves (canales, decimacion) presentes en esta
corrida — para poder ir completando configuraciones con corridas
separadas, como paso ademas en la practica (mono_dec32 + dual_dec64
primero, mono_dec64 despues).

Uso:
  .venv/bin/python3 analisis/generar_baseline.py "carpeta con capturas confirmadas"/*/
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _calcular, _clave_config, _detectar_dual, _detectar_mono, _recopilar_rutas  # noqa: E402

OUT = Path(__file__).parent / 'baseline_confirmado.json'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    rutas = sorted(_recopilar_rutas(sys.argv[1:]), key=lambda p: p.name)
    if not rutas:
        print('[!] No se encontraron archivos campo_*.bin')
        sys.exit(1)

    resultados = []
    for ruta in rutas:
        print(f'  leyendo {ruta.name} ...', end='\r', flush=True)
        try:
            resultados.append(_calcular(ruta))
        except Exception as e:
            print(f'[ERROR] {ruta.name}: {e}')
    print()

    if not resultados:
        sys.exit(1)

    contaminados = []
    for r in resultados:
        det = _detectar_mono(r) if r['canales'] == 1 else _detectar_dual(r)
        if det != 'reposo':
            contaminados.append((r['archivo'], det))
    if contaminados:
        print('[!] ABORTADO — hay archivos detectados como arena/ruido en el lote pasado, '
              'no puede ser un baseline confirmado:')
        for nombre, det in contaminados:
            print(f'      {nombre}: {det}')
        sys.exit(1)

    grupos = {}
    for r in resultados:
        grupos.setdefault(_clave_config(r['canales'], r['decimacion']), []).append(r)

    configs = {}
    if OUT.exists():
        with open(OUT) as f:
            configs = json.load(f).get('configs', {})

    for clave, grupo in grupos.items():
        canales = grupo[0]['canales']
        if canales == 1:
            entrada = {
                'canales': 1, 'decimacion': grupo[0]['decimacion'],
                'rms': float(np.median([r['rms'] for r in grupo])),
            }
        else:
            entrada = {
                'canales': 2, 'decimacion': grupo[0]['decimacion'],
                'rms1': float(np.median([r['rms1'] for r in grupo])),
                'rms2': float(np.median([r['rms2'] for r in grupo])),
            }
        entrada['n_archivos'] = len(grupo)
        entrada['archivos_fuente'] = sorted(r['archivo'] for r in grupo)
        configs[clave] = entrada
        print(f'[OK] {clave}: {len(grupo)} archivos confirmados en reposo')

    data = {'generado_utc': datetime.now(timezone.utc).isoformat(), 'configs': configs}
    with open(OUT, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    print(f'\n[OK] {OUT}')


if __name__ == '__main__':
    main()
