#!/bin/bash
# abrir_paquete.sh — doble-click para abrir el visor de paquetes livianos
# (área/kurtosis) sin depender de la carpeta desde la que se lo ejecute.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$DIR/.venv/bin/python3" "$DIR/analisis/visores/ver_paquete.py"
