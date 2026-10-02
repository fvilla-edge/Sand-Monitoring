# Pendiente para la placa de campo (`rp-f0fbda`)

Lista viva de todo lo que la placa de campo tiene que recibir cuando se la
iguale a la placa de pruebas (`rp-f0fd8c`). Cada cambio que afecte a campo se
agrega acá en el momento, no al final.

**Estado (2026-09-30):** placa de campo con la **segunda actualización**
(sección 0) desde el 30/9 18:05 UTC: paquete `20260930_171700_4740b4e`, tag
`campo-2026-09-30`, bitstream `7f23f7d` (relé leído sin cortar la medición +
modo Master fijo + protecciones). La primera fue el 29/9 (paquete
`20260928_183636_a920731`, tag `campo-2026-09-29`, secciones 1-6). Todo se
prueba antes **solo en la placa de pruebas**, que no tiene relé real, sensor
ni ESP32.

**Abierto al 30/9 noche:** el **disco USB de 1 TB dejó de enumerar** después
de dos congelamientos (reset por watchdog del sistema, `0xF8000258` bit
SWDT) que ocurrieron segundos después de subidas a GCS; GCS quedó **apagado**
(el 1/10 se rediseñó, ver 4b). Hasta el corte de energía de la caja (el disco cuelga de un hub con
fuente externa, no se puede desenchufar a distancia) la medición sigue con dos
cosas **temporales, en `/run`, que se borran solas al reiniciar**: un drop-in
`/run/systemd/system/modo-evento.service.d/sd_temporal.conf` (CSV a
`/root/eventos_sd`, sin señal cruda) y un `tmpfs` de 64 MB montado en
`/mnt/usb` para que el anotador y el cartero publiquen a Losant (esa noche
`usb_montado`/`usb_libre_mb` en Losant no son el disco real). Después del
corte: que el disco monte, que el modo evento vuelva solo a
`/mnt/usb/eventos`, y traer y borrar `/root/eventos_sd/*.csv`.

Mismo ecosistema en las dos placas (v3.00 `e00665135`, build 57, Ubuntu
24.04.4): no hace falta reflashear.

## 0. Segunda actualización: relé sin cortar la medición + modo Master fijo

**Aplicada el 2026-09-30 18:03-18:05 UTC**, `RESULTADO: ok`, en hora_on (en
vez de esperar al día siguiente: justo antes, la verificación de 2h de las
17:59 UTC había caído en un crash-loop en Slave con la versión vieja). Ensayada
antes en la placa de pruebas **desde estado campo** (paquete del 29/9
reinstalado): normal `ok` y con `FALLA_EN=lectura_rele` `revertida` al estado
del 29/9 exacto, con los timers reanudados recién después de revertir. En
campo: `lectura directa del rele: 0x40200078=0x00000000 (bit2=0 es 'on'),
antena 192.168.100.1: responde`, arranques siempre en Master, reconciliador por
lectura directa sin paradas de la medición. Falta ver la primera conmutación
real (hora_off 20:15 UTC del 30/9) y la vuelta en hora_on.

**Por qué:** con la versión del 29/9, cada verificación del relé (cada 2h,
hora_off, hora_on) para y relanza el modo evento, y el relanzamiento es una
tirada de dados: el `streaming-server` arranca en **Slave** si el conector
daisy chain (sin nada conectado) levanta ruido, y en Slave no llegan muestras.
El 29/9: 46/46 arranques en Slave fallaron, crash-loops de ~17 min (18:02 UTC)
y ~45 min (20:03 UTC) sin medir.

**Qué va en el paquete** (uno solo, armado desde `main`):

- Bitstream `7f23f7d` de `lectura-dio` (`fpga_pitaya`): lectura de los DIO en
  `0x40200078` con DIO2_P siempre entrada, ID `0x534D0001` en `0x4020007C` y
  `daisy_slave` fijo en 0 (siempre Master; la detección queda solo en el LED
  `led_o[2]`). sha256 del `.bin`: `498e54b40fd6a834e8435ac76d95ce253c41c908173a8435d2e7f9dc48b5e817`.
- `main` con `rele-sin-cortar` mergeado: el relé se lee sin frenar el modo
  evento y `cfg.py` lee la config en una llamada (reconciliador ~1.6s de CPU
  en vez de ~7s), con las protecciones contra una lectura del relé al revés
  (ver abajo). Sin el ID del bitstream, vuelve solo al camino viejo (v0.94).

