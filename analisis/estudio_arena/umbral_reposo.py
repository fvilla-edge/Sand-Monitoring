#!/usr/bin/env python3
"""
umbral_reposo.py — frente "umbral minimo" del plan (docs/plan_modelo_arena.md sec.7.1).

1. Reposo: distribucion de la kurtosis en las horas mas tranquilas (menor p99.9).
2. Para cada umbral: ventanas/h sobre el umbral en reposo (piso), en los episodios
   conocidos y en el resto; contraste episodio/piso.
3. Actividad sostenida: minutos cuya MEDIANA de kurtosis supera MEDIANA_ACTIVA
   (toda la distribucion corrida, no solo la cola), por intervalo entre purgas,
   con el factor kg/minuto ajustado en los intervalos completos y la estimacion
   del intervalo abierto.

Uso:
    .venv/bin/python analisis/estudio_arena/umbral_reposo.py PLANILLA.csv CARPETA_CSV [...]
"""
import argparse, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_purgas as mp

UMBRALES = [3.03, 3.05, 3.08, 3.1, 3.15, 3.2, 3.3, 3.5, 4.0, 5.0]
MEDIANA_ACTIVA = 2.978          # ~ reposo (2.973-2.975) + 0.004; fijado 2026-10-02
N_TRANQUILAS = 20
# episodios con loma identificados en la Etapa C (hora local)
EPISODIOS = [(datetime(2026, 9, 29, 15), 2), (datetime(2026, 10, 1, 5), 3)]
COB_MIN = 0.8


def mediana_por_minuto(T, K):
    mi = (T // 60).astype(np.int64)
    u, inv = np.unique(mi, return_inverse=True)
    o = np.argsort(inv, kind="stable"); c = np.cumsum(np.bincount(inv))[:-1]
    return u, np.array([np.median(x) for x in np.split(K[o], c)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilla"); ap.add_argument("carpetas", nargs="+")
    a = ap.parse_args()
    loc = timezone(timedelta(hours=mp.HUSO_PLANILLA_H))
    _, purgas = mp.leer_planilla(a.planilla)
    T, _, K = mp.leer_ventanas(a.carpetas)

    h = (T // 3600).astype(np.int64)
    u, inv = np.unique(h, return_inverse=True)
    ok = [i for i in range(len(u)) if np.sum(inv == i) >= 36000]
    p999 = np.array([np.percentile(K[inv == i], 99.9) for i in ok])
    quietas = [ok[j] for j in np.argsort(p999)[:N_TRANQUILAS]]
    kq = np.concatenate([K[inv == i] for i in quietas])
    print(f"Reposo ({N_TRANQUILAS} horas mas tranquilas, {len(kq)} ventanas): mediana {np.median(kq):.4f}, "
          f"p1 {np.percentile(kq, 1):.4f}, p99 {np.percentile(kq, 99):.4f}, "
          f"dispersion ~{(np.percentile(kq, 99) - np.percentile(kq, 1)) / 4.65:.4f}")

    def en_episodio(x):
        t = datetime.fromtimestamp(x * 3600, loc).replace(tzinfo=None)
        return any(t0 <= t < t0 + timedelta(hours=n) for t0, n in EPISODIOS)
    ep = [i for i in ok if en_episodio(u[i])]
    resto = [i for i in ok if i not in ep]
    print(f"\n{'umbral':>6s} {'piso/h':>7s} {'episodio/h':>10s} {'resto/h':>8s} {'contraste':>9s}")
    for t in UMBRALES:
        r = lambda S: np.median([np.mean(K[inv == i] > t) * 72000 for i in S])
        p, e, s = r(quietas), r(ep), r(resto)
        print(f"{t:6.2f} {p:7.1f} {e:10.1f} {s:8.1f} {e / max(p, 0.5):9.1f}")

    um, med = mediana_por_minuto(T, K)
    activo = med > MEDIANA_ACTIVA
    pts = purgas + [(datetime.fromtimestamp(T[-1], timezone.utc), None, "")]
    X, Y, filas = [], [], []
    for (t0, _, _), (t1, kg, _) in zip(pts, pts[1:]):
        m = (um * 60 >= t0.timestamp()) & (um * 60 < t1.timestamp())
        if not m.any():
            continue
        minutos = (t1 - t0).total_seconds() / 60
        n = activo[m].sum() * minutos / m.sum()       # extrapolado a los minutos sin dato
        completo = m.sum() / minutos >= COB_MIN
        filas.append((t0, t1, kg, n, m.sum(), completo))
        if kg is not None and completo:
            X.append(n); Y.append(kg)
    X, Y = np.array(X), np.array(Y)
    f = (Y @ X) / (X @ X)
    print(f"\nActividad sostenida (minutos con mediana k > {MEDIANA_ACTIVA}); factor {f:.3f} kg/minuto con {len(X)} intervalos completos:")
    for t0, t1, kg, n, nm, comp in filas:
        print(f"  {t0.astimezone(loc):%d/%m %H:%M} -> {t1.astimezone(loc):%d/%m %H:%M}  "
              f"real {'abierto' if kg is None else f'{kg:g} kg':>8s}  minutos activos {n:5.0f}  -> {f * n:5.1f} kg"
              f"{'' if comp else '  (parcial)'}")


if __name__ == "__main__":
    main()
