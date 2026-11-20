#!/bin/bash
# lab_demo.sh — deja la placa de laboratorio lista para la demo con las apps
# web de Red Pitaya (Oscilloscope / DFT), o la devuelve a como estaba.
# Solo para la placa de laboratorio; no se usa en campo.
#
# Las apps web reprograman el FPGA (v0.94) cada vez que se abren, y al arrancar
# redpitaya_startup tambien lo carga y enseguida lee el FPGA (getsysinfo.sh,
# que genera /tmp/sysinfo.json para la pagina principal). Los servicios de
# Starlink leen el FPGA (feedback del rele) y, si no ven v0.94, lo recargan:
# en la demo no se usan, asi que se deshabilitan para que nadie lea ni recargue
# el FPGA en paralelo con la web.
#
# Uso:   bash lab_demo.sh aplicar|revertir|estado
set -u

DIR=/root/demo_presentacion
PREVIAS=$DIR/unidades_previas.txt
UNIDADES="starlink-mux-ps10.service starlink-reconciliador.timer starlink-ventana.timer starlink-rele-on.timer starlink-rele-off.timer"

estado() {
    echo "modo-evento: $(systemctl is-enabled modo-evento 2>/dev/null) / $(systemctl is-active modo-evento 2>/dev/null)"
    for u in $UNIDADES; do
        echo "$u: $(systemctl is-enabled "$u" 2>/dev/null) / $(systemctl is-active "$u" 2>/dev/null)"
    done
    echo "FPGA cargado: $(cat /tmp/loaded_fpga.inf 2>/dev/null || echo '-')"
    if [ -s /tmp/sysinfo.json ]; then echo "sysinfo.json: OK"; else echo "sysinfo.json: FALTA (pagina principal en negro)"; fi
    echo "cargas del FPGA en este arranque: $(journalctl -k -b --no-pager -o cat | grep -c 'writing fpga.bin')"
    [ -f "$PREVIAS" ] && echo "modo demo: APLICADO (previas en $PREVIAS)" || echo "modo demo: no aplicado"
}

case "${1:-}" in
aplicar)
    if systemctl is-enabled --quiet modo-evento; then
        echo "modo-evento esta habilitado: pasar antes a clasico (bash /root/scripts_campo/cambiar_modo.sh clasico)" >&2
        exit 1
    fi
    mkdir -p "$DIR"
    if [ ! -f "$PREVIAS" ]; then
        for u in $UNIDADES; do
            systemctl is-enabled --quiet "$u" 2>/dev/null && echo "$u"
        done > "$PREVIAS"
        sync
    fi
    for u in $UNIDADES; do
        systemctl disable --now "$u" >/dev/null 2>&1
    done
    estado
    ;;
revertir)
    if [ ! -f "$PREVIAS" ]; then
        echo "no hay $PREVIAS: el modo demo no estaba aplicado" >&2
        exit 1
    fi
    while read -r u; do
        [ -z "$u" ] && continue
        case "$u" in
            *.timer) systemctl enable --now "$u" ;;
            *) systemctl enable "$u" ;;   # el mux de PS10 corre en el proximo arranque
        esac
    done < "$PREVIAS"
    rm -f "$PREVIAS"; sync
    estado
    ;;
estado)
    estado
    ;;
*)
    echo "uso: $0 aplicar|revertir|estado" >&2
    exit 1
    ;;
esac
