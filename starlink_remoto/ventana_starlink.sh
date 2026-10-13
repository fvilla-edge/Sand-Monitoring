#!/usr/bin/env bash
# ventana_starlink.sh — una ventana del modo "ventana" de Starlink
# (docs/plan_modos_starlink.md, Fase 3). Lo corre starlink-ventana.service,
# disparado por starlink-ventana.timer (cada 2 h a los :05, y al arrancar).
#
# 1. Modo permanente: no hace nada (Starlink ya esta prendida).
# 2. Abre la ventana: VENTANA_FLAG con la hora de apertura y aplica el
#    objetivo (decidir_objetivo.sh => "on").
# 3. Espera internet hasta starlink.ventana_espera_internet_min.
# 4. Un intento de subida a GCS (subir_csv_gcs.py --ventana).
# 5. Deja starlink.ventana_espera_losant_s desde que hubo internet para que
#    llegue un comando "modo" de Losant (panel-solar-informe).
# 6. Si la antena esta actualizando firmware (softwareUpdateState distinto
#    de IDLE), espera hasta starlink.ventana_extension_update_min mas.
# 7. Cierra la ventana: borra VENTANA_FLAG y aplica el objetivo (=> "off",
#    salvo que en el medio se haya pasado a permanente o haya un manual).
# 8. Una linea en LOG_VENTANAS (solo local).
#
# Haya subido o no, apaga: lo que fallo queda para la proxima ventana. Si el
# script muere en el medio, decidir_objetivo.sh ignora la marca despues de
# starlink.ventana_cada_h horas.
#
# ESTADO_UPDATE_CMD (variable de entorno, solo para pruebas): comando que
# imprime el softwareUpdateState en lugar de preguntarle a la antena.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/modo_operacion_common.sh"   # modo_vigente

VENTANA_FLAG=/run/starlink_ventana   # la lee decidir_objetivo.sh
LOG_VENTANAS=/root/logs_campo/ventanas_starlink.log
SUBIR_GCS=/root/scripts_campo/subir_csv_gcs.py
HOST_INTERNET=storage.googleapis.com
SONDEO_S=30

# Una sola llamada a cfg.py (un valor por linea): cada python3 cuesta ~0.4s de CPU en la placa
CFG_VALORES=$(python3 "$CFG" rutas.modo_operacion_file starlink.modo_defecto \
  starlink.ventana_espera_internet_min starlink.ventana_espera_losant_s \
  starlink.ventana_extension_update_min starlink_api.host starlink_api.timeout_s \
  rutas.ultima_ventana_file)
{ read -r MODO_FILE; read -r MODO_DEFECTO; read -r ESPERA_INTERNET_MIN; read -r ESPERA_LOSANT_S;
  read -r EXTENSION_UPDATE_MIN; read -r ANTENA_HOST; read -r ANTENA_TIMEOUT_S; read -r ULTIMA_VENTANA_FILE; } <<< "$CFG_VALORES"

if [ "$(modo_vigente "$MODO_FILE" "$MODO_DEFECTO")" = "permanente" ]; then
  echo "modo permanente: no se abre ventana"
  exit 0
fi

# Una ventana a la vez (timer + arranque, o una corrida a mano)
exec 8>/run/lock/starlink_ventana.lock
if ! flock -n 8; then
  echo "ya hay una ventana abierta, no se abre otra"
  exit 0
fi

hay_internet() { timeout 10 bash -c "exec 3<>/dev/tcp/$HOST_INTERNET/443" 2>/dev/null; }

estado_update() {   # softwareUpdateState de la antena, vacio si no responde
  if [ -n "${ESTADO_UPDATE_CMD:-}" ]; then
    bash -c "$ESTADO_UPDATE_CMD" 2>/dev/null || true
    return
  fi
  python3 - "$ANTENA_HOST" "$ANTENA_TIMEOUT_S" 2>/dev/null <<'EOF' || true
import sys
sys.path.insert(0, "/root/starlink_api")
from starlink_get_location import _call
r = _call(sys.argv[1], "get_status", float(sys.argv[2]))
print(r.get("dishGetStatus", {}).get("softwareUpdateStats", {}).get("softwareUpdateState", ""))
EOF
}

cerrar() {
  rm -f "$VENTANA_FLAG"
  "$DIR/aplicar_objetivo.sh" 8>&- || echo "ADVERTENCIA: aplicar_objetivo.sh fallo al cerrar la ventana" >&2
}

SEG_INTERNET=-1
GCS="sin internet"
UPDATE="-"
registrar() {   # registrar <como termino>
  mkdir -p "$(dirname "$LOG_VENTANAS")"
  printf '%s abierta=%s internet_s=%s gcs="%s" update=%s duracion_s=%s fin=%s\n' \
    "$(date -u +%FT%TZ)" "$(date -u -d "@$T0" +%T)" "$SEG_INTERNET" "$GCS" "$UPDATE" \
    "$(( $(date +%s) - T0 ))" "$1" >> "$LOG_VENTANAS"
}

T0=$(date +%s)
echo "$T0" > "$VENTANA_FLAG"
# Prueba de vida del mecanismo de ventanas (rescate de ventana en
# decidir_objetivo.sh). En la SD: sobrevive un reinicio.
echo "$T0" > "$ULTIMA_VENTANA_FILE.tmp" && mv "$ULTIMA_VENTANA_FILE.tmp" "$ULTIMA_VENTANA_FILE" \
  || echo "ADVERTENCIA: no se pudo escribir $ULTIMA_VENTANA_FILE" >&2
# Pase lo que pase (error, kill de systemd por timeout), la ventana se cierra
trap 'cerrar; registrar cortada' EXIT
echo "ventana abierta"
"$DIR/aplicar_objetivo.sh" 8>&- || echo "ADVERTENCIA: aplicar_objetivo.sh fallo al abrir la ventana" >&2

limite=$(( T0 + ESPERA_INTERNET_MIN * 60 ))
while :; do
  if hay_internet; then SEG_INTERNET=$(( $(date +%s) - T0 )); break; fi
  [ "$(date +%s)" -ge "$limite" ] && break
  sleep "$SONDEO_S"
done

if [ "$SEG_INTERNET" -ge 0 ]; then
  echo "internet a los ${SEG_INTERNET}s, subo a GCS (un intento)"
  t_net=$(date +%s)
  salida=$(nice -n 19 ionice -c3 python3 -u "$SUBIR_GCS" --ventana 2>&1 8>&-) || true
  printf '%s\n' "$salida"
  GCS=$(printf '%s\n' "$salida" | tail -1 | sed 's/^\[[0-9:]*\] //')
  restante=$(( t_net + ESPERA_LOSANT_S - $(date +%s) ))
  if [ "$restante" -gt 0 ]; then
    echo "espero ${restante}s por un comando de Losant"
    sleep "$restante"
  fi
fi

estado=$(estado_update)
if [ -n "$estado" ] && [ "$estado" != "IDLE" ]; then
  UPDATE="$estado"
  limite=$(( $(date +%s) + EXTENSION_UPDATE_MIN * 60 ))
  echo "antena con softwareUpdateState=$estado: extiendo la ventana hasta ${EXTENSION_UPDATE_MIN} min"
  while [ "$(date +%s)" -lt "$limite" ]; do
    sleep "$SONDEO_S"
    estado=$(estado_update)
    [ -z "$estado" ] || [ "$estado" = "IDLE" ] && break
  done
  UPDATE="$UPDATE->${estado:-sin_respuesta}"
fi

trap - EXIT
cerrar
echo "ventana cerrada"
registrar normal
