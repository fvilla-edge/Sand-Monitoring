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
- [x] **Umbral de captura de la cruda 5 → 3.4** (pedido del usuario, 2026-10-05;
      placa de pruebas 18:11 UTC, **campo 18:15 UTC**, sin validar con señal en
      lab porque no hay forma de generar kurtosis 3.4-5 ahí). En campo el 1er
      arranque murió por el SIGSEGV del vendor al conectar ("Operation aborted",
      core dump) y el relanzamiento de systemd a los 60 s quedó bien.
      Script usado en campo: `/root/logs_campo/aplicar_umbral_34.sh` (log al lado).
      Drop-in (desde el 5/10 la unit del repo también trae 3.4; el drop-in
      queda en las placas ya instaladas para no reinstalar la unit). Defaults de
      `capturar_eventos.py` y del `.cpp` también en 3.4 (probado en pruebas 5/10:
      corrida sin `--umbral` arranca en 3.40); **en campo instalados el 5/10
      18:33 UTC** (compilado aparte con la captura andando, después stop → copiar →
      start; script y log `/root/logs_campo/aplicar_defaults_34.*`, respaldo de lo
      anterior en `/root/respaldo_umbral_20261005/`):
      ```bash
      mkdir -p /etc/systemd/system/modo-evento.service.d
      printf '[Service]\nEnvironment=UMBRAL=3.4\n' > /etc/systemd/system/modo-evento.service.d/umbral.conf
      systemctl daemon-reload && systemctl restart --no-block modo-evento
      ```
      Verificar: `journalctl -u modo-evento | grep "umbral kurtosis>=3.40"`.
      Volver a 5: borrar `umbral.conf`, `daemon-reload`, `restart`. El anotador
      (`ventanas_umbral_1min`, `me_eventos_hoy` en Losant) toma el umbral nuevo
      solo. Volumen esperado con los CSV de campo 29/9-5/10: ~2.7× eventos
      (51/h contra 19/h, ~0.6 GB/día en el disco; peor hora ~1350 eventos, ~720 MB).
- [ ] **Dos canales + decimación configurable** (rama `dos-canales`,
      `docs/plan_dos_canales.md`, 2026-10-06; **solo en la placa de pruebas**).
      Va todo junto: `c/capturar_eventos.cpp` (compilar en la placa),
      `capturar_eventos.py`, `supervisor_eventos.sh`, `resumen_modo_evento.py`
      y `systemd/modo-evento.service` (unit nueva: `daemon-reload` con la
      captura parada). Con la unit nueva y sin drop-in la placa sigue en mono
      dec32 como hoy. Cambios que se notan aunque siga en mono:
      - el CSV de ventanas suma una 7.ª columna `dec` (32/64); en la PC
        `organizar_csv_campo.py` y `ventanas_a_paquete.py` ya la entienden
        (los CSV viejos de 6 columnas = dec32);
      - el `.json` de cada evento suma `dec` y `canales`;
      - el arranque tarda ~1 s más (verifica la ventana de la FPGA);
      - Losant recibe `me_canales` y `me_dec`: **crear los atributos (Number)
        en el Device de campo y en `test_SC`**.
      Pasar a dual (antes: confirmar físicamente qué hay en el IN2 de campo y
      su jumper): drop-in `canales.conf` con `Environment=CANALES=2` (DEC
      queda en 64 solo), `daemon-reload` con la captura parada, `start`.
      Verificar: `cat /run/modo-evento/medicion` = `canales=2 dec=64` y en el
      journal `IN2: muestras=100%`. Volver a mono: borrar `canales.conf`.
      OJO dual: el umbral 3.4 y la escala FPGA/software de la PC están medidos
      a dec32 (a dec64 el área de reposo da ~0.575 en vez de ~0.514).
      **Reemplazado por el IN2 como sensor independiente** (rama `in2-sensor`,
      `docs/plan_in2_independiente.md`, en curso): requiere además el
      bitstream nuevo (fpga_pitaya `20ac88b`+); con el bitstream viejo el
      software nuevo mide solo el IN1 aunque esté en dual. El IN1 ya no
      guarda `_ch2.bin`; el IN2 tiene eventos y CSV en `<destino>/in2/`,
      que suben a GCS con sufijo `_in2`; Losant recibe `kurt_max_1min_in2`
      y `area_max_1min_in2` (**crear los atributos, Number, en el Device de
      campo y en `test_SC`**). Va en la etapa 9 del plan: primero el
      bitstream solo con el software actual en mono.
      **Cambio mono/dual desde Losant** (`docs/plan_cambio_canales_remoto.md`,
      2026-10-06, probado en `test_SC`): comando `canales` con
      `{"canales": 1|2}`. Archivos: `cambiar_canales.sh` (nuevo),
      `supervisor_eventos.sh`, unit (ya **sin** `Environment=CANALES`: el modo
      sale de `config_campo.json` `modo_evento.canales`, que agrega la fusión
      con valor 1), `cfg.py` (`--poner` atómico), `resumen_modo_evento.py`
      (`me_cambio`), `panel_solar_ble/publicar_losant.py` (cartero: reiniciar
      `panel-solar-informe`), `fusionar_config.py` (fsync). **Crear el
      atributo `me_cambio` (String) en el Device de campo.** Si en campo
      queda algún drop-in `canales.conf`, borrarlo (le gana al config).
      Incluye el parche del SIGSEGV de arranque del vendor (`connect()` en un
      hilo propio; en lab 0/20 caídas contra 3/10 sin parche): es la caída
      que se vio en campo el 5/10 al aplicar el umbral 3.4.

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
- [x] **Starlink también sábado y domingo** (decisión del equipo, 2026-10-05; **aplicado
      2026-10-05 13:16 UTC** en lab `rp-f0fd8c` y después en campo, respaldo
      `config_campo.json.bak_pre_finde_20261005`; simulado día 6/7 con `date` falso
      en el PATH: 10/10 casos OK en lab y 8/8 en campo; reconciliador real OK; falta
      ver el sábado 10/10 08:55 local):
      `starlink.dias_habilitados` de `"1,2,3,4,5"` a `"1,2,3,4,5,6,7"` en
      `/root/scripts_campo_comun/config_campo.json`, mismo horario. Solo
      config: los timers ya disparan todos los días y `decidir_objetivo.sh`
      lo lee en cada corrida (sin reinicios ni daemon-reload). Antes de editar,
      comparar la copia de la placa con el repo y guardar respaldo. Verificar:
      `bash /root/starlink_remoto/decidir_objetivo.sh` (en horario de un día
      hábil tiene que decir `on`) y el sábado siguiente, a las 08:55 local, el
      journal de `starlink-aplicar-objetivo` tiene que decir "rele ahora en 'on'".

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

