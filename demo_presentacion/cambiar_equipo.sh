#!/bin/bash
# cambiar_equipo.sh — pasa el equipo entre DEMO (web: Oscilloscope/DFT/Arena,
# modo clasico, Starlink deshabilitado) y CAMPO (modo evento + Starlink).
# Plan: docs/plan_demo_a_campo.md. demo->campo lo dispara el comando "equipo" de
# Losant (panel_solar_ble/publicar_losant.py), que solo acepta {"modo":"campo"}
# (decision 24/11: solo ida; un equipo instalado no vuelve a demo).
# campo->demo solo por SSH en el lab (y la vuelta automatica si campo falla).
#
# Metodo (decidido 24/11): dejar la config y REINICIAR. No se para ni arranca
# nada en vivo (Starlink y el mux cargan/leen el FPGA y competian con la web).
#   1. pedido en $PEDIDO (objetivo, anterior, intento);
#   2. solo systemctl enable/disable (modo-evento y Starlink);
#   3. sync + reboot.
# Al arrancar, verificar-equipo.service corre "cambiar_equipo.sh verificar":
# espera el estado esperado (tope 5 min) SIN leer el FPGA. Si falla en el 1er
# intento vuelve a la config anterior y reinicia una vez mas; en el 2do deja
# el error y no reintenta.
# Corte de luz a mitad del cambio (prueba 24/11): el pedido sobrevive pero
# los enable/disable pueden no haber llegado al disco. Si al arrancar la
# config del objetivo no esta, se reaplica y se reinicia UNA vez (marca
# reaplicado=1 en el pedido, sin bucles). La lista de Starlink ($PREVIAS)
# se borra recien con campo verificado, para que ningun corte la pierda.
# Resultado en rutas.log_dir/cambio_equipo_estado (una linea) -> me_equipo.
#
# Uso:  bash cambiar_equipo.sh demo|campo     (se desacopla solo)
#       bash cambiar_equipo.sh estado
#       bash cambiar_equipo.sh instalar       (una vez: unidad de verificacion
#                                              + modo actual en $MODO_FILE)
#       bash cambiar_equipo.sh verificar      (lo corre la unidad al arrancar)
# Ver:  journalctl -u cambiar-equipo -u verificar-equipo
set -u

DIR=/root/demo_presentacion
SCRIPT="$DIR/cambiar_equipo.sh"
MODO_FILE="$DIR/equipo_modo"          # demo | campo (lo que se pidio y se verifico)
PEDIDO="$DIR/equipo_pedido"           # existe solo durante un cambio
PREVIAS="$DIR/unidades_previas.txt"   # el mismo archivo de lab_demo.sh
UNIDAD_VERIF=/etc/systemd/system/verificar-equipo.service
# Igual que lab_demo.sh: lo que lee/recarga el FPGA por Starlink
UNIDADES="starlink-mux-ps10.service starlink-reconciliador.timer starlink-ventana.timer starlink-rele-on.timer starlink-rele-off.timer"
CFG=/root/scripts_campo_comun/cfg.py
LOG_DIR=$(python3 "$CFG" rutas.log_dir 2>/dev/null || echo /root/logs_campo)
LOG="$LOG_DIR/cambiar_equipo.log"
ESTADO="$LOG_DIR/cambio_equipo_estado"
mkdir -p "$LOG_DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [equipo] $*" | tee -a "$LOG"; }
escribir() {  # archivo contenido — atomico
    printf '%s\n' "$2" > "$1.tmp" && sync "$1.tmp" && mv "$1.tmp" "$1" && sync "$(dirname "$1")"
}
resultado() { escribir "$ESTADO" "$1 $(date -u +%Y-%m-%dT%H:%M:%SZ)"; log "RESULTADO: $1"; }
modo_actual() { cat "$MODO_FILE" 2>/dev/null || echo desconocido; }

