#!/usr/bin/env python3
"""coleccionar_paquete_placa.py — prototipo del "paquete liviano" armado
EN VIVO a partir de los registros de area/kurtosis de la FPGA (Etapas
4c/5/6 de RedPitaya-FPGA-Release_2025.2), en vez de guardar la señal
cruda y correr `exportar_paquete_area(_c).py` despues sobre el .bin.

Arma el MISMO formato de paquete que ya usa el proyecto
(`exportar_paquete_area.py`): {"archivo","fs_hz","ventana_s","canales":
[{"canal","t_centro_s","area","kurtosis"}]} - para que cualquier
consumidor rio abajo (analisis en la PC, subida por Starlink) no tenga
que cambiar. Diferencia real con esos scripts: ESTE no filtra nada ni lee
la señal cruda - solo lee 3 sumas por ventana (ya calculadas en HW) y
hace la division final (kurt = m4/m2²), que es liviana.

Validado de punta a punta (ver sesion 2026-09-14, memoria del proyecto):
combinando el filtro de punto fijo + la aproximacion media=0 del
acumulador, contra el paquete 100% software para el archivo real de
referencia: 95.6% de coincidencia de clasificacion (kurtosis>=6) sobre
160 ventanas de "reposo" - las 7 discrepancias caen justo al filo del
umbral, ninguna en impactos fuertes. Aceptado por el usuario como punto
de partida, revisar con datos reales de la placa nueva mas adelante.

ARQUITECTURA (lo que hay que reemplazar cuando llegue la placa nueva):
  LectorRegistros es la unica pieza que sabe de donde vienen los datos.
  Hoy hay una sola implementacion, LectorRegistrosMock, que REPRODUCE
  (no simula en vivo con timing real) las sumas que darian los registros
  reales, calculadas del archivo real de referencia con el mismo modelo
  de punto fijo ya validado. El reemplazo real (Etapa 7, con la placa
  nueva) es una clase LectorRegistrosHW que lea /dev/mem via mmap en los
  offsets de AREA_WINDOW_COUNT/AREA_SUM_*
  (0x40000000+0x22C..0x40000000+0x248, ver README de
  RedPitaya-FPGA-Release_2025.2) - el resto de este script (deteccion de
  ventana nueva, calculo de area/kurtosis, armado del paquete) no
  necesita cambiar.

Uso (demo, sin placa - reproduce el archivo real de referencia):
  .venv/bin/python3 analisis/placa/coleccionar_paquete_placa.py --demo
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

SAND_MONITORING = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SAND_MONITORING / "analisis"))
sys.path.insert(0, str(SAND_MONITORING / "analisis" / "placa"))
from revisar import _leer_canales_bin, _cargar_info  # noqa: E402
from area_kurtosis import AREA_VENTANA_S  # noqa: E402

KURT_UMBRAL = 6.0
FRAC_BITS = 20
SECTIONS_Q = [
    (58743, 117487, 58743, -1311029, 526845),
    (1048576, -2097152, 1048576, -1984139, 943367),
]
ROUND_BIAS = 1 << (FRAC_BITS - 1)


def _sat16(v):
    return max(-32768, min(32767, v))


def _biquad_section(xs, B0, B1, B2, A1, A2):
    n = len(xs)
    out = np.empty(n, dtype=np.int32)
    x1 = x2 = 0
    y1 = y2 = 0
    xs_list = xs.tolist()
    for i in range(n):
        x0 = xs_list[i]
        acc = B0 * x0 + B1 * x1 + B2 * x2 - A1 * y1 - A2 * y2
        y0 = _sat16((acc + ROUND_BIAS) >> FRAC_BITS)
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def _cascade_fixed(xs):
    mid = _biquad_section(xs, *SECTIONS_Q[0])
    return _biquad_section(mid, *SECTIONS_Q[1])


class LectorRegistros:
    """Interfaz que hay que respetar - ver LectorRegistrosHW (TODO) para
    la implementacion real, cuando exista la placa nueva."""

    def fs_hz(self):
        raise NotImplementedError

    def window_samples(self):
        raise NotImplementedError

    def leer(self):
        """Devuelve (window_count, sum_abs, sum_x2, sum_x4) - el estado
        ACTUAL de los registros, tal como estarian en cualquier momento
        (puede repetir el mismo window_count si todavia no se completo
        una ventana nueva desde la ultima lectura)."""
        raise NotImplementedError


class LectorRegistrosMock(LectorRegistros):
    """Reproduce, ventana por ventana, las sumas que darian los
    registros reales - calculadas UNA vez de punta a punta con el mismo
    modelo de punto fijo validado, no en vivo. Sirve para probar el resto
    del pipeline (deteccion de ventana, armado del paquete) sin la placa.
    """

    def __init__(self, archivo, limite_s=None):
        info = _cargar_info(archivo)
        ch0, ch1, meta = _leer_canales_bin(archivo)
        self._fs = float(info["fs_hz"])
        if limite_s is not None:
            ch0 = ch0[: int(limite_s * self._fs)]

        filtrado = _cascade_fixed(ch0.astype(np.int64))
        self._n_ventana = int(self._fs * AREA_VENTANA_S)
        n_total = len(filtrado) // self._n_ventana
        mat = filtrado[: n_total * self._n_ventana].reshape(n_total, self._n_ventana).astype(np.float64)

        self._sum_abs = np.abs(mat).sum(axis=1)
        self._sum_x2 = (mat ** 2).sum(axis=1)
        self._sum_x4 = (mat ** 4).sum(axis=1)
        self._n_total = n_total
        self._idx_actual = 0  # proxima ventana a "completar"

    def fs_hz(self):
        return self._fs

    def window_samples(self):
        return self._n_ventana

    def avanzar_una_ventana(self):
        """Solo en el mock: simula que paso el tiempo de una ventana
        mas y el HW la termino - en la placa real esto lo hace el reloj
        del ADC, no hace falta llamarlo a mano."""
        if self._idx_actual < self._n_total:
            self._idx_actual += 1

    def leer(self):
        i = self._idx_actual - 1 if self._idx_actual > 0 else 0
        if self._idx_actual == 0:
            return 0, 0, 0, 0
        return self._idx_actual, int(self._sum_abs[i]), int(self._sum_x2[i]), int(self._sum_x4[i])

    def hay_mas(self):
        return self._idx_actual < self._n_total


def _area_kurtosis_de_suma(sum_abs, sum_x2, sum_x4, n, fs):
    """Misma formula que _area_por_ventana/_kurtosis_por_ventana de
    area_kurtosis.py, pero partiendo de las SUMAS (lo que da el
    registro) en vez de la señal completa - la unica cuenta que hace
    falta del lado del host."""
    area = sum_abs / fs
    m2 = sum_x2 / n
    m4 = sum_x4 / n
    kurt = m4 / (m2 * m2) if m2 > 0 else m4 / 1e-30
    return area, kurt


def coleccionar(lector: LectorRegistros, archivo_nombre, callback_avance=None):
    """Recorre las ventanas que entrega `lector` (una por una, en orden -
    la deteccion de "ventana nueva" vs. confiabilidad del polling en
    tiempo real es un problema APARTE, ya medido por separado en
    medir_polling_ventanas.c) y arma el paquete. Se corta cuando el
    lector avisa que no hay mas ventanas (`hay_mas()`) - en la placa
    real, en cambio, esto correria hasta juntar un chunk (ej. 30s) o
    hasta que se lo corte externamente, no "hasta que se acaben los
    datos"."""
    fs = lector.fs_hz()
    n = lector.window_samples()

    t_centro_s, area_lista, kurt_lista = [], [], []
    ultimo_wc = 0
    idx_ventana = 0

    while True:
        if callback_avance is not None:
            callback_avance(lector)  # solo el mock necesita esto (simular el paso del tiempo)

        wc, sum_abs, sum_x2, sum_x4 = lector.leer()
        if wc != ultimo_wc:
            area, kurt = _area_kurtosis_de_suma(sum_abs, sum_x2, sum_x4, n, fs)
            t_centro_s.append(round((idx_ventana + 0.5) * AREA_VENTANA_S, 6))
            area_lista.append(float(area))
            kurt_lista.append(float(kurt))
            idx_ventana += 1
            ultimo_wc = wc

        if isinstance(lector, LectorRegistrosMock) and not lector.hay_mas() and wc == ultimo_wc:
            break

    return {
        "archivo": archivo_nombre,
        "fs_hz": fs,
        "ventana_s": AREA_VENTANA_S,
        "canales": [{
            "canal": "IN1",
            "t_centro_s": t_centro_s,
            "area": area_lista,
            "kurtosis": kurt_lista,
        }],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true",
                     help="corre contra el archivo real de referencia del proyecto (sin placa)")
    ap.add_argument("--limite-s", type=float, default=8.0,
                     help="segundos del archivo de referencia a usar en --demo (default 8.0)")
    ap.add_argument("-o", "--salida", type=Path, default=Path("paquete_placa_demo.json"))
    args = ap.parse_args()

    if not args.demo:
        print("Sin --demo no hay de donde leer todavia (LectorRegistrosHW no existe hasta"
              " que llegue la placa nueva - ver docstring del script).", file=sys.stderr)
        sys.exit(1)

    archivo = (SAND_MONITORING / "datos_campo" / "42_1_reposo_20260903_145033_mono_dec32"
               / "campo_reposo_20260903_145033_0001.bin")
    print(f"Modo demo: reproduciendo {archivo.name} ({args.limite_s}s) como si vinieran de la FPGA...")
    lector = LectorRegistrosMock(archivo, limite_s=args.limite_s)

    def avanzar(lector):
        lector.avanzar_una_ventana()

    paquete = coleccionar(lector, archivo.name, callback_avance=avanzar)

    with open(args.salida, "w") as f:
        json.dump(paquete, f)

    n_ventanas = len(paquete["canales"][0]["area"])
    clasif = [k >= KURT_UMBRAL for k in paquete["canales"][0]["kurtosis"]]
    print(f"[OK] {args.salida}: {n_ventanas} ventanas, {sum(clasif)} sobre el umbral (kurtosis>={KURT_UMBRAL})")
    print(f"     tamaño del paquete: {args.salida.stat().st_size/1024:.2f} KB")


if __name__ == "__main__":
    main()
