#!/usr/bin/env python3
"""Forma de banda del pasabanda de la FPGA con tonos por OUT1 (T de OUT1 a
IN1 + IN2; Etapa 5 de docs/plan_in2_independiente.md).

  tonos_banda.py generar SALIDA.bin   -> int16 LE a 3906250 Hz para
      capturar_eventos --prueba-archivo SALIDA.bin --dac-escala 1 --dac-rate 3906250
  tonos_banda.py analizar DESTINO DEC -> |H| medido (IN1, IN2) vs diseño

Secuencia (después del 0.5 s de silencio que agrega GeneradorArchivo):
marcador 150 kHz 1.0 s, silencio 0.5 s y, por cada frecuencia, tono 0.4 s +
silencio 0.2 s. Una senoide tiene kurtosis 1.5: no dispara eventos.

El área de la FPGA es la suma de |x| filtrada por ventana, proporcional a la
amplitud: área(f) / área(150 kHz) = |H(f)| / |H(150 kHz)|.

El análisis separa por MESETAS (ventanas sobre 2.5x el piso), no por una
grilla fija: el DAC por red no respeta el tiempo exacto y tiene cortes
(visto 2026-10-16). Se toma la mediana del interior de cada meseta.
"""
import csv, glob, os, sys
import numpy as np
from scipy.signal import butter, sosfreqz

RATE = 3_906_250
AMP = 12000          # cuentas DAC (~0.37 del fondo de escala; entra en LV)
FREQS = [5e3, 10e3, 20e3, 30e3, 40e3, 50e3, 70e3, 100e3, 150e3, 200e3, 250e3,
         300e3, 350e3, 400e3, 450e3, 500e3, 600e3, 700e3, 800e3, 900e3]
MARCA_S, POST_MARCA_S, TONO_S, SIL_S = 1.0, 0.5, 0.4, 0.2


def tono(f, dur):
    n = int(round(dur * RATE))
    x = AMP * np.sin(2 * np.pi * f * np.arange(n) / RATE)
    r = min(n // 2, int(0.002 * RATE))      # rampa 2 ms, sin escalón
    w = np.ones(n); w[:r] = np.linspace(0, 1, r); w[-r:] = np.linspace(1, 0, r)
    return x * w


def generar(ruta):
    sil = lambda d: np.zeros(int(round(d * RATE)))
    partes = [tono(150e3, MARCA_S), sil(POST_MARCA_S)]
    for f in FREQS:
        partes += [tono(f, TONO_S), sil(SIL_S)]
    x = np.concatenate(partes).round().astype("<i2")
    x.tofile(ruta)
    print(f"{ruta}: {len(x)} muestras, {len(x)/RATE:.2f} s, {x.nbytes/1e6:.1f} MB")


def leer(carpeta):
    filas = {}
    for ruta in sorted(glob.glob(os.path.join(carpeta, "ventanas_*.csv"))):
        for r in csv.DictReader(open(ruta)):
            if r["estado"] == "ok" and r["area"] not in ("", "nan"):
                filas[int(r["window_count"])] = float(r["area"])
    return filas


def teorico(fs, freqs):
    # mismo diseño que generar_etapa4c.py / generar_coefs_dec64.py (fpga_pitaya):
    # Butterworth orden 2, 50-400 kHz, coeficientes cuantizados Q20
    sos = butter(2, [50e3 / (fs / 2), 400e3 / (fs / 2)], btype="bandpass", output="sos")
    sos = sos / sos[:, [3]]
    sos = np.round(sos * (1 << 20)) / (1 << 20)
    _, h = sosfreqz(sos, worN=np.asarray(freqs), fs=fs)
    return np.abs(h)


def mesetas(v):
    piso = np.nanmedian(v[-40:])            # cola de la corrida: silencio
    alto = v > 2.5 * piso
    runs, i = [], 0
    while i < len(v):
        if alto[i]:
            j = i
            while j + 1 < len(v) and alto[j + 1]:
                j += 1
            if j - i + 1 >= 4:
                runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return piso, runs


def analizar(dest, dec):
    fs = 125e6 / dec
    a = {"IN1": leer(dest), "IN2": leer(os.path.join(dest, "in2"))}
    wcs = range(min(a["IN1"]), max(a["IN1"]) + 1)
    serie = {c: np.array([a[c].get(w, np.nan) for w in wcs]) for c in a}
    piso, runs = mesetas(serie["IN1"])
    print(f"dec{dec}: {len(runs)} mesetas en IN1 (esperadas {len(FREQS) + 1} = marcador + tonos), piso IN1 {piso:.3f}")
    if len(runs) < len(FREQS) + 1:
        sys.exit("faltan mesetas: revisar la serie a mano")
    runs = runs[:len(FREQS) + 1]
    med = {c: np.array([np.nanmedian(serie[c][i + 1:j]) for i, j in runs[1:]]) for c in a}
    F = np.array(FREQS)
    ref = FREQS.index(150e3)
    db = lambda x: 20 * np.log10(x / x[ref])
    t, m1, m2 = db(teorico(fs, F)), db(med["IN1"]), db(med["IN2"])
    print("  f_kHz  diseño_dB |  IN1_dB  IN2_dB | IN1-diseño  IN2/IN1  ventanas")
    for k, f in enumerate(F):
        i, j = runs[k + 1]
        print(f"  {f/1e3:5.0f}  {t[k]:8.2f}  | {m1[k]:7.2f} {m2[k]:7.2f} |   {m1[k]-t[k]:+6.2f}    "
              f"{med['IN2'][k]/med['IN1'][k]:.3f}    {j-i+1}")
    b = (F >= 50e3) & (F <= 400e3)
    print(f"  50-400 kHz: IN1-diseño media {np.mean(m1[b]-t[b]):+.2f} dB, máx |{np.max(np.abs(m1[b]-t[b])):.2f}| dB; "
          f"IN2-IN1 máx |{np.max(np.abs(m2[b]-m1[b])):.2f}| dB")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("generar", "analizar"):
        sys.exit(__doc__)
    if sys.argv[1] == "generar":
        generar(sys.argv[2])
    else:
        analizar(sys.argv[2], int(sys.argv[3]))