**Antes:** placa de pruebas OK con este bitstream y estos scripts (desde el
30/9: solo `Detected Master`, 0 paradas por relé, CSV completos); merge de
`rele-sin-cortar` a `main`; inventario de campo (sección 6, paso 2); armar el
paquete (paso 3); después de enviarlo, `grep -c SOLO_CHEQUEAR` sobre el
`aplicar_actualizacion.sh` **de la copia que quedó en la placa** antes de usar
el chequeo previo (el 29/9 una copia vieja sin el flag aplicó de verdad).

**Aplicar** en hora_on, igual que la sección 6 (pasos 4-6).

**Lectura del relé al revés (el riesgo principal):** la lectura nueva nunca
se probó con el relé y el transistor reales (en la placa de pruebas coincidió
con v0.94 sobre el mismo pin con 10k a 3.3V). Si diera al revés, de día el
reconciliador pulsaría y apagaría Starlink, y en hora_off lo prendería:
horario invertido sin forma de entrar (el relé corta dish y router). Dos
protecciones automáticas (`cd19c27`, probadas en la placa de pruebas el 30/9):

1. `aplicar_actualizacion.sh` (paso 5b), **antes de reanudar los timers**:
   espera al bitstream con lectura directa y comprueba que el relé se lea
   `on` (se actualiza por Starlink, tiene que estar prendido). Si se lee
   `off`, vuelve solo al respaldo: `RESULTADO_<id>` = `revertida ... estaria al
   reves`. Ningún timer llega a correr con la lectura nueva.
2. `control_starlink.sh`: nunca pulsa para `on` si la antena responde en
   `192.168.100.1:9200`; lo cuenta como fallo (aviso a los 4). Cubre también
   un cable del feedback suelto más adelante.

En el log de la actualización tiene que estar:

```
lectura directa del rele: 0x40200078=0x00000000 (bit2=0 es 'on'), antena 192.168.100.1: responde
```

- Si dice `antena ... no responde` con Starlink andando, la protección 2 no
  está cubriendo (la antena no contesta en esa dirección): no rompe nada,
  pero anotarlo y revisarlo antes de dejarla sin mirar.
- Como respaldo manual, en los primeros minutos `journalctl -u
  starlink-reconciliador -n 5` tiene que decir `OK: el rele ya esta en 'on'
  (verificado por HW)`. Si dice `desacuerdo detectado (se pidio 'on', HW en
  'off')`: `systemctl stop starlink-reconciliador.timer` y volver atrás
  (sección 6).
- Probar la vuelta automática sin tocar campo: `FALLA_EN=lectura_rele` en la
  placa de pruebas (igual que los otros `FALLA_EN` del ensayo del 28/9).

**Verificar después:**

- `/opt/redpitaya/bin/monitor 0x4020007C` = `0x534d0001` (bitstream nuevo cargado).
- `journalctl -u modo-evento | grep Detected`: solo `Detected Master mode`
  desde la actualización.
- `/root/logs_campo/modo_evento_reinicios.log`: sin
  `parada_por_verificacion_rele` nuevas (antes: cada 2h y en cada hora_on/off).
- `starlink-reconciliador`: `lectura directa` en cada corrida, ~1.6s de CPU
  (`Consumed ...` en el journal).
- **hora_off real (20:15 UTC):** `OK: rele ahora en 'off' (confirmado por HW)`
  sin frenar la medición (el CSV de la hora 20 con ~72000 ventanas). Es la
  primera conmutación real con la lectura nueva.
- **hora_on siguiente (11:55 UTC):** lo mismo en `on`, y el cartero al día.
- CSV por hora ~72000 ventanas, 0 saltadas.

**Volver atrás:** `revertir_actualizacion.sh` (sección 6) deja scripts y
bitstream del 29/9 (`dfabb64`).

## 1. FPGA

- [ ] Bitstream propio port-2026.1 en `/opt/stream_app/fpga.bin` con
      `desplegar_bitstream.sh` del repo FPGA (checksum local y remoto, backup
      del anterior; `revertir_bitstream.sh` para volver).
- [ ] No cambiar el bitstream que carga el arranque del vendor (`v0.94`): lo
      usa `control_starlink.sh` para leer el relé.

## 2. Modo evento (`scripts_campo/`, `scripts_campo_comun/`)

- [ ] `scripts_campo_comun/campo_common.py`: `asegurar_servidor(bitstream_propio=...)`
      (`4adb3ea`) y `pgrep/pkill -x streaming-serve` (`026dfd5`).
