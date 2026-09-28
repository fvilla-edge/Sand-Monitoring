#!/usr/bin/env bash
# aplicar_objetivo.sh [--forzar] [--reconciliar] — decide (decidir_objetivo.sh)
# que deberia tener el rele ahora y lo aplica.
#
# Sin --forzar (uso normal: los dos timers diarios y el reconciliador de 5
# min): si hay una captura activa Y el objetivo ya coincide con STATE_FILE (la
# ultima lectura real conocida), no invoca control_starlink.sh — verificar de
# verdad exige el bitstream v0.94 (ver control_starlink.sh), que corta esa
# captura. Sin captura activa que proteger, siempre se verifica contra el HW
# real, aunque el objetivo ya coincida con la cache — de lo contrario
# STATE_FILE puede quedar desactualizado indefinidamente si el rele cambia de
# estado por fuera de este script (ver HISTORIAL_STARLINK.md, pulsos
# espurios con Starlink real conectado).
#
# Con --forzar (uso: boot, via asegurar_mux_ps10.sh): siempre llama a
# control_starlink.sh, que verifica el HW de verdad. Hace falta en el boot
# porque habilitar el mux de PS_MIO10 puede togglear el rele solo (ver
# HISTORIAL_STARLINK.md) — un mismatch entre STATE_FILE cacheado y el HW
# real que la comparacion liviana de abajo no detectaria.
#
# Con --reconciliar (uso: solo starlink-reconciliador.service): reenvia el
# flag a control_starlink.sh, que exige ver el mismo desacuerdo en dos
# ciclos seguidos (~10 min) antes de corregirlo — le da margen a alguien que
# uso el boton fisico fuera de horario a entrar por SSH y fijar modo manual
# antes de que se revierta solo. Los timers de horario y los comandos
# manuales NO pasan este flag, corrigen de inmediato como siempre.
#
# Con el modo evento (modo-evento.service, medicion 24h) activo: verificar
# por HW exige cortar la medicion (control_starlink.sh la detiene y la
# reanuda), asi que si el objetivo coincide con STATE_FILE no se verifica,
# salvo una verificacion real cada starlink.verificacion_hw_con_modo_evento_h
# horas mientras el objetivo es "on" (0 = nunca; solo al conmutar). Contra un
# pulso espurio que apague Starlink de dia, sin esto no se corrige hasta el
# proximo hora_on.
#
# starlink.sin_rele (config_campo.json, default false): este script es el
# unico camino real hacia control_starlink.sh (timers de horario,
# reconciliador, boot via --forzar, y starlink_manual.sh pasan todos por
# aca) — con la bandera en true, no-opea de entrada, antes de calcular el
# objetivo o mirar si hay captura activa. Para placa en banco sin rele
# fisico conectado, donde el feedback por HW nunca puede confirmar el pulso
# (ver control_starlink.sh) y por eso el reconciliador reintenta sin parar.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps10_common.sh"   # PATRON_CAPTURA
STATE_FILE=$(python3 "$CFG" rutas.state_file)
VERIF_FILE=$(python3 "$CFG" rutas.ultima_verificacion_rele_file)
VERIF_MODO_EVENTO_H=$(python3 "$CFG" starlink.verificacion_hw_con_modo_evento_h)

if [ "$(python3 "$CFG" starlink.sin_rele)" = "True" ]; then
  echo "starlink.sin_rele=true, no se controla el rele (placa en banco sin rele fisico)"
  exit 0
fi

FORZAR=0
RECONCILIAR=0
for arg in "$@"; do
  case "$arg" in
    --forzar) FORZAR=1 ;;
    --reconciliar) RECONCILIAR=1 ;;
  esac
done

OBJETIVO=$("$DIR/decidir_objetivo.sh")

CAPTURA_ACTIVA=0
pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1 && CAPTURA_ACTIVA=1

if [ "$FORZAR" -eq 0 ] && [ "$CAPTURA_ACTIVA" -eq 1 ] && [ "$(cat "$STATE_FILE" 2>/dev/null || echo '')" = "$OBJETIVO" ]; then
  echo "objetivo '$OBJETIVO' ya coincide con la ultima lectura real conocida y hay una captura activa, no se verifica por HW para no cortarla"
  exit 0
fi

MODO_EVENTO_ACTIVO=0
case "$(systemctl is-active modo-evento 2>/dev/null || true)" in
  active|activating|reloading) MODO_EVENTO_ACTIVO=1 ;;
esac

if [ "$FORZAR" -eq 0 ] && [ "$MODO_EVENTO_ACTIVO" -eq 1 ] && [ "$(cat "$STATE_FILE" 2>/dev/null || echo '')" = "$OBJETIVO" ]; then
  ultima=$(cat "$VERIF_FILE" 2>/dev/null || echo 0)
  [[ "$ultima" =~ ^[0-9]+$ ]] || ultima=0
  edad_s=$(( $(date +%s) - ultima ))
  if [ "$OBJETIVO" = "on" ] && [ "$VERIF_MODO_EVENTO_H" -gt 0 ] && [ "$edad_s" -ge $((VERIF_MODO_EVENTO_H * 3600)) ]; then
    echo "modo evento activo, verificacion periodica del rele (ultima hace ${edad_s}s)"
  else
    echo "objetivo '$OBJETIVO' ya coincide con la ultima lectura real conocida y el modo evento esta midiendo, no se verifica por HW para no cortarlo"
    exit 0
  fi
fi

ARGS=("$OBJETIVO")
[ "$RECONCILIAR" -eq 1 ] && ARGS+=(--reconciliar)
exec "$DIR/control_starlink.sh" "${ARGS[@]}"
