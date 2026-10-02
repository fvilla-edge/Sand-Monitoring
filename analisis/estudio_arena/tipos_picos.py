#!/usr/bin/env python3
"""
tipos_picos.py — Etapa C del plan (docs/plan_modelo_arena.md): agrupar los picos
del sensor en tipos SIN usar los kg, para ver si hay picos de distinto origen
(arena vs actividad del pad, maniobras, control de separador...).

1. Rafaga = grupo de ventanas de 50 ms con kurtosis > KURT_UMBRAL separadas por
   menos de GAP_S segundos.
2. Forma de cada rafaga (lo unico que entra al agrupamiento):
     log(ventanas), log(duracion), log(kurtosis max - 3), exceso de area max,
     exceso de area medio en +-CTX_S s alrededor ("loma" de fondo).
3. Mezcla gaussiana con k = 1..KMAX grupos, se elige k por BIC.
4. Contexto de cada grupo (NO entra al agrupamiento, sirve para interpretarlo):
   hora local, dia (08-16 local) / noche, BPO-2072 en control de separador
   (planilla), Starlink encendido, intervalo entre purgas y sus kg.

Uso:
    .venv/bin/python analisis/estudio_arena/tipos_picos.py PLANILLA.csv CARPETA_CSV [...] [--salida rafagas.csv]
"""
import argparse, csv, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_purgas as mp

KURT_UMBRAL = 3.5
GAP_S = 1.0
CTX_S = 60.0
KMAX = 6
SEMILLA = 0
RELE_ON_UTC = (11 * 60 + 55, 20 * 60 + 15)   # horario de Starlink encendido (minutos UTC)