- [ ] `scripts_campo_comun/config_campo.json`: claves nuevas
      `modo_evento.minimo_libre_mb`, `starlink.verificacion_hw_con_modo_evento_h`,
      `rutas.ultima_verificacion_rele_file` (comparar con el de la placa antes
      de pisarlo: puede tener valores propios de campo).
- [ ] `scripts_campo/capturar_eventos.py` + `scripts_campo/c/` (compilar en la
      placa: `make -C /root/scripts_campo/c`).
- [ ] `scripts_campo/supervisor_eventos.sh` (espera 90s de uptime, USB
      obligatorio, poda de cores, parada por relé no cuenta como caída).
- [ ] `scripts_campo/cambiar_modo.sh` (vuelta atrás evento/clásico).
- [ ] `scripts_campo/resumen_modo_evento.py` (anotador: resumen por minuto +
      salud de la placa; `ntp_sincronizado` por adjtimex).
- [ ] Units: `scripts_campo/systemd/modo-evento.service` y
      `resumen-modo-evento.service` en `/etc/systemd/system/`,
      `daemon-reload`, `enable`.
- [ ] Destino `/mnt/usb/eventos` (nunca la SD). La prueba previa del disco
      de 1TB **no se hace** (decidido 2026-09-28): al instalarlo en campo
      verificar montaje (`findmnt /mnt/usb`), `usb_libre_mb` en Losant y que el
      modo evento escriba el CSV sin saltadas.

## 3. Control de Starlink (`starlink_remoto/`)

- [ ] `aplicar_objetivo.sh` y `control_starlink.sh` (`3ccd602`). **Sin esto el
      modo evento se corta cada 5 min** (reconciliador) y en cada hora_on/off.
      Con esto: se corta ~30s al conmutar y cada 2h con Starlink prendido
      (verificación real del relé).
- [ ] Probar en campo con el relé real: conmutación on/off con modo evento
      corriendo, y que la verificación cada 2h confirme el estado. En la placa
      de pruebas no hay relé: solo se probó el parar/reanudar.
- [ ] Primera noche en campo: revisar en el journal el paso por hora_off y la
      vuelta en hora_on (pérdida de DHCP, IP link-local 169.254.x con el link
      arriba, modo evento sin huecos ni reinicios, cartero al día al volver
      Starlink). **Ese caso no se pudo probar en la placa de pruebas**: el
      DHCP de networkd entra por socket crudo (no lo frena iptables) y el
      kernel no tiene `tc`; hace falta un switch entre la placa y el router
      de Starlink, que no hay (2026-09-28).

## 4. Losant (cartero y Device de campo)

- [ ] `panel_solar_ble/publicar_losant.py` (cartero: pendientes del USB 1/s,
      ESP32 opcional, `device_state=modo_evento`, "capturar" bloqueado con
      modo evento activo, aviso del ESP32 solo la 1ra vez; `1900628`,
      `c6dcbe6`). Revisar que el venv tenga `losantmqtt` + `pyserial`.
- [ ] `losant_config.py` de campo: credenciales del Device de **campo**
      (en la placa de pruebas está el de `test_SC`, nunca mezclarlos).
- [ ] Crear en el Device de campo los atributos que hoy existen solo en
      `test_SC`: `me_activo`, `me_ventanas_1min`, `me_ventanas_saltadas_1min`,
      `me_eventos_hoy`, `me_muestras_perdidas_1min`, `me_seg_sin_datos`,
      `kurt_ultima`, `kurt_max_1min`, `ventanas_umbral_1min`, `area_ultima`,
      `area_mediana_1min`, `area_max_1min`, `me_cruda_pausada`,
      `me_reinicios_hoy`, `ram_disp_mb`, `uptime_s`, `temp_cpu_c`,
      `ntp_sincronizado`, `usb_montado`, `sd_libre_mb` (+ `usb_libre_mb`, ya
      existía). `device_state` acepta el valor nuevo `modo_evento`.
- [ ] Dashboard y alertas en el Device de campo (inactividad del Device,
      RAM, temperatura, SD, `usb_montado`, `ntp_sincronizado`; en modo
      clásico `me_seg_sin_datos` crece, no alertar si `me_activo=false`).

## 4a. Medir sin disco y avisar a Losant (rama `medir-sin-disco`, 2026-10-01)

