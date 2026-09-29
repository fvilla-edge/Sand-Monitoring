#!/bin/bash
# estado_placa.sh — resumen de SOLO LECTURA de como esta andando una placa:
# modo, servicios, medicion, salud, Starlink/rele, cartero y actualizaciones.
# No escribe nada ni pulsa el rele (lee los archivos de estado, no el HW).
#
# Uso (desde la PC, no hace falta instalarlo en la placa):
#   ssh root@<IP> 'bash -s' < scripts_campo_comun/estado_placa.sh
set -u
export LC_ALL=C
CFG=/root/scripts_campo_comun/cfg.py
t() { printf '\n## %s\n' "$1"; }
act() { printf '%-26s %s' "$1" "$(systemctl is-active "$1" 2>/dev/null)"; \
        [ -e "/etc/systemd/system/$1" ] && printf ' (%s, NRestarts=%s)' \
        "$(systemctl is-enabled "$1" 2>/dev/null)" "$(systemctl show -p NRestarts --value "$1" 2>/dev/null)"; echo; }

t "placa"
echo "$(hostname)  $(date -u +%FT%TZ)  uptime $(awk '{printf "%.1fh", $1/3600}' /proc/uptime)"
echo "eth0: $(ip -4 -o addr show dev eth0 | awk '{print $4}' | paste -sd, -)"
echo "bitstream cargado: $(cat /tmp/loaded_fpga.inf 2>/dev/null)"

t "servicios"
for s in modo-evento.service resumen-modo-evento.service panel-solar-informe.service \
         pitaya-indicador-estado.service starlink-reconciliador.timer; do act "$s"; done

t "medicion (modo evento)"
if systemctl is-active --quiet modo-evento; then
    journalctl -u modo-evento -n 30 -o cat --no-pager | grep 'ESTADO' | tail -1 | sed 's/^ *//' | cut -c1-200
else
    echo "modo evento NO activo (modo clasico o detenido)"
fi
LOG_DIR=$(python3 "$CFG" rutas.log_dir 2>/dev/null || echo /root/logs_campo)
hoy=$(date -u +%Y-%m-%d)
if [ -f "$LOG_DIR/modo_evento_reinicios.log" ]; then
    echo "caidas hoy (UTC): $(grep "^$hoy" "$LOG_DIR/modo_evento_reinicios.log" | grep 'resultado=' | grep -vc 'resultado=success')"
fi
csv=$(ls -1 /mnt/usb/eventos/ventanas_"$(date -u +%Y%m%d_%H)".csv 2>/dev/null)
[ -n "$csv" ] && echo "CSV de esta hora: $(basename "$csv"), $(($(wc -l < "$csv") - 1)) ventanas"

t "salud"
awk '/MemAvailable/ {printf "RAM disponible: %d MB\n", $2/1024}' /proc/meminfo
x=/sys/bus/iio/devices/iio:device0
[ -r $x/in_temp0_raw ] && awk -v r="$(cat $x/in_temp0_raw)" -v o="$(cat $x/in_temp0_offset)" \
    -v s="$(cat $x/in_temp0_scale)" 'BEGIN {printf "temperatura chip: %.1f C\n", (r+o)*s/1000}'
echo "SD libre: $(df -m --output=avail / | tail -1 | tr -d ' ') MB"
if mountpoint -q /mnt/usb; then echo "USB libre: $(df -m --output=avail /mnt/usb | tail -1 | tr -d ' ') MB"; else echo "USB: NO MONTADO"; fi

t "Starlink / rele"
S=/root/starlink_remoto
echo "ultima lectura real del rele: $(cat $S/estado 2>/dev/null || echo '?')"
[ -f $S/ultima_verificacion_rele ] && echo "  hace $(( ($(date +%s) - $(cat $S/ultima_verificacion_rele)) / 60 )) min"
[ -f $S/modo_manual ] && echo "MODO MANUAL: $(head -1 $S/modo_manual)"
echo "objetivo ahora: $(bash $S/decidir_objetivo.sh 2>/dev/null || echo '?')"
echo "fallos consecutivos del rele: $(cat $S/fallos_consecutivos 2>/dev/null || echo 0)"
journalctl -u starlink-reconciliador -u starlink-aplicar-objetivo -n 40 -o short-iso --no-pager \
    | grep -E 'OK:|ADVERTENCIA|desacuerdo|no se verifica|verificacion periodica|ERROR' | tail -3 | cut -c1-180

t "cartero (Losant)"
journalctl -u panel-solar-informe -n 5 -o short-iso --no-pager | cut -c1-160
echo "resumenes pendientes en el USB: $(ls /mnt/usb/losant_pendientes 2>/dev/null | wc -l)"

t "actualizaciones"
ls -1t /root/actualizacion/RESULTADO_* 2>/dev/null | head -3 | while read -r f; do echo "$(basename "$f"): $(cat "$f")"; done
[ -n "$(ls /root/actualizacion/RESULTADO_* 2>/dev/null)" ] || echo "(ninguna aplicada)"
