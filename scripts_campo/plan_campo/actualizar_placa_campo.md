# Pendiente para la placa de campo (`rp-f0fbda`)

Lista viva de todo lo que la placa de campo tiene que recibir cuando se la
iguale a la placa de pruebas (`rp-f0fd8c`). Cada cambio que afecte a campo se
agrega acá en el momento, no al final.

**Estado:** placa de campo **actualizada el 2026-09-29** (paquete
`20260928_183636_a920731`, tag `campo-2026-09-29`): modo evento 24h, cartero
nuevo, bitstream propio `dfabb64`. Las secciones 1-6 son las de esa primera
actualización; la próxima está en la sección 0. Todo se prueba antes **solo en
la placa de pruebas**, que no tiene relé real, sensor ni ESP32.

Mismo ecosistema en las dos placas (v3.00 `e00665135`, build 57, Ubuntu
24.04.4): no hace falta reflashear.

## 0. Próxima actualización: relé sin cortar la medición + modo Master fijo

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
- Van también los archivos de GCS (sección 4b) pero **quedan inactivos**:
  `aplicar_actualizacion.sh` solo habilita `modo-evento` y
  `resumen-modo-evento`. GCS se prende después, aparte (sección 4b).

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

## 4b. CSV horarios a Google Cloud Storage (en `main` desde el 2026-09-30)

Se prende **aparte**, después de la actualización de la sección 0: el paquete
ya instala los archivos y las units, pero no habilita el timer.

- [ ] `scripts_campo/subir_csv_gcs.py` + `scripts_campo/systemd/subir-csv-gcs.{service,timer}`
      (los instala el paquete). Sube cada hora cerrada, gzip 6
      (~3 MB → ~0.7 MB, ~2.7 s de CPU), a
      `campo/csv_ventanas/<hostname>/AAAA/MM/DD/` del bucket
      `vista-sandvision-scout-files` (la placa de pruebas usa
      `pruebas/csv_ventanas/`); sin internet reintenta cada 10 min.
- [ ] `config_campo.json`: bloque `gcs` (lo agrega la fusión de config del
      paquete con `prefijo: campo/csv_ventanas` y `dias_atras: 7`: la primera
      vez sube hasta 7 días viejos, de a 6 horas por corrida).
- [ ] Prender, en hora_on: copiar la clave (`scp credenciales.json
      root@<IP_CAMPO>:/root/credenciales_gcs.json`, `chmod 600`), correr una vez
      a mano (`systemctl start subir-csv-gcs.service`,
      `journalctl -u subir-csv-gcs -n 10`), ver los primeros `.csv.gz` en la
      consola de Google Cloud bajo `campo/csv_ventanas/rp-f0fbda/`, y recién
      ahí `systemctl enable --now subir-csv-gcs.timer`.
- [ ] Clave de la cuenta de servicio `sandscout` en `/root/credenciales_gcs.json`
      (`chmod 600`, nunca en git ni en el paquete de actualización: copiarla
      aparte). La cuenta tiene **solo** `storage.objects.create` desde el
      2026-09-29: puede subir, no leer, listar ni borrar. Bajar los CSV: consola
      web de Google Cloud (o otra cuenta de lectura, solo en la PC).

## 5. Sistema

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

- Opción 2 del relé: registro de lectura de los DIO en el bitstream propio
  (confirmar el relé sin cortar la medición). Antes ver el esquema del
  circuito del feedback.
- Piloto con sensor y arena real: **no se hace** (decidido 2026-09-28). La
  validación de la detección queda para los primeros días en campo: cruzar
  los eventos (`kurt_max_1min`, `me_eventos_hoy`, `evento_*.json`) con los
  pases de arena que informe el pozo, como con las 3 franjas del 21/9.
