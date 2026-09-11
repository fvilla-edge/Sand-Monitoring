#!/bin/bash
# abrir_acumulado_lote.sh — doble-click para abrir el visor de acumulado de
# lote sin depender de la carpeta desde la que se lo ejecute.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$DIR/.venv/bin/python3" "$DIR/analisis/visores/ver_acumulado_lote.py"
