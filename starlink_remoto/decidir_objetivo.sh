#!/usr/bin/env bash
# decidir_objetivo.sh — calcula si el rele DEBERIA estar on/off ahora mismo.
# No toca hardware, no pulsa nada — solo imprime "on" u "off" por stdout.
#
# Prioridad, de mayor a menor:
#   0. Rescate por modo manual "off" vencido (starlink.rescate_manual_horas)
#      — ver mas abajo, corta la cadena ANTES de honrar el manual.
#   1. Modo manual (modo_manual_file) — gana siempre, con una excepcion: se
#      autolimpia solo (sin tocar HW, sin pedir "auto" a mano) en cuanto el
#      calculo de 2-4 coincide por su cuenta con lo que el manual ya venia
#      forzando. Asi "apagar-starlink" a mitad de la ventana de "on" no
#      necesita acordarse de "auto-starlink" despues: en cuanto pasa el
#      hora_off real, el horario puro ya dice "off" solo, coincide, y el
#      manual se borra. Con el modo ventana (4): un "on" manual dura hasta
#      la proxima ventana abierta; un "off" en medio de una ventana la
#      corta, y se borra al cerrarse.
#   2. Reloj no confiable (ni NTPSynchronized=yes ni el RTC DS3231 restaurado
#      con exito en este boot, ver /run/rtc_ds3231_ok mas abajo) — sin
#      ninguna de las dos fuentes no hay forma de confiar en el horario. Se
#      fuerza "on" para que Starlink suba y ntpsec (o el RTC en el proximo
#      boot) puedan corregir el reloj.
#   3. Modo permanente (modo_operacion.sh) — "on" siempre.
#   4. Modo ventana — "on" solo mientras hay una ventana abierta
#      (VENTANA_FLAG, la crea/borra ventana_starlink.sh cada
#      starlink.ventana_cada_h horas), "off" el resto del tiempo. Una marca
#      de ventana mas vieja que ventana_cada_h horas se ignora (la ventana
#      que la creo murio sin borrarla; la siguiente la reescribe).
#   Ver docs/plan_modos_starlink.md (reemplaza al horario hora_on/hora_off).
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
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/modo_operacion_common.sh"   # modo_vigente
VENTANA_FLAG=/run/starlink_ventana   # 1ra linea: epoch de apertura (ventana_starlink.sh)

# Una sola llamada a cfg.py (un valor por linea): cada python3 cuesta ~0.4s de CPU en la placa
CFG_VALORES=$(python3 "$CFG" rutas.modo_manual_file starlink.rescate_manual_horas \
  rutas.modo_operacion_file starlink.modo_defecto starlink.ventana_cada_h)
{ read -r MODO_MANUAL_FILE; read -r RESCATE_MANUAL_HORAS; read -r MODO_FILE; read -r MODO_DEFECTO; read -r VENTANA_CADA_H; } <<< "$CFG_VALORES"

NTP_SYNC=$(timedatectl show -p NTPSynchronized --value)
RTC_FLAG_OK=/run/rtc_ds3231_ok

if [ "$NTP_SYNC" = "yes" ] || [ -e "$RTC_FLAG_OK" ]; then
  RELOJ_CONFIABLE=yes
else
  RELOJ_CONFIABLE=no
fi

ventana_abierta() {
  local abierta_ts
  abierta_ts=$(sed -n '1p' "$VENTANA_FLAG" 2>/dev/null) || return 1
  [[ "$abierta_ts" =~ ^[0-9]+$ ]] || return 1
  if [ $(( $(date +%s) - abierta_ts )) -ge $(( VENTANA_CADA_H * 3600 )) ]; then
    echo "AVISO: marca de ventana $VENTANA_FLAG de hace mas de ${VENTANA_CADA_H}h, se ignora" >&2
    return 1
  fi
}

if [ "$RELOJ_CONFIABLE" != "yes" ]; then
  RESCATE_U_MODO=on
elif [ "$(modo_vigente "$MODO_FILE" "$MODO_DEFECTO")" = "permanente" ]; then
  RESCATE_U_MODO=on
elif ventana_abierta; then
  RESCATE_U_MODO=on
else
  RESCATE_U_MODO=off
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

  if [ "$MANUAL" = "$RESCATE_U_MODO" ]; then
    rm -f "$MODO_MANUAL_FILE"
  fi
  echo "$MANUAL"
  exit 0
fi

echo "$RESCATE_U_MODO"
