#!/usr/bin/env python3
"""
revisar.py — Revision rapida de capturas de campo en PC (mono o dual).

Acepta:
  - Archivos .bin (capturar_stream.py, requiere session_*_info.json)
  - Directorios   (busca campo_*.bin recursivamente)

La cantidad de canales se detecta por archivo leyendo "canales" (1 o 2) del
JSON de sesion — no hace falta indicarlo por linea de comandos. Un mismo lote
puede mezclar capturas mono y dual: se muestran en tablas separadas.

Mono: kurtosis, crest factor, fraccion_activa y rms_diferencial sobre la
senal filtrada (25-400 kHz — migrado desde 100-450 kHz para usar la misma
banda que ver_forma_onda.py, ver constantes BANDA_LOW/BANDA_HIGH mas abajo;
los umbrales de referencia de kurtosis/fraccion_activa de
INTERPRETACION_RESULTADOS.md fueron calibrados con la banda VIEJA — no
aplican tal cual a los numeros que salen de aca hasta recalibrar).

Dual (CH1 codo / CH2 referencia): mismas metricas por canal (incluye crest
factor cf1/cf2) mas kurtosis_diff (k1-k2) y rms_ratio (CH1/CH2) para separar
arena de ruido de linea comun a ambos sensores.

rms_diferencial usa como baseline la mediana del RMS de las ventanas de
FONDO (kurtosis < FA_THRESH) DEL PROPIO ARCHIVO — AUTOCALIBRADO, mismo
criterio que ver_forma_onda.py (formula Gao 2015 sobre ese baseline, ver
analisis/INTERPRETACION_RESULTADOS.md). Ya NO depende de que el lote tenga
una carpeta 'reposo' al lado, ni de comparar contra una captura de otro dia
o sesion — eso varia por causas ajenas a la arena (turbulencia, ganancia,
acoplamiento del sensor ese dia). Si un archivo no tiene ninguna ventana de
fondo propia (saturado de arena de punta a punta, sin ningun tramo de
calma), cae a --baseline externo si esta disponible (ver mas abajo); sin
eso, rms_dif/rd1/rd2 quedan en N/A para ese archivo/canal.

Uso:
  .venv/bin/python3 analisis/revisar.py /mnt/usb/0_0_reposo_20260630_134042/
  .venv/bin/python3 analisis/revisar.py campo_reposo_*.bin campo_con_arena_*.bin

Con --baseline analisis/baseline_confirmado.json (ver generar_baseline.py),
rms_diferencial usa ese baseline confirmado como RESPALDO, solo para los
archivos/canales sin ventanas de fondo propias — mas solido que inventar un
"reposo" del lote que puede no estar confirmado de verdad (ver sec.151 de
la memoria del proyecto).

Formato del .bin: NO es raw plano — es un tren de segmentos [header][datos
canal0][datos canal1][marcador fin, 12 bytes 0xFF]. El tamaño de header
varia segun firmware (112 o 144 bytes) y se autodetecta por archivo — ver
`_leer_canales_bin` mas abajo.
"""
import re
import sys
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt
from scipy.stats import kurtosis as scipy_kurtosis

BANDA_LOW   = 25_000    # Hz — migrado de 100_000 a la banda de ver_forma_onda.py
BANDA_HIGH  = 400_000   # Hz — migrado de 450_000, idem
FILTRO_ORD  = 4
FA_WINDOW_S = 0.050     # 50 ms por ventana
FA_THRESH   = 6         # kurtosis Pearson >= 6 → ventana activa (KURT_FIJO_ACUMULADO de ver_forma_onda.py, calibrado contra la purga de 8kg confirmada del 3/9 — ver sec.163/165 de la memoria del proyecto). Antes: 20, calibrado para la banda vieja (100-450kHz).

V_REF = 20.0            # ±20V con jumper HV y gain A_1_20

# El tamaño de header cambia segun firmware: 144 bytes en Release_2026.1 en
# adelante (coincide con el struct oficial CBinInfo::BinHeader, w_binary.h
# del repo Red Pitaya), 112 bytes en firmware anterior (sin struct oficial
# publicado). Se autodetecta por archivo — un mismo lote puede mezclar
# capturas de ambos firmwares.
_HEADER_SIZES_CONOCIDOS = (144, 112)   # probar 144 primero (firmware vigente)
_MARKER      = b'\xff' * 12  # fin de segmento
_OFF_SIZE_CH = 4              # offset del array sizeCh[4] (uint32 LE) dentro del header

