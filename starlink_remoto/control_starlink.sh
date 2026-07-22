#!/usr/bin/env bash
# control_starlink.sh — togglea el rele biestable que corta/da paso a Starlink.
#
# El rele es biestable por flanco (modulo "boton externo" en paralelo con su
# boton de a bordo): un pulso lo cambia de estado sin importar cual era antes,
# no hay nivel a sostener. DIO1_P queda en reposo LOW; un pulso a HIGH y de
# vuelta a LOW es lo que togglea. Sin realimentacion todavia (el modulo tiene
# un "pad indicador externo" que refleja su estado real, pendiente de cablear
# a otro DIO) — este script confia ciegamente en STATE_FILE para saber en que
# estado quedo el rele. Si algo externo lo togglea sin pasar por aca (boton
# fisico a mano, un pulso perdido/duplicado por un crash a mitad de camino),
# STATE_FILE queda desincronizado del estado real y el script hace lo
# contrario de lo pedido, en silencio, hasta agregar esa realimentacion.
#
# El registro de DIO1_P solo existe en el bitstream default (v0.94); con
# streaming-server corriendo (bitstream stream_app) esa misma direccion es
# otra cosa, y el nivel no sobrevive el cambio de bitstream. Por eso hace
# falta forzar v0.94 siempre, y por eso una captura activa se corta primero.
#
# En "on" reinicia ntpsec para forzar un STEP inmediato del reloj (la placa
# no tiene RTC, asi que llega a cada ventana con reloj desviado).
#
# STATE_FILE evita reprogramar la FPGA (y su pulso espurio de tri-state) si
# ya estamos en el estado pedido — pero SOLO evita eso. El corte de captura
# activa corre siempre, sin importar STATE_FILE: si alguien arranca una
# captura por fuera de este script (a mano, o systemd que la relanza), el
# archivo puede decir "off" mientras el bitstream sigue en stream_app, y ese
# desacople no se detecta salvo que se chequee de verdad si hay algo corriendo.

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
DIO1_BIT=0x2
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

# Se pone en 1 si parar_captura_si_corre encontro algo activo — invalida el
# atajo de STATE_FILE de mas abajo, porque prueba que el bitstream no estaba
# donde STATE_FILE decia que estaba.
HABIA_ACTIVO=0

parar_captura_si_corre() {
  # SIGTERM = mismo handler que Ctrl+C: corta el chunk en curso y sale con
  # exit 0, para que relanzar_captura.sh no la relance. Si no corta a
  # tiempo, se fuerza.
  if pgrep -f "$PATRON_CAPTURA" >/dev/null 2>&1; then
    HABIA_ACTIVO=1
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
    HABIA_ACTIVO=1
    pkill -TERM -f streaming-server 2>/dev/null || true
    sleep 2
    pkill -9 -f streaming-server 2>/dev/null || true
  fi
}

# Corre siempre, antes de mirar STATE_FILE — ver comentario arriba.
parar_captura_si_corre

# Evita reprogramar la FPGA si ya estamos en el estado pedido (y con eso, el
# pulso espurio de tri-state que genera cada reprogramacion) — pero solo si
# ademas no habia nada activo, porque si habia algo, el estado real no era
# el que STATE_FILE decia.
if [ "$HABIA_ACTIVO" -eq 0 ] && [ "$(cat "$STATE_FILE" 2>/dev/null || true)" = "$ACCION" ]; then
  echo "ya esta en '$ACCION', no hago nada"
  exit 0
fi

# Reprogramar la FPGA resetea los registros de la logica programable
# (incluido el housekeeping donde viven DIR_REG/OUT_REG), lo que genera un
# pulso real en el pin. Si v0.94 ya esta cargado, no reprogramar de nuevo.
if [ "$(cat "$LOADED_INF" 2>/dev/null)" != "$FPGA_NAME" ]; then
  "$OVERLAY" "$FPGA_NAME"
fi
"$MONITOR" "$DIR_REG" "$DIO1_BIT"

# Toggle: reposo LOW -> pulso HIGH -> vuelve a LOW. No asume el nivel previo
# del pin (puede venir de un reset de FPGA), lo fuerza a LOW antes de pulsar.
"$MONITOR" "$OUT_REG" 0x0
sleep "$PULSO_S"
"$MONITOR" "$OUT_REG" "$DIO1_BIT"
sleep "$PULSO_S"
"$MONITOR" "$OUT_REG" 0x0

if [ "$ACCION" = "on" ]; then
  systemctl restart ntpsec
fi

mkdir -p "$(dirname "$STATE_FILE")"
echo "$ACCION" > "$STATE_FILE"
