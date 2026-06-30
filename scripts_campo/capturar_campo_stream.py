#!/usr/bin/env python3
"""
capturar_campo_stream.py — Captura continua via streaming FILE mode.

El streaming-server (bitstream stream_app) escribe int16 raw directo al storage.
Python solo controla inicio/fin de cada chunk. Eficiencia: ~98%.

Formato de salida: raw int16, little-endian, muestras secuenciales, sin header.
Metadata en session_info.json junto a los archivos.

Uso:
  python3 capturar_campo_stream.py --condicion reposo --directorio /mnt/usb

  # 2 horas, chunks de 10 minutos
  python3 capturar_campo_stream.py --condicion con_arena \
      --duracion_total 120 --duracion_chunk 10 --directorio /mnt/usb
"""
import sys
import os
import time
import signal
import shutil
import argparse
import datetime
import threading
import subprocess
import json

sys.path.insert(0, '/tmp/rpsa_client/python_lib')
import streaming

FS_BASE      = 125_000_000
ESPACIO_MIN  = 500 * 1024 * 1024        # 500 MB — margen para int16 (más grande que HDF5)
STREAM_DIR   = '/home/redpitaya/streaming_files/adc'
RPSA_LIB     = '/tmp/rpsa_client/python_lib'
SERVER_BIN   = '/opt/redpitaya/bin/streaming-server'

_stop = False

def _handle_stop(sig, frame):
    global _stop
    _stop = True
    print('\n[!] Ctrl+C — termina el chunk actual y para...', flush=True)

signal.signal(signal.SIGINT,  _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)


def _asegurar_servidor():
    """Carga bitstream stream_app e inicia streaming-server si no corre."""
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
        stdout=open('/tmp/sstream_campo.log', 'w'),
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)


def _redirigir_a_usb(directorio):
    """Apunta STREAM_DIR al subdirectorio stream_adc/ del USB via symlink."""
    dest = os.path.join(directorio, 'stream_adc')
    os.makedirs(dest, exist_ok=True)

    if os.path.islink(STREAM_DIR):
        if os.readlink(STREAM_DIR) == dest:
            return
        os.unlink(STREAM_DIR)
    elif os.path.isdir(STREAM_DIR):
        os.rename(STREAM_DIR, STREAM_DIR + '_sd_backup')

    os.symlink(dest, STREAM_DIR)
    print(f'  Archivos → {dest}', flush=True)
    return dest


def _guardar_metadata(dest_dir, condicion, decimacion, fs_ef):
    """Escribe session_info.json con los parametros de la sesion."""
    info = {
        'formato':      'raw_int16_le',
        'descripcion':  'Muestras ADC canal 1, int16 little-endian, sin header',
        'condicion':    condicion,
        'decimacion':   decimacion,
        'fs_hz':        fs_ef,
        'fs_base_hz':   FS_BASE,
        'sensor':       'VS150-RI',
        'gain':         'A_1_20 (HV jumper instalado, rango +-20V)',
        'acoplamiento': 'DC',
        'uso_calibracion': True,
        'escala_voltios': '(valor_int16 / 32767.0) * 20.0  [aprox]',
        'fecha_inicio':  datetime.datetime.now().isoformat(),
    }
    with open(os.path.join(dest_dir, 'session_info.json'), 'w') as f:
        json.dump(info, f, indent=2, ensure_ascii=False)


def _capturar_chunk(client, n_muestras, fs_ef, chunk_num, condicion):
    """Dispara un chunk de n_muestras y renombra el archivo resultante."""
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

    ts = datetime.datetime.now()
    client.sendConfig('samples_limit_sd', str(n_muestras))

    t0 = time.perf_counter()
    if not client.startStreaming():
        raise RuntimeError("startStreaming fallo")

    done.wait(timeout=n_muestras / fs_ef + 15)
    t_total = time.perf_counter() - t0

    if error[0]:
        raise RuntimeError(f"Streaming error: {error[0]}")

    # Encontrar el .bin recien generado (el mas nuevo que no renombramos aun)
    archivos = sorted([
        f for f in os.listdir(STREAM_DIR)
        if f.startswith('data_file_') and f.endswith('.bin')
    ])
    if not archivos:
        raise RuntimeError("No se genero archivo de salida")

    nombre_orig  = os.path.join(STREAM_DIR, archivos[-1])
    bytes_totales = os.path.getsize(nombre_orig)
    muestras_reales = bytes_totales // 2
    senal_s      = muestras_reales / fs_ef
    ts_str       = ts.strftime('%Y%m%d_%H%M%S')
    nombre_final = os.path.join(
        STREAM_DIR,
        f'campo_{condicion}_{ts_str}_{chunk_num:04d}.bin'
    )
    os.rename(nombre_orig, nombre_final)

    # Limpiar logs auxiliares del servidor
    for f in os.listdir(STREAM_DIR):
        if f.endswith('.log.txt') or f.endswith('.log.lost.txt'):
            try:
                os.remove(os.path.join(STREAM_DIR, f))
            except OSError:
                pass

    eficiencia = senal_s / t_total * 100
    size_mb    = bytes_totales / 1e6
    print(f'  [OK] {os.path.basename(nombre_final)}'
          f'  ({senal_s:.1f}s señal | {t_total:.1f}s reloj | '
          f'{eficiencia:.0f}% eficiencia | {size_mb:.0f} MB)',
          flush=True)
    return senal_s


