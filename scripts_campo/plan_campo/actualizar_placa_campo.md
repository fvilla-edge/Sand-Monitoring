# Pendiente para la placa de campo (`rp-f0fbda`)

Lista viva de todo lo que la placa de campo tiene que recibir cuando se la
iguale a la placa de pruebas (`rp-f0fd8c`). Cada cambio que afecte a campo se
agrega acá en el momento, no al final.

**Estado:** placa de campo con **freeze** desde el 2026-09-11 (solo se le
aplicó `dummy0` el 22/9 como excepción). Corre el modo clásico
(`capturar_stream.py` a pedido + control de Starlink + panel solar). Todo lo
de abajo está probado **solo en la placa de pruebas**, que no tiene relé,
sensor ni ESP32. No se actualiza hasta que el usuario lo decida.

Mismo ecosistema en las dos placas (v3.00 `e00665135`, build 57, Ubuntu
24.04.4): no hace falta reflashear.

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
  (confirmar el relé sin cortar la medición). **En prueba (2026-09-29), no
  instalar en campo todavía.** Van juntos: bitstream de la rama `lectura-dio`
  de `fpga_pitaya` (DIO2_P siempre entrada, pines en `0x40200078`, ID
  `0x534D0001` en `0x4020007C`) y la rama `rele-sin-cortar` de este repo
  (`mux_ps10_common.sh`, `control_starlink.sh`, `aplicar_objetivo.sh`: si el
  ID está, leen el relé ahí sin frenar el modo evento y verifican cada 5 min;
  si no, el camino de siempre con v0.94). Circuito del feedback: pad del
  módulo → 1k → base NPN, colector a DIO2_P con 10k a 3.3V de la Pitaya.
- Piloto con sensor y arena real: **no se hace** (decidido 2026-09-28). La
  validación de la detección queda para los primeros días en campo: cruzar
  los eventos (`kurt_max_1min`, `me_eventos_hoy`, `evento_*.json`) con los
  pases de arena que informe el pozo, como con las 3 franjas del 21/9.
