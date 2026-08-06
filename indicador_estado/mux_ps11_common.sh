#!/usr/bin/env bash
# mux_ps11_common.sh — constantes y funciones para dejar PS_MIO11 (E2 pin4,
# rol de fabrica SPI1 MISO) configurado como GPIO de salida. Pin elegido
# para el indicador de estado de la placa (ver memoria del proyecto,
# sec.106): los LEDs de la placa se descartaron porque su registro se
# reutiliza como factor de decimacion del ADC durante una captura
# (bitstream stream_app), y la API oficial de LEDs choca con
# streaming-server corriendo.
#
# OJO con el valor de MUX_GPIO: el campo de funcion de MIO_PIN_x es UN
# registro de 7 bits (bits[7:1]), no varios subcampos chicos — limpiarlo a
# medias deja el pin en una tercera funcion no intencional (el registro
# lee bien, pero el pin fisico no se mueve, sin ningun error visible).
# GPIO = ese campo completo en 0. Confirmado en HW real con analizador
# logico (sec.106 de la memoria del proyecto).

MONITOR=/opt/redpitaya/bin/monitor

MUX_REG=0xf800072c    # SLCR MIO_PIN_11
MUX_GPIO=0x1600       # campo de funcion (bits[7:1]) en 0 = GPIO, resto igual al valor de fabrica
DATA_REG=0xe000a040   # GPIO banco0 (MIO0-31), dato de salida — compartido con PS_MIO10 (rele de Starlink)
DIRM_REG=0xe000a204   # GPIO banco0, direccion
OEN_REG=0xe000a208    # GPIO banco0, habilitacion de salida
PS_BIT=0x800          # bit11 = MIO11

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

# Pulso: reposo en LOW, pulso como flanco de subida (0->1->0). A diferencia
# del rele (PS_MIO10, reposo invertido por el HW especifico de esa placa,
# ver starlink_remoto/control_starlink.sh), este pin no tiene nada fisico
# enganchado todavia — no hay razon para invertir la polaridad. Siempre
# read-modify-write sobre DATA_REG para no tocar el bit10 (rele) ni
# cualquier otro bit ajeno.
pulsar_ps11() {
  local base=$(( $("$MONITOR" "$DATA_REG") & ~PS_BIT & 0xFFFFFFFF ))
  "$MONITOR" "$DATA_REG" "$(printf '0x%x' $((base | PS_BIT)))"
  sleep "$PULSO_S"
  "$MONITOR" "$DATA_REG" "$(printf '0x%x' "$base")"
}
