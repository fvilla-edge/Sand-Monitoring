#!/usr/bin/env python3
"""
probar_dual_stream.py — Prueba minima: modo FILE con CH1+CH2 activos.

Objetivo: ver que archivos genera el streaming-server en la SD cuando
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

    # Limpiar SD de archivos previos de prueba/campo para que la lista final sea clara
    print(f'\n  Contenido de {STREAM_DIR} ANTES de la prueba:')
    antes = set(os.listdir(STREAM_DIR)) if os.path.isdir(STREAM_DIR) else set()
    for f in sorted(antes):
        print(f'    {f}  ({os.path.getsize(os.path.join(STREAM_DIR, f))/1e6:.1f} MB)')

    client = streaming.ADCStreamClient()
    client.setVerbose(False)
    if not client.connect():
        sys.exit('ERROR: no se pudo conectar al streaming-server')

    client.sendConfig('adc_pass_mode',        'FILE')
    client.sendConfig('adc_decimation',       str(args.decimacion))
    client.sendConfig('channel_attenuator_1', 'A_1_20')
    client.sendConfig('channel_attenuator_2', 'A_1_20')
    client.sendConfig('channel_state_1',      'ON')
    client.sendConfig('channel_state_2',      'ON')

    done  = threading.Event()
    error = [None]

    class CB(streaming.ADCCallback):
        def recievePack(self, c, n): pass
        def connected(self, c, h):   pass
        def disconnected(self, c, h):pass
        def error(self, c, h, code): error[0] = f'code={code}'; done.set()
        def stopped(self, c, h, code):           done.set()
        def stoppedNoActiveChannels(self, c, h): error[0] = 'no-channels'; done.set()
        def stoppedMemError(self, c, h):         error[0] = 'mem-error'; done.set()
        def stoppedMemModify(self, c, h):        done.set()
        def stoppedSDFull(self, c, h):           error[0] = 'sd-full'; done.set()
        def stoppedSDDone(self, c, h):           done.set()
        def configConnected(self, c, h):  pass
        def configError(self, c, h, code):pass
        def configErrorTimeout(self, c, h):pass

    cb = CB()
    client.setReciveDataFunction(cb.__disown__())
    client.sendConfig('samples_limit_sd', str(n_muestras))

    print(f'\n  Capturando {args.duracion}s a dec={args.decimacion} '
          f'(fs={fs_ef/1e6:.4f} MHz), CH1+CH2 ON...', flush=True)

    t0 = time.perf_counter()
    if not client.startStreaming():
        sys.exit('ERROR: startStreaming fallo')

    bytes_esperados_1ch = n_muestras * 2
    flush_sd_s    = (bytes_esperados_1ch * 2) / (12 * 1024 * 1024) + 20
    timeout_total = n_muestras / fs_ef + flush_sd_s
    completado = done.wait(timeout=timeout_total)
    t_total = time.perf_counter() - t0

    if not completado:
        try:
            client.stopStreaming()
        except Exception:
            pass
        time.sleep(2)
        print('  [!] Timeout esperando el callback de fin — reviso igual lo que quedo en SD.')

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

    print(f'\n  Bytes esperados por canal (1ch): {bytes_esperados_1ch:,}')
    print(f'  Bytes esperados si 2ch intercalado en 1 archivo: {bytes_esperados_1ch*2:,}')
    print(f'  Bytes esperados si 2ch en archivos separados: {bytes_esperados_1ch:,} c/u')
    print('\n  No se movio ni borro nada. Revisar a mano en la placa antes de repetir.')


if __name__ == '__main__':
    main()
