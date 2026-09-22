#!/usr/bin/env python3
"""capturar_eventos.py — "modo evento": streaming continuo (24h, sin cortes),
NO persiste nada salvo cuando una ventana de 50ms cruza kurtosis>=5 — en ese
caso guarda esa ventana cruda + su área/kurtosis. Nada se guarda para
ventanas tranquilas (a propósito, ver plan/memoria sec.182, 2026-09-22).

Arquitectura (ver playful-inventing-pumpkin.md para el detalle completo):
  - Modo NET del vendor (no FILE, que usa capturar_stream.py) — las muestras
    llegan en memoria via ADCCallback.receivePack, un solo stream continuo.
    Validado en Fase 1 (rp-f0fd8c, 2026-09-22): 0 muestras perdidas en 10 min
    corridos con el sondeo de kurtosis compitiendo por CPU al mismo tiempo.
  - Un buffer circular en RAM guarda las últimas BUFFER_VENTANAS ventanas de
    señal cruda — margen de sobra contra la ventana de 50ms.
  - LectorRegistrosHW (coleccionar_paquete_placa.py) sondea el acumulador de
    área/kurtosis de la FPGA cada ~10ms. Si kurtosis>=KURT_UMBRAL: extrae la
    ventana correspondiente del buffer y la guarda. Si no: no hace nada.

Calibración de alineación (window_count de la FPGA <-> índice de muestra en
el buffer propio): el registro corre desde el reload del bitstream, este
script arranca a recibir muestras un rato después — se mide un offset fijo
una sola vez al arrancar (ver `_calibrar_offset`), NO se asume que arrancan
juntos. Confirmar con un golpe real al sensor antes de confiar en el
recorte (Fase 3 del plan).

Uso:
  python3 capturar_eventos.py [--umbral 5.0] [--destino /mnt/usb/eventos]
"""
import sys
import os
import time
import argparse
import datetime
import json
import threading

import numpy as np

sys.path.insert(0, '/root/rpsa_client/python_lib')
sys.path.insert(0, '/root/scripts_campo_comun')
import streaming
import campo_common as cc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analisis', 'placa'))
from coleccionar_paquete_placa import LectorRegistrosHW, _area_kurtosis_de_suma

DECIMACION = 32
FS_HZ = 3_906_250.0  # decimacion 32, mono — ver area_kurtosis.py/config_campo.json
VENTANA_MUESTRAS = int(FS_HZ * 0.05)  # 195312, 50ms
BUFFER_VENTANAS = 6  # ~300ms de margen — de sobra frente a los 10ms de poll validados hoy
BUFFER_MUESTRAS = VENTANA_MUESTRAS * BUFFER_VENTANAS

_stop = cc.instalar_manejador_stop()


class BufferCircular:
    """Guarda las últimas `capacidad` muestras int16 recibidas, indexadas
    por posición ABSOLUTA (desde que arrancó el stream) — permite pedir
    "dame las muestras [a:b)" mientras b todavía esté dentro del margen que
    no se pisó."""

    def __init__(self, capacidad):
        self.capacidad = capacidad
        self.datos = np.zeros(capacidad, dtype=np.int16)
        self.total_recibidas = 0
        self.lock = threading.Lock()

    def escribir(self, muestras):
        with self.lock:
            n = len(muestras)
            pos = self.total_recibidas % self.capacidad
            fin = pos + n
            if fin <= self.capacidad:
                self.datos[pos:fin] = muestras
            else:
                primera = self.capacidad - pos
                self.datos[pos:] = muestras[:primera]
                self.datos[:n - primera] = muestras[primera:]
            self.total_recibidas += n

    def extraer(self, indice_inicio, n):
        """None si la ventana ya se pisó, o si todavía no llegó del todo."""
        with self.lock:
            if indice_inicio < 0:
                return None
            fin = indice_inicio + n
            if fin > self.total_recibidas:
                return None  # todavia no llego
            if self.total_recibidas - indice_inicio > self.capacidad:
                return None  # ya se piso
            pos = indice_inicio % self.capacidad
            fin_pos = pos + n
            if fin_pos <= self.capacidad:
                return self.datos[pos:fin_pos].copy()
            primera = self.capacidad - pos
            return np.concatenate([self.datos[pos:], self.datos[:n - primera]])


def _calibrar_offset(buf, lector, log_evento):
    """offset tal que: samples_en_buffer_propio = wc*VENTANA_MUESTRAS - offset.
    Se mide una sola vez, con el stream ya corriendo hace un par de segundos
    (margen para que el buffer tenga datos reales que correlacionar)."""
    time.sleep(2.0)
    wc_cal, _, _, _ = lector.leer()
    total_cal = buf.total_recibidas
    offset = wc_cal * VENTANA_MUESTRAS - total_cal
    log_evento(f'Calibracion: window_count={wc_cal} muestras_propias={total_cal} offset={offset}')
    return offset


