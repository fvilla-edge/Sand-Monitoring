#!/usr/bin/env bash
# indicador_estado.sh — loop del pin de estado (PS_MIO11, ver
# mux_ps11_common.sh). Un pulso cada N segundos, con N segun el estado real
# de la placa:
#   captura     -> pulso cada 0.75s
#   transmision -> pulso cada 0.25s   (TODO: en_transmision() sin definir)
#   standby     -> pulso cada 3s      (default)
#
# El mux+salida ya se aseguraron al boot (pitaya-mux-ps11.service) — este
# script solo pulsa, no vuelve a tocar el mux (mismo criterio que
# starlink_remoto/aplicar_objetivo.sh con PS_MIO10).
#
# El periodo real entre pulsos es PERIODO + PULSO_S (no se resta el ancho
# del pulso al dormir) — de sobra para distinguir los 3 estados a simple
# vista, pero si se necesita el periodo exacto hay que restar PULSO_S antes
# del sleep.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps11_common.sh"

CFG=/root/scripts_campo_comun/cfg.py

PULSO_S=0.15   # ancho del pulso — pensado para prender un LED de forma visible; techo real es el periodo mas corto (transmision, 0.25s)

CAPTURA_PERIODO_S=0.75
TRANSMISION_PERIODO_S=0.25
STANDBY_PERIODO_S=3

# Mismo patron que PATRON_CAPTURA en starlink_remoto/mux_ps10_common.sh —
# exige el prefijo "python3" para no matchear la propia linea de comando de
# relanzar_captura.sh (que incluye la ruta a capturar_stream.py como
# argumento).
PATRON_CAPTURA='python3.*capturar_stream\.py'

AVISOS_DIR=$(python3 "$CFG" rutas.avisos_pendientes_dir)
# URL_AVISO vive en config_campo.json (indicador_estado.url_aviso), no acá
# hardcodeada — se lee de nuevo en cada tanda de envío para no depender de
# reiniciar este servicio (Restart=always, corre para siempre) cada vez que
# el endpoint cambie.

en_captura() {
  pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1
}

en_transmision() {
  # TODO: definir que proceso/evento cuenta como "en transmision".
  return 1
}

# Manda por POST cada aviso pendiente (dejado por capturar_stream.py al
# terminar una sesion) y lo borra una vez confirmado el envio (curl -f
# trata cualquier respuesta no-2xx como fallo). Si el POST falla, el
# archivo .json queda igual y se reintenta solo en el proximo ciclo — no
# hay perdida silenciosa, solo demora hasta que la red ande. Nunca se
# llama mientras en_captura() es cierto (ver el loop).
enviar_avisos_pendientes() {
  local f url
  shopt -s nullglob
  local pendientes=("$AVISOS_DIR"/*.json)
  shopt -u nullglob
  [ "${#pendientes[@]}" -eq 0 ] && return
  url=$(python3 "$CFG" indicador_estado.url_aviso)
  for f in "${pendientes[@]}"; do
    if curl -sf -X POST -H 'Content-Type: application/json' \
         --max-time 5 -d "@$f" "$url" >/dev/null 2>&1; then
      rm -f "$f"
    fi
  done
}

while true; do
  if en_captura; then
    periodo="$CAPTURA_PERIODO_S"
  else
    if en_transmision; then
      periodo="$TRANSMISION_PERIODO_S"
    else
      periodo="$STANDBY_PERIODO_S"
    fi
    enviar_avisos_pendientes
  fi
  pulsar_ps11
  sleep "$periodo"
done
