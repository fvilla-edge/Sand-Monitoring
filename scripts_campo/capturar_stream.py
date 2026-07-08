#!/usr/bin/env python3
"""
capturar_stream.py — Captura continua via streaming FILE mode, 1 o 2 canales.

El streaming-server escribe a la SD interna (15 MB/s, suficiente para 7.8
MB/s de captura a dec=32 por canal). Cada chunk terminado se mueve al
destino (USB o red) en un thread de fondo mientras ya se captura el
siguiente. Eficiencia tipica: ~98%.

Formato del .bin: NO es raw plano — es un tren de segmentos [header]
[datos IN1][datos IN2 si esta activo][marcador de fin, 12 bytes 0xFF],
repetido hasta el final del archivo. Cada canal es un bloque contiguo
dentro del segmento (IN1 siempre primero, IN2 segundo — fijo por
construccion del formato, no depende de decimacion ni cableado). Para leer
estos .bin usar `analisis/revisar.py::_leer_canales_bin`, no `np.fromfile`
directo.

Con 2 canales el ancho de banda se duplica — usar `--decimacion 64` para
dual (unico valor validado sin perdida sostenida). Para minimizar perdida
de muestras en sesiones largas, usar `--duracion_chunk` lo mas grande que
el caso de uso permita (menos transiciones de chunk = menos perdida total).

Metadata en session_{condicion}_{ts}_info.json en el directorio destino
(campo "canales": 1 o 2).

Uso:
  python3 capturar_stream.py --condicion reposo --directorio /mnt/usb

  # 2 horas, chunks de 10 minutos, 1 canal
  python3 capturar_stream.py --condicion con_arena \
      --duracion_total 120 --duracion_chunk 10 --directorio /mnt/usb

  # dual, decimacion segura
  python3 capturar_stream.py --condicion con_arena --canales 2 \
      --decimacion 64 --duracion_total 120 --duracion_chunk 10 --directorio /mnt/usb
"""
import sys
import os
import time
import shutil
import argparse
import datetime
import threading
import subprocess
import json

sys.path.insert(0, '/root/rpsa_client/python_lib')
sys.path.insert(0, '/root/scripts_campo_comun')
import streaming
import campo_common as cc

FS_BASE          = cc.FS_BASE
ESPACIO_MIN_BASE = 500 * 1024 * 1024   # 500 MB minimo libre en USB, por canal
STREAM_DIR       = cc.STREAM_DIR
SERVER_BIN       = cc.SERVER_BIN
DEC_SEGURAS_DUAL = {64}   # unica probada sin perdida sostenida con 2 canales; ver docstring

_stop = cc.instalar_manejador_stop()


def _guardar_metadata(dest_dir, condicion, decimacion, fs_ef, session_ts, canales):
    """Escribe session_{condicion}_{ts}_info.json en el directorio destino."""
    if canales == 1:
        info = {
            'formato':       'streaming_file_segmentado',
            'descripcion':   'Segmentos [header][datos IN1][marcador 12B 0xFF] repetidos. '
                              'Parsear con analisis/revisar.py::_leer_canales_bin, no como raw plano.',
            'canales':       1,
        }
    else:
        info = {
            'formato':      'streaming_file_segmentado',
            'descripcion':  'Segmentos [header][datos IN1][datos IN2][marcador 12B 0xFF] repetidos '
                             '(bloques contiguos por canal, no intercalado por muestra). '
                             'Parsear con analisis/revisar.py::_leer_canales_bin, no como raw plano.',
            'canales':      2,
            'canal_ch1':     'IN1 — sensor codo (medicion), siempre primer bloque del segmento',
            'canal_ch2':     'IN2 — sensor referencia (ruido de linea), siempre segundo bloque del segmento',
        }
    info.update({
        'condicion':     condicion,
        'decimacion':    decimacion,
        'fs_hz_por_canal' if canales == 2 else 'fs_hz': fs_ef,
        'fs_base_hz':    FS_BASE,
        'sensor':        'VS150-RI',
        'gain':          'A_1_20 (HV jumper instalado, rango +-20V)' + (', ambos canales' if canales == 2 else ''),
        'acoplamiento':  'DC',
        'escala_voltios': '(valor_int16 / 32767.0) * 20.0  [aprox]',
        'fecha_inicio':  datetime.datetime.now().isoformat(),
        'ecosystem':     '3.00-e00665135 (Release_2026.1)',
    })
    json_name = f'session_{condicion}_{session_ts}_info.json'
    with open(os.path.join(dest_dir, json_name), 'w') as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    return json_name