Probado en la placa de pruebas el 1/10 (sacando y volviendo a montar el
pendrive con `mnt-usb-automount@sda1`, y parando la captura). **Aplicado en
campo el 1/10 17:13 UTC** (script y respaldo en
`/root/instalar_sin_disco_20261001/`), sacando el drop-in temporal y el
`tmpfs` del 30/9: campo mide sin disco por el camino nuevo
(`me_estado = midiendo_sin_disco` en Losant). Al arrancar hubo 3 SIGSEGV
seguidos de `capturar_eventos` antes de que el 4to intento anduviera
(17:13-17:17 sin medir; cores en `/root/logs_campo`, causa sin analizar).
Falta probar en campo la vuelta del disco (después del corte de energía).

- [x] `supervisor_eventos.sh` + `modo-evento.service` (`ExecStart` nuevo:
      `supervisor_eventos.sh arrancar`): sin disco mide igual, solo el CSV en
      `/root/eventos_sd` sin cruda; reemplaza a mano el drop-in temporal del
      30/9 (`rearmar_temporal.sh` deja de hacer falta).
- [x] `automount_usb.sh`: al montar el disco relanza `modo-evento` si estaba
      sin disco.
- [x] `resumen_modo_evento.py` (anotador): sin disco deja los resúmenes en
      `/run/losant_pendientes` (RAM) en vez de guardarlos solo en memoria;
      `usb_montado` ya no da `true` con un `tmpfs`; atributo nuevo
      **`me_estado`** = `midiendo` / `midiendo_sin_disco` / `no_midiendo`
      (no midiendo = servicio parado o más de 30 s sin una ventana nueva).
- [x] `panel_solar_ble/publicar_losant.py` (cartero): manda los resúmenes de
      `/mnt/usb/losant_pendientes` y de `/run/losant_pendientes`.
- [x] `config_campo.json`: `rutas.eventos_sd` (lo agrega la fusión).
- [x] Losant: atributo `me_estado` (String) en el Device de campo (y en
      `test_SC`), y un bloque en el dashboard que lo muestre. Sin mail.
- Instalar con la captura parada antes del `daemon-reload` (el paquete ya lo
  hace así). Con el drop-in temporal puesto, el drop-in pisa el `ExecStart`
  nuevo hasta el reinicio: en campo se sacó a mano.

## 4b. CSV horarios a Google Cloud Storage (rama `gcs-v2`, 2026-10-01)

Historia: se prendió en campo el 30/9 y la placa se congeló dos veces
segundos después de una subida (reset por watchdog); tras la segunda el disco
USB no volvió a enumerar. El 1/10 se lo sacó del sistema y ese mismo día se
decidió volver a ponerlo, armado bien primero en la placa de pruebas y en
campo **paso a paso**. El primer congelamiento encaja con `systemctl enable
--now` y el watchdog de 5 s (sección 5, ya en 30 s); **el segundo (18:17, justo
tras una subida) sigue sin explicar**.

Qué cambió respecto del 30/9 (`subir_csv_gcs.py`, `subir-csv-gcs.{service,timer}`):
- Registro de subidos en la SD (`gcs.registro_sd` = `/root/gcs_subidos.txt`);
  el viejo de `/mnt/usb` solo se lee.
- Carga acotada: gzip 1, 2 archivos por corrida, 30 s entre archivos,
  `Nice=19`, `CPUQuota=25%`.
- Dos orígenes: `/mnt/usb/eventos` si hay disco y `/root/eventos_sd` (placa
  midiendo sin disco, sección 4a), estos con sufijo `_sd`
  (`ventanas_AAAAMMDD_HH_sd.csv.gz`) para no chocar con la misma hora del disco.
- Placa de pruebas: instalado el 1/10 18:21 UTC; los CSV viejos se marcaron
  como subidos (el usuario no quiere re-subidas de prueba).

Pasos en campo (uno por vez, mirando; `evidencia.sh on` en las subidas):
- [ ] 1. Instalar script, units, clave (`/root/credenciales_gcs.json`, 600) y
      bloque `gcs` del config **con la captura parada**; `daemon-reload` sin
      habilitar el timer.
- [ ] 2. Una subida a mano: `python3 /root/scripts_campo/subir_csv_gcs.py --max 1`.
      Los CSV de la SD de campo del 1/10 12-18 UTC **sí se suben** (decisión
      del usuario).
- [ ] 3. Varias corridas a mano seguidas (de a 2).
- [ ] 4. Habilitar el timer (cada 5 min, decisión del usuario) **con la captura parada**:
      mañana 2/10 en hora_on (11:55 UTC), mirando la primera tanda de la noche.
