#!/usr/bin/env python3
"""
exportar_paquete_area.py — Fase 1 del "paquete liviano para la placa"
(ver docs del feature, rama area-en-placa): por archivo de captura calcula
(t_centro_s, area, kurtosis) por ventana de AREA_VENTANA_S — mismas
formulas de area/kurtosis que las pestañas "Área" y "Señal+Kurtosis" de
ver_forma_onda.py (ver analisis/placa/area_kurtosis.py, de donde se
importan) — y lo guarda en JSON.

A proposito NO hace el paso de "Acumulado" (umbral de kurtosis + cumsum):
esa parte se hace despues, en la PC, a partir de este JSON — no hace falta
volver a tocar la señal cruda para eso. Tampoco importa matplotlib/tkinter
(a diferencia de ver_forma_onda.py) — pensado para poder correr tal cual en
la placa (fase 2 del plan) sin arrastrar esas dependencias.

Uso:
  .venv/bin/python3 analisis/placa/exportar_paquete_area.py campo_reposo_..._0000.bin
  .venv/bin/python3 analisis/placa/exportar_paquete_area.py archivo.bin -o salida.json

Validacion contra ver_forma_onda.py (sec.172): desde que area_kurtosis.py
pasa a filtro CAUSAL (sosfilt, una pasada — ver_forma_onda.py sigue con
sosfiltfilt zero-phase a proposito, para que la forma de onda se vea bien
en el visor) los valores de area/kurtosis de este paquete NO coinciden
exacto con los del visor — hay un retardo de grupo fijo y menos atenuacion
por pasada simple. Lo que se valida ahora es CLASIFICACION equivalente
(mismos archivos por encima/debajo del umbral de kurtosis), no igualdad
numerica exacta.
"""
import sys
import json
import argparse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))          # placa/ (area_kurtosis.py)
sys.path.insert(0, str(Path(__file__).parent.parent))    # analisis/ (revisar.py)
from revisar import _leer_canales_bin, _cargar_info, V_REF  # noqa: E402
from area_kurtosis import (  # noqa: E402
    AREA_VENTANA_S, BLOQUE_S_DEFAULT, MARGEN_S_DEFAULT,
    _filtrar_pasabanda, _rms_muestra_a_muestra, _area_por_ventana, _kurtosis_por_ventana,
    _bloques_canal, _area_kurtosis_de_bloque,
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
    Limpia=IN1-IN2 si es dual, igual que ver_forma_onda.py).

    Carga el .bin ENTERO en memoria (via _leer_canales_bin) — sirve en la PC
    (donde se valido originalmente contra ver_forma_onda.py) pero NO en la
    placa: un chunk de captura real hace OOM ahi (ver
    construir_paquete_por_bloques, pensada para eso)."""
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


def construir_paquete_por_bloques(ruta: Path, bloque_s=BLOQUE_S_DEFAULT, margen_s=MARGEN_S_DEFAULT):
    """Mismo resultado que construir_paquete, pero leyendo y filtrando el
    .bin de a bloques de `bloque_s` segundos (revisar._iterar_segmentos +
    area_kurtosis._bloques_canal) en vez de cargarlo entero — memoria
    acotada a ~1 bloque en todo momento, sin importar el tamaño del
    archivo. Pensada para correr en la placa."""
    info = _cargar_info(ruta)
    dual = int(info.get("canales", 1)) == 2
    fs = float(info["fs_hz_por_canal"]) if dual else float(info["fs_hz"])

    nombres = ["IN1"] + (["IN2", "Limpia (IN1-IN2)"] if dual else [])
    acumulado = {n: {"t": [], "area": [], "kurt": []} for n in nombres}
    # residual = muestras YA FILTRADAS del bloque anterior que no llegaron a
    # completar una ventana — se le pegan adelante al core del proximo
    # bloque (ver _area_kurtosis_de_bloque) para no reiniciar la grilla de
    # ventanas en cada bloque.
    residual = {n: None for n in nombres}

    def _agregar(nombre, volts_bloque, n_izq, n_core, t_offset_s):
        t_loc, area, kurt, nuevo_residual = _area_kurtosis_de_bloque(
            volts_bloque, fs, n_izq, n_core, residual_anterior=residual[nombre])
        n_residual_anterior = len(residual[nombre]) if residual[nombre] is not None else 0
        t_abs = t_loc + t_offset_s - n_residual_anterior / fs
        acumulado[nombre]["t"].extend(t_abs.tolist())
        acumulado[nombre]["area"].extend(area.tolist())
        acumulado[nombre]["kurt"].extend(kurt.tolist())
        residual[nombre] = nuevo_residual

    for t_offset_s, bloque0_i16, bloque1_i16, n_izq, n_core in _bloques_canal(ruta, fs, bloque_s, margen_s):
        ch0_v = bloque0_i16.astype(np.float32) / 32767.0 * V_REF
        _agregar("IN1", ch0_v, n_izq, n_core, t_offset_s)

        if dual:
            ch1_v = bloque1_i16.astype(np.float32) / 32767.0 * V_REF
            _agregar("IN2", ch1_v, n_izq, n_core, t_offset_s)
            limpia_v = ch0_v - ch1_v
            _agregar("Limpia (IN1-IN2)", limpia_v, n_izq, n_core, t_offset_s)

    canales = [
        {
            "canal": nombre,
            "t_centro_s": [round(float(v), 6) for v in d["t"]],
            "area": [float(v) for v in d["area"]],
            "kurtosis": [float(v) for v in d["kurt"]],
        }
        for nombre, d in acumulado.items()
    ]
    return {"archivo": ruta.name, "fs_hz": fs, "ventana_s": AREA_VENTANA_S, "canales": canales}


def main():
    ap = argparse.ArgumentParser(
        description="Exporta el paquete liviano (area+kurtosis por ventana) de una captura .bin")
    ap.add_argument("archivo", type=Path, help="captura .bin (requiere session_*_info.json al lado)")
    ap.add_argument("-o", "--salida", type=Path, default=None,
                     help="ruta del JSON de salida (default: <archivo sin .bin>.paquete.json)")
    ap.add_argument("--todo-de-una", action="store_true",
                     help="cargar el .bin entero en memoria en vez de procesarlo por bloques "
                          "(sirve para comparar en la PC; en la placa hace OOM con un chunk real)")
    ap.add_argument("--bloque-s", type=float, default=BLOQUE_S_DEFAULT,
                     help=f"segundos de señal 'core' por bloque (default: {BLOQUE_S_DEFAULT})")
    args = ap.parse_args()

    if args.todo_de_una:
        paquete = construir_paquete(args.archivo)
    else:
        paquete = construir_paquete_por_bloques(args.archivo, bloque_s=args.bloque_s)
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
