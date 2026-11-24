#!/usr/bin/env python3
"""simular_ventanas.py — genera un ventanas.json falso para probar el panel
"Arena" en la PC, sin placa (mismo formato que capturar_eventos_demo --en-vivo).

Ruido: kurtosis ~3, area ~0,54 (lo medido en el lab sin arena el 20/11).
Cada ~6 s simula un golpe de arena de ~1 s (kurtosis y area altas).
Los valores con arena son INVENTADOS: solo sirven para ver la pagina moverse.

Uso (en la PC):
  python3 simular_ventanas.py RUTA/ventanas.json
  # y en otra terminal, desde la carpeta que tiene arena/:
  python3 -m http.server 8000      ->  http://localhost:8000/arena/
"""
import json
import os
import random
import sys
import time

if len(sys.argv) != 2:
    sys.exit(__doc__)
ruta = sys.argv[1]
MAX = 20 * 30
filas = []
wc = 1000
t = int(time.time() * 1000)
prox_golpe = time.time() + 3
fin_golpe = 0

while True:
    ahora = time.time()
    while t <= ahora * 1000 - 50:
        t += 50
        wc += 1
        if ahora >= prox_golpe:
            fin_golpe = ahora + random.uniform(0.5, 1.5)
            prox_golpe = ahora + random.uniform(4, 8)
        if ahora < fin_golpe:
            kurt = random.uniform(4, 15)
            area = random.uniform(2, 8)
        else:
            kurt = random.gauss(3.0, 0.03)
            area = random.gauss(0.54, 0.02)
        filas.append([wc, t, round(area, 6), round(kurt, 6), None, None])
    del filas[:-MAX]
    tmp = ruta + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'t_ms': int(ahora * 1000), 'dec': 32, 'fs_hz': 3906250.0, 'ventanas': filas}, f)
    os.replace(tmp, ruta)
    time.sleep(0.2)
