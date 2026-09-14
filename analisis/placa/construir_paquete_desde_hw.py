#!/usr/bin/env python3
"""Prototipo del "paquete liviano" armado a partir de lo que la FPGA
entregaria por registro (Etapas 4c/5/6 de RedPitaya-FPGA-Release_2025.2),
en vez de la señal cruda + filtro en software.

Simula, con el MISMO modelo de punto fijo ya validado en esa sesion, lo
que el acumulador de HW entregaria por ventana (sum_abs, sum_x2, sum_x4)
y arma con esas sumas el MISMO formato de paquete que ya usa el proyecto
(`exportar_paquete_area.py`/`exportar_paquete_area_c.py`:
{"archivo","fs_hz","ventana_s","canales":[{"canal","t_centro_s","area","kurtosis"}]}) -
para que cualquier consumidor rio abajo del paquete no tenga que cambiar.

Primera vez que se valida de punta a punta: filtro de punto fijo (Etapa
4c, ~0.01-1.2dB de error vs ideal) + aproximacion media=0 del acumulador
(Etapa 5, ~100% coincidencia sola) JUNTAS, contra el paquete que arma hoy
el software 100% real (`area_kurtosis.py`, scipy en punto flotante) para
el mismo archivo real de referencia del proyecto.

PENDIENTE REAL (no resuelto aca): esto sigue sin leer un registro de
verdad - simula el acumulador aplicando la misma cuenta sobre la señal ya
filtrada en Python. Cuando haya placa nueva, el equivalente real es un
programa en C (mismo criterio que medir_polling_ventanas.c) leyendo
`/dev/mem` en vez de este script.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

SAND_MONITORING = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SAND_MONITORING / "analisis"))
sys.path.insert(0, str(SAND_MONITORING / "analisis" / "placa"))
from revisar import _leer_canales_bin, _cargar_info, V_REF  # noqa: E402
from area_kurtosis import (  # noqa: E402
    _filtrar_pasabanda, _rms_muestra_a_muestra, _area_por_ventana,
    _kurtosis_por_ventana, AREA_VENTANA_S,
)

ARCHIVO = SAND_MONITORING / "datos_campo" / "42_1_reposo_20260903_145033_mono_dec32" / "campo_reposo_20260903_145033_0001.bin"
FS = 3_906_250.0
LIMITE_S = 8.0
KURT_UMBRAL = 6.0

FRAC_BITS = 20
SECTIONS_Q = [
    (58743, 117487, 58743, -1311029, 526845),
    (1048576, -2097152, 1048576, -1984139, 943367),
]
ROUND_BIAS = 1 << (FRAC_BITS - 1)


def sat16(v):
    return max(-32768, min(32767, v))


def biquad_section(xs, B0, B1, B2, A1, A2):
    n = len(xs)
    out = np.empty(n, dtype=np.int32)
    x1 = x2 = 0
    y1 = y2 = 0
    xs_list = xs.tolist()
    for i in range(n):
        x0 = xs_list[i]
        acc = B0 * x0 + B1 * x1 + B2 * x2 - A1 * y1 - A2 * y2
        y0 = sat16((acc + ROUND_BIAS) >> FRAC_BITS)
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def cascade_fixed(xs):
    mid = biquad_section(xs, *SECTIONS_Q[0])
    return biquad_section(mid, *SECTIONS_Q[1])


print(f"Leyendo {ARCHIVO} ...")
info = _cargar_info(ARCHIVO)
ch0, ch1, meta = _leer_canales_bin(ARCHIVO)
n_limite = int(LIMITE_S * FS)
ch0 = ch0[:n_limite]
print(f"Usando los primeros {LIMITE_S}s ({len(ch0)} muestras).")

# --- Camino HW simulado: filtro de punto fijo + acumulador media=0 ----
print("Filtrando con el modelo de punto fijo (mismo que el RTL)...")
t0 = time.time()
filtrado_fp = cascade_fixed(ch0.astype(np.int64))
print(f"  listo en {time.time()-t0:.1f}s")

n_ventana = int(FS * AREA_VENTANA_S)
n_total = len(filtrado_fp) // n_ventana
mat = filtrado_fp[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)

sum_abs = np.abs(mat).sum(axis=1)
sum_x2 = (mat ** 2).sum(axis=1)
sum_x4 = (mat ** 4).sum(axis=1)

area_hw = (sum_abs / FS).astype(np.float32)
m2_hw = sum_x2 / n_ventana
m4_hw = sum_x4 / n_ventana
kurt_hw = (m4_hw / np.where(m2_hw > 0, m2_hw ** 2, 1e-30)).astype(np.float32)
t_hw = (np.arange(n_total) + 0.5) * AREA_VENTANA_S

paquete_hw = {
    "archivo": ARCHIVO.name,
    "fs_hz": FS,
    "ventana_s": AREA_VENTANA_S,
    "canales": [{
        "canal": "IN1",
        "t_centro_s": [round(float(v), 6) for v in t_hw],
        "area": [float(v) for v in area_hw],
        "kurtosis": [float(v) for v in kurt_hw],
    }],
}

# --- Camino software real (100% como area_kurtosis.py hoy) ------------
volts = ch0.astype(np.float32) / 32767.0 * V_REF
filtrado_sw = _filtrar_pasabanda(volts, FS)
rms_sw = _rms_muestra_a_muestra(filtrado_sw)
t_sw, area_sw = _area_por_ventana(rms_sw, FS)
_, kurt_sw = _kurtosis_por_ventana(filtrado_sw, FS)

# --- Comparacion end-to-end ---------------------------------------------
n_cmp = min(len(kurt_hw), len(kurt_sw))
clasif_hw = kurt_hw[:n_cmp] >= KURT_UMBRAL
clasif_sw = kurt_sw[:n_cmp] >= KURT_UMBRAL
coincide = clasif_hw == clasif_sw

print(f"\nVentanas comparadas: {n_cmp}")
print(f"Coincidencia de clasificacion (kurtosis>={KURT_UMBRAL}) HW-simulado vs software real: "
      f"{coincide.sum()}/{n_cmp} ({100*coincide.mean():.2f}%)")
if not coincide.all():
    idx = np.where(~coincide)[0][:10]
    for i in idx:
        print(f"  ventana {i}: hw={kurt_hw[i]:.2f} sw={kurt_sw[i]:.2f}")

diff_rel = np.abs(kurt_hw[:n_cmp] - kurt_sw[:n_cmp]) / np.where(kurt_sw[:n_cmp] > 0, kurt_sw[:n_cmp], 1e-30)
print("\nDiferencia relativa de kurtosis (HW-simulado vs software real), percentiles:")
for p in (50, 90, 99, 100):
    print(f"  p{p}: {np.percentile(diff_rel, p)*100:.2f}%")

# --- Tamaño: paquete vs señal cruda -------------------------------------
salida = Path(__file__).parent / "paquete_hw_prueba.json"
with open(salida, "w") as f:
    json.dump(paquete_hw, f)
tam_bin_proporcional_mb = (LIMITE_S / (ch0.size / FS)) * (ARCHIVO.stat().st_size / 1e6) if False else (len(ch0) * 2 / 1e6)
tam_json_kb = salida.stat().st_size / 1024
print(f"\n{LIMITE_S}s de señal cruda (solo estas muestras, int16): {tam_bin_proporcional_mb:.2f} MB")
print(f"Paquete equivalente (este script): {tam_json_kb:.2f} KB")
print(f"Reduccion: {tam_bin_proporcional_mb*1024/tam_json_kb:.0f}x")