- [ ] 5. Con el disco de vuelta (después del corte de energía): una subida a
      mano desde `/mnt/usb/eventos` mirando, antes de dejarlo solo.
      (2/10: tras el corte el timer subió solo desde `/mnt/usb/eventos`, md5 ok.)
- [x] 6. **Sacar `CPUQuota=25%` de `subir-csv-gcs.service`** (campo: drop-in aplicado 2/10 15:28 UTC con la captura parada; lab: 2/10 15:20 UTC) (commit de este
      cambio; en una placa ya instalada alcanza el drop-in
      `/etc/systemd/system/subir-csv-gcs.service.d/sin-cpuquota.conf` con
      `[Service]` + `CPUQuota=` y `daemon-reload`, 3.6 s en la de pruebas, watchdog 30 s).
      Por qué: con `CPUQuota` systemd enciende el controlador `cpu` de cgroup v2 en
      `system.slice` mientras el timer está activo (se ve en
      `/sys/fs/cgroup/system.slice/cgroup.subtree_control`), y la captura pierde
      ventanas. Evidencia en campo [seguro]: 0 ventanas saltadas del 29/9 al 1/10
      19:21 UTC (también con Starlink on); desde 19:22:00 (`enable --now` del timer)
      5-27 saltadas/h de noche y ~600/h de día, y pérdidas de la cruda ×2.6-×3.7.
      Tras el corte del 2/10: 98 % y 0 saltadas los 5 min antes de la 1ra corrida
      de GCS (15:00:18), 88 % y ~10 saltadas/min desde 15:02, con Starlink on las dos veces.
      En la de pruebas [seguro]: el controlador queda encendido con el timer activo, se
      apaga con `systemctl stop` del timer y no se enciende con el drop-in
      (aplicado ahí el 2/10 15:20 UTC). El efecto en pérdidas en la de pruebas es chico
      (0 → 0.09 M muestras/min), así que la confirmación final es campo.
      Comprobar después en campo: `subtree_control` sin `cpu`, ventanas saltadas ~0
      y `muestras` ~98 % con Starlink on.

## 5. Sistema

- [x] **Watchdog de systemd 5 s → 30 s** (`RuntimeWatchdogSec=30s` en
      `/etc/systemd/system.conf`, se aplica con `systemctl daemon-reexec`
      **con `modo-evento` parado**). Causa probada en la placa de pruebas el
      2026-10-01: algunas operaciones de systemd tardan casi 5 s en estas
      placas (`list-unit-files` 4.5-4.75 s con la captura parada, ~5 s con la
      captura corriendo; `daemon-reload` ~3 s). Con 5 s, `list-unit-files`
      con la captura corriendo reinició la placa por watchdog al primer
      intento; con 30 s, 3 de 3 sin reinicio. Explica los reinicios del
      1/10 (limpieza de GCS) y [probable] el del 30/9 18:11 (`systemctl
      enable --now`). Lab y campo: aplicado el 1/10 (campo 16:34 UTC,
      respaldo en `/root/watchdog30_20261001/`).
      Mientras no esté en campo: **no correr `systemctl enable/disable/
      daemon-reload/list-unit-files` en campo con la captura corriendo**
      (`aplicar_actualizacion.sh` ya para la captura antes del
      `daemon-reload`).

- [ ] Journal persistente: ya lo tiene desde el 2026-08-03 con
      `SystemMaxUse=50M`; la de pruebas usa 200M (decidir, `setup_placa.md`
      sec.3c).
- [ ] `dummy0` (ya aplicado el 22/9) y `/etc/hosts` con el hostname: verificar
      que sigan.
- `apt-daily` / `apt-daily-upgrade` / `motd-news`: **se dejan como están**
  (decidido 2026-09-28). Sin `unattended-upgrades` ni `APT::Periodic` no
  actualizan nada; a veces dejan un hueco de ms en la cruda, no en área/kurtosis.
- [ ] Temperatura: el chip da ~71°C en el laboratorio (grado comercial, tope
      ~85°C). Revisar disipación/ventilación de la caja.
- [ ] Jumper de IN1 en **HV** (campo ya está en HV; confirmar).

## 6. Procedimiento de actualización (`scripts_campo/actualizacion/`)

Ensayado el 2026-09-28 en la placa de pruebas puesta en **estado campo**
(copia exacta de `rp-f0fbda` según `inventario_placa.sh`): actualización
normal, paquete cortado a mitad de camino, SSH cortado al lanzar, falla
forzada al final (vuelve sola) y vuelta atrás a mano. Los paquetes y el
estado de cada placa quedan fuera de git (`paquetes_actualizacion/`,
`datos_campo/inventarios/`).

