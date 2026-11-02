# Qué hacer si algo falla

Organizado por síntoma. Si no está acá, revisar `/root/logs_campo/` (ver
`formato_y_funcionamiento.md` → "Logs") antes de asumir un bug nuevo.

Primero, una foto de solo lectura de la placa (modo, servicios, última línea
`ESTADO`, relé, resultado de la última actualización):

```bash
ssh root@<IP_PLACA> 'bash -s' < scripts_campo_comun/estado_placa.sh
```

---

# Modo evento (lo que corre hoy)

## No puedo entrar por SSH a la placa del sitio

En modo ventana la Starlink está apagada salvo unos minutos cada 2 h (horas pares a
los :05, hora Argentina). Esperar la próxima ventana, o poner el tag `modo_starlink`
= `permanente` (Losant o SandVision → Estado → Modos): llega en la próxima ventana y
desde ahí queda prendida. Si no se abrió ninguna ventana en 6 h
(`starlink.rescate_ventana_horas`), la placa prende Starlink sola.

## Losant: `me_activo = false`, o `me_seg_sin_datos` creciendo

La captura no está escribiendo el CSV.

```bash
systemctl status modo-evento
journalctl -u modo-evento -n 50
tail /root/logs_campo/modo_evento_reinicios.log     # core-dump/SEGV = caída; success = parada limpia
tail /root/logs_campo/cambiar_modo.log              # ¿alguien la pasó a modo clásico?
```

- **Modo clásico:** `me_activo=false` es lo esperado. Volver con
  `bash /root/scripts_campo/cambiar_modo.sh evento`.
- **Caídas:** systemd la relanza a los 60 s, sin límite. ~1 de cada 10 arranques la
  librería del vendor se cae en `startStreaming` y se recupera en el reintento: solo
  preocupa si se repite seguido.
- **Parada a mano** (`systemctl stop modo-evento`): `systemctl start modo-evento`.
- Justo después de un reinicio de la captura (cambio de canales, ventana con la
  mitigación del relé) hay un hueco normal de ~10 s a ~2 min.

## Mide pero sin disco (`sin_disco`, CSV en `/root/eventos_sd`)

`cat /run/modo-evento/destino` dice `... sin_disco`: `/mnt/usb` no es un disco. La
placa sigue midiendo, solo CSV (sin señal cruda), en la SD. Revisar el disco con las
secciones de USB del final. Cuando vuelve a montar, `automount_usb.sh` relanza
`modo-evento` y vuelve solo a `/mnt/usb/eventos`. Los CSV de la SD suben a GCS igual,
con sufijo `_sd`.

## Losant: `me_cruda_pausada`

Queda menos de `modo_evento.minimo_libre_mb` (2048 MB) libre en el disco: la placa
dejó de guardar señal cruda y sigue con los CSV. Se reanuda sola con un 25 % de margen.
Liberar lugar borrando eventos crudos ya copiados a la PC (los CSV están en GCS, pero
no se borran solos del USB).

## SandVision / GCS sin datos nuevos

Los CSV suben recién cuando la hora se cerró y hay internet: en modo ventana el
atraso normal es de hasta ~2 h.

```bash
tail /root/logs_campo/ventanas_starlink.log     # por ventana: internet_s=, gcs="..."
journalctl -u subir-csv-gcs -n 30
python3 /root/scripts_campo/subir_csv_gcs.py --seco   # qué falta subir, sin conectarse
```

- `gcs="sin internet"` en todas las ventanas: Starlink no da internet (antena,
  alimentación, cielo). Mirar Losant `sl_*` si llegó algo.
- Errores de credenciales: `gcs.credenciales_file` (`/root/credenciales_gcs.json`).
- Si la placa no tiene disco, mirar también que haya CSV en `/root/eventos_sd`.

## El cambio mono/dual no se aplicó

```bash
cat /root/logs_campo/cambio_canales_estado    # = me_cambio en Losant
cat /run/modo-evento/medicion
```

- En modo ventana, cambiar los **tags** (`canales`, `in2_modo`), no mandar el
  comando: un comando con la placa desconectada se pierde sin error.
- `error: no midio con ... (volvio a 1)`: el modo pedido no llegó a medir en 4 min y
  la placa volvió sola al anterior. Ver `journalctl -u cambiar-canales`.
- Con los tags puestos, un comando a mano distinto lo deshace el workflow.

## La placa se reinicia al prender el relé de Starlink

Es de hardware (corriente de arranque de lo que cuelga del relé después de más de
~35-45 s en "off"), no de software: ver `actualizar_placa_campo.md` → sección 8. La
placa vuelve sola. En el sitio, con la Starlink real, la primera noche en modo ventana
no mostró resets (29-30/10).

---

# Modo clásico (`capturar_stream.py`)

Solo aplica con la placa en modo clásico (`cambiar_modo.sh clasico`).

## "No se pudo conectar al streaming-server" / "Host not found"

**Causa más probable (confirmada 2026-09-22, ver `setup_placa.md` → "2b"): `eth0` no tiene una
ruta de red válida en este momento** (cayó la interfaz, se perdió el lease DHCP durante el corte
del relé Starlink, etc.). El cliente y el servidor se descubren entre sí por un
broadcast UDP a `255.255.255.255:18902` — aunque están en la misma placa, **no** usan `127.0.0.1`
ni hostname/DNS para esto, así que un `eth0` caído rompe la conexión igual. El mensaje
`Host not found` es genérico del vendor, no es un error real de DNS.

**Verificar primero si el fix de `dummy0` está instalado** (`setup_placa.md` → "2b"):
```bash
ssh root@<IP_PLACA> "networkctl status dummy0"
```
Si no existe, instalarlo soluciona este síntoma específico durante cortes de `eth0` — validado
con 0 fallos en un corte de 150s (antes: 10/10 fallos y abandono del lote de captura entero).

**Si `dummy0` YA está instalado y el error sigue apareciendo,** entonces es la causa clásica —
el servidor no arrancó correctamente. Verificar el log:

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
