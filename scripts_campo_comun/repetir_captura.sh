#!/bin/bash
# repetir_captura.sh — repite una captura corta N veces en vez de una sola
# sesion larga, para evitar carpetas pesadas dificiles de transmitir. Cada
# repeticion es una corrida independiente de capturar_stream.py, con su
# propia carpeta (nombrada con su propio timestamp, ver capturar_stream.py)
# y su propio aviso — no hace falta tocar nada de ese pipeline.
#
# Uso:
#   bash repetir_captura.sh <repeticiones> <duracion_min_por_repeticion> \
#     <script> [args...]
#
# <script> [args...] es el comando completo a repetir tal cual — normalmente
# relanzar_captura.sh envolviendo capturar_stream.py, para que un crash
# intermitente del streaming-server dentro de una repeticion se recupere
# solo en vez de perderse esa repeticion entera:
#
#   bash /root/scripts_campo_comun/repetir_captura.sh 5 2 \
#  /root/scripts_campo_comun/relanzar_captura.sh /root/scripts_campo/capturar_stream.py \
#  --condicion reposo --directorio /mnt/usb --duracion_chunk 0.5
#
# --duracion_total se agrega solo, al final de cada llamada (pisa cualquier
# --duracion_total puesto de mas en [args...], porque argparse se queda con
# la ultima ocurrencia de un flag repetido). Es a proposito un argumento
# obligatorio y separado de [args...], no queda a criterio del operador
# acordarse de ponerlo: sin el, el default de --duracion_total en
# capturar_stream.py es "sin limite" y la primera repeticion no terminaria
# nunca, rompiendo todo el sentido de repetir en silencio.
#
# Si una repeticion agota los reintentos del supervisor (falla dura, ej.
# USB desconectado), se aborta el lote entero en vez de seguir con las
# repeticiones restantes.

set -u

if [ $# -lt 3 ]; then
    echo "Uso: $0 <repeticiones> <duracion_min_por_repeticion> <script> [args...]" >&2
    exit 1
fi

REPETICIONES="$1"; shift
DURACION_MIN="$1"; shift

if ! [[ "$REPETICIONES" =~ ^[0-9]+$ ]] || [ "$REPETICIONES" -lt 1 ]; then
    echo "ERROR: <repeticiones> debe ser un entero >= 1 (recibido: '$REPETICIONES')" >&2
    exit 1
fi

if ! [[ "$DURACION_MIN" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: <duracion_min_por_repeticion> debe ser numerico (recibido: '$DURACION_MIN')" >&2
    exit 1
fi

for ((i = 1; i <= REPETICIONES; i++)); do
    echo "[repetidor] === Repeticion $i/$REPETICIONES (duracion_total=$DURACION_MIN min) ==="
    "$@" --duracion_total "$DURACION_MIN"
    codigo=$?
    if [ "$codigo" -ne 0 ]; then
        echo "[repetidor] Repeticion $i/$REPETICIONES termino con error (exit $codigo). Se aborta el lote." >&2
        exit "$codigo"
    fi
done

echo "[repetidor] Las $REPETICIONES repeticiones terminaron OK."
