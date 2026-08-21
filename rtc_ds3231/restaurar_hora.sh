#!/usr/bin/env bash
# restaurar_hora.sh — al boot, setea el reloj del sistema desde el RTC DS3231.
# Corre antes que ntpsec y que cualquier logica de Starlink (ver rtc-restaurar.service).
# Si el RTC no responde, loguea advertencia y sale 0 — no debe bloquear el boot.

set -uo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BUS=$(python3 "$CFG" rtc_ds3231.bus)
ADDR=$(python3 "$CFG" rtc_ds3231.direccion)

EPOCH=$(python3 "$DIR/leer_epoch.py" --bus "$BUS" --addr "$ADDR" 2>&1)
if [ $? -ne 0 ]; then
  echo "ADVERTENCIA: no se pudo leer el RTC DS3231, se mantiene la hora actual del sistema. $EPOCH" >&2
  exit 0
fi

date -u -s "@$EPOCH" >/dev/null
echo "Hora del sistema restaurada desde el RTC DS3231: $(date -u -Iseconds)"
