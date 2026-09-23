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

ARQUITECTURA:
  LectorRegistros es la unica pieza que sabe de donde vienen los datos.
  LectorRegistrosMock REPRODUCE (no simula en vivo con timing real) las
  sumas que darian los registros reales, calculadas de un archivo real
  de referencia - sirve para probar el resto del pipeline sin placa.
  LectorRegistrosHW (Etapa 7/8, 2026-09-22) lee los registros REALES via
  mmap de /dev/mem en los offsets de AREA_WINDOW_COUNT/AREA_SUM_*
  (0x40000000+0x32C..0x348 en el bitstream portado a Release_2026.1,
  0x22C..0x248 en el etapa7 viejo de Release_2025.2 — se detecta solo,
  ver LectorRegistrosHW._detectar_bloque; offsets en scope_cfg.sv del
  repo FPGA, la .rst del repo esta desactualizada) - corre EN la placa
  con un bitstream con el acumulador cargado. El resto del script (deteccion de ventana
  nueva, calculo de area/kurtosis, armado del paquete) es el mismo para
  los dos lectores.

Coeficientes del pasabanda por decimacion (sec.177 de la memoria del
proyecto): el filtro real de la FPGA tiene coeficientes fijos calculados
para un fs concreto (limitacion documentada en RedPitaya-FPGA-Release_2025.2/README.md).
`LectorRegistrosMock` elige el juego correcto (`SECTIONS_Q_POR_DECIMACION`)
segun el campo `decimacion` del `session_info.json` de cada archivo -
antes solo soportaba dec32 (hardcodeado), ahora tambien dec64, validado
con datos reales contra el software (0.1-0.5% de diferencia de kurtosis,
igual que el juego de dec32). Un archivo con una decimacion sin
coeficientes validados levanta un error explicito en vez de asumir uno
existente y reproducir el corrimiento de banda en silencio.

Uso (demo, sin placa - reproduce el archivo real de referencia):
  .venv/bin/python3 analisis/placa/coleccionar_paquete_placa.py --demo
  .venv/bin/python3 analisis/placa/coleccionar_paquete_placa.py --demo --archivo otro_archivo.bin
