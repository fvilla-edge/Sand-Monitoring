# Comandos — Sand Monitoring

Referencia rápida de todos los scripts del repo. Para el procedimiento completo de
campo (setup, topologías de red, troubleshooting) ver `scripts_campo/PLAN_CAMPO.md`.

---

## Captura (corren en la Red Pitaya)

### `scripts_campo/capturar_stream.py` — recomendado

Streaming FILE mode, ~98% eficiencia, raw `.bin`. Mono (1 canal) o dual (2 canales,
sensor de referencia) con el mismo script.

```bash
python3 scripts_campo/capturar_stream.py --condicion reposo --directorio /mnt/usb
```

| Argumento | Default | Descripción |
|---|---|---|
| `--condicion` | *obligatorio* | `reposo` o `con_arena` |
| `--canales` | `1` | `1` = mono (IN1), `2` = dual (IN1+IN2) |
| `--decimacion` | `32` | Factor de decimación, por canal → fs = 125 MHz / dec. Con `--canales 2` usar `64` |
| `--duracion_chunk` | `1.0` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales de la sesión |
| `--directorio` | `/mnt/usb` | Storage externo montado |
| `--destino` | `usb` | `usb` o `red` (scp SSH a la PC) |
| `--pc_host` | — | `usuario@ip` de la PC — solo con `--destino red` |
| `--pc_ruta` | — | Ruta destino en la PC — solo con `--destino red` |
| `--verbosidad` | `completo` | `completo` (todo, con color) o `minimo` (solo warnings/errores) |
| `--pad` | `0` | Identificador de pad, se guarda en el JSON de metadata |
| `--pozo` | `0` | Identificador de pozo, se guarda en el JSON de metadata |

### `scripts_campo/probar_dual_stream.py` — prueba de banco

Captura corta de solo lectura para investigar formato/mapeo de canales con 2 canales
activos. No mueve ni borra nada del USB/red — usar antes de confiar en una captura dual.

```bash
python3 scripts_campo/probar_dual_stream.py --decimacion 32 --duracion 5
```

| Argumento | Default | Descripción |
|---|---|---|
| `--decimacion` | `32` | Factor de decimación |
| `--duracion` | `5.0` | Segundos de captura de prueba |

### `scripts_campo_comun/relanzar_captura.sh` — supervisor para sesiones largas

Relanza `capturar_stream.py` si crashea (bug conocido de la librería de Red Pitaya, no
arreglado del lado de ellos todavía). No relanza si el script termina limpio (Ctrl+C,
`--duracion_total` alcanzado, o problema de USB detectado). **Usar siempre para
sesiones de noche o sin supervisión.**

```bash
bash scripts_campo_comun/relanzar_captura.sh scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

Primer argumento: ruta del script de captura. El resto se pasa tal cual a ese script
(cualquier combinación de los argumentos de `capturar_stream.py` de arriba, incluido
`--canales 2`). Constantes internas fijas: `MAX_REINTENTOS=10`, 5s de espera entre
reintentos, mata `streaming-server` residual antes de cada reintento.

### `scripts_campo_comun/repetir_captura.sh` — varias sesiones cortas en vez de una larga

Repite una captura corta N veces (cada repetición es una sesión independiente, con su
propia carpeta con timestamp propio) en vez de una sola sesión larga con una carpeta
pesada. Pensado para envolver `relanzar_captura.sh` (así una falla intermitente dentro
de una repetición se recupera sola).

```bash
bash scripts_campo_comun/repetir_captura.sh 5 10 \
  scripts_campo_comun/relanzar_captura.sh scripts_campo/capturar_stream.py \
  --condicion reposo --pad Pad-3 --pozo "Pozo A" --directorio /mnt/usb --duracion_chunk 1
