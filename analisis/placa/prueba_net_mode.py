#!/usr/bin/env python3
"""prueba_net_mode.py — Fase 1 del plan de "modo evento" (ver memoria del
proyecto sec.182, 2026-09-22): mide si el modo NET del vendor (entrega las
muestras en memoria via ADCCallback.receivePack, en vez de escribir a un
archivo como hace capturar_stream.py) aguanta el ancho de banda real de
produccion SIN perder muestras — antes de construir el diseño final
(buffer circular + persistencia solo si kurtosis>=5) sobre esa base.

NO guarda nada — solo cuenta paquetes/muestras recibidas y lee `fpgaLost`
(el propio contador de perdida que reporta el vendor por canal).

Por que esto puede alcanzar ahora aunque el modo NET nunca se probo antes:
el filtrado pesado y el area/kurtosis ya viven en la FPGA (Etapas 4-8) - en
NET, el ARM solo copia muestras crudas a un buffer, no filtra nada.

Uso (en la placa, con el bitstream Etapa 6+ ya cargado):
  cd /root/proyecto/analisis/placa   # o donde se haya copiado
  python3 prueba_net_mode.py [duracion_s] [--con-polling]

  --con-polling agrega un hilo sondeando LectorRegistrosHW en paralelo
  (la carga real que importa - con capturar_stream.py+FILE mode compartiendo
  CPU con el sondeo hoy dio 0 perdidas, este test confirma si NET tambien).
"""
import sys
import time
import threading
import argparse

sys.path.insert(0, '/root/rpsa_client/python_lib')
sys.path.insert(0, '/root/scripts_campo_comun')
import streaming
import campo_common as cc

sys.path.insert(0, '.')
from coleccionar_paquete_placa import LectorRegistrosHW

DECIMACION = 32
FS_HZ = 3_906_250.0  # decimacion 32, ver area_kurtosis.py / config_campo.json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('duracion_s', type=float, nargs='?', default=60.0)
    ap.add_argument('--con-polling', action='store_true',
                     help='sondear LectorRegistrosHW en paralelo (la carga real)')
    args = ap.parse_args()

    stats = {'packs': 0, 'muestras': 0, 'fpga_lost_max': 0,
             'primer_ts': None, 'ultimo_ts': None, 'primer_muestras': None}
    lock = threading.Lock()

    class ADC_CB(streaming.ADCCallback):
        def receivePack(self, c, pack):
            with lock:
                stats['packs'] += 1
                ch = pack.channel1
                stats['muestras'] += ch.samples
                if ch.fpgaLost > stats['fpga_lost_max']:
                    stats['fpga_lost_max'] = ch.fpgaLost
                if stats['primer_ts'] is None:
                    stats['primer_ts'] = ch.timeCapture
                stats['ultimo_ts'] = ch.timeCapture

        def connected(self, c, h):
            print(f'conectado: {h}')

        def disconnected(self, c, h):
            print(f'desconectado: {h}')

        def error(self, c, h, code):
            print(f'ERROR receivePack: {code}')

    print('Asegurando streaming-server (mata previo + carga bitstream)...')
    cc.asegurar_servidor('/root/prueba_net_mode_server.log')

    confObj = streaming.ConfigStreamClient()
    adcObj = streaming.ADCStreamClient(confObj)
    confObj.setVerbose(False)
    adcObj.setVerbose(False)
    if not confObj.connect():
        sys.exit('ERROR: no se pudo conectar al streaming-server')

    confObj.sendConfig('adc_pass_mode', 'NET')
    confObj.sendConfig('adc_decimation', str(DECIMACION))
    confObj.sendConfig('channel_attenuator_1', 'A_1_20')
    confObj.sendConfig('channel_state_1', 'ON')
    confObj.sendConfig('channel_state_2', 'OFF')

    cb = ADC_CB()
    adcObj.setCallback(cb)

    stop_polling = threading.Event()
    ventanas_polling = [0]

    def hilo_polling():
        lector = LectorRegistrosHW(FS_HZ, int(FS_HZ * 0.05))
        try:
            ultimo_wc = 0
            while not stop_polling.is_set():
                wc, _, _, _ = lector.leer()
                if wc != ultimo_wc:
                    ventanas_polling[0] += 1
                    ultimo_wc = wc
                time.sleep(0.01)
        finally:
            lector.close()

    if args.con_polling:
        print('Arrancando hilo de sondeo LectorRegistrosHW en paralelo (la carga real)...')
        pt = threading.Thread(target=hilo_polling, daemon=True)
        pt.start()

    print(f'Iniciando streaming NET por {args.duracion_s:.0f}s '
          f'(decimacion={DECIMACION}, fs={FS_HZ}Hz, mono)...')
    if not adcObj.startStreaming():
        sys.exit('ERROR: startStreaming fallo')

    t0 = time.monotonic()
    time.sleep(args.duracion_s)
    t_total = time.monotonic() - t0

    adcObj.stopStreaming()
    stop_polling.set()
    time.sleep(1)

    print()
    print('=== RESULTADO ===')
    print(f'duracion real (reloj)     : {t_total:.2f}s')
    with lock:
        print(f'paquetes recibidos        : {stats["packs"]}')
        print(f'muestras recibidas        : {stats["muestras"]}')
        print(f'muestras esperadas (~)    : {int(FS_HZ * t_total)}')
        print(f'fpgaLost maximo reportado : {stats["fpga_lost_max"]}')
        if stats['primer_ts'] is not None and stats['ultimo_ts'] is not None:
            dur_ts = (stats['ultimo_ts'] - stats['primer_ts']) / 1e9
            print(f'duracion segun timeCapture: {dur_ts:.2f}s')
    if args.con_polling:
        print(f'ventanas vistas por el sondeo de kurtosis: {ventanas_polling[0]} '
              f'(esperado ~{int(t_total / 0.05)})')


if __name__ == '__main__':
    main()