## 4c. Registro de energía (rama `registro-energia`, ex `perfiles-energia`, 2026-10-07)

Plan: `docs/plan_perfiles_energia.md` (etapas 1, 1b y 2). Sale de `main` =
tag `campo-2026-10-05b` (`3dd05e9`): va a campo antes que el IN2. **No toca
el relé, el horario de Starlink ni el modo evento**: solo el proceso que
publica a Losant (`panel-solar-informe`), la subida a GCS y el config.

Qué cambia:
- `panel_solar_ble/registro_energia.py` (nuevo): una fila por minuto en
  `/mnt/usb/energia/energia_AAAAMMDD_HH.csv` (sin USB, `/root/energia_sd/`).
- `panel_solar_ble/balance_energia.py` (nuevo): SOC, energía de la hora y
  del día, resumen horario `<ms>.energia.json` en la cola del cartero.
  Estado en `/root/energia_estado.json` (SD).
- `panel_solar_ble/publicar_losant.py`: los llama (si fallan, avisa una
  vez y el informe sigue igual).
- `scripts_campo/subir_csv_gcs.py`: sube también los CSV de energía a
  `campo/energia/<hostname>/AAAA/MM/DD/`. Reestructura el bucle de subida:
  **verificar que los CSV de ventanas sigan subiendo**.
- `config_campo.json`: clave `energia` (se fusiona; sin ella los scripts usan
  los mismos valores por defecto).

**Aplicado en campo 2026-10-08 18:28 UTC** (pasos 3-7 OK: inventario = tag
`campo-2026-10-05b`, respaldo en `/root/respaldo_registro_energia_20261008`,
md5 = rama `registro-energia` @ `aeb470c`, config solo agregó `energia`,
publicador `active` sin reinicios, CSV de energía con lecturas). Paso 9 OK
(19:03 UTC subieron `ventanas_20261008_18` y `energia_20261008_18`). Paso 8
con **bug**: el MPPT reportó "float" 18:38-18:41 UTC descargando (i_bat < 0,
V volviendo a 12,9) y `balance_energia.py` calibró el SOC a 100 % confiable:
`en_soc_*` y autonomías falsos hasta el arreglo. Tag `campo-2026-10-08` = lo
que está en la placa (con el bug), sobre `registro-energia`, sin merge a
`main` todavía.

### Camino para instalarlo (actualización puntual, sin paquete)

Se eligió copiar solo los 4 archivos en vez del paquete de la sección 6: el
paquete para el modo evento y recarga el bitstream, y acá no cambia nada de
eso. Vuelta atrás = volver a copiar los 4 archivos y el config del respaldo.

**Antes (oficina):**
1. Crear en el Device de **campo** los 14 atributos (Number salvo
   `en_soc_confiable`, Boolean): `en_soc_pct`, `en_soc_confiable`,
   `en_energia_restante_wh`, `en_autonomia_sin_sl_h`,
   `en_autonomia_con_sl_dias`, `en_balance_dia_wh`, `en_minutos`,
   `en_starlink_min`, `en_p_carga_w`, `en_e_carga_wh`, `en_e_pv_wh`,
   `en_e_bat_wh`, `en_v_min`, `en_sin_lecturas_min`.
   (`en_sin_lecturas_min` no es del resumen horario: va con el informe cada
   15 min = minutos sin lectura valida del ESP32, 0 = todo bien.)
2. Placa de campo prendida (salida LOAD del MPPT encendida, con captura de
   su configuración antes) y con Starlink.

**En la placa de campo (ventana de Starlink):**
3. Inventario de solo lectura y compararlo con `inventario_rp-f0fbda_20260930.txt`
   (que nada haya cambiado por fuera).
