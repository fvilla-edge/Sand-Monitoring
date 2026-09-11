#!/usr/bin/env python3
"""
area_kurtosis.py — filtrado pasabanda (25-400kHz) + área bajo la curva del
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
import numpy as np
from scipy.signal import butter, sosfiltfilt

from revisar import FA_WINDOW_S

# Banda de interes para arena: <25kHz es ruido de fluido, >400kHz no aporta
# (fuera del rango de interes del sensor). Pasabanda Butterworth zero-phase.
FILTRO_BANDA_HZ = (25_000, 400_000)
FILTRO_ORDEN = 4

# Mismo tamaño de ventana que fraccion_activa/kurtosis en revisar.py y
# timeline_lote.py, para que el area/kurtosis de aca queden alineados en el
# tiempo con esas metricas del mismo archivo.
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
