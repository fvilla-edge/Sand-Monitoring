#!/usr/bin/env python3
"""
estudio_completo.py — busca que metrica del sensor predice los kg de las purgas,
con todos los intervalos entre purgas que tienen datos (docs/estudio_arena_vs_kg.md).

Con tan pocos intervalos solo se prueban modelos de UN parametro (kg = a*x, por
el origen) y se evaluan con leave-one-out (LOO): cada intervalo se predice con
el factor ajustado en los demas. Referencias contra las que comparar:
  - "horas": kg proporcional a la duracion del intervalo (no usa el sensor);
  - azar: misma evaluacion con la metrica permutada entre intervalos, para ver
    cuanto se puede "ganar" por casualidad eligiendo la mejor de muchas.

Intervalos parciales (pocas horas con dato) se extrapolan a la duracion
completa (x * horas / horas_con_dato) y se marcan; solo entran al ajuste con
--incluir-parciales.

Uso:
    .venv/bin/python analisis/estudio_arena/estudio_completo.py PLANILLA.csv CARPETA_CSV [...] [--salida features.csv]
"""
import argparse, csv, itertools, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_purgas as mp

UMBRALES_K = [3.2, 3.5, 3.8, 4.5, 5.0, 6.0, 8.0]
UMBRALES_EXC = [0.004, 0.008, 0.016, 0.032]
COB_MIN = 0.8          # fraccion de horas con dato para considerar el intervalo completo
GAP_RAFAGA_S = 60      # ventanas sobre umbral a menos de esto forman una misma rafaga


def rafagas(t):
    return 0 if len(t) == 0 else int(1 + np.sum(np.diff(t) > GAP_RAFAGA_S))


def features(T, K, ex, m):
    t, k, e = T[m], K[m], ex[m]
    f = {}
    for u in UMBRALES_K:
        s = k > u
        f[f"n_k>{u}"] = int(s.sum())
        f[f"exc_k>{u}"] = float(e[s].sum())
        f[f"rafagas_k>{u}"] = rafagas(t[s])
    for u in UMBRALES_EXC:
        f[f"exc>{u}"] = float(e[e > u].sum())
    f["exc_pos_total"] = float(e[e > 0].sum())
    f["kurt_p99.9"] = float(np.percentile(k, 99.9))
    f["kurt_max"] = float(k.max())
    f["sum_kurt-3_k>3.5"] = float((k[k > 3.5] - 3).sum())
    f["min_con_k>5"] = int(len(np.unique((t[k > 5] // 60).astype(np.int64))))
    return f


def loo(x, y):
    n = len(y); pred = np.empty(n)
    for i in range(n):
        o = np.arange(n) != i
        a = (y[o] @ x[o]) / (x[o] @ x[o]) if x[o] @ x[o] > 0 else 0.0
        pred[i] = a * x[i]
    return pred


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilla"); ap.add_argument("carpetas", nargs="+")
    ap.add_argument("--salida"); ap.add_argument("--incluir-parciales", action="store_true")
    ap.add_argument("--permutaciones", type=int, default=2000)
    a = ap.parse_args()

    datos, purgas = mp.leer_planilla(a.planilla)
    T, A, K = mp.leer_ventanas(a.carpetas)
    ex = A - mp.base_area(T, A)
    loc = timezone(timedelta(hours=mp.HUSO_PLANILLA_H))

    filas = []
    for (t0, _, _), (t1, kg, _) in zip(purgas, purgas[1:]):
        m = (T >= t0.timestamp()) & (T < t1.timestamp())
        if not m.any():
            continue
        horas = (t1 - t0).total_seconds() / 3600
        cob = m.sum() * 0.05 / 3600
        f = features(T, K, ex, m)
        esc = horas / cob
        par = [d for t, d in datos if t0 <= t < t1]
        fila = dict(inicio=t0.astimezone(loc).strftime("%d/%m %H:%M"), fin=t1.astimezone(loc).strftime("%d/%m %H:%M"),
                    kg=kg, horas=horas, horas_con_dato=cob, completo=cob / horas >= COB_MIN,
                    horas_en_control=sum(1 for d in par if d["liq"] > 0),
                    p_linea=float(np.nanmean([d["plin"] for d in par])) if par else np.nan)
        fila.update({k: v * esc for k, v in f.items() if not k.startswith("kurt_")})
        fila.update({k: v for k, v in f.items() if k.startswith("kurt_")})
        filas.append(fila)

    print("Intervalos con datos del sensor:")
    for r in filas:
        print(f"  {r['inicio']} -> {r['fin']}  {r['kg']:6.1f} kg  {r['horas']:5.1f} h  "
              f"dato {r['horas_con_dato']:5.1f} h  {'completo' if r['completo'] else 'PARCIAL (extrapolado)'}")
    uso = [r for r in filas if r["completo"] or a.incluir_parciales]
    y = np.array([r["kg"] for r in uso])
    print(f"\nAjuste con {len(uso)} intervalos, kg = {y}")

    claves = [k for k in filas[0] if k not in ("inicio", "fin", "kg", "completo", "horas_con_dato")]
    res = []
    for c in claves:
        x = np.array([float(r[c]) for r in uso])
        if np.all(x == 0) or np.any(np.isnan(x)):
            continue
        p = loo(x, y)
        res.append((np.abs(p - y).mean(), c, np.corrcoef(x, y)[0, 1] if x.std() > 0 else np.nan, p))
    res.sort()
    base = next(r for r in res if r[1] == "horas")
    print(f"\nReferencia sin sensor (kg ~ horas): error medio LOO = {base[0]:.1f} kg")
    print(f"Referencia trivial (kg = promedio de los otros): "
          f"{np.mean([abs(y[i] - np.delete(y, i).mean()) for i in range(len(y))]):.1f} kg\n")
    print(f"{'metrica':24s} {'MAE LOO':>8s} {'r':>6s}  predicciones LOO")
    for mae, c, r, p in res:
        print(f"{c:24s} {mae:8.1f} {r:+6.2f}  {np.round(p, 1)}")

    # azar: mejor MAE posible eligiendo entre metricas sin relacion con los kg
    X = np.array([[float(r[c]) for r in uso] for _, c, _, _ in res if c != "horas"])
    rng = np.random.default_rng(0); mejores = []
    for _ in range(a.permutaciones):
        yp = rng.permutation(y)
        if np.array_equal(yp, y):
            continue
        mejores.append(min(np.abs(loo(x, yp) - yp).mean() for x in X))
    mejores = np.array(mejores)
    mejor_real = min(r[0] for r in res if r[1] != "horas")
    print(f"\nAzar: con los kg permutados, la mejor de {len(X)} metricas da MAE LOO "
          f"mediana {np.median(mejores):.1f} kg (p10 {np.percentile(mejores, 10):.1f}); "
          f"la mejor real da {mejor_real:.1f} kg -> "
          f"fraccion de permutaciones igual o mejor: {np.mean(mejores <= mejor_real):.2f}")

    if a.salida:
        with open(a.salida, "w", newline="") as fh:
            w = csv.DictWriter(fh, list(filas[0].keys())); w.writeheader(); w.writerows(filas)


if __name__ == "__main__":
    main()
