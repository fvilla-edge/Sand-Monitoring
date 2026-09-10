"""
Tests de analisis/revisar.py — enfocados en el parser del formato .bin
(el que causo semanas de diagnostico erroneo por asumir un formato raw que
nunca existio) y en la logica de deteccion/metricas, toda pura y sin
hardware de por medio.

No cubre capturar_stream.py/campo_common.py/probar_dual_stream.py/
relanzar_captura.sh — dependen de la libreria `streaming` (SWIG, solo vive
en la placa) y del streaming-server real.
"""
import struct
import sys

import numpy as np
import pytest

import revisar as rv


# ---------------------------------------------------------------------------
# Helper: construye un .bin sintetico byte a byte, respetando el struct real
# (CBinInfo::BinHeader, 144 bytes) y el layout legacy de 112. sizeCh vive en
# el mismo offset (4) en ambos formatos — es lo que permite que
# _detectar_header_size distinga uno de otro probando el marcador de cada
# candidato contra el mismo header crudo.
# ---------------------------------------------------------------------------

def _header_bytes(header_size, size_ch, lost_ch=None, osc_ch=None, time_capture=None,
                   sigment_length=None):
    buf = bytearray(header_size)
    for i, sc in enumerate(size_ch):
        struct.pack_into('<I', buf, rv._OFF_SIZE_CH + i * 4, sc)
    if header_size == 144:
        lost_ch = lost_ch or (0, 0, 0, 0)
        osc_ch = osc_ch or (0, 0, 0, 0)
        time_capture = time_capture or (0, 0, 0, 0)
        for i, lc in enumerate(lost_ch):
            struct.pack_into('<Q', buf, rv._OFF_LOST_COUNT + i * 8, lc)
        for i, oc in enumerate(osc_ch):
            struct.pack_into('<Q', buf, rv._OFF_OSC_RATE + i * 8, oc)
        for i, tc in enumerate(time_capture):
            struct.pack_into('<q', buf, rv._OFF_TIME_CAPTURE + i * 8, tc)
        if sigment_length is None:
            sigment_length = sum(size_ch)
        struct.pack_into('<I', buf, rv._OFF_SIGMENT_LENGTH, sigment_length)
    return bytes(buf)


def _escribir_bin(ruta, header_size, segmentos):
    """segmentos: lista de dicts con:
      ch0, ch1 (opcional, default vacio): arrays int16
      lost, osc, time_capture (tuplas de 4, solo aplican si header_size==144)
      sigment_length (int, default = suma de sizeCh — pasar un valor distinto
        para simular corrupcion de ese campo)
      marcador: bytes de 12 (default 0xFF*12)
      omitir_marcador: bool — corta el archivo antes de escribir el marcador
        (simula un proceso muerto a mitad de escritura del ultimo segmento)
    """
    with open(ruta, 'wb') as f:
        for seg in segmentos:
            ch0 = np.asarray(seg['ch0'], dtype='<i2').tobytes()
            ch1 = np.asarray(seg.get('ch1', np.array([], dtype='<i2')), dtype='<i2').tobytes()
            header = _header_bytes(header_size, (len(ch0), len(ch1), 0, 0),
                                    seg.get('lost'), seg.get('osc'),
                                    seg.get('time_capture'), seg.get('sigment_length'))
            f.write(header)
            f.write(ch0)
            f.write(ch1)
            if seg.get('omitir_marcador'):
                continue
            f.write(seg.get('marcador', b'\xff' * 12))
    return ruta


# --- _detectar_header_size ---------------------------------------------------

def test_detectar_header_size_144(tmp_path):
    ruta = _escribir_bin(tmp_path / 'a.bin', 144, [{'ch0': [1, 2, 3]}])
    with open(ruta, 'rb') as f:
        assert rv._detectar_header_size(f, ruta.stat().st_size) == 144


def test_detectar_header_size_112_legacy(tmp_path):
    ruta = _escribir_bin(tmp_path / 'a.bin', 112, [{'ch0': [1, 2, 3]}])
    with open(ruta, 'rb') as f:
        assert rv._detectar_header_size(f, ruta.stat().st_size) == 112


