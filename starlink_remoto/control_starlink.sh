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
# nivel no sobrevive el cambio, confirmado). No se intenta parar/reiniciar
# streaming-server aca: capturar_stream.py ya se encarga de recargar
# stream_app solo la proxima vez que arranque una captura (asegurar_servidor
# en campo_common.py).
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

ACCION="${1:-}"
case "$ACCION" in
  on|off) ;;
  *)
    echo "uso: $0 {on|off}" >&2
    exit 1
    ;;
esac

# Reprogramar la FPGA (overlay.sh) causa una caida de ~800ms en el pin sin
# importar el estado previo (hueco de tri-state, ver nota arriba). Si ya
# estamos en el estado pedido no hay que tocar nada: evita ese pulso
# espurio en vez de solo evitarlo "en teoria".
if [ "$(cat "$STATE_FILE" 2>/dev/null || true)" = "$ACCION" ]; then
  echo "ya esta en '$ACCION', no hago nada"
  exit 0
fi

if pgrep -f streaming-server >/dev/null 2>&1; then
  echo "ADVERTENCIA: streaming-server esta corriendo, este cambio de bitstream le va a cortar la captura en curso" >&2
fi

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