4. Respaldo de lo que se va a tocar:
   ```bash
   ssh root@<IP_CAMPO> 'R=/root/respaldo_registro_energia_$(date +%Y%m%d); mkdir -p $R &&
     cp -p /root/panel_solar_ble/publicar_losant.py /root/scripts_campo/subir_csv_gcs.py \
           /root/scripts_campo_comun/config_campo.json $R/ && ls -l $R'
   ```
5. Copiar los 4 archivos de la rama y el config del repo a un temporal,
   verificar md5 contra la PC, y fusionar el config:
   ```bash
   git switch registro-energia
   scp panel_solar_ble/{registro_energia.py,balance_energia.py,publicar_losant.py} root@<IP_CAMPO>:/root/panel_solar_ble/
   scp scripts_campo/subir_csv_gcs.py root@<IP_CAMPO>:/root/scripts_campo/
   scp scripts_campo_comun/config_campo.json root@<IP_CAMPO>:/tmp/config_nuevo.json
   scp scripts_campo/actualizacion/fusionar_config.py root@<IP_CAMPO>:/tmp/
   ssh root@<IP_CAMPO> 'python3 /tmp/fusionar_config.py /root/scripts_campo_comun/config_campo.json /tmp/config_nuevo.json'
   # esperado: "claves agregadas: energia"
   ```
6. Reiniciar solo el publicador y mirar que no se reinicie solo:
   ```bash
   ssh root@<IP_CAMPO> 'systemctl restart panel-solar-informe; sleep 60;
     systemctl is-active panel-solar-informe; systemctl show -p NRestarts --value panel-solar-informe;
     journalctl -u panel-solar-informe --since "-2min" --no-pager | tail -15'
   ```
   Esperado: `active`, `0`, "Conectado a Losant", lecturas del ESP32, sin
   "Registro de energia: fallo" ni "sin lecturas validas del ESP32".
   En Losant `en_sin_lecturas_min` = 0.

**Verificación (en la hora siguiente):**
7. A los ~2 min: `/mnt/usb/energia/energia_<hoy>_<hora UTC>.csv` con filas
   por minuto y `lecturas` > 0; `/root/energia_estado.json` existe.
8. Al cerrar la primera hora completa: el resumen `en_*` en el Device de
   campo, con la hora original. SOC arranca en 50 % no confiable (se calibra
   en el primer float).
9. En el journal de `subir-csv-gcs`, después de la hora cerrada: sube el
   `energia_..._HH.csv.gz` **y siguen subiendo los `ventanas_*`**.