# ---- config persistente de cada modo (solo enable/disable) ----
config_demo() {
    systemctl disable modo-evento >/dev/null 2>&1
    if [ ! -f "$PREVIAS" ]; then
        for u in $UNIDADES; do systemctl is-enabled --quiet "$u" 2>/dev/null && echo "$u"; done > "$PREVIAS.tmp"
        sync "$PREVIAS.tmp"; mv "$PREVIAS.tmp" "$PREVIAS"; sync "$DIR"
    fi
    for u in $UNIDADES; do systemctl disable "$u" >/dev/null 2>&1; done
    sync   # los symlinks de /etc al disco antes de seguir (corte de luz)
    config_esta_demo
}
config_campo() {
    # $PREVIAS NO se borra aca: recien con campo verificado (verificar)
    if [ -f "$PREVIAS" ]; then
        while read -r u; do [ -n "$u" ] && systemctl enable "$u" >/dev/null 2>&1; done < "$PREVIAS"
    fi
    systemctl enable modo-evento >/dev/null 2>&1
    sync
    config_esta_campo
}
# ¿la config persistente del modo esta en disco? (no mira si anda)
starlink_falta() {  # unidades de $PREVIAS que no estan habilitadas
    [ -f "$PREVIAS" ] || return 0
    while read -r u; do
        [ -n "$u" ] && ! systemctl is-enabled --quiet "$u" 2>/dev/null && echo "$u"
    done < "$PREVIAS"
}
config_esta_demo() {
    [ "$(systemctl is-enabled modo-evento 2>/dev/null)" = disabled ] || return 1
    for u in $UNIDADES; do systemctl is-enabled --quiet "$u" 2>/dev/null && return 1; done
    return 0
}
config_esta_campo() {
    [ "$(systemctl is-enabled modo-evento 2>/dev/null)" = enabled ] && [ -z "$(starlink_falta)" ]
}

# ---- verificacion al arrancar (sin leer el FPGA) ----
ok_demo() {
    ! systemctl is-active --quiet modo-evento \
        && [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = v0.94 ] \
        && [ -s /tmp/sysinfo.json ] \
        && systemctl is-active --quiet redpitaya_nginx
}
ok_campo() {
    systemctl is-active --quiet modo-evento \
        && journalctl -u modo-evento -b -o cat --no-pager | grep -q "ESTADO muestras=" \
        && [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = stream_app_propio ] \
        && ! systemctl is-active --quiet arena-demo \
        && [ -z "$(starlink_falta)" ]
}
falta_demo() {
    systemctl is-active --quiet modo-evento && echo "modo-evento activo"
    [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = v0.94 ] || echo "FPGA=$(cat /tmp/loaded_fpga.inf 2>/dev/null)"
    [ -s /tmp/sysinfo.json ] || echo "sin sysinfo.json"
    systemctl is-active --quiet redpitaya_nginx || echo "nginx inactivo"
}
falta_campo() {
    systemctl is-active --quiet modo-evento || echo "modo-evento inactivo"
    journalctl -u modo-evento -b -o cat --no-pager | grep -q "ESTADO muestras=" || echo "sin ESTADO de modo-evento"
    [ "$(cat /tmp/loaded_fpga.inf 2>/dev/null)" = stream_app_propio ] || echo "FPGA=$(cat /tmp/loaded_fpga.inf 2>/dev/null)"
    systemctl is-active --quiet arena-demo && echo "arena-demo activo"
    for u in $(starlink_falta); do echo "$u deshabilitado"; done
}

reiniciar() { log "reinicio ($1)"; sync; sleep 2; systemctl reboot; }

case "${1:-}" in
demo|campo)
    OBJ=$1
    if [ -z "${CAMBIAR_EQUIPO_DESACOPLADO:-}" ]; then
        if ! systemd-run --unit=cambiar-equipo --collect --quiet \
                --setenv=CAMBIAR_EQUIPO_DESACOPLADO=1 /bin/bash "$SCRIPT" "$OBJ"; then
            echo "no se pudo lanzar (¿ya hay un cambio en curso? systemctl status cambiar-equipo)" >&2
            exit 1
        fi
        echo "cambio de equipo a '$OBJ' lanzado (la placa va a reiniciar). Ver: journalctl -u cambiar-equipo -u verificar-equipo"
        exit 0
    fi
    log "pedido: $OBJ (actual: $(modo_actual))"
    [ -f "$UNIDAD_VERIF" ] || { resultado "error: falta verificar-equipo.service (cambiar_equipo.sh instalar), sin cambio"; exit 1; }
    [ -f "$PEDIDO" ] && { resultado "error: ya hay un cambio pendiente de verificar ($(tr '\n' ' ' < "$PEDIDO")), sin cambio"; exit 1; }
    for u in cambiar-canales cambiar-modo; do
        systemctl is-active --quiet "$u" && { resultado "error: hay un $u en curso, sin cambio"; exit 1; }
    done
    exec 9>/run/lock/starlink_rele.lock
    flock -w 200 9 || { resultado "error: lock del rele ocupado, sin cambio"; exit 1; }
    ANT=$(modo_actual)
    if [ "$ANT" = "$OBJ" ] && { [ "$OBJ" = demo ] && ok_demo || { [ "$OBJ" = campo ] && ok_campo; }; }; then
        resultado "ok $OBJ (ya estaba)"
        exit 0
    fi
    case "$ANT" in demo|campo) ;; *) ANT=$([ "$OBJ" = demo ] && echo campo || echo demo) ;; esac
    escribir "$PEDIDO" "objetivo=$OBJ anterior=$ANT intento=1"
    if ! "config_$OBJ"; then
        "config_$ANT"; rm -f "$PEDIDO"; sync "$DIR"
        resultado "error: no se pudo dejar la config de $OBJ (vuelta a $ANT, sin reiniciar)"
        exit 1
    fi
    resultado "reiniciando hacia $OBJ"
    reiniciar "$OBJ"
    ;;
