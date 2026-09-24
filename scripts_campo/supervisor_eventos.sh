#!/bin/bash
# supervisor_eventos.sh — pasos antes/despues de cada arranque de
# modo-evento.service (systemd hace el relanzamiento en si).
#   antes:   no deja arrancar si DESTINO esta en /mnt/usb y no hay USB montado;
#            poda core dumps viejos (mismo limite que relanzar_captura.sh)
#   despues: anota en modo_evento_reinicios.log como termino cada corrida
#            (systemd pasa SERVICE_RESULT/EXIT_CODE/EXIT_STATUS a ExecStopPost)
set -u
CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir)
MAX_CORE_DUMPS=$(python3 "$CFG" limpieza.max_core_dumps)
mkdir -p "$LOG_DIR"

case "${1:-}" in
antes)
    # destino en el storage externo: exigir que /mnt/usb sea un montaje real
    # (sin USB es una carpeta comun de la SD). Salir con error = systemd
    # reintenta en RestartSec, hasta que el USB aparezca.
    case "${DESTINO:-}" in
    /mnt/usb|/mnt/usb/*)
        if ! mountpoint -q /mnt/usb; then
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sin_usb: /mnt/usb no esta montado, no se arranca (destino $DESTINO)" \
                >> "$LOG_DIR/modo_evento_reinicios.log"
            echo "[supervisor] /mnt/usb no esta montado — no se arranca para no escribir en la SD" >&2
            exit 1
        fi
        ;;
    esac
    n=$(find "$LOG_DIR" -maxdepth 1 -name 'core*' -type f 2>/dev/null | wc -l)
    if [ "$n" -gt "$MAX_CORE_DUMPS" ]; then
        find "$LOG_DIR" -maxdepth 1 -name 'core*' -type f -printf '%T@ %p\n' \
            | sort -n | head -n "$((n - MAX_CORE_DUMPS))" | cut -d' ' -f2- | xargs -r rm -f
        echo "[supervisor] podados $((n - MAX_CORE_DUMPS)) core dump(s) viejos (limite: $MAX_CORE_DUMPS)"
    fi
    ;;
despues)
    # exited/0 = parada limpia (systemctl stop o --duracion-s); killed/SEGV, exited/1... = caida
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) resultado=${SERVICE_RESULT:-?} codigo=${EXIT_CODE:-?} estado=${EXIT_STATUS:-?}" \
        >> "$LOG_DIR/modo_evento_reinicios.log"
    ;;
*)
    echo "uso: $0 antes|despues" >&2
    exit 2
    ;;
esac
