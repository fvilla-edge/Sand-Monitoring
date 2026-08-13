#!/usr/bin/env bash
# control_starlink.sh — togglea el rele biestable que corta/da paso a Starlink.
#
# Rele biestable por flanco: un pulso (via PS_MIO10, reposo LOW) lo cambia de
# estado sin importar cual era antes. El mux de PS_MIO10 no persiste un
# reboot (vuelve a SPI1_MOSI) y habilitar su salida por primera vez togglea
# el rele solo (glitch real, confirmado con analizador) — por eso ese
# reconfigurado corre aislado al boot (starlink-mux-ps10.service), nunca
# junto a un pulso intencional (si se mezclan, se cancelan y el pedido
# termina sin efecto). asegurar_mux_gpio/asegurar_salida_ps mas abajo son
# red de seguridad idempotente por si esa unit no corrio.
#
# Feedback (DIO2_P) cableado via transistor NPN en emisor comun (el pad da
# 0.15V/1.8V, insuficiente para logica limpia) — la lectura sale invertida:
# bit en alto = rele en "off". Solo existe en el bitstream default (v0.94);
# con stream_app el nivel no sobrevive el cambio, por eso se fuerza v0.94
# siempre, cortando la captura activa antes. El pulso de control (PS_MIO10)
# no depende de esto.
#
# En "on" reinicia ntpsec para forzar un STEP de reloj (sin RTC, llega
# desviado a cada ventana). El atajo de mas abajo evita el pulso si el rele
# ya esta, de verdad, en el estado pedido — STATE_FILE es solo copia
# informativa de la ultima lectura real, nunca la fuente de la decision.

set -euo pipefail

CFG=/root/scripts_campo_comun/cfg.py

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps10_common.sh"   # MONITOR, MUX_REG/MUX_GPIO, DATA/DIRM/OEN_REG, PS_BIT, asegurar_mux_gpio(), asegurar_salida_ps()

# Invariantes de hardware/firmware, acopladas al bitstream v0.94 — quedan
# hardcodeadas a proposito, no en config_campo.json (ver comentario arriba).
OVERLAY=/opt/redpitaya/sbin/overlay.sh
LOADED_INF=/tmp/loaded_fpga.inf
FPGA_NAME=v0.94
IN_REG=0x40000020    # entrada P (bit2 = DIO2_P, feedback del rele)
DIO2_BIT=0x4
PULSO_S=0.2   # ancho del pulso — 19ms ya alcanzo a togglear en la placa real, esto deja margen

# Parametros operativos — ver scripts_campo_comun/config_campo.json
STATE_FILE=$(python3 "$CFG" rutas.state_file)
TIMEOUT_STOP=$(python3 "$CFG" starlink.timeout_stop_s)   # seg de margen para el corte limpio, mayor al chunk mas largo que se use en campo
FALLOS_FILE=$(python3 "$CFG" rutas.fallos_consecutivos_file)
UMBRAL_ALERTA=$(python3 "$CFG" starlink.alerta_fallos_consecutivos)
AVISOS_DIR=$(python3 "$CFG" rutas.avisos_pendientes_dir)

ACCION="${1:-}"
case "$ACCION" in
  on|off) ;;
  *)
    echo "uso: $0 {on|off}" >&2
    exit 1
    ;;
esac

# Serializa instancias concurrentes de este script (ej. los timers on/off
# disparando juntos tras un salto de reloj, ver HISTORIAL_STARLINK.md) — sin
# esto, dos procesos pueden hacer un read-modify-write concurrente sobre el
# mismo registro de HW y pisarse entre si, ademas de competir por cual pulso
# queda como estado final.
LOCKFILE=/run/lock/starlink_rele.lock
exec 9>"$LOCKFILE"
if ! flock -w 180 9; then
  echo "ADVERTENCIA: no se pudo tomar el lock del rele en 180s (¿otra instancia colgada?)" >&2
  exit 1
fi

# Precondicion: bitstream v0.94 ya cargado (ver header).
leer_estado_real() {
  local val=$("$MONITOR" "$IN_REG")
  if (( (val & DIO2_BIT) != 0 )); then
    echo off
  else
    echo on
  fi
}

