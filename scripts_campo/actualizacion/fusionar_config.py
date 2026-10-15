#!/usr/bin/env python3
"""
fusionar_config.py — agrega a config_campo.json de la placa las claves nuevas
del paquete SIN pisar los valores que ya tiene la placa (horarios, URLs,
umbrales propios de campo). Escritura atomica.

Uso: python3 fusionar_config.py <config_de_la_placa.json> <config_del_paquete.json>
"""
import json
import os
import sys


def fusionar(local, nuevo, camino=""):
    agregadas = []
    for clave, valor in nuevo.items():
        ruta = f"{camino}.{clave}" if camino else clave
        if clave not in local:
            local[clave] = valor
            agregadas.append(ruta)
        elif isinstance(local[clave], dict) and isinstance(valor, dict):
            agregadas += fusionar(local[clave], valor, ruta)
    return agregadas


def main():
    ruta_local, ruta_nuevo = sys.argv[1], sys.argv[2]
    with open(ruta_local) as f:
        local = json.load(f)
    with open(ruta_nuevo) as f:
        nuevo = json.load(f)
    agregadas = fusionar(local, nuevo)
    tmp = ruta_local + ".tmp"
    with open(tmp, "w") as f:
        json.dump(local, f, indent=2, ensure_ascii=False)
        f.write("\n")
        # sin fsync, un cuelgue justo despues puede dejar el archivo en ceros
        # (visto con un drop-in el 2026-10-06)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta_local)
    fd = os.open(os.path.dirname(os.path.abspath(ruta_local)), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print("claves agregadas: " + (", ".join(agregadas) if agregadas else "ninguna"))


if __name__ == "__main__":
    main()
