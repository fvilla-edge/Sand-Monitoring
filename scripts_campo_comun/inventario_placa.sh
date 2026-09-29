#!/bin/bash
# inventario_placa.sh — foto de SOLO LECTURA del estado de una placa: que
# archivos del proyecto tiene (sha256), que units/timers estan instalados y
# habilitados, y los archivos de /etc que el proyecto toca. Sirve para
# comparar la placa de campo con la de pruebas y con el repo antes de
# actualizar (scripts_campo/plan_campo/actualizar_placa_campo.md).
#
# No escribe nada en la placa ni habla con PID1 (sin systemctl list-*: se
# leen los directorios de systemd). No imprime el contenido de archivos con
# credenciales (losant_config.py, credenciales*): solo su sha256.
#
# Uso (desde la PC):
#   ssh root@<IP> 'bash -s' < scripts_campo_comun/inventario_placa.sh > inventario_<placa>.txt
set -u
export LC_ALL=C

seccion() { printf '\n## %s\n' "$1"; }

seccion "placa"
echo "hostname=$(hostname) fecha_utc=$(date -u +%FT%TZ) uptime_s=$(cut -d. -f1 /proc/uptime)"
grep -E "Version|Build" /opt/redpitaya/version.txt 2>/dev/null
grep PRETTY_NAME /etc/os-release
uname -r
cat /tmp/loaded_fpga.inf 2>/dev/null && echo

seccion "/root (primer nivel)"
ls -1A /root

seccion "archivos del proyecto (sha256)"
for d in scripts_campo scripts_campo_comun starlink_remoto panel_solar_ble starlink_api rtc_ds3231 indicador_estado; do
    [ -d "/root/$d" ] || continue
    [ -L "/root/$d" ] && echo "# /root/$d -> $(readlink -f "/root/$d")"
    # -L: seguir enlaces (en campo algunas carpetas/archivos son symlinks)
    find -L "/root/$d" -type f \
        -not -path '*/__pycache__/*' -not -path '*/venv/*' -not -path '*/.venv/*' \
        -not -name '*.pyc' -not -name '*.log' -not -name '*.bin' -not -name 'core*' \
        -size -5M -print0 | sort -z | xargs -0 -r sha256sum
done

seccion "bitstreams (sha256)"
for f in /opt/stream_app/fpga.bin /opt/stream_app/fpga.bin.bak_* \
         /opt/redpitaya/fpga/*/stream_app/fpga.bin /opt/redpitaya/fpga/*/v0.94/fpga.bin; do
    [ -f "$f" ] && sha256sum "$f"
done

seccion "units propias en /etc/systemd/system (sha256; -> destino si es enlace)"
for u in /etc/systemd/system/*.service /etc/systemd/system/*.timer /etc/systemd/system/*.path; do
    [ -e "$u" ] || continue
    if [ -L "$u" ]; then
        echo "$(sha256sum < "$u" | cut -d' ' -f1)  $u -> $(readlink "$u")"
    else
        sha256sum "$u"
    fi
done

seccion "habilitadas (*.wants)"
for w in /etc/systemd/system/*.wants; do
    for u in "$w"/*; do [ -e "$u" ] || [ -L "$u" ] && echo "$(basename "$w") -> $(basename "$u")"; done
done | sort

seccion "drop-ins"
find /etc/systemd/system -mindepth 2 -path '*.d/*' -type f -print0 | sort -z | xargs -0 -r sha256sum
find /etc/systemd/journald.conf.d /etc/systemd/system.conf.d -type f 2>/dev/null -print0 | sort -z | xargs -0 -r sha256sum

seccion "red y sistema (sha256)"
for f in /etc/fstab /etc/hosts /etc/systemd/network/* /etc/ssh/sshd_config /etc/fail2ban/jail.local \
         /etc/udev/rules.d/* /etc/tmpfiles.d/* /etc/systemd/system.conf /etc/systemd/journald.conf; do
    [ -f "$f" ] && sha256sum "$f"
done

seccion "fstab (sin comentarios)"
grep -vE '^\s*(#|$)' /etc/fstab

seccion "hosts"
grep -vE '^\s*(#|$)' /etc/hosts

seccion "cron"
crontab -l 2>/dev/null || echo "(sin crontab de root)"
ls -1 /etc/cron.d 2>/dev/null

seccion "config_campo.json"
cat /root/scripts_campo_comun/config_campo.json 2>/dev/null || echo "(no existe)"

seccion "credenciales (solo sha256, nunca el contenido)"
find /root -maxdepth 3 \( -name 'losant_config*.py' -o -name 'credenciales*' \) -type f -print0 \
    | sort -z | xargs -0 -r sha256sum

seccion "entornos Python del proyecto"
for py in $(find /root -maxdepth 4 -path '*/bin/python3' 2>/dev/null); do
    echo "== $py"
    "$py" -m pip freeze 2>/dev/null
done

seccion "USB"
findmnt -no SOURCE,FSTYPE,SIZE,AVAIL /mnt/usb 2>/dev/null || echo "(sin /mnt/usb montado)"