def test_detectar_header_size_sin_match_lanza_error(tmp_path):
    ruta = tmp_path / 'basura.bin'
    ruta.write_bytes(b'\x00' * 200)
    with open(ruta, 'rb') as f:
        with pytest.raises(ValueError):
            rv._detectar_header_size(f, ruta.stat().st_size)


# --- _leer_canales_bin --------------------------------------------------------

def test_leer_canales_bin_mono(tmp_path):
    ch0 = np.array([1, 2, 3, 4, 5], dtype='<i2')
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [{'ch0': ch0}])
    ch0_leido, ch1_leido, meta = rv._leer_canales_bin(ruta)
    np.testing.assert_array_equal(ch0_leido, ch0)
    assert len(ch1_leido) == 0


def test_leer_canales_bin_dual_no_intercalado(tmp_path):
    """El caso que estaba roto originalmente: cada canal es un bloque
    contiguo, no una intercalacion por muestra."""
    ch0 = np.array([1, 2, 3, 4, 5], dtype='<i2')
    ch1 = np.array([10, 20, 30, 40, 50], dtype='<i2')
    ruta = _escribir_bin(tmp_path / 'dual.bin', 144, [{'ch0': ch0, 'ch1': ch1}])
    ch0_leido, ch1_leido, meta = rv._leer_canales_bin(ruta)
    np.testing.assert_array_equal(ch0_leido, ch0)
    np.testing.assert_array_equal(ch1_leido, ch1)


def test_leer_canales_bin_multiples_segmentos_se_concatenan(tmp_path):
    seg1 = {'ch0': [1, 2, 3], 'ch1': [10, 20, 30]}
    seg2 = {'ch0': [4, 5], 'ch1': [40, 50]}
    ruta = _escribir_bin(tmp_path / 'dual.bin', 144, [seg1, seg2])
    ch0_leido, ch1_leido, meta = rv._leer_canales_bin(ruta)
    np.testing.assert_array_equal(ch0_leido, [1, 2, 3, 4, 5])
    np.testing.assert_array_equal(ch1_leido, [10, 20, 30, 40, 50])


def test_leer_canales_bin_header_144_lost_y_osc(tmp_path):
    seg1 = {'ch0': [1, 2, 3], 'lost': (1, 0, 0, 0), 'osc': (1000, 2000, 0, 0)}
    # el oscRate solo se toma del primer segmento — estos valores deben ignorarse
    seg2 = {'ch0': [4, 5], 'lost': (2, 0, 0, 0), 'osc': (9999, 9999, 0, 0)}
    ruta = _escribir_bin(tmp_path / 'dual.bin', 144, [seg1, seg2])
    _, _, meta = rv._leer_canales_bin(ruta)
    assert meta['lost0'] == 3
    assert meta['lost1'] == 0
    assert meta['osc0'] == 1000
    assert meta['osc1'] == 2000


def test_leer_canales_bin_header_112_no_tiene_lost_ni_osc(tmp_path):
    ruta = _escribir_bin(tmp_path / 'mono.bin', 112, [{'ch0': [1, 2, 3]}])
    _, _, meta = rv._leer_canales_bin(ruta)
    assert meta['lost0'] is None
    assert meta['lost1'] is None
    assert meta['osc0'] is None
    assert meta['osc1'] is None
    assert meta['dur_real_s'] is None


def test_leer_canales_bin_dur_real_s_sin_gap(tmp_path):
    """1000 muestras a 1000Hz (osc0) = 1s, timeCapture del 2do segmento
    arranca exactamente 1s despues (sin perdida) -> dur_real_s coincide con
    la duracion nominal por conteo de muestras (1000+500 muestras / 1000Hz)."""
    seg1 = {'ch0': np.zeros(1000, dtype='<i2'), 'osc': (1000, 0, 0, 0), 'time_capture': (0, 0, 0, 0)}
    seg2 = {'ch0': np.zeros(500, dtype='<i2'), 'time_capture': (1_000_000_000, 0, 0, 0)}
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [seg1, seg2])
    _, _, meta = rv._leer_canales_bin(ruta)
    assert meta['dur_real_s'] == pytest.approx(1.5)


