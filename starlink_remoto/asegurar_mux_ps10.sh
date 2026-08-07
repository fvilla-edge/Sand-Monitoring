#!/usr/bin/env bash
# asegurar_mux_ps10.sh — corre una sola vez al boot (starlink-mux-ps10.service).
#
# Configurar el mux+salida de PS_MIO10 por primera vez tras un reboot puede
# togglear el rele solo, entre 1 y 2 veces segun la corrida (no
# deterministico, confirmado con analizador en placa real) — por eso, en vez
# de asumir en que estado queda el rele, se aplica el objetivo calculado por
# aplicar_objetivo.sh (manual > reloj no confiable > horario — ver ese script
# y decidir_objetivo.sh). Esa llamada no vuelve a tocar el mux (ya quedo
# configurado arriba, sus propias asegurar_mux_gpio/asegurar_salida_ps son
# no-op) — solo lee el feedback real y pulsa una sola vez, limpio, si los
# toggles accidentales de arriba lo dejaron distinto de lo pedido.
#
# Antes esto restauraba STATE_FILE a ciegas; el problema es que si la placa
# estuvo apagada mucho tiempo (sin RTC) y arranca con el reloj atrasado, el
# horario normal no es confiable todavia — aplicar_objetivo.sh ya contempla
# ese caso (rescate por NTPSynchronized=no) antes de mirar STATE_FILE/horario.
#
# Si el pulso de --forzar no logra confirmar el estado pedido (ej. sin rele
# fisico conectado, o un glitch transitorio), este script NO debe fallar: al
# ser oneshot sin RemainAfterExit efectivo tras un error, systemd lo deja
# "no activo" y cada tick del reconciliador de 5 min (starlink-aplicar-
# objetivo.service Requires= esta unit) lo vuelve a disparar completo — eso
# incluye el corte forzado de cualquier captura activa (parar_captura_si_corre
# en control_starlink.sh), cada 5 min, indefinidamente, en vez de una sola
# vez al boot como dice el nombre de este archivo. El estado real del rele
# ya queda registrado en STATE_FILE (control_starlink.sh) sea cual sea el
# resultado del pulso; la advertencia se loguea igual, solo no tira el script.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/mux_ps10_common.sh"

asegurar_mux_gpio
asegurar_salida_ps

if ! "$DIR/aplicar_objetivo.sh" --forzar; then
  echo "ADVERTENCIA: aplicar_objetivo.sh --forzar termino con error (ver arriba) — no se reintenta hasta el proximo boot" >&2
fi
