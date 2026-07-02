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
import datetime
import traceback
import subprocess

FS_BASE     = 125_000_000
STREAM_DIR  = '/home/redpitaya/streaming_files/adc'   # siempre en SD
SERVER_BIN  = '/opt/redpitaya/bin/streaming-server'
DEC_VALIDOS = {1, 2, 4, 8, 16, 32, 64}
LOG_DIR     = '/root/logs_campo'   # SD interna, no el USB/SSD de campo (ver Why abajo)

UMBRAL_EFICIENCIA_BAJA = 80   # %, por debajo de esto se loguea (operacion normal: 90-98%)

# Lineas que valen la pena guardar en el log persistente: errores/warnings
# propios (marcados con "[!]") y firmas conocidas de crashes de la
# libreria nativa, que no pasan por nuestro codigo asi que no se pueden
# marcar de antemano — hay que reconocerlas por texto. Regex ERE (para
# `awk`), se matchea contra tolower($0) asi que va todo en minuscula.
_PATRONES_AWK = (
    r'error|traceback|crash|segmentation|abort|fallo|\[!\]|'
    r"can.t start|end of file|broken pipe|resource deadlock|"
    r'register controller|directormethodexception|terminate called|'
    r'no se pudo'
)


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


def activar_log_archivo(prefix, condicion, session_ts):
    """
    La consola sigue mostrando TODO igual que siempre. Al archivo en
    LOG_DIR solo se escriben las lineas que matchean _PATRONES_AWK
    (errores, warnings marcados "[!]", firmas de crash) — no el log
    completo linea por linea, para no acumular ruido en sesiones largas
    (decision del usuario, 2026-07-02: "prefiero guardar datos que
    realmente nos digan cosas... pero no todo").

    Se filtra a nivel de file descriptor (dup2 hacia un `awk` externo),
    no reasignando sys.stdout, porque parte de lo interesante (ej.
    "Error: ... End of file", "Can't start ADC on remote machines") lo
    imprime directo la libreria C++ nativa sin pasar por Python —
    sys.stdout no lo veria.

    Se usa un proceso `awk` separado en vez de un thread Python interno
    (que fue el primer intento): un thread daemon puede perder las
    ultimas lineas bufferizadas justo cuando el proceso principal sale
    (el thread muere junto con el proceso antes de terminar de leer el
    pipe). `awk`, al ser un proceso del sistema operativo aparte, sigue
    vivo el tiempo necesario para vaciar el pipe aunque el nuestro ya
    haya terminado — probado localmente, sin esto se perdian lineas.

    Devuelve (log_path, log_evento) — usar log_evento(mensaje) para
    forzar al log algo que no tiene por que matchear _PATRONES_AWK (ej.
    encabezado de la sesion, eficiencia baja) pero que conviene guardar
    igual porque ya lo sabemos por codigo, no hay que adivinarlo del
    texto impreso.

    LOG_DIR vive en la SD interna, no en el USB/SSD de campo, para que
    el log sobreviva si el storage externo se desconecta a mitad de
    sesion (ver desconexion USB del 02/07/2026 en la memoria del
    proyecto).
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'log_{prefix}_{condicion}_{session_ts}.txt')

    fd_stdout_real = os.dup(1)
    fd_stderr_real = os.dup(2)

    awk_prog = (
        '{ print; if (tolower($0) ~ /' + _PATRONES_AWK + '/) '
        'print >> "' + log_path + '"; fflush() }'
    )

    def _filtrar(fd_original, fd_salida):
        proc = subprocess.Popen(['awk', awk_prog], stdin=subprocess.PIPE, stdout=fd_salida)
        os.dup2(proc.stdin.fileno(), fd_original)

    _filtrar(1, fd_stdout_real)
    _filtrar(2, fd_stderr_real)

    def log_evento(mensaje):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        linea = f'  [LOG {ts}] {mensaje}'
        os.write(fd_stdout_real, (linea + '\n').encode())
        with open(log_path, 'a') as f:
            f.write(linea + '\n')

    return log_path, log_evento


def _salida_comando(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout + r.stderr) or '(sin salida)\n'
    except Exception as e:
        return f'(no se pudo ejecutar {cmd}: {e})\n'


def guardar_contexto_crash(prefix, condicion, session_ts, chunk_num, excepcion):
    """
    Al morir con una excepcion no manejada, vuelca a un archivo dedicado
    en LOG_DIR el traceback + contexto util para diagnosticar sin tener
    que ir a buscarlo a mano por SSH (dmesg, estado del streaming-server,
    espacio libre). El traceback tambien queda en el log filtrado de la
    sesion (matchea "Traceback" en _PATRONES_AWK) — esto es ademas un
    resumen aparte, mas facil de ubicar.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    crash_path = os.path.join(
        LOG_DIR, f'crash_{prefix}_{condicion}_{session_ts}_{chunk_num:04d}.txt'
    )
    with open(crash_path, 'w') as f:
        f.write(f'=== CRASH — chunk {chunk_num} — {datetime.datetime.now().isoformat()} ===\n\n')
        f.write('--- Traceback ---\n')
        f.write(''.join(traceback.format_exception(
            type(excepcion), excepcion, excepcion.__traceback__)))
        f.write('\n--- pgrep streaming-server ---\n')
        f.write(_salida_comando(['pgrep', '-af', 'streaming-server']))
        f.write('\n--- dmesg (ultimas 40 lineas) ---\n')
        f.write(_salida_comando(['sh', '-c', 'dmesg | tail -n 40']))
        f.write('\n--- espacio libre SD (STREAM_DIR) ---\n')
        try:
            libre_sd = shutil.disk_usage(STREAM_DIR).free
            f.write(f'{libre_sd/1e9:.2f} GB libres en {STREAM_DIR}\n')
        except Exception as e:
            f.write(f'no se pudo leer: {e}\n')
    print(f'\n  [!] Contexto de crash guardado en {crash_path}', flush=True)
    return crash_path


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