"""
import argparse
import json
import mmap
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

SAND_MONITORING = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SAND_MONITORING / "analisis"))
sys.path.insert(0, str(SAND_MONITORING / "analisis" / "placa"))
from revisar import _leer_canales_bin, _cargar_info  # noqa: E402
from area_kurtosis import AREA_VENTANA_S  # noqa: E402

KURT_UMBRAL = 6.0
FRAC_BITS = 20
# Coeficientes del pasabanda REAL de la FPGA (Etapa 4c/6 de
# RedPitaya-FPGA-Release_2025.2), uno por decimacion soportada - el
# filtro real usa coeficientes fijos calculados para un fs concreto
# (limitacion documentada en el README de ese repo: con dec32 corridos a
# dec64, o viceversa, el filtro queda corrido de banda). El de dec64 se
# calculo y valido con datos reales en sec.177 de la memoria del
# proyecto (generar_coefs_dec64.py) - mismo metodo, distinto FS.
SECTIONS_Q_POR_DECIMACION = {
    32: [
        (58743, 117487, 58743, -1311029, 526845),
        (1048576, -2097152, 1048576, -1984139, 943367),
    ],
    64: [
        (182309, 364619, 182309, -480688, 286917),
        (1048576, -2097152, 1048576, -1865486, 846090),
    ],
}
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


def _cascade_fixed(xs, sections_q):
    mid = _biquad_section(xs, *sections_q[0])
    return _biquad_section(mid, *sections_q[1])


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
        self._fs = float(info.get("fs_hz", info.get("fs_hz_por_canal")))
        if limite_s is not None:
            ch0 = ch0[: int(limite_s * self._fs)]

        decimacion = info.get("decimacion")
        if decimacion not in SECTIONS_Q_POR_DECIMACION:
            raise ValueError(
                f"{archivo}: decimacion {decimacion!r} sin coeficientes de pasabanda "
                f"validados (solo hay para {sorted(SECTIONS_Q_POR_DECIMACION)}) - "
                "calcular y validar un juego nuevo antes de usar este archivo "
                "(ver generar_coefs_dec64.py en RedPitaya-FPGA-Release_2025.2 como referencia), "
                "no asumir uno existente para no reproducir el corrimiento de banda conocido.")
        sections_q = SECTIONS_Q_POR_DECIMACION[decimacion]

        filtrado = _cascade_fixed(ch0.astype(np.int64), sections_q)
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


class LectorRegistrosHW(LectorRegistros):
    """Lee los registros REALES de area/kurtosis via mmap de /dev/mem
    (Etapa 7/8 de RedPitaya-FPGA-Release_2025.2). Offsets confirmados en
    prj/stream_app/ip/rp_oscilloscope/scope_cfg.sv (la .rst del repo esta
    desactualizada, no la documenta - no seguirla). El acumulador corre
    en el FPGA de forma continua mientras el bitstream este cargado, no
    depende de que haya una sesion de capturar_stream.py activa - por
    eso `AREA_WINDOW_COUNT` puede arrancar en cualquier valor, no en 0."""

    _REG_BASE = 0x40000000
    _MAP_SIZE = 0x1000  # cubre de sobra hasta 0x248

    # offsets del etapa7 viejo; el port a Release_2026.1 los tiene +0x100
    # (2026.1 ocupo 0x200-0x214 con registros de timestamp)
    _OFF_WINDOW_SAMPLES = 0x228
    _OFF_WINDOW_COUNT = 0x22C
    _OFF_SUM_ABS_LO = 0x230
    _OFF_SUM_ABS_HI = 0x234
    _OFF_SUM_X2_LO = 0x238
    _OFF_SUM_X2_HI = 0x23C
    _OFF_SUM_X4_LO = 0x240
    _OFF_SUM_X4_MID = 0x244
    _OFF_SUM_X4_HI = 0x248

    def __init__(self, fs_hz, window_samples, duracion_s=None):
        self._fs = float(fs_hz)
        self._n_ventana = int(window_samples)
        self._duracion_s = duracion_s
        self._t_inicio = time.monotonic()

        fd = os.open("/dev/mem", os.O_RDONLY)
        try:
            self._mm = mmap.mmap(fd, self._MAP_SIZE, mmap.MAP_SHARED, mmap.PROT_READ,
                                  offset=self._REG_BASE)
        finally:
            os.close(fd)
        self._base = self._detectar_bloque()

    def _detectar_bloque(self):
        """0x100 si el acumulador responde en 0x328 (port 2026.1), 0 si en
        0x228 (etapa7 viejo). El registro de muestras por ventana es R/W con
        default 195312 y los registros sin mapear se leen 0 en ambos."""
        if struct.unpack_from("<I", self._mm, self._OFF_WINDOW_SAMPLES + 0x100)[0] != 0:
            return 0x100
        if struct.unpack_from("<I", self._mm, self._OFF_WINDOW_SAMPLES)[0] != 0:
            return 0
        raise RuntimeError("el bitstream cargado no tiene el acumulador de area/kurtosis "
                           "(ni en 0x328 ni en 0x228)")

    def _leer_reg(self, offset):
        return struct.unpack_from("<I", self._mm, offset + self._base)[0]

    def fs_hz(self):
        return self._fs

    def window_samples(self):
        return self._n_ventana

    def leer(self):
        wc = self._leer_reg(self._OFF_WINDOW_COUNT)
        sum_abs = self._leer_reg(self._OFF_SUM_ABS_LO) | (self._leer_reg(self._OFF_SUM_ABS_HI) << 32)
        sum_x2 = self._leer_reg(self._OFF_SUM_X2_LO) | (self._leer_reg(self._OFF_SUM_X2_HI) << 32)
        sum_x4 = (self._leer_reg(self._OFF_SUM_X4_LO)
                  | (self._leer_reg(self._OFF_SUM_X4_MID) << 32)
                  | (self._leer_reg(self._OFF_SUM_X4_HI) << 64))
        return wc, sum_abs, sum_x2, sum_x4

    def hay_mas(self):
        if self._duracion_s is None:
            return True
        return (time.monotonic() - self._t_inicio) < self._duracion_s

    def close(self):
        self._mm.close()


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

        if not lector.hay_mas() and wc == ultimo_wc:
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
    ap.add_argument("--hw", action="store_true",
                     help="lee los registros reales via mmap de /dev/mem (Etapa 7/8, solo "
                          "funciona corriendo EN la placa con el bitstream nuevo cargado)")
    ap.add_argument("--fs-hz", type=float, default=None,
                     help="--hw: fs real del ADC (ej. 3906250 para decimacion 32)")
    ap.add_argument("--duracion-s", type=float, default=None,
                     help="--hw: cuanto tiempo leer antes de cortar (default: sin limite, Ctrl+C)")
    ap.add_argument("--archivo", type=Path, default=None,
                     help="usar este .bin en vez del archivo de referencia por default "
                          "(para probar con datos de otra decimacion, por ejemplo)")
    ap.add_argument("--limite-s", type=float, default=8.0,
                     help="segundos del archivo de referencia a usar en --demo (default 8.0)")
    ap.add_argument("-o", "--salida", type=Path, default=Path("paquete_placa_demo.json"))
    args = ap.parse_args()

    if not args.demo and not args.hw:
        print("Elegir --demo (sin placa) o --hw (en la placa, registros reales).", file=sys.stderr)
        sys.exit(1)

    if args.hw:
        if args.fs_hz is None:
            print("--hw necesita --fs-hz (fs real del ADC para esta decimacion).", file=sys.stderr)
            sys.exit(1)
        n_ventana = int(args.fs_hz * AREA_VENTANA_S)
        print(f"Modo HW: leyendo /dev/mem en vivo (fs={args.fs_hz}Hz, "
              f"ventana={n_ventana} muestras, duracion={args.duracion_s or 'sin limite'})...")
        lector = LectorRegistrosHW(args.fs_hz, n_ventana, duracion_s=args.duracion_s)

        def avanzar(lector):
            time.sleep(0.005)  # polling liviano, no busy-loop a full velocidad

        try:
            paquete = coleccionar(lector, "hw_live", callback_avance=avanzar)
        finally:
            lector.close()
    else:
        archivo = args.archivo or (SAND_MONITORING / "datos_campo" / "42_1_reposo_20260903_145033_mono_dec32"
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
