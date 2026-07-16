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

intento=0
while [ "$intento" -lt "$MAX_REINTENTOS" ]; do
    if [ "$intento" -gt 0 ]; then
        echo "[supervisor] matando streaming-server residual antes de reintentar..."
        pkill -9 -f streaming-server 2>/dev/null
        sleep "$ESPERA_ENTRE_REINTENTOS"
    fi

    echo "[supervisor] lanzando: python3 $*"
    python3 "$@"
    codigo=$?

    if [ "$codigo" -eq 0 ]; then
        echo "[supervisor] sesion termino limpio (exit 0). No se relanza."
        exit 0
    fi

    intento=$((intento + 1))
    echo "[supervisor] script termino con error (exit $codigo). Reintento $intento/$MAX_REINTENTOS."
done

echo "[supervisor] se alcanzo el maximo de $MAX_REINTENTOS reintentos. Abandonando." >&2
exit 1
