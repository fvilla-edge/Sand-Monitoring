#!/usr/bin/env python3
"""
exportar_paquete_area_c.py — misma salida que exportar_paquete_area.py
(paquete area+kurtosis por ventana, sin acumulado), pero el trabajo pesado
(leer el .bin, filtrar, ventanear) corre en un binario C
(analisis/c/paquete_area) en vez de Python/NumPy/SciPy.

Motivo: medido en la placa real (rp-f0fbda), la version Python tarda ~10x
el tiempo real de la señal AUN SOLA, sin competir con ninguna captura
(245.9s para procesar 25.7s de audio, bloque_s=0.25/0.5 — casi lo mismo,
no es overhead por-bloque) — muy por debajo de lo que hace falta.

Este script solo hace la parte barata en Python: leer session_info.json y
calcular los coeficientes SOS del pasabanda con scipy.signal.butter (una
sola vez por archivo, no es el cuello de botella — se evita a proposito
reimplementar el diseño Butterworth en C, riesgo de un bug numerico sutil
para algo que no hace falta que sea rapido). El binario C hace todo lo
demas: leer el .bin por bloques (memoria acotada, mismo diseño ya validado
en area_kurtosis.py — margen real entre bloques + residual de ventaneo
arrastrado para no perder la grilla continua) y filtrar/ventanear.

Uso: igual que exportar_paquete_area.py
  .venv/bin/python3 analisis/exportar_paquete_area_c.py archivo.bin [-o salida.json] [--bloque-s N]

Requiere haber compilado antes el binario:
  cd analisis/c && make
"""
import sys
import json
import argparse
import subprocess
import tempfile
from pathlib import Path

from scipy.signal import butter

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _cargar_info, V_REF  # noqa: E402
from area_kurtosis import (  # noqa: E402
    FILTRO_BANDA_HZ, FILTRO_ORDEN, AREA_VENTANA_S, BLOQUE_S_DEFAULT, MARGEN_S_DEFAULT,
)

BINARIO = Path(__file__).parent / "c" / "paquete_area"


def _coeficientes_sos(fs, banda=FILTRO_BANDA_HZ, orden=FILTRO_ORDEN):
    """Mismo calculo que area_kurtosis._filtrar_pasabanda, pero devolviendo
    los coeficientes en vez de aplicarlos — se calculan una sola vez acá
    (en Python, con scipy.signal.butter ya validado) y se le pasan al
    binario C, que solo los APLICA."""
    nyq = fs / 2
    return butter(orden, [banda[0] / nyq, banda[1] / nyq], btype="bandpass", output="sos")


def construir_paquete_c(ruta: Path, bloque_s=BLOQUE_S_DEFAULT, margen_s=MARGEN_S_DEFAULT):
    if not BINARIO.exists():
        raise FileNotFoundError(f"Falta compilar {BINARIO} — correr 'make' en {BINARIO.parent}")

    info = _cargar_info(ruta)
    dual = int(info.get("canales", 1)) == 2
    fs = float(info["fs_hz_por_canal"]) if dual else float(info["fs_hz"])
    sos = _coeficientes_sos(fs)

    with tempfile.TemporaryDirectory() as tmp:
        coefs_path = Path(tmp) / "coefs.txt"
        with open(coefs_path, "w") as f:
            f.write(f"{sos.shape[0]}\n")
            for b0, b1, b2, a0, a1, a2 in sos:
                assert float(a0) == 1.0, "scipy deberia normalizar a0=1.0 en formato 'sos'"
                # float(...) explicito: numpy>=2.0 cambio el repr de sus
                # escalares a "np.float64(...)", que fscanf del lado C no
                # puede parsear — %.17g de un float de Python si sirve.
                f.write(f"{float(b0):.17g} {float(b1):.17g} {float(b2):.17g} "
                        f"{float(a1):.17g} {float(a2):.17g}\n")

        salida_tmp = Path(tmp) / "salida.json"
        subprocess.run([
            str(BINARIO), str(ruta), str(coefs_path),
            repr(fs), repr(V_REF), repr(AREA_VENTANA_S),
            repr(bloque_s), repr(margen_s), "1" if dual else "0",
            str(salida_tmp),
        ], check=True)

        with open(salida_tmp) as f:
            return json.load(f)


def main():
    ap = argparse.ArgumentParser(
        description="Exporta el paquete liviano (area+kurtosis por ventana) usando el binario C")
    ap.add_argument("archivo", type=Path, help="captura .bin (requiere session_*_info.json al lado)")
    ap.add_argument("-o", "--salida", type=Path, default=None,
                     help="ruta del JSON de salida (default: <archivo sin .bin>.paquete.json)")
    ap.add_argument("--bloque-s", type=float, default=BLOQUE_S_DEFAULT,
                     help=f"segundos de señal 'core' por bloque (default: {BLOQUE_S_DEFAULT})")
    args = ap.parse_args()

    paquete = construir_paquete_c(args.archivo, bloque_s=args.bloque_s)
    salida = args.salida or args.archivo.with_suffix(".paquete.json")
    with open(salida, "w") as f:
        json.dump(paquete, f)

    n_ventanas = sum(len(c["area"]) for c in paquete["canales"])
    tam_bin_mb = args.archivo.stat().st_size / 1e6
    tam_json_kb = salida.stat().st_size / 1024
    print(f"[OK] {salida.name}: {len(paquete['canales'])} canal(es), {n_ventanas} ventanas totales")
    print(f"     {tam_bin_mb:.1f} MB (.bin crudo) -> {tam_json_kb:.1f} KB (paquete)")


if __name__ == "__main__":
    main()
