#!/usr/bin/env python3
"""
metricas_purgas.py — estudio area del sensor vs kg de arena de las purgas del BBS.

La verdad de campo son las PURGAS ("Purga de BBS ... Aporte: N kg de arena"):
entre una purga y la siguiente salieron N kg. El kg/hora de la planilla es esa
cantidad repartida pareja entre purgas, no un dato horario real.

Por cada intervalo entre purgas calcula, con los CSV del modo evento:
  M1  ventanas con kurtosis > KURT_UMBRAL                        (picos, cantidad)
  M2  suma de (area - base) en esas ventanas                      (picos, energia)
  M3  suma de (area - base) en ventanas con exceso > EXC_LENTO    ("lomas" lentas)
y los parametros de la planilla promediados en el intervalo (presiones,
orificio, caudales cuando BPO-2072 esta en control, horas en control).

Base: percentil BASE_PCT de la mediana por minuto del area, en una ventana
movil de +-BASE_MIN minutos. Definiciones FIJADAS el 2026-10-01 antes de ver
la purga que cierra el intervalo que arranca 1/10 04:00 local (ver
docs/estudio_arena_vs_kg.md): no cambiarlas sin anotarlo ahi.

Uso:
    .venv/bin/python analisis/estudio_arena/metricas_purgas.py PLANILLA.csv CARPETA_CSV [CARPETA_CSV ...] [--salida tabla.csv]
"""
import argparse, csv, glob, os, re
from datetime import datetime, timedelta, timezone
import numpy as np

KURT_UMBRAL = 3.8
EXC_LENTO = 0.008
BASE_PCT = 20
BASE_MIN = 90
HUSO_PLANILLA_H = -3          # [suposicion] la planilla esta en hora local UTC-3
COL = dict(fecha=0, orif=1, pboca=2, tboca=3, plin=4, psep=8, liq=10, petr_pct=13,
           agua_pct=19, gas=23, kgh=27, com=36)


def num(s):
    s = (s or "").strip()
    if s in ("", "-"):
        return np.nan
    return float(s.replace(".", "").replace(",", "."))


def leer_planilla(ruta):
    filas = list(csv.reader(open(ruta, encoding="utf-8")))
    datos, purgas = [], []
    for r in filas:
        if not r or not re.match(r"\d+-\d+-\d+ \d+:\d+", r[0]):
            continue
        t = datetime.strptime(r[0], "%d-%m-%y %H:%M").replace(tzinfo=timezone(timedelta(hours=HUSO_PLANILLA_H)))
        datos.append((t, {k: num(r[i]) for k, i in COL.items() if k not in ("fecha", "com")}))
        com = r[COL["com"]] if len(r) > COL["com"] else ""
        if re.search(r"purga", com, re.I) and re.search(r"arena", com, re.I) and not re.search(r"sin aporte", com, re.I):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", com, re.I)
            if not m:
                continue
            tp = t
            h = re.search(r"(\d{1,2}):(\d{2})\s*hs", com, re.I)    # hora dentro del comentario
            if h:
                tp = t.replace(hour=int(h.group(1)), minute=int(h.group(2)))
            purgas.append((tp, float(m.group(1).replace(",", ".")), com.strip()))
    return datos, purgas


def leer_ventanas(carpetas):
    archivos = {}
    for d in carpetas:
        for f in glob.glob(os.path.join(d, "ventanas_*.csv")):
            b = os.path.basename(f)
            if b not in archivos or os.path.getsize(f) > os.path.getsize(archivos[b]):
                archivos[b] = f
    T, A, K = [], [], []
    for b in sorted(archivos):
        for linea in open(archivos[b]):
            p = linea.rstrip().split(",")
            if p[0] == "window_count" or len(p) < 5 or p[4] != "ok":
                continue
            T.append(int(p[1]) / 1000.0); A.append(float(p[2])); K.append(float(p[3]))
    T, A, K = np.array(T), np.array(A), np.array(K)
    o = np.argsort(T, kind="stable")
    return T[o], A[o], K[o]


def base_area(T, A):
    minuto = (T // 60).astype(np.int64)
    u, inv = np.unique(minuto, return_inverse=True)
    orden = np.argsort(inv, kind="stable")
    cortes = np.cumsum(np.bincount(inv))[:-1]
    med = np.array([np.median(x) for x in np.split(A[orden], cortes)])
    base = np.array([np.percentile(med[np.abs(u - x) <= BASE_MIN], BASE_PCT) for x in u])
    return np.interp(T / 60.0, u, base)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilla"); ap.add_argument("carpetas", nargs="+"); ap.add_argument("--salida")
    a = ap.parse_args()
    datos, purgas = leer_planilla(a.planilla)
    T, A, K = leer_ventanas(a.carpetas)
    ex = A - base_area(T, A)
    tabla = []
    puntos = purgas + [(datetime.fromtimestamp(T[-1], timezone.utc), None, "ABIERTO (ultimo dato del sensor)")]
    for (t0, _, _), (t1, kg, com) in zip(puntos, puntos[1:]):
        m = (T >= t0.timestamp()) & (T < t1.timestamp())
        horas = (t1 - t0).total_seconds() / 3600
        cob = m.sum() * 0.05 / 3600
        if cob == 0:
            continue
        k, e = K[m], ex[m]
        par = [d for t, d in datos if t0 <= t < t1]
        prom = lambda c: np.nanmean([d[c] for d in par]) if par else np.nan
        en_control = [d for d in par if d["liq"] > 0]
        fila = dict(inicio_local=t0.astimezone(timezone(timedelta(hours=HUSO_PLANILLA_H))).strftime("%d/%m %H:%M"),
                    fin_local=t1.astimezone(timezone(timedelta(hours=HUSO_PLANILLA_H))).strftime("%d/%m %H:%M"),
                    kg="" if kg is None else kg, horas=round(horas, 1), horas_con_dato=round(cob, 1),
                    M1=int(np.sum(k > KURT_UMBRAL)), M2=round(float(e[k > KURT_UMBRAL].sum()), 2),
                    M3=round(float(e[e > EXC_LENTO].sum()), 0), kurt_max=round(float(k.max()), 1),
                    orificio_mm=round(prom("orif"), 3), p_boca_psi=round(prom("pboca"), 0),
                    p_linea_psi=round(prom("plin"), 0), horas_en_control=len(en_control),
                    liq_m3h_control=round(np.mean([d["liq"] for d in en_control]), 2) if en_control else "",
                    gas_m3h_control=round(np.nanmean([d["gas"] for d in en_control]), 0) if en_control else "",
                    agua_pct_control=round(np.nanmean([d["agua_pct"] for d in en_control]), 0) if en_control else "")
        tabla.append(fila)
    cols = list(tabla[0].keys())
    print("  ".join(cols))
    for f in tabla:
        print("  ".join(str(f[c]) for c in cols))
    if a.salida:
        with open(a.salida, "w", newline="") as fh:
            w = csv.DictWriter(fh, cols); w.writeheader(); w.writerows(tabla)


if __name__ == "__main__":
    main()
