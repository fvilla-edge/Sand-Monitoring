#!/usr/bin/env bash
# mux_ps10_common.sh — constantes y funciones para dejar PS_MIO10 configurado
# como GPIO de salida. Compartido por dos consumidores:
#   - starlink-mux-ps10.service: lo aplica una sola vez al boot, aislado de
#     cualquier pulso (ver HISTORIAL_STARLINK.md — mezclar mux+pulso en la misma
#     corrida generaba un toggle accidental del rele, ademas del intencional).
#   - control_starlink.sh: lo vuelve a llamar como red de seguridad
#     idempotente (no hace nada si ya esta configurado), por si la unit de
#     boot todavia no corrio o fallo.

MONITOR=/opt/redpitaya/bin/monitor

MUX_REG=0xf8000728    # SLCR MIO_PIN_10
MUX_GPIO=0x1600       # L3_SEL=000 (GPIO), resto igual al valor de fabrica
DATA_REG=0xe000a040   # GPIO banco0 (MIO0-31), dato de salida
DIRM_REG=0xe000a204   # GPIO banco0, direccion
OEN_REG=0xe000a208    # GPIO banco0, habilitacion de salida
PS_BIT=0x400          # bit10 = MIO10

asegurar_mux_gpio() {
  if [ "$("$MONITOR" "$MUX_REG")" != "$(printf '0x%08x' "$MUX_GPIO")" ]; then
    "$MONITOR" "$MUX_REG" "$MUX_GPIO"
  fi
}

asegurar_salida_ps() {
  local dirm=$("$MONITOR" "$DIRM_REG")
  "$MONITOR" "$DIRM_REG" "$(printf '0x%x' $((dirm | PS_BIT)))"
  local oen=$("$MONITOR" "$OEN_REG")
  "$MONITOR" "$OEN_REG" "$(printf '0x%x' $((oen | PS_BIT)))"
}
