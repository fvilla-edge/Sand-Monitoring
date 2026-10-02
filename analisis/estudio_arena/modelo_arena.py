#!/usr/bin/env python3
"""
modelo_arena.py — modelo que aprende con cada purga (docs/plan_modelo_arena.md).

Modelo v1, dos ingredientes por hora:
    kg de la hora = a * (ventanas con kurtosis > KURT_UMBRAL en la hora) + b
      a = kg por pico, b = "fondo" (kg/h que salen sin picos visibles).
Cada purga solo dice la SUMA de las horas de su intervalo, asi que el ajuste es
    kg del intervalo = a * N_picos + b * horas
con regresion bayesiana (a, b con incertidumbre, prior debil, ruido SIGMA_KG).

Evaluacion honesta ("prequential"): cada purga se predice SOLO con las purgas
anteriores a ella. Las predicciones van a REGISTRO (CSV en git, nunca se
sobrescribe; una fila por version del modelo y por intervalo). Una prediccion
es "anticipada" si la version del modelo es anterior al fin del intervalo; si
no, "retro" (calculada despues, vale como referencia pero no como prueba).

Niveles (kg/h promedio): poca < 0.5, media 0.5-3, mucha >= 3.

Uso:
    .venv/bin/python analisis/estudio_arena/modelo_arena.py PLANILLA.csv CARPETA_CSV [...] [--registrar] [--horas 48]
"""
import argparse, csv, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np
from math import erf, sqrt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_purgas as mp

MODELO_VERSION = "v1"
MODELO_FECHA = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)   # fijado antes de la purga que cierra E
KURT_UMBRAL = 3.5
PRIOR_MEDIA = np.array([0.04, 0.3])      # a [kg/pico], b [kg/h]
PRIOR_SD = np.array([0.04, 0.5])
SIGMA_KG = 3.0                           # ruido por intervalo (~ error LOO de la sec.9)
COB_MIN = 0.8                            # fraccion de horas con dato para usar el intervalo
NIVELES = [("poca", 0.0), ("media", 0.5), ("mucha", 3.0)]   # cortes en kg/h
REGISTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registro_predicciones.csv")
COLS = ["fecha_calculo", "version", "tipo", "inicio_local", "fin_local", "horas", "horas_con_dato",
        "n_picos", "n_purgas_usadas", "a", "b", "kg_pred", "kg_sd", "p_poca", "p_media", "p_mucha",
        "nivel_pred", "kg_real", "nivel_real", "acierto_nivel", "error_kg"]


def nivel(kg_h):
    return [n for n, c in NIVELES if kg_h >= c][-1]


def ajustar(X, y):
    """Regresion bayesiana lineal con prior gaussiano independiente. Devuelve media y covarianza."""
    P0 = np.diag(1 / PRIOR_SD ** 2)
    if len(y) == 0:
        return PRIOR_MEDIA.copy(), np.linalg.inv(P0)
    P = P0 + X.T @ X / SIGMA_KG ** 2
    S = np.linalg.inv(P)
    return S @ (P0 @ PRIOR_MEDIA + X.T @ y / SIGMA_KG ** 2), S


