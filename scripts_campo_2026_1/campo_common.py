#!/usr/bin/env python3
"""
campo_common.py — funciones compartidas usadas por capturar_stream.py
(1 o 2 canales, via --canales).

Variante para Release_2026.1 (Ecosystem 3.00-e00665135, migracion 2026-07-07)
— sin cambios respecto a la version de scripts_campo_comun/, no toca la API
de streaming directamente.

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

_NIVEL_COLOR = {
    'INFO':    '\033[34m',   # azul   — configuracion/setup, no es una confirmacion de resultado
    'OK':      '\033[32m',   # verde  — chunk generado/guardado/enviado bien
    'WARNING': '\033[33m',   # amarillo
    'ERROR':   '\033[31m',   # rojo
}
_RESET = '\033[0m'
_ESC   = '\033'   # para el gsub de awk que le saca el color al log persistente

_es_tty     = False
_verbosidad = 'completo'   # 'completo' o 'minimo', ver configurar_salida()

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

# Ruido conocido de la libreria nativa: confirmado benigno (ver memoria del
# proyecto, "End of file" aparece en cada chunk desde 2026-07-02, nunca se
# encontro la causa, no rompe la sesion). En consola se muestra en amarillo
# en verbosidad completa y se suprime del todo en minima — el archivo de
# log lo sigue guardando igual que siempre (ya matchea _PATRONES_AWK).
_RUIDO_BENIGNO = r'end of file'


def configurar_salida(verbosidad):
    """
    Llamar UNA VEZ al principio de main(), antes de activar_log_archivo().

    activar_log_archivo() redirige el file descriptor 1 a un pipe hacia
    `awk` (para el archivo de log) — si esta funcion se llama despues de
    eso, `os.isatty(1)` siempre da False porque fd 1 ya no apunta a la
    terminal real sino al pipe, y el color quedaria desactivado siempre
    aunque haya una terminal real del otro lado.
    """
    global _es_tty, _verbosidad
    assert verbosidad in ('completo', 'minimo')
    _es_tty     = os.isatty(1)
    _verbosidad = verbosidad


def log(nivel, mensaje, flush=True):
    """
    Imprime `mensaje` en color segun `nivel` ('INFO', 'OK', 'WARNING' o
    'ERROR').

    En verbosidad 'minimo' las lineas INFO/OK (rutina) no se imprimen —
    WARNING y ERROR se muestran siempre, pase lo que pase. Sin terminal
    real detras (salida redirigida a archivo, corriendo en background)
    nunca colorea, para no dejar codigos ANSI crudos en una salida no
    interactiva.
    """
    if nivel in ('INFO', 'OK') and _verbosidad == 'minimo':
        return
    if _es_tty:
        color = _NIVEL_COLOR.get(nivel, '')
        print(f'{color}{mensaje}{_RESET}', flush=flush)
    else:
        print(mensaje, flush=flush)


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
        log('INFO', '\n[!] Ctrl+C — termina el chunk actual y para...')

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
        log('INFO', f'  Cargando bitstream stream_app... (intento {intento}/{max_intentos})')
        subprocess.run(['/opt/redpitaya/sbin/overlay.sh', 'stream_app'],
                       check=True, capture_output=True)
        time.sleep(1)

        log('INFO', '  Iniciando streaming-server...')
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

        log('WARNING', f'  [!] streaming-server abortó al iniciar (intento {intento}/{max_intentos}). '
                        f'Reintentando...')
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

    log('INFO', f'  Captura (SD) → {STREAM_DIR}')
    log('INFO', f'  Archivos (USB) → {dest_usb}')
    return dest_usb


def id_dispositivo(directorio):
    """
    st_dev del punto de montaje de `directorio` — llamar una vez al
    arrancar la sesion y guardar el valor para comparar despues con
    verificar_usb().
    """
    return os.stat(directorio).st_dev


def verificar_usb(directorio, dev_id_esperado):
    """
    Chequea que el storage externo en `directorio` siga siendo el mismo
    dispositivo y siga aceptando escritura. Cubre los dos sintomas
    vistos en la desconexion del 02/07/2026: el USB reaparecio como un
    device node distinto (sda1 -> sdb1, detectado por cambio de st_dev)
    y el kernel lo remonto automaticamente a solo lectura tras abortar
    el journal ext4 (detectado con una escritura de prueba — st_dev
    solo no lo distingue, un remontado ro no cambia el numero de
    dispositivo).

    Devuelve None si todo esta bien, o un string con el motivo si algo
    cambio (para loguearlo y frenar la sesion antes de que la captura
    siguiente degrade en cascada, como paso esa vez).
    """
    try:
        st = os.stat(directorio)
    except OSError as e:
        return f'directorio inaccesible: {e}'

    if st.st_dev != dev_id_esperado:
        return f'cambio el dispositivo de bloque (st_dev {dev_id_esperado} -> {st.st_dev})'

    sentinel = os.path.join(directorio, '.chequeo_escritura')
    try:
        with open(sentinel, 'w') as f:
            f.write('ok')
        os.remove(sentinel)
    except OSError as e:
        return f'no se puede escribir (posible remontado read-only): {e}'

    return None


def mover_a_usb(archivo_sd, dest_usb, chunk_num):
    """Copia archivo de SD a USB y elimina el original (corre en thread)."""
    nombre  = os.path.basename(archivo_sd)
    destino = os.path.join(dest_usb, nombre)
    t0 = time.perf_counter()
    shutil.move(archivo_sd, destino)
    t = time.perf_counter() - t0
    size_mb = os.path.getsize(destino) / 1e6
    log('OK', f'  [USB] chunk {chunk_num:04d} → {nombre}'
              f'  ({size_mb:.0f} MB en {t:.0f}s | {size_mb/t:.1f} MB/s)')


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

    Nota color (2026-07-03): las lineas que pasan por log() pueden venir
    con codigos ANSI (para la terminal). El awk de abajo les saca el
    color (`gsub`) ANTES de matchear y guardar — la terminal recibe $0
    tal cual (con color), el archivo solo recibe la version sin color.
    Sin este gsub, un [!] coloreado quedaria en el archivo con los
    codigos ANSI crudos, ensuciando un log pensado para texto plano.

    Nota ruido benigno (2026-07-03): las lineas que matchean
    _RUIDO_BENIGNO (ej. "End of file", ver esa constante) se manejan
    aparte del resto — en vez del passthrough normal, se recolorean en
    amarillo (si hay TTY) y se suprimen del todo en verbosidad minima.
    El color/supresion se decide en Python (via _es_tty/_verbosidad) y
    se embebe como texto fijo en el programa de awk al construirlo, asi
    que awk no necesita saber nada de verbosidad ni de TTY.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'log_{prefix}_{condicion}_{session_ts}.txt')

    fd_stdout_real = os.dup(1)
    fd_stderr_real = os.dup(2)

    color_ruido = _NIVEL_COLOR['WARNING'] if _es_tty else ''
    reset_ruido = _RESET if _es_tty else ''
    suprimir_ruido = (_verbosidad == 'minimo')

    if suprimir_ruido:
        rama_ruido = ''   # no imprime nada a la terminal
    else:
        rama_ruido = 'print "' + color_ruido + '" plano "' + reset_ruido + '"'

    awk_prog = (
        '{ plano = $0; gsub(/' + _ESC + r'\[[0-9;]*m/, "", plano); '
        'if (tolower(plano) ~ /' + _RUIDO_BENIGNO + '/) { ' + rama_ruido + ' } '
        'else { print } '
        'if (tolower(plano) ~ /' + _PATRONES_AWK + '/) '
        'print plano >> "' + log_path + '"; fflush() }'
    )

    def _filtrar(fd_original, fd_salida):
        proc = subprocess.Popen(['awk', awk_prog], stdin=subprocess.PIPE, stdout=fd_salida)
        os.dup2(proc.stdin.fileno(), fd_original)

    _filtrar(1, fd_stdout_real)
    _filtrar(2, fd_stderr_real)

    def log_evento(mensaje, nivel='OK'):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        linea = f'  [LOG {ts}] {mensaje}'
        if _es_tty:
            color = _NIVEL_COLOR.get(nivel, '')
            os.write(fd_stdout_real, f'{color}{linea}{_RESET}\n'.encode())
        else:
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
    log('WARNING', f'\n  [!] Contexto de crash guardado en {crash_path}')
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
    log('OK', f'  [RED] chunk {chunk_num:04d} → {pc_host}:{pc_ruta}/{nombre}'
              f'  ({size_mb:.0f} MB en {t:.0f}s | {size_mb/t:.1f} MB/s)')
