"""
Tests de analisis/acumulado_lote.py — solo la logica pura (windowing, area,
pegado de archivos en un eje de tiempo absoluto, fusion de tramos,
acumulado), sin pasar por el bandpass real ni por .bin sinteticos: mismo
criterio que tests/test_revisar.py, que tampoco ejercita _calcular_mono/
_calcular_dual end-to-end (necesitarian una fs real >800kHz para que el
pasabanda 50-400kHz tenga sentido, y no agregan cobertura sobre la logica
propia de este script).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

import acumulado_lote as al
import revisar as rv


# --- _metricas_por_ventana ----------------------------------------------------

def test_metricas_por_ventana_senal_corta_devuelve_vacio():
    sig = np.zeros(10)
    kurt_w, area_w = al._metricas_por_ventana(sig, fs=1000)
    assert len(kurt_w) == 0 and len(area_w) == 0


def test_metricas_por_ventana_area_de_señal_constante():
    # fs=1000, ventana_s=0.05 (FA_WINDOW_S) -> 50 muestras/ventana.
    sig = np.full(500, 2.0)  # 10 ventanas, todas con el mismo valor
    _, area_w = al._metricas_por_ventana(sig, fs=1000)
    assert len(area_w) == 10
    np.testing.assert_allclose(area_w, 2.0 * al.FA_WINDOW_S)


def test_metricas_por_ventana_area_usa_valor_absoluto():
    sig = np.full(500, -3.0)
    _, area_w = al._metricas_por_ventana(sig, fs=1000)
    np.testing.assert_allclose(area_w, 3.0 * al.FA_WINDOW_S)


def test_metricas_por_ventana_kurt_coincide_con_revisar():
    rng = np.random.default_rng(7)
    sig = rng.normal(0, 1, 500)
    kurt_w, _ = al._metricas_por_ventana(sig, fs=1000)
    kurt_rv, _ = rv._metricas_por_ventana(sig, fs=1000)
    np.testing.assert_allclose(kurt_w, kurt_rv)


# --- _t_inicio_archivo ---------------------------------------------------------

def test_t_inicio_archivo_prefiere_timecapture_de_hw():
    meta = {'t_inicio_ns': 1_700_000_000_000_000_000}
    info = {'fecha_inicio': '2020-01-01T00:00:00'}
    t = al._t_inicio_archivo(Path('x.bin'), info, meta)
    assert t == datetime.fromtimestamp(1_700_000_000_000_000_000 / 1e9, tz=timezone.utc)


def test_t_inicio_archivo_cae_a_fecha_inicio_del_json():
    meta = {'t_inicio_ns': None}
    info = {'fecha_inicio': '2026-09-03T14:00:00'}
    t = al._t_inicio_archivo(Path('x.bin'), info, meta)
    assert t == datetime(2026, 9, 3, 14, 0, 0, tzinfo=timezone.utc)


def test_t_inicio_archivo_sin_ninguno_lanza_error():
    with pytest.raises(ValueError):
        al._t_inicio_archivo(Path('x.bin'), {}, {'t_inicio_ns': None})


# --- _armar_serie ---------------------------------------------------------------

def _item(t_inicio, kurt, area, canales=1, cond='reposo'):
    kurt = np.asarray(kurt, dtype=float)
    area = np.asarray(area, dtype=float)
    return {
        't_inicio': t_inicio, 'canales': canales, 'cond': cond,
        'decimacion': 32, 'kurt': [kurt], 'area': [area],
    }


def test_armar_serie_sin_hueco_real_registra_hueco_de_0s_pero_marca_nan():
    # _armar_serie siempre inserta un punto de union entre archivos (aunque
    # el segundo arranque exactamente donde termino el anterior, hueco_s=0)
    # — mismo comportamiento que timeline_lote.py, del que se copio esta
    # funcion tal cual.
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dur = timedelta(seconds=al.FA_WINDOW_S)
    it1 = _item(t0, [3.0, 3.0], [0.1, 0.1])
    it2 = _item(t0 + 2 * dur, [3.0], [0.1])  # arranca justo donde termino it1
    tiempos, kurt, area, huecos = al._armar_serie([it1, it2], 0)
    assert len(huecos) == 1 and huecos[0][2] == 0.0
    assert len(tiempos) == 4  # 2 ventanas + 1 nan de union + 1 ventana
    assert np.isnan(kurt).sum() == 1


def test_armar_serie_con_hueco_inserta_nan_en_los_dos_arrays():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    it1 = _item(t0, [3.0], [0.1])
    it2 = _item(t0 + timedelta(seconds=10), [3.0], [0.1])  # hueco real de varios segundos
    tiempos, kurt, area, huecos = al._armar_serie([it1, it2], 0)
    assert len(huecos) == 1
    assert len(tiempos) == 3  # 1 ventana + 1 nan de hueco + 1 ventana
    assert np.isnan(kurt[1]) and np.isnan(area[1])


def test_armar_serie_descarta_archivos_sin_ventanas():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    it_vacio = _item(t0, [], [])
    it_con_datos = _item(t0 + timedelta(seconds=1), [3.0], [0.1])
    tiempos, kurt, area, huecos = al._armar_serie([it_vacio, it_con_datos], 0)
    assert len(tiempos) == 1
    assert huecos == []  # el archivo vacio no cuenta como "anterior" para detectar hueco


# --- _tramos_activos -------------------------------------------------------------

def test_tramos_activos_sin_actividad_da_lista_vacia():
    tiempos = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i) for i in range(5)]
    kurt = np.array([3.0] * 5)
    assert al._tramos_activos(tiempos, kurt, umbral=6) == []


def test_tramos_activos_fusiona_corridas_separadas_por_silencio_corto():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dur = timedelta(seconds=al.FA_WINDOW_S)
    tiempos = [t0 + i * dur for i in range(6)]
    # activo, calma (< tolerancia), activo
    kurt = np.array([10.0, 3.0, 3.0, 10.0, 3.0, 3.0])
    tramos = al._tramos_activos(tiempos, kurt, umbral=6, tolerancia_s=al.FA_WINDOW_S * 3)
    assert len(tramos) == 1


def test_tramos_activos_no_fusiona_a_traves_de_un_hueco():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dur = timedelta(seconds=al.FA_WINDOW_S)
    tiempos = [t0, t0 + dur, t0 + 2 * dur]
    kurt = np.array([10.0, np.nan, 10.0])  # hueco real entre dos tramos activos
    tramos = al._tramos_activos(tiempos, kurt, umbral=6, tolerancia_s=100)
    assert len(tramos) == 2


# --- _acumulado --------------------------------------------------------------------

def test_acumulado_solo_suma_ventanas_sobre_el_umbral():
    kurt = np.array([3.0, 10.0, 3.0, 10.0])
    area = np.array([0.1, 0.2, 0.1, 0.3])
    acumulado, mask = al._acumulado(kurt, area, umbral=6)
    np.testing.assert_array_equal(mask, [False, True, False, True])
    np.testing.assert_allclose(acumulado, [0.0, 0.2, 0.2, 0.5])


def test_acumulado_hueco_nan_no_rompe_la_suma():
    kurt = np.array([10.0, np.nan, 10.0])
    area = np.array([0.2, np.nan, 0.3])  # area tambien lleva nan en el hueco (ver _armar_serie)
    acumulado, mask = al._acumulado(kurt, area, umbral=6)
    assert not np.isnan(acumulado).any()
    np.testing.assert_allclose(acumulado, [0.2, 0.2, 0.5])


# --- _etiqueta_lote ------------------------------------------------------------------

def test_etiqueta_lote_extrae_timestamps():
    etiqueta = al._etiqueta_lote(
        'mono', 'campo_reposo_20260903_140000_0001.bin', 'campo_reposo_20260903_143000_0012.bin')
    assert etiqueta == 'mono_20260903_140000_a_143000'