**Antes (en la oficina):**

1. Crear en el Device de campo los atributos de la sección 4 (si no, Losant
   descarta esos datos).
2. Inventario de la placa de campo (solo lectura) y compararlo con el último,
   para ver que no cambió nada por fuera desde el inventario del 2026-09-28:
   ```bash
   ssh root@<IP_CAMPO> 'bash -s' < scripts_campo_comun/inventario_placa.sh \
       > datos_campo/inventarios/inventario_rp-f0fbda_<fecha>.txt
   ```
3. Armar el paquete desde el commit a instalar (compila el binario en la
   placa de pruebas, en `/tmp`, sin tocar lo instalado):
   ```bash
   bash scripts_campo/actualizacion/armar_paquete_actualizacion.sh \
       --bitstream ~/RedPitaya-FPGA-Release_2025.2/prj/stream_app/out/red_pitaya.bin \
       --compilar-en root@192.168.0.136
   ```

**En la ventana de Starlink (hora_on), con tiempo para volver:**

4. Mandar el paquete. No toca nada instalado; reintenta si se corta y lo
   verifica por sha256 en la placa:
   ```bash
   bash scripts_campo/actualizacion/enviar_paquete.sh root@<IP_CAMPO> paquetes_actualizacion/actualizacion_<id>.tgz
   ```
   Antes de aplicar, chequeos previos sin cambiar nada (checksums, USB
   montado, espacio, sin captura, paquete no aplicado antes):
   ```bash
   ssh root@<IP_CAMPO> 'SOLO_CHEQUEAR=1 bash /root/actualizacion/<id>/aplicar_actualizacion.sh /root/actualizacion/<id>'
   ```
5. Aplicar. Se desacopla solo (un corte de SSH no lo frena) y tarda ~1-2 min:
   ```bash
   ssh root@<IP_CAMPO> 'bash /root/actualizacion/<id>/aplicar_actualizacion.sh'
   ssh root@<IP_CAMPO> 'cat /root/actualizacion/RESULTADO_<id>'   # ok / abortada / revertida
   ```
   Hace: chequeos previos (sin cambiar nada) → pausa del control de Starlink
   → respaldo en `/root/respaldos_actualizacion/<id>/` → instala (la config se
   fusiona: agrega claves, no pisa valores; `losant_config.py` no se toca) →
   `cambiar_modo.sh evento` → verifica (servicios, cartero sin reinicios,
   reconciliador, bitstream propio). Si algo falla después de empezar a
   instalar, **vuelve solo** al respaldo. Log: `/root/logs_campo/actualizacion_<id>.log`.
6. Verificar con `ssh root@<IP_CAMPO> 'bash -s' < scripts_campo_comun/estado_placa.sh`
   (solo lectura: modo, servicios, ESTADO, temperatura, relé, cartero,
   resultado de la actualización) y desde afuera: puntos nuevos en Losant del Device de campo
   (`device_state=modo_evento`, `me_activo=true`, ventanas ~1200/min) y
   `journalctl -u modo-evento -n 3` en la placa.

**Si después algo se porta mal:**

- Pasar a modo clásico sin desinstalar: `bash /root/scripts_campo/cambiar_modo.sh clasico`.
- Volver a como estaba antes de la actualización:
  ```bash
  ssh root@<IP_CAMPO> 'R=/root/respaldos_actualizacion/<id>; systemd-run --unit=revertir --collect bash $R/revertir_actualizacion.sh $R'
  ```

**Lo que el ensayo no cubrió (diferencias de la placa de pruebas):** relé real
(en pruebas un cable fija el feedback en "on" y Starlink queda en modo manual),
ESP32, RTC, fail2ban y el Device de campo de Losant. Tampoco un enlace
Starlink real durante la transferencia (el ensayo fue por LAN).

## Después (no bloquea)

- Opción 2 del relé (lectura de los DIO en el bitstream propio, relé leído
  sin cortar la medición) + modo Master fijo: **lista para campo, ver la
  sección 0**. Circuito del feedback: pad del módulo → 1k → base NPN,
  colector a DIO2_P con 10k a 3.3V de la Pitaya.
- Piloto con sensor y arena real: **no se hace** (decidido 2026-09-28). La
  validación de la detección queda para los primeros días en campo: cruzar
  los eventos (`kurt_max_1min`, `me_eventos_hoy`, `evento_*.json`) con los
  pases de arena que informe el pozo, como con las 3 franjas del 21/9.
