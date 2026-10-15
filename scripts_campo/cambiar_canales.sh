#!/bin/bash
# cambiar_canales.sh — pasa modo-evento entre mono (1 = solo IN1) y dual
# (2 = IN1 + IN2 como sensor independiente, docs/plan_in2_independiente.md).
# Lo dispara el comando "canales" de Losant (panel_solar_ble/publicar_losant.py)
# o se corre a mano. Diseño: docs/plan_cambio_canales_remoto.md.
#
# - El modo vive en config_campo.json (modo_evento.canales), que lee
#   supervisor_eventos.sh al arrancar: cambiar = escribir la clave (atomico,
#   cfg.py --poner) + systemctl restart. Sin daemon-reload.
# - Toma el lock del rele (el mismo de control_starlink.sh y
#   aplicar_actualizacion.sh): no se cruza con hora_on/hora_off.
# - Espera a que el arranque nuevo mida (primer ESTADO) en el modo pedido; si
#   no llega en 4 min vuelve solo al modo anterior.
# - No lee registros de la FPGA: durante el arranque se recarga el bitstream
#   y una lectura en ese momento cuelga la placa.
# - Se desacopla en una unidad transitoria (cambiar-canales): un corte de
#   Starlink o del cartero no lo deja por la mitad, y un segundo cambio
#   mientras hay uno en curso se rechaza.
# - Resultado en rutas.log_dir/cambio_canales_estado (una linea), que el
#   anotador manda a Losant como me_cambio; detalle en cambiar_canales.log.
#
# Uso:   bash cambiar_canales.sh 1|2
# Ver:   journalctl -u cambiar-canales -f      (o el log en rutas.log_dir)
set -u

N="${1:-}"
case "$N" in
1|2) ;;
*) echo "uso: $0 1|2" >&2; exit 1 ;;
esac

CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir)
LOG="$LOG_DIR/cambiar_canales.log"
ESTADO="$LOG_DIR/cambio_canales_estado"
MEDICION=/run/modo-evento/medicion
mkdir -p "$LOG_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [canales=$N] $*" | tee -a "$LOG"; }

# una linea, escrita de forma atomica (temporal + sync + rename): la lee el anotador
resultado() {
    echo "$1 $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ESTADO.tmp"
    sync "$ESTADO.tmp"
    mv "$ESTADO.tmp" "$ESTADO"
    sync "$LOG_DIR"
    log "RESULTADO: $1"
}

if [ -z "${CAMBIAR_CANALES_DESACOPLADO:-}" ]; then
    if ! systemd-run --unit=cambiar-canales --collect --quiet \
            --setenv=CAMBIAR_CANALES_DESACOPLADO=1 /bin/bash "$(readlink -f "$0")" "$N"; then
        echo "no se pudo lanzar (¿ya hay un cambio en curso? systemctl status cambiar-canales)" >&2
        log "rechazado: ya hay un cambio en curso"
        exit 1
    fi
    echo "cambio a canales=$N lanzado en segundo plano. Seguirlo con: journalctl -u cambiar-canales -f"
    exit 0
fi

canales_midiendo() { sed -n 's/.*canales=\([0-9]\).*/\1/p' "$MEDICION" 2>/dev/null; }

# escribe la clave, reinicia y espera (tope 4 min) el primer ESTADO del
# arranque nuevo con /run/modo-evento/medicion en el modo pedido
aplicar() {
    local objetivo=$1 desde
    python3 "$CFG" --poner modo_evento.canales "$objetivo" || { log "no se pudo escribir config_campo.json"; return 1; }
    desde=$(date '+%Y-%m-%d %H:%M:%S')
    log "config en canales=$objetivo, reinicio modo-evento"
    systemctl restart modo-evento || { log "systemctl restart fallo"; return 1; }
    for _ in $(seq 1 48); do
        sleep 5
        if journalctl -u modo-evento --since "$desde" -o cat --no-pager | grep -q "ESTADO muestras=" \
                && [ "$(canales_midiendo)" = "$objetivo" ]; then
            DESDE_OK="$desde"
            return 0
        fi
    done
    log "no midio en 4 min con canales=$objetivo"
    return 1
}

log "inicio del cambio"
exec 9>/run/lock/starlink_rele.lock
if ! flock -w 200 9; then
    resultado "error: lock del rele ocupado (control_starlink?), sin cambio"
    exit 1
fi

if [ "$(systemctl is-enabled modo-evento 2>/dev/null)" != "enabled" ]; then
    resultado "error: modo clasico (modo-evento deshabilitado), sin cambio"
    exit 1
fi
# un drop-in con CANALES le gana al config: el cambio no tendria efecto
if systemctl show -p Environment modo-evento | grep -q "CANALES="; then
    resultado "error: hay un drop-in con CANALES en modo-evento, sin cambio"
    exit 1
fi
if systemctl is-active --quiet modo-evento && [ "$(canales_midiendo)" = "$N" ]; then
    resultado "ok $N (ya estaba)"
    exit 0
fi

anterior=$(python3 "$CFG" modo_evento.canales)
DESDE_OK=""
if aplicar "$N"; then
    if [ "$N" = 2 ] && journalctl -u modo-evento --since "$DESDE_OK" -o cat --no-pager \
            | grep -q "bitstream sin calculo del IN2"; then
        resultado "ok 2 (bitstream sin IN2: mide solo IN1)"
    else
        resultado "ok $N"
    fi
    exit 0
fi

if [ "$anterior" != "$N" ] && aplicar "$anterior"; then
    resultado "error: no midio con canales=$N (volvio a $anterior)"
else
    resultado "error: no midio con canales=$N ni volviendo a $anterior"
fi
exit 1
