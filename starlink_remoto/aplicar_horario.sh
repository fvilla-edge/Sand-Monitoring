#!/usr/bin/env bash
# aplicar_horario.sh — aplica starlink.hora_on/hora_off de config_campo.json
# a los .timer de systemd instalados. OnCalendar es estatico (systemd no lo
# lee del json en runtime), asi que despues de cambiar el horario en el
# config hay que correr este script una vez para que surta efecto.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
TZ="America/Argentina/Buenos_Aires"
UNIT_DIR=/etc/systemd/system

HORA_ON=$(python3 "$CFG" starlink.hora_on)
HORA_OFF=$(python3 "$CFG" starlink.hora_off)

FORMATO='^([01][0-9]|2[0-3]):[0-5][0-9]$'
for hora in "$HORA_ON" "$HORA_OFF"; do
  if ! [[ "$hora" =~ $FORMATO ]]; then
    echo "hora invalida en config_campo.json: '$hora' (formato esperado HH:MM)" >&2
    exit 1
  fi
done

sed -i \
  -e "s|^OnCalendar=.*|OnCalendar=*-*-* ${HORA_ON}:00 ${TZ}|" \
  -e "s|^Description=.*|Description=Enciende el rele de Starlink todos los dias a las ${HORA_ON}|" \
  "$UNIT_DIR/starlink-rele-on.timer"

sed -i \
  -e "s|^OnCalendar=.*|OnCalendar=*-*-* ${HORA_OFF}:00 ${TZ}|" \
  -e "s|^Description=.*|Description=Apaga el rele de Starlink todos los dias a las ${HORA_OFF}|" \
  "$UNIT_DIR/starlink-rele-off.timer"

systemctl daemon-reload

echo "aplicado: on=$HORA_ON off=$HORA_OFF"
systemctl list-timers starlink-rele-on.timer starlink-rele-off.timer --no-pager
