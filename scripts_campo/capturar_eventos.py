#!/usr/bin/env python3
"""capturar_eventos.py — "modo evento": streaming continuo (24h, sin cortes),
NO persiste nada salvo cuando una ventana de 50ms cruza kurtosis>=umbral — en
ese caso guarda esa ventana cruda + su área/kurtosis.

Este script solo prepara la placa (bitstream stream_app + streaming-server,
igual que capturar_stream.py) y hace exec del núcleo en C++
(`c/capturar_eventos`, compilar en la placa con `make -C c`). El recibir
muestras + buffer + sondeo de la FPGA vive en C++ porque en Python el
callback no daba abasto: leer y convertir `ch.raw` costaba ~19ms por paquete
contra 8.4ms entre paquetes a decimación 32, y el streaming-server descartaba
~63% de las muestras (medido en rp-f0fd8c, 2026-09-23 — detalle en
c/capturar_eventos.cpp).

Uso:
  python3 capturar_eventos.py [--umbral 5.0] [--destino /root/eventos]
                              [--dec 32] [--estado-s 10] [--duracion-s 0]
                              [--host 127.0.0.1]
"""
import os
import sys
import argparse

sys.path.insert(0, '/root/scripts_campo_comun')
import campo_common as cc

BINARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'c', 'capturar_eventos')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--umbral', type=float, default=5.0,
                     help='kurtosis minima para guardar la ventana (default 5.0, '
                          'con margen contra el umbral real de 6.0)')
    ap.add_argument('--destino', default='/root/eventos',
                     help='carpeta donde se guardan los eventos que cruzan el umbral')
    ap.add_argument('--dec', type=int, default=32, help='decimacion (default 32)')
    ap.add_argument('--estado-s', type=int, default=10,
                     help='cada cuantos segundos loguear una linea de ESTADO (default 10)')
    ap.add_argument('--duracion-s', type=int, default=0,
                     help='cortar solo despues de N segundos (default 0 = hasta Ctrl+C/SIGTERM)')
    ap.add_argument('--host', default='127.0.0.1',
                     help='IP del streaming-server (default 127.0.0.1). "auto" = descubrimiento '
                          'por broadcast del vendor, que ata la conexion a la IP de eth0: con '
                          'eth0 abajo (corte de Starlink) el stream se congela y se pierde la '
                          'señal cruda. Con IP fija no (probado en rp-f0fd8c, 2026-09-23).')
    args = ap.parse_args()

    if not os.access(BINARIO, os.X_OK):
        sys.exit(f'ERROR: falta {BINARIO} — compilar en la placa con: make -C {os.path.dirname(BINARIO)}')

    cc.log('INFO', 'Asegurando streaming-server (mata previo + carga bitstream)...')
    cc.asegurar_servidor('/root/capturar_eventos_server.log')

    # exec: el binario reemplaza a este proceso, asi SIGINT/SIGTERM le llegan directo
    os.execv(BINARIO, [BINARIO,
                       '--umbral', str(args.umbral),
                       '--destino', args.destino,
                       '--dec', str(args.dec),
                       '--estado-s', str(args.estado_s),
                       '--duracion-s', str(args.duracion_s)]
             + ([] if args.host == 'auto' else ['--host', args.host]))


if __name__ == '__main__':
    main()
