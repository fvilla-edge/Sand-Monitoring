#!/bin/bash
# armar_paquete_actualizacion.sh — arma en la PC un paquete de actualizacion
# para una placa de campo a partir de un commit del repo (no del arbol de
# trabajo): archivos del proyecto, units de systemd, bitstream propio y el
# binario capturar_eventos ya compilado, con un MANIFIESTO de sha256.
# El paquete se manda con enviar_paquete.sh y se aplica en la placa con
# aplicar_actualizacion.sh (plan_campo/actualizar_placa_campo.md).
#
# El binario se compila en una placa que tenga toolchain y /root/rpsa_client
# (misma imagen que campo: la placa de pruebas), asi la placa de campo no
# necesita compilador. Se compila en /tmp de esa placa, sin tocar lo instalado.
#
# Uso:
#   bash scripts_campo/actualizacion/armar_paquete_actualizacion.sh \
#       --bitstream ~/RedPitaya-FPGA-Release_2025.2/prj/stream_app/out/red_pitaya.bin \
#       --compilar-en root@192.168.0.136 [--commit HEAD] [--salida DIR]
set -euo pipefail

REPO=$(git rev-parse --show-toplevel)
COMMIT=HEAD
SALIDA="$REPO/paquetes_actualizacion"
BITSTREAM=""
COMPILAR_EN=""
while [ $# -gt 0 ]; do
    case "$1" in
    --commit) COMMIT="$2"; shift 2 ;;
    --salida) SALIDA="$2"; shift 2 ;;
    --bitstream) BITSTREAM="$2"; shift 2 ;;
    --compilar-en) COMPILAR_EN="$2"; shift 2 ;;
    *) echo "argumento desconocido: $1" >&2; exit 1 ;;
    esac
done
[ -f "$BITSTREAM" ] || { echo "falta --bitstream <fpga.bin propio>" >&2; exit 1; }
[ -n "$COMPILAR_EN" ] || { echo "falta --compilar-en root@<placa con toolchain>" >&2; exit 1; }

CORTO=$(git -C "$REPO" rev-parse --short "$COMMIT")
ID="$(date -u +%Y%m%d_%H%M%S)_$CORTO"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
PKG="$TMP/$ID"
A="$PKG/archivos"
mkdir -p "$A/root" "$A/etc/systemd/system" "$A/opt/stream_app"

# Carpetas del proyecto que viven en /root de la placa. Se excluye lo que no
# se usa en la placa (docs, planes, firmware del ESP32).
DIRS="scripts_campo scripts_campo_comun starlink_remoto panel_solar_ble indicador_estado rtc_ds3231 starlink_api"
git -C "$REPO" archive "$COMMIT" $DIRS | tar -x -C "$TMP" --one-top-level=src
for d in $DIRS; do
    (cd "$TMP/src" && find "$d" -type f \
        -not -name '*.md' -not -path '*/plan_campo/*' -not -path '*/esp32_victron_scan/*' \
        -not -path '*/actualizacion/*' -print0) \
    | (cd "$TMP/src" && xargs -0 -r cp --parents -p -t "$A/root")
done
# nunca credenciales en el paquete: losant_config.py queda el de cada placa
find "$A/root" -name 'losant_config*.py' -delete
# En git casi todos los .sh estan en 644 (en campo se les dio +x a mano) y las
# units los ejecutan directo: sin esto systemd falla con 203/EXEC (ensayo 28/9)
find "$A/root" -name '*.sh' -exec chmod 0755 {} +

# Units: van a /etc/systemd/system (y quedan tambien como copia en /root)
find "$A/root" -path '*/systemd/*' \( -name '*.service' -o -name '*.timer' \) -exec cp -p {} "$A/etc/systemd/system/" \;
cp -p "$A/root/scripts_campo_comun/udev-automount/mnt-usb-automount@.service" "$A/etc/systemd/system/"

# Bitstream propio
install -m 0644 "$BITSTREAM" "$A/opt/stream_app/fpga.bin"

# Binario capturar_eventos compilado en la placa indicada (en /tmp, sin instalar)
REMOTO="/tmp/compilar_$ID"
echo "== compilando capturar_eventos en $COMPILAR_EN:$REMOTO"
ssh -o BatchMode=yes "$COMPILAR_EN" "mkdir -p $REMOTO"
scp -q "$A/root/scripts_campo/c/"{Makefile,capturar_eventos.cpp,generador_pulsos.h} "$COMPILAR_EN:$REMOTO/"
ssh -o BatchMode=yes "$COMPILAR_EN" "make -s -C $REMOTO capturar_eventos"
scp -q "$COMPILAR_EN:$REMOTO/capturar_eventos" "$A/root/scripts_campo/c/capturar_eventos"
ssh -o BatchMode=yes "$COMPILAR_EN" "rm -rf $REMOTO"
chmod 0755 "$A/root/scripts_campo/c/capturar_eventos"

# Scripts del lado de la placa
cp -p "$REPO/scripts_campo/actualizacion/"{aplicar_actualizacion.sh,revertir_actualizacion.sh,fusionar_config.py} "$PKG/"

# Que se habilita y que se reinicia al aplicar
printf '%s\n' modo-evento.service resumen-modo-evento.service > "$PKG/habilitar.txt"

# Manifiesto: rutas relativas a archivos/ (= rutas absolutas en la placa sin la / inicial)
(cd "$A" && find . -type f -printf '%P\0' | sort -z | xargs -0 sha256sum) > "$PKG/MANIFIESTO"
FPGA_REPO=$(dirname "$(dirname "$(dirname "$(dirname "$(readlink -f "$BITSTREAM")")")")")
{
    echo "id=$ID"
    echo "commit=$(git -C "$REPO" rev-parse "$COMMIT")"
    echo "commit_desc=$(git -C "$REPO" log -1 --format='%cs %s' "$COMMIT")"
    echo "armado_utc=$(date -u +%FT%TZ)"
    echo "bitstream_sha256=$(sha256sum < "$BITSTREAM" | cut -d' ' -f1)"
    echo "bitstream_origen=$(readlink -f "$BITSTREAM")"
    echo "bitstream_repo_commit=$(git -C "$FPGA_REPO" rev-parse --short HEAD 2>/dev/null || echo '?')"
    echo "binario_sha256=$(sha256sum < "$A/root/scripts_campo/c/capturar_eventos" | cut -d' ' -f1)"
    echo "binario_compilado_en=$COMPILAR_EN"
    echo "archivos=$(wc -l < "$PKG/MANIFIESTO")"
} > "$PKG/VERSION"

mkdir -p "$SALIDA"
tar -czf "$SALIDA/actualizacion_$ID.tgz" -C "$TMP" "$ID"
(cd "$SALIDA" && sha256sum "actualizacion_$ID.tgz" > "actualizacion_$ID.tgz.sha256")
cat "$PKG/VERSION"
echo "== paquete: $SALIDA/actualizacion_$ID.tgz"
