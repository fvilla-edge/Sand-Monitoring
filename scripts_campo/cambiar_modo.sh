#!/bin/bash
# cambiar_modo.sh — pasa la placa entre el modo evento y el modo clasico
# (vuelta atras, docs/modo_evento.md).
#   evento:  modo-evento.service habilitado y corriendo (bitstream propio,
#            area/kurtosis 24h, cruda solo si kurtosis>=umbral).
#   clasico: modo-evento deshabilitado (no vuelve al reiniciar), FPGA con el
#            stream_app del vendor; se captura como antes, a pedido
#            (comando "capturar" de Losant o capturar_stream.py/repetir_captura.sh).
# resumen-modo-evento sigue en los dos modos: en clasico manda me_activo=false
# y la salud de la placa (RAM, temperatura, discos) igual.
#
# Se desacopla solo en una unidad transitoria de systemd (cambiar-modo): un
# corte de SSH/Starlink a mitad de camino no lo deja por la mitad. Si ya hay
# un cambio en curso, systemd-run rechaza el segundo. Correrlo dos veces con
# el mismo modo no rompe nada.
#
# Uso:   bash cambiar_modo.sh evento|clasico
# Ver:   journalctl -u cambiar-modo -f      (o el log en rutas.log_dir)
set -u

MODO="${1:-}"
case "$MODO" in
evento|clasico) ;;
*) echo "uso: $0 evento|clasico" >&2; exit 1 ;;
esac

if [ -z "${CAMBIAR_MODO_DESACOPLADO:-}" ]; then
    if ! systemd-run --unit=cambiar-modo --collect --quiet \
            --setenv=CAMBIAR_MODO_DESACOPLADO=1 /bin/bash "$(readlink -f "$0")" "$MODO"; then
        echo "no se pudo lanzar (¿ya hay un cambio en curso? systemctl status cambiar-modo)" >&2
        exit 1
    fi
    echo "cambio a '$MODO' lanzado en segundo plano. Seguirlo con: journalctl -u cambiar-modo -f"
    exit 0
fi

CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir)
LOG="$LOG_DIR/cambiar_modo.log"
MONITOR=/opt/redpitaya/bin/monitor
# Registro de muestras por ventana del acumulador propio (port 2026.1): lee
# 195312 con el bitstream propio y 0 con el del vendor (lo no mapeado lee 0)
REG_VENTANA=0x40000328
mkdir -p "$LOG_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [$MODO] $*" | tee -a "$LOG"; }
fallar() { log "ERROR: $*"; exit 1; }

registro_ventana() {
    local h
    h=$($MONITOR $REG_VENTANA 2>/dev/null) || { echo -1; return; }
    printf '%d' "$h" 2>/dev/null || echo -1
}

log "inicio del cambio"

if [ "$MODO" = "clasico" ]; then
    systemctl disable --now modo-evento || fallar "no se pudo detener modo-evento"
    # streaming-server vive en el cgroup de modo-evento (KillMode=mixed lo
    # mata al parar); por las dudas no dejar uno huerfano con el bitstream propio
    if pgrep -x streaming-serve >/dev/null; then
        log "streaming-server residual, lo detengo"
        pkill -x streaming-serve; sleep 2
    fi
    /opt/redpitaya/sbin/overlay.sh stream_app >/dev/null 2>&1 \
        || fallar "overlay.sh stream_app (vendor) fallo"
    sleep 1
    # verificacion
    [ "$(systemctl is-enabled modo-evento)" = "disabled" ] || fallar "modo-evento sigue habilitado"
    systemctl is-active --quiet modo-evento && fallar "modo-evento sigue activo"
    [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = "stream_app" ] \
        || fallar "loaded_fpga.inf dice '$(cat /tmp/loaded_fpga.inf 2>/dev/null)', esperaba stream_app"
    v=$(registro_ventana)
    [ "$v" = "0" ] || fallar "el registro del acumulador lee $v: no parece el bitstream del vendor"
    log "OK: modo clasico (modo-evento deshabilitado, bitstream del vendor, acumulador ausente)"
else
    # el streaming-server acepta un solo cliente: no pisar una captura en curso
    if pgrep -f capturar_stream.py >/dev/null; then
        fallar "hay un capturar_stream.py corriendo; esperar a que termine (o pararlo) y reintentar"
    fi
    systemctl enable --now modo-evento || fallar "no se pudo arrancar modo-evento"
    # supervisor_eventos.sh puede esperar hasta 90s de uptime y el arranque
    # tarda ~15s: se espera el primer ESTADO del servicio (tope 4 min)
    desde=$(date -u '+%Y-%m-%d %H:%M:%S')
    for _ in $(seq 1 48); do
        if journalctl -u modo-evento --since "$desde" -o cat --no-pager | grep -q "ESTADO muestras="; then
            break
        fi
        sleep 5
    done
    journalctl -u modo-evento --since "$desde" -o cat --no-pager | grep -q "ESTADO muestras=" \
        || fallar "modo-evento no llego a medir en 4 min (journalctl -u modo-evento)"
    [ "$(systemctl is-enabled modo-evento)" = "enabled" ] || fallar "modo-evento no quedo habilitado"
    [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = "stream_app_propio" ] \
        || fallar "loaded_fpga.inf dice '$(cat /tmp/loaded_fpga.inf 2>/dev/null)', esperaba stream_app_propio"
    v=$(registro_ventana)
    [ "$v" -gt 0 ] 2>/dev/null || fallar "el registro del acumulador lee $v: falta el bitstream propio"
    log "OK: modo evento midiendo ($(journalctl -u modo-evento -n 1 -o cat --no-pager | grep -o 'ESTADO.*' | cut -c1-80))"
fi
