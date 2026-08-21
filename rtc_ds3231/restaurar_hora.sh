#!/usr/bin/env bash
# restaurar_hora.sh — al boot, setea el reloj del sistema desde el RTC DS3231.
# Corre antes que ntpsec y que cualquier logica de Starlink (ver rtc-restaurar.service).
# Si el RTC no responde, loguea advertencia y sale 0 — no debe bloquear el boot.
#
# Deja $FLAG_OK (tmpfs) cuando la restauracion funciono — lo lee decidir_objetivo.sh
# para confiar en el horario aunque NTPSynchronized todavia diga "no". Al vivir en
# /run se resetea solo en cada boot real; se borra al principio para no dejar un
# flag viejo si el servicio se reintenta a mano tras un fallo (systemctl restart).

set -uo pipefail

CFG=/root/scripts_campo_comun/cfg.py
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAG_OK=/run/rtc_ds3231_ok

rm -f "$FLAG_OK"

BUS=$(python3 "$CFG" rtc_ds3231.bus)
ADDR=$(python3 "$CFG" rtc_ds3231.direccion)

EPOCH=$(python3 "$DIR/leer_epoch.py" --bus "$BUS" --addr "$ADDR" 2>&1)
if [ $? -ne 0 ]; then
  echo "ADVERTENCIA: no se pudo leer el RTC DS3231, se mantiene la hora actual del sistema. $EPOCH" >&2
  exit 0
fi

date -u -s "@$EPOCH" >/dev/null
touch "$FLAG_OK"
echo "Hora del sistema restaurada desde el RTC DS3231: $(date -u -Iseconds)"
