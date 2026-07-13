#!/bin/bash
# automount_usb.sh — monta o desmonta el storage de campo en /mnt/usb.
#
# No se ejecuta a mano: lo invoca mnt-usb-automount@.service (udev-automount/) como
# ExecStart (mount) y ExecStop (umount, via BindsTo=dev-%i.device cuando el
# dispositivo desaparece), disparado por la regla udev 99-automount-campo.rules al
# conectar una particion sd[a-z][0-9] (el storage externo siempre aparece como sd*,
# la SD interna de la placa es mmcblk* y nunca la toca este script).
#
# Uso: automount_usb.sh mount|umount <particion sin /dev/, ej. sda1>

set -u

ACCION="${1:?uso: automount_usb.sh mount|umount <particion>}"
DISPOSITIVO="${2:?uso: automount_usb.sh mount|umount <particion>}"
DEV="/dev/$DISPOSITIVO"
MONTAJE="/mnt/usb"
LOG="/root/logs_campo/automount_usb.log"

mkdir -p "$(dirname "$LOG")"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [automount] $*" >>"$LOG"; }

case "$ACCION" in
mount)
    if mountpoint -q "$MONTAJE"; then
        log "$DEV detectado pero $MONTAJE ya esta ocupado por otro dispositivo — no se toca."
        exit 0
    fi

    # udev ya garantiza que el nodo existe al disparar la unidad, pero blkid puede
    # devolver vacio si el kernel todavia no termino de poblar el filesystem.
    for _ in 1 2 3 4 5; do
        [ -b "$DEV" ] && break
        sleep 1
    done

    TIPO=$(blkid -o value -s TYPE "$DEV" 2>/dev/null)
    if [ -z "$TIPO" ]; then
        log "$DEV sin filesystem reconocible (blkid vacio) — no se monta."
        exit 1
    fi

    mkdir -p "$MONTAJE"
    if mount "$DEV" "$MONTAJE" 2>>"$LOG"; then
        log "$DEV ($TIPO) montado en $MONTAJE."
    else
        log "$DEV ($TIPO) fallo al montar en $MONTAJE — ver linea anterior para el error de mount. Si el filesystem quedo sucio por una desconexion abrupta, correr fsck a mano (ver scripts_campo/plan_campo/troubleshooting.md)."
        exit 1
    fi
    ;;
umount)
    if mountpoint -q "$MONTAJE" && [ "$(findmnt -n -o SOURCE "$MONTAJE" 2>/dev/null)" = "$DEV" ]; then
        umount -l "$MONTAJE"
        log "$DEV desconectado — $MONTAJE liberado (umount -l)."
    fi
    ;;
*)
    log "accion desconocida: $ACCION"
    exit 1
    ;;
esac
