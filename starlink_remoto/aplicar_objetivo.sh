#!/usr/bin/env bash
# aplicar_objetivo.sh [--forzar] — decide (decidir_objetivo.sh) que deberia
# tener el rele ahora y lo aplica.
#
# Sin --forzar (uso normal: los dos timers diarios y el reconciliador de 5
# min): compara el objetivo contra STATE_FILE (la ultima lectura real
# conocida) y solo invoca control_starlink.sh si difieren. Sin esto, el
# reconciliador cortaria cualquier captura activa cada 5 min sin necesidad
# real de pulsar — el mismo motivo por el que este proyecto ya habia
# descartado un chequeo de horario de alta frecuencia (ver
# HISTORIAL_STARLINK.md, seccion "Horario configurable").
#
# Con --forzar (uso: boot, via asegurar_mux_ps10.sh): siempre llama a
# control_starlink.sh, que verifica el HW de verdad. Hace falta en el boot
# porque habilitar el mux de PS_MIO10 puede togglear el rele solo (ver
# HISTORIAL_STARLINK.md) — un mismatch entre STATE_FILE cacheado y el HW
# real que la comparacion liviana de abajo no detectaria.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE=$(python3 "$CFG" rutas.state_file)

FORZAR=0
[ "${1:-}" = "--forzar" ] && FORZAR=1

OBJETIVO=$("$DIR/decidir_objetivo.sh")

if [ "$FORZAR" -eq 0 ] && [ "$(cat "$STATE_FILE" 2>/dev/null || echo '')" = "$OBJETIVO" ]; then
  echo "objetivo '$OBJETIVO' ya coincide con la ultima lectura real conocida, no se verifica por HW"
  exit 0
fi

exec "$DIR/control_starlink.sh" "$OBJETIVO"
