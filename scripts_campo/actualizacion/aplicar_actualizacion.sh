#!/bin/bash
# aplicar_actualizacion.sh — aplica en la placa un paquete ya desempacado por
# enviar_paquete.sh (corre desde /root/actualizacion/<id>/).
#
# Pasos: chequeos previos (sin cambiar nada) -> pausa del control de Starlink
# -> respaldo de todo lo que se va a pisar -> instalacion -> arranque en modo
# evento -> verificacion. Si algo falla despues de empezar a instalar, vuelve
# SOLO al respaldo (revertir_actualizacion.sh). El resultado queda en
# /root/actualizacion/RESULTADO_<id> (ok / abortada / revertida / FALLO...).
#
# Se desacopla solo en la unidad transitoria "actualizacion": un corte de SSH
# o de Starlink no la interrumpe, y no puede haber dos a la vez.
#
# Uso:   bash /root/actualizacion/<id>/aplicar_actualizacion.sh
# Ver:   journalctl -u actualizacion -f
# Ensayo de falla (solo pruebas): FALLA_EN=instalar|lectura_rele|verificar bash ... aplicar_actualizacion.sh
# Solo chequeos previos, sin cambiar nada (sirve con un paquete ya enviado,
# aunque su propio aplicar sea mas viejo):
#   SOLO_CHEQUEAR=1 bash aplicar_actualizacion.sh /root/actualizacion/<id>
set -u

PKG=$(readlink -f "${1:-$(dirname "$(readlink -f "$0")")}")
ID=$(basename "$PKG")

if [ -n "${SOLO_CHEQUEAR:-}" ]; then
    ok=1
    chk() { if eval "$2" >/dev/null 2>&1; then echo "OK    $1"; else echo "FALLA $1"; ok=0; fi; }
    echo "== chequeos previos de $ID (no se cambia nada)"
    chk "MANIFIESTO del paquete" "cd '$PKG/archivos' && sha256sum -c --quiet ../MANIFIESTO"
    chk "paquete no aplicado antes" "[ ! -e /root/respaldos_actualizacion/$ID ]"
    chk "SD con >300MB libres ($(df -m --output=avail / | tail -1 | tr -d ' ')MB)" "[ \$(df -m --output=avail / | tail -1) -gt 300 ]"
    chk "/mnt/usb montado" "mountpoint -q /mnt/usb"
    chk "sin capturar_stream.py corriendo" "! pgrep -f 'python3.*capturar_stream\\.py'"
    chk "sin otra actualizacion en curso" "! systemctl is-active --quiet actualizacion"
    [ "$ok" -eq 1 ] && echo "== todo OK para aplicar" || echo "== HAY CHEQUEOS QUE FALLAN: no aplicar asi"
    [ "$ok" -eq 1 ]; exit $?
fi

if [ -z "${ACTUALIZACION_DESACOPLADA:-}" ]; then
    if ! systemd-run --unit=actualizacion --collect --quiet \
            --setenv=ACTUALIZACION_DESACOPLADA=1 --setenv=FALLA_EN="${FALLA_EN:-}" \
            /bin/bash "$PKG/aplicar_actualizacion.sh" "$PKG"; then
        echo "no se pudo lanzar (¿ya hay una en curso? systemctl status actualizacion)" >&2
        exit 1
    fi
    echo "actualizacion $ID lanzada. Seguirla con: journalctl -u actualizacion -f"
    echo "Resultado final en: /root/actualizacion/RESULTADO_$ID"
    exit 0
fi

LOG_DIR=/root/logs_campo
LOG="$LOG_DIR/actualizacion_$ID.log"
RESP="/root/respaldos_actualizacion/$ID"
RESULTADO="/root/actualizacion/RESULTADO_$ID"
TIMERS_STARLINK="starlink-reconciliador.timer starlink-rele-on.timer starlink-rele-off.timer"
mkdir -p "$LOG_DIR"
INSTALANDO=0
TIMERS_PAUSADOS=""

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

reanudar_starlink() {
    exec 9>&- 2>/dev/null || true   # suelta el lock del rele si lo tenia
    for t in $TIMERS_PAUSADOS; do systemctl start "$t" || log "ADVERTENCIA: no arranco $t"; done
    TIMERS_PAUSADOS=""
}

