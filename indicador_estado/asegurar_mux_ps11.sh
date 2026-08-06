#!/usr/bin/env bash
# asegurar_mux_ps11.sh — corre una sola vez al boot (pitaya-mux-ps11.service).
#
# A diferencia de PS_MIO10 (rele), este pin no tiene nada fisico enganchado
# todavia, asi que no hay riesgo de glitch real al habilitar la salida por
# primera vez. Se separa igual en su propio service (mismo criterio que
# starlink_remoto/asegurar_mux_ps10.sh) para no mezclar el setup del mux con
# el loop de pulsos — si el loop se reinicia solo (Restart=always), no debe
# volver a tocar el mux cada vez.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps11_common.sh"

asegurar_mux_gpio
asegurar_salida_ps
