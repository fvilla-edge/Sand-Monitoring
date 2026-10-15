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
# - Con 2, un segundo argumento opcional elige el modo del IN2
#   (modo_evento.in2_modo, docs/plan_in2_asociado.md): independiente o
#   asociado. Sin el, el modo del IN2 no se toca.
#
# Uso:   bash cambiar_canales.sh 1|2 [independiente|asociado]
# Ver:   journalctl -u cambiar-canales -f      (o el log en rutas.log_dir)
set -u

[ $# -le 2 ] || { echo "uso: $0 1|2 [independiente|asociado]" >&2; exit 1; }
N="${1:-}"
M="${2:-}"   # modo del IN2 pedido (vacio = no se toca)
case "$N" in
1|2) ;;
*) echo "uso: $0 1|2 [independiente|asociado]" >&2; exit 1 ;;
esac
case "$N:$M" in
1:|2:|2:independiente|2:asociado) ;;
*) echo "uso: $0 1|2 [independiente|asociado] (el modo del IN2 solo con 2)" >&2; exit 1 ;;
esac

CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir)
LOG="$LOG_DIR/cambiar_canales.log"
ESTADO="$LOG_DIR/cambio_canales_estado"
MEDICION=/run/modo-evento/medicion
mkdir -p "$LOG_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [canales=$N${M:+ in2=$M}] $*" | tee -a "$LOG"; }

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
            --setenv=CAMBIAR_CANALES_DESACOPLADO=1 /bin/bash "$(readlink -f "$0")" "$N" $M; then
        echo "no se pudo lanzar (¿ya hay un cambio en curso? systemctl status cambiar-canales)" >&2
        log "rechazado: ya hay un cambio en curso"
        exit 1
    fi
    echo "cambio a canales=$N${M:+ in2=$M} lanzado en segundo plano. Seguirlo con: journalctl -u cambiar-canales -f"
    exit 0
fi

canales_midiendo() { sed -n 's/.*canales=\([0-9]\).*/\1/p' "$MEDICION" 2>/dev/null; }
in2_midiendo() { sed -n 's/.*in2=\([a-z]*\).*/\1/p' "$MEDICION" 2>/dev/null; }
# lo que se esta midiendo coincide con canales=$1 (y, en dual, in2=$2)
midiendo_en() { [ "$(canales_midiendo)" = "$1" ] && { [ "$1" = 1 ] || [ "$(in2_midiendo)" = "$2" ]; }; }

# escribe las claves, reinicia y espera (tope 4 min) el primer ESTADO del
# arranque nuevo con /run/modo-evento/medicion en el modo pedido
aplicar() {
    local objetivo=$1 modo2=$2 desde
    python3 "$CFG" --poner modo_evento.canales "$objetivo" || { log "no se pudo escribir config_campo.json"; return 1; }
    # config viejo sin la clave: independiente es lo mismo que no tenerla
    if [ "$modo2" != independiente ] || python3 "$CFG" modo_evento.in2_modo >/dev/null 2>&1; then
        python3 "$CFG" --poner modo_evento.in2_modo "$modo2" || { log "no se pudo escribir in2_modo en config_campo.json"; return 1; }
    fi
    desde=$(date '+%Y-%m-%d %H:%M:%S')
    log "config en canales=$objetivo in2_modo=$modo2, reinicio modo-evento"
    systemctl restart modo-evento || { log "systemctl restart fallo"; return 1; }
    for _ in $(seq 1 48); do
        sleep 5
        if journalctl -u modo-evento --since "$desde" -o cat --no-pager | grep -q "ESTADO muestras=" \
                && midiendo_en "$objetivo" "$modo2"; then
            DESDE_OK="$desde"
            return 0
        fi
    done
    log "no midio en 4 min con canales=$objetivo in2_modo=$modo2"
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
anterior=$(python3 "$CFG" modo_evento.canales)
# modo del IN2 de antes; config viejo sin la clave = independiente
anterior2=$(python3 "$CFG" modo_evento.in2_modo 2>/dev/null)
case "$anterior2" in independiente|asociado) ;; *) anterior2=independiente ;; esac
M="${M:-$anterior2}"
texto() { [ "$1" = 2 ] && echo "2 $2" || echo "$1"; }   # "2 asociado" / "1"

if systemctl is-active --quiet modo-evento && midiendo_en "$N" "$M"; then
    resultado "ok $(texto "$N" "$M") (ya estaba)"
    exit 0
fi

DESDE_OK=""
if aplicar "$N" "$M"; then
    if [ "$N" = 2 ] && journalctl -u modo-evento --since "$DESDE_OK" -o cat --no-pager \
            | grep -q "bitstream sin calculo del IN2"; then
        if [ "$M" = asociado ]; then
            resultado "ok 2 asociado (bitstream sin IN2: cruda del IN2 sin area/kurtosis)"
        else
            resultado "ok 2 (bitstream sin IN2: mide solo IN1)"
        fi
    else
        resultado "ok $(texto "$N" "$M")"
    fi
    exit 0
fi

if { [ "$anterior" != "$N" ] || [ "$anterior2" != "$M" ]; } && aplicar "$anterior" "$anterior2"; then
    resultado "error: no midio con $(texto "$N" "$M") (volvio a $(texto "$anterior" "$anterior2"))"
else
    resultado "error: no midio con $(texto "$N" "$M") ni volviendo a $(texto "$anterior" "$anterior2")"
fi
exit 1