def test_leer_canales_bin_dur_real_s_incluye_gap_de_perdida(tmp_path):
    """Si el timeCapture del 2do segmento salta mas de lo que darian las
    muestras del 1ro (aca 2s en vez del 1s esperado por 1000 muestras a
    1000Hz), dur_real_s refleja el gap real de tiempo -- a diferencia de
    len(muestras)/fs, que no puede verlo porque esas muestras nunca llegaron."""
    seg1 = {'ch0': np.zeros(1000, dtype='<i2'), 'osc': (1000, 0, 0, 0), 'time_capture': (0, 0, 0, 0)}
    seg2 = {'ch0': np.zeros(500, dtype='<i2'), 'time_capture': (2_000_000_000, 0, 0, 0)}
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [seg1, seg2])
    ch0_leido, _, meta = rv._leer_canales_bin(ruta)
    dur_nominal_s = len(ch0_leido) / 1000
    assert dur_nominal_s == pytest.approx(1.5)
    assert meta['dur_real_s'] == pytest.approx(2.5)
    assert meta['dur_real_s'] > dur_nominal_s


def test_leer_canales_bin_sigment_length_no_coincide_avisa(tmp_path, capsys):
    seg = {'ch0': [1, 2, 3], 'sigment_length': 999}
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [seg])
    rv._leer_canales_bin(ruta)
    assert 'sigmentLength' in capsys.readouterr().err


def test_leer_canales_bin_ultimo_segmento_truncado_se_descarta(tmp_path, capsys):
    seg1 = {'ch0': [1, 2, 3]}
    seg2_truncado = {'ch0': [4, 5], 'omitir_marcador': True}
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [seg1, seg2_truncado])
    ch0_leido, _, _ = rv._leer_canales_bin(ruta)
    np.testing.assert_array_equal(ch0_leido, [1, 2, 3])
    assert 'truncado' in capsys.readouterr().err


def test_leer_canales_bin_marcador_invalido_corta_la_lectura(tmp_path, capsys):
    """Comportamiento actual (no necesariamente "ideal", pero es el contrato
    vigente): los datos del segmento con marcador invalido YA se agregaron
    al buffer antes de detectarse el marcador roto, asi que quedan incluidos;
    en cambio lost/osc de ese segmento NO se cuentan (se acumulan despues del
    chequeo de marcador)."""
    seg1 = {'ch0': [1, 2, 3], 'lost': (1, 0, 0, 0)}
    seg2_roto = {'ch0': [4, 5], 'lost': (99, 0, 0, 0), 'marcador': b'\x00' * 12}
    ruta = _escribir_bin(tmp_path / 'mono.bin', 144, [seg1, seg2_roto])
    ch0_leido, _, meta = rv._leer_canales_bin(ruta)
    np.testing.assert_array_equal(ch0_leido, [1, 2, 3, 4, 5])
    assert meta['lost0'] == 1
    assert 'marcador invalido' in capsys.readouterr().err


# --- _chequear_osc_rate -------------------------------------------------------

def test_chequear_osc_rate_dentro_de_tolerancia(capsys):
    from pathlib import Path
    ok = rv._chequear_osc_rate(Path('x.bin'), 1_000_000, 1_000_000)
    assert ok is True
    assert capsys.readouterr().err == ''


def test_chequear_osc_rate_fuera_de_tolerancia_avisa(capsys):
    from pathlib import Path
    ok = rv._chequear_osc_rate(Path('x.bin'), 1_100_000, 1_000_000)
    assert ok is False
    assert 'no coincide' in capsys.readouterr().err


def test_chequear_osc_rate_none_no_chequea(capsys):
    from pathlib import Path
    assert rv._chequear_osc_rate(Path('x.bin'), None, 1_000_000) is None
    assert capsys.readouterr().err == ''


# --- _metricas_por_ventana / _fraccion_activa / _baseline_autocalibrado -------

def test_metricas_por_ventana_senal_corta_devuelve_vacio():
    sig = np.zeros(10)
    kurt_w, rms_w = rv._metricas_por_ventana(sig, fs=1000)
    assert len(kurt_w) == 0 and len(rms_w) == 0


def test_fraccion_activa_sin_ventanas_devuelve_cero():
    assert rv._fraccion_activa(np.array([])) == 0.0