# lostCount[4] (uint64 LE, muestras perdidas por canal), oscRate[4] (uint64
# LE, Hz efectivos post-decimacion), timeCapture[4] (int64 LE, ns desde epoca
# Unix, timestamp de hardware por segmento) y sigmentLength (uint32, bytes
# totales de datos del segmento = suma de sizeCh) — offsets del struct
# oficial CBinInfo::BinHeader. Solo existen en el header de 144 bytes; en el
# de 112 (sin struct publicado) quedan como None en vez de asumir un offset
# no verificado.
#
# timeCapture confirmado como timestamp real de hardware (no un contador
# derivado de "muestras esperadas sin perdida"): en un segmento con
# lostCount=26032 a fs=3906250 Hz, el salto hacia el siguiente timeCapture
# fue exactamente 6.664.192 ns mayor que lo normal — exactamente 26032/fs en
# ns. O sea, SI incluye el tiempo real de las muestras perdidas, a diferencia
# de len(muestras)/fs que solo cuenta lo que efectivamente llego.
_OFF_LOST_COUNT     = 40
_OFF_OSC_RATE       = 72
_OFF_TIME_CAPTURE   = 104
_OFF_SIGMENT_LENGTH = 136
_TOLERANCIA_OSC_RATE = 0.005   # 0.5% — margen contra redondeo de fs


def _detectar_header_size(f, tam):
    """Prueba los tamaños de header conocidos contra el primer segmento del
    archivo y devuelve el que hace calzar el marcador de fin de segmento."""
    for candidato in _HEADER_SIZES_CONOCIDOS:
        if candidato + 12 > tam:
            continue
        f.seek(0)
        header = f.read(candidato)
        size_ch = np.frombuffer(header, dtype='<u4', count=4, offset=_OFF_SIZE_CH)
        marker_off = candidato + int(size_ch.sum())
        if marker_off + 12 > tam:
            continue
        f.seek(marker_off)
        if f.read(12) == _MARKER:
            return candidato
    raise ValueError(
        f'no se pudo determinar el tamaño de header del formato FILE '
        f'(probados: {_HEADER_SIZES_CONOCIDOS}) — ¿archivo de un firmware nuevo?')


