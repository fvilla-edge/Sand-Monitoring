#!/usr/bin/env bash
# control_starlink.sh — enciende/apaga el GPIO que va a usar el rele.
#
# INTERIM, no es el diseño final: todavia no hay rele fisico. Esto solo prueba
# que el toggle llega al pin DIO0_P (confirmado con analizador logico, ver
# PLAN_STARLINK.md sec. 2026-07-15). Cuando llegue el rele biestable, esto se
# reemplaza por pulsos cortos en vez de niveles sostenidos.
#
# El registro que controla DIO0_P (Housekeeping) solo existe en el bitstream
# default (v0.94) — si streaming-server esta corriendo (bitstream stream_app),
# cambiar de bitstream para hacer el toggle LE CORTA la captura en curso (el
# nivel no sobrevive el cambio, confirmado). Por eso, si hay una captura
# corriendo, se le pide un corte limpio (SIGTERM a capturar_stream.py, el
# mismo handler que usa Ctrl+C) ANTES de tocar el bitstream: asi termina el
# chunk en curso y sale con exit 0, y relanzar_captura.sh no la vuelve a
# levantar peleando contra este script. No se vuelve a cargar stream_app
# despues: capturar_stream.py ya se encarga de eso la proxima vez que
# arranque una captura (asegurar_servidor en campo_common.py).
#
# En "on" reinicia ntpsec: confirmado en banco que ante un reinicio hace
# un STEP inmediato (<10s) en vez de esperar el ciclo de poll normal, que
# puede tardar minutos. Sin RTC, la placa arranca cada ventana con reloj
# desviado, asi que forzar el restart es lo que garantiza el resync rapido.
#
# Idempotencia (STATE_FILE): sin esto, pedir "on" estando ya en "on" (o
# "off" ya en "off") igual reprograma la FPGA y genera el mismo pulso
# espurio que el cambio de bitstream real (confirmado con analizador
# logico, 2026-07-15). El archivo de estado NO sobrevive un reinicio de
# forma confiable (el registro de hardware puede volver a su default sin
# que el archivo se entere) — aceptable porque este script es interino
# (ver nota arriba) y con rele biestable el estado fisico lo sostiene el
# rele, no el pin.

set -euo pipefail

MONITOR=/opt/redpitaya/bin/monitor
OVERLAY=/opt/redpitaya/sbin/overlay.sh
DIR_REG=0x40000010   # direccion P (bit0 = DIO0_P)
OUT_REG=0x40000018   # salida P (bit0 = DIO0_P)
STATE_FILE=/root/starlink_remoto/estado
TIMEOUT_STOP=150      # seg de margen para el corte limpio, > tope de duracion_chunk (2 min, sec.29)

ACCION="${1:-}"
case "$ACCION" in
  on|off) ;;
  *)
    echo "uso: $0 {on|off}" >&2
    exit 1
    ;;
esac

# Si hay una captura corriendo, pedirle un corte limpio antes de tocar el
# bitstream. SIGTERM = mismo handler que Ctrl+C (instalar_manejador_stop en
# campo_common.py): termina el chunk en curso y sale con exit 0, para que
# relanzar_captura.sh NO la relance. Si no corta a tiempo, se fuerza.
#
# El patron matchea "python3 ... capturar_stream.py" a proposito, NO
# "capturar_stream.py" solo: relanzar_captura.sh invoca el script pasandole
# la ruta como argumento, asi que su propia linea de comando (bash
# relanzar_captura.sh /ruta/capturar_stream.py ...) tambien contiene ese
# string — un pkill -f mas amplio manda SIGTERM al supervisor tambien,
# matandolo antes de que corra su propio chequeo de exit code (confirmado
# en prueba real, 2026-07-16). Con "python3.*capturar_stream" solo pega en
# el proceso python, y relanzar_captura.sh ve el exit 0 y decide solo no
# relanzar.
PATRON_CAPTURA='python3.*capturar_stream\.py'

parar_captura_si_corre() {
  if ! pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1; then
    return
  fi

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

  # streaming-server queda huerfano: no se cae solo al terminar capturar_stream.py
  if pgrep -f streaming-server >/dev/null 2>&1; then
    pkill -TERM -f streaming-server 2>/dev/null || true
    sleep 2
    pkill -9 -f streaming-server 2>/dev/null || true
  fi
}

# Reprogramar la FPGA (overlay.sh) causa una caida de ~800ms en el pin sin
# importar el estado previo (hueco de tri-state, ver nota arriba). Si ya
# estamos en el estado pedido no hay que tocar nada: evita ese pulso
# espurio en vez de solo evitarlo "en teoria".
if [ "$(cat "$STATE_FILE" 2>/dev/null || true)" = "$ACCION" ]; then
  echo "ya esta en '$ACCION', no hago nada"
  exit 0
fi

parar_captura_si_corre

"$OVERLAY" v0.94
"$MONITOR" "$DIR_REG" 0x1

case "$ACCION" in
  on)
    "$MONITOR" "$OUT_REG" 0x1
    systemctl restart ntpsec
    ;;
  off)
    "$MONITOR" "$OUT_REG" 0x0
    ;;
esac

mkdir -p "$(dirname "$STATE_FILE")"
echo "$ACCION" > "$STATE_FILE"
