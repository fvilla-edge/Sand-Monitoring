# Setup inicial en la placa (una sola vez)

Estos pasos se hacen una vez por placa. Después de un reset de firmware hay que repetirlos.
IPs según topología de red: ver `../PLAN_CAMPO.md` → "IPs según topología de red".

## 1. Copiar los scripts a la placa

```bash
scp scripts_campo/capturar_stream.py scripts_campo_comun/campo_common.py root@<IP_PLACA>:/root/scripts_campo/
scp scripts_campo_comun/relanzar_captura.sh root@<IP_PLACA>:/root/
scp scripts_campo_comun/cfg.py scripts_campo_comun/config_campo.json root@<IP_PLACA>:/root/scripts_campo_comun/
```

`cfg.py` tiene que vivir junto a `config_campo.json` en `/root/scripts_campo_comun/` — esa ruta
está hardcodeada tanto en los scripts Python (`sys.path.insert(0, '/root/scripts_campo_comun')`
en `capturar_stream.py`) como en los de Starlink (`CFG=/root/scripts_campo_comun/cfg.py` en
`control_starlink.sh` y `decidir_objetivo.sh`), y `cfg.py` busca `config_campo.json` en su propio
directorio. Sin este paso, la captura falla en el primer arranque con
`ModuleNotFoundError: No module named 'cfg'`.

## 2. Librería de streaming — persistencia automática

La placa tiene un servicio systemd (`rpsa-lib`) que extrae automáticamente la librería
`rpsa_client` al arrancar si no está presente. No hay que hacer nada en cada reinicio.

**Verificar que está activo:**
```bash
ssh root@<IP_PLACA> "systemctl is-enabled rpsa-lib && ls /root/rpsa_client/python_lib/_python_lib.so"
# Debe responder: enabled + la ruta del archivo
```

**Si la placa fue reflasheada** (firmware nuevo), reinstalar el servicio:
```bash
ssh root@<IP_PLACA> "
unzip -o /opt/redpitaya/streaming/rpsa_client-*-rp.zip -d /root/rpsa_client/
cat > /etc/systemd/system/rpsa-lib.service << 'EOF'
[Unit]
Description=Extract RPSA streaming library
Before=network.target
ConditionPathExists=!/root/rpsa_client/python_lib/_python_lib.so

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'unzip -o /opt/redpitaya/streaming/rpsa_client-*-rp.zip -d /root/rpsa_client/'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable rpsa-lib.service"
```

## 3. Montaje automático del USB (una sola vez)

Evita tener que hacer `lsblk` + `mount` a mano cada vez que se reconecta la placa o el
storage — apenas el kernel detecta la partición (`sd[a-z][0-9]`), una unidad systemd
dispara el montaje en `/mnt/usb`; al desconectarla, la misma unidad se para sola
(`BindsTo=dev-%i.device`) y su `ExecStop` libera el punto de montaje.

```bash
scp scripts_campo_comun/automount_usb.sh root@<IP_PLACA>:/root/scripts_campo_comun/
scp scripts_campo_comun/udev-automount/99-automount-campo.rules root@<IP_PLACA>:/etc/udev/rules.d/
scp scripts_campo_comun/udev-automount/mnt-usb-automount@.service root@<IP_PLACA>:/etc/systemd/system/

ssh root@<IP_PLACA> "
chmod +x /root/scripts_campo_comun/automount_usb.sh
udevadm control --reload-rules
systemctl daemon-reload
"
```

**Probar sin desconectar nada** (dispara el mismo evento que un hotplug real —
ajustar `sda1` según lo que muestre `lsblk`):

```bash
ssh root@<IP_PLACA> "udevadm trigger --action=add /sys/class/block/sda1 && sleep 2 && df -h /mnt/usb"
```

**Si algo no monta:** revisar el log dedicado (separado de `logs_campo/log_*.txt` de
captura, mismo directorio):

```bash
ssh root@<IP_PLACA> "cat /root/logs_campo/automount_usb.log"
```

Si el filesystem es exFAT, `exfatprogs` tiene que estar instalado en la placa (ver
"El USB no aparece con lsblk, o aparece pero no monta" en `troubleshooting.md`) — sin eso
`mount` falla silenciosamente para ese tipo de filesystem y queda registrado en el log.
Solo monta un dispositivo a la vez: si `/mnt/usb` ya está ocupado, el script lo deja
así y no pisa nada (ver el log para confirmarlo).

**Por qué no hay una unidad separada de desmontaje:** `systemd` ignora
`ENV{SYSTEMD_WANTS}` en eventos `remove` (solo lo procesa en `add`/`change` — limitación
documentada, no un bug de la regla). Por eso el desmontaje no se dispara con una segunda
regla udev sino con `BindsTo=` + `ExecStop=` en la misma unidad de montaje: cuando el
device unit desaparece, `systemd` para la unidad automáticamente y corre el `ExecStop`.