10. Si todo bien: merge `registro-energia` → `main` ("Registro de energía
    (sin perfiles)") y tag `campo-2026-10-08` sobre ese commit.

**Si algo se porta mal** (el publicador se reinicia solo, no llegan datos
a Losant, no suben las ventanas):
```bash
ssh root@<IP_CAMPO> 'R=/root/respaldo_registro_energia_<fecha>;
  cp -p $R/publicar_losant.py /root/panel_solar_ble/ && cp -p $R/subir_csv_gcs.py /root/scripts_campo/ &&
  cp -p $R/config_campo.json /root/scripts_campo_comun/ && systemctl restart panel-solar-informe'
```
(`registro_energia.py` y `balance_energia.py` pueden quedar: el publicador
viejo no los importa.)

### 4c-bis. Arreglo del float falso (sobre `campo-2026-10-08`)

El 8/10 18:38-18:41 UTC el MPPT dijo "float" descargando y el SOC quedó en
100 % confiable (falso). `balance_energia.py` ahora solo calibra con float
**sostenido**: 10 min seguidos con `v_bat_min >= 13,3` e `i_bat >= -0,1`.
Un solo archivo; el estado viejo (sin `float_racha`) se carga igual. Hay que
**resetear el SOC** en campo: el 100 % guardado es falso.

```bash
# 1. respaldo + copia (verificar md5 contra la PC)
ssh root@<IP_CAMPO> 'R=/root/respaldo_registro_energia_$(date +%Y%m%d); mkdir -p $R &&
  cp -p /root/panel_solar_ble/balance_energia.py /root/energia_estado.json $R/ && ls -l $R'
scp panel_solar_ble/balance_energia.py root@<IP_CAMPO>:/root/panel_solar_ble/
ssh root@<IP_CAMPO> 'md5sum /root/panel_solar_ble/balance_energia.py'
# 2. parar el publicador (escribe el estado cada minuto), resetear SOC, arrancar
ssh root@<IP_CAMPO> 'systemctl stop panel-solar-informe && python3 -c "
import json; f=\"/root/energia_estado.json\"; e=json.load(open(f))
e.update(soc_ah=50.0, ultimo_float=None, float_racha=0)
json.dump(e, open(f, \"w\")); print(e)"; sync; systemctl start panel-solar-informe;
  sleep 75; systemctl is-active panel-solar-informe; systemctl show -p NRestarts --value panel-solar-informe;
  python3 -c "import json; e=json.load(open(\"/root/energia_estado.json\")); print(e[\"soc_ah\"], e[\"ultimo_float\"], e[\"float_racha\"])"'
```
Esperado: `active`, `0`, SOC ~50 Ah, `ultimo_float` `None`. En Losant, desde
el siguiente resumen horario, `en_soc_confiable = false`. El SOC queda en
50 % no confiable hasta el primer float sostenido.

## 4d. Comando de Losant para apagar Starlink (rama `comando-starlink`, 2026-10-08)

- [ ] Comando `starlink` con payload `{"accion": "off"}` = `apagar-starlink`
  (a los 10 s, unidad `apagar-starlink-losant`); avisa antes con el atributo
  `starlink_comando` = `"off"`. Solo "off": apagada, Losant ya no llega.
  Vuelve sola al día siguiente en `hora_on` (ver COMANDOS.md). Probado en el
  lab 8/10 desde `test_SC` (off ejecutado, `{"accion":"on"}` ignorado).

Instalación (solo `publicar_losant.py`, desde un commit que ya tenga
registro-energia; md5 = el de la rama):
1. Crear en el Device de campo el atributo **`starlink_comando`** (String).
2. Respaldo + copia + restart:
```bash
ssh root@<IP_CAMPO> 'mkdir -p /root/respaldo_comando_starlink_<fecha> &&
  cp -p /root/panel_solar_ble/publicar_losant.py /root/respaldo_comando_starlink_<fecha>/'
scp panel_solar_ble/publicar_losant.py root@<IP_CAMPO>:/root/panel_solar_ble/
ssh root@<IP_CAMPO> 'sync; md5sum /root/panel_solar_ble/publicar_losant.py;
  systemctl restart panel-solar-informe; sleep 10; systemctl is-active panel-solar-informe'
```
3. NO probar el "off" en campo dentro del horario salvo que se quiera dejar
   el sitio sin Starlink hasta el día siguiente. Para verificar sin cortar:
   mandar `{"accion": "on"}` y ver `Comando 'starlink' ignorado` en
   `journalctl -u panel-solar-informe`.

Revertir: `cp -p` del respaldo a `/root/panel_solar_ble/` + restart
`panel-solar-informe`.

Con el modo ventana (4e) el "off" ya no vuelve en `hora_on`: en ventana
prende en la próxima ventana (hasta 2 h), en permanente recién con el rescate
de 24 h.

## 4e. Modos de Starlink ventana / permanente (rama `modos-starlink`, 2026-10-13)

Plan y resultados: `docs/plan_modos_starlink.md`. Fases 0-5 hechas y
probadas en el lab; en campo falta medir la duración real de las ventanas
(Fase 6, punto 1) y que no haya pérdidas nuevas por las conmutaciones.

- [x] Fases 1-3a probadas en el lab 13/10 (11/11, ver plan).
- [x] Fase 3b: ensayo del paquete en el lab 13/10 (sin permanente aborta,
  falla forzada revierte, aplicación OK).
- [x] Fase 4: comando `modo` y `sl_modo` con el workflow de `test_SC` 13/10.
- [x] Fase 5: Losant solo en vivo (último resumen en `/run/losant_ultimo`).
- [x] Rescate de ventana (6 h sin ventanas => "on"). Al pasar a ventana por
  primera vez queda prendida hasta la primera ventana (hasta 2 h): normal.
- [x] Corrida larga en el lab en modo ventana (13/10 21:05 → 15/10 11:05 UTC):
  20/20 ventanas OK, sin rescate ni reinicios (ver plan, Fase 6). La subida
  real a GCS en la ventana no se probó (GCS deshabilitado en el lab).
- [ ] `subir_csv_gcs.py` con `PAUSA_VENTANA_S = 5` (15/10): en la ventana la
  pausa entre CSV baja de 30 s a 5 s (con 30 s la ventana de 24 duraba ~12 min).
  Va en el paquete de modos-starlink: rearmar el paquete con este cambio.
- [ ] **Después de aplicar:** borrar la cola vieja (ya nadie la manda),
  dejando el contador del día:
  ```bash
  ssh root@<IP_CAMPO> "cd /mnt/usb/losant_pendientes && ls | wc -l && find . -maxdepth 1 -name '[0-9]*.json' -delete && rm -rf .malos && ls -A"
  ```
  (tiene que quedar solo `.contadores.json`).
- [ ] Va **por paquete** (cambian units: entra `starlink-ventana.timer`, se
  deshabilitan `starlink-rele-on/off.timer`). Incluye 4d.
- [ ] **Antes de aplicar**, con SSH por Starlink: poner el modo permanente.
  La placa de campo todavía no tiene `modo_operacion.sh`:
  ```bash
  ssh root@<IP_CAMPO> "printf 'permanente\n' > /root/starlink_remoto/modo_operacion && sync && cat /root/starlink_remoto/modo_operacion"
  ```
  `aplicar_actualizacion.sh` aborta si no está en permanente (también lo
  muestra `SOLO_CHEQUEAR=1`).
- [ ] **Después de aplicar**, a mano (el paquete no pisa valores existentes
  del config): `gcs.dias_atras` 7 → 30 en
  `/root/scripts_campo_comun/config_campo.json`.
- [ ] En Losant, Device de campo: atributo `sl_modo` (String), tag
  `modo_starlink` = `permanente` al principio, y el workflow de dos
  Conditionals (copia del de `test_SC`, con el Device de campo).
- [ ] Verificar: `systemctl list-timers 'starlink*'` (ventana cada 2 h a los
  :05 hora local, sin `rele-on/off`), `modo_operacion.sh` = permanente.
- [ ] Pasar a ventana desde el tag de Losant cuando se decida.

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
3. Armar el paquete desde el commit a instalar. **OJO (2026-10-07):** el
   `out/red_pitaya.bin` del repo FPGA hoy es el bitstream del IN2
   (`b34cd26f`); el de campo es `~/bitstreams/campo_7f23f7d_red_pitaya.bin`
   (md5 `1e6b2cf2`). Verificar el md5 antes de armar (compila el binario en la
   placa de pruebas, en `/tmp`, sin tocar lo instalado):
   ```bash
   bash scripts_campo/actualizacion/armar_paquete_actualizacion.sh \
       --bitstream ~/bitstreams/campo_7f23f7d_red_pitaya.bin --bitstream-commit 7f23f7d \
       --compilar-en root@<IP_LAB>
   ```
   (`--commit <tag>` para armar desde un tag; en `VERSION` queda el commit.)

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

## 7. Paquete integrado `integracion-campo` en la empresa (2026-10-15)

La placa de campo vuelve a la empresa: se instala y se prueba todo junto con
la placa a mano (LAN, sin depender de Starlink). Reemplaza la instalación por
separado de 4c-bis, 4d y 4e y la etapa 9 del IN2: todo va en **un solo
paquete**.

- Rama `integracion-campo` = `main` + `registro-energia` (arreglo del float)
  + `modos-starlink` (incluye 4d) + `in2-sensor` (IN2 independiente, cambio
  mono/dual remoto) + `me_canales` real + IN2 asociado al IN1
  (`docs/plan_in2_asociado.md`: `modo_evento.in2_modo`, comando `canales` con
  `"in2"`).
- Paquete: `paquetes_actualizacion/actualizacion_20261015_190535_864a15c.tgz`
  (commit `864a15c`, bitstream del IN2 `20ac88b` = md5 `b34cd26f`, binario
  sha256 `74b88bb2…`). Si hay commits nuevos, rearmarlo desde la rama con ese
  mismo bitstream (`~/bitstreams/in2_20ac88b_red_pitaya.bin`).
- Probado en el lab (15/10): aplicación (y la reversión sola por la lectura
  del relé), dual/mono por Losant, dual con bitstream viejo, modo clásico,
  `cfg.py --poner`, `me_canales`, ventanas y GCS en ventana. **No probado:**
  energía con el paquete integrado (el lab no tiene ESP32), Starlink real,
  relé real.
- **Ensayo completo de esta sección en el lab (16/10, 14:43-14:53 UTC): OK.**
  Vuelta atrás a mano (7.6) dos veces seguidas (`5de699f_b` y `50dc5ce_b`,
  45 s cada una, sin errores) hasta dejar el lab como campo (horario viejo,
  bitstream de campo `1e6b2cf2`); desde ahí 7.1 (tag y placa en permanente),
  7.2 (`864a15c` → `ok` en 2 min, 80/80 archivos del MANIFIESTO, relé leído
  "on", bitstream `b34cd26f`) y 7.3 con los comandos literales. Fue la
  primera aplicación de `864a15c` como paquete (antes el lab tenía
  `5de699f_b` + instalaciones a mano). Salieron dos correcciones: el `;` del
  reseteo del SOC (7.3) y crear los tags de canales después de instalar
  (7.4).
- **Cambio respecto de la etapa 9 del plan del IN2** (bitstream solo con el
  software viejo en mono, después el software, después dual): ese
  escalonamiento era para cuando el único acceso era Starlink. Con la placa
  en la empresa va todo junto (**decidido 2026-10-15**): si algo falla, la
  vuelta atrás automática y el acceso local alcanzan.

### 7.1 Antes de tocar la placa

`<IP_CAMPO>` en la empresa (llegó 2026-10-20): cable directo a la PC =
**`10.42.0.180`** (perfil NetworkManager `directo-placa` en la PC, modo
compartido: `nmcli con up directo-placa`); por la LAN de la oficina =
`192.168.0.55`.

- [x] **Confirmar físicamente qué hay en el IN2 de campo y su jumper** (lo
      pide el plan del IN2 antes de pasar a dual). **2026-10-20:** IN2 sin
      nada conectado, jumper en HV (usuario).
- [x] Respaldo completo antes de instalar (**2026-10-20**, no lo pedía el
      plan): `tar` de `/root` (sin `.cache` ni core dumps) + `/etc` +
      `/opt/stream_app` en `/mnt/usb/respaldos/pre_integracion_20261020.tgz`
      (40 MB, sha256 `81a219ce…`) y copia verificada en la PC en
      `datos_campo/respaldos/`.
- [x] Inventario (solo lectura) y compararlo con el último: la placa tiene
      cambios puntuales del 8/10 (4c por `scp`, tag `campo-2026-10-08`).
      **Hecho 2026-10-20** (`inventario_rp-f0fbda_20261020.txt`): coincide
      con `campo-2026-10-08`; solo difieren el config (propio de la placa) y
      la copia en `/root` de `modo-evento.service` y `subir-csv-gcs.service`,
      que está en su versión del 1/10 (`b612993`, `eefbe1b`):
  ```bash
  ssh root@<IP_CAMPO> 'bash -s' < scripts_campo_comun/inventario_placa.sh \
      > datos_campo/inventarios/inventario_rp-f0fbda_<fecha>.txt
  ```
- [x] Losant, Device de campo — atributos nuevos (si no, Losant los
      descarta): `sl_modo` (String), `starlink_comando` (String),
      `me_canales` y `me_dec` (Number), `me_cambio` (String),
      `kurt_max_1min_in2` y `area_max_1min_in2` (Number), `me_in2_modo`
      (String). Verificar que
      estén los `en_*` (se crearon el 8/10). **Hecho 2026-10-19** (creados
      por el usuario en `SC1`).
- [x] Losant: tag `modo_starlink` = `permanente` en el Device de campo y el
      workflow de dos Conditionals (copia del de `test_SC`, con el Device de
      campo; plan de modos, Fase 0). **Hecho 2026-10-19**: workflow aparte
      para el Device de campo `SC1` (misma aplicación que `test_SC`,
      `6a85af0d0a0c5812f97c1828`), solo Conditional 1/2 + Command `modo`, sin
      los nodos de canales (van en 7.4). Probado sin la placa: Virtual Button
      -> nodo Device: State que escribe `sl_modo` en `SC1` -> trigger real,
      con Debug en vez del Command: `permanente` -> corta en Cond. 2,
      `ventana` -> pasa (mandaría `modo`), sin `sl_modo` -> corta en Cond. 1.
      Nodos de prueba borrados; deja datos `sl_modo` de prueba en el
      historial de `SC1`. Falta ver el comando llegar a la placa (7.4).
- [x] Misma aplicación => `comandos_losant/modo_starlink.py` sirve con el
      mismo token; solo cambia el ID del Device (`SC1`).
- [x] Modo permanente en la placa (`aplicar_actualizacion.sh` aborta sin él;
      la placa de campo todavía no tiene `modo_operacion.sh`). **Hecho
      2026-10-20.**
  ```bash
  ssh root@<IP_CAMPO> "printf 'permanente\n' > /root/starlink_remoto/modo_operacion && sync && cat /root/starlink_remoto/modo_operacion"
  ```

### 7.2 Instalar

**Hecho 2026-10-20 14:49-14:51 UTC** por cable directo (`10.42.0.180`):
`SOLO_CHEQUEAR` todo OK, `RESULTADO: ok` (73 reemplazados, 8 nuevos; relé
leído "on", antena no responde porque no estaba conectada), bitstream
`b34cd26f`, mono, `in2_modo` independiente, timers `starlink-ventana` sin
`rele-on/off`, 0 units failed.

7.3 el mismo día: timer GCS `enabled`/`active`, `gcs.dias_atras` = 30,
drop-in solo `umbral.conf`, cola de Losant ya vacía (solo
`.contadores.json`). SOC reseteado a 50 Ah (`ultimo_float` None,
`float_racha` 0), `panel-solar-informe` active.

Igual que la sección 6 (pasos 4-6):
```bash
bash scripts_campo/actualizacion/enviar_paquete.sh root@<IP_CAMPO> paquetes_actualizacion/actualizacion_20261015_190535_864a15c.tgz
ssh root@<IP_CAMPO> 'SOLO_CHEQUEAR=1 bash /root/actualizacion/20261015_190535_864a15c/aplicar_actualizacion.sh /root/actualizacion/20261015_190535_864a15c'
ssh root@<IP_CAMPO> 'bash /root/actualizacion/20261015_190535_864a15c/aplicar_actualizacion.sh'
ssh root@<IP_CAMPO> 'cat /root/actualizacion/RESULTADO_20261015_190535_864a15c'
```
- Si da `revertida` por "la lectura directa del relé da 'off' con Starlink
  prendido": el relé lee al revés o la Starlink no prendió (en el lab pasó
  con el cable de feedback sacado). Revisar el relé antes de reintentar; un
  ID ya usado no se vuelve a aplicar: copiar la carpeta como `<id>_b`.