def _leer_canales_bin(ruta):
    """
    Recorre el archivo segmento por segmento (header + datos + marcador) y
    devuelve (ch0, ch1, meta) — ch0/ch1 son arrays int16 con SOLO muestras
    reales, sin los bytes de header/marcador mezclados adentro.

    ch0/ch1 corresponden a los canales tal cual los arma el streaming-server
    (indice 0 = IN1, indice 1 = IN2, orden fijo — cada canal es un bloque
    contiguo dentro del segmento, no hay interleaving por muestra). En
    mono, ch1 queda vacio.

    meta trae, si el header es de 144 bytes (2026.1+; None si es el de 112,
    ver constantes de arriba):
      - lost0/lost1: muestras perdidas acumuladas por canal (suma de
        lostCount de todos los segmentos del archivo)
      - osc0/osc1: oscRate en Hz reportado por el primer segmento (se asume
        constante durante toda la sesion, no cambia la decimacion a mitad de
        una captura)
      - dur_real_s: duracion real de la captura en segundos, calculada con
        timeCapture (timestamp de hardware) del primer y ultimo segmento
        leido, mas la duracion del propio ultimo segmento. A diferencia de
        len(ch0)/fs, SI incluye el tiempo de las muestras perdidas (ver nota
        de timeCapture junto a las constantes de arriba). None si no hay
        ningun segmento con header de 144 bytes.

    Si el ultimo segmento quedo truncado (sesion cortada a mitad de escritura)
    se corta ahi y se avisa por stderr, en vez de fallar o inventar datos.
    Tambien se avisa por stderr si sigmentLength (offset 136, redundante con
    sizeCh) no coincide con la suma de sizeCh declarada en el mismo header —
    señal de corrupcion que el chequeo de marcador podria no detectar.
    """
    ch0_partes, ch1_partes = [], []
    header_144 = None
    lost0 = lost1 = 0
    osc0 = osc1 = None
    t_inicio = t_ultimo = None
    tam_ultimo_ch0 = 0
    tam = ruta.stat().st_size
    with open(ruta, 'rb') as f:
        header_size = _detectar_header_size(f, tam)
        header_144 = header_size == 144
        pos = 0
        n_seg = 0
        while pos + header_size <= tam:
            f.seek(pos)
            header = f.read(header_size)
            size_ch0, size_ch1, size_ch2, size_ch3 = np.frombuffer(
                header, dtype='<u4', count=4, offset=_OFF_SIZE_CH)
            fin_datos = pos + header_size + int(size_ch0) + int(size_ch1) + int(size_ch2) + int(size_ch3)
            if fin_datos + 12 > tam:
                print(f'[!] {ruta.name}: segmento {n_seg} truncado al final del archivo, se descarta', file=sys.stderr)
                break
            f.seek(pos + header_size)
            ch0_partes.append(f.read(int(size_ch0)))
            ch1_partes.append(f.read(int(size_ch1)))
            f.seek(fin_datos)
            marcador = f.read(12)
            if marcador != _MARKER:
                print(f'[!] {ruta.name}: marcador invalido en segmento {n_seg} (offset {fin_datos}), '
                      f'se corta la lectura ahi', file=sys.stderr)
                break
            if header_144:
                size_declarado = int(size_ch0) + int(size_ch1) + int(size_ch2) + int(size_ch3)
                sigment_length = int(np.frombuffer(header, dtype='<u4', count=1, offset=_OFF_SIGMENT_LENGTH)[0])
                if sigment_length != size_declarado:
                    print(f'[!] {ruta.name}: sigmentLength del header ({sigment_length}) no coincide '
                          f'con sizeCh declarado ({size_declarado}) en segmento {n_seg}', file=sys.stderr)
                lost_ch = np.frombuffer(header, dtype='<u8', count=4, offset=_OFF_LOST_COUNT)
                lost0 += int(lost_ch[0])
                lost1 += int(lost_ch[1])
                t_cap = int(np.frombuffer(header, dtype='<i8', count=1, offset=_OFF_TIME_CAPTURE)[0])
                if n_seg == 0:
                    osc_ch = np.frombuffer(header, dtype='<u8', count=4, offset=_OFF_OSC_RATE)
                    osc0, osc1 = int(osc_ch[0]), int(osc_ch[1])
                    t_inicio = t_cap
                t_ultimo = t_cap
                tam_ultimo_ch0 = int(size_ch0)
            pos = fin_datos + 12
            n_seg += 1

    ch0 = np.frombuffer(b''.join(ch0_partes), dtype='<i2')
    ch1 = np.frombuffer(b''.join(ch1_partes), dtype='<i2')
    dur_real_s = None
    if header_144 and t_inicio is not None and osc0:
        dur_real_s = (t_ultimo - t_inicio) / 1e9 + (tam_ultimo_ch0 // 2) / osc0
    meta = {
        'lost0': lost0 if header_144 else None,
        'lost1': lost1 if header_144 else None,
        'osc0': osc0,
        'osc1': osc1,
        'dur_real_s': dur_real_s,
        # timeCapture del primer segmento (ns desde epoca Unix, reloj de HW) —
        # None en header de 112 bytes. Usado por timeline_lote.py para ubicar
        # cada archivo en un eje de tiempo absoluto real, no asumido.
        't_inicio_ns': t_inicio if header_144 else None,
    }
    return ch0, ch1, meta


def _chequear_osc_rate(ruta, osc_rate, fs_esperado, canal_label=''):
    """Avisa por stderr si el oscRate del header no coincide con el fs
    esperado segun la decimacion configurada en el JSON de sesion. None
    (header viejo de 112 bytes, sin este campo) no se chequea."""
    if osc_rate is None:
        return None
    ok = abs(osc_rate - fs_esperado) / fs_esperado < _TOLERANCIA_OSC_RATE
    if not ok:
        print(f'[!] {ruta.name}: oscRate del header{canal_label} ({osc_rate:.0f} Hz) '
              f'no coincide con fs esperado ({fs_esperado:.0f} Hz)', file=sys.stderr)
    return ok


def _bandpass(signal, fs):
    sos = butter(FILTRO_ORD, [BANDA_LOW, BANDA_HIGH], btype='band', fs=fs, output='sos')
    return sosfilt(sos, signal)


def _metricas_por_ventana(sig, fs):
    """(kurt_w, rms_w) por ventana de FA_WINDOW_S — mismo criterio que
    _kurtosis_por_ventana/_rms_por_ventana_directo de ver_forma_onda.py.
    Base compartida de fraccion_activa y del baseline autocalibrado del rms
    diferencial (ver _baseline_autocalibrado)."""
    n_win   = int(fs * FA_WINDOW_S)
    n_total = len(sig) // n_win
    if n_total == 0:
        return np.array([]), np.array([])
    mat = sig[:n_total * n_win].reshape(n_total, n_win)
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2  = np.mean(mat ** 2, axis=1)
    m4  = np.mean(mat ** 4, axis=1)
    kurt_w = m4 / np.where(m2 > 0, m2 ** 2, 1e-30)
    rms_w  = np.sqrt(m2)
    return kurt_w, rms_w


def _fraccion_activa(kurt_w):
    if len(kurt_w) == 0:
        return 0.0
    return float(np.mean(kurt_w >= FA_THRESH) * 100)


def _baseline_autocalibrado(kurt_w, rms_w):
    """Mediana del RMS de las ventanas de FONDO (kurt_w < FA_THRESH) DEL
    PROPIO ARCHIVO — mismo criterio que el RMS diferencial autocalibrado de
    ver_forma_onda.py, en vez de depender de un 'reposo' externo de otro
    archivo/sesion/dia (que varia por causas ajenas a la arena). None si el
    archivo no tiene ninguna ventana de fondo (saturado de arena de punta a
    punta) — en ese caso rms_diferencial cae al baseline confirmado externo
    (--baseline) si esta disponible, ver _agregar_rms_diferencial_mono/dual."""
    fondo = rms_w[kurt_w < FA_THRESH]
    if len(fondo) == 0:
        return None
    return float(np.median(fondo))


def _chunk_num_from_nombre(stem):
    try:
        return int(stem.rsplit('_', 1)[-1])
    except ValueError:
        return 0


def _cargar_info(ruta):
    """Busca el JSON de sesion de `ruta`, con fallback a session_info.json
    para capturas viejas sin el nombre por condicion/timestamp."""
    m = re.match(r'campo_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
    info_path = None
    if m:
        candidato = ruta.parent / f'session_{m.group(1)}_{m.group(2)}_info.json'
        if candidato.exists():
            info_path = candidato
    if info_path is None:
        info_path = ruta.parent / 'session_info.json'
    if not info_path.exists():
        raise FileNotFoundError(f"No se encontro JSON de sesion en {ruta.parent}")
    with open(info_path) as f:
        return json.load(f)


def _calcular_mono(ruta, info):
    fs    = float(info['fs_hz'])
    cond  = str(info.get('condicion', '?'))
    chunk = _chunk_num_from_nombre(ruta.stem)
    dec   = info.get('decimacion')

    raw, _, meta = _leer_canales_bin(ruta)
    signal = raw.astype(np.float32) * (V_REF / 32767.0)
    dur_s  = len(signal) / fs
    size   = ruta.stat().st_size / 1e6

    sig_f = _bandpass(signal, fs)
    rms   = float(np.sqrt(np.mean(sig_f ** 2)))
    pico  = float(np.max(np.abs(sig_f)))
    kurt  = float(scipy_kurtosis(sig_f, fisher=False))
    cf    = float(pico / rms) if rms > 0 else 0.0
    kurt_w, rms_w = _metricas_por_ventana(sig_f, fs)
    fa    = _fraccion_activa(kurt_w)
    baseline_auto = _baseline_autocalibrado(kurt_w, rms_w)

    _chequear_osc_rate(ruta, meta['osc0'], fs)

    dur_real_min = meta['dur_real_s'] / 60 if meta['dur_real_s'] is not None else None

    return {
        'archivo': ruta.name, 'cond': cond, 'chunk': chunk, 'dur_min': dur_s / 60,
        'dur_real_min': dur_real_min, 'decimacion': dec,
        'rms': rms, 'kurt': kurt, 'crest': cf, 'fa_pct': fa, 'size_mb': size,
        'lost': meta['lost0'], 'baseline_auto': baseline_auto,
    }


def _calcular_dual(ruta, info):
    dec  = int(info.get('decimacion', 64))
    fs   = float(info.get('fs_hz_por_canal', 125_000_000 / dec))
    cond = str(info.get('condicion', '?'))

    ch1_i16, ch2_i16, meta = _leer_canales_bin(ruta)

    ch1 = ch1_i16.astype(np.float32) * (V_REF / 32767.0)
    ch2 = ch2_i16.astype(np.float32) * (V_REF / 32767.0)
    dur_s = len(ch1) / fs
    chunk = _chunk_num_from_nombre(ruta.stem)
    size  = ruta.stat().st_size / 1e6

    f1 = _bandpass(ch1, fs)
    f2 = _bandpass(ch2, fs)

    rms1  = float(np.sqrt(np.mean(f1 ** 2)))
    rms2  = float(np.sqrt(np.mean(f2 ** 2)))
    pico1 = float(np.max(np.abs(f1)))
    pico2 = float(np.max(np.abs(f2)))
    cf1   = float(pico1 / rms1) if rms1 > 0 else 0.0
    cf2   = float(pico2 / rms2) if rms2 > 0 else 0.0
    k1   = float(scipy_kurtosis(f1, fisher=False))
    k2   = float(scipy_kurtosis(f2, fisher=False))
    kurt_w1, rms_w1 = _metricas_por_ventana(f1, fs)
    kurt_w2, rms_w2 = _metricas_por_ventana(f2, fs)
    fa1  = _fraccion_activa(kurt_w1)
    fa2  = _fraccion_activa(kurt_w2)
    baseline_auto1 = _baseline_autocalibrado(kurt_w1, rms_w1)
    baseline_auto2 = _baseline_autocalibrado(kurt_w2, rms_w2)

    _chequear_osc_rate(ruta, meta['osc0'], fs, canal_label=' ch1')
    _chequear_osc_rate(ruta, meta['osc1'], fs, canal_label=' ch2')

    dur_real_min = meta['dur_real_s'] / 60 if meta['dur_real_s'] is not None else None

    return {
        'archivo': ruta.name, 'cond': cond, 'chunk': chunk, 'dur_min': dur_s / 60,
        'dur_real_min': dur_real_min, 'decimacion': dec,
        'rms1': rms1, 'rms2': rms2, 'cf1': cf1, 'cf2': cf2,
        'k1': k1, 'k2': k2, 'dk': k1 - k2,
        'fa1': fa1, 'fa2': fa2, 'rms_r': rms1 / rms2 if rms2 > 0 else 0.0,
        'size_mb': size, 'lost1': meta['lost0'], 'lost2': meta['lost1'],
        'baseline_auto1': baseline_auto1, 'baseline_auto2': baseline_auto2,
    }


def _calcular(ruta):
    ruta = Path(ruta)
    if ruta.suffix != '.bin':
        raise ValueError(f"Formato no soportado: {ruta.suffix}")
    info    = _cargar_info(ruta)
    canales = int(info.get('canales', 1))
    r = _calcular_dual(ruta, info) if canales == 2 else _calcular_mono(ruta, info)
    r['canales'] = canales
    return r


def _clave_config(canales, decimacion):
    return f"{'mono' if canales == 1 else 'dual'}_dec{decimacion}"


def cargar_baseline_externo(ruta):
    """Carga el JSON generado por generar_baseline.py (ver ese script para
    como se arma). Devuelve el dict 'configs' (clave 'mono_dec32'/'dual_dec64'/
    etc. -> {'rms': ...} o {'rms1':..., 'rms2':...}), o {} si el archivo no
    tiene esa clave."""
    with open(ruta) as f:
        data = json.load(f)
    return data.get('configs', {})


def _agregar_rms_diferencial_mono(resultados, baseline_externo=None):
    """rms_diferencial por archivo. Baseline preferido:
    1. AUTOCALIBRADO (mediana del RMS de las ventanas de fondo, kurt_w <
       FA_THRESH, DEL PROPIO ARCHIVO — ver _baseline_autocalibrado, mismo
       criterio que ver_forma_onda.py). No depende de otros archivos del
       lote ni de que dia se capturaron.
    2. Si el archivo no tiene ninguna ventana de fondo propia (saturado de
       arena de punta a punta), cae a baseline_externo (--baseline, ver
       generar_baseline.py) para la (canales=1, decimacion) del archivo, si
       esta disponible.
    Si ninguno de los dos aplica, rms_dif queda en None (N/A). Ya NO se usa
    la mediana de 'reposo' del lote (comparar contra otro archivo/sesion no
    tiene sentido, ver ver_forma_onda.py)."""
    for r in resultados:
        baseline = r.get('baseline_auto')
        modo = 'auto'
        if baseline is None:
            cfg = (baseline_externo or {}).get(_clave_config(1, r.get('decimacion')))
            if cfg:
                baseline, modo = cfg['rms'], 'confirmado'
        if baseline is None:
            r['rms_dif'] = None
            r['baseline_modo'] = None
            continue
        r['rms_dif'] = float(np.sqrt(max(0.0, r['rms'] ** 2 - baseline ** 2)) / baseline)
        r['baseline_modo'] = modo


def _agregar_rms_diferencial_dual(resultados, baseline_externo=None):
    """rd1/rd2 por chunk. Baseline preferido POR CANAL:
    1. AUTOCALIBRADO (mediana del RMS de las ventanas de fondo del PROPIO
       archivo, ver _baseline_autocalibrado) — no depende de otros archivos
       del lote/sesion.
    2. Si ese canal no tiene ninguna ventana de fondo propia (saturado de
       arena de punta a punta), cae a baseline_externo (--baseline) para la
       (canales=2, decimacion) del lote, si esta disponible.
    Si ninguno de los dos aplica para un canal, ese rd queda en None (N/A).
    Los dos canales de un mismo archivo pueden terminar con fuentes
    distintas (uno auto, otro confirmado) — rd_modo lo marca como 'mixto'
    en ese caso. Ya NO se usa 'reposo' del lote ni el fallback in-session
    (rms minimo de la sesion) — comparar contra otro archivo/sesion no
    tiene sentido, ver ver_forma_onda.py."""
    dec = resultados[0].get('decimacion') if resultados else None
    cfg = (baseline_externo or {}).get(_clave_config(2, dec))

    for r in resultados:
        base1, fuente1 = r.get('baseline_auto1'), 'auto'
        if base1 is None and cfg:
            base1, fuente1 = cfg['rms1'], 'confirmado'
        base2, fuente2 = r.get('baseline_auto2'), 'auto'
        if base2 is None and cfg:
            base2, fuente2 = cfg['rms2'], 'confirmado'

        r['rd1'] = float(np.sqrt(max(0.0, r['rms1'] ** 2 - base1 ** 2)) / base1) if base1 else None
        r['rd2'] = float(np.sqrt(max(0.0, r['rms2'] ** 2 - base2 ** 2)) / base2) if base2 else None

        if r['rd1'] is None and r['rd2'] is None:
            r['rd_modo'] = None
        elif r['rd1'] is None or r['rd2'] is None or fuente1 == fuente2:
            r['rd_modo'] = fuente1 if r['rd1'] is not None else fuente2
        else:
            r['rd_modo'] = 'mixto'


def _detectar_mono(r):
    if r['kurt'] > FA_THRESH or r['fa_pct'] > 5:
        return '*** ARENA ***'
    return 'reposo'


def _detectar_dual(r):
    k1, k2 = r['k1'], r['k2']
    if k1 > FA_THRESH and k2 > FA_THRESH:
        return 'RUIDO COMUN'   # ambos canales impulsivos -> no es arena localizada
    if k1 > FA_THRESH and k1 > 3 * k2:
        return '*** ARENA ***'
    return 'reposo'


def _recopilar_rutas(args):
    rutas = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            rutas.extend(sorted(p.glob('campo_*.bin')))
        elif p.exists():
            rutas.append(p)
        else:
            print(f'[!] No encontrado: {a}')
    return rutas


def _mostrar_mono(resultados, baseline_externo=None):
    _agregar_rms_diferencial_mono(resultados, baseline_externo)
    n_confirmado = sum(1 for r in resultados if r.get('baseline_modo') == 'confirmado')
    n_na = sum(1 for r in resultados if r['rms_dif'] is None)
    if n_confirmado:
        print(f'[OK] rms_diferencial: {n_confirmado}/{len(resultados)} archivo(s) sin ventanas de fondo propias, '
              f'usando baseline CONFIRMADO externo (--baseline)')
    if n_na:
        print(f'[!] rms_diferencial: {n_na}/{len(resultados)} archivo(s) sin baseline (ni ventanas de fondo propias '
              f'ni --baseline) — N/A')

    ancho = max(len(r['archivo']) for r in resultados)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'chunk':>5}  "
              f"{'dur':>6}  {'dur_r':>7}  {'kurt':>7}  {'crest':>6}  {'fa%':>5}  {'rms_dif':>7}  {'perd':>6}  {'MB':>6}  deteccion")
    sep = '-' * len(header)
    print(f'\n=== MONO ({len(resultados)} archivos) ===')
    print(sep)
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar_mono(r)
        rd     = f"{r['rms_dif']:>7.2f}" if r['rms_dif'] is not None else f"{'N/A':>7}"
        perd   = f"{r['lost']:>6}" if r['lost'] is not None else f"{'N/A':>6}"
        dur_r  = f"{r['dur_real_min']:.2f}m" if r['dur_real_min'] is not None else 'N/A'
        print(
            f"{r['archivo']:<{ancho}}  "
            f"{r['cond']:<10}  "
            f"{r['chunk']:>5}  "
            f"{r['dur_min']:>5.2f}m  "
            f"{dur_r:>7}  "
            f"{r['kurt']:>7.1f}  "
            f"{r['crest']:>6.1f}  "
            f"{r['fa_pct']:>4.1f}%  "
            f"{rd}  "
            f"{perd}  "
            f"{r['size_mb']:>6.1f}  "
            f"{det}"
        )

    print(sep)
    n_arena  = sum(1 for r in resultados if _detectar_mono(r) != 'reposo')
    n_reposo = len(resultados) - n_arena
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_reposo} en reposo')
    print()
    print(f'  Referencia: kurtosis reposo ~3 | arena >{FA_THRESH}  |  fa% reposo 0% | arena >25%')
    print('  rms_diferencial (informativo, no afecta deteccion): sqrt(max(0,rms²-baseline²))/baseline,')
    print(f'  baseline = AUTOCALIBRADO (mediana RMS de ventanas propias con kurtosis<{FA_THRESH}); si el archivo no')
    print('  tiene ventanas de fondo propias cae a --baseline externo | <0.1 insignificante | 0.1-0.4 leve | >0.4 significativo')
    print('  perd = muestras perdidas (lostCount del header, N/A en archivos pre-2026.1 sin ese campo).')
    print('  dur_r = duracion real del chunk segun el reloj de hardware (timeCapture del header) —')
    print('  a diferencia de "dur" (basada en cantidad de muestras), SI incluye el tiempo de "perd".')
    print('  dur_r > dur revela tiempo real perdido, no solo conteo de muestras; N/A en archivos pre-2026.1.')
    print('  oscRate del header se valida contra fs esperado — mismatch avisa por stderr, no aparece en la tabla.')


