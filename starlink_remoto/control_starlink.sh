#!/usr/bin/env bash
# control_starlink.sh — enciende/apaga la fuente del Starlink via el rele.
#
# Corre EN la Red Pitaya. Escribe directo al registro de housekeeping con
# `monitor` (acceso a /dev/mem) en vez de usar la libreria rp/rp_LEDSetState:
# rp_Init() inicializa tambien el osciloscopio, y choca (Bus error) con el
# streaming-server cuando hay una captura corriendo, que es el caso normal
# en campo. `monitor` no toca esa region de memoria.
#
# Por ahora escribe el registro de LED0 (0x40000030) para simular el rele
# sin tener el hardware conectado. Cuando este el rele real, cambiar solo
# el registro/valor de ON/OFF aca abajo — el resto (timers, systemd) no
# cambia.
#
# En "on" reinicia ntpsec: confirmado en banco que ante un reinicio hace
# un STEP inmediato (<10s) en vez de esperar el ciclo de poll normal, que
# puede tardar minutos. Sin RTC, la placa arranca cada ventana con reloj
# desviado, asi que forzar el restart es lo que garantiza el resync rapido.

set -euo pipefail

MONITOR=/opt/redpitaya/bin/monitor
LED_REG=0x40000030

case "${1:-}" in
  on)
    "$MONITOR" "$LED_REG" 0x1
    systemctl restart ntpsec
    ;;
  off)
    "$MONITOR" "$LED_REG" 0x0
    ;;
  *)
    echo "uso: $0 {on|off}" >&2
    exit 1
    ;;
esac