def rafagas(T, A, K, ex):
    idx = np.flatnonzero(K > KURT_UMBRAL)
    if len(idx) == 0:
        return []
    cortes = np.flatnonzero(np.diff(T[idx]) > GAP_S) + 1
    out = []
    for g in np.split(idx, cortes):
        t0, t1 = T[g[0]], T[g[-1]]
        c = (T >= t0 - CTX_S) & (T <= t1 + CTX_S)
        out.append(dict(t0=t0, t1=t1, ventanas=len(g), duracion_s=t1 - t0 + 0.05,
                        kurt_max=float(K[g].max()), suma_k3=float((K[g] - 3).sum()),
                        exc_max=float(ex[g].max()), exc_ctx=float(np.median(ex[c]))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilla"); ap.add_argument("carpetas", nargs="+"); ap.add_argument("--salida")
    a = ap.parse_args()
    loc = timezone(timedelta(hours=mp.HUSO_PLANILLA_H))

    datos, purgas = mp.leer_planilla(a.planilla)
    control = {}                                  # hora local (redondeada) -> BPO-2072 en control
    for t, d in datos:
        control[t.replace(minute=0)] = bool(d["liq"] > 0)
    T, A, K = mp.leer_ventanas(a.carpetas)
    ex = A - mp.base_area(T, A)
    R = rafagas(T, A, K, ex)
    horas_dato = np.unique((T // 3600).astype(np.int64))
    print(f"{len(R)} rafagas (k>{KURT_UMBRAL}, gap {GAP_S}s) en {len(horas_dato)} horas con dato")

    X = np.array([[np.log(r["ventanas"]), np.log(r["duracion_s"]), np.log(r["kurt_max"] - 3),
                   r["exc_max"], r["exc_ctx"]] for r in R])
    Z = StandardScaler().fit_transform(X)
    modelos = [GaussianMixture(k, covariance_type="full", random_state=SEMILLA, n_init=5).fit(Z) for k in range(1, KMAX + 1)]
    bic = [m.bic(Z) for m in modelos]
    print("BIC por k:", "  ".join(f"k={k}:{b:.0f}" for k, b in enumerate(bic, 1)))
    gm = modelos[int(np.argmin(bic))]
    et = gm.predict(Z)
    # ordenar grupos por kurtosis max mediana (0 = los mas suaves)
    orden = np.argsort([np.median(X[et == g, 2]) if np.any(et == g) else 0 for g in range(gm.n_components)])
    renombre = {g: i for i, g in enumerate(orden)}
    et = np.array([renombre[g] for g in et])

    pts = purgas + [(datetime.fromtimestamp(T[-1], timezone.utc), None, "")]
    for r, g in zip(R, et):
        tl = datetime.fromtimestamp(r["t0"], loc)
        tu = datetime.fromtimestamp(r["t0"], timezone.utc)
        mu = tu.hour * 60 + tu.minute
        r.update(grupo=int(g), hora_local=tl.hour, dia=8 <= tl.hour < 16,
                 control=control.get(tl.replace(minute=0, second=0, microsecond=0), None),
                 starlink=RELE_ON_UTC[0] <= mu < RELE_ON_UTC[1], inicio_local=tl.strftime("%d/%m %H:%M:%S"))
        r["intervalo"] = next((f"{p0.astimezone(loc):%d/%m %H}->{p1.astimezone(loc):%d/%m %H}" for (p0, _, _), (p1, _, _) in zip(pts, pts[1:])
                               if p0.timestamp() <= r["t0"] < p1.timestamp()), "")

    # horas de cada contexto (para pasar de cantidad a tasa)
    def frac(cond):
        hs = [datetime.fromtimestamp(h * 3600, loc) for h in horas_dato]
        return sum(1 for h in hs if cond(h))
    h_dia = frac(lambda h: 8 <= h.hour < 16); h_noche = len(horas_dato) - h_dia
    h_ctrl = frac(lambda h: control.get(h.replace(minute=0, second=0, microsecond=0)) is True)
    h_noctrl = len(horas_dato) - h_ctrl
    print(f"Horas con dato: dia(08-16) {h_dia}, resto {h_noche}; BPO-2072 en control {h_ctrl}, fuera {h_noctrl}\n")

    print(f"{'grupo':5s} {'n':>4s} {'ventanas':>8s} {'dur s':>6s} {'kmax':>6s} {'exc max':>8s} {'loma':>7s} | "
          f"{'/h dia':>6s} {'/h resto':>8s} {'/h ctrl':>7s} {'/h fuera':>8s}")
    for g in range(gm.n_components):
        S = [r for r in R if r["grupo"] == g]
        if not S:
            continue
        med = lambda k: np.median([r[k] for r in S])
        nd = sum(r["dia"] for r in S); nc = sum(r["control"] is True for r in S)
        print(f"{g:5d} {len(S):4d} {med('ventanas'):8.0f} {med('duracion_s'):6.2f} {med('kurt_max'):6.1f} "
              f"{med('exc_max'):8.4f} {med('exc_ctx'):+7.4f} | {nd / h_dia:6.2f} {(len(S) - nd) / h_noche:8.2f} "
              f"{nc / max(h_ctrl, 1):7.2f} {(len(S) - nc) / max(h_noctrl, 1):8.2f}")

    print("\nRafagas por grupo en cada intervalo entre purgas:")
    ints = sorted({r["intervalo"] for r in R if r["intervalo"]}, key=lambda s: datetime.strptime(s[:8], "%d/%m %H"))
    kg = {f"{p0.astimezone(loc):%d/%m %H}->{p1.astimezone(loc):%d/%m %H}": k for (p0, _, _), (p1, k, _) in zip(pts, pts[1:])}
    print(f"  {'intervalo':18s} {'kg':>5s}  " + "  ".join(f"g{g}" for g in range(gm.n_components)))
    for i in ints:
        c = [sum(1 for r in R if r["intervalo"] == i and r["grupo"] == g) for g in range(gm.n_components)]
        print(f"  {i:18s} {'' if kg.get(i) is None else kg[i]:>5}  " + "  ".join(f"{x:2d}" for x in c))

    if a.salida:
        cols = ["inicio_local", "grupo", "ventanas", "duracion_s", "kurt_max", "suma_k3", "exc_max", "exc_ctx",
                "hora_local", "dia", "control", "starlink", "intervalo"]
        with open(a.salida, "w", newline="") as fh:
            w = csv.DictWriter(fh, cols, extrasaction="ignore"); w.writeheader(); w.writerows(R)


if __name__ == "__main__":
    main()