- La captura arranca en **mono** (`modo_evento.canales` lo agrega la fusión
  en `1`).
- **No crear todavía los tags `canales` / `in2_modo` en el Device de campo**
  (van en 7.4, después de `RESULTADO ok`). En el ensayo del 16/10 los tags de
  `test_SC` (dual) hicieron que Losant mandara el comando `canales` al primer
  resumen, con `aplicar_actualizacion.sh` todavía verificando: terminó `ok`
  porque `cambiar_canales.sh` y el reconciliador comparten el lock del relé y
  se esperan, pero conviene no depender de eso.

### 7.3 Ajustes después de aplicar (el paquete no pisa valores del config)

- [ ] Timer de GCS habilitado y activo (en permanente es el único que sube a
      GCS; el paquete no lo toca, así que queda como estaba). Si falta, Losant
      sigue recibiendo todo y nada avisa que GCS dejó de subir (en el lab
      estaba deshabilitado, visto 2026-10-19):
  ```bash
  ssh root@<IP_CAMPO> 'systemctl is-enabled subir-csv-gcs.timer; systemctl is-active subir-csv-gcs.timer'
  ```
  Tiene que dar `enabled` y `active`. Si no: `systemctl enable --now subir-csv-gcs.timer`.
- [ ] `gcs.dias_atras` 7 → 30:
  ```bash
  ssh root@<IP_CAMPO> 'python3 /root/scripts_campo_comun/cfg.py --poner gcs.dias_atras 30 && python3 /root/scripts_campo_comun/cfg.py gcs.dias_atras'
  ```