# En prueba (pulsos espurios con Starlink real conectado, ver
# HISTORIAL_STARLINK.md): polaridad invertida — reposo en 1 en vez de 0, pulso
# como flanco de bajada (1->0->1) en vez de subida. El header de este archivo
# (linea 4, "reposo LOW") describe la polaridad ORIGINAL, no esta — no
# cambia el glitch conocido del primer enable del mux al boot, ese pasa antes
# de que este reposo importe.
#
# Para volver a la polaridad original: comentar el bloque "invertido" de
# abajo y descomentar el bloque "original" (son mutuamente excluyentes, no
# dejar los dos activos a la vez).
pulsar_ps() {
  # --- original (comentado): reposo en 0, pulso como flanco de subida (0->1->0) ---
  # local base=$(( ($("$MONITOR" "$DATA_REG") & ~PS_BIT) & 0xFFFFFFFF ))
  # "$MONITOR" "$DATA_REG" "$(printf '0x%x' "$base")"
  # sleep "$PULSO_S"
  # "$MONITOR" "$DATA_REG" "$(printf '0x%x' $((base | PS_BIT)))"
  # sleep "$PULSO_S"
  # "$MONITOR" "$DATA_REG" "$(printf '0x%x' "$base")"

  # --- invertido, activo: reposo en 1, pulso como flanco de bajada (1->0->1) ---
  local base=$(( ($("$MONITOR" "$DATA_REG") | PS_BIT) & 0xFFFFFFFF ))
  "$MONITOR" "$DATA_REG" "$(printf '0x%x' "$base")"
  sleep "$PULSO_S"
  "$MONITOR" "$DATA_REG" "$(printf '0x%x' $((base & ~PS_BIT)))"
  sleep "$PULSO_S"
  "$MONITOR" "$DATA_REG" "$(printf '0x%x' "$base")"
}

# Cuenta fallos consecutivos de este script en confirmar el estado pedido
# (persistido en FALLOS_FILE, ver header — cada invocacion es un proceso
# nuevo, sin esto no hay forma de distinguir entre invocaciones separadas el
# glitch normal del boot (se autocorrige en el proximo tick del reconciliador)
# de un rele trabado de verdad). Encola un aviso (mismo mecanismo que usa
# capturar_stream.py) una sola vez, justo al cruzar el umbral — no en cada
# tick posterior mientras siga fallando.
actualizar_contador_fallos() {
  local fallo="$1" actual
  if [ "$fallo" -eq 0 ]; then
    echo 0 > "$FALLOS_FILE"
    return
  fi
  actual=$(cat "$FALLOS_FILE" 2>/dev/null || echo 0)
  [[ "$actual" =~ ^[0-9]+$ ]] || actual=0
  actual=$((actual + 1))
  echo "$actual" > "$FALLOS_FILE"
  if [ "$actual" -eq "$UMBRAL_ALERTA" ]; then
    mkdir -p "$AVISOS_DIR"
    echo "{\"evento\": \"rele_sin_confirmar\", \"objetivo\": \"$ACCION\", \"fallos_consecutivos\": $actual}" \
      > "$AVISOS_DIR/alerta_rele_$(date +%Y%m%d_%H%M%S).json"
    echo "ALERTA: $actual fallos consecutivos sin confirmar el rele, aviso encolado" >&2
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

# Reprogramar resetea los registros de logica programable (incluye IN_REG,
# el feedback) y genera un pulso real en DIO2_P — por eso se evita si v0.94
# ya esta cargado (ver header). Ya no afecta al pulso de control (PS_MIO10).
if [ "$(cat "$LOADED_INF" 2>/dev/null)" != "$FPGA_NAME" ]; then
  "$OVERLAY" "$FPGA_NAME"
fi

# Atajo obligatorio, no optimizacion (ver header).
ESTADO_REAL=$(leer_estado_real)
if [ "$ESTADO_REAL" = "$ACCION" ]; then
  echo "OK: el rele ya esta en '$ACCION' (verificado por HW), no hago nada"
  echo "$ESTADO_REAL" > "$STATE_FILE"
  actualizar_contador_fallos 0
  exit 0
fi

asegurar_mux_gpio   # no-op normalmente (ver header) — starlink-mux-ps10.service ya lo hizo al boot
asegurar_salida_ps  # idem
pulsar_ps

# Se re-lee (no se asume que el pulso funciono) para que STATE_FILE quede
# con el estado real del rele, no con lo que se pidio.
ESTADO_REAL=$(leer_estado_real)
FALLO=0
if [ "$ESTADO_REAL" != "$ACCION" ]; then
  echo "ADVERTENCIA: se pidio '$ACCION' pero el feedback del rele sigue en '$ESTADO_REAL' despues del pulso" >&2
  FALLO=1
else
  echo "OK: rele ahora en '$ESTADO_REAL' (confirmado por HW)"
fi
actualizar_contador_fallos "$FALLO"

if [ "$ACCION" = "on" ]; then
  systemctl restart ntpsec
fi

mkdir -p "$(dirname "$STATE_FILE")"
echo "$ESTADO_REAL" > "$STATE_FILE"
sync   # sin esto un corte de luz justo despues del pulso puede perder este cambio (probado: ext4 tarda hasta 5s en confirmarlo solo)

exit "$FALLO"
