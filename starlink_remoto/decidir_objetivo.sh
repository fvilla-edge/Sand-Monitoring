#!/usr/bin/env bash
# decidir_objetivo.sh — calcula si el rele DEBERIA estar on/off ahora mismo.
# No toca hardware, no pulsa nada — solo imprime "on" u "off" por stdout.
#
# Prioridad, de mayor a menor:
#   1. Modo manual (modo_manual_file) — si existe, gana siempre, sin excepcion.
#   2. Reloj no confiable (NTPSynchronized=no) — la placa no tiene RTC (ver
#      control_starlink.sh), asi que si todavia no sincronizo desde el boot
#      no hay forma de confiar en el horario. Se fuerza "on" para que
#      Starlink suba y ntpsec pueda corregir el reloj.
#   3. Horario normal (config_campo.json: starlink.hora_on/hora_off).
#
# Ver HISTORIAL_STARLINK.md, seccion "reloj sin RTC + Persistent=true", para
# el porque de este orden (reproducido en placa real: con reloj atrasado,
# Persistent=true de los timers NO dispara el catch-up al bootear).

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
TZ_CAMPO="America/Argentina/Buenos_Aires"

MODO_MANUAL_FILE=$(python3 "$CFG" rutas.modo_manual_file)
HORA_ON=$(python3 "$CFG" starlink.hora_on)
HORA_OFF=$(python3 "$CFG" starlink.hora_off)

if [ -s "$MODO_MANUAL_FILE" ]; then
  cat "$MODO_MANUAL_FILE"
  exit 0
fi

if [ "$(timedatectl show -p NTPSynchronized --value)" != "yes" ]; then
  echo on
  exit 0
fi

AHORA=$(TZ="$TZ_CAMPO" date +%H:%M)
if [[ ( "$AHORA" > "$HORA_ON" || "$AHORA" == "$HORA_ON" ) && "$AHORA" < "$HORA_OFF" ]]; then
  echo on
else
  echo off
fi
