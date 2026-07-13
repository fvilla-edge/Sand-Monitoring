# Setup inicial en la placa (una sola vez)

Estos pasos se hacen una vez por placa. Después de un reset de firmware hay que repetirlos.
IPs según topología de red: ver `../PLAN_CAMPO.md` → "IPs según topología de red".

## 1. Copiar los scripts a la placa

```bash
scp scripts_campo/capturar_stream.py scripts_campo_comun/campo_common.py root@<IP_PLACA>:/root/scripts_campo/
scp scripts_campo_comun/relanzar_captura.sh root@<IP_PLACA>:/root/
```

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