terminar() {   # terminar <resultado> <mensaje>
    echo "$1 $(date -u +%FT%TZ) $2" > "$RESULTADO"
    sync
    log "RESULTADO: $1 — $2"
}

fallar() {
    log "ERROR: $*"
    if [ "$INSTALANDO" -eq 1 ]; then
        log "vuelvo al respaldo $RESP"
        if bash "$PKG/revertir_actualizacion.sh" "$RESP" >> "$LOG" 2>&1; then
            reanudar_starlink
            terminar revertida "$*"
        else
            reanudar_starlink
            terminar FALLO_Y_REVERSION_FALLIDA "$* (ver $LOG)"
        fi
    else
        reanudar_starlink
        terminar abortada "$*"
    fi
    exit 1
}

log "== actualizacion $ID"
sed 's/^/   /' "$PKG/VERSION" | tee -a "$LOG"

# ---- 1. chequeos previos: no cambian nada ----
(cd "$PKG/archivos" && sha256sum -c --quiet ../MANIFIESTO) >> "$LOG" 2>&1 \
    || fallar "el MANIFIESTO no coincide (paquete corrupto o incompleto)"
[ -e "$RESP" ] && fallar "ya existe $RESP (¿paquete ya aplicado? usar otro id)"
libre_mb=$(df -m --output=avail / | tail -1 | tr -d ' ')
[ "$libre_mb" -gt 300 ] || fallar "poco espacio en la SD (${libre_mb}MB)"
mountpoint -q /mnt/usb || fallar "/mnt/usb no esta montado (el modo evento lo necesita)"
pgrep -f 'python3.*capturar_stream\.py' >/dev/null && fallar "hay un capturar_stream.py corriendo; esperar a que termine"
log "chequeos previos OK (SD libre ${libre_mb}MB, USB montado, sin captura)"

# ---- 2. pausa del control de Starlink (que no conmute ni lea el rele en el medio) ----
for t in $TIMERS_STARLINK; do
    if systemctl is-active --quiet "$t"; then
        systemctl stop "$t" && TIMERS_PAUSADOS="$TIMERS_PAUSADOS $t"
    fi
done
exec 9>/run/lock/starlink_rele.lock
flock -w 200 9 || fallar "no se pudo tomar el lock del rele (¿control_starlink colgado?)"
log "control de Starlink en pausa (timers:${TIMERS_PAUSADOS:- ninguno})"

# ---- 3. respaldo de todo lo que se va a pisar ----
mkdir -p "$RESP"
: > "$RESP/existentes.txt"; : > "$RESP/creados.txt"
while read -r _ rel; do
    if [ -e "/$rel" ]; then echo "$rel" >> "$RESP/existentes.txt"; else echo "$rel" >> "$RESP/creados.txt"; fi
done < "$PKG/MANIFIESTO"
tar -C / -czf "$RESP/respaldo.tgz" -T "$RESP/existentes.txt" || fallar "no se pudo armar el respaldo"
for u in $(ls "$PKG/archivos/etc/systemd/system"); do
    echo "$u $(systemctl is-enabled "$u" 2>/dev/null || echo not-found)"
done > "$RESP/units_habilitadas.txt"
for s in modo-evento resumen-modo-evento panel-solar-informe; do
    echo "$s $(systemctl is-active "$s" 2>/dev/null)"
done > "$RESP/servicios_activos.txt"
cp -p "$PKG/revertir_actualizacion.sh" "$RESP/"
sync
log "respaldo en $RESP ($(wc -l < "$RESP/existentes.txt") reemplazados, $(wc -l < "$RESP/creados.txt") nuevos)"

# ---- 4. instalacion ----
INSTALANDO=1
systemctl stop modo-evento resumen-modo-evento panel-solar-informe 2>/dev/null || true
grep -v ' root/scripts_campo_comun/config_campo.json$' "$PKG/MANIFIESTO" | cut -d' ' -f3- > "$RESP/instalar.txt"
tar -C "$PKG/archivos" -cf - -T "$RESP/instalar.txt" | tar -C / -xpf - --no-same-owner \
    || fallar "fallo la copia de archivos"
python3 "$PKG/fusionar_config.py" /root/scripts_campo_comun/config_campo.json \
    "$PKG/archivos/root/scripts_campo_comun/config_campo.json" >> "$LOG" 2>&1 \
    || fallar "fallo la fusion de config_campo.json"
