#!/bin/bash
# revertir_actualizacion.sh — deja la placa como estaba antes de una
# actualizacion, a partir del respaldo que armo aplicar_actualizacion.sh:
# restaura los archivos reemplazados, borra los que la actualizacion creo,
# y vuelve a dejar habilitadas/activas las mismas units que antes.
#
# Lo llama solo aplicar_actualizacion.sh si algo falla; tambien se puede
# correr a mano despues (conviene desacoplarlo de la sesion SSH):
#   systemd-run --unit=revertir --collect bash /root/respaldos_actualizacion/<id>/revertir_actualizacion.sh /root/respaldos_actualizacion/<id>
#   journalctl -u revertir -f
set -u
RESP="${1:?uso: $0 /root/respaldos_actualizacion/<id>}"
for f in respaldo.tgz existentes.txt creados.txt units_habilitadas.txt servicios_activos.txt; do
    [ -f "$RESP/$f" ] || { echo "ERROR: falta $RESP/$f" >&2; exit 1; }
done
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [revertir] $*"; }
error=0

log "detengo modo evento, anotador y cartero"
systemctl stop modo-evento resumen-modo-evento panel-solar-informe 2>/dev/null
pkill -x streaming-serve 2>/dev/null

# units que no existian antes: deshabilitarlas mientras su archivo existe
# (si no, queda el enlace colgando en *.wants)
while read -r u estado; do
    [ "$estado" = "not-found" ] && systemctl disable "$u" 2>/dev/null
done < "$RESP/units_habilitadas.txt"

log "restauro $(wc -l < "$RESP/existentes.txt") archivos"
tar -C / -xpzf "$RESP/respaldo.tgz" || { log "ERROR restaurando el respaldo"; error=1; }

log "borro $(wc -l < "$RESP/creados.txt") archivos nuevos"
while read -r rel; do
    [ -n "$rel" ] && rm -f "/$rel"
done < "$RESP/creados.txt"
rmdir /opt/stream_app 2>/dev/null   # solo si quedo vacia (la creo la actualizacion)

systemctl daemon-reload
while read -r u estado; do
    case "$estado" in
    enabled) systemctl enable "$u" 2>/dev/null || { log "ERROR habilitando $u"; error=1; } ;;
    disabled) systemctl disable "$u" 2>/dev/null ;;
    esac
    # not-found: la unit no existia antes, ya se borro con los archivos nuevos
done < "$RESP/units_habilitadas.txt"
systemctl daemon-reload

while read -r s estado; do
    case "$estado" in
    active|activating) systemctl start "$s" || { log "ERROR arrancando $s"; error=1; } ;;
    esac
done < "$RESP/servicios_activos.txt"

# sin modo evento la FPGA queda como la deja el arranque (v0.94, la que usa
# control_starlink para leer el rele)
if ! systemctl is-active --quiet modo-evento; then
    /opt/redpitaya/sbin/overlay.sh v0.94 >/dev/null 2>&1 || log "ADVERTENCIA: no se pudo cargar v0.94"
fi
log "listo (error=$error), bitstream: $(cat /tmp/loaded_fpga.inf 2>/dev/null)"
exit "$error"
