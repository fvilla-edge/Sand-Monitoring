"""Visor portable de los CSV del modo evento (analisis/visores/visor_csv.py):
umbral igual al del analisis y lectura de .csv/.csv.gz con la ultima linea
cortada (CSV copiado mientras la placa lo escribia)."""
import ast
import gzip
import sys
from pathlib import Path

import revisar as rv

_ANALISIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ANALISIS / "placa"))
import ventanas_a_paquete as vap  # noqa: E402


def _umbral_visor():
    arbol = ast.parse((_ANALISIS / "visores" / "visor_csv.py").read_text())
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and getattr(nodo.targets[0], "id", None) == "UMBRAL_KURT":
            return ast.literal_eval(nodo.value)
    raise AssertionError("visor_csv.py sin UMBRAL_KURT")


def test_umbral_del_visor_igual_a_fa_thresh():
    # el visor no importa revisar.py (scipy inflaria el ejecutable): tiene su copia
    assert _umbral_visor() == rv.FA_THRESH


CSV = (
    "window_count,t_utc_ms,area,kurtosis,estado,perdidas_fpga\n"
    "100,1790701200050,0.51,2.98,ok,0\n"
    "101,1790701200100,0.52,7.50,ok,0\n"
    "102,1790701200150,,,saltada,0\n"
    "103,1790701200200,0.50,3.01,ok,0\n"
    "104,17907012002"  # ultima linea cortada a mitad de escritura
)


def test_csv_y_csv_gz_con_ultima_linea_cortada(tmp_path):
    plano = tmp_path / "ventanas_20260929_16.csv"
    plano.write_text(CSV)
    comprimido = tmp_path / "ventanas_20260929_16.csv.gz"
    with gzip.open(comprimido, "wt") as f:
        f.write(CSV)
    for ruta in (plano, comprimido):
        paquete = vap.armar_paquete(vap.leer_filas([ruta]), ruta.name)
        canal = paquete["canales"][0]
        assert canal["kurtosis"] == [2.98, 7.50, 3.01]
        assert paquete["ventanas_saltadas"] == 1


def test_filas_pegadas_por_corte_de_energia(tmp_path):
    # ventanas_20261020_14.csv de campo: linea cortada + la siguiente pegada
    # (14:07:44 y 14:32:57), y filas de 7 columnas bajo el encabezado de 6
    # (hora en que se actualizo la placa)
    ruta = tmp_path / "ventanas_20261020_14.csv"
    ruta.write_text(
        "window_count,t_utc_ms,area,kurtosis,estado,perdidas_fpga\n"
        "5689,1792505264000,0.6520,2.87,ok,0\n"
        "5690,1792505264050,1792505482708,0.6523,2.87614,ok,5832\n"
        "4051,1792505482752,0.65286,2.84142,ok,17536\n"
        "19611,17925064066,1792506777551,0.50475,2.96188,ok,0\n"
        "4067,1792506777600,0.503006,2.97358,ok,0\n"
        "4109,1792507799705,0.501161,2.99631,ok,0,32\n"
        "4110,1792507799755,0.5,2.9,ok,1100,1792507799805,0.5,2.9,ok,0,32\n")
    filas = vap.leer_filas([ruta])
    assert [r["wc"] for r in filas] == [5689, 4051, 4067, 4109]
    assert all(r["t_ms"] > 1.7e12 for r in filas)

    sys.path.insert(0, str(_ANALISIS / "utilidades"))
    import organizar_csv_campo as occ  # noqa: E402
    assert [t for t, _ in occ.leer_filas(ruta)[0]] == [r["t_ms"] for r in filas]


def test_area_acumulada_suma_solo_kurtosis_mayor_al_umbral():
    sys.path.insert(0, str(_ANALISIS / "visores"))
    import visor_csv  # noqa: E402 (tkinter/matplotlib se importan, no abren ventana)
    area = [1.0, 2.0, 4.0, 8.0]
    kurt = [3.0, 3.8, 3.81, 10.0]  # 3.8 exacto NO suma (estrictamente mayor)
    assert list(visor_csv.area_acumulada(area, kurt, 3.8)) == [0.0, 0.0, 4.0, 12.0]


def test_grupos_se_parten_solo_con_huecos_mayores_a_una_hora():
    sys.path.insert(0, str(_ANALISIS / "visores"))
    import numpy as np
    import visor_csv  # noqa: E402
    # en segundos -> dias: 3 ventanas, corte de 44 min (no parte), 2 ventanas,
    # corte de 3 h (parte), 2 ventanas
    seg = [0, 0.05, 0.10, 0.10 + 44 * 60, 0.15 + 44 * 60, 0.15 + 44 * 60 + 3 * 3600, 0.20 + 44 * 60 + 3 * 3600]
    t = np.array(seg) / 86400
    acum = np.array([1, 2, 3, 3, 5, 6, 10], dtype=float)
    grupos = visor_csv.partir_en_grupos(t, acum)
    assert [(i0, i1) for i0, i1, _ in grupos] == [(0, 5), (5, 7)]
    assert [sub for _, _, sub in grupos] == [5.0, 5.0]  # la suma de subtotales es el total
