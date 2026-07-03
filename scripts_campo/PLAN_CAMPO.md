# Guía operativa de campo — Sand Monitoring

## Resumen

El script recomendado es **`capturar_stream.py`**.  
Captura a ~98% de eficiencia escribiendo primero a la SD interna de la placa (15 MB/s,
suficiente para los 7.8 MB/s de datos) y luego mueve cada chunk al destino elegido en
un thread de fondo mientras ya empieza el siguiente chunk.

**Tres modos de operación:**

| Modo | Topología de red | Velocidad típica | Límite de sesión |
|---|---|---|---|
| `usb` | Sin PC | 4–5 MB/s | Storage del USB |
| `red` via gateway | Placa y PC en la misma red (router) | 6–15+ MB/s | Sin límite en SD |
| `red` via link directo | RJ45 placa ↔ PC directamente | 5.6 MB/s concurrente | ~2.9 horas (ver abajo) |

---

## Cómo funciona el script

### Por qué la SD como buffer intermedio

El streaming-server de Red Pitaya genera datos a **7.8 MB/s** (decimación 32, 2 bytes por muestra).
Un USB 2.0 típico escribe a 4–5 MB/s — más lento que la tasa de datos. Si el servidor escribiera
directo al USB, el buffer interno se llenaría y los datos se perderían o el servidor pararía antes
de tiempo. La SD interna de la placa escribe a **15 MB/s**, suficiente para no perder nada.

### Flujo por chunk

```
     PLACA                                      DESTINO
  ┌──────────────────────────────┐
  │  1. startStreaming()         │
  │     servidor escribe a SD   │  ← 15 MB/s, ~60s para 1 min de señal
  │     Python espera callback  │
  │  2. callback stoppedSDDone  │
  │     renombra archivo en SD  │
  └──────────────────────────────┘
           │
           ├─── thread de fondo ──────────────────► USB: shutil.move()  4–5 MB/s
           │                                         RED: scp            6–15 MB/s
           │
  ┌──────────────────────────────┐
  │  3. startStreaming() chunk 2 │  ← arranca inmediatamente, no espera el move
  │     ...                     │
  └──────────────────────────────┘
```

El move del chunk anterior y la captura del siguiente corren **en paralelo**. Si el move no
terminó cuando la captura nueva termina, el script espera (`[esperando move anterior...]`)
antes de iniciar el siguiente move — nunca hay más de un archivo en tránsito a la vez, y
nunca se acumulan archivos en la SD.

### Eficiencia real

La **eficiencia** que imprime el script es `tiempo_de_señal / tiempo_de_reloj`. Con SD como
destino de captura se obtiene consistentemente 97–99%. El tiempo de move al USB o red no
cuenta en esa métrica — ocurre fuera del loop de captura.

---

## Estructura de archivos

```
Sand Monitoring/
  scripts_campo/
    capturar_stream.py   ← RECOMENDADO para campo (98% eficiencia, int16 raw)
    capturar_campo.py          ← alternativa HDF5 (54% eficiencia, float32 autodescrip.)
    PLAN_CAMPO.md              ← este documento
  analisis/
    revisar.py           ← revision rapida en PC (lee .bin)
```

---

## Setup inicial en la placa (una sola vez)

Estos pasos se hacen una vez por placa. Después de un reset de firmware hay que repetirlos.

### 1. Copiar el script a la placa

La IP de la placa depende de cómo esté conectada (ver sección de IPs más abajo):

```bash
scp scripts_campo/capturar_stream.py root@<IP_PLACA>:/root/scripts_campo/
```