def test_fraccion_activa_ruido_bajo_no_cruza_umbral():
    rng = np.random.default_rng(42)
    sig = rng.normal(0, 1, 500)   # 10 ventanas de 50ms a fs=1000
    kurt_w, _ = rv._metricas_por_ventana(sig, fs=1000)
    assert rv._fraccion_activa(kurt_w) == 0.0


def test_fraccion_activa_impulsos_cruzan_umbral():
    n_win = 50
    ventanas = []
    for _ in range(10):
        v = np.zeros(n_win)
        v[0] = 1000.0   # espiga aislada -> kurtosis pearson muy por encima de FA_THRESH
        ventanas.append(v)
    sig = np.concatenate(ventanas)
    kurt_w, _ = rv._metricas_por_ventana(sig, fs=1000)
    assert rv._fraccion_activa(kurt_w) == 100.0


def test_baseline_autocalibrado_usa_mediana_de_ventanas_de_fondo():
    kurt_w = np.array([1.0, 2.0, rv.FA_THRESH + 5, 3.0])
    rms_w = np.array([1.0, 3.0, 999.0, 5.0])   # la ventana de arena (indice 2) no debe entrar
    assert rv._baseline_autocalibrado(kurt_w, rms_w) == pytest.approx(3.0)


def test_baseline_autocalibrado_sin_ventanas_de_fondo_da_none():
    kurt_w = np.array([rv.FA_THRESH + 1, rv.FA_THRESH + 5])
    rms_w = np.array([1.0, 2.0])
    assert rv._baseline_autocalibrado(kurt_w, rms_w) is None


# --- _agregar_rms_diferencial_mono -------------------------------------------

def test_rms_diferencial_mono_usa_baseline_autocalibrado():
    resultados = [
        {'rms': 1.0, 'baseline_auto': 1.0},
        {'rms': 2.0, 'baseline_auto': 1.0},
    ]
    rv._agregar_rms_diferencial_mono(resultados)
    assert resultados[0]['rms_dif'] == pytest.approx(0.0)
    assert resultados[0]['baseline_modo'] == 'auto'
    assert resultados[1]['rms_dif'] == pytest.approx(3 ** 0.5)
    assert resultados[1]['baseline_modo'] == 'auto'


def test_rms_diferencial_mono_sin_baseline_auto_cae_a_externo():
    resultados = [{'rms': 2.0, 'baseline_auto': None, 'decimacion': 32}]
    baseline_externo = {'mono_dec32': {'rms': 1.0}}
    rv._agregar_rms_diferencial_mono(resultados, baseline_externo)
    assert resultados[0]['rms_dif'] == pytest.approx(3 ** 0.5)
    assert resultados[0]['baseline_modo'] == 'confirmado'


def test_rms_diferencial_mono_sin_ningun_baseline_da_none():
    resultados = [{'rms': 2.0, 'baseline_auto': None, 'decimacion': 32}]
    rv._agregar_rms_diferencial_mono(resultados)
    assert resultados[0]['rms_dif'] is None
    assert resultados[0]['baseline_modo'] is None


# --- _agregar_rms_diferencial_dual --------------------------------------------

def test_rms_diferencial_dual_usa_baseline_autocalibrado_por_canal():
    resultados = [
        {'rms1': 1.0, 'rms2': 2.0, 'baseline_auto1': 1.0, 'baseline_auto2': 2.0, 'decimacion': 64},
        {'rms1': 3.0, 'rms2': 4.0, 'baseline_auto1': 1.0, 'baseline_auto2': 2.0, 'decimacion': 64},
    ]
    rv._agregar_rms_diferencial_dual(resultados)
    assert resultados[1]['rd1'] == pytest.approx(8 ** 0.5)
    assert resultados[1]['rd2'] == pytest.approx(12 ** 0.5 / 2)
    assert all(r['rd_modo'] == 'auto' for r in resultados)


