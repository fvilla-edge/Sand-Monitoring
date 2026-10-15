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

Escritura (solo claves que ya existen; el valor se interpreta como JSON si se
puede, si no queda como texto):
    python3 /root/scripts_campo_comun/cfg.py --poner modo_evento.canales 2
Es atomica: temporal en la misma carpeta + fsync + rename + fsync de la
carpeta. Un corte o un cuelgue en el medio deja el archivo viejo o el nuevo,
nunca uno a medias (un archivo recien escrito sin fsync puede quedar en ceros
si la placa se cuelga, visto el 2026-10-06).
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


def poner(clave, valor):
    """Cambia `clave` (que tiene que existir) y guarda el config de forma atomica."""
    global _config
    with open(_CONFIG_PATH) as f:
        config = json.load(f)   # releer: no pisar cambios hechos por otro proceso
    partes = clave.split('.')
    nodo = config
    for parte in partes[:-1]:
        nodo = nodo[parte]
    if partes[-1] not in nodo:
        raise KeyError(clave)
    nodo[partes[-1]] = valor
    carpeta = os.path.dirname(_CONFIG_PATH)
    tmp = _CONFIG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _CONFIG_PATH)
    fd = os.open(carpeta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _config = config


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == '--poner':
        try:
            nuevo = json.loads(sys.argv[3])
        except ValueError:
            nuevo = sys.argv[3]
        try:
            poner(sys.argv[2], nuevo)
        except KeyError:
            print(f'No existe la clave {sys.argv[2]}', file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    if len(sys.argv) < 2:
        print('Uso: cfg.py <clave.punteada> [<clave.punteada> ...]', file=sys.stderr)
        sys.exit(1)
    # Varias claves = un valor por linea, en el mismo orden: cada arranque de
    # python3 cuesta ~0.4s de CPU en la placa, y el reconciliador de 5 min
    # hacia 16 (~7s, coincidian con perdidas de muestras crudas).
    for clave in sys.argv[1:]:
        print(obtener(clave))
