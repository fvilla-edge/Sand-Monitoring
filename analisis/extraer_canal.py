#!/usr/bin/env python3
"""
extraer_canal.py — Saca un solo canal (IN1 o IN2) de capturas DUAL ya
grabadas, generando un .bin + session_info.json equivalentes a una captura
mono real. Util cuando solo hace falta un canal para el analisis (o para
mover menos datos, ej. por Starlink) sin descartar la captura dual original
completa, que queda intacta.

Es posprocesamiento en la PC sobre archivos .bin ya transferidos — no corre
en la placa ni toca el pipeline de scripts_campo/capturar_stream.py.

--canal 1 = IN1 (sensor codo), --canal 2 = IN2 (sensor referencia) — mismo
orden fijo que _leer_canales_bin en revisar.py (indice 0 = IN1, indice 1 =
IN2). El archivo de salida queda con el canal elegido en la posicion de
"canal unico", asi revisar.py/graficar.py/timeline_lote.py lo leen como
cualquier captura mono, sin cambios.

Uso:
  .venv/bin/python3 analisis/extraer_canal.py --canal 1 "carpeta dual"/ -o salida/
  .venv/bin/python3 analisis/extraer_canal.py --canal 2 campo_con_arena_*.bin -o salida/
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from revisar import (  # noqa: E402
    _MARKER, _OFF_LOST_COUNT, _OFF_OSC_RATE, _OFF_SIGMENT_LENGTH, _OFF_SIZE_CH,
    _cargar_info, _detectar_header_size, _recopilar_rutas,
)

CANAL_NOMBRE = {1: 'IN1', 2: 'IN2'}


def _extraer_bin(ruta, idx_canal, destino):
    """Reescribe ruta (dual) a destino (mono), quedandose solo con el canal
    idx_canal (0=IN1, 1=IN2). Mismo contenedor de segmentos/header/marcador
    que el original, con sizeCh (y en header de 144B: lostCount, oscRate,
    sigmentLength) remapeados a la posicion 0 — para que el resto del
    pipeline lo lea igual que una captura mono real."""
    tam = ruta.stat().st_size
    n_seg = 0
    with open(ruta, 'rb') as f_in, open(destino, 'wb') as f_out:
        header_size = _detectar_header_size(f_in, tam)
        pos = 0
        while pos + header_size <= tam:
            f_in.seek(pos)
            header = bytearray(f_in.read(header_size))
            size_ch = np.frombuffer(bytes(header), dtype='<u4', count=4, offset=_OFF_SIZE_CH)
            fin_datos = pos + header_size + int(size_ch.sum())
            if fin_datos + 12 > tam:
                print(f'[!] {ruta.name}: segmento {n_seg} truncado, se corta ahi', file=sys.stderr)
                break
            f_in.seek(pos + header_size + int(size_ch[:idx_canal].sum()))
            datos_canal = f_in.read(int(size_ch[idx_canal]))
            f_in.seek(fin_datos)
            if f_in.read(12) != _MARKER:
                print(f'[!] {ruta.name}: marcador invalido en segmento {n_seg}, se corta ahi', file=sys.stderr)
                break

            nuevo_size_ch = np.zeros(4, dtype='<u4')
            nuevo_size_ch[0] = size_ch[idx_canal]
            header[_OFF_SIZE_CH:_OFF_SIZE_CH + 16] = nuevo_size_ch.tobytes()

            if header_size == 144:
                lost_ch = np.frombuffer(bytes(header), dtype='<u8', count=4, offset=_OFF_LOST_COUNT)
                nuevo_lost = np.zeros(4, dtype='<u8')
                nuevo_lost[0] = lost_ch[idx_canal]
                header[_OFF_LOST_COUNT:_OFF_LOST_COUNT + 32] = nuevo_lost.tobytes()

                osc_ch = np.frombuffer(bytes(header), dtype='<u8', count=4, offset=_OFF_OSC_RATE)
                nuevo_osc = np.zeros(4, dtype='<u8')
                nuevo_osc[0] = osc_ch[idx_canal]
                header[_OFF_OSC_RATE:_OFF_OSC_RATE + 32] = nuevo_osc.tobytes()

                nuevo_len = np.array([size_ch[idx_canal]], dtype='<u4')
                header[_OFF_SIGMENT_LENGTH:_OFF_SIGMENT_LENGTH + 4] = nuevo_len.tobytes()

            f_out.write(bytes(header))
            f_out.write(datos_canal)
            f_out.write(_MARKER)

            pos = fin_datos + 12
            n_seg += 1
    return n_seg


def _info_extraido(info_original, canal_extraido, nombre_dual):
    info = dict(info_original)
    fs_por_canal = info.pop('fs_hz_por_canal', None)
    info.pop('canal_ch1', None)
    info.pop('canal_ch2', None)
    info['canales'] = 1
    if fs_por_canal is not None:
        info['fs_hz'] = fs_por_canal
    info['descripcion'] = (
        'Segmentos [header][datos canal][marcador 12B 0xFF] repetidos — '
        f'extraido del canal {canal_extraido} de una captura dual original. '
        'Parsear con analisis/revisar.py::_leer_canales_bin, no como raw plano.'
    )
    info['gain'] = str(info.get('gain', '')).replace(', ambos canales', '')
    info['canal_extraido'] = canal_extraido
    info['extraido_de'] = nombre_dual
    return info


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rutas', nargs='+', help='carpeta(s) o archivo(s) .bin de capturas dual')
    ap.add_argument('--canal', type=int, choices=(1, 2), required=True,
                     help='1=IN1 (sensor codo), 2=IN2 (sensor referencia)')
    ap.add_argument('-o', '--salida', required=True, help='carpeta de salida (se crea si no existe)')
    args = ap.parse_args()

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    idx = args.canal - 1
    canal_nombre = CANAL_NOMBRE[args.canal]

    rutas = sorted(_recopilar_rutas(args.rutas), key=lambda p: p.name)
    if not rutas:
        print('[!] No se encontraron archivos campo_*.bin', file=sys.stderr)
        sys.exit(1)

    jsons_escritos = set()
    for ruta in rutas:
        info = _cargar_info(ruta)
        if int(info.get('canales', 1)) != 2:
            print(f'[!] {ruta.name}: no es una captura dual (canales={info.get("canales")}), se omite', file=sys.stderr)
            continue

        destino = salida / f'{ruta.stem}_ch{args.canal}{ruta.suffix}'
        n_seg = _extraer_bin(ruta, idx, destino)
        print(f'[OK] {ruta.name} -> {destino.name} ({n_seg} segmentos, canal {canal_nombre})')

        m = re.match(r'campo_(reposo|con_arena)_(\d{8}_\d{6})_\d{4}', ruta.stem)
        nombre_json = (f'session_{m.group(1)}_{m.group(2)}_info.json' if m
                        else 'session_info.json')
        destino_json = salida / nombre_json
        if destino_json not in jsons_escritos:
            info_nuevo = _info_extraido(info, canal_nombre, ruta.name)
            with open(destino_json, 'w') as f:
                json.dump(info_nuevo, f, indent=2, ensure_ascii=False)
                f.write('\n')
            jsons_escritos.add(destino_json)

    print(f'\n[OK] {len(jsons_escritos)} sesion(es) escritas en {salida}')


if __name__ == '__main__':
    main()
