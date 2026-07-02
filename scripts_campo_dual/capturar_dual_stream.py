#!/usr/bin/env python3
"""
capturar_dual_stream.py — Captura dual (CH1+CH2) via streaming FILE mode.

Igual esquema que capturar_campo_stream.py: el streaming-server escribe a la
SD interna (15 MB/s) y cada chunk se mueve al destino en un thread de fondo
mientras ya se captura el siguiente.

Formato de salida: raw int16 little-endian, INTERCALADO por muestra
(CH_par, CH_impar, CH_par, CH_impar, ...) en un solo archivo — asi es como el
streaming-server escribe cuando los dos canales estan activos, no es algo
configurable.:
    posiciones IMPARES (indices 1,3,5,...) = CH1 (IN1, sensor codo)
    posiciones PARES   (indices 0,2,4,...) = CH2 (IN2, sensor referencia)
Este mapeo hay que re-confirmarlo con el sensor VS150-RI realmente puesto —
la prueba se hizo golpeando el cable sin transductor.

IMPORTANTE — decimacion: con los dos canales activos el ancho de banda se
duplica. Medido en esta placa: dec=32 sostenido pierde ~0.42% de muestras
por canal (982.068 de 233M en 60s). A dec=64 no se midio perdida. Se deja
--decimacion configurable igual que en campo, pero se avisa si se elige
un valor que no llego a probarse sin perdidas.

Uso:
  python3 capturar_dual_stream.py --condicion reposo --directorio /mnt/usb

  # 2 horas, chunks de 10 minutos, decimacion segura
  python3 capturar_dual_stream.py --condicion con_arena \
      --decimacion 64 --duracion_total 120 --duracion_chunk 10 --directorio /mnt/usb
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

sys.path.insert(0, '/root/rpsa_client/python_lib')
import streaming

FS_BASE     = 125_000_000
ESPACIO_MIN = 1000 * 1024 * 1024   # 1 GB minimo libre — chunk dual pesa ~2x que mono
STREAM_DIR  = '/home/redpitaya/streaming_files/adc'   # siempre en SD
SERVER_BIN  = '/opt/redpitaya/bin/streaming-server'
DEC_SEGURAS = {64}   # unica probada sin perdida sostenida en dual; ver docstring

_stop = False

def _handle_stop(sig, frame):
    global _stop
    _stop = True
    print('\n[!] Ctrl+C — termina el chunk actual y para...', flush=True)

signal.signal(signal.SIGINT,  _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)


def _asegurar_servidor(max_intentos=3):
    """
    Carga bitstream stream_app e inicia streaming-server si no corre.

    Fix Bug 2 (portado de capturar_campo_stream.py, 2026-07-02): el
    streaming-server puede abortar (SIGABRT) casi al instante de arrancar
    si recibe comandos antes de que su "register controller" termine de
    inicializarse — un sleep fijo no garantiza que ya este listo. Se
    verifica que el proceso siga vivo unos segundos despues de lanzarlo y,
    si murio, se reintenta el bitstream+arranque desde cero.
    """
    r = subprocess.run(['pgrep', '-f', 'streaming-server'], capture_output=True)
    if r.returncode == 0:
        return

    for intento in range(1, max_intentos + 1):
        print(f'  Cargando bitstream stream_app... (intento {intento}/{max_intentos})', flush=True)
        subprocess.run(['/opt/redpitaya/sbin/overlay.sh', 'stream_app'],
                       check=True, capture_output=True)
        time.sleep(1)

        print('  Iniciando streaming-server...', flush=True)
        env = os.environ.copy()
        env['LD_LIBRARY_PATH'] = '/opt/redpitaya/lib'
        proc = subprocess.Popen(
            [SERVER_BIN, '-v'],
            cwd='/opt/redpitaya/bin',
            env=env,
            stdout=open('/tmp/sstream_dual.log', 'w'),
            stderr=subprocess.STDOUT,
        )

        # Chequeo de vida cada 0.5s en vez de un sleep ciego de 2s.
        vivo = True
        for _ in range(6):  # ~3s de margen
            time.sleep(0.5)
            if proc.poll() is not None:
                vivo = False
                break

        if vivo:
            return

        print(f'  [!] streaming-server abortó al iniciar (intento {intento}/{max_intentos}). '
              f'Reintentando...', flush=True)
        time.sleep(1)

    sys.exit('ERROR: streaming-server no pudo inicializar tras reintentos '
              '(ver /tmp/sstream_dual.log en la placa).')


def _preparar_dirs(directorio):
    """
    Asegura que STREAM_DIR sea un directorio real en SD (no symlink a USB)
    y crea el subdirectorio de destino en el USB.
    """
    dest_usb = os.path.join(directorio, 'stream_dual')
    os.makedirs(dest_usb, exist_ok=True)

    if os.path.islink(STREAM_DIR):
        os.unlink(STREAM_DIR)

    backup = STREAM_DIR + '_sd_backup'
    if not os.path.isdir(STREAM_DIR):
        if os.path.isdir(backup):
            os.rename(backup, STREAM_DIR)
        else:
            os.makedirs(STREAM_DIR, exist_ok=True)

    print(f'  Captura (SD) → {STREAM_DIR}', flush=True)
    print(f'  Archivos (USB) → {dest_usb}', flush=True)
    return dest_usb


def _guardar_metadata(dest_dir, condicion, decimacion, fs_ef):
    """Escribe session_dual_{condicion}_{ts}_info.json en el directorio destino."""
    session_ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    info = {
        'formato':      'raw_int16_le_interleaved',
        'descripcion':  'Muestras CH1+CH2 intercaladas por muestra, int16 little-endian, sin header',
        'mapeo_canales': {
            'ch1_posiciones': 'impares (indices 1,3,5,...)',
            'ch2_posiciones': 'pares (indices 0,2,4,...)',
            'confirmado':     'golpe fisico en cable IN1 sin sensor conectado, 2026-07-01',
            'advertencia':    'reconfirmar mapeo con sensor VS150-RI conectado antes de usar para analisis final',
        },
        'condicion':     condicion,
        'decimacion':    decimacion,
        'fs_hz_por_canal': fs_ef,
        'fs_base_hz':    FS_BASE,
        'sensor':        'VS150-RI',
        'canal_ch1':     'IN1 — sensor codo (medicion)',
        'canal_ch2':     'IN2 — sensor referencia (ruido de linea)',
        'gain':          'A_1_20 (HV jumper instalado, rango +-20V), ambos canales',
        'acoplamiento':  'DC',
        'escala_voltios': '(valor_int16 / 32767.0) * 20.0  [aprox]',
        'fecha_inicio':  datetime.datetime.now().isoformat(),
    }
    json_name = f'session_dual_{condicion}_{session_ts}_info.json'
    with open(os.path.join(dest_dir, json_name), 'w') as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    return session_ts, json_name


def _capturar_chunk(client, n_muestras, fs_ef, chunk_num, condicion, session_ts):
    """
    Dispara un chunk de n_muestras POR CANAL a SD y renombra el archivo resultante.
    El archivo real pesa 2x n_muestras*2 bytes (2 canales intercalados).
    Retorna (senal_s, ruta_archivo_en_sd).
    """
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

    t0 = time.perf_counter()
    if not client.startStreaming():
        raise RuntimeError("startStreaming fallo")

    # Timeout: tiempo de captura + flush a SD (15 MB/s) + margen.
    # bytes_totales = n_muestras * 2 canales * 2 bytes/muestra
    bytes_esperados = n_muestras * 4
    flush_sd_s      = bytes_esperados / (12 * 1024 * 1024) + 20  # conservador 12 MB/s
    timeout_total   = n_muestras / fs_ef + flush_sd_s
    completado = done.wait(timeout=timeout_total)
    t_total = time.perf_counter() - t0

    if not completado:
        try:
            client.stopStreaming()
        except Exception:
            pass
        time.sleep(2)

    if error[0]:
        raise RuntimeError(f"Streaming error: {error[0]}")

    archivos = sorted([
        f for f in os.listdir(STREAM_DIR)
        if f.startswith('data_file_') and f.endswith('.bin')
    ])
    if not archivos:
        raise RuntimeError("No se genero archivo de salida en SD")

    nombre_orig   = os.path.join(STREAM_DIR, archivos[-1])
    bytes_totales = os.path.getsize(nombre_orig)
    senal_s       = (bytes_totales // 4) / fs_ef   # //4: 2 canales x 2 bytes
    nombre_final  = os.path.join(
        STREAM_DIR,
        f'dual_{condicion}_{session_ts}_{chunk_num:04d}.bin'
    )
    os.rename(nombre_orig, nombre_final)

    for f in os.listdir(STREAM_DIR):
        if f.endswith('.log.txt') or f.endswith('.log.lost.txt'):
            try:
                os.remove(os.path.join(STREAM_DIR, f))
            except OSError:
                pass

    eficiencia = senal_s / t_total * 100
    size_mb    = bytes_totales / 1e6
    print(f'  [SD] dual_{condicion}_{session_ts}_{chunk_num:04d}.bin'
          f'  ({senal_s:.1f}s | {t_total:.1f}s reloj | '
          f'{eficiencia:.0f}% efic | {size_mb:.0f} MB)',
          flush=True)
    return senal_s, nombre_final


def _nuevo_cliente(args):
    """
    Crea, conecta y configura un cliente streaming nuevo.

    Mitigacion Bug 1 (portada de capturar_campo_stream.py, 2026-07-02): la
    causa raiz confirmada es una race condition del lado del
    streaming-server (no una fuga en el cliente), asi que esto no esta
    confirmado que evite el crash — es la misma mitigacion experimental
    que en mono, mientras se espera respuesta de Red Pitaya sobre el issue.
    """
    client = streaming.ADCStreamClient()
    client.setVerbose(False)
    if not client.connect():
        raise RuntimeError('no se pudo conectar al streaming-server')

    client.sendConfig('adc_pass_mode',        'FILE')
    client.sendConfig('adc_decimation',       str(args.decimacion))
    client.sendConfig('channel_attenuator_1', 'A_1_20')
    client.sendConfig('channel_attenuator_2', 'A_1_20')
    client.sendConfig('channel_state_1',      'ON')
    client.sendConfig('channel_state_2',      'ON')
    return client


def _cerrar_cliente(client):
    """
    Descarta un cliente streaming ya usado, de forma best-effort.

    Ver misma nota en capturar_campo_stream.py: no llamar stopStreaming()
    aca (el streaming del chunk ya termino), y no hay API de desconexion
    conocida del binding SWIG — se suelta la referencia y listo.
    """
    pass


def _mover_a_usb(archivo_sd, dest_usb, chunk_num):
    """Copia archivo de SD a USB y elimina el original (corre en thread)."""
    nombre  = os.path.basename(archivo_sd)
    destino = os.path.join(dest_usb, nombre)
    t0 = time.perf_counter()
    shutil.move(archivo_sd, destino)
    t = time.perf_counter() - t0
    size_mb = os.path.getsize(destino) / 1e6
    print(f'  [USB] chunk {chunk_num:04d} → {nombre}'
          f'  ({size_mb:.0f} MB en {t:.0f}s | {size_mb/t:.1f} MB/s)',
          flush=True)


def _mover_a_red(archivo_sd, pc_host, pc_ruta, chunk_num):
    """Envia archivo de SD a la PC via scp SSH y elimina el original."""
    nombre  = os.path.basename(archivo_sd)
    size_mb = os.path.getsize(archivo_sd) / 1e6
    t0 = time.perf_counter()
    subprocess.run(
        ['scp', '-q', archivo_sd, f'{pc_host}:{pc_ruta}/'],
        check=True,
    )
    os.remove(archivo_sd)
    t = time.perf_counter() - t0
    print(f'  [RED] chunk {chunk_num:04d} → {pc_host}:{pc_ruta}/{nombre}'
          f'  ({size_mb:.0f} MB en {t:.0f}s | {size_mb/t:.1f} MB/s)',
          flush=True)


def main():
    p = argparse.ArgumentParser(
        description='Captura dual CH1+CH2 via streaming FILE mode — SD intermedia, USB/red destino'
    )
    p.add_argument('--condicion',      required=True, choices=['reposo', 'con_arena'])
    p.add_argument('--decimacion',     type=int, default=32,
                   help='Factor de decimacion por canal (default 32 → 3.906 MHz/canal)')
    p.add_argument('--duracion_chunk', type=float, default=1.0,
                   help='Minutos por chunk (default 1)')
    p.add_argument('--duracion_total', type=float, default=None,
                   help='Minutos totales (sin limite si no se especifica)')
    p.add_argument('--directorio',     default='/mnt/usb',
                   help='Storage externo montado (default /mnt/usb)')
    p.add_argument('--destino',        choices=['usb', 'red'], default='usb',
                   help='Destino de los chunks: usb (default) o red (scp SSH a PC)')
    p.add_argument('--pc_host',        default=None,
                   help='usuario@ip de la PC destino (ej: facu@192.168.0.10) — solo con --destino red')
    p.add_argument('--pc_ruta',        default=None,
                   help='Ruta en la PC donde guardar los archivos — solo con --destino red')
    args = p.parse_args()

    if args.destino == 'red' and (not args.pc_host or not args.pc_ruta):
        sys.exit('ERROR: --destino red requiere --pc_host y --pc_ruta')

    DEC_VALIDOS = {1, 2, 4, 8, 16, 32, 64}
    if args.decimacion not in DEC_VALIDOS:
        sys.exit(f'Decimacion invalida. Opciones: {sorted(DEC_VALIDOS)}')

    if args.decimacion not in DEC_SEGURAS:
        print(f'\n  [!] ADVERTENCIA: decimacion={args.decimacion} con los 2 canales activos NO fue '
              f'validada sin perdida de muestras en esta placa.')
        print(f'      Medido: dec=32 sostenido (60s) perdio ~0.42% de muestras por canal (982.068/233M).')
        print(f'      Medido: dec=64 sostenido (60s) — 0 perdidas.')
        print(f'      Se continua igual porque la decimacion queda a tu criterio, pero quedas avisado.\n')

    fs_ef      = FS_BASE / args.decimacion
    chunk_s    = args.duracion_chunk * 60.0
    total_s    = args.duracion_total * 60.0 if args.duracion_total else None
    n_muestras = int(fs_ef * chunk_s)

    _asegurar_servidor()
    dest_usb = _preparar_dirs(args.directorio)

    if args.destino == 'usb':
        mover_fn      = lambda archivo, num: _mover_a_usb(archivo, dest_usb, num)
        destino_label = dest_usb
    else:
        mover_fn      = lambda archivo, num: _mover_a_red(archivo, args.pc_host, args.pc_ruta, num)
        destino_label = f'{args.pc_host}:{args.pc_ruta}'

    try:
        client = _nuevo_cliente(args)
    except RuntimeError as e:
        sys.exit(f'ERROR: {e}')

    session_ts, json_name = _guardar_metadata(dest_usb, args.condicion, args.decimacion, fs_ef)

    if args.destino == 'red':
        subprocess.run(
            ['scp', '-q',
             os.path.join(dest_usb, json_name),
             f'{args.pc_host}:{args.pc_ruta}/'],
            check=True,
        )

    bytes_chunk = n_muestras * 4   # 2 canales x 2 bytes, intercalados
    print(f'\n=== CAPTURA DUAL CH1+CH2 — SD intermedia + {args.destino.upper()} destino ===')
    print(f'  condicion  : {args.condicion}')
    print(f'  decimacion : {args.decimacion}  →  fs = {fs_ef/1e6:.4f} MHz por canal '
          f'({fs_ef*2/1e6:.4f} MHz combinado)')
    print(f'  chunk      : {args.duracion_chunk} min  ({n_muestras:,} muestras/canal | {bytes_chunk/1e6:.0f} MB)')
    print(f'  destino    : {destino_label}')
    if total_s:
        n_est = max(1, int(total_s / chunk_s))
        print(f'  total      : {args.duracion_total} min  (~{n_est} chunks)')
    else:
        print(f'  total      : indefinido  (Ctrl+C para detener)')
    print(f'  Presiona Ctrl+C para detener.\n')

    chunk_num        = 1
    tiempo_capturado = 0.0
    move_thread      = None

    try:
        while not _stop:
            if total_s and tiempo_capturado >= total_s:
                print('[OK] Tiempo total de sesion alcanzado.')
                break

            libre_usb = shutil.disk_usage(args.directorio).free
            if libre_usb < ESPACIO_MIN:
                print(f'[!] USB sin espacio ({libre_usb/1e6:.0f} MB libres). Deteniendo.')
                break

            if total_s:
                restante = total_s - tiempo_capturado
                if restante < 2.0:
                    print('[OK] Tiempo total de sesion alcanzado.')
                    break
                n = min(n_muestras, int(fs_ef * restante))
            else:
                n = n_muestras

            if args.destino == 'usb':
                espacio_label = f'USB {libre_usb/1e9:.2f} GB libres'
            else:
                libre_sd = shutil.disk_usage(STREAM_DIR).free
                espacio_label = f'SD {libre_sd/1e9:.2f} GB libres'
            print(f'--- Chunk {chunk_num:04d} | {espacio_label} ---', flush=True)
            secs, archivo_sd = _capturar_chunk(client, n, fs_ef, chunk_num, args.condicion, session_ts)
            tiempo_capturado += secs

            # Reiniciar el cliente para el proximo chunk (mitigacion Bug 1)
            _cerrar_cliente(client)
            client = _nuevo_cliente(args)
            print('  [cliente reiniciado]', flush=True)

            if move_thread and move_thread.is_alive():
                print('  [esperando move anterior...]', flush=True)
                move_thread.join()

            move_thread = threading.Thread(
                target=mover_fn,
                args=(archivo_sd, chunk_num),
                daemon=True,
            )
            move_thread.start()
            chunk_num += 1

    finally:
        if move_thread and move_thread.is_alive():
            print(f'\n  [esperando ultimo move a {args.destino.upper()}...]', flush=True)
            move_thread.join()
        print(f'\n=== SESION TERMINADA ===')
        print(f'  Chunks guardados : {chunk_num - 1}')
        print(f'  Tiempo capturado : {tiempo_capturado/60:.2f} min  ({tiempo_capturado:.0f}s)')
        print(f'  Archivos en       : {destino_label}')


if __name__ == '__main__':
    main()
