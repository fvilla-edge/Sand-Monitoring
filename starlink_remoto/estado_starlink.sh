#!/usr/bin/env bash
# estado_starlink.sh — muestra el ultimo estado real conocido del rele.
#
# Lectura pasiva: solo lee STATE_FILE (que control_starlink.sh actualiza con
# el feedback real de HW cada vez que corre) y no toca el FPGA ni corta una
# captura activa. Con el timer reconciliador (cada 5 min) instalado, esto
# nunca deberia estar mas desactualizado que eso — si necesitas una
# verificacion en vivo, control_starlink.sh {on|off} fuerza una lectura real,
# pero corta cualquier captura en curso (ver su cabecera).

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
STATE_FILE=$(python3 "$CFG" rutas.state_file)
MODO_MANUAL_FILE=$(python3 "$CFG" rutas.modo_manual_file)

if [ -s "$STATE_FILE" ]; then
  ESTADO=$(cat "$STATE_FILE")
  echo "${ESTADO^^}"
else
  echo "DESCONOCIDO (nunca se registro un estado)"
fi

# Detalle extra (mtime, modo manual, sincronizacion de reloj) — comentado a
# pedido para no saturar la salida en demos. Descomentar para volver a verlo.
# MTIME=$(stat -c '%y' "$STATE_FILE" 2>/dev/null | cut -d. -f1)
# echo "ultima confirmacion real por HW: ${MTIME}"
#
# if [ -s "$MODO_MANUAL_FILE" ]; then
#   echo "Modo: MANUAL ($(cat "$MODO_MANUAL_FILE")) — automatico desactivado hasta 'starlink_manual.sh auto'"
# else
#   echo "Modo: automatico (reloj + horario)"
# fi
#
# if [ "$(timedatectl show -p NTPSynchronized --value)" = "yes" ]; then
#   echo "Reloj sincronizado: si"
# else
#   echo "Reloj sincronizado: NO — el automatico va a forzar 'on' hasta que sincronice"
# fi
