#!/bin/bash
# relanzar_captura.sh — supervisor simple para capturar_stream.py
# (mono o dual, via --canales). Relanza el script si termina con error (crash),
# no si termina limpio (Ctrl+C, duracion_total alcanzado, o problema de USB
# detectado por verificar_usb() — los tres casos salen con exit code 0 a
# proposito, no hay que relanzar en esos casos).
#
# Uso:
#   bash relanzar_captura.sh /root/scripts_campo/capturar_stream.py \
#     --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
#
# Decision (2026-07-02): cada relanzamiento arranca una sesion nueva
# (session_ts y numeracion de chunk desde 0001), no continua la anterior.
# Mas simple — cero cambios en capturar_stream.py.
# revisar.py lee cada sesion por separado sin problema, solo hay que
# saber que son fragmentos de la misma noche si hubo reintentos.

set -u

# Habilita core dumps sin limite de tamano — se hereda por python3 mas abajo.
# Requiere ademas que /proc/sys/kernel/core_pattern apunte a una ruta persistente
# (ver scripts_campo/plan_campo/formato_y_funcionamiento.md, seccion "Core dumps"). Sin esto, un abort() de la libreria
# C++ (ej. std::bad_alloc no atrapado) no deja rastro analizable.
ulimit -c unlimited

if [ $# -lt 1 ]; then
    echo "Uso: $0 <script.py> [args...]" >&2
    exit 1
fi

CFG=/root/scripts_campo_comun/cfg.py
MAX_REINTENTOS=$(python3 "$CFG" reintentos.max)
ESPERA_ENTRE_REINTENTOS=$(python3 "$CFG" reintentos.espera_s)

# Extrae el valor de un flag de los args de capturar_stream.py (--directorio,
# --condicion) para poder ubicar despues la carpeta de una sesion que
# crasheo. No asume nada de capturar_stream.py salvo el nombre del flag.
extraer_arg() {
    local flag="$1"; shift
    local i
    for ((i = 1; i <= $#; i++)); do
        if [ "${!i}" = "$flag" ]; then
            local j=$((i + 1))
            echo "${!j}"
            return 0
        fi
    done
    return 1
}

DIRECTORIO=$(extraer_arg --directorio "$@")
CONDICION=$(extraer_arg --condicion "$@")

# Si un intento crashea a mitad de camino (exit != 0, incluye un abort/segfault
# de la libreria C++ que ni siquiera pasa por el finally de capturar_stream.py
# — ver nota de core dumps arriba), los chunks que ya se guardaron en USB
# antes del crash quedan sin el aviso que normalmente dispara la descarga
# (capturar_stream.py solo lo genera si la sesion termino sin excepcion). En
# campo esos minutos pueden ser irrepetibles (ej. con_arena), asi que se
# avisan igual si hay al menos un chunk completo — el backend descarga por
# nombre de carpeta y valida cada archivo por sha256, no le importa si la
# sesion está completa.
avisar_si_hay_datos_parciales() {
    local marca="$1"
    if [ -z "$DIRECTORIO" ] || [ -z "$CONDICION" ]; then
        return
    fi
    local carpeta
    carpeta=$(find "$DIRECTORIO" -maxdepth 1 -type d -name "*_${CONDICION}_*" -newer "$marca" 2>/dev/null | sort | tail -1)
    if [ -z "$carpeta" ]; then
        return
    fi
    local n_chunks
    n_chunks=$(find "$carpeta" -maxdepth 1 -name '*.bin' 2>/dev/null | wc -l)
    if [ "$n_chunks" -lt 1 ]; then
        echo "[supervisor] sesion parcial sin chunks completos ($carpeta) — no se avisa, se borra."
        rm -rf "$carpeta"
        return
    fi
    local json_path json_name subdir_nombre
    json_path=$(find "$carpeta" -maxdepth 1 -name 'session_*_info.json' 2>/dev/null | head -1)
    if [ -z "$json_path" ]; then
        echo "[supervisor] sesion parcial sin metadata json ($carpeta) — no se puede avisar." >&2
        return
    fi
    json_name=$(basename "$json_path")
    subdir_nombre=$(basename "$carpeta")
    echo "[supervisor] sesion parcial detectada: $subdir_nombre ($n_chunks chunks) — generando aviso."
    python3 -c "
import sys
sys.path.insert(0, '/root/scripts_campo_comun')
import campo_common as cc
cc.crear_aviso_pendiente('$json_name', '$subdir_nombre', lambda m, nivel='OK': print(f'[supervisor] {m}'))
" || echo "[supervisor] ADVERTENCIA: no se pudo generar el aviso de sesion parcial." >&2
}

intento=0
while [ "$intento" -lt "$MAX_REINTENTOS" ]; do
    if [ "$intento" -gt 0 ]; then
        echo "[supervisor] matando streaming-server residual antes de reintentar..."
        pkill -9 -f streaming-server 2>/dev/null
        sleep "$ESPERA_ENTRE_REINTENTOS"
    fi

    marca_tmp=$(mktemp)
    echo "[supervisor] lanzando: python3 $*"
    python3 "$@"
    codigo=$?

    if [ "$codigo" -eq 0 ]; then
        rm -f "$marca_tmp"
        echo "[supervisor] sesion termino limpio (exit 0). No se relanza."
        exit 0
    fi

    avisar_si_hay_datos_parciales "$marca_tmp"
    rm -f "$marca_tmp"

    intento=$((intento + 1))
    echo "[supervisor] script termino con error (exit $codigo). Reintento $intento/$MAX_REINTENTOS."
done

echo "[supervisor] se alcanzo el maximo de $MAX_REINTENTOS reintentos. Abandonando." >&2
exit 1
