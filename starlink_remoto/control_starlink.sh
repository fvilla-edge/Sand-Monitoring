#!/usr/bin/env bash
# control_starlink.sh — togglea el rele biestable que corta/da paso a Starlink.
#
# El rele es biestable por flanco (modulo "boton externo" en paralelo con su
# boton de a bordo): un pulso lo cambia de estado sin importar cual era antes.
# DIO1_P en reposo LOW; pulso a HIGH y vuelta a LOW togglea. El "pad indicador
# externo" (LED de estado) esta cableado a DIO2_P via un transistor NPN en
# emisor comun (el pad solo da 0.15V/1.8V, insuficiente para logica limpia);
# la lectura sale invertida (transistor saturado con LED prendido = colector
# en LOW): bit en alto = rele en "off".
#
# El registro de DIO1_P solo existe en el bitstream default (v0.94); con
# streaming-server (stream_app) es otra cosa y el nivel no sobrevive el
# cambio — por eso se fuerza v0.94 siempre, cortando la captura activa antes.
#
# En "on" reinicia ntpsec para forzar un STEP inmediato del reloj (la placa
# no tiene RTC, asi que llega a cada ventana con reloj desviado).
#
# El atajo de mas abajo evita el pulso (y su vuelta al bitstream v0.94 en la
# proxima corrida) si el rele ya esta, de verdad, en el estado pedido —
# STATE_FILE queda solo como copia informativa de la ultima lectura real,
# nunca es la fuente de la decision.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py

# Invariantes de hardware/firmware, acopladas al bitstream v0.94 — quedan
# hardcodeadas a proposito, no en config_campo.json (ver comentario arriba).
MONITOR=/opt/redpitaya/bin/monitor
OVERLAY=/opt/redpitaya/sbin/overlay.sh
LOADED_INF=/tmp/loaded_fpga.inf
FPGA_NAME=v0.94
DIR_REG=0x40000010   # direccion P (bit1 = DIO1_P)
OUT_REG=0x40000018   # salida P (bit1 = DIO1_P)
IN_REG=0x40000020    # entrada P (bit2 = DIO2_P, feedback del rele)
DIO1_BIT=0x2
DIO2_BIT=0x4
PULSO_S=0.2   # ancho del pulso — 19ms ya alcanzo a togglear en la placa real, esto deja margen

# Parametros operativos — ver scripts_campo_comun/config_campo.json
STATE_FILE=$(python3 "$CFG" rutas.state_file)
TIMEOUT_STOP=$(python3 "$CFG" starlink.timeout_stop_s)   # seg de margen para el corte limpio, mayor al chunk mas largo que se use en campo

ACCION="${1:-}"
case "$ACCION" in
  on|off) ;;
  *)
    echo "uso: $0 {on|off}" >&2
    exit 1
    ;;
esac

# El patron exige el prefijo "python3" para no matchear tambien la linea de
# comando de relanzar_captura.sh (que incluye la ruta a capturar_stream.py
# como argumento) — si lo matchea, un pkill -f mata al supervisor junto con
# el proceso python, y este nunca llega a ver el exit code para decidir si
# relanzar o no.
PATRON_CAPTURA='python3.*capturar_stream\.py'

# Precondicion: bitstream v0.94 ya cargado (ver header).
leer_estado_real() {
  local val=$("$MONITOR" "$IN_REG")
  if (( (val & DIO2_BIT) != 0 )); then
    echo off
  else
    echo on
  fi
}

parar_captura_si_corre() {
  # SIGTERM = mismo handler que Ctrl+C: corta el chunk en curso y sale con
  # exit 0, para que relanzar_captura.sh no la relance. Si no corta a
  # tiempo, se fuerza.
  if pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1; then
    echo "captura en curso, pidiendo corte limpio (SIGTERM, como Ctrl+C)..."
    pkill -TERM -f "$PATRON_CAPTURA" 2>/dev/null || true

    esperado=0
    while pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1; do
      if [ "$esperado" -ge "$TIMEOUT_STOP" ]; then
        echo "ADVERTENCIA: capturar_stream.py no cortó en ${TIMEOUT_STOP}s, forzando" >&2
        pkill -9 -f "$PATRON_CAPTURA" 2>/dev/null || true
        break
      fi
      sleep 2
      esperado=$((esperado + 2))
    done
  fi

  # streaming-server no muere solo con capturar_stream.py, ni limpio ni
  # forzado — queda huerfano en stream_app aunque ya no haya ninguna
  # captura activa. Por eso este chequeo es incondicional, no solo dentro
  # del if de arriba.
  if pgrep -f streaming-server >/dev/null 2>&1; then
    pkill -TERM -f streaming-server 2>/dev/null || true
    sleep 2
    pkill -9 -f streaming-server 2>/dev/null || true
  fi
}

# Corre siempre, antes de reprogramar/leer nada.
parar_captura_si_corre

# Reprogramar resetea los registros de logica programable (incluye
# DIR_REG/OUT_REG/IN_REG) y genera un pulso real en el pin — por eso se
# evita si v0.94 ya esta cargado (ver header).
if [ "$(cat "$LOADED_INF" 2>/dev/null)" != "$FPGA_NAME" ]; then
  "$OVERLAY" "$FPGA_NAME"
fi

# Atajo obligatorio, no optimizacion (ver header).
ESTADO_REAL=$(leer_estado_real)
if [ "$ESTADO_REAL" = "$ACCION" ]; then
  echo "el rele ya esta en '$ACCION' (verificado por HW), no hago nada"
  echo "$ESTADO_REAL" > "$STATE_FILE"
  exit 0
fi

"$MONITOR" "$DIR_REG" "$DIO1_BIT"

# Toggle: reposo LOW -> pulso HIGH -> vuelve a LOW. No asume el nivel previo
# del pin (puede venir de un reset de FPGA), lo fuerza a LOW antes de pulsar.
"$MONITOR" "$OUT_REG" 0x0
sleep "$PULSO_S"
"$MONITOR" "$OUT_REG" "$DIO1_BIT"
sleep "$PULSO_S"
"$MONITOR" "$OUT_REG" 0x0

# Se re-lee (no se asume que el pulso funciono) para que STATE_FILE quede
# con el estado real del rele, no con lo que se pidio.
ESTADO_REAL=$(leer_estado_real)
if [ "$ESTADO_REAL" != "$ACCION" ]; then
  echo "ADVERTENCIA: se pidio '$ACCION' pero el feedback del rele sigue en '$ESTADO_REAL' despues del pulso" >&2
fi

if [ "$ACCION" = "on" ]; then
  systemctl restart ntpsec
fi

mkdir -p "$(dirname "$STATE_FILE")"
echo "$ESTADO_REAL" > "$STATE_FILE"
