#!/usr/bin/env python3
"""Etapa 5 de docs/plan_in2_independiente.md (T de OUT1 a IN1+IN2): compara IN1 vs IN2 ventana por ventana.

Uso: comparar_in1_in2.py DESTINO [--umbral 3.4]
  DESTINO = carpeta de capturar_eventos (ventanas_*.csv del IN1, in2/ventanas_*.csv del IN2).
Cruza por window_count. Reporta: ventanas en comun, razon de area IN2/IN1,
diferencia de kurtosis, y ventanas sobre el umbral en cada canal (coinciden o no).
"""
import csv, glob, os, statistics as st, sys


def leer(carpeta):
    filas = {}
    for ruta in sorted(glob.glob(os.path.join(carpeta, "ventanas_*.csv"))):
        with open(ruta) as f:
            for r in csv.DictReader(f):
                if r.get("estado") != "ok" or r.get("area") in (None, "", "nan"):
                    continue
                filas[int(r["window_count"])] = (float(r["area"]), float(r["kurtosis"]))
    return filas


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p / 100 * len(v)))]


def main():
    dest = sys.argv[1]
    umbral = float(sys.argv[sys.argv.index("--umbral") + 1]) if "--umbral" in sys.argv else 3.4
    a, b = leer(dest), leer(os.path.join(dest, "in2"))
    comun = sorted(set(a) & set(b))
    print(f"IN1 {len(a)} ventanas ok, IN2 {len(b)}, en comun {len(comun)}")
    if not comun:
        return
    razon = [b[w][0] / a[w][0] for w in comun if a[w][0] > 0]
    dk = [b[w][1] - a[w][1] for w in comun]
    print(f"area IN2/IN1: mediana {st.median(razon):.4f}  p10 {pct(razon,10):.4f}  p90 {pct(razon,90):.4f}")
    print(f"kurt IN2-IN1: mediana {st.median(dk):+.3f}  p10 {pct(dk,10):+.3f}  p90 {pct(dk,90):+.3f}")
    print(f"kurt IN1: mediana {st.median(a[w][1] for w in comun):.3f}  max {max(a[w][1] for w in comun):.2f}")
    print(f"kurt IN2: mediana {st.median(b[w][1] for w in comun):.3f}  max {max(b[w][1] for w in comun):.2f}")
    s1 = {w for w in comun if a[w][1] >= umbral}
    s2 = {w for w in comun if b[w][1] >= umbral}
    print(f"sobre umbral {umbral}: IN1 {len(s1)}, IN2 {len(s2)}, ambos {len(s1 & s2)}, "
          f"solo IN1 {len(s1 - s2)}, solo IN2 {len(s2 - s1)}")
    for w in sorted(s1 | s2):
        marca = "ambos" if w in s1 and w in s2 else ("solo IN1" if w in s1 else "solo IN2")
        print(f"  wc {w}: IN1 kurt {a[w][1]:7.2f} area {a[w][0]:10.1f} | "
              f"IN2 kurt {b[w][1]:7.2f} area {b[w][0]:10.1f}  {marca}")


if __name__ == "__main__":
    main()
