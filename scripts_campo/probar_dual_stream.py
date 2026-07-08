#!/usr/bin/env python3
"""
probar_dual_stream.py — Prueba minima: modo FILE con CH1+CH2 activos.

Objetivo: ver que archivo genera el streaming-server en la SD cuando
channel_state_1 y channel_state_2 estan ambos ON. No mueve nada a USB/red,
no borra nada — solo lista lo que aparece en STREAM_DIR despues de una
captura corta.

Uso (en la placa):
  python3 probar_dual_stream.py --decimacion 32 --duracion 5
"""
import sys
import os
import time
import argparse
import threading
import subprocess

sys.path.insert(0, '/root/rpsa_client/python_lib')
import streaming

FS_BASE    = 125_000_000
STREAM_DIR = '/home/redpitaya/streaming_files/adc'
SERVER_BIN = '/opt/redpitaya/bin/streaming-server'


def _asegurar_servidor():
    r = subprocess.run(['pgrep', '-f', 'streaming-server'], capture_output=True)
    if r.returncode == 0:
        return
    print('  Cargando bitstream stream_app...', flush=True)
    subprocess.run(['/opt/redpitaya/sbin/overlay.sh', 'stream_app'],
                   check=True, capture_output=True)
    time.sleep(1)
    print('  Iniciando streaming-server...', flush=True)
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = '/opt/redpitaya/lib'
    subprocess.Popen(
        [SERVER_BIN, '-v'],
        cwd='/opt/redpitaya/bin',
        env=env,
        stdout=open('/tmp/sstream_prueba_dual.log', 'w'),
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)


def main():
    p = argparse.ArgumentParser(description='Prueba FILE mode con 2 canales')
    p.add_argument('--decimacion', type=int, default=32)
    p.add_argument('--duracion', type=float, default=5.0, help='segundos')
    args = p.parse_args()

    fs_ef      = FS_BASE / args.decimacion
    n_muestras = int(fs_ef * args.duracion)

    _asegurar_servidor()

    print(f'\n  Contenido de {STREAM_DIR} ANTES de la prueba:')
    antes = set(os.listdir(STREAM_DIR)) if os.path.isdir(STREAM_DIR) else set()
    for f in sorted(antes):
        print(f'    {f}  ({os.path.getsize(os.path.join(STREAM_DIR, f))/1e6:.1f} MB)')

    done  = threading.Event()
    error = [None]

    class ADC_CB(streaming.ADCCallback):
        def receivePack(self, c, n): pass
        def connected(self, c, h):    pass
        def disconnected(self, c, h): pass
        def error(self, c, h, code):  error[0] = f'code={code}'; done.set()

    class Config_CB(streaming.ConfigCallback):
        def adcServerStoppedNoActiveChannels(self, c, h): error[0] = 'no-channels'; done.set()
        def adcServerStoppedMemError(self, c, h):         error[0] = 'mem-error'; done.set()
        def adcServerStoppedMemModify(self, c, h):        done.set()
        def adcServerStoppedSDFull(self, c, h):           error[0] = 'sd-full'; done.set()
        def adcServerStoppedSDDone(self, c, h):           done.set()
        def configError(self, c, h, code): pass
        def configErrorTimeout(self, c, h): pass

    confObj = streaming.ConfigStreamClient()
    adcObj  = streaming.ADCStreamClient(confObj)
    confObj.setVerbose(False)
    adcObj.setVerbose(False)
    if not confObj.connect():
        sys.exit('ERROR: no se pudo conectar al streaming-server')

    adc_cb = ADC_CB()
    adcObj.setCallback(adc_cb)
    cfg_cb = Config_CB()
    confObj.addCallback(cfg_cb)

    confObj.sendConfig('adc_pass_mode',        'FILE')
    confObj.sendConfig('adc_decimation',       str(args.decimacion))
    confObj.sendConfig('channel_attenuator_1', 'A_1_20')
    confObj.sendConfig('channel_attenuator_2', 'A_1_20')
    confObj.sendConfig('channel_state_1',      'ON')
    confObj.sendConfig('channel_state_2',      'ON')
    confObj.sendConfig('samples_limit_sd',     str(n_muestras))

    print(f'\n  Capturando {args.duracion}s a dec={args.decimacion} '
          f'(fs={fs_ef/1e6:.4f} MHz), CH1+CH2 ON...', flush=True)

    t0 = time.perf_counter()
    if not adcObj.startStreaming():
        sys.exit('ERROR: startStreaming fallo')

    bytes_esperados_1ch = n_muestras * 2
    flush_sd_s    = (bytes_esperados_1ch * 2) / (12 * 1024 * 1024) + 20
    timeout_total = n_muestras / fs_ef + flush_sd_s
    completado = done.wait(timeout=timeout_total)
    t_total = time.perf_counter() - t0

    if not completado:
        try:
            adcObj.stopStreaming()
        except Exception:
            pass
        time.sleep(2)
        print('  [!] Timeout esperando el callback de fin — reviso igual lo que quedo en SD.')

    confObj.removeCallback(cfg_cb)
    adcObj.removeCallback()

    if error[0]:
        print(f'  [!] Error reportado por el server: {error[0]}')

    print(f'\n  Contenido de {STREAM_DIR} DESPUES de la prueba ({t_total:.1f}s reloj):')
    despues = set(os.listdir(STREAM_DIR)) if os.path.isdir(STREAM_DIR) else set()
    nuevos = sorted(despues - antes)
    if not nuevos:
        print('    (no aparecieron archivos nuevos)')
    for f in nuevos:
        ruta = os.path.join(STREAM_DIR, f)
        size = os.path.getsize(ruta)
        print(f'    {f}  ({size/1e6:.1f} MB, {size} bytes)')

    print('\n  No se movio ni borro nada. Revisar con analisis/revisar.py antes de repetir.')


if __name__ == '__main__':
    main()
