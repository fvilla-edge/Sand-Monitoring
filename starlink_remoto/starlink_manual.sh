#!/usr/bin/env bash
# starlink_manual.sh {on|off|auto} — fuerza modo manual o lo desactiva.
#
# Mientras el modo manual este activo, decidir_objetivo.sh lo respeta (ver ese
# script) — ni el rescate por reloj no confiable ni el horario lo van a pisar,
# salvo que ya coincidan solos con lo forzado, en cuyo caso decidir_objetivo.sh
# lo autolimpia. Para forzar la vuelta a automatico ya mismo (sin esperar a
# que coincida), correr "auto" a mano.
#
# Excepcion aparte de la autolimpieza: si el modo manual queda en "off" mas de
# starlink.rescate_manual_horas sin que se vuelva a correr este script (osea,
# sin "renovar" el pedido), decidir_objetivo.sh lo ignora y fuerza "on" —
# rescate del riesgo de fail-safe (unico camino de acceso remoto es el propio
# Starlink que este rele corta). Por eso se guarda el timestamp de cuando se
# pidio, no solo el valor.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODO_MANUAL_FILE=$(python3 "$CFG" rutas.modo_manual_file)

ACCION="${1:-}"
case "$ACCION" in
  on|off)
    printf '%s\n%s\n' "$ACCION" "$(date +%s)" > "$MODO_MANUAL_FILE"
    # echo "modo manual: $ACCION — se mantiene asi hasta correr 'starlink_manual.sh auto', o hasta el rescate por timeout si es 'off'"
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
