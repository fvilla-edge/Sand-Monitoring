#!/usr/bin/env python3
"""ventanas_a_paquete.py — convierte el registro continuo del modo evento
(`ventanas_AAAAMMDD_HH.csv`, escrito por scripts_campo/c/capturar_eventos)
al formato de "paquete liviano" que ya usa el proyecto
(`exportar_paquete_area.py`, `coleccionar_paquete_placa.py`, visor
`ver_paquete.py`):

  {"archivo", "fs_hz", "ventana_s",
   "canales": [{"canal", "t_centro_s", "area", "kurtosis"}]}

mas campos extra que los consumidores actuales ignoran: "origen",
"inicio_utc", "window_count_inicial", "ventanas_saltadas", "segmentos".

Tiempo: la referencia exacta es window_count (cada ventana dura 50ms justos);
t_utc_ms del CSV es la hora en que el sondeo LEYO la ventana (jitter de
decenas de ms), asi que solo se usa para anclar cada tramo continuo a la
hora real (mediana de t_utc_ms - wc*50ms). Un tramo nuevo empieza cuando
window_count retrocede o cuando su avance no cuadra con el reloj por mas de
1s (reinicio de la captura o del bitstream: el contador de la FPGA no es
continuo entre corridas). t_centro_s es relativo al inicio del paquete.

Las ventanas con estado=saltada (el sondeo no llego a leerlas, no hay dato)
NO van en las listas: quedan como hueco en t_centro_s y se cuentan en
"ventanas_saltadas". A proposito no se rellenan con NaN (romperia el
acumulado/cumsum rio abajo).

Uso:
  .venv/bin/python3 analisis/placa/ventanas_a_paquete.py ventanas_20260924_13.csv [...]
      -> un ventanas_20260924_13.paquete.json por CSV, al lado
  .venv/bin/python3 analisis/placa/ventanas_a_paquete.py CARPETA --unir -o dia.paquete.json
      -> todos los ventanas_*.csv de la carpeta en un solo paquete
"""
import argparse
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

VENTANA_S = 0.05
FS_HZ = 125e6 / 32  # capturar_eventos corre a decimacion 32 por defecto
SALTO_RELOJ_S = 1.0


def leer_filas(rutas):
    filas = []
    for ruta in rutas:
        with open(ruta, newline="") as f:
            for r in csv.DictReader(f):
                filas.append({
                    "wc": int(r["window_count"]),
                    "t_ms": int(r["t_utc_ms"]),
                    "ok": r["estado"] == "ok",
                    "area": float(r["area"]) if r["area"] else None,
                    "kurt": float(r["kurtosis"]) if r["kurtosis"] else None,
                })
    filas.sort(key=lambda r: r["t_ms"])
    return filas


def partir_en_tramos(filas):
    """Listas de filas con window_count continuo y coherente con el reloj."""
    tramos, actual = [], []
    for r in filas:
        if actual:
            p = actual[-1]
            dwc = r["wc"] - p["wc"]
            dt = (r["t_ms"] - p["t_ms"]) / 1000
            if dwc <= 0 or abs(dwc * VENTANA_S - dt) > SALTO_RELOJ_S:
                tramos.append(actual)
                actual = []
        actual.append(r)
    if actual:
        tramos.append(actual)
    return tramos


def armar_paquete(filas, nombre, fs_hz=FS_HZ):
    tramos = partir_en_tramos(filas)
    if not tramos:
        raise ValueError(f"{nombre}: sin filas")
    # ancla de cada tramo: hora UTC (ms) del INICIO de la ventana wc0 del tramo.
    # t_utc_ms se toma al leer, o sea despues de que la ventana termino.
    anclas = [statistics.median(r["t_ms"] - (r["wc"] - t[0]["wc"] + 1) * VENTANA_S * 1000 for r in t)
              for t in tramos]
    t0_ms = anclas[0]
    t_centro, area, kurt = [], [], []
    saltadas = 0
    segmentos = []
    for t, ancla in zip(tramos, anclas):
        base_s = (ancla - t0_ms) / 1000
        segmentos.append({
            "inicio_utc": _iso(ancla),
            "window_count_inicial": t[0]["wc"],
            "ventanas": t[-1]["wc"] - t[0]["wc"] + 1,
        })
        for r in t:
            if not r["ok"]:
                saltadas += 1
                continue
            t_centro.append(round(base_s + (r["wc"] - t[0]["wc"] + 0.5) * VENTANA_S, 6))
            area.append(r["area"])
            kurt.append(r["kurt"])
    return {
        "archivo": nombre,
        "fs_hz": fs_hz,
        "ventana_s": VENTANA_S,
        "canales": [{"canal": "IN1", "t_centro_s": t_centro, "area": area, "kurtosis": kurt}],
        "origen": "registro_continuo_modo_evento",
        "inicio_utc": _iso(t0_ms),
        "window_count_inicial": tramos[0][0]["wc"],
        "ventanas_saltadas": saltadas,
        "segmentos": segmentos,
    }


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", type=Path, help="ventanas_*.csv o carpetas que los contienen")
    ap.add_argument("--unir", action="store_true", help="un solo paquete con todos los CSV")
    ap.add_argument("-o", "--salida", type=Path, help="JSON de salida (solo con --unir)")
    args = ap.parse_args()

    csvs = []
    for e in args.entradas:
        csvs += sorted(e.glob("ventanas_*.csv")) if e.is_dir() else [e]
    if not csvs:
        sys.exit("no hay ventanas_*.csv en las entradas")
    if args.salida and not args.unir:
        sys.exit("-o solo tiene sentido con --unir (sin --unir sale un paquete por CSV)")

    grupos = [csvs] if args.unir else [[c] for c in csvs]
    for grupo in grupos:
        nombre = grupo[0].name if len(grupo) == 1 else f"{grupo[0].stem}..{grupo[-1].stem}"
        paquete = armar_paquete(leer_filas(grupo), nombre)
        salida = args.salida if args.unir and args.salida else grupo[0].with_suffix(".paquete.json")
        with open(salida, "w") as f:
            json.dump(paquete, f)
        n = len(paquete["canales"][0]["kurtosis"])
        print(f"{salida}: {n} ventanas, {paquete['ventanas_saltadas']} saltadas, "
              f"{len(paquete['segmentos'])} tramo(s), inicio {paquete['inicio_utc']}")


if __name__ == "__main__":
    main()