### 2. Librería de streaming — persistencia automática (RESUELTO)

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
ExecStart=/usr/bin/unzip -o /opt/redpitaya/streaming/rpsa_client-2.07-51-ffe70f24f-rp.zip -d /root/rpsa_client/
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable rpsa-lib.service"
```

### 3. Setup para modo RED (solo si se usa `--destino red`)

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

---

## IPs según topología de red

La placa obtiene su IP del router o de la PC según cómo esté conectada:

| Topología | IP placa | IP PC (en esa interfaz) | Notas |
|---|---|---|---|
| Placa → gateway/router → PC | 192.168.0.55 | 192.168.0.147 | Red compartida |
| Placa → RJ45 directo → PC | 10.42.0.180 | 10.42.0.1 | Linux "connection sharing" |

> Con link directo (RJ45), Linux asigna automáticamente `10.42.0.1` al lado PC y
> da `10.42.0.180` a la placa por DHCP. No hay que configurar nada extra.

---

## Captura en campo — paso a paso

### 1. Conectar por SSH

```bash
ssh root@<IP_PLACA>
# password: edge1234
```

### 2. Montar el USB (solo para modo `usb`)

```bash
lsblk
# Buscar el USB/HDD externo en la lista (por tamaño).
# Generalmente aparece como sda1 o sdb1.

mount /dev/sda1 /mnt/usb    # ajustar según lsblk
df -h /mnt/usb              # verificar espacio disponible
```

> **Antes de salir al campo:** formatear el USB limpio y verificar que tiene espacio suficiente.

### 3. Ejecutar la captura

**Modo USB** (storage externo conectado a la placa):

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --directorio /mnt/usb
```

**Modo RED via gateway** (placa y PC en la misma red con router):

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --destino red \
  --pc_host facu-edge@192.168.0.147 \
  --pc_ruta /home/facu-edge/datos_campo
```

**Modo RED via link directo** (RJ45 placa ↔ PC, sin router):

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --destino red \
  --pc_host facu-edge@10.42.0.1 \
  --pc_ruta /home/facu-edge/datos_campo
```

**Parar:** Ctrl+C. El chunk que está corriendo termina y se guarda antes de parar.

### Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| `--condicion` | obligatorio | `reposo` o `con_arena` |
| `--decimacion` | `32` | Factor de decimación → fs = 125 MHz / dec |
| `--duracion_chunk` | `1` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales. Sin esto corre hasta Ctrl+C |
| `--directorio` | `/mnt/usb` | Storage externo (siempre requerido, aunque sea modo red) |
| `--destino` | `usb` | Destino de los chunks: `usb` o `red` |
| `--pc_host` | — | `usuario@ip` de la PC (solo con `--destino red`) |
| `--pc_ruta` | — | Ruta en la PC donde guardar (solo con `--destino red`) |

### Ejemplos de uso

```bash
# Loop indefinido a USB, chunks de 1 minuto (uso típico campo sin PC)
python3 /root/scripts_campo/capturar_stream.py --condicion reposo

# 2 horas a USB con chunks de 10 minutos
python3 /root/scripts_campo/capturar_stream.py \
  --condicion con_arena --duracion_total 120 --duracion_chunk 10

# Directo a la PC por gateway, loop indefinido
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo \
  --destino red --pc_host facu-edge@192.168.0.147 --pc_ruta /home/facu-edge/datos_campo

# Directo a la PC por link directo (RJ45), 3 chunks de prueba
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --duracion_total 3 \
  --destino red --pc_host facu-edge@10.42.0.1 --pc_ruta /home/facu-edge/datos_campo

# Menor frecuencia de muestreo (archivos más chicos)
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 64 --duracion_chunk 5
```

### Sesiones largas desatendidas: relanzado automático si crashea

**Para cualquier corrida larga o desatendida, lanzar SIEMPRE con
`relanzar_captura.sh` (no el script de captura solo) — el bug conocido de
Red Pitaya sigue sin arreglo, y sin este wrapper un crash deja la sesión
muerta sin relanzar (confirmado en campo el 2026-07-02, sesión sin wrapper
se frenó a los ~17 chunks).**

Para sesiones de noche o sin supervisión, envolver el mismo comando con
`relanzar_captura.sh` — si el script crashea (el bug conocido de la librería
de Red Pitaya, ver `docs/` para el detalle), lo relanza solo en vez de dejar
la sesión muerta hasta que alguien la note. Si el script termina limpio
(Ctrl+C, `--duracion_total` alcanzado, o problema de USB detectado) **no**
relanza — esos casos son intencionales, no un crash.