- [ ] Resetear el SOC (el 100 % guardado el 8/10 es falso; 4c-bis, solo el
      paso 2 — el archivo ya lo trae el paquete):
  ```bash
  ssh root@<IP_CAMPO> 'systemctl stop panel-solar-informe && python3 -c "import json; f=\"/root/energia_estado.json\"; e=json.load(open(f)); e.update(soc_ah=50.0, ultimo_float=None, float_racha=0); json.dump(e, open(f, \"w\")); print(e)"; sync; systemctl start panel-solar-informe; systemctl is-active panel-solar-informe'
  ```
  El `python3` va en una sola línea a propósito: este bloque está indentado
  dentro de la lista y, copiado del archivo en crudo, las líneas sueltas
  llegaban con 2 espacios adelante (`IndentationError`, visto 16/10).
  El `start` va con `;` y no con `&&`: si el archivo falta o está roto, el
  `python3` falla pero el cartero vuelve a arrancar igual (con `&&` quedaba
  parado y la placa dejaba de reportar a Losant; visto en el ensayo del
  16/10). Si imprime un error en vez del diccionario, el SOC no se reseteó.
- [ ] Borrar la cola vieja de Losant dejando el contador (4e):
  ```bash
  ssh root@<IP_CAMPO> "cd /mnt/usb/losant_pendientes && ls | wc -l && find . -maxdepth 1 -name '[0-9]*.json' -delete && rm -rf .malos && ls -A"
  ```
