#!/bin/bash
# supervisor_eventos.sh — pasos antes/despues de cada arranque de
# modo-evento.service (systemd hace el relanzamiento en si).
#   antes:   espera de uptime al boot; poda core dumps viejos (mismo limite
#            que relanzar_captura.sh)
#   arrancar: (ExecStart) elige el destino y hace exec de capturar_eventos.py.
#            CANALES=1|2 (mono/dual, default 1) y DEC=32|64 (default: 32 en
#            mono, 64 en dual, docs/plan_dos_canales.md) salen del
#            Environment= de la unit; lo que corre queda en /run/modo-evento/medicion.
#            Si DESTINO esta en /mnt/usb y no hay disco montado, mide igual:
#            solo el CSV de ventanas en la SD (rutas.eventos_sd), con la señal
#            cruda siempre pausada, y lo anota en /run/modo-evento/destino
#            para el anotador. automount_usb.sh relanza el servicio al volver
#            el disco.
#   despues: anota en modo_evento_reinicios.log como termino cada corrida
#            (systemd pasa SERVICE_RESULT/EXIT_CODE/EXIT_STATUS a ExecStopPost)
set -u
CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir)
MAX_CORE_DUMPS=$(python3 "$CFG" limpieza.max_core_dumps)
mkdir -p "$LOG_DIR"
# la crea control_starlink.sh justo antes de detener el servicio
MARCA_PARADA_RELE=/run/modo_evento_parada_rele
# destino real de la corrida en curso: "<carpeta>" o "<carpeta> sin_disco"
DESTINO_ACTUAL=/run/modo-evento/destino
# canales y decimacion de la corrida en curso: "canales=N dec=M" (lo lee el anotador)
MEDICION_ACTUAL=/run/modo-evento/medicion

# true si /mnt/usb es un disco de verdad (no la carpeta comun de la SD ni un tmpfs)
disco_montado() {
    mountpoint -q /mnt/usb && [ "$(findmnt -n -o FSTYPE /mnt/usb)" != tmpfs ]
}

case "${1:-}" in
antes)
    # Al boot, no arrancar antes de UPTIME_MIN_S de encendida. Si arranca
    # antes, startStreaming() del vendor falla por dentro y su camino de stop
    # crashea (SIGSEGV en requestStopStreamingCommon, libstreaming_api.so; 7/8
    # arranques en rp-f0fd8c 2026-09-25, el reintento a ~90s anduvo 6/6).
    # Causa de fondo sin identificar: no es el salto de reloj de NTP ni
    # startup.sh del vendor (probado). Con la placa ya andando (caida o
    # restart a mano) el uptime supera el minimo y no hay espera extra.
    # TimeoutStartSec del .service tiene que cubrir esta espera.
    UPTIME_MIN_S=90
    uptime_s=$(cut -d. -f1 /proc/uptime)
    if [ "$uptime_s" -lt "$UPTIME_MIN_S" ]; then
        echo "[supervisor] placa recien encendida (${uptime_s}s), espero hasta ${UPTIME_MIN_S}s de uptime"
        sleep $((UPTIME_MIN_S - uptime_s))
    fi
    n=$(find "$LOG_DIR" -maxdepth 1 -name 'core*' -type f 2>/dev/null | wc -l)
    if [ "$n" -gt "$MAX_CORE_DUMPS" ]; then
        find "$LOG_DIR" -maxdepth 1 -name 'core*' -type f -printf '%T@ %p\n' \
            | sort -n | head -n "$((n - MAX_CORE_DUMPS))" | cut -d' ' -f2- | xargs -r rm -f
        echo "[supervisor] podados $((n - MAX_CORE_DUMPS)) core dump(s) viejos (limite: $MAX_CORE_DUMPS)"
    fi
    ;;
arrancar)
    # Sin disco (se cayo el 30/9 y no volvio hasta cortar la energia) antes no
    # se arrancaba y la placa quedaba sin medir hasta que alguien entraba por
    # SSH. Ahora se mide igual, solo el CSV (~3 MB/h, la SD tiene ~19 GB):
    # --minimo-libre-mb enorme = la cruda queda pausada desde el arranque.
    destino="$DESTINO"
    extra=()
    marca=""
    case "${DESTINO:-}" in
    /mnt/usb|/mnt/usb/*)
        if ! disco_montado; then
            destino=$(python3 "$CFG" rutas.eventos_sd)
            extra=(--minimo-libre-mb 100000000)
            marca=" sin_disco"
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sin_disco: /mnt/usb sin disco, CSV a $destino sin cruda" \
                >> "$LOG_DIR/modo_evento_reinicios.log"
            echo "[supervisor] /mnt/usb sin disco — se mide igual, solo el CSV en $destino (cruda pausada)"
        fi
        ;;
    esac
    # dual a dec64: a dec32 el dual pierde ~250x mas muestras escribiendo
    # eventos (0.12% vs 0.00045%, pruebas W15/W15d64 del 2026-10-06)
    canales="${CANALES:-1}"
    dec="${DEC:-}"
    [ -n "$dec" ] || { [ "$canales" = 2 ] && dec=64 || dec=32; }
    mkdir -p "$(dirname "$DESTINO_ACTUAL")" "$destino"
    echo "$destino$marca" > "$DESTINO_ACTUAL"
    echo "canales=$canales dec=$dec" > "$MEDICION_ACTUAL"
    exec /usr/bin/python3 -u /root/scripts_campo/capturar_eventos.py \
        --umbral "$UMBRAL" --umbral2 "${UMBRAL2:-$UMBRAL}" --destino "$destino" --canales "$canales" --dec "$dec" \
        "${extra[@]}"
    ;;
despues)
    rm -f "$DESTINO_ACTUAL" "$MEDICION_ACTUAL"
    # control_starlink.sh detiene el servicio para leer el rele (a veces todavia
    # en la espera de uptime del boot, que termina en resultado=signal): no es
    # una caida, se anota sin "resultado=" para que no la cuente el anotador
    if [ -e "$MARCA_PARADA_RELE" ]; then
        rm -f "$MARCA_PARADA_RELE"
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) parada_por_verificacion_rele (${SERVICE_RESULT:-?})" \
            >> "$LOG_DIR/modo_evento_reinicios.log"
        exit 0
    fi
    # exited/0 = parada limpia (systemctl stop o --duracion-s); killed/SEGV, exited/1... = caida
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) resultado=${SERVICE_RESULT:-?} codigo=${EXIT_CODE:-?} estado=${EXIT_STATUS:-?}" \
        >> "$LOG_DIR/modo_evento_reinicios.log"
    ;;
*)
    echo "uso: $0 antes|arrancar|despues" >&2
    exit 2
    ;;
esac