```

Primer argumento: cantidad de repeticiones. Segundo argumento: minutos por repetición —
se agrega como `--duracion_total` al final de cada llamada (obligatorio y separado a
propósito: sin él, el default de `capturar_stream.py` es sin límite y la primera
repetición no terminaría nunca). Tercer argumento en adelante: el comando completo a
repetir, tal cual (no incluir `--duracion_total` ahí, se pisa). Si una repetición agota
los reintentos del supervisor (falla dura), aborta el lote entero.

### `scripts_campo_comun/automount_usb.sh` — montaje automático de `/mnt/usb`

No se ejecuta a mano: lo invoca `mnt-usb-automount@.service` (`scripts_campo_comun/udev-automount/`)
como `ExecStart` (mount) y `ExecStop` (umount, al desconectar el dispositivo vía
`BindsTo=dev-%i.device`), disparado por una regla udev al conectar el storage externo. Monta
la primera partición `sd[a-z][0-9]` que aparece y no pisa un montaje existente. Setup e instrucciones de prueba en
`scripts_campo/plan_campo/setup_placa.md` ("3. Montaje automático del USB"). Log propio en
`/root/logs_campo/automount_usb.log`.

### `scripts_campo/repro_in1_file_bug.py` — referencia

Script mínimo de reproducción enviado a Red Pitaya para un issue ya resuelto (el formato
`.bin` tiene headers, no es raw — ver `analisis/revisar.py`). Se conserva como referencia,
no es parte del flujo operativo normal.

---

### `scripts_campo/capturar_eventos.py` — modo evento (rama `modo-evento`)

Captura continua; guarda la señal cruda solo de las ventanas con kurtosis ≥ umbral
y un CSV por hora con área/kurtosis de todas. Detalle completo, formatos y pruebas
en `docs/modo_evento.md`.

```bash
make -C /root/scripts_campo/c      # compilar el nucleo C++ en la placa (una vez)
python3 /root/scripts_campo/capturar_eventos.py --umbral 3.4 --destino /root/eventos   # a mano; en la placa lo corre modo-evento.service
```

### Mono / dual y modo del IN2 (modo evento instalado)

En la placa lo maneja `modo-evento.service`; el modo sale de `config_campo.json`
(`modo_evento.canales` y `modo_evento.in2_modo`). No editar el config a mano:
cambiarlo con el comando de Losant o con `cambiar_canales.sh`, que escriben la clave
de forma segura, reinician la captura, verifican que mida y, si no mide en 4 min,
vuelven solos al modo anterior.

| Modo | Qué mide | Losant (comando `canales`) | SSH |
|---|---|---|---|
| Mono | solo IN1, dec 32 | `{"canales": 1}` | `cambiar_canales.sh 1` |
| Dual independiente | IN1 + IN2 (dec 64); el IN2 graba su cruda por **su** kurtosis | `{"canales": 2, "in2": "independiente"}` | `cambiar_canales.sh 2 independiente` |
| Dual asociado | IN1 + IN2; el IN2 graba su cruda **solo cuando graba el IN1** (mismo tramo, mismo nombre en `in2/`) | `{"canales": 2, "in2": "asociado"}` | `cambiar_canales.sh 2 asociado` |

**En modo ventana usar los tags del Device, no el comando a mano**
(`docs/plan_canales_por_tag.md`): Losant no guarda comandos, y uno mandado con
la placa desconectada (entre ventanas) se pierde sin error. Tags `canales` (`1` |
`2`) e `in2_modo` (`independiente` | `asociado`, solo con `canales` = `2`): el
workflow los compara con `me_canales`/`me_in2_modo` y manda el comando `canales`
solo si difieren, apenas la placa conecta (en el lab, `ok` a los ~40 s de
conectar; la ventana espera 2 min). Sin tags o con un valor mal escrito no hace
nada. Cambiar el tag a mano en el Device; el comando a mano sirve con la placa
conectada (modo permanente o durante una ventana). Ojo: con los tags puestos, un
comando a mano que no coincida con ellos lo deshace el workflow al minuto
siguiente.

- `{"canales": 2}` sin `"in2"` deja el modo del IN2 como estaba. `"in2"` con
  `"canales": 1` se rechaza (el modo del IN2 queda guardado para el próximo dual).
- El dual pide el bitstream del IN2. Con el bitstream viejo: independiente mide solo
  el IN1; asociado graba la cruda del IN2 igual, sin su área/kurtosis ni su CSV.
- Tarda ~30 s. Alrededor de 1 de cada 10 arranques la captura se cae dentro de la
  librería del vendor (`startStreaming`) y systemd la relanza a los 60 s: el cambio
  tarda ~1,5 min pero termina igual.
- Detalle: `docs/plan_cambio_canales_remoto.md`, `docs/plan_in2_independiente.md`,
  `docs/plan_in2_asociado.md`.

```bash
# en la placa (se desacopla solo: un corte de SSH no lo frena)
bash /root/scripts_campo/cambiar_canales.sh 2 asociado
journalctl -u cambiar-canales -f                       # seguirlo
cat /root/logs_campo/cambio_canales_estado             # resultado (= me_cambio en Losant)
cat /run/modo-evento/medicion                          # lo que mide ahora: canales=2 dec=64 in2=asociado
```

Resultado (`cambio_canales_estado`, en Losant `me_cambio`): `ok 2 asociado`,
`ok 1 (ya estaba)`, `ok 2 (bitstream sin IN2: mide solo IN1)`,
`error: modo clasico (modo-evento deshabilitado), sin cambio`,
`error: no midio con 2 asociado (volvio a 1)`, etc. En Losant también: `me_canales`
(lo que de verdad se mide: 1 si el dual no puede medir el IN2), `me_dec`,
`me_in2_modo` (en dual) y `kurt_max_1min_in2` / `area_max_1min_in2` (desde el
segundo minuto en dual con el bitstream del IN2).

Modo evento ↔ modo clásico (vuelta atrás, captura a pedido como antes):
```bash
bash /root/scripts_campo/cambiar_modo.sh clasico   # deshabilita modo-evento, bitstream del vendor
bash /root/scripts_campo/cambiar_modo.sh evento    # vuelve al modo evento con el modo de canales del config
```

## Análisis (corren en la PC)

### `analisis/revisar.py` — revisión rápida

Lee `.bin` + `session_*_info.json`, detecta automáticamente si cada archivo es mono o
dual (no hace falta indicarlo). Calcula kurtosis, crest factor, fracción activa y
rms_diferencial sobre la señal filtrada 100–450 kHz (más métricas cruzadas CH1/CH2 si
es dual). No usa `argparse` — rutas posicionales.

```bash
.venv/bin/python3 analisis/revisar.py /ruta/al/directorio/
.venv/bin/python3 analisis/revisar.py campo_reposo_*.bin campo_con_arena_*.bin
```

| Argumento | Descripción |
|---|---|
| rutas (posicional) | Archivos `.bin` o directorios (busca `campo_*.bin` recursivamente) |

### Modo evento: `ventanas_a_paquete.py`, `reconstruir_senal.py`, `ver_paquete.py`

```bash
.venv/bin/python analisis/placa/ventanas_a_paquete.py CARPETA --unir -o dia.paquete.json   # CSV -> paquete liviano
./analisis/visores/abrir_paquete.sh                                                          # visor (horas/dias)
.venv/bin/python analisis/placa/reconstruir_senal.py CARPETA --desde 120 --duracion-s 10 --png   # señal continua (max 300s)
```

Ver `docs/modo_evento.md`.

### `analisis/tests/` — tests del parser y la lógica de detección

Cubre `_leer_canales_bin`, `_detectar_header_size`, `_fraccion_activa`, `_agregar_rms_diferencial_*`
y `_detectar_mono`/`_detectar_dual` con archivos `.bin` sintéticos — no requiere placa, sensor
ni datos de campo reales.

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest analisis/tests/ -v
```

