#!/usr/bin/env python3
"""
nivel_arena.py — indicador cualitativo de arena por hora: poca / media / mucha.

Cuenta por hora las ventanas de 50 ms con kurtosis > KURT_UMBRAL (la metrica M1
de docs/estudio_arena_vs_kg.md, que fue la mejor contra los kg de las purgas
desde el 29/9) y la clasifica con cortes fijos. Los cortes salen del factor
de la sec.9 (0.039 kg por ventana): 15 ventanas/h ~ 0.6 kg/h, 80 ventanas/h ~ 3 kg/h.
PROVISORIOS (sec.10 del doc): no hay todavia ningun intervalo de "mucha" arena
con datos continuos para validarlos.

Si se pasa la planilla, ademas resume los niveles por intervalo entre purgas.

Uso:
    .venv/bin/python analisis/estudio_arena/nivel_arena.py CARPETA_CSV [...] [--planilla PLANILLA.csv]
"""
import argparse, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_purgas as mp

KURT_UMBRAL = 3.5
CORTE_MEDIA = 15        # ventanas > umbral por hora
CORTE_MUCHA = 80
KG_POR_VENTANA = 0.039  # sec.9.4, solo orientativo
MIN_VENTANAS_HORA = 36000   # media hora con dato; si no, "sin dato"
SIMBOLO = {"poca": ".", "media": "m", "mucha": "M", "sin dato": " "}


def nivel(x):
    if np.isnan(x):
        return "sin dato"
    return "poca" if x < CORTE_MEDIA else "media" if x < CORTE_MUCHA else "mucha"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpetas", nargs="+"); ap.add_argument("--planilla")
    a = ap.parse_args()
    loc = timezone(timedelta(hours=mp.HUSO_PLANILLA_H))

    T, _, K = mp.leer_ventanas(a.carpetas)
    hora = (T // 3600).astype(np.int64)
    u, inv = np.unique(hora, return_inverse=True)
    n = np.bincount(inv)
    tasa = np.where(n >= MIN_VENTANAS_HORA, np.bincount(inv, weights=K > KURT_UMBRAL) / np.maximum(n, 1) * 72000, np.nan)
    niveles = [nivel(x) for x in tasa]

    print(f"Nivel de arena por hora (hora local UTC{mp.HUSO_PLANILLA_H:+d}); "
          f"ventanas k>{KURT_UMBRAL}/h: poca <{CORTE_MEDIA}, media <{CORTE_MUCHA}, mucha >={CORTE_MUCHA}")
    print("Linea por dia, un caracter por hora desde las 00:  . poca   m media   M mucha   (blanco) sin dato")
    dia = None; linea = ""
    for x, lv in zip(u, niveles):
        t = datetime.fromtimestamp(x * 3600, loc)
        if t.date() != dia:
            if dia: print(f"  {dia:%d/%m} {linea}")
            dia, linea = t.date(), " " * t.hour
        linea += SIMBOLO[lv]
    print(f"  {dia:%d/%m} {linea}")

    print("\nHoras con nivel media o mucha:")
    for x, v, lv in zip(u, tasa, niveles):
        if lv in ("media", "mucha"):
            print(f"  {datetime.fromtimestamp(x * 3600, loc):%d/%m %H}h  {lv:5s}  {v:5.0f} ventanas  (~{v * KG_POR_VENTANA:.1f} kg)")

    if a.planilla:
        _, purgas = mp.leer_planilla(a.planilla)
        pts = [p for p in purgas if p[0].timestamp() > u[0] * 3600 - 24 * 3600]
        pts.append((datetime.fromtimestamp(T[-1], timezone.utc), None, ""))
        print("\nPor intervalo entre purgas:")
        for (t0, _, _), (t1, kg, _) in zip(pts, pts[1:]):
            m = (u * 3600 >= t0.timestamp()) & (u * 3600 < t1.timestamp())
            if not m.any():
                continue
            lv = [l for l, s in zip(niveles, m) if s]
            mk = (T >= t0.timestamp()) & (T < t1.timestamp())
            est = KG_POR_VENTANA * np.sum(K[mk] > KURT_UMBRAL) * ((t1 - t0).total_seconds() / 3600) / (mk.sum() * 0.05 / 3600)
            print(f"  {t0.astimezone(loc):%d/%m %H:%M} -> {t1.astimezone(loc):%d/%m %H:%M}  "
                  f"real {'abierto' if kg is None else f'{kg:g} kg':>8s}  estimado ~{est:4.1f} kg  "
                  + "  ".join(f"{k}={lv.count(k)}" for k in ("poca", "media", "mucha", "sin dato")))


if __name__ == "__main__":
    main()