def _mostrar_dual(resultados, baseline_externo=None):
    _agregar_rms_diferencial_dual(resultados, baseline_externo)
    n_confirmado = sum(1 for r in resultados if r.get('rd_modo') == 'confirmado')
    n_mixto = sum(1 for r in resultados if r.get('rd_modo') == 'mixto')
    n_na = sum(1 for r in resultados if r.get('rd_modo') is None)
    if n_confirmado or n_mixto:
        print(f'[OK] rd1/rd2: {n_confirmado}/{len(resultados)} archivo(s) sin ventanas de fondo propias en NINGUN '
              f'canal usando baseline CONFIRMADO externo (--baseline), {n_mixto} con un canal auto y otro confirmado')
    if n_na:
        print(f'[!] rd1/rd2: {n_na}/{len(resultados)} archivo(s) sin baseline en ningun canal '
              f'(ni ventanas de fondo propias ni --baseline) — N/A')

    ancho = max(len(r['archivo']) for r in resultados)

    header = (f"{'archivo':<{ancho}}  {'cond':<10}  {'ck':>5}  {'dur':>6}  {'dur_r':>7}  "
              f"{'k1':>7}  {'k2':>7}  {'dk':>7}  "
              f"{'cf1':>6}  {'cf2':>6}  "
              f"{'fa1%':>5}  {'fa2%':>5}  {'rms_r':>6}  {'rd1':>6}  {'rd2':>6}  "
              f"{'perd1':>6}  {'perd2':>6}  {'MB':>6}  deteccion")
    sep = '-' * len(header)
    print(f'\n=== DUAL ({len(resultados)} archivos) ===')
    print(sep)
    print(header)
    print(sep)

    for r in resultados:
        det = _detectar_dual(r)
        rd1   = f"{r['rd1']:>6.2f}" if r['rd1'] is not None else f"{'N/A':>6}"
        rd2   = f"{r['rd2']:>6.2f}" if r['rd2'] is not None else f"{'N/A':>6}"
        perd1 = f"{r['lost1']:>6}" if r['lost1'] is not None else f"{'N/A':>6}"
        perd2 = f"{r['lost2']:>6}" if r['lost2'] is not None else f"{'N/A':>6}"
        dur_r = f"{r['dur_real_min']:.2f}m" if r['dur_real_min'] is not None else 'N/A'
        print(
            f"{r['archivo']:<{ancho}}  "
            f"{r['cond']:<10}  "
            f"{r['chunk']:>5}  "
            f"{r['dur_min']:>5.2f}m  "
            f"{dur_r:>7}  "
            f"{r['k1']:>7.1f}  "
            f"{r['k2']:>7.1f}  "
            f"{r['dk']:>7.1f}  "
            f"{r['cf1']:>6.1f}  "
            f"{r['cf2']:>6.1f}  "
            f"{r['fa1']:>4.1f}%  "
            f"{r['fa2']:>4.1f}%  "
            f"{r['rms_r']:>6.2f}  "
            f"{rd1}  "
            f"{rd2}  "
            f"{perd1}  "
            f"{perd2}  "
            f"{r['size_mb']:>6.1f}  "
            f"{det}"
        )

    print(sep)
    n_arena  = sum(1 for r in resultados if _detectar_dual(r) == '*** ARENA ***')
    n_ruido  = sum(1 for r in resultados if _detectar_dual(r) == 'RUIDO COMUN')
    n_reposo = len(resultados) - n_arena - n_ruido
    dur_tot  = sum(r['dur_min'] for r in resultados)
    print(f'\n  {len(resultados)} archivos | {dur_tot:.1f} min total | '
          f'{n_arena} con arena | {n_ruido} ruido comun | {n_reposo} en reposo')
    print()
    print('  Referencia reposo: k1~3, k2~3, dk~0, fa1%~0, fa2%~0, rms_r~1, cf~5-6')
    print(f'  Referencia arena:  k1>{FA_THRESH}, k2~3, dk>>0, fa1%>25, rms_r>1, cf mas alto que reposo')
    print('  cf1/cf2 = crest factor por canal (pico/rms de la señal filtrada).')
    print('  rd1/rd2 (informativo, no afecta deteccion): rms_diferencial por canal,')
    print(f'  baseline = AUTOCALIBRADO por canal (mediana RMS de ventanas propias con kurtosis<{FA_THRESH}); si ese')
    print('  canal no tiene ventanas de fondo propias cae a --baseline externo (ver arriba)')
    print('  | <0.1 insignificante | 0.1-0.4 leve | >0.4 significativo.')
    print('  ch1=IN1, ch2=IN2 por construccion del formato (ver _leer_canales_bin) — ya no depende de pares/impares.')
    print('  perd1/perd2 = muestras perdidas por canal (lostCount del header, N/A en archivos pre-2026.1 sin ese campo).')
    print('  dur_r = duracion real del chunk segun el reloj de hardware (timeCapture del header) —')
    print('  a diferencia de "dur" (basada en cantidad de muestras), SI incluye el tiempo de "perd1/perd2".')
    print('  dur_r > dur revela tiempo real perdido, no solo conteo de muestras; N/A en archivos pre-2026.1.')
    print('  oscRate del header se valida por canal contra fs esperado — mismatch avisa por stderr, no aparece en la tabla.')