- [ ] Si quedó algún drop-in `canales.conf` en `modo-evento.service.d`,
      borrarlo (le gana al config).
- [ ] Verificar: `bash -s < scripts_campo_comun/estado_placa.sh`;
      `systemctl list-timers 'starlink*'` (ventana a los :05 de horas pares
      locales, sin `rele-on/off`); en Losant `sl_modo = permanente`,
      `me_canales = 1`, `me_dec = 32`, resúmenes cada minuto.

### 7.4 Pruebas en la empresa (lo que el lab no pudo)

**2026-10-20 (sin SmartSolar ni antena en la oficina; IN2 sin nada
conectado):** el usuario armó en el workflow de `SC1` los nodos de canales
(Cond A/B/C + 2 Command) y los tags. Por tag (PATCH por API conservando los
demás tags), un solo comando por cambio y `RESULTADO: ok` en ~35 s cada uno:
mono → dual independiente (14:59) → dual asociado (15:02) → mono (15:04) →
dual independiente (15:06). En dual: `me_canales` 2, `me_dec` 64,
`kurt_max_1min_in2`/`area_max_1min_in2` en el resumen, CSV en
`/mnt/usb/eventos/in2/`. Ninguna de las dos entradas tiene nada conectado
(los sensores quedaron en el sitio): en dual las dos dan `raw_max` ~210,
solo ruido. Por pedido del usuario **queda en mono** (15:11, `ok 1`, dec32;
tags `canales` 1, `in2_modo` independiente). Falta: pares de eventos en
asociado (requiere sensor en el IN1), energía y ventana real.

- [ ] **Energía con el paquete integrado:** filas por minuto en
      `/mnt/usb/energia/`, resumen horario `en_*` en Losant a la hora
      siguiente, `en_soc_confiable = false` hasta un float sostenido.
- [ ] **Dual con el sensor del IN2:** comando `canales` `{"canales": 2}` →
      `ok 2`, `me_canales = 2`, `kurt_max_1min_in2` desde el segundo minuto,
      CSV en `/mnt/usb/eventos/in2/`. Volver a mono y a dual una vez.
- [ ] **IN2 asociado con los dos sensores:** `{"canales": 2, "in2":
      "asociado"}` → `ok 2 asociado`, `me_in2_modo = asociado`. Con señal en
      el IN1 (golpe/arena), cada `evento_*` de `/mnt/usb/eventos/` tiene su par
      con el **mismo nombre** en `in2/` (`"disparo": "IN1"` en el JSON); con
      señal **solo en el IN2**, no se graba nada. Volver a `"independiente"`
      (o dejar el modo que se decida para el sitio).
- [ ] **Ventana con Starlink real** (antena con cielo despejado): tag →
      `ventana`; mirar `/root/logs_campo/ventanas_starlink.log` (internet_s,
      duración, `gcs="subidos N/N"`), que suban `ventanas_*`, `*_in2` y
      `energia_*` a `campo/…`, y que el relé apague y confirme. Fase 6 del
      plan de modos: anotar duración y consumo. Con el cable del relé
      puesto, en `journalctl -u starlink-ventana` **no** debe aparecer
      `ADVERTENCIA: aplicar_objetivo.sh fallo al abrir la ventana` (en el lab
      sale en cada ventana porque el cable está sacado).
