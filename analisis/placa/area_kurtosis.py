#!/usr/bin/env python3
"""
area_kurtosis.py — filtrado pasabanda (50-400kHz) + área bajo la curva del
RMS y kurtosis, ambas por ventana de AREA_VENTANA_S. Es la parte PURA (sin
matplotlib/tkinter) de ver_forma_onda.py: ese visor importa estas mismas
funciones en vez de definirlas, para que solo exista una formula real.

Se separó de ver_forma_onda.py para que scripts que no grafican (por
ejemplo exportar_paquete_area.py, pensado para correr en la placa) no
arrastren tkinter/matplotlib como dependencia — ver docs/compresion_datos.md
sobre lo poco que sobra de CPU en el ARM de la placa; no tiene sentido
sumarle encima el peso de import de una GUI que ahí nunca se usa.

No reimplementa la lectura del formato .bin — eso sigue en
revisar.py::_leer_canales_bin/_cargar_info, misma fuente de verdad de
siempre.
"""
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).parent.parent))  # analisis/ (revisar.py)
from revisar import FA_WINDOW_S, _iterar_segmentos  # noqa: E402

# Banda de interes para arena: <50kHz es ruido de fluido, >400kHz no aporta
# (fuera del rango de interes del sensor). Pasabanda Butterworth zero-phase.
FILTRO_BANDA_HZ = (50_000, 400_000)
FILTRO_ORDEN = 4

# Mismo tamaño de ventana que fraccion_activa/kurtosis en revisar.py, para
# que el area/kurtosis de aca queden alineados en el tiempo con esas
# metricas del mismo archivo.
AREA_VENTANA_S = FA_WINDOW_S


def _filtrar_pasabanda(volts, fs, banda=FILTRO_BANDA_HZ, orden=FILTRO_ORDEN):
    nyq = fs / 2
    sos = butter(orden, [banda[0] / nyq, banda[1] / nyq], btype="bandpass", output="sos")
    return sosfiltfilt(sos, volts).astype(np.float32)


def _rms_muestra_a_muestra(volts):
    """RMS con ventana de 1 muestra (sqrt(x^2) = |x|): la señal completa,
    misma resolucion temporal que la original, pero siempre >= 0."""
    return np.abs(volts)


def _area_por_ventana(rms, fs, ventana_s=AREA_VENTANA_S):
    """(t_centro_s, area) del area bajo la curva de rms (ya siempre >= 0)
    en ventanas de ventana_s no superpuestas — suma de Riemann (rectangular,
    area_i = sum(muestras de la ventana) * dt) por ventana."""
    n_ventana = max(1, int(fs * ventana_s))
    n_total = len(rms) // n_ventana
    if n_total == 0:
        return np.array([]), np.array([], dtype=np.float32)
    mat = rms[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)
    area = (mat.sum(axis=1) / fs).astype(np.float32)
    t = (np.arange(n_total) + 0.5) * ventana_s
    return t, area


