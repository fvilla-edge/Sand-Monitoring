#!/usr/bin/env python3
"""
prueba_adc_directo.py — diagnostico HARDWARE vs BITSTREAM del artefacto de IN1.

Usa la API "rp" (bitstream/app CLASICO de adquisicion, /opt/redpitaya/lib/python/rp.py)
en vez del bitstream de la app "streaming" (rpsa_client) que usa capturar_stream.py.

Logica: si IN1 sigue mostrando el mismo pico/kurtosis anomalo con este bitstream
distinto, el problema es de hardware (ADC/front-end de esa entrada). Si con este
bitstream IN1 sale limpio, el problema es especifico de la app/bitstream de streaming.

Requiere que streaming-server NO este corriendo (usan el FPGA a la vez).
Ambos canales en HV (atenuador fisico A_1_20 en los dos, igual que en produccion).

Uso (correr en la placa): python3 prueba_adc_directo.py
"""
import sys
import os
import time
import subprocess
import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')

# El streaming-server (bitstream de la app streaming) y este script pelean por
# el mismo FPGA — hay que matarlo y cargar el bitstream clasico (v0.94) antes
# de importar rp, si no las lecturas salen invalidas o rp_Init() falla.
subprocess.run(['pkill', '-9', '-f', 'streaming-server'])
time.sleep(1)

from rp_overlay import overlay
overlay('v0.94')

import rp

BUFF_SIZE = rp.ADC_BUFFER_SIZE


def kurtosis(x):
    x = x - np.mean(x)
    m2 = np.mean(x ** 2)
    if m2 == 0:
        return 0.0
    return np.mean(x ** 4) / (m2 ** 2)


def leer_canal(canal_rp, canal_trig, nombre, duracion_s=4.0):
    # Una sola ventana de 16384 muestras a dec=64 cubre ~8ms, mucho menos que
    # el periodo del artefacto ya visto en campo (~16.8ms). Se repiten capturas
    # sueltas hasta cubrir duracion_s de tiempo real y se concatenan, asi un
    # evento periodico raro tiene chances reales de caer en alguna ventana.
    rp.rp_AcqSetGain(canal_rp, rp.RP_HIGH)  # HV, jumper fisico ya esta en HV
    rp.rp_AcqSetDecimation(rp.RP_DEC_64)
    rp.rp_AcqSetTriggerLevel(canal_trig, 0)
    rp.rp_AcqSetTriggerDelay(0)
    buff = rp.fBuffer(BUFF_SIZE)

    trozos = []
    t0 = time.time()
    n_capturas = 0
    while time.time() - t0 < duracion_s:
        rp.rp_AcqStart()
        rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_NOW)
        while rp.rp_AcqGetTriggerState()[1] != rp.RP_TRIG_STATE_TRIGGERED:
            pass
        while not rp.rp_AcqGetBufferFillState()[1]:
            pass
        rp.rp_AcqGetOldestDataV(canal_rp, BUFF_SIZE, buff)
        trozos.append(np.array([buff[i] for i in range(BUFF_SIZE)]))
        n_capturas += 1

    v = np.concatenate(trozos)
    dur_cubierta_ms = n_capturas * BUFF_SIZE * 64 / 125e6 * 1000
    print(f'{nombre}: {n_capturas} capturas, {dur_cubierta_ms:.0f}ms de señal real cubierta, '
          f'n={len(v)}  min={v.min():.3f}V  max={v.max():.3f}V  '
          f'rms={np.sqrt(np.mean(v ** 2)):.4f}V  kurtosis={kurtosis(v):.1f}')
    return v


def main():
    if rp.rp_Init() != rp.RP_OK:
        print('ERROR: no se pudo inicializar la API rp (¿streaming-server sigue corriendo?)')
        sys.exit(1)
    try:
        rp.rp_AcqReset()
        print('=== Lectura directa via bitstream clasico (API rp), ambos canales en HV ===')
        leer_canal(rp.RP_CH_1, rp.RP_T_CH_1, 'IN1')
        leer_canal(rp.RP_CH_2, rp.RP_T_CH_2, 'IN2')
    finally:
        rp.rp_Release()


if __name__ == '__main__':
    main()
