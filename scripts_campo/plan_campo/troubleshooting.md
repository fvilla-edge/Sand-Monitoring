# Qué hacer si algo falla

Organizado por síntoma. Si no está acá, revisar `/root/logs_campo/` (ver
`formato_y_funcionamiento.md` → "Logs") antes de asumir un bug nuevo.

## "No se pudo conectar al streaming-server"

El servidor no arrancó correctamente. Verificar el log:

```bash
cat /tmp/sstream_campo.log
```

Si el log muestra errores de bitstream, cargar el overlay a mano:

```bash
/opt/redpitaya/sbin/overlay.sh stream_app
sleep 2
/opt/redpitaya/bin/streaming-server -v &
```

## La eficiencia cae por debajo de 90%

Verificar que `STREAM_DIR` no sea un symlink al USB (de una sesión anterior con una versión
vieja del script). Si existe el symlink, el script lo elimina automáticamente al arrancar.
Verificar manualmente:

```bash
ls -la /home/redpitaya/streaming_files/adc
# Debe ser un directorio, no un symlink. Si es symlink: rm adc && mkdir adc
```

## "startStreaming fallo" en el chunk 2

Indica que el servidor quedó en estado inconsistente. Reiniciar el streaming-server:

```bash
pkill streaming-server
sleep 2
/opt/redpitaya/bin/streaming-server -v &
```

## Ctrl+C tarda en cortar la sesión

Con streaming activo, Ctrl+C sí corta la sesión de forma limpia (no hay que matar el
proceso), pero no es inmediato: el loop principal solo revisa la señal una vez por chunk,
así que el corte real llega recién cuando termina el chunk en curso — con
`--duracion_chunk` grande (hasta 2 min, ver `formato_y_funcionamiento.md`) esto puede
tardar hasta esos minutos. Es esperable, no un cuelgue: si tarda, esperar a que termine
el chunk en vez de matar el proceso a la fuerza (matarlo a mitad de chunk sí pierde ese
chunk).

## Modo RED: "Permission denied" o cuelga en scp

La clave SSH de la placa no está en el `authorized_keys` de la PC. Repetir el setup de clave:

```bash
ssh-copy-id -i <(ssh root@<IP_PLACA> "cat ~/.ssh/id_rsa.pub") facu-edge@<IP_PC>
```

Verificar que el servidor SSH de la PC esté corriendo:

```bash
sudo systemctl status ssh
```

## "No module named 'streaming'"

La librería no está extraída. Verificar el servicio systemd:

```bash
ssh root@<IP_PLACA> "systemctl status rpsa-lib"
```

Si el servicio no existe (placa reflasheada), reinstalar siguiendo `setup_placa.md` → 2.

## Espacio insuficiente en USB

El script frena automáticamente (corte limpio, guarda el último chunk, sesión
termina con exit 0, no se relanza) cuando quedan menos de 500 MB × `--canales`
libres (1 GB con `--canales 2`). Umbral configurable en
`config_campo.json` → `espacio.minimo_mb_por_canal` (ver
`formato_y_funcionamiento.md`). Montar un storage más grande o borrar capturas ya
copiadas a la PC.

## El USB no aparece con lsblk, o aparece pero no monta

```bash
dmesg | tail -20    # ver últimos mensajes del kernel al conectar el USB
```

Probar desconectar y volver a conectar el USB. Si quedó en estado inconsistente por una
desconexión abrupta, correr `fsck -f -y /dev/sda1` (ajustar el device según `lsblk`) antes
de montar. Si el sistema de archivos es exFAT:

```bash
apt-get install exfatprogs -y
mount /dev/sda1 /mnt/usb
```

## El USB/SSD se desconecta solo, incluso en reposo

Revisar `bMaxPower` del dispositivo con `lsusb -v` — 500 mA (el máximo del estándar USB)
es señal de que el puerto de la placa puede no sostenerlo. Usar un hub USB alimentado en
vez de conectar directo a la placa.

Si además `dmesg` muestra `cannot reset (err=-110)` en más de un puerto del hub casi al
mismo tiempo, y `/sys/bus/usb/devices/1-1/power/control` (o `usb1`) está en `auto`, es el
autosuspend cortando el hub entero a mitad de una escritura — ver `setup_placa.md` → "3b.
Desactivar autosuspend en los hubs USB" (se instala una sola vez, no hace falta
reaplicarlo a mano en cada sesión). Si el hub ya quedó sin re-enumerar (no aparece en
`lsusb -t` ni con `udevadm trigger`), un `unbind`/`bind` por software puede no alcanzar
(`can't set config #1, error -22`) — en ese caso hace falta reboot de la placa (o
desconectar/reconectar el hub físicamente) antes de `fsck` y remontar.
