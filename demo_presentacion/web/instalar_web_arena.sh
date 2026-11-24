#!/bin/bash
# instalar_web_arena.sh — app "Arena" en la web de la placa de LABORATORIO
# (solo demo, no campo): icono en la pantalla de inicio junto a Oscilloscope y
# DFT, pagina en http://<placa>/arena/.
#
# instalar:
#  - copia /root/demo_presentacion/web/arena (pagina, info/ con el icono y
#    nginx.conf) a /opt/redpitaya/www/apps/arena. /opt/redpitaya es FAT (no
#    admite symlinks): el JSON en vivo (/run/arena/ventanas.json) se sirve con un
#    alias en arena/nginx.conf, que tambien trae /arena_iniciar y /arena_estado.
#  - instala arena-demo.service (SIN habilitar: lo arranca la pagina).
#  - icono: la lista /bazaar?apps= solo trae carpetas con backend compilado
#    (controllerhf.so) y Arena no tiene; por eso va como entrada fija en
#    assets/desktop.js (default_applications, como "Remote control"), y se
#    agrega "arena" a la lista de apps visibles (assets/black_list_app.js).
#  - exclusion mutua: los fpga.sh de Oscilloscope, DFT y de la pantalla de
#    inicio (main_menu, que tambien carga v0.94) paran arena-demo y esperan a
#    que no quede streaming-server antes del overlay (leer el FPGA mientras se
#    recarga cuelga la placa). Si ya estaban parcheados, se re-parchean desde
#    la copia *.antes_arena.
#  - valida y recarga nginx.
# quitar: deja todo como antes (copias *.antes_arena) y para el servicio.
#
# Uso (en la placa):  bash instalar_web_arena.sh instalar|quitar
set -eu

ORIGEN=/root/demo_presentacion/web
APPS=/opt/redpitaya/www/apps
DESTINO=$APPS/arena
UNIDAD=/etc/systemd/system/arena-demo.service
LISTA=$APPS/assets/black_list_app.js
ESCRITORIO=$APPS/assets/desktop.js
# main_menu = la pantalla de inicio: tambien carga v0.94 al abrirse (24/11)
FPGA_SH="$APPS/scopegenpro/fpga.sh $APPS/spectrumpro/fpga.sh $APPS/main_menu/fpga.sh"
MARCA='# demo-arena'
MONTAJE=/opt/redpitaya
NGINX="/opt/redpitaya/sbin/nginx -p /opt/redpitaya/www"

estaba_ro=0
if findmnt -no OPTIONS "$MONTAJE" 2>/dev/null | grep -qw ro; then
    estaba_ro=1
    mount -o remount,rw "$MONTAJE"
fi
volver_ro() {
    sync
    [ "$estaba_ro" = 1 ] && mount -o remount,ro "$MONTAJE"
    return 0
}
trap volver_ro EXIT

respaldar() { [ -f "$1.antes_arena" ] || cp -p "$1" "$1.antes_arena"; }
restaurar() { if [ -f "$1.antes_arena" ]; then mv -f "$1.antes_arena" "$1"; fi; }

# (el aviso "could not open error log" de nginx -t es inofensivo: se filtra)
recargar_nginx() {
    if ! $NGINX -t >/dev/null 2>&1; then
        $NGINX -t 2>&1 | grep -v "could not open error log" >&2
        echo "configuracion de nginx invalida: se quita $DESTINO/nginx.conf y NO se recarga" >&2
        rm -f "$DESTINO/nginx.conf"
        exit 1
    fi
    $NGINX -s reload 2>&1 | grep -v "could not open error log\|signal process started" || true
    echo "nginx recargado"
}

case "${1:-}" in
instalar)
    [ -f "$ORIGEN/arena/index.html" ] || { echo "falta $ORIGEN/arena/index.html" >&2; exit 1; }
    grep -q '"spectrumpro"\]' "$LISTA" || grep -q '"arena"' "$LISTA" || {
        echo "$LISTA no tiene la lista allowed_root esperada (¿aplicar_mods.py?): no se toca nada" >&2; exit 1; }

    mkdir -p "$DESTINO"
    cp -r "$ORIGEN/arena/." "$DESTINO/"

    cp "$ORIGEN/arena-demo.service" "$UNIDAD"
    systemctl daemon-reload

    if ! grep -q "demo-arena" "$ESCRITORIO"; then
        grep -q '^    var default_applications = \[$' "$ESCRITORIO" || {
            echo "$ESCRITORIO no tiene default_applications donde se esperaba: no se agrega el icono" >&2; exit 1; }
        respaldar "$ESCRITORIO"
        sed -i '/^    var default_applications = \[$/a\
        { id: "arena", name: "Arena",  // demo-arena\
            description: "Kurtosis, area y acumulado en vivo (demo Edge)",\
            url: "/arena/",\
            image_path: "arena/info/icon",\
            image_sizes: "128;256;512",\
            check_online: false, licensable: false, callback: undefined, type: '"'run'"' },' "$ESCRITORIO"
    fi
    if ! grep -q '"arena"' "$LISTA"; then
        respaldar "$LISTA"
        sed -i 's/"spectrumpro"\]/"spectrumpro", "arena"]/' "$LISTA"
    fi
    for f in $FPGA_SH; do
        if grep -q "$MARCA" "$f"; then cp -p "$f.antes_arena" "$f"; else respaldar "$f"; fi
        sed -i "1a $MARCA: parar el panel Arena (y su streaming-server) antes de recargar el FPGA\\
systemctl stop arena-demo.service 2>/dev/null\\
pkill -x streaming-serve 2>/dev/null\\
for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -x streaming-serve >/dev/null || break; sleep 0.5; done" "$f"
    done

    recargar_nginx
    echo "--- instalado"
    grep -n "allowed_root =" "$LISTA"
    for f in $FPGA_SH; do echo "== $f"; cat "$f"; done
    ;;
quitar)
    systemctl stop arena-demo.service 2>/dev/null || true
    rm -f "$UNIDAD"
    systemctl daemon-reload
    restaurar "$LISTA"
    restaurar "$ESCRITORIO"
    for f in $FPGA_SH; do restaurar "$f"; done
    rm -rf "$DESTINO"
    recargar_nginx
    echo "quitada la app Arena (pagina, servicio, icono y cambios en fpga.sh)"
    ;;
*)
    echo "uso: $0 instalar|quitar" >&2
    exit 1
    ;;
esac