def _extraer_flag_baseline(argv):
    """Saca '--baseline archivo.json' de argv (si esta) y devuelve el dict de
    configs cargado, o None. Modifica argv in-place — lo que queda son solo
    rutas de capturas, listo para _recopilar_rutas."""
    if '--baseline' not in argv:
        return None
    i = argv.index('--baseline')
    if i + 1 >= len(argv):
        print('[!] --baseline requiere una ruta a un JSON (ver generar_baseline.py)')
        sys.exit(1)
    ruta = argv.pop(i + 1)
    argv.pop(i)
    return cargar_baseline_externo(ruta)


def main():
    argv = sys.argv[1:]
    baseline_externo = _extraer_flag_baseline(argv)

    if not argv:
        print(__doc__)
        sys.exit(1)

    rutas = _recopilar_rutas(argv)
    if not rutas:
        print('[!] No se encontraron archivos campo_*.bin')
        sys.exit(1)

    resultados = []
    for ruta in rutas:
        print(f'  leyendo {ruta.name} ...', end='\r', flush=True)
        try:
            resultados.append(_calcular(ruta))
        except Exception as e:
            print(f'[ERROR] {ruta.name}: {e}')

    if not resultados:
        return

    mono = [r for r in resultados if r['canales'] == 1]
    dual = [r for r in resultados if r['canales'] == 2]

    if mono:
        _mostrar_mono(mono, baseline_externo)
    if dual:
        _mostrar_dual(dual, baseline_externo)


if __name__ == '__main__':
    main()