```bash
bash /root/scripts_campo_comun/relanzar_captura.sh \
  /root/scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

Cada relanzamiento arranca una **sesión nueva** (`session_ts` y chunk 0001
distintos) — una noche con 2 crashes deja 3 sesiones separadas en el
directorio, cada una válida y legible por separado con `revisar.py`.
Máximo 10 reintentos con 5s de espera entre cada uno (mata el
`streaming-server` residual antes de reintentar, para forzar arranque en
frío). Si se supera el máximo, el wrapper termina con error — revisar
`/root/logs_campo/` para diagnosticar antes de relanzar a mano.

### Lo que se ve mientras corre

**Modo USB:**

```
=== CAPTURA CAMPO — SD intermedia + USB destino ===
  condicion  : reposo
  decimacion : 32  →  fs = 3.9062 MHz
  chunk      : 1.0 min  (234,375,000 muestras | 469 MB)
  destino    : /mnt/usb/stream_adc
  total      : indefinido  (Ctrl+C para detener)

--- Chunk 0001 | USB 6.18 GB libres ---
  [SD] campo_reposo_20260630_141907_0001.bin  (60.0s | 61.5s reloj | 96% efic | 469 MB)
--- Chunk 0002 | USB 6.18 GB libres ---
  [SD] campo_reposo_20260630_142009_0002.bin  (60.0s | 60.9s reloj | 99% efic | 469 MB)
  [esperando move anterior...]
  [USB] chunk 0001 → campo_reposo_20260630_141907_0001.bin  (469 MB en 97s | 4.9 MB/s)
```

**Modo RED:**

```
=== CAPTURA CAMPO — SD intermedia + RED destino ===
  condicion  : reposo
  decimacion : 32  →  fs = 3.9062 MHz
  chunk      : 1.0 min  (234,375,000 muestras | 469 MB)
  destino    : facu-edge@192.168.0.147:/home/facu-edge/datos_campo
  total      : indefinido  (Ctrl+C para detener)

--- Chunk 0001 | USB 4.30 GB libres ---
  [SD] campo_reposo_20260630_145328_0001.bin  (60.1s | 61.1s reloj | 98% efic | 469 MB)
--- Chunk 0002 | USB 4.30 GB libres ---
  [SD] campo_reposo_20260630_145429_0002.bin  (60.0s | 61.6s reloj | 97% efic | 469 MB)
  [esperando move anterior...]
  [RED] chunk 0001 → campo_reposo_20260630_145328_0001.bin  (469 MB en 69s | 6.8 MB/s)
```

> `[esperando move anterior...]` aparece cuando el USB/red no terminó de copiar el chunk
> anterior antes de que el siguiente capture completo. Es normal — la captura no se
> interrumpe, solo hay una pausa antes de empezar el move del nuevo chunk.

---

## Archivos generados

**Modo USB** — los archivos quedan en la memoria externa:

```
/mnt/usb/stream_adc/
  session_info.json                        ← parámetros de la sesión (leer primero)
  campo_reposo_20260630_134042_0001.bin    ← muestras CH1, int16 raw
  campo_reposo_20260630_135042_0002.bin
  ...
```

**Modo RED** — los archivos llegan directamente a la PC en `--pc_ruta`:

```
/home/facu-edge/datos_campo/
  session_info.json
  campo_reposo_20260630_145328_0001.bin
  campo_reposo_20260630_145429_0002.bin
  ...
```

**Formato `.bin`:** int16 little-endian, muestras secuenciales del Canal 1, sin header.  
**No abrir con un editor de texto** — son datos binarios.

---

## Logs (errores y eventos) — en la placa, no en el USB

**Dónde están:** `/root/logs_campo/` en la Red Pitaya. No están en el USB/SSD de campo a
propósito — así sobreviven si el storage externo se desconecta a mitad de sesión.

```
/root/logs_campo/
  log_campo_reposo_20260702_183536.txt        ← una por sesión (mono usa prefijo "campo", dual "dual")
  log_dual_reposo_20260702_183644.txt
  crash_campo_reposo_20260702_183536_0007.txt ← solo aparece si la sesion crasheo, uno por crash
