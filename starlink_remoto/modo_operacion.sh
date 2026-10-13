#!/usr/bin/env bash
# modo_operacion.sh [ventana|permanente] — modo de operacion de Starlink
# (docs/plan_modos_starlink.md, Fase 1).
#
#   sin argumento        imprime el modo vigente ("ventana" o "permanente")
#   ventana|permanente   lo guarda en rutas.modo_operacion_file
#
# El modo vigente es el del archivo si existe y es valido; si no, el
# starlink.modo_defecto de config_campo.json (y si ese tampoco es valido,
# "ventana" con un aviso: es el que menos bateria gasta). El archivo lo
# escribe este script (comando "modo" de Losant, o a mano por SSH); persiste
# entre reinicios, con el timestamp en la 2da linea solo para diagnostico.
#
# Solo guarda/lee: no toca el rele. Quien decide on/off con el modo es
# decidir_objetivo.sh.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py
# Una sola llamada a cfg.py (un valor por linea): cada python3 cuesta ~0.4s de CPU en la placa
CFG_VALORES=$(python3 "$CFG" rutas.modo_operacion_file starlink.modo_defecto)
{ read -r MODO_FILE; read -r MODO_DEFECTO; } <<< "$CFG_VALORES"

valido() { [ "$1" = "ventana" ] || [ "$1" = "permanente" ]; }

ACCION="${1:-}"
case "$ACCION" in
  ventana|permanente)
    tmp="$MODO_FILE.tmp"
    printf '%s\n%s\n' "$ACCION" "$(date +%s)" > "$tmp"
    mv "$tmp" "$MODO_FILE"
    sync   # sin esto un corte de luz justo despues puede perder el cambio (igual que starlink_manual.sh)
    echo "$ACCION"
    ;;
  "")
    MODO=$(sed -n '1p' "$MODO_FILE" 2>/dev/null || true)
    if valido "$MODO"; then
      echo "$MODO"
    elif valido "$MODO_DEFECTO"; then
      echo "$MODO_DEFECTO"
    else
      echo "AVISO: starlink.modo_defecto='$MODO_DEFECTO' no es valido, se usa 'ventana'" >&2
      echo "ventana"
    fi
    ;;
  *)
    echo "uso: $0 [ventana|permanente]" >&2
    exit 1
    ;;
esac
