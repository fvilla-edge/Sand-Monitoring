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
