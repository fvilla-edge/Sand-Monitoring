#!/usr/bin/env python3
"""arena_demo.py — captura para el panel "Arena" de la demo (rama demo-presentacion).

Igual que scripts_campo/capturar_eventos.py (carga el bitstream propio +
streaming-server y hace exec del nucleo en C++), pero con la copia de demo
(c/capturar_eventos_demo) y sin dejar nada en disco:
  - sin CSV (--sin-registro) y sin señal cruda de eventos (umbral inalcanzable);
  - todo en /run/arena (RAM): ventanas.json con las ultimas 30 s, se pisa
    cada ~200 ms y se borra al apagar.

Uso:  python3 arena_demo.py [--canales 1|2] [--dec 32]
"""
import argparse
import os
import sys

sys.path.insert(0, '/root/scripts_campo_comun')
import campo_common as cc

DIR = '/run/arena'
BINARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'c', 'capturar_eventos_demo')
UMBRAL_SIN_EVENTOS = '1e9'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--canales', type=int, choices=(1, 2), default=1)
    ap.add_argument('--dec', type=int, choices=(32, 64), default=32)
    args = ap.parse_args()

    if not os.access(BINARIO, os.X_OK):
        sys.exit(f'ERROR: falta {BINARIO} — compilar en la placa con: make -C {os.path.dirname(BINARIO)}')
    os.makedirs(DIR, exist_ok=True)

    cc.log('INFO', 'Arena demo: cargando bitstream propio + streaming-server...')
    cc.asegurar_servidor(os.path.join(DIR, 'server.log'), bitstream_propio=True)

    os.execv(BINARIO, [BINARIO,
                       '--umbral', UMBRAL_SIN_EVENTOS,
                       '--umbral2', UMBRAL_SIN_EVENTOS,
                       '--destino', DIR,
                       '--sin-registro',
                       '--minimo-libre-mb', '0',
                       '--dec', str(args.dec),
                       '--canales', str(args.canales),
                       '--estado-s', '10',
                       '--host', '127.0.0.1',
                       '--en-vivo', os.path.join(DIR, 'ventanas.json')])


if __name__ == '__main__':
    main()
