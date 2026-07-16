#!/usr/bin/env python3
"""
cfg.py — lectura de config_campo.json, fuente unica de parametros operativos
(umbrales, timeouts, rutas, defaults de captura) compartida entre los
scripts Python y Bash de campo.

No incluye invariantes de hardware/firmware (frecuencia base del ADC,
factores de decimacion validos, direcciones de registro FPGA) — esos
quedan hardcodeados en el codigo a proposito, ver campo_common.py y
starlink_remoto/control_starlink.sh.

Uso desde Python:
    import cfg
    minimo = cfg.obtener('espacio.minimo_mb_por_canal')

Uso desde Bash:
    TIMEOUT_STOP=$(python3 /root/scripts_campo_comun/cfg.py starlink.timeout_stop_s)
"""
import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_campo.json')
_config = None


def cargar():
    """Carga (una sola vez, con cache en el modulo) y devuelve el config completo."""
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = json.load(f)
    return _config


def obtener(clave):
    """Busca `clave` con notacion punto, ej. 'reintentos.max', dentro del config."""
    valor = cargar()
    for parte in clave.split('.'):
        valor = valor[parte]
    return valor


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Uso: cfg.py <clave.punteada>', file=sys.stderr)
        sys.exit(1)
    print(obtener(sys.argv[1]))