---

## Starlink / control remoto del relé (`starlink_remoto/`)

Arquitectura, hallazgos de hardware y decisiones: `starlink_remoto/HISTORIAL_STARLINK.md`.

Instalación (una vez por placa, qué copiar y qué comandos correr):
`scripts_campo/plan_campo/setup_placa.md` → paso 5.

### Operación día a día

El rele ya no responde a "quien lo llamo" sino a una unica decision
(`decidir_objetivo.sh`, prioridad rescate por manual vencido > manual >
reloj no confiable > modo permanente/ventana — ver `HISTORIAL_STARLINK.md` y
`docs/plan_modos_starlink.md`). Todo lo de
abajo termina llamando a esa misma logica, asi que no hay forma de que dos
caminos se pisen entre si.

```bash
# ver estado sin tocar hardware ni cortar una captura activa
estado-starlink
# = ON
# (el detalle de mtime/modo manual/sincronizacion de reloj esta comentado en
#  estado_starlink.sh a pedido, para no saturar la salida en demos con
#  cliente — descomentar ahi si hace falta ese nivel de detalle)

# prender/apagar a mano — entra en modo MANUAL, no se lo pisa el modo ni el
# rescate por reloj; se autolimpia solo en cuanto el modo llegue a coincidir
# con lo forzado (en modo ventana: un "prender" dura hasta la proxima ventana,
# un "apagar" en medio de una ventana la corta y se borra al cerrarla), o
# "auto-starlink" fuerza la vuelta ya mismo.
# "apagar-starlink" que NUNCA coincide solo con el modo (ej. en modo
# permanente) se ignora despues de starlink.rescate_manual_horas (default 24h)
# sin renovarse, forzando "on" — evita quedar sin acceso remoto para siempre
# si de por medio hay un corte de luz largo (ver HISTORIAL_STARLINK.md).
prender-starlink
apagar-starlink

# volver a control automatico (modo + rescate por reloj)
auto-starlink

# ver cuando dispara cada timer
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"

# ver si corrio bien (ADVERTENCIA + exit code != 0 si el pulso no coincidio con el feedback real)
ssh root@<IP_PLACA> "journalctl -u starlink-aplicar-objetivo.service"
```

