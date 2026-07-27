#!/usr/bin/env bash
# decidir_objetivo.sh — calcula si el rele DEBERIA estar on/off ahora mismo.
# No toca hardware, no pulsa nada — solo imprime "on" u "off" por stdout.
#
# Prioridad, de mayor a menor:
#   1. Modo manual (modo_manual_file) — gana siempre, con una excepcion: se
#      autolimpia solo (sin tocar HW, sin pedir "auto" a mano) en cuanto el
#      calculo de 2+3 coincide por su cuenta con lo que el manual ya venia
#      forzando. Asi "apagar-starlink" a mitad de la ventana de "on" no
#      necesita acordarse de "auto-starlink" despues: en cuanto pasa el
#      hora_off real, el horario puro ya dice "off" solo, coincide, y el
#      manual se borra. Si el manual y 2+3 NUNCA coinciden (ver
#      HISTORIAL_STARLINK.md, "riesgo de fail-safe"), el manual sigue
#      ganando sin limite de tiempo — eso sigue sin resolverse, es un caso
#      distinto.
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

if [ "$(timedatectl show -p NTPSynchronized --value)" != "yes" ]; then
  RESCATE_U_HORARIO=on
else
  AHORA=$(TZ="$TZ_CAMPO" date +%H:%M)
  if [[ ( "$AHORA" > "$HORA_ON" || "$AHORA" == "$HORA_ON" ) && "$AHORA" < "$HORA_OFF" ]]; then
    RESCATE_U_HORARIO=on
  else
    RESCATE_U_HORARIO=off
  fi
fi

if [ -s "$MODO_MANUAL_FILE" ]; then
  MANUAL=$(cat "$MODO_MANUAL_FILE")
  if [ "$MANUAL" = "$RESCATE_U_HORARIO" ]; then
    rm -f "$MODO_MANUAL_FILE"
  fi
  echo "$MANUAL"
  exit 0
fi

echo "$RESCATE_U_HORARIO"
