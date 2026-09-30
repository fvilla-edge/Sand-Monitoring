#!/bin/bash
# abrir_visor_csv.sh — doble-click para abrir el visor de los CSV del modo
# evento (kurtosis, área y área acumulada) sin depender de la carpeta desde la
# que se lo ejecute. Acepta CSV o carpetas como argumentos (o arrastrados).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$DIR/.venv/bin/python3" "$DIR/analisis/visores/visor_csv.py" "$@"
