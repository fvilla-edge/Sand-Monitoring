#!/usr/bin/env bash
# control_starlink.sh — enciende/apaga el GPIO que va a usar el rele.
#
# INTERIM: todavia no hay rele fisico, esto solo mueve el nivel de DIO0_P.
# Cuando llegue el rele biestable se reemplaza por un pulso corto.
#
# El registro de DIO0_P solo existe en el bitstream default (v0.94); con
# streaming-server corriendo (bitstream stream_app) esa misma direccion es
# otra cosa, y el nivel no sobrevive el cambio de bitstream. Por eso hace
# falta forzar v0.94 siempre, y por eso una captura activa se corta primero.
#
# En "on" reinicia ntpsec para forzar un STEP inmediato del reloj (la placa
# no tiene RTC, asi que llega a cada ventana con reloj desviado).
#
# STATE_FILE evita reprogramar la FPGA (y su pulso espurio de tri-state) si
# ya estamos en el estado pedido.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py

# Invariantes de hardware/firmware, acopladas al bitstream v0.94 — quedan
# hardcodeadas a proposito, no en config_campo.json (ver comentario arriba).
MONITOR=/opt/redpitaya/bin/monitor
OVERLAY=/opt/redpitaya/sbin/overlay.sh
DIR_REG=0x40000010   # direccion P (bit0 = DIO0_P)
OUT_REG=0x40000018   # salida P (bit0 = DIO0_P)

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

# Evita reprogramar la FPGA si ya estamos en el estado pedido (y con eso, el
# pulso espurio de tri-state que genera cada reprogramacion).
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
