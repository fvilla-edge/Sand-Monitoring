#!/bin/bash
# armar_exe_windows.sh — arma VisorSandMonitoring.exe (visor_csv.py) para
# Windows desde Linux, con un Python de Windows dentro de Wine y PyInstaller.
# Un solo .exe, sin instalar nada en la PC que lo abre.
#
# Prefijo de Wine propio (no toca ~/.wine): ~/.wine_visor_csv, con Python
# 3.12.10 de python.org instalado desde los .msi de 64 bits (el instalador
# .exe de python.org es de 32 bits y en esta PC falta wine32). Ver README.md.
#
# Uso: bash analisis/visores/empaquetar/armar_exe_windows.sh
# Salida: visor_windows/VisorSandMonitoring.exe en la raiz del repo (fuera de git)
set -euo pipefail

REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine_visor_csv}" WINEDEBUG=-all
PY='C:\Python312\python.exe'
[ -f "$WINEPREFIX/drive_c/Python312/python.exe" ] || { echo "falta Python en $WINEPREFIX (ver README.md)" >&2; exit 1; }

# Wine y PyInstaller se llevan mal con espacios en la ruta ("Sand Monitoring"):
# se compila una copia en C:\build_visor
B="$WINEPREFIX/drive_c/build_visor"
rm -rf "$B" && mkdir -p "$B"
cp "$REPO/analisis/visores/visor_csv.py" "$REPO/analisis/visores/vista_reducida.py" \
   "$REPO/analisis/placa/ventanas_a_paquete.py" "$B/"
echo "commit=$(git -C "$REPO" rev-parse --short HEAD)$(git -C "$REPO" diff --quiet -- analisis || echo '+cambios')" > "$B/VERSION.txt"

cd "$B"
wine "$PY" -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name VisorSandMonitoring --paths 'C:\build_visor' \
    --collect-all tkinterdnd2 --add-data 'VERSION.txt;.' \
    --exclude-module scipy --exclude-module pandas --exclude-module PyQt5 --exclude-module PySide6 \
    visor_csv.py 2>&1 | grep -v -E "wine32|apt-get" | grep -E "INFO: Building EXE|completed successfully|ERROR|Error" || true

mkdir -p "$REPO/visor_windows"
cp "$B/dist/VisorSandMonitoring.exe" "$REPO/visor_windows/"
cp "$B/VERSION.txt" "$REPO/visor_windows/"
ls -la "$REPO/visor_windows/"
sha256sum "$REPO/visor_windows/VisorSandMonitoring.exe"