def main():
    p = argparse.ArgumentParser(
        description='Captura campo via streaming FILE mode — ~98% eficiencia'
    )
    p.add_argument('--condicion',      required=True, choices=['reposo', 'con_arena'])
    p.add_argument('--decimacion',     type=int, default=32,
                   help='Factor de decimacion (default 32 → 3.906 MHz)')
    p.add_argument('--duracion_chunk', type=float, default=1.0,
                   help='Minutos por chunk (default 1)')
    p.add_argument('--duracion_total', type=float, default=None,
                   help='Minutos totales (sin limite si no se especifica)')
    p.add_argument('--directorio',     default='/mnt/usb',
                   help='Storage externo montado (default /mnt/usb)')
    args = p.parse_args()

    DEC_VALIDOS = {1, 2, 4, 8, 16, 32, 64}
    if args.decimacion not in DEC_VALIDOS:
        sys.exit(f'Decimacion invalida. Opciones: {sorted(DEC_VALIDOS)}')

    fs_ef      = FS_BASE / args.decimacion
    chunk_s    = args.duracion_chunk * 60.0
    total_s    = args.duracion_total * 60.0 if args.duracion_total else None
    n_muestras = int(fs_ef * chunk_s)

    _asegurar_servidor()
    dest_dir = _redirigir_a_usb(args.directorio)

    client = streaming.ADCStreamClient()
    client.setVerbose(False)
    if not client.connect():
        sys.exit('ERROR: no se pudo conectar al streaming-server')

    client.sendConfig('adc_pass_mode',        'FILE')
    client.sendConfig('adc_decimation',       str(args.decimacion))
    client.sendConfig('channel_attenuator_1', 'A_1_20')
    client.sendConfig('channel_state_1',      'ON')
    client.sendConfig('channel_state_2',      'OFF')

    _guardar_metadata(dest_dir, args.condicion, args.decimacion, fs_ef)

    print(f'\n=== CAPTURA CAMPO — STREAMING FILE MODE ===')
    print(f'  condicion  : {args.condicion}')
    print(f'  decimacion : {args.decimacion}  →  fs = {fs_ef/1e6:.4f} MHz')
    print(f'  chunk      : {args.duracion_chunk} min  ({n_muestras:,} muestras)')
    print(f'  directorio : {dest_dir}')
    if total_s:
        n_est = max(1, int(total_s / chunk_s))
        print(f'  total      : {args.duracion_total} min  (~{n_est} chunks)')
    else:
        print(f'  total      : indefinido  (Ctrl+C para detener)')
    print(f'  Presiona Ctrl+C para detener.\n')

    chunk_num        = 1
    tiempo_capturado = 0.0

    try:
        while not _stop:
            if total_s and tiempo_capturado >= total_s:
                print('[OK] Tiempo total de sesion alcanzado.')
                break

            libre = shutil.disk_usage(args.directorio).free
            if libre < ESPACIO_MIN:
                print(f'[!] Espacio insuficiente ({libre/1e6:.0f} MB libres). Deteniendo.')
                break

            if total_s:
                restante   = total_s - tiempo_capturado
                n          = min(n_muestras, int(fs_ef * restante))
            else:
                n = n_muestras

            print(f'--- Chunk {chunk_num:04d} | {libre/1e9:.2f} GB libres ---', flush=True)
            secs = _capturar_chunk(client, n, fs_ef, chunk_num, args.condicion)
            tiempo_capturado += secs
            chunk_num += 1

    finally:
        print(f'\n=== SESION TERMINADA ===')
        print(f'  Chunks guardados : {chunk_num - 1}')
        print(f'  Tiempo capturado : {tiempo_capturado/60:.2f} min  ({tiempo_capturado:.0f}s)')
        print(f'  Directorio       : {dest_dir}')


if __name__ == '__main__':
    main()
