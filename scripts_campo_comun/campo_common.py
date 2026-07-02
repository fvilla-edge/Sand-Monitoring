#!/usr/bin/env python3
"""
campo_common.py — funciones compartidas entre capturar_campo_stream.py
(mono) y capturar_dual_stream.py (dual).

Todo lo que es igual entre mono y dual vive aca: arranque del
streaming-server (con el fix del Bug 2 — reintento si aborta al iniciar),
manejo de Ctrl+C, preparacion de directorios SD/USB, y el movido de
archivos a USB o red. Lo que difiere (config de canales, aritmetica de
bytes por muestra, metadata especifica) queda en cada script.

Requiere que el script que importa este modulo haya insertado antes en
sys.path el directorio de la libreria streaming
(/root/rpsa_client/python_lib) si necesita usarla directamente — este
modulo no la importa.
"""
import os
import sys
import time
import signal
import shutil
import subprocess

FS_BASE     = 125_000_000
STREAM_DIR  = '/home/redpitaya/streaming_files/adc'   # siempre en SD
SERVER_BIN  = '/opt/redpitaya/bin/streaming-server'
DEC_VALIDOS = {1, 2, 4, 8, 16, 32, 64}


def instalar_manejador_stop():
    """
    Registra SIGINT/SIGTERM. Retorna un objeto cuyo atributo `.activo`
    pasa a True al recibir la señal — usar `while not stop.activo:` en
    el loop principal.
    """
    class _StopFlag:
        activo = False

    def _handler(sig, frame):
        _StopFlag.activo = True
        print('\n[!] Ctrl+C — termina el chunk actual y para...', flush=True)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return _StopFlag


def asegurar_servidor(log_path, max_intentos=3):
    """
    Carga bitstream stream_app e inicia streaming-server si no corre.

    Fix Bug 2 (2026-07-02): el streaming-server puede abortar (SIGABRT)
    casi al instante de arrancar si recibe comandos antes de que su
    "register controller" termine de inicializarse — un sleep fijo no
    garantiza que ya este listo. Se verifica que el proceso siga vivo
    unos segundos despues de lanzarlo y, si murio, se reintenta el
    bitstream+arranque desde cero.

    Nota: si ya hay un streaming-server corriendo (pgrep positivo), se
    retorna de inmediato SIN pasar por este chequeo — si ese server
    preexistente esta en mal estado (mismo bug), el crash va a pasar
    igual en el primer startStreaming(), fuera del alcance de este fix.
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
            stdout=open(log_path, 'w'),
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

    sys.exit(f'ERROR: streaming-server no pudo inicializar tras reintentos '
              f'(ver {log_path} en la placa).')


def preparar_dirs(directorio, subdir_nombre):
    """
    Asegura que STREAM_DIR sea un directorio real en SD (no symlink a USB)
    y crea el subdirectorio de destino (subdir_nombre) en el USB.
    """
    dest_usb = os.path.join(directorio, subdir_nombre)
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


def mover_a_usb(archivo_sd, dest_usb, chunk_num):
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


def mover_a_red(archivo_sd, pc_host, pc_ruta, chunk_num):
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