```

**Qué tiene el `log_*.txt`:** NO es todo lo que se ve en pantalla — solo errores, warnings
(los que arrancan con `[!]`) y los eventos que el script marca a propósito (inicio y fin de
sesión, chunks con eficiencia baja). Una sesión larga sin problemas genera un archivo de
apenas un par de líneas.

**Cómo leerlo:** es texto plano, con cualquier editor o:

```bash
ssh root@<IP_PLACA> "cat /root/logs_campo/log_campo_reposo_20260702_183536.txt"
```

**Qué tiene el `crash_*.txt`:** si la sesión se cayó con una excepción, además del log
normal queda este archivo aparte con el traceback completo, el estado de
`streaming-server` (`pgrep`), las últimas líneas de `dmesg` y el espacio libre en la SD —
todo lo que antes había que ir a buscar a mano por SSH.

---

## Espacio en disco y velocidades

### Tamaño de archivos

| Decimación | fs | Chunk 1 min | Chunk 10 min |
|---|---|---|---|
| 32 | 3.906 MHz | ~469 MB | ~4.7 GB |
| 64 | 1.953 MHz | ~235 MB | ~2.4 GB |

### Capacidad de storage

| Storage | Capacidad útil | Chunks de 1 min (dec=32) |
|---|---|---|
| Pendrive 8 GB | ~7.5 GB | ~16 chunks (~16 min) |
| HDD 500 GB | ~500 GB | ~1.065 chunks (~17.7 hs) |
| HDD 1 TB | ~1 TB | ~2.130 chunks (~35.5 hs) |

### Velocidades de transferencia medidas (esta placa, dec=32, chunk=1min)

| Destino | Velocidad medida | Tiempo transfer / chunk | Espera entre chunks |
|---|---|---|---|
| SD interna (captura) | 15 MB/s | — | — |
| USB 2.0 pendrive | 4–5 MB/s | ~100s | ~40s |
| RED link directo (concurrente) | 5.6 MB/s | ~83s | ~23s |
| RED link directo (sin competencia) | 10.4 MB/s | ~45s | 0s |
| RED via gateway (100 Mbit) | 6–15 MB/s | 30–80s | 0–20s |

### Límite de sesión por acumulación en SD (modo RED link directo)

Con link directo la transferencia (83s) es más lenta que la captura (60s), por lo que
la SD acumula chunks no transferidos a un ritmo de ~130 MB por chunk capturado.

| SD libre | Límite de sesión |
|---|---|
| 22 GB | ~173 chunks ≈ **2.9 horas** |
| 16 GB | ~126 chunks ≈ **2.1 horas** |

**Para sesiones más largas:** usar modo gateway (si la red da >7.8 MB/s sostenido, no acumula)
o hacer pausas entre bloques para que la SD drene.

**Fórmula:** `limite_min = SD_libre_MB / 130 * 1`  (chunks de 1 min, dec=32)

---

## Revisar los archivos en la PC

```bash
# Revisar todo el directorio (USB o red)
.venv/bin/python3 analisis/revisar.py /ruta/al/directorio/stream_adc/

# Revisar archivos específicos
.venv/bin/python3 analisis/revisar.py campo_reposo_*.bin
```

Salida de ejemplo:

```
archivo                                     cond        chunk   dur     kurt   crest   fa%     MB   deteccion
campo_reposo_20260630_134042_0001.bin       reposo          1  1.0m      3.1     5.2   0.0%  469.0  reposo
campo_con_arena_20260630_150000_0001.bin    con_arena       1  1.0m    412.5   101.8  68.0%  469.0  *** ARENA ***
```

### Leer un archivo .bin manualmente en Python

```python
import numpy as np, json