def _guardar_evento(destino, muestras, area, kurt, wc, timestamp):
    os.makedirs(destino, exist_ok=True)
    ts_str = timestamp.strftime('%Y%m%d_%H%M%S_%f')
    base = f'evento_{ts_str}_wc{wc:010d}'
    muestras.astype('<i2').tofile(os.path.join(destino, base + '.bin'))
    meta = {
        'formato': 'evento_ventana_cruda_int16_le',
        'fs_hz': FS_HZ,
        'ventana_s': 0.05,
        'muestras': int(len(muestras)),
        'window_count': int(wc),
        'area': float(area),
        'kurtosis': float(kurt),
        'timestamp_iso': timestamp.isoformat(),
    }
    with open(os.path.join(destino, base + '.json'), 'w') as f:
        json.dump(meta, f, indent=2)
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--umbral', type=float, default=5.0,
                     help='kurtosis minima para guardar la ventana (default 5.0, '
                          'con margen contra el umbral real de 6.0)')
    ap.add_argument('--destino', default='/root/eventos',
                     help='carpeta donde se guardan los eventos que cruzan el umbral')
    args = ap.parse_args()

    buf = BufferCircular(BUFFER_MUESTRAS)

    class ADC_CB(streaming.ADCCallback):
        def receivePack(self, c, pack):
            ch = pack.channel1
            if ch.samples > 0:
                buf.escribir(np.array(ch.raw, dtype=np.int16))

        def connected(self, c, h):
            cc.log('INFO', f'  Conectado: {h}')

        def disconnected(self, c, h):
            cc.log('WARNING', f'  Desconectado: {h}')

        def error(self, c, h, code):
            cc.log('WARNING', f'  Error receivePack: {code}')

    cc.log('INFO', 'Asegurando streaming-server (mata previo + carga bitstream)...')
    cc.asegurar_servidor('/root/capturar_eventos_server.log')

    confObj = streaming.ConfigStreamClient()
    adcObj = streaming.ADCStreamClient(confObj)
    confObj.setVerbose(False)
    adcObj.setVerbose(False)
    if not confObj.connect():
        sys.exit('ERROR: no se pudo conectar al streaming-server')

    confObj.sendConfig('adc_pass_mode', 'NET')
    confObj.sendConfig('adc_decimation', str(DECIMACION))
    confObj.sendConfig('channel_attenuator_1', 'A_1_20')
    confObj.sendConfig('channel_state_1', 'ON')
    confObj.sendConfig('channel_state_2', 'OFF')

    cb = ADC_CB()
    adcObj.setCallback(cb)

    cc.log('INFO', f'Modo evento — umbral kurtosis>={args.umbral}, destino={args.destino}')
    if not adcObj.startStreaming():
        sys.exit('ERROR: startStreaming fallo')

    lector = LectorRegistrosHW(FS_HZ, VENTANA_MUESTRAS)
    try:
        offset = _calibrar_offset(buf, lector, lambda m: cc.log('INFO', m))

        eventos_guardados = 0
        ventanas_vistas = 0
        ventanas_perdidas_del_registro = 0
        ultimo_wc, _, _, _ = lector.leer()

        while not _stop.activo:
            wc, sum_abs, sum_x2, sum_x4 = lector.leer()
            if wc != ultimo_wc:
                if wc - ultimo_wc > 1:
                    # el registro no guarda cola - si saltamos mas de una
                    # ventana, las intermedias se perdieron para el calculo
                    # (aunque la senal cruda de esas SI pudo seguir en el
                    # buffer, si hiciera falta reconstruirlas aparte).
                    ventanas_perdidas_del_registro += (wc - ultimo_wc - 1)
                ventanas_vistas += 1
                area, kurt = _area_kurtosis_de_suma(sum_abs, sum_x2, sum_x4, VENTANA_MUESTRAS, FS_HZ)
                if kurt >= args.umbral:
                    idx_inicio = (wc - 1) * VENTANA_MUESTRAS - offset
                    ventana_cruda = buf.extraer(idx_inicio, VENTANA_MUESTRAS)
                    timestamp = datetime.datetime.now(datetime.timezone.utc)
                    if ventana_cruda is not None:
                        nombre = _guardar_evento(args.destino, ventana_cruda, area, kurt, wc, timestamp)
                        eventos_guardados += 1
                        cc.log('OK', f'  [EVENTO] {nombre}  area={area:.4f} kurtosis={kurt:.2f}')
                    else:
                        cc.log('WARNING', f'  Ventana wc={wc} cruzo el umbral (kurt={kurt:.2f}) '
                                          f'pero ya no estaba en el buffer — se perdio')
                ultimo_wc = wc
            time.sleep(0.01)
    finally:
        adcObj.stopStreaming()
        lector.close()
        cc.log('INFO', f'Modo evento terminado. Ventanas vistas: {ventanas_vistas} | '
                       f'eventos guardados: {eventos_guardados} | '
                       f'ventanas perdidas del registro (saltos>1): {ventanas_perdidas_del_registro}')


if __name__ == '__main__':
    main()