verificar)
    [ -f "$PEDIDO" ] || exit 0
    # shellcheck disable=SC1090
    eval "$(tr ' ' '\n' < "$PEDIDO" | grep -E '^(objetivo|anterior|intento|reaplicado)=(demo|campo|[12])$')"
    OBJ=${objetivo:-}; ANT=${anterior:-}; INT=${intento:-1}; REAP=${reaplicado:-0}
    case "$OBJ:$ANT" in demo:campo|campo:demo) ;; *) log "pedido ilegible: $(cat "$PEDIDO")"; rm -f "$PEDIDO"; resultado "error: pedido ilegible"; exit 1 ;; esac
    log "verificando $OBJ (intento $INT, reaplicado $REAP)"
    # config del objetivo perdida (corte de luz antes de que llegara al disco):
    # se reaplica y se reinicia una sola vez por intento
    if ! "config_esta_$OBJ"; then
        if [ "$REAP" = 0 ]; then
            log "la config de $OBJ no esta en disco (¿corte durante el cambio?): la reaplico"
            escribir "$PEDIDO" "objetivo=$OBJ anterior=$ANT intento=$INT reaplicado=1"
            "config_$OBJ"
            resultado "reaplicando config de $OBJ (se perdio, ¿corte durante el cambio?)"
            reiniciar "$OBJ (reaplicado)"
            exit 0
        fi
        log "la config de $OBJ sigue sin estar en disco despues de reaplicarla"
    fi
    for _ in $(seq 1 60); do
        if "ok_$OBJ"; then
            escribir "$MODO_FILE" "$OBJ"; rm -f "$PEDIDO"; sync "$DIR"
            # campo verificado con Starlink habilitado: la lista ya no hace falta
            [ "$OBJ" = campo ] && { rm -f "$PREVIAS"; sync "$DIR"; }
            if [ "$INT" = 1 ]; then resultado "ok $OBJ"
            else resultado "error: no anduvo $ANT, volvio a $OBJ"; fi
            exit 0
        fi
        sleep 5
    done
    falta=$("falta_$OBJ" | tr '\n' ',' | sed 's/,$//')
    if [ "$INT" = 1 ]; then
        log "no quedo en $OBJ en 5 min ($falta): vuelvo a $ANT"
        escribir "$PEDIDO" "objetivo=$ANT anterior=$OBJ intento=2"
        "config_$ANT"
        resultado "volviendo a $ANT: no anduvo $OBJ ($falta)"
        reiniciar "$ANT"
    else
        rm -f "$PEDIDO"; sync "$DIR"
        resultado "error: no quedo en $OBJ ($falta) ni volviendo; sin mas reintentos"
        exit 1
    fi
    ;;
estado)
    echo "equipo: $(modo_actual)$([ -f "$PEDIDO" ] && echo " (cambio pendiente: $(tr '\n' ' ' < "$PEDIDO"))")"
    echo "ultimo resultado: $(cat "$ESTADO" 2>/dev/null || echo -)"
    echo "modo-evento: $(systemctl is-enabled modo-evento 2>/dev/null) / $(systemctl is-active modo-evento 2>/dev/null)"
    for u in $UNIDADES; do echo "$u: $(systemctl is-enabled "$u" 2>/dev/null)"; done
    echo "arena-demo: $(systemctl is-active arena-demo 2>/dev/null)"
    echo "FPGA: $(cat /tmp/loaded_fpga.inf 2>/dev/null || echo -)"
    echo "verificar-equipo: $(systemctl is-enabled verificar-equipo 2>/dev/null)"
    ;;
instalar)
    cp "$DIR/verificar-equipo.service" "$UNIDAD_VERIF"
    systemctl daemon-reload
    systemctl enable verificar-equipo.service
    if [ ! -f "$MODO_FILE" ]; then
        if systemctl is-enabled --quiet modo-evento; then escribir "$MODO_FILE" campo; else escribir "$MODO_FILE" demo; fi
    fi
    echo "instalado; equipo: $(modo_actual)"
    ;;
*)
    echo "uso: $0 demo|campo|estado|instalar|verificar" >&2
    exit 1
    ;;
esac
