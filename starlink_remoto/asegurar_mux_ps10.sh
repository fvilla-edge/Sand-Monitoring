#!/usr/bin/env bash
# asegurar_mux_ps10.sh — corre una sola vez al boot (starlink-mux-ps10.service).
#
# Configurar el mux+salida de PS_MIO10 por primera vez tras un reboot puede
# togglear el rele solo, entre 1 y 2 veces segun la corrida (no
# deterministico, confirmado con analizador en placa real) — por eso, en vez
# de asumir en que estado queda el rele, se restaura el ultimo estado real
# conocido (STATE_FILE, de antes del reboot) llamando a control_starlink.sh.
# Esa llamada no vuelve a tocar el mux (ya quedo configurado arriba, sus
# propias asegurar_mux_gpio/asegurar_salida_ps son no-op) — solo lee el
# feedback real y pulsa una sola vez, limpio, si los toggles accidentales
# de arriba lo dejaron distinto de lo pedido.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps10_common.sh"

asegurar_mux_gpio
asegurar_salida_ps

CFG=/root/scripts_campo_comun/cfg.py
STATE_FILE=$(python3 "$CFG" rutas.state_file)
OBJETIVO=$(cat "$STATE_FILE" 2>/dev/null || echo off)

"$DIR/control_starlink.sh" "$OBJETIVO"
