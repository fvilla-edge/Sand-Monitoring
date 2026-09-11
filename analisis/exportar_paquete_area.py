#!/usr/bin/env python3
"""
exportar_paquete_area.py — Fase 1 del "paquete liviano para la placa"
(ver docs del feature, rama area-en-placa): por archivo de captura calcula
(t_centro_s, area, kurtosis) por ventana de AREA_VENTANA_S — mismas
formulas que las pestañas "Área" y "Señal+Kurtosis" de ver_forma_onda.py
(ver analisis/area_kurtosis.py, de donde se importan) — y lo guarda en
JSON.

A proposito NO hace el paso de "Acumulado" (umbral de kurtosis + cumsum):
esa parte se hace despues, en la PC, a partir de este JSON — no hace falta
volver a tocar la señal cruda para eso. Tampoco importa matplotlib/tkinter
(a diferencia de ver_forma_onda.py) — pensado para poder correr tal cual en
la placa (fase 2 del plan) sin arrastrar esas dependencias.

Uso:
  .venv/bin/python3 analisis/exportar_paquete_area.py campo_reposo_..._0000.bin
  .venv/bin/python3 analisis/exportar_paquete_area.py archivo.bin -o salida.json

Valida contra ver_forma_onda.py: abrir el mismo archivo ahi y comparar
"area" contra la pestaña "Área" (ventana 50ms) y "kurtosis" contra la curva
de la pestaña "... Señal+Kurtosis" — tienen que coincidir (misma formula,
mismos datos).
"""
import sys
import json
import argparse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _leer_canales_bin, _cargar_info, V_REF  # noqa: E402
from area_kurtosis import (  # noqa: E402
    AREA_VENTANA_S,
    _filtrar_pasabanda, _rms_muestra_a_muestra, _area_por_ventana, _kurtosis_por_ventana,
)


def _construir_paquete_canal(nombre, volts, fs):
    filtrado = _filtrar_pasabanda(volts, fs)
    rms = _rms_muestra_a_muestra(filtrado)
    t, area = _area_por_ventana(rms, fs)
    _, kurt = _kurtosis_por_ventana(filtrado, fs)
    return {
        "canal": nombre,
        "t_centro_s": [round(float(v), 6) for v in t],
        "area": [float(v) for v in area],
        "kurtosis": [float(v) for v in kurt],
    }


def construir_paquete(ruta: Path):
    """{"archivo", "fs_hz", "ventana_s", "canales": [{"canal", "t_centro_s",
    "area", "kurtosis"}, ...]} — un dict por canal real (IN1, IN2 y
    Limpia=IN1-IN2 si es dual, igual que ver_forma_onda.py)."""
    info = _cargar_info(ruta)
    ch0, ch1, meta = _leer_canales_bin(ruta)
    dual = int(info.get("canales", 1)) == 2
    fs = float(info["fs_hz_por_canal"]) if dual else float(info["fs_hz"])

    ch0_v = ch0.astype(np.float32) / 32767.0 * V_REF
    canales = [_construir_paquete_canal("IN1", ch0_v, fs)]
    if dual:
        ch1_v = ch1.astype(np.float32) / 32767.0 * V_REF
        canales.append(_construir_paquete_canal("IN2", ch1_v, fs))
        # IN1 e IN2 SI estan sincronizados (mismo reloj, misma captura) —
        # restar en Volts es valido, igual que en ver_forma_onda.py.
        limpia_v = ch0_v - ch1_v
        canales.append(_construir_paquete_canal("Limpia (IN1-IN2)", limpia_v, fs))

    return {
        "archivo": ruta.name,
        "fs_hz": fs,
        "ventana_s": AREA_VENTANA_S,
        "canales": canales,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Exporta el paquete liviano (area+kurtosis por ventana) de una captura .bin")
    ap.add_argument("archivo", type=Path, help="captura .bin (requiere session_*_info.json al lado)")
    ap.add_argument("-o", "--salida", type=Path, default=None,
                     help="ruta del JSON de salida (default: <archivo sin .bin>.paquete.json)")
    args = ap.parse_args()

    paquete = construir_paquete(args.archivo)
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
