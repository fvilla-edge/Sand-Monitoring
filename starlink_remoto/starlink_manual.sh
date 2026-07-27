#!/usr/bin/env bash
# starlink_manual.sh {on|off|auto} — fuerza modo manual o lo desactiva.
#
# Mientras el modo manual este activo, decidir_objetivo.sh lo respeta siempre
# (ver ese script) — ni el rescate por reloj no confiable ni el horario lo
# van a pisar, salvo que ya coincidan solos con lo forzado, en cuyo caso
# decidir_objetivo.sh lo autolimpia. Para forzar la vuelta a automatico ya
# mismo (sin esperar a que coincida), correr "auto" a mano.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODO_MANUAL_FILE=$(python3 "$CFG" rutas.modo_manual_file)

ACCION="${1:-}"
case "$ACCION" in
  on|off)
    echo "$ACCION" > "$MODO_MANUAL_FILE"
    # echo "modo manual: $ACCION — se mantiene asi hasta correr 'starlink_manual.sh auto'"
    ;;
  auto)
    rm -f "$MODO_MANUAL_FILE"
    # echo "modo manual desactivado — vuelve a decidir por reloj/horario"
    ;;
  *)
    echo "uso: $0 {on|off|auto}" >&2
    exit 1
    ;;
esac

"$DIR/aplicar_objetivo.sh"