def _kurtosis_por_ventana(volts, fs, ventana_s=AREA_VENTANA_S):
    """(t_centro_s, kurtosis) en ventanas de ventana_s no superpuestas —
    mismo criterio y formula que _metricas_por_ventana de timeline_lote.py
    (y el calculo de kurtosis de revisar.py): dentro de cada ventana se le
    resta la media, y kurt = m4/m2^2 con m2=E[(x-x̄)^2], m4=E[(x-x̄)^4]. Para
    ruido gaussiano da ~3; picos aislados grandes (impactos) la disparan
    mucho mas arriba porque m4 pesa los valores extremos a la 4ta potencia."""
    n_ventana = max(1, int(fs * ventana_s))
    n_total = len(volts) // n_ventana
    if n_total == 0:
        return np.array([]), np.array([], dtype=np.float32)
    mat = volts[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2 = np.mean(mat ** 2, axis=1)
    m4 = np.mean(mat ** 4, axis=1)
    kurt = (m4 / np.where(m2 > 0, m2 ** 2, 1e-30)).astype(np.float32)
    t = (np.arange(n_total) + 0.5) * ventana_s
    return t, kurt


# --- Procesamiento por bloques (memoria acotada, para la placa) ------------
#
# _filtrar_pasabanda/_area_por_ventana/_kurtosis_por_ventana de arriba
# reciben el canal ENTERO ya en memoria (via revisar._leer_canales_bin, que
# junta todo el .bin) — en la PC sobra RAM, pero en la placa (Zynq, 459MiB
# SIN swap) un chunk de captura real (hasta 2 minutos recomendados en
# capturar_stream.py) hace que el proceso muera por OOM antes de terminar:
# confirmado en HW real (ver docs/plan del feature area-en-placa), un
# archivo de apenas 200MB (30s) ya llego a ~376MB de RSS y el kernel lo
# mato. La causa: leer 100M+ muestras int16 (200MB), convertir a float32
# (otro 2x) y filtrar con sosfiltfilt (trabaja en float64 internamente,
# otro 2-4x) — todo de una sola vez escala con el archivo COMPLETO, sin
# limite por mas grande que sea el chunk.
#
# _bloques_canal recorre el .bin de a un segmento (revisar._iterar_segmentos,
# NO _leer_canales_bin) y arma bloques de BLOQUE_S_DEFAULT segundos "core",
# con un margen de MARGEN_S_DEFAULT a cada lado tomado de datos reales
# (no relleno inventado) para que sosfiltfilt asiente bien en cada corte
# artificial entre bloques -- el margen se descarta del resultado filtrado
# antes de ventanear, solo se cuenta/emite el core. En memoria, en todo
# momento, hay como mucho ~1 bloque (unos pocos MB), sin importar cuan
# largo sea el archivo entero.

BLOQUE_S_DEFAULT = 0.25    # segundos de señal "core" por bloque — medido en HW real:
# bloque_s=2.0 llegaba a ~493MB de RSS (sosfiltfilt trabaja en float64 sobre
# el bloque completo, varias copias intermedias) — demasiado para la placa
# (459MiB totales, sin swap). 0.25s midio ~155MB en la PC; se re-valida el
# numero real en la placa antes de confiar en este default (ver plan del
# feature area-en-placa).
# Margen >> tiempo de asentamiento real de un Butterworth orden 4 (del
# orden de decenas de muestras) — se usa una ventana completa (AREA_VENTANA_S)
# por simpleza y para tener bastante margen de sobra, no porque haga falta
# tanto.
MARGEN_S_DEFAULT = AREA_VENTANA_S


def _bloques_canal(ruta, fs, bloque_s=BLOQUE_S_DEFAULT, margen_s=MARGEN_S_DEFAULT):
    """Generador (t_offset_s, bloque0_i16, bloque1_i16_o_None, n_izq,
    n_core) recorriendo `ruta` de a un segmento (revisar._iterar_segmentos),
    sin cargar el archivo entero en memoria.

    bloque0_i16/bloque1_i16 (int16, SIN convertir a Volts) traen
    [margen_izq][core][margen_der] (margen_der puede faltar/ser mas chico
    en el ultimo bloque del archivo). t_offset_s es el tiempo absoluto
    (desde el inicio del archivo) de la PRIMERA muestra core del bloque —
    no de la muestra con margen. El consumidor debe filtrar el bloque
    COMPLETO y quedarse solo con [n_izq : n_izq+n_core] del resultado antes
    de ventanear (descartar el margen, que solo esta ahi para el
    asentamiento del filtro zero-phase en este corte artificial)."""
    n_core = max(1, int(round(fs * bloque_s)))
    n_margen = max(1, int(round(fs * margen_s)))

    cola0 = np.array([], dtype='<i2')
    cola1 = np.array([], dtype='<i2')
    buf0, buf1 = [], []
    n_buf = 0
    dual = None
    muestras_core_emitidas = 0

    def _flush(cerrar):
        nonlocal buf0, buf1, n_buf, cola0, cola1, muestras_core_emitidas
        arr0 = np.frombuffer(b''.join(buf0), dtype='<i2')
        arr1 = np.frombuffer(b''.join(buf1), dtype='<i2') if dual else None

        n_izq = len(cola0)
        n_core_real = min(n_core, len(arr0))
        n_der = min(n_margen, len(arr0) - n_core_real)

        bloque0 = np.concatenate([cola0, arr0[: n_core_real + n_der]])
        bloque1 = np.concatenate([cola1, arr1[: n_core_real + n_der]]) if dual else None

        t_offset_s = muestras_core_emitidas / fs

        # Cola para el proximo bloque: las ultimas n_margen muestras de lo
        # que ACA se cuenta como core (el margen derecho recien usado NO se
        # descarta del buffer — se vuelve a leer como parte del proximo
        # bloque, ver mas abajo: solo se "espia" para el asentamiento del
        # filtro de ESTE bloque, sus ventanas de area/kurtosis todavia no
        # se calcularon).
        core_hasta_ahora0 = np.concatenate([cola0, arr0[:n_core_real]])
        cola0 = core_hasta_ahora0[-n_margen:]
        if dual:
            core_hasta_ahora1 = np.concatenate([cola1, arr1[:n_core_real]])
            cola1 = core_hasta_ahora1[-n_margen:]

        muestras_core_emitidas += n_core_real

        resto0 = arr0[n_core_real:]
        buf0 = [resto0.tobytes()] if len(resto0) else []
        if dual:
            resto1 = arr1[n_core_real:]
            buf1 = [resto1.tobytes()] if len(resto1) else []
        n_buf = len(resto0)

        return t_offset_s, bloque0, bloque1, n_izq, n_core_real

    for ch0_b, ch1_b, _info in _iterar_segmentos(ruta):
        if dual is None:
            dual = len(ch1_b) > 0
        buf0.append(ch0_b)
        if dual:
            buf1.append(ch1_b)
        n_buf += len(ch0_b) // 2
        if n_buf >= n_core + n_margen:
            yield _flush(cerrar=False)

    if n_buf > 0:
        yield _flush(cerrar=True)


def _area_kurtosis_de_bloque(volts_bloque, fs, n_izq, n_core, residual_anterior=None, ventana_s=AREA_VENTANA_S):
    """Filtra el bloque COMPLETO (margen+core+margen) y devuelve
    (t_local_s, area, kurtosis, residual_nuevo) para las ventanas completas
    que se pueden armar — descarta el margen usado nada mas para el
    asentamiento del filtro zero-phase (eso SI se tira, ver _bloques_canal).

    OJO con una trampa distinta a la del margen: bloque_s no tiene por que
    ser multiplo exacto de ventana_s (ej. fs=3906250Hz, ventana=50ms da
    195312 muestras/ventana — NO 195312.5 — y un core de 2s = 7812500
    muestras entran 40 veces justas con 20 de sobra). Si cada bloque
    ventaneara su propio core de forma independiente (arrancando en 0), esas
    20 muestras se perderian AL FINAL DE CADA BLOQUE en vez de una sola vez
    al final del archivo (como hace el modo "todo de una") — y peor, la
    grilla de ventanas de cada bloque quedaria corrida respecto de la
    grilla global, haciendo que un impacto real cerca de un borde de bloque
    caiga en una ventana distinta segun el modo (confirmado con datos
    reales: un evento real en el archivo de prueba corrio ventanas enteras
    de kurtosis entre "todo de una" y "por bloques" antes de este fix).

    Por eso esta funcion recibe/devuelve un `residual` (muestras YA
    FILTRADAS del bloque anterior que no llegaron a completar una ventana)
    para pegarlo ADELANTE del core de este bloque antes de ventanear —
    mantiene una sola grilla de ventanas continua para todo el archivo,
    igual que el modo "todo de una", en vez de reiniciarla en cada bloque.
    t_local_s ya viene ajustado para tener en cuenta ese residual (arranca
    en 0 relativo al PRIMER dato de residual_anterior+core, no al inicio
    del core de este bloque) — el llamador solo debe sumarle
    (t_offset_s_del_bloque - len(residual_anterior)/fs)."""
    filtrado = _filtrar_pasabanda(volts_bloque, fs)
    core = filtrado[n_izq: n_izq + n_core]
    if residual_anterior is not None and len(residual_anterior):
        core = np.concatenate([residual_anterior, core])

    n_ventana = max(1, int(fs * ventana_s))
    n_completas = len(core) // n_ventana
    usado = n_completas * n_ventana
    core_alineado = core[:usado]
    residual_nuevo = core[usado:]

    rms = _rms_muestra_a_muestra(core_alineado)
    t, area = _area_por_ventana(rms, fs, ventana_s)
    _, kurt = _kurtosis_por_ventana(core_alineado, fs, ventana_s)
    return t, area, kurt, residual_nuevo
