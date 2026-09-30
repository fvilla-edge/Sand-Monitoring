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

# El patron exige el prefijo "python3" para no matchear tambien la linea de
# comando de relanzar_captura.sh (que incluye la ruta a capturar_stream.py
# como argumento) — si lo matchea, un pkill -f mata al supervisor junto con
# el proceso python, y este nunca llega a ver el exit code para decidir si
# relanzar o no. Compartido por control_starlink.sh (para cortarla) y
# aplicar_objetivo.sh (para saber si hay que protegerla del reconciliador).
PATRON_CAPTURA='python3.*capturar_stream\.py'

# Lectura directa del feedback del rele (DIO2_P) con el bitstream propio que
# la trae (repo fpga_pitaya, rama lectura-dio): rp_gpio expone los pines en
# 0x40200078 (DIO2_P = bit2, misma mascara que 0x40000020 de v0.94) y deja
# DIO2_P siempre como entrada, asi que se lee sin frenar la captura ni cargar
# v0.94. 0x4020007C es un ID fijo: en cualquier otro bitstream (v0.94,
# stream_app del vendor o el propio sin este cambio) no da este valor, y ahi
# 0x78 no sirve (el propio viejo lee 0, que pasaria por "on").
DIO_REG=0x40200078
DIO_ID_REG=0x4020007C
DIO_ID=0x534d0001      # "SM" + version 1 del bloque dio_lectura

# Solo se lee el ID con un bitstream ya cargado: overlay.sh borra
# /tmp/loaded_fpga.inf antes de programar y lo escribe al terminar, y leer la
# logica programable mientras se reprograma (p.ej. el modo evento cargando el
# suyo al arrancar) puede colgar el bus. Con v0.94 no hace falta leer: no lo
# tiene (y en 0x40200000 esta el generador de señales).
lectura_rele_directa() {
  local inf
  inf=$(cat /tmp/loaded_fpga.inf 2>/dev/null) || return 1
  case "$inf" in
    ""|v0.94) return 1 ;;
  esac
  [ "$("$MONITOR" "$DIO_ID_REG" 2>/dev/null)" = "$DIO_ID" ]
}

# Antena Starlink: el rele corta la alimentacion del kit entero (dish +
# router), asi que si el dish responde en su IP local el rele esta en "on" de
# verdad, diga lo que diga el feedback. Prueba independiente para no pulsar
# a "on" algo que ya esta prendido (lectura al reves o cable del feedback
# suelto = Starlink apagado de dia). Misma direccion que starlink_api.host.
ANTENA_HOST=192.168.100.1
ANTENA_PUERTO=9200
# Solo ensayos (placa de pruebas, sin Starlink): "responde" o "no_responde"
# reemplaza la prueba real. En /run, se borra solo al reiniciar.
ANTENA_PRUEBA_FILE=/run/starlink_antena_prueba

antena_responde() {
  local forzado
  if forzado=$(cat "$ANTENA_PRUEBA_FILE" 2>/dev/null); then
    echo "ADVERTENCIA: respuesta de la antena forzada por $ANTENA_PRUEBA_FILE ('$forzado'), solo para ensayos" >&2
    [ "$forzado" = "responde" ]
    return
  fi
  timeout 3 bash -c "exec 3<>/dev/tcp/$ANTENA_HOST/$ANTENA_PUERTO" 2>/dev/null
}

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
