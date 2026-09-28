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
- [ ] Destino `/mnt/usb/eventos` (nunca la SD). En campo va el **disco de
      1TB**: probar formato, montaje y velocidad antes (pendiente, no hay
      disco todavía).

## 3. Control de Starlink (`starlink_remoto/`)

- [ ] `aplicar_objetivo.sh` y `control_starlink.sh` (`3ccd602`). **Sin esto el
      modo evento se corta cada 5 min** (reconciliador) y en cada hora_on/off.
      Con esto: se corta ~30s al conmutar y cada 2h con Starlink prendido
      (verificación real del relé).
- [ ] Probar en campo con el relé real: conmutación on/off con modo evento
      corriendo, y que la verificación cada 2h confirme el estado. En la placa
      de pruebas no hay relé: solo se probó el parar/reanudar.

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
- [ ] Decidir `apt-daily` / `apt-daily-upgrade` / `motd-news` (causan pérdidas
      de muestras de la señal cruda; pendiente).
- [ ] Temperatura: el chip da ~71°C en el laboratorio (grado comercial, tope
      ~85°C). Revisar disipación/ventilación de la caja.
- [ ] Jumper de IN1 en **HV** (campo ya está en HV; confirmar).

## 6. Procedimiento de actualización (a diseñar antes de tocarla)

- Hacerlo dentro de la ventana de Starlink (hora_on) y con tiempo para volver.
- Todo lo que corta la conexión a mitad de camino tiene que dejar la placa
  como estaba o en un estado conocido (`nohup`/`systemd-run`, checksums).
- Plan de vuelta atrás: `cambiar_modo.sh clasico` + `revertir_bitstream.sh`;
  guardar copia de los archivos que se reemplazan (`*.bak_<fecha>`).
- Verificación final: modo evento midiendo (`ESTADO`), puntos en Losant del
  Device de campo, relé confirmado.

## Después (no bloquea)

- Opción 2 del relé: registro de lectura de los DIO en el bitstream propio
  (confirmar el relé sin cortar la medición). Antes ver el esquema del
  circuito del feedback. Después del piloto.
- Piloto con sensor y arena real sobre el modo evento.
