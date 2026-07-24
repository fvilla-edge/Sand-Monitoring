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

### Instalación (una vez por placa)

```bash
cd starlink_remoto

# scripts + configuracion de mux compartida + boot + horario
scp control_starlink.sh mux_ps10_common.sh asegurar_mux_ps10.sh aplicar_horario.sh \
    root@<IP_PLACA>:/root/starlink_remoto/

# unidades systemd
scp systemd/starlink-mux-ps10.service systemd/starlink-rele@.service \
    systemd/starlink-rele-on.timer systemd/starlink-rele-off.timer \
    root@<IP_PLACA>:/etc/systemd/system/

ssh root@<IP_PLACA> "
  chmod +x /root/starlink_remoto/control_starlink.sh /root/starlink_remoto/asegurar_mux_ps10.sh /root/starlink_remoto/aplicar_horario.sh
  systemctl daemon-reload
  systemctl enable --now starlink-mux-ps10.service
  systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer
"

# alias para prender/apagar a mano por SSH (opcional, comodidad)
scp aliases.sh root@<IP_PLACA>:/root/starlink_remoto/
ssh root@<IP_PLACA> "grep -q 'prender-starlink' /root/.bashrc || cat /root/starlink_remoto/aliases.sh >> /root/.bashrc"
```

### Operación día a día

```bash
# ver cuando dispara cada timer
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"

# prender/apagar a mano, sin esperar el horario (logueado por SSH en la placa)
prender-starlink   # = systemctl start starlink-rele@on.service
apagar-starlink    # = systemctl start starlink-rele@off.service

# ver si corrio bien (ADVERTENCIA si el pulso no coincidio con el feedback real)
ssh root@<IP_PLACA> "journalctl -u starlink-rele@on.service"

# estado real del rele, leido por hardware — idempotente, no pulsa si ya esta en ese estado
ssh root@<IP_PLACA> "/root/starlink_remoto/control_starlink.sh on"   # o "off"
```

`apagar-starlink` corta la sesión SSH en el acto si depende del mismo Starlink que se
está apagando — es lo esperado.

### Cambiar el horario (`hora_on`/`hora_off`)

El horario NO se edita en los `.timer` directamente — vive en
`scripts_campo_comun/config_campo.json` → `starlink.hora_on`/`starlink.hora_off`
(formato `HH:MM`, hora Argentina). Después de cambiarlos, aplicar con:

```bash
ssh root@<IP_PLACA> "/root/starlink_remoto/aplicar_horario.sh"
```

Reescribe el `OnCalendar=` de los dos `.timer` y hace `systemctl daemon-reload` — no
hace falta reiniciar ni tocar nada más.

### Activar/desactivar la programación automática (ej. pruebas de campo)

```bash
# desactivar los dos horarios sin perder la instalacion
ssh root@<IP_PLACA> "systemctl disable --now starlink-rele-on.timer starlink-rele-off.timer"

# reactivarlos
ssh root@<IP_PLACA> "systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer"

# confirmar (0 timers listados = desactivados)
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"
```

`disable` evita que el timer se reactive solo si la placa reinicia; `--now` además lo
corta ya. Los alias `prender-starlink`/`apagar-starlink` no dependen de que el timer
esté activo.

---

## Referencias

- Guía operativa completa (setup, topologías de red, troubleshooting): `scripts_campo/PLAN_CAMPO.md`
- Interpretación de métricas con valores reales medidos: `analisis/INTERPRETACION_RESULTADOS.md`
- Historial y arquitectura del relé de Starlink: `starlink_remoto/HISTORIAL_STARLINK.md`
- Plan de proyecto vigente: `docs/roadmap_deteccion_arena.md`