def test_rms_diferencial_dual_sin_baseline_auto_cae_a_externo():
    resultados = [{'rms1': 3.0, 'rms2': 4.0, 'baseline_auto1': None, 'baseline_auto2': None, 'decimacion': 64}]
    baseline_externo = {'dual_dec64': {'rms1': 1.0, 'rms2': 2.0}}
    rv._agregar_rms_diferencial_dual(resultados, baseline_externo)
    assert resultados[0]['rd1'] == pytest.approx(8 ** 0.5)
    assert resultados[0]['rd2'] == pytest.approx(12 ** 0.5 / 2)
    assert resultados[0]['rd_modo'] == 'confirmado'


def test_rms_diferencial_dual_un_canal_auto_otro_confirmado_da_mixto():
    resultados = [{'rms1': 1.0, 'rms2': 4.0, 'baseline_auto1': 1.0, 'baseline_auto2': None, 'decimacion': 64}]
    baseline_externo = {'dual_dec64': {'rms1': 1.0, 'rms2': 2.0}}
    rv._agregar_rms_diferencial_dual(resultados, baseline_externo)
    assert resultados[0]['rd_modo'] == 'mixto'


def test_rms_diferencial_dual_sin_ningun_baseline_da_none():
    resultados = [{'rms1': 3.0, 'rms2': 4.0, 'baseline_auto1': None, 'baseline_auto2': None, 'decimacion': 64}]
    rv._agregar_rms_diferencial_dual(resultados)
    assert resultados[0]['rd1'] is None
    assert resultados[0]['rd2'] is None
    assert resultados[0]['rd_modo'] is None


# --- _detectar_mono / _detectar_dual ------------------------------------------

@pytest.mark.parametrize('kurt,fa_pct,esperado', [
    (rv.FA_THRESH, 0.0, 'reposo'),          # limite exacto de kurtosis: no dispara
    (rv.FA_THRESH + 0.1, 0.0, '*** ARENA ***'),
    (0.0, 5.0, 'reposo'),                   # limite exacto de fa%: no dispara
    (0.0, 5.1, '*** ARENA ***'),
])
def test_detectar_mono_umbrales(kurt, fa_pct, esperado):
    r = {'kurt': kurt, 'fa_pct': fa_pct}
    assert rv._detectar_mono(r) == esperado


@pytest.mark.parametrize('k1,k2,esperado', [
    (rv.FA_THRESH + 5, rv.FA_THRESH + 5, 'RUIDO COMUN'),
    (rv.FA_THRESH + 5, (rv.FA_THRESH + 5) / 4, '*** ARENA ***'),   # k1 > umbral y k1 > 3*k2
    (rv.FA_THRESH + 5, (rv.FA_THRESH + 5) / 2, 'reposo'),          # k1 > umbral pero k1 no > 3*k2
    (rv.FA_THRESH - 1, 1.0, 'reposo'),                             # k1 ni siquiera cruza el umbral
])
def test_detectar_dual_umbrales(k1, k2, esperado):
    r = {'k1': k1, 'k2': k2}
    assert rv._detectar_dual(r) == esperado


# --- helpers de nombre de archivo --------------------------------------------

def test_chunk_num_from_nombre():
    assert rv._chunk_num_from_nombre('campo_reposo_20260708_140510_0003') == 3


def test_chunk_num_from_nombre_sin_sufijo_numerico_da_cero():
    assert rv._chunk_num_from_nombre('archivo_raro_sin_numero') == 0


# --- _cargar_info --------------------------------------------------------------

def test_cargar_info_encuentra_json_por_condicion_y_timestamp(tmp_path):
    (tmp_path / 'session_reposo_20260708_140510_info.json').write_text('{"a": 1}')
    ruta = tmp_path / 'campo_reposo_20260708_140510_0003.bin'
    assert rv._cargar_info(ruta) == {'a': 1}


def test_cargar_info_cae_a_session_info_json_generico(tmp_path):
    (tmp_path / 'session_info.json').write_text('{"b": 2}')
    ruta = tmp_path / 'campo_reposo_20260708_999999_0001.bin'
    assert rv._cargar_info(ruta) == {'b': 2}


def test_cargar_info_sin_ningun_json_lanza_error(tmp_path):
    ruta = tmp_path / 'campo_reposo_20260708_140510_0003.bin'
    with pytest.raises(FileNotFoundError):
        rv._cargar_info(ruta)