## 3b. Desactivar autosuspend en los hubs USB (una sola vez)

Sin esto, el kernel puede autosuspender el root hub o el hub externo alimentado a mitad
de una escritura pesada — visto en campo como `cannot reset (err=-110)` / "Maybe the USB
cable is bad?" en los puertos, journal de ext4 abortado, y en el peor caso el hub sin
volver a enumerar hasta un reboot físico de la placa (ver "El USB/SSD se desconecta solo"
en `troubleshooting.md`).

```bash
scp scripts_campo_comun/udev-automount/90-usb-autosuspend-hubs.rules root@<IP_PLACA>:/etc/udev/rules.d/

ssh root@<IP_PLACA> "
udevadm control --reload
udevadm trigger --action=add --subsystem-match=usb
cat /sys/bus/usb/devices/1-1/power/control /sys/bus/usb/devices/usb1/power/control
"
```

Ambos deben quedar en `on`. La regla matchea por `bDeviceClass==09` (clase hub) en vez
de por nombre de dispositivo (`usb1`, `1-1`), porque el devpath puede cambiar entre
boots — cubre el root hub y cualquier hub externo que se conecte, y se re-aplica sola en
cada `add` (incluido el boot), sin necesitar `echo on` a mano.

## 4. Setup para modo RED (solo si se usa `--destino red`)

La placa necesita poder conectarse a la PC por SSH sin password.
Hacer esto desde la PC:

```bash
# 1. Asegurarse de que la PC tiene servidor SSH instalado
sudo apt install openssh-server
sudo systemctl start ssh

# 2. Copiar la clave pública de la placa a la PC
ssh-copy-id -i <(ssh root@<IP_PLACA> "cat ~/.ssh/id_rsa.pub") facu-edge@<IP_PC>
```

Verificar que funciona:

```bash
ssh root@<IP_PLACA> "ssh facu-edge@<IP_PC> 'echo OK'"
# Debe imprimir OK sin pedir contraseña
```

Crear el directorio destino en la PC **antes de correr el script** (SCP falla si no existe):

```bash
mkdir -p ~/datos_campo
```

## 5. Starlink / control remoto del relé (si esta placa lo maneja)

Arquitectura, hallazgos de hardware y decisiones: `../../starlink_remoto/HISTORIAL_STARLINK.md`.
Depende de `cfg.py`/`config_campo.json` del paso 1 — no hace falta copiarlos de nuevo (si por algún
motivo se instala Starlink solo, sin el resto de este setup, copiarlos igual desde el paso 1 antes
de seguir).

```bash
cd starlink_remoto

# scripts + configuracion de mux compartida + boot + horario + decision/aplicacion + estado
scp control_starlink.sh mux_ps10_common.sh asegurar_mux_ps10.sh aplicar_horario.sh \
    decidir_objetivo.sh aplicar_objetivo.sh starlink_manual.sh estado_starlink.sh \
    root@<IP_PLACA>:/root/starlink_remoto/

# unidades systemd
scp systemd/starlink-mux-ps10.service systemd/starlink-aplicar-objetivo.service \
    systemd/starlink-rele-on.timer systemd/starlink-rele-off.timer \
    systemd/starlink-reconciliador.timer \
    root@<IP_PLACA>:/etc/systemd/system/

ssh root@<IP_PLACA> "
  chmod +x /root/starlink_remoto/*.sh
  systemctl daemon-reload
  systemctl enable --now starlink-mux-ps10.service
  systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer
  systemctl enable --now starlink-reconciliador.timer
  /root/starlink_remoto/aplicar_horario.sh
"

# alias para prender/apagar/consultar a mano por SSH (opcional, comodidad)
scp aliases.sh root@<IP_PLACA>:/root/starlink_remoto/
ssh root@<IP_PLACA> "grep -q 'prender-starlink' /root/.bashrc || cat /root/starlink_remoto/aliases.sh >> /root/.bashrc"
```

El `aplicar_horario.sh` del final no es opcional: los `.timer` de este repo tienen `hora_on`/`hora_off`
hardcodeados en su `OnCalendar=` (los valores por defecto de `config_campo.json`). Si el JSON se editó
antes de este paso, sin ese comando la placa queda armada con el horario viejo hasta que alguien lo
corra a mano — sin ningún aviso.

Uso día a día (prender/apagar a mano, cambiar horario, etc.): ver `COMANDOS.md` →
"Starlink / control remoto del relé".
