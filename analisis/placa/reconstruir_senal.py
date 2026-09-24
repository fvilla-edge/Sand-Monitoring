#!/usr/bin/env python3
"""reconstruir_senal.py — arma en la PC una señal continua a partir de lo que
guarda el modo evento: las ventanas crudas de los eventos (evento_*.bin/.json,
solo las que cruzaron el umbral) y el registro continuo de area/kurtosis de
TODAS las ventanas (ventanas_*.csv). Los huecos entre eventos se rellenan con
ruido de fondo.

Todo en el DOMINIO FILTRADO (mismo pasabanda que el resto del analisis,
area_kurtosis._filtrar_pasabanda): el area que mide la FPGA es de la señal
filtrada, asi que solo se puede imitar la parte dentro de la banda — pegar
relleno entre ventanas CRUDAS dejaria un salto en cada union (la cruda trae
continua y baja frecuencia que el relleno no tiene). La cruda original no se
toca: sigue en cada evento_*.bin.

Relleno: ruido gaussiano pasado por el mismo pasabanda, con una envolvente
que sigue el area de cada ventana (interpolada entre centros de ventana,
para no meter escalones cada 50ms). El area de la FPGA se pasa a la del
software con escala + piso de ruido propio de la FPGA (ver calibrar_area),
calibrados con los mismos eventos de la corrida cuando se puede.

Uniones: cada evento entra con peso 1 en su ventana oficial y una rampa
lineal en el margen (±10ms); donde se superponen dos eventos (ventanas
consecutivas) se promedian — son copias del mismo stream. Donde el peso
total no llega a 1, completa el relleno.

La señal reconstruida es en parte INVENTADA: sirve para ver/escuchar, no
para calcular. La mascara dice que es cada muestra:
  1 = señal real (evento), 0 = relleno con area medida,
  2 = relleno SIN dato (ventana saltada: envolvente interpolada).

Tamaño: a 3.9MHz son ~15.6MB por segundo (float32) — 1h serian ~56GB. Por
eso se reconstruye un rango (--desde/--duracion-s, default 30s), no un dia.

Uso:
  .venv/bin/python3 analisis/placa/reconstruir_senal.py CARPETA [--desde S] [--duracion-s 30]
      [--umbral-simulado K] [-o salida.npz] [--semilla 0] [--png]
  CARPETA: la de --destino de capturar_eventos (eventos + ventanas_*.csv).
  --desde: segundos desde el inicio del registro (default 0).
  --umbral-simulado: usar solo los eventos con kurtosis >= K (para validar
      contra una corrida con --umbral 1, que guardo todas las ventanas).
Salida .npz: senal (float32, cuentas filtradas), mascara (uint8), fs_hz,
window_count_inicial, inicio_utc, escala_area, eventos usados.
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from area_kurtosis import _filtrar_pasabanda  # noqa: E402
from ventanas_a_paquete import VENTANA_S, _iso, leer_filas, partir_en_tramos  # noqa: E402

FS_HZ = 125e6 / 32
# piso de ruido del area de la FPGA (bitstream port-2026.1, decimacion 32),
# medido en rp-f0fd8c el 2026-09-24 — ver calibrar_area(). DEPENDE DEL JUMPER
# de IN1: HV (campo) 0.3074 (395 ventanas de reposo), LV 0.2333 (R2). Que
# cambie con el jumper indica que no es solo redondeo interno de la FPGA.
PISO_FPGA_DEFAULT = 0.3074  # HV, como en campo
ESCALA_FPGA_DEFAULT = 0.9992


def cargar_eventos(carpeta, umbral=None):
    eventos = []
    for js in sorted(glob.glob(os.path.join(carpeta, "evento_*.json"))):
        with open(js) as f:
            e = json.load(f)
        if umbral is not None and e["kurtosis"] < umbral:
            continue
        e["ruta"] = js[:-5] + ".bin"
        eventos.append(e)
    return eventos


def calibrar_area(eventos, area_reposo, fs, piso_default=PISO_FPGA_DEFAULT, escala_default=ESCALA_FPGA_DEFAULT):
    """Relacion entre el area de la FPGA (f) y la del software sobre las mismas
    muestras (sw), modelada como señal + piso de ruido propio de la FPGA
    (causa sin confirmar: se penso en redondeo del filtro en punto fijo, pero
    q cambia con el jumper HV/LV): sw = sqrt((c*f)^2 - q^2). Medido en
    rp-f0fd8c (2026-09-24, LV): con señal fuerte sw/f = 0.999, en reposo
    (f ~0.63) sw/f = 0.897. En HV, c no esta medido (sin señal fuerte).

    c sale de los eventos con area alta (o `escala_default` si hay menos de
    5); q de los eventos de reposo (area
    cerca de `area_reposo`, la mediana del registro continuo en ventanas
    tranquilas, y kurtosis < 4). Con --umbral 5 casi no se guardan ventanas de reposo: si hay
    menos de 5, se usa `piso_default` (medido en el banco, depende del
    bitstream)."""
    f, sw, k = [], [], []
    for e in eventos:
        if e["con_hueco"] or e["area"] <= 0:
            continue
        x = np.fromfile(e["ruta"], dtype="<i2").astype(np.float64)
        y = _filtrar_pasabanda(x, fs).astype(np.float64)
        a = e["inicio_ventana_en_archivo"]
        f.append(e["area"])
        k.append(e["kurtosis"])
        sw.append(np.abs(y[a:a + e["ventana_muestras"]]).sum() / fs)
    if not f:
        raise SystemExit("no hay eventos sin hueco para calibrar el area")
    f, sw, k = np.array(f), np.array(sw), np.array(k)
    fuertes = f >= 3 * area_reposo
    # con pocos eventos fuertes no se estima c con los de nivel bajo: ahi el
    # cociente ya trae el piso adentro y se restaria dos veces (visto en L1,
    # 1 evento de reposo -> c=0.88)
    if fuertes.sum() >= 5:
        c, origen_c = float(np.median(sw[fuertes] / f[fuertes])), f"medida ({int(fuertes.sum())} eventos fuertes)"
    else:
        c, origen_c = escala_default, "default del banco"
    # solo reposo de verdad (kurtosis < 4): con --umbral 5 las ventanas de area
    # baja que se guardan tienen picos sueltos y el piso sale ~0 (visto en R1/R2)
    quietos = (f > 0.5 * area_reposo) & (f < 1.5 * area_reposo) & (k < 4)
    if quietos.sum() >= 5:
        q = float(np.sqrt(max(0.0, np.median((c * f[quietos]) ** 2 - sw[quietos] ** 2))))
        origen = f"medido ({int(quietos.sum())} eventos de reposo)"
    else:
        q, origen = piso_default, "default del banco (sin eventos de reposo en la corrida)"
    return c, q, f"escala {origen_c}, piso {origen}", len(f)


def area_software(f, c, q):
    return np.sqrt(np.maximum((c * np.asarray(f)) ** 2 - q ** 2, 0.0))


def reconstruir(carpeta, desde_s=0.0, duracion_s=30.0, umbral=None, semilla=0, fs=FS_HZ):
    csvs = sorted(glob.glob(os.path.join(carpeta, "ventanas_*.csv")))
    if not csvs:
        raise SystemExit(f"{carpeta}: no hay ventanas_*.csv (¿captura sin registro continuo?)")
    tramos = partir_en_tramos(leer_filas(csvs))
    if len(tramos) > 1:
        print(f"aviso: {len(tramos)} tramos (reinicios de captura); se usa el primero", file=sys.stderr)
    filas = tramos[0]
    N = int(round(fs * VENTANA_S))
    wc0 = filas[0]["wc"] + int(desde_s / VENTANA_S)
    nv = int(round(duracion_s / VENTANA_S))
    por_wc = {r["wc"]: r for r in filas}
    wcs = np.arange(wc0, wc0 + nv)
    if not any(w in por_wc for w in wcs):
        raise SystemExit("el rango pedido no tiene ventanas en el registro")

    eventos = cargar_eventos(carpeta, umbral)
    area_ok = [r["area"] for r in filas if r["ok"] and r["kurt"] < 4]
    area_reposo = float(np.median(area_ok)) if area_ok else float(np.median([e["area"] for e in eventos]))
    c, q, origen_piso, n_escala = calibrar_area(eventos, area_reposo, fs)
    eventos = [e for e in eventos if wc0 <= e["window_count"] < wc0 + nv]

    # envolvente del relleno: mean|x| objetivo por ventana (en cuentas filtradas)
    obj = np.full(nv, np.nan)
    sin_dato = np.ones(nv, dtype=bool)
    for i, w in enumerate(wcs):
        r = por_wc.get(int(w))
        if r is not None and r["ok"]:
            obj[i] = area_software(r["area"], c, q) * fs / N
            sin_dato[i] = False
    if np.isnan(obj).all():
        raise SystemExit("el rango no tiene ventanas con area")
    idx = np.arange(nv)
    obj = np.interp(idx, idx[~np.isnan(obj)], obj[~np.isnan(obj)])
    total = nv * N
    centros = (idx + 0.5) * N
    envolvente = np.interp(np.arange(total), centros, obj).astype(np.float32)

    # ruido de banda: gaussiano filtrado, normalizado a mean|x| = 1. Se filtra con
    # un colchon previo para que el transitorio de arranque del filtro no entre.
    rng = np.random.default_rng(semilla)
    colchon = N
    ruido = _filtrar_pasabanda(rng.standard_normal(total + colchon).astype(np.float32), fs)[colchon:]
    ruido /= np.abs(ruido).mean()
    relleno = ruido * envolvente

    num = np.zeros(total, dtype=np.float64)
    den = np.zeros(total, dtype=np.float64)
    usados = []
    # un evento con hueco trae, en el tramo que no llego, datos VIEJOS del buffer
    # circular (el indice avanza sin escribir) y el .json no dice donde: se deja
    # afuera y esa ventana va como relleno
    con_hueco = sorted(e["window_count"] for e in eventos if e["con_hueco"])
    for e in (e for e in eventos if not e["con_hueco"]):
        x = np.fromfile(e["ruta"], dtype="<i2").astype(np.float64)
        y = _filtrar_pasabanda(x, fs).astype(np.float64)
        M = e["margen_muestras"]
        peso = np.ones(len(y))
        if M > 0:
            peso[:M] = np.linspace(0, 1, M, endpoint=False)
            peso[len(y) - M:] = np.linspace(1, 0, M + 1)[1:]
        # la ventana wc cubre las muestras [(wc-1)*N, wc*N) del registro; x[0] esta M antes
        ini = (e["window_count"] - 1 - (wc0 - 1)) * N - e["inicio_ventana_en_archivo"]
        a, b = max(0, ini), min(total, ini + len(y))
        if a >= b:
            continue
        num[a:b] += (y * peso)[a - ini:b - ini]
        den[a:b] += peso[a - ini:b - ini]
        usados.append(e["window_count"])

    senal = relleno.astype(np.float64)
    hay = den > 0
    real = num[hay] / np.maximum(den[hay], 1.0)
    w = np.minimum(den[hay], 1.0)
    senal[hay] = real + (1 - w) * relleno[hay]
    mascara = np.zeros(total, dtype=np.uint8)
    mascara[np.repeat(sin_dato, N)] = 2
    mascara[den >= 0.5] = 1

    t0_ms = filas[0]["t_ms"] + (wc0 - filas[0]["wc"]) * VENTANA_S * 1000 - VENTANA_S * 1000
    return {
        "senal": senal.astype(np.float32),
        "mascara": mascara,
        "fs_hz": fs,
        "window_count_inicial": int(wc0),
        "inicio_utc": _iso(t0_ms),
        "escala_area": c,
        "piso_fpga": q,
        "origen_piso": origen_piso,
        "eventos": np.array(sorted(usados), dtype=np.int64),
        "eventos_con_hueco_omitidos": np.array(con_hueco, dtype=np.int64),
        "n_escala": n_escala,
    }


def guardar_png(r, ruta):
    """Vista rapida: señal (color = real, gris = relleno, rojo = sin dato) y
    mean|x| por ventana. Reduce a ~20000 puntos (min/max por grupo) para que
    los picos no desaparezcan."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x, m, fs = r["senal"], r["mascara"], r["fs_hz"]
    paso = max(1, len(x) // 10000)
    n = len(x) // paso * paso
    g = x[:n].reshape(-1, paso)
    t = np.repeat(np.arange(g.shape[0]) * paso / fs, 2)
    y = np.column_stack([g.min(axis=1), g.max(axis=1)]).ravel()
    mg = np.repeat(np.round(m[:n].reshape(-1, paso).mean(axis=1)).astype(int), 2)
    N = int(round(fs * VENTANA_S))
    nv = len(x) // N
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for valor, color, etiqueta in ((1, "C1", "real (evento)"), (0, "0.6", "relleno"), (2, "C3", "relleno sin dato")):
        if (mg == valor).any():
            a1.plot(t, np.where(mg == valor, y, np.nan), lw=0.4, color=color, label=etiqueta)
    a1.legend(loc="upper right")
    a1.set_ylabel("cuentas (filtrada)")
    a1.set_title(f"Reconstruccion desde {r['inicio_utc']} — relleno inventado, no usar para calcular")
    a2.plot((np.arange(nv) + 0.5) * VENTANA_S, np.abs(x[:nv * N]).reshape(nv, N).mean(axis=1), lw=0.8)
    a2.set_yscale("log")
    a2.set_ylabel("nivel promedio por ventana\n(≈ área / 0.05 s)")
    a2.set_xlabel("t (s)")
    fig.tight_layout()
    fig.savefig(ruta, dpi=90)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", type=Path)
    ap.add_argument("--desde", type=float, default=0.0, help="segundos desde el inicio del registro")
    ap.add_argument("--duracion-s", type=float, default=30.0)
    ap.add_argument("--umbral-simulado", type=float, default=None)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("-o", "--salida", type=Path)
    ap.add_argument("--png", action="store_true", help="guardar tambien una vista rapida (.png al lado del .npz)")
    args = ap.parse_args()
    if args.duracion_s > 300:
        sys.exit(f"--duracion-s {args.duracion_s:.0f}: son ~{args.duracion_s * 15.6 / 1000:.1f}GB; "
                 "reconstruir de a tramos de hasta 300s")

    r = reconstruir(args.carpeta, args.desde, args.duracion_s, args.umbral_simulado, args.semilla)
    salida = args.salida or args.carpeta / f"reconstruccion_wc{r['window_count_inicial']}.npz"
    np.savez(salida, **r)
    if args.png:
        guardar_png(r, salida.with_suffix(".png"))
    m = r["mascara"]
    print(f"{salida}: {len(r['senal']) / r['fs_hz']:.1f}s desde {r['inicio_utc']} | "
          f"{len(r['eventos'])} eventos ({len(r['eventos_con_hueco_omitidos'])} con hueco omitidos) | real {np.mean(m == 1) * 100:.1f}% relleno {np.mean(m == 0) * 100:.1f}% "
          f"sin dato {np.mean(m == 2) * 100:.1f}% | area sw=sqrt(({r['escala_area']:.4g}*fpga)^2-{r['piso_fpga']:.4g}^2), "
          f"{r['origen_piso']}")


if __name__ == "__main__":
    main()