def _capturar_chunk(confObj, adcObj, n_muestras, fs_ef, chunk_num, condicion, session_ts, canales, log_evento):
    """
    Dispara un chunk de n_muestras POR CANAL a SD y renombra el archivo resultante.
    Retorna (senal_s, ruta_archivo_en_sd).

    El evento de fin de chunk llega por dos vias: datos/errores de
    transporte via ADCCallback (colgado de adcObj), y el resultado del
    comando de parada (SD lleno, memoria, fin OK) via ConfigCallback
    (colgado de confObj).
    """
    done  = threading.Event()
    error = [None]

    class ADC_CB(streaming.ADCCallback):
        def receivePack(self, c, n): pass
        def connected(self, c, h):    pass
        def disconnected(self, c, h): pass
        def error(self, c, h, code):  error[0] = f'code={code}'; done.set()

    class Config_CB(streaming.ConfigCallback):
        # No escuchar 'adcServerStopped' generico: se dispara como aviso de
        # "todavia no arranco" antes del inicio real, no es el fin del chunk.
        def adcServerStoppedNoActiveChannels(self, c, h): error[0] = 'no-channels'; done.set()
        def adcServerStoppedMemError(self, c, h):         error[0] = 'mem-error'; done.set()
        def adcServerStoppedMemModify(self, c, h):        done.set()
        def adcServerStoppedSDFull(self, c, h):           error[0] = 'sd-full'; done.set()
        def adcServerStoppedSDDone(self, c, h):           done.set()
        def configError(self, c, h, code): pass
        def configErrorTimeout(self, c, h): pass

    adc_cb = ADC_CB()
    adcObj.setCallback(adc_cb)
    cfg_cb = Config_CB()
    confObj.addCallback(cfg_cb)

    confObj.sendConfig('samples_limit_sd', str(n_muestras))

    t0 = time.perf_counter()
    if not adcObj.startStreaming():
        raise RuntimeError("startStreaming fallo")

    # Timeout: tiempo de captura + flush a SD (15 MB/s) + margen
    bytes_por_muestra = 2 * canales
    bytes_esperados    = n_muestras * bytes_por_muestra
    flush_sd_s         = bytes_esperados / (12 * 1024 * 1024) + 20  # conservador 12 MB/s
    timeout_total      = n_muestras / fs_ef + flush_sd_s
    completado = done.wait(timeout=timeout_total)
    t_total = time.perf_counter() - t0

    if not completado:
        try:
            adcObj.stopStreaming()
        except Exception:
            pass
        time.sleep(2)

    # El cliente (confObj/adcObj) es unico para toda la sesion (ver
    # _nuevo_cliente) — sacar los callbacks de este chunk antes del proximo
    # evita que se acumulen escuchando eventos de chunks futuros.
    # removeCallback() de ADCStreamClient no toma argumentos; el de
    # ConfigStreamClient si.
    confObj.removeCallback(cfg_cb)
    adcObj.removeCallback()

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
    senal_s       = (bytes_totales // bytes_por_muestra) / fs_ef
    nombre_final  = os.path.join(
        STREAM_DIR,
        f'campo_{condicion}_{session_ts}_{chunk_num:04d}.bin'
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
    cc.log('OK', f'  [SD] campo_{condicion}_{session_ts}_{chunk_num:04d}.bin'
                 f'  ({senal_s:.1f}s | {t_total:.1f}s reloj | '
                 f'{eficiencia:.0f}% efic | {size_mb:.0f} MB)')
    if eficiencia < cc.UMBRAL_EFICIENCIA_BAJA:
        log_evento(f'EFICIENCIA BAJA en chunk {chunk_num}: {eficiencia:.0f}% '
                    f'(esperado ~90-98%)', nivel='WARNING')
    return senal_s, nombre_final


def _nuevo_cliente(args):
    """
    Crea, conecta y configura un par confObj (ConfigStreamClient) +
    adcObj (ADCStreamClient) — UNA VEZ por sesion, se reusa para todos los
    chunks (recrearlo entre chunks produce un SIGSEGV al reconectar).
    """
    confObj = streaming.ConfigStreamClient()
    adcObj  = streaming.ADCStreamClient(confObj)
    confObj.setVerbose(False)
    adcObj.setVerbose(False)
    if not confObj.connect():
        raise RuntimeError('no se pudo conectar al streaming-server')

    confObj.sendConfig('adc_pass_mode',        'FILE')
    confObj.sendConfig('adc_decimation',       str(args.decimacion))
    confObj.sendConfig('channel_attenuator_1', 'A_1_20')
    confObj.sendConfig('channel_state_1',      'ON')
    if args.canales == 2:
        confObj.sendConfig('channel_attenuator_2', 'A_1_20')
        confObj.sendConfig('channel_state_2',      'ON')
    else:
        confObj.sendConfig('channel_state_2',      'OFF')
    return confObj, adcObj


def main():
    p = argparse.ArgumentParser(
        description='Captura campo via streaming FILE mode — SD intermedia, USB/red destino, 1 o 2 canales'
    )
    p.add_argument('--condicion',      required=True, choices=['reposo', 'con_arena'])
    p.add_argument('--canales',        type=int, default=1, choices=[1, 2],
                   help='Cantidad de canales activos: 1 = mono/IN1 (default), 2 = dual IN1+IN2')
    p.add_argument('--decimacion',     type=int, default=32,
                   help='Factor de decimacion, por canal (default 32 → 3.906 MHz/canal)')
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
    p.add_argument('--verbosidad',     choices=['completo', 'minimo'], default='completo',
                   help='completo (default): todo, con color. minimo: solo warnings/errores')
    args = p.parse_args()

    cc.configurar_salida(args.verbosidad)

    if args.destino == 'red' and (not args.pc_host or not args.pc_ruta):
        sys.exit('ERROR: --destino red requiere --pc_host y --pc_ruta')

    if args.decimacion not in cc.DEC_VALIDOS:
        sys.exit(f'Decimacion invalida. Opciones: {sorted(cc.DEC_VALIDOS)}')

    if args.canales == 2 and args.decimacion not in DEC_SEGURAS_DUAL:
        cc.log('WARNING', f'\n  [!] ADVERTENCIA: decimacion={args.decimacion} con los 2 canales activos NO fue '
                           f'validada sin perdida de muestras — usar {sorted(DEC_SEGURAS_DUAL)} para dual.')
        cc.log('WARNING', f'      Se continua igual porque la decimacion queda a tu criterio, pero quedas avisado.\n')

    ESPACIO_MIN = ESPACIO_MIN_BASE * args.canales
    fs_ef      = FS_BASE / args.decimacion
    chunk_s    = args.duracion_chunk * 60.0
    total_s    = args.duracion_total * 60.0 if args.duracion_total else None
    n_muestras = int(fs_ef * chunk_s)

    session_ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path, log_evento = cc.activar_log_archivo('campo', args.condicion, session_ts)
    cc.log('INFO', f'  Log (solo errores/eventos) → {log_path}')

    cc.asegurar_servidor('/tmp/sstream_campo.log')
    dest_usb   = cc.preparar_dirs(args.directorio, 'stream_adc')
    usb_dev_id = cc.id_dispositivo(args.directorio)

    if args.destino == 'usb':
        mover_fn      = lambda archivo, num: cc.mover_a_usb(archivo, dest_usb, num)
        destino_label = dest_usb
    else:
        mover_fn      = lambda archivo, num: cc.mover_a_red(archivo, args.pc_host, args.pc_ruta, num)
        destino_label = f'{args.pc_host}:{args.pc_ruta}'

    try:
        confObj, adcObj = _nuevo_cliente(args)
    except RuntimeError as e:
        sys.exit(f'ERROR: {e}')

    json_name = _guardar_metadata(dest_usb, args.condicion, args.decimacion, fs_ef, session_ts, args.canales)

    if args.destino == 'red':
        subprocess.run(
            ['scp', '-q',
             os.path.join(dest_usb, json_name),
             f'{args.pc_host}:{args.pc_ruta}/'],
            check=True,
        )

    bytes_chunk = n_muestras * 2 * args.canales
    cc.log('INFO', f'\n=== CAPTURA CAMPO ({args.canales} canal{"es" if args.canales == 2 else ""}) — '
                    f'SD intermedia + {args.destino.upper()} destino ===')
    cc.log('INFO', f'  condicion  : {args.condicion}')
    if args.canales == 2:
        cc.log('INFO', f'  decimacion : {args.decimacion}  →  fs = {fs_ef/1e6:.4f} MHz por canal '
                        f'({fs_ef*2/1e6:.4f} MHz combinado)')
        cc.log('INFO', f'  chunk      : {args.duracion_chunk} min  ({n_muestras:,} muestras/canal | {bytes_chunk/1e6:.0f} MB)')
    else:
        cc.log('INFO', f'  decimacion : {args.decimacion}  →  fs = {fs_ef/1e6:.4f} MHz')
        cc.log('INFO', f'  chunk      : {args.duracion_chunk} min  ({n_muestras:,} muestras | {bytes_chunk/1e6:.0f} MB)')
    cc.log('INFO', f'  destino    : {destino_label}')
    if total_s:
        n_est = max(1, int(total_s / chunk_s))
        cc.log('INFO', f'  total      : {args.duracion_total} min  (~{n_est} chunks)')
    else:
        cc.log('INFO', f'  total      : indefinido  (Ctrl+C para detener)')
    cc.log('INFO', f'  Presiona Ctrl+C para detener.\n')

    log_evento(f'Sesion iniciada — condicion={args.condicion} canales={args.canales} decimacion={args.decimacion} '
                f'chunk={args.duracion_chunk}min destino={args.destino}')

    chunk_num        = 1
    tiempo_capturado = 0.0
    move_thread      = None

    try:
        while not _stop.activo:
            if total_s and tiempo_capturado >= total_s:
                cc.log('OK', '[OK] Tiempo total de sesion alcanzado.')
                break

            motivo_usb = cc.verificar_usb(args.directorio, usb_dev_id)
            if motivo_usb:
                cc.log('ERROR', f'[!] Storage externo con problema en {args.directorio}: '
                                 f'{motivo_usb}. Deteniendo sesion.')
                break

            libre_usb = shutil.disk_usage(args.directorio).free
            if libre_usb < ESPACIO_MIN:
                cc.log('ERROR', f'[!] USB sin espacio ({libre_usb/1e6:.0f} MB libres). Deteniendo.')
                break

            if total_s:
                restante = total_s - tiempo_capturado
                if restante < 2.0:
                    cc.log('OK', '[OK] Tiempo total de sesion alcanzado.')
                    break
                n = min(n_muestras, int(fs_ef * restante))
            else:
                n = n_muestras

            if args.destino == 'usb':
                espacio_label = f'USB {libre_usb/1e9:.2f} GB libres'
            else:
                libre_sd = shutil.disk_usage(STREAM_DIR).free
                espacio_label = f'SD {libre_sd/1e9:.2f} GB libres'
            cc.log('INFO', f'--- Chunk {chunk_num:04d} | {espacio_label} ---')

            secs, archivo_sd = _capturar_chunk(
                confObj, adcObj, n, fs_ef, chunk_num, args.condicion, session_ts, args.canales, log_evento)
            tiempo_capturado += secs

            # confObj/adcObj se reusan para toda la sesion — no se reconecta
            # entre chunks (ver _nuevo_cliente). Si el streaming-server
            # llegara a morirse solo entre chunks, el proximo
            # startStreaming() en _capturar_chunk va a fallar y la excepcion
            # sube hasta el supervisor externo (relanzar_captura.sh) para
            # reiniciar la sesion completa.

            # Esperar que termine el move anterior si sigue corriendo
            if move_thread and move_thread.is_alive():
                cc.log('INFO', '  [esperando move anterior...]')
                move_thread.join()

            # Mover este chunk en background (mientras captura el siguiente)
            move_thread = threading.Thread(
                target=mover_fn,
                args=(archivo_sd, chunk_num),
                daemon=True,
            )
            move_thread.start()
            chunk_num += 1

    except Exception as e:
        cc.guardar_contexto_crash('campo', args.condicion, session_ts, chunk_num, e)
        raise

    finally:
        # Esperar que el ultimo move termine antes de salir
        if move_thread and move_thread.is_alive():
            cc.log('INFO', f'\n  [esperando ultimo move a {args.destino.upper()}...]')
            move_thread.join()
        cc.log('OK', f'\n=== SESION TERMINADA ===')
        cc.log('OK', f'  Chunks guardados : {chunk_num - 1}')
        cc.log('OK', f'  Tiempo capturado : {tiempo_capturado/60:.2f} min  ({tiempo_capturado:.0f}s)')
        cc.log('OK', f'  Archivos en       : {destino_label}')
        log_evento(f'Sesion terminada — {chunk_num - 1} chunks, '
                    f'{tiempo_capturado/60:.2f} min capturados')


if __name__ == '__main__':
    main()
