#!/usr/bin/env bash
# decidir_objetivo.sh — calcula si el rele DEBERIA estar on/off ahora mismo.
# No toca hardware, no pulsa nada — solo imprime "on" u "off" por stdout.
#
# Prioridad, de mayor a menor:
#   0. Rescate por modo manual "off" vencido (starlink.rescate_manual_horas)
#      — ver mas abajo, corta la cadena ANTES de honrar el manual.
#   1. Modo manual (modo_manual_file) — gana siempre, con una excepcion: se
#      autolimpia solo (sin tocar HW, sin pedir "auto" a mano) en cuanto el
#      calculo de 2+3 coincide por su cuenta con lo que el manual ya venia
#      forzando. Asi "apagar-starlink" a mitad de la ventana de "on" no
#      necesita acordarse de "auto-starlink" despues: en cuanto pasa el
#      hora_off real, el horario puro ya dice "off" solo, coincide, y el
#      manual se borra.
#   2. Reloj no confiable (ni NTPSynchronized=yes ni el RTC DS3231 restaurado
#      con exito en este boot, ver /run/rtc_ds3231_ok mas abajo) — sin
#      ninguna de las dos fuentes no hay forma de confiar en el horario. Se
#      fuerza "on" para que Starlink suba y ntpsec (o el RTC en el proximo
#      boot) puedan corregir el reloj.
#   3. Horario normal (config_campo.json: starlink.hora_on/hora_off,
#      starlink.dias_habilitados). Fuera de un dia habilitado el resultado es
#      "off" sin importar la hora — mismo nivel de prioridad que el chequeo
#      de hora, no uno nuevo: un "prender-starlink" manual sigue ganando
#      igual que ya gana sobre el horario (prioridad 1, mas arriba).
#
# Ver HISTORIAL_STARLINK.md, seccion "reloj sin RTC + Persistent=true", para
# el porque de este orden (reproducido en placa real: con reloj atrasado,
# Persistent=true de los timers NO dispara el catch-up al bootear).
#
# Rescate por modo manual "off" vencido (riesgo de fail-safe, ver
# HISTORIAL_STARLINK.md): el unico camino de acceso remoto al sitio es el
# propio Starlink que este rele corta. Si alguien pone modo manual="off" y
# nunca lo renueva (corte de luz largo, viaje, olvido), sin esto quedaria
# forzado "off" para siempre sin forma de corregirlo a distancia. Por eso,
# a diferencia de la autolimpieza (que solo actua cuando manual y 2+3 ya
# coinciden solos), este rescate ignora el manual aunque siga en desacuerdo
# con el horario, despues de starlink.rescate_manual_horas sin renovarse
# (starlink_manual.sh reescribe el timestamp cada vez que se corre). No
# borra el archivo de modo manual: si alguien lo vuelve a poner en "off"
# (renovarlo), el reloj de rescate arranca de nuevo desde cero.
#
# Formato viejo de modo_manual_file (una sola linea, sin timestamp, de antes
# de este mecanismo): se trata como timestamp desconocido y el rescate se
# considera vencido de entrada (fuerza "on") — mas seguro asumir "no se sabe
# hace cuanto" que confiar en que es reciente. Mismo criterio si el reloj no
# es confiable (ni NTP sincronizado ni RTC DS3231 restaurado en este boot,
# ver /run/rtc_ds3231_ok mas abajo): sin ninguna de las dos fuentes el
# "date +%s" post-reboot puede estar atrasado, y la resta contra el
# timestamp guardado daria horas de menos (o negativo) justo cuando mas
# importa el rescate — se trata como vencido de entrada por la misma razon.
# Con el RTC restaurado con exito, en cambio, la resta es confiable desde el
# primer segundo del boot aunque ntpsec todavia no haya sincronizado por red.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
TZ_CAMPO="America/Argentina/Buenos_Aires"

MODO_MANUAL_FILE=$(python3 "$CFG" rutas.modo_manual_file)
HORA_ON=$(python3 "$CFG" starlink.hora_on)
HORA_OFF=$(python3 "$CFG" starlink.hora_off)
DIAS_HABILITADOS=$(python3 "$CFG" starlink.dias_habilitados)   # ISO: 1=lunes .. 7=domingo, separados por coma
RESCATE_MANUAL_HORAS=$(python3 "$CFG" starlink.rescate_manual_horas)

NTP_SYNC=$(timedatectl show -p NTPSynchronized --value)
RTC_FLAG_OK=/run/rtc_ds3231_ok

if [ "$NTP_SYNC" = "yes" ] || [ -e "$RTC_FLAG_OK" ]; then
  RELOJ_CONFIABLE=yes
else
  RELOJ_CONFIABLE=no
fi

if [ "$RELOJ_CONFIABLE" != "yes" ]; then
  RESCATE_U_HORARIO=on
else
  DIA_HOY=$(TZ="$TZ_CAMPO" date +%u)
  AHORA=$(TZ="$TZ_CAMPO" date +%H:%M)
  if [[ ",$DIAS_HABILITADOS," == *",$DIA_HOY,"* ]] && [[ ( "$AHORA" > "$HORA_ON" || "$AHORA" == "$HORA_ON" ) && "$AHORA" < "$HORA_OFF" ]]; then
    RESCATE_U_HORARIO=on
  else
    RESCATE_U_HORARIO=off
  fi
fi

if [ -s "$MODO_MANUAL_FILE" ]; then
  MANUAL=$(sed -n '1p' "$MODO_MANUAL_FILE")
  MANUAL_TS=$(sed -n '2p' "$MODO_MANUAL_FILE")

  if [ "$MANUAL" = "off" ]; then
    if [ "$RELOJ_CONFIABLE" != "yes" ]; then
      echo "AVISO: reloj no confiable desde el boot (ni NTP ni RTC), se ignora el modo manual '$MANUAL' y se fuerza 'on' (rescate)" >&2
      echo "on"   # rescate: reloj no confiable, no se puede confiar en el timestamp guardado (ver header)
      exit 0
    fi
    AHORA_EPOCH=$(date +%s)
    if [[ ! "$MANUAL_TS" =~ ^[0-9]+$ ]]; then
      HORAS_TRANSCURRIDAS=$((RESCATE_MANUAL_HORAS))   # formato viejo sin timestamp: vencido de entrada (ver header)
    else
      HORAS_TRANSCURRIDAS=$(( (AHORA_EPOCH - MANUAL_TS) / 3600 ))
    fi
    if [ "$HORAS_TRANSCURRIDAS" -ge "$RESCATE_MANUAL_HORAS" ]; then
      echo "AVISO: modo manual 'off' vencido hace ${HORAS_TRANSCURRIDAS}hs (>=${RESCATE_MANUAL_HORAS}), se ignora y se fuerza 'on' (rescate)" >&2
      echo "on"   # rescate: manual="off" vencido, se ignora sin borrar el archivo (ver header)
      exit 0
    fi
  fi

  if [ "$MANUAL" = "$RESCATE_U_HORARIO" ]; then
    rm -f "$MODO_MANUAL_FILE"
  fi
  echo "$MANUAL"
  exit 0
fi

echo "$RESCATE_U_HORARIO"