def predecir(theta, S, x, horas):
    m = float(x @ theta); sd = float(np.sqrt(x @ S @ x + SIGMA_KG ** 2))
    cdf = lambda v: 0.5 * (1 + erf((v - m) / (sd * sqrt(2))))
    cortes = [c * horas for _, c in NIVELES[1:]]
    p = [cdf(cortes[0]), cdf(cortes[1]) - cdf(cortes[0]), 1 - cdf(cortes[1])]
    return max(m, 0.0), sd, p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilla"); ap.add_argument("carpetas", nargs="+")
    ap.add_argument("--registrar", action="store_true", help=f"agrega las predicciones nuevas a {REGISTRO}")
    ap.add_argument("--horas", type=int, default=0, help="muestra el nivel estimado de las ultimas N horas")
    a = ap.parse_args()
    loc = timezone(timedelta(hours=mp.HUSO_PLANILLA_H))
    fmt = lambda t: t.astimezone(loc).strftime("%d/%m %H:%M")

    _, purgas = mp.leer_planilla(a.planilla)
    T, _, K = mp.leer_ventanas(a.carpetas)
    pico = K > KURT_UMBRAL

    # intervalos entre purgas con datos del sensor (+ el abierto hasta el ultimo dato)
    pts = purgas + [(datetime.fromtimestamp(T[-1], timezone.utc), None, "")]
    ints = []
    for (t0, _, _), (t1, kg, _) in zip(pts, pts[1:]):
        m = (T >= t0.timestamp()) & (T < t1.timestamp())
        if not m.any():
            continue
        horas = (t1 - t0).total_seconds() / 3600
        cob = m.sum() * 0.05 / 3600
        ints.append(dict(t0=t0, t1=t1, kg=kg, horas=horas, cob=cob,
                         n=pico[m].sum() * horas / cob))      # picos extrapolados a las horas sin dato
    usables = [i for i in ints if i["kg"] is not None and i["cob"] / i["horas"] >= COB_MIN]

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    filas = []
    print(f"Modelo {MODELO_VERSION}: kg = a*picos(k>{KURT_UMBRAL}) + b*horas   (fijado {MODELO_FECHA:%Y-%m-%d %H:%M} UTC)\n")
    print(f"{'intervalo (local)':27s} {'h':>5s} {'picos':>6s} {'usa':>4s} {'pred kg':>12s} {'P poca/media/mucha':>20s} "
          f"{'nivel':>6s} {'real':>9s} {'tipo':>10s}")
    for it in ints:
        previas = [u for u in usables if u["t1"] <= it["t0"]]
        X = np.array([[u["n"], u["horas"]] for u in previas]).reshape(-1, 2)
        y = np.array([u["kg"] for u in previas])
        th, S = ajustar(X, y)
        kg_p, sd, p = predecir(th, S, np.array([it["n"], it["horas"]]), it["horas"])
        nv = ["poca", "media", "mucha"][int(np.argmax(p))]
        real = it["kg"]
        nv_real = nivel(real / it["horas"]) if real is not None else ""
        tipo = "abierto" if real is None else ("anticipada" if it["t1"] > MODELO_FECHA else "retro")
        parcial = it["cob"] / it["horas"] < COB_MIN
        print(f"{fmt(it['t0'])} -> {fmt(it['t1'])} {it['horas']:5.1f} {it['n']:6.0f} {len(previas):4d} "
              f"{kg_p:6.1f} ±{sd:4.1f} {p[0]:6.0%}/{p[1]:4.0%}/{p[2]:4.0%}  {nv:>6s} "
              f"{'' if real is None else f'{real:g} {nv_real}':>9s} {tipo:>10s}{'  (parcial)' if parcial else ''}")
        filas.append(dict(fecha_calculo=ahora, version=MODELO_VERSION, tipo=tipo + ("_parcial" if parcial else ""),
                          inicio_local=fmt(it["t0"]), fin_local=fmt(it["t1"]) + (" (ultimo dato)" if real is None else ""),
                          horas=round(it["horas"], 2), horas_con_dato=round(it["cob"], 2), n_picos=round(it["n"]),
                          n_purgas_usadas=len(previas), a=round(th[0], 5), b=round(th[1], 4),
                          kg_pred=round(kg_p, 2), kg_sd=round(sd, 2), p_poca=round(p[0], 3), p_media=round(p[1], 3),
                          p_mucha=round(p[2], 3), nivel_pred=nv, kg_real="" if real is None else real, nivel_real=nv_real,
                          acierto_nivel="" if real is None else int(nv == nv_real),
                          error_kg="" if real is None else round(kg_p - real, 2)))

    X = np.array([[u["n"], u["horas"]] for u in usables]); y = np.array([u["kg"] for u in usables])
    th, S = ajustar(X, y); sd = np.sqrt(np.diag(S))
    print(f"\nCon las {len(usables)} purgas usables: a = {th[0]:.4f} ± {sd[0]:.4f} kg/pico   "
          f"b = {th[1]:.3f} ± {sd[1]:.3f} kg/h de fondo")
    cerradas = [f for f in filas if f["kg_real"] != "" and "parcial" not in f["tipo"]]
    if cerradas:
        print(f"Purgas predichas (sin parciales): {len(cerradas)}, nivel acertado {sum(f['acierto_nivel'] for f in cerradas)}, "
              f"error medio {np.mean([abs(f['error_kg']) for f in cerradas]):.1f} kg "
              f"(anticipadas: {sum(1 for f in cerradas if f['tipo'] == 'anticipada')})")

    if a.horas:
        print(f"\nNivel estimado por hora, ultimas {a.horas} h (kg/h = a*picos + b):")
        h = (T // 3600).astype(np.int64); u, inv = np.unique(h, return_inverse=True)
        n = np.bincount(inv); c = np.bincount(inv, weights=pico)
        for x, nn, cc in list(zip(u, n, c))[-a.horas:]:
            if nn < 36000:
                print(f"  {datetime.fromtimestamp(x * 3600, loc):%d/%m %H}h  sin dato"); continue
            kgh = th[0] * cc * 72000 / nn + th[1]
            print(f"  {datetime.fromtimestamp(x * 3600, loc):%d/%m %H}h  {cc * 72000 / nn:5.0f} picos  ~{kgh:4.1f} kg/h  {nivel(kgh)}")

    if a.registrar:
        previas = set()
        if os.path.exists(REGISTRO):
            previas = {(r["version"], r["inicio_local"], r["fin_local"]) for r in csv.DictReader(open(REGISTRO))}
        nuevas = [f for f in filas if (f["version"], f["inicio_local"], f["fin_local"]) not in previas]
        nuevo = not os.path.exists(REGISTRO)
        with open(REGISTRO, "a", newline="") as fh:
            w = csv.DictWriter(fh, COLS)
            if nuevo:
                w.writeheader()
            w.writerows(nuevas)
        print(f"\nRegistro: {len(nuevas)} filas nuevas en {os.path.relpath(REGISTRO)}")


if __name__ == "__main__":
    main()