info  = json.load(open('/ruta/al/directorio/session_info.json'))
datos = np.fromfile('campo_reposo_20260630_134042_0001.bin', dtype='<i2')
fs    = info['fs_hz']          # ej: 3906250.0
volts = datos * (20.0 / 32767) # escala aproximada ±20V
```

---

## Qué hacer si algo falla

### "No se pudo conectar al streaming-server"

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

### La eficiencia cae por debajo de 90%

Verificar que `STREAM_DIR` no sea un symlink al USB (de una sesión anterior con una versión
vieja del script). Si existe el symlink, el script lo elimina automáticamente al arrancar.
Verificar manualmente:

```bash
ls -la /home/redpitaya/streaming_files/adc
# Debe ser un directorio, no un symlink. Si es symlink: rm adc && mkdir adc
```

### "startStreaming fallo" en el chunk 2

Indica que el servidor quedó en estado inconsistente. Reiniciar el streaming-server:

```bash
pkill streaming-server
sleep 2
/opt/redpitaya/bin/streaming-server -v &
```

### Modo RED: "Permission denied" o cuelga en scp

La clave SSH de la placa no está en el `authorized_keys` de la PC. Repetir el setup de clave:

```bash
ssh-copy-id -i <(ssh root@<IP_PLACA> "cat ~/.ssh/id_rsa.pub") facu-edge@<IP_PC>
```

Verificar que el servidor SSH de la PC esté corriendo:

```bash
sudo systemctl status ssh
```

### "No module named 'streaming'"

La librería no está extraída. Verificar el servicio systemd:

```bash
ssh root@<IP_PLACA> "systemctl status rpsa-lib"
```

Si el servicio no existe (placa reflasheada), reinstalar siguiendo la sección "Setup inicial → 2".

### Espacio insuficiente en USB

El script para automáticamente cuando quedan menos de 500 MB libres e imprime un mensaje.
Montar un storage más grande o borrar capturas ya copiadas a la PC.

### El USB no aparece con lsblk

```bash
dmesg | tail -20    # ver últimos mensajes del kernel al conectar el USB
```

Probar desconectar y volver a conectar el USB. Si el sistema de archivos es exFAT:

```bash
apt-get install exfatprogs -y
mount /dev/sda1 /mnt/usb
```

---

## Referencia de hardware

| Componente | Detalle |
|---|---|
| Sensor | Vallen VS150-RI (100–450 kHz, preamp 40 dB) |
| ADC | Red Pitaya STEMlab 125-14 (125 MHz, 14 bits) |
| Jumper | HV → rango ±20 V |
| Attenuator config | `A_1_20` |
| Acceso SSH | `root@<IP_PLACA>` / pass: `edge1234` (ver sección de IPs) |
| Storage campo | USB/HDD externo en `/mnt/usb` |

---

## Script alternativo: HDF5 (capturar_campo.py)

Si necesitás archivos auto-descriptos sin depender de `session_info.json`:

```bash
PYTHONPATH=/opt/redpitaya/lib/python \
  python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

| | `capturar_stream.py` | `capturar_campo.py` |
|---|---|---|
| Eficiencia | **98%** | 54% |
| Formato | raw int16 (.bin) | float32 HDF5 (.h5) |
| Tamaño/min (dec=32) | **~469 MB** | ~940 MB |
| Metadata | `session_info.json` aparte | dentro del archivo |
| Modos destino | USB o RED (scp) | USB solo |

---

## Estado del proyecto (junio 2026)

- [x] Captura via streaming FILE mode — 97–99% eficiencia, 0 muestras perdidas
- [x] SD interna como buffer intermedio (evita cuello de botella del USB)
- [x] Modo USB — move en background mientras captura el siguiente chunk
- [x] Modo RED via gateway — scp directo a PC (6–15 MB/s)
- [x] Modo RED via link directo RJ45 — sin router, 5.6 MB/s concurrente, límite ~2.9 h
- [x] Librería `rpsa_client` con persistencia automática vía systemd (`rpsa-lib.service`)
- [x] Loop continuo con Ctrl+C limpio, chequeo de espacio, chunks numerados
- [x] Revisión rápida en PC (`revisar.py`) para .bin
- [ ] Análisis post-campo con métricas completas (kurtosis, espectro, clasificación)
