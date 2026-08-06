#!/usr/bin/env bash
# indicador_estado.sh — loop del pin de estado (PS_MIO11, ver
# mux_ps11_common.sh). Un pulso cada N segundos, con N segun el estado real
# de la placa:
#   captura     -> pulso cada 0.75s   (TODO: en_captura() sin definir)
#   transmision -> pulso cada 0.25s   (TODO: en_transmision() sin definir)
#   standby     -> pulso cada 3s      (unico estado activo por ahora)
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

PULSO_S=0.15   # ancho del pulso — pensado para prender un LED de forma visible; techo real es el periodo mas corto (transmision, 0.25s)

CAPTURA_PERIODO_S=0.75
TRANSMISION_PERIODO_S=0.25
STANDBY_PERIODO_S=3

en_captura() {
  # TODO: definir que constituye "en captura" para este indicador. Candidato
  # natural: el mismo PATRON_CAPTURA que ya usa
  # starlink_remoto/mux_ps10_common.sh ('python3.*capturar_stream\.py').
  return 1
}

en_transmision() {
  # TODO: definir que proceso/evento cuenta como "en transmision".
  return 1
}

while true; do
  if en_captura; then
    periodo="$CAPTURA_PERIODO_S"
  elif en_transmision; then
    periodo="$TRANSMISION_PERIODO_S"
  else
    periodo="$STANDBY_PERIODO_S"
  fi
  pulsar_ps11
  sleep "$periodo"
done