`apagar-starlink` corta la sesión SSH en el acto si depende del mismo Starlink que se
está apagando — es lo esperado.

**Desde Losant** (Device > Send Device Command): nombre `starlink`, payload
`{"accion": "off"}` — corre lo mismo que `apagar-starlink`, a los 10 s (para que antes
salga a Losant el atributo `starlink_comando` = `"off"`, String, crearlo en el Device).
No existe "on" a proposito: en campo el unico enlace es el propio Starlink, asi que
apagada ya no llega ningun comando. Vuelve sola como cualquier `apagar-starlink`:
en modo ventana prende en la proxima ventana (hasta 2 h); en modo permanente recien
con el rescate a las `rescate_manual_horas` (24 h). Cualquier otro payload se ignora (queda en
`journalctl -u panel-solar-informe`); lo que hizo el apagado:
`journalctl -u apagar-starlink-losant`.

### Modo de operación: ventana / permanente

Reemplaza al horario `hora_on`/`hora_off` (`docs/plan_modos_starlink.md`):

- **ventana** (defecto): Starlink prende cada 2 h a los :05 (horas pares, hora
  Argentina) y al arrancar la placa; espera internet hasta 15 min, sube a GCS una
  vez, espera 2 min por Losant y apaga. Log: `/root/logs_campo/ventanas_starlink.log`.
- **permanente**: prendida las 24 h, sin vencimiento.

```bash
# ver / cambiar el modo (aplicar_objetivo para que el rele cambie ya)
ssh root@<IP_PLACA> "/root/starlink_remoto/modo_operacion.sh"
ssh root@<IP_PLACA> "/root/starlink_remoto/modo_operacion.sh permanente && /root/starlink_remoto/aplicar_objetivo.sh"

# abrir una ventana ya (en modo ventana)
ssh root@<IP_PLACA> "systemctl start --no-block starlink-ventana.service"
ssh root@<IP_PLACA> "journalctl -u starlink-ventana -f"
```

**Desde Losant:** el modo deseado es el tag `modo_starlink` del Device (`ventana` |
`permanente`). La placa publica `sl_modo` (String, crearlo en el Device) al conectar,
cada `informe_intervalo_min` y al cambiarlo; un workflow (dos Conditionals, ver
`docs/plan_modos_starlink.md` Fase 0) manda el comando `modo` `{"modo": "<tag>"}` solo
si difieren. La placa lo guarda y aplica el objetivo a los 10 s
(`journalctl -u modo-starlink-losant`); otro valor se ignora (queda en
`journalctl -u panel-solar-informe`). En modo ventana, un cambio de tag llega recién
en la próxima ventana (hasta 2 h).

**Cambiar el tag desde la PC** (API REST, sin entrar a Losant), desde la raíz del repo:
```bash
python3 comandos_losant/modo_starlink.py <DEVICE_ID> --ver              # modo actual y si está conectada
python3 comandos_losant/modo_starlink.py <DEVICE_ID> permanente --seco  # qué mandaría, sin cambiar nada
python3 comandos_losant/modo_starlink.py <DEVICE_ID> permanente         # o ventana
```
Cambia solo `modo_starlink` (los demás tags del Device quedan) y verifica. La placa lo
aplica con su próximo `sl_modo` (hasta 15 min conectada; en ventana, la próxima
ventana). Token: `losant_api_token.txt` en la raíz del repo, el txt que descarga Losant
(Application Token con scope `device.get` + `device.patch`), fuera de git, nunca a la
placa. `test_SC` = `6a9713dc3a600bd2d61f13de`.