- [ ] **Mono/dual por tag en ventana real** (`docs/plan_canales_por_tag.md`;
      lab 7/7 con placa conectada y reconexión simulada 2026-10-16). Antes
      (y recién ahora, con la instalación ya en `ok`, ver 7.2):
      en el Device de campo crear tags `canales` / `in2_modo` y los nodos del
      workflow (Cond A/B/C + 2 Command `canales`, **Save**). Con Starlink
      apagada (entre ventanas) cambiar el tag y en la ventana siguiente ver:
      un solo comando `canales` en `journalctl -u panel-solar-informe`,
      `RESULTADO: ok …` en `/root/logs_campo/cambiar_canales.log` **antes**
      de que cierre la ventana (en el lab, 42 s desde que conecta; la ventana
      espera 120 s), `fin=normal` en `ventanas_starlink.log`, relé apagado y
      el cambio visible en Losant (`me_canales`/`me_in2_modo`) en la ventana
      siguiente. Repetir una vez para cada sentido (mono → dual, dual → mono).
- [ ] **Comandos con el relé real:** `starlink` `{"accion": "on"}` →
      ignorado; tag permanente ↔ ventana ida y vuelta.
- [ ] Si se puede, IN2 con arena tirada a mano (como en julio) para ver que
      el IN2 reacciona.

### 7.5 Primeros días en el sitio (no se prueba en la empresa)

- Balance de energía real con ventanas cada 2 h (estimado ~250 Wh/día contra
  ~400 antes, nunca medido): `en_*` diarios y tensión mínima nocturna.
- Primer float real: que calibre el SOC (umbrales 13,3 V / 10 min son una
  suposición, ajustarlos con ese dato).
- IN2 con la arena del pozo: umbral del IN2 (hoy = el del IN1, 3,40) con
  datos de campo.
- Pérdidas de muestras por las 12 conmutaciones diarias del relé.

### 7.6 Volver atrás

- Modo clásico sin desinstalar: `bash /root/scripts_campo/cambiar_modo.sh clasico`.
- Todo como estaba: `revertir_actualizacion.sh` del respaldo
  `/root/respaldos_actualizacion/20261015_190535_864a15c/` (sección 6).
- Solo el bitstream: `revertir_bitstream.sh` del repo FPGA; con el config en
  dual la captura sigue midiendo el IN1 y `me_canales` pasa a `1`.

## 8. Próximo paquete (después de `campo-2026-10-20`)

Instalado en campo: tag `campo-2026-10-20` (`864a15c`). Lo que sigue va en un
paquete nuevo armado desde `integracion-campo`:

- [ ] **CSV sin filas pegadas tras un corte de energía** (`capturar_eventos.cpp`,
      2026-10-20). Visto en campo: `ventanas_20261020_14.csv` con dos líneas
      cortadas (14:07:44 y 14:32:57) y la fila siguiente pegada (timestamp
      truncado, área en la columna de t). Al reabrir el CSV de la hora, la
      captura recorta lo posterior al último `\n` (también los NUL) y lo deja
      en el log: `CSV ...: recortados N bytes de una linea cortada`. Probado
      en el lab (`rp-f0fd8c`, dual dec64): 11 bytes recortados, 0 filas mal
      formadas en IN1 e IN2. Los lectores de la PC (`ventanas_a_paquete.py`,
      `organizar_csv_campo.py`) descartan las filas pegadas que ya están en
      GCS. Cambia el binario: rearmar el paquete (compila en la placa de
      pruebas).
- [ ] **Primer pulso del relé después de cada arranque sin efecto** (sin
      hacer). `PS_MIO10` arranca en 0 (leído 2026-10-20, bit 10 de
      `0xe000a040` a los 31 s del boot) y `pulsar_ps` asume reposo en 1: el
      primer pulso hace 0→1→0→1 y el relé no cambia. Lo corrige el
      reconciliador en 5-10 min. Arreglo candidato: fijar el bit en 1 antes de
      habilitar la salida en `mux_ps10_common.sh`.
- Sin resolver (no es de software, a confirmar): en la oficina, con fuente de
  laboratorio y nada en la salida del relé, **cada off→on del relé resetea la
  placa** (3 de 3 el 2026-10-20: 17:41, 17:44, 19:05 UTC). Revisar en el
  sitio la primera ventana (`uptime_s` en Losant) antes de dejarla en ventana.

## Después (no bloquea)

- Opción 2 del relé (lectura de los DIO en el bitstream propio, relé leído
  sin cortar la medición) + modo Master fijo: **lista para campo, ver la
  sección 0**. Circuito del feedback: pad del módulo → 1k → base NPN,
  colector a DIO2_P con 10k a 3.3V de la Pitaya.
- Piloto con sensor y arena real: **no se hace** (decidido 2026-09-28). La
  validación de la detección queda para los primeros días en campo: cruzar
  los eventos (`kurt_max_1min`, `me_eventos_hoy`, `evento_*.json`) con los
  pases de arena que informe el pozo, como con las 3 franjas del 21/9.