systemctl daemon-reload
for u in $(cat "$PKG/habilitar.txt"); do systemctl enable "$u" >> "$LOG" 2>&1 || fallar "no se pudo habilitar $u"; done
[ "${FALLA_EN:-}" = "instalar" ] && fallar "falla forzada (FALLA_EN=instalar, ensayo)"
sync
log "archivos instalados y units habilitadas"

# ---- 5. arranque ----
exec 9>&-   # soltar el lock: cambiar_modo/control_starlink lo necesitan
systemctl start panel-solar-informe resumen-modo-evento || fallar "no arrancaron cartero/anotador"
CAMBIAR_MODO_DESACOPLADO=1 bash /root/scripts_campo/cambiar_modo.sh evento >> "$LOG" 2>&1 \
    || fallar "cambiar_modo.sh evento fallo (ver $LOG)"

# ---- 5b. lectura directa del rele, ANTES de reanudar los timers ----
# Se actualiza por Starlink con el control en pausa: el rele esta en "on" si o
# si, y con el bitstream que trae la lectura directa esa lectura TIENE que dar
# "on". Si da "off" (al reves, mal cableada), el reconciliador apagaria Starlink
# de dia y el horario quedaria invertido: se vuelve al respaldo sin que corra
# ningun timer. Se espera a que el modo evento cargue el bitstream nuevo (el de
# antes tambien se llama stream_app_propio, pero no tiene el ID); si el
# paquete trae uno sin lectura directa, queda el camino de siempre (v0.94).
source /root/starlink_remoto/mux_ps10_common.sh   # MONITOR, DIO_REG, lectura_rele_directa, antena_responde
directa=0
for _ in $(seq 1 24); do lectura_rele_directa && { directa=1; break; }; sleep 5; done
if [ "$directa" -eq 1 ]; then
    dio=$("$MONITOR" "$DIO_REG")
    antena="no responde"; antena_responde && antena="responde"
    log "lectura directa del rele: $DIO_REG=$dio (bit2=0 es 'on'), antena $ANTENA_HOST: $antena"
    [ "${FALLA_EN:-}" = "lectura_rele" ] && dio=$(printf '0x%08x' $(( dio | 0x4 )))   # ensayo: simula la lectura al reves
    (( (dio & 0x4) == 0 )) \
        || fallar "la lectura directa del rele da 'off' con Starlink prendido ($DIO_REG=$dio): estaria al reves, no se reanuda el control"
else
    log "sin lectura directa del rele (el bitstream no trae el ID): control por el camino de siempre (v0.94)"
fi
reanudar_starlink
log "modo evento arrancado, control de Starlink reanudado"

# ---- 6. verificacion ----
for s in modo-evento resumen-modo-evento panel-solar-informe; do
    systemctl is-active --quiet "$s" || fallar "$s no quedo activo"
done
r0=$(systemctl show -p NRestarts --value panel-solar-informe)
sleep 30
r1=$(systemctl show -p NRestarts --value panel-solar-informe)
[ "$r1" = "$r0" ] || fallar "panel-solar-informe se reinicia solo ($r0 -> $r1)"
if systemctl cat starlink-reconciliador.service >/dev/null 2>&1; then
    systemctl start starlink-reconciliador.service || fallar "el reconciliador de Starlink fallo tras actualizar"
    journalctl -u starlink-reconciliador -n 3 -o cat --no-pager | sed 's/^/   /' | tee -a "$LOG"
    # la 1ra vez no hay ultima_verificacion_rele: el reconciliador lee el rele
    # de verdad, detiene el modo evento y lo reanuda (--no-block)
    for _ in $(seq 1 30); do systemctl is-active --quiet modo-evento && break; sleep 5; done
    systemctl is-active --quiet modo-evento || fallar "modo-evento no volvio despues del reconciliador"
fi
[ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = "stream_app_propio" ] \
    || fallar "bitstream cargado: '$(cat /tmp/loaded_fpga.inf 2>/dev/null)', esperaba stream_app_propio"
[ "${FALLA_EN:-}" = "verificar" ] && fallar "falla forzada (FALLA_EN=verificar, ensayo)"
estado=$(journalctl -u modo-evento -n 20 -o cat --no-pager | grep -o 'ESTADO muestras=[^ ]*' | tail -1)
terminar ok "modo evento midiendo ($estado), cartero y anotador activos, respaldo en $RESP"
exit 0