**Rescate de ventana:** si en `starlink.rescate_ventana_horas` (6 h) no se abrió
ninguna ventana (`/root/starlink_remoto/ultima_ventana`), la placa prende Starlink
y la deja prendida hasta que una ventana vuelva a abrir (aviso en
`journalctl -u starlink-reconciliador`).

Cambiar el período o el minuto exige tocar `starlink-ventana.timer` (`OnCalendar=`
es estático) además de `starlink.ventana_cada_h`/`ventana_minuto` del config.
Antes de aplicar una actualización por paquete, el modo tiene que estar en
permanente (lo exige `aplicar_actualizacion.sh`).

### Activar/desactivar la programación automática (ej. pruebas de campo)

Para dejar el rele quieto en un valor fijo durante una prueba, alcanza con
`prender-starlink`/`apagar-starlink` (modo manual, ver arriba) o con el modo
permanente — ni las ventanas ni el reconciliador de 5 min lo van a tocar mientras el flag manual
este puesto. Desactivar los timers solo hace falta si ademas queres que la
placa no reevalue nada:

```bash
# desactivar ventanas + reconciliador sin perder la instalacion
ssh root@<IP_PLACA> "systemctl disable --now starlink-ventana.timer starlink-reconciliador.timer"

# reactivarlos
ssh root@<IP_PLACA> "systemctl enable --now starlink-ventana.timer starlink-reconciliador.timer"

# confirmar (0 timers listados = todo desactivado)
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"
```

`disable` evita que el timer se reactive solo si la placa reinicia; `--now` además lo
corta ya. Los alias `prender-starlink`/`apagar-starlink` no dependen de que ningun
timer esté activo.

---

## Panel solar por BLE (`panel_solar_ble/`)

Qué es, por qué hace falta un ESP32-C3 como puente y el detalle de
instalación (ojo con `bleak` — ver el README): `panel_solar_ble/README.md`.

Instalación (una vez por placa, qué copiar y qué comandos correr):
`scripts_campo/plan_campo/setup_placa.md` → paso 6.

Corre como servicio systemd (`panel-solar-informe.service`): publica un informe por MQTT
a Losant cuando detecta conexión real, y además cada `panel_solar.informe_intervalo_min`
mientras siga conectado — pensado para la ventana en la que el relé de
`starlink_remoto/` da paso a Starlink.

```bash
# ver si esta corriendo / reiniciar / logs en vivo
ssh root@<IP_PLACA> "systemctl status panel-solar-informe.service"
ssh root@<IP_PLACA> "systemctl restart panel-solar-informe.service"
ssh root@<IP_PLACA> "journalctl -u panel-solar-informe.service -f"

# lectura por pantalla, para probar el puente ESP32->Pitaya a mano (no toca Losant)
ssh root@<IP_PLACA> "cd /root/panel_solar_ble && .venv/bin/python3 -u leer_smartsolar_serial.py"
```

`-u` es necesario para ver la salida en vivo por SSH (si no, Python bufferea todo y no
se ve nada hasta que el proceso corta). Ctrl+C para cortar.

### Cambiar el intervalo del informe periódico

Vive en `scripts_campo_comun/config_campo.json` → `panel_solar.informe_intervalo_min`
(minutos). Después de cambiarlo, reiniciar el servicio para que tome el valor nuevo:

```bash
ssh root@<IP_PLACA> "systemctl restart panel-solar-informe.service"
```

No correr `publicar_losant.py` a mano mientras el servicio systemd esté activo — los dos
abrirían `/dev/ttyACM0` a la vez y competirían por publicar el mismo informe. Pararlo
primero (`systemctl stop panel-solar-informe.service`) si hace falta correrlo a mano para
debuggear (no correr junto con el publicador de la notebook tampoco, mismo Device de
Losant).

---

## Referencias

- Guía operativa completa (setup, topologías de red, troubleshooting): `scripts_campo/PLAN_CAMPO.md`
- Interpretación de métricas con valores reales medidos: `analisis/INTERPRETACION_RESULTADOS.md`
- Historial y arquitectura del relé de Starlink: `starlink_remoto/HISTORIAL_STARLINK.md`
- Panel solar por BLE (ESP32-C3 como puente): `panel_solar_ble/README.md`
- Plan de proyecto vigente: `docs/roadmap_deteccion_arena.md`
