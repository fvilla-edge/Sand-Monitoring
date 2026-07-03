# Guía operativa de campo — Sand Monitoring

## Resumen

El script recomendado es **`capturar_stream.py`**, con `--canales 1` (mono, default)
o `--canales 2` (dual — sensor de referencia además del sensor de medición, ver
"Sensor de referencia (dual)" más abajo).

Captura a ~98% de eficiencia escribiendo primero a la SD interna de la placa (15 MB/s,
suficiente para los 7.8 MB/s de datos a 1 canal) y luego mueve cada chunk al destino elegido en
un thread de fondo mientras ya empieza el siguiente chunk.

**Tres modos de operación (mono y dual):**

| Modo | Topología de red | Velocidad típica | Límite de sesión |
|---|---|---|---|
| `usb` | Sin PC | 4–5 MB/s | Storage del USB |
| `red` via gateway | Placa y PC en la misma red (router) | 6–15+ MB/s | Sin límite en SD |
| `red` via link directo | RJ45 placa ↔ PC directamente | 5.6 MB/s concurrente | ~2.9 horas (ver abajo, 1 canal) |

---

## Sensor de referencia (dual, `--canales 2`)

Un segundo sensor VS150-RI actúa como **referencia de ruido de línea**, aprovechando que
el STEMlab 125-14 tiene dos ADC que sampean sincrónicamente por hardware. Restando la
contribución del sensor de referencia (CH2) a la señal del sensor de medición (CH1), se
puede aislar el evento de arena del ruido mecánico/de línea que afecta a ambos por igual.

```
[Línea de producción]

       IN1 (CH1)              IN2 (CH2)
       Sensor codo       Sensor referencia
           |                   |
      [Evento arena]     [Ruido de fondo/línea]
           |                   |
           +---[Red Pitaya]----+
               Adquisición
               simultánea
```

| Elemento | Detalle |
|---|---|
| Sensor medición | VS150-RI → **IN1 (CH1)** — montado en el codo |
| Sensor referencia | VS150-RI → **IN2 (CH2)** — aguas arriba o abajo del codo |

**Sincronía:** garantizada por el FPGA del RP. Ambos canales se sampean en el mismo
ciclo de clock — no hay offset temporal entre CH1 y CH2.

**Consideraciones de posicionamiento:**
- **Posición sensor referencia:** aguas arriba preferido — el flujo pasa primero por la
  referencia y luego por el codo, evitando que arena que ya pasó vuelva a afectar CH2.
- **Distancia mínima:** suficiente para que las ondas de impacto del codo no lleguen al
  sensor de referencia (regla de dedo: >0.5 m en tubería metálica).
- **Cables:** misma longitud de cable BNC posible para ambos sensores — reduce diferencia
  de ganancia.

**Pendiente — bloqueante antes de usar dual en campo real:** el mapeo de canales y la
ausencia de artefactos de entrada flotante (ver "Historial de desarrollo dual" al final
de este documento) se confirmaron con las entradas al aire o golpeando el cable, no con
los sensores VS150-RI reales puestos. Repetir esa confirmación antes de confiar en datos
dual de campo.

---

## Cómo funciona el script

### Por qué la SD como buffer intermedio

El streaming-server de Red Pitaya genera datos a **7.8 MB/s por canal** (decimación 32,
2 bytes por muestra) — con `--canales 2` el ancho de banda combinado se duplica.
Un USB 2.0 típico escribe a 4–5 MB/s — más lento que la tasa de datos. Si el servidor escribiera
directo al USB, el buffer interno se llenaría y los datos se perderían o el servidor pararía antes
de tiempo. La SD interna de la placa escribe a **15 MB/s**, suficiente para 1 canal a
cualquier decimación válida, y para 2 canales a partir de dec=64 (ver más abajo).

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
destino de captura se obtiene consistentemente 97–99%, en mono y en dual. El tiempo de move
al USB o red no cuenta en esa métrica — ocurre fuera del loop de captura.

---

## Estructura de archivos

```
Sand Monitoring/
  scripts_campo/
    capturar_stream.py      ← RECOMENDADO para campo (98% eficiencia, int16 raw, --canales 1|2)
    capturar_campo.py       ← alternativa HDF5 (54% eficiencia, float32 autodescrip., solo mono)
    probar_dual_stream.py   ← prueba de banco de solo lectura, para reconfirmar mapeo de canales
    PLAN_CAMPO.md           ← este documento
  scripts_campo_comun/
    campo_common.py         ← funciones compartidas (arranque servidor, logs, USB/red)
    relanzar_captura.sh     ← supervisor para sesiones largas desatendidas
  analisis/
    revisar.py              ← revision rapida en PC (lee .bin, mono o dual)
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

**Modo USB, mono** (storage externo conectado a la placa):

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --directorio /mnt/usb
```

**Modo USB, dual** (sensor de referencia conectado a IN2):

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --canales 2 \
  --decimacion 64 \
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
| `--canales` | `1` | `1` = mono (IN1), `2` = dual (IN1+IN2, ver "Sensor de referencia" arriba) |
| `--decimacion` | `32` | Factor de decimación, por canal → fs = 125 MHz / dec. Con `--canales 2`, usar `64` (ver "Decimación segura con 2 canales" abajo) |
| `--duracion_chunk` | `1` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales. Sin esto corre hasta Ctrl+C |
| `--directorio` | `/mnt/usb` | Storage externo (siempre requerido, aunque sea modo red) |
| `--destino` | `usb` | Destino de los chunks: `usb` o `red` |
| `--pc_host` | — | `usuario@ip` de la PC (solo con `--destino red`) |
| `--pc_ruta` | — | Ruta en la PC donde guardar (solo con `--destino red`) |

### Decimación segura con 2 canales

Con los dos canales activos el ancho de banda se duplica. Medido en esta placa:

| Decimación (dual) | Ancho de banda combinado | Pérdida de muestras (test 60s) |
|---|---|---|
| 32 | ~15.6 MB/s | ~0.42% por canal (982.068 de 233M) — supera lo que la SD sostiene (15 MB/s) |
| 64 | ~7.8 MB/s | 0% — mismo margen que mono a dec=32 |

`capturar_stream.py` avisa en consola (sin bloquear) si se usa `--canales 2` con una
decimación que no sea 64.

### Ejemplos de uso

```bash
# Loop indefinido a USB, chunks de 1 minuto (uso típico campo sin PC, mono)
python3 /root/scripts_campo/capturar_stream.py --condicion reposo

# 2 horas a USB con chunks de 10 minutos
python3 /root/scripts_campo/capturar_stream.py \
  --condicion con_arena --duracion_total 120 --duracion_chunk 10

# Dual, 2 horas a USB, chunks de 10 minutos, decimacion segura
python3 /root/scripts_campo/capturar_stream.py \
  --condicion con_arena --canales 2 --decimacion 64 \
  --duracion_total 120 --duracion_chunk 10

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
# Mono
bash /root/scripts_campo_comun/relanzar_captura.sh \
  /root/scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb

# Dual
bash /root/scripts_campo_comun/relanzar_captura.sh \
  /root/scripts_campo/capturar_stream.py \
  --condicion reposo --canales 2 --decimacion 64 --duracion_chunk 1 --directorio /mnt/usb
```

Cada relanzamiento arranca una **sesión nueva** (`session_ts` y chunk 0001
distintos) — una noche con 2 crashes deja 3 sesiones separadas en el
directorio, cada una válida y legible por separado con `revisar.py`.
Máximo 10 reintentos con 5s de espera entre cada uno (mata el
`streaming-server` residual antes de reintentar, para forzar arranque en
frío). Si se supera el máximo, el wrapper termina con error — revisar
`/root/logs_campo/` para diagnosticar antes de relanzar a mano.

### Lo que se ve mientras corre

**Modo USB, mono:**

```
=== CAPTURA CAMPO (1 canal) — SD intermedia + USB destino ===
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

**Modo USB, dual:**

```
=== CAPTURA CAMPO (2 canales) — SD intermedia + USB destino ===
  condicion  : reposo
  decimacion : 64  →  fs = 1.9531 MHz por canal (3.9062 MHz combinado)
  chunk      : 1.0 min  (117,187,500 muestras/canal | 469 MB)
  destino    : /mnt/usb/stream_adc
  total      : indefinido  (Ctrl+C para detener)

--- Chunk 0001 | USB 6.18 GB libres ---
  [SD] campo_reposo_20260703_090000_0001.bin  (60.0s | 61.2s reloj | 98% efic | 469 MB)
```

**Modo RED:**

```
=== CAPTURA CAMPO (1 canal) — SD intermedia + RED destino ===
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
  session_reposo_20260630_134042_info.json  ← parámetros de la sesión (leer primero)
  campo_reposo_20260630_134042_0001.bin     ← muestras (mono: CH1 | dual: CH1+CH2 intercalado)
  campo_reposo_20260630_135042_0002.bin
  ...
```

**Modo RED** — los archivos llegan directamente a la PC en `--pc_ruta`.

**Formato `.bin`:** int16 little-endian, sin header.
- Mono: muestras secuenciales del Canal 1.
- Dual: muestras intercaladas por paridad (`datos[1::2]` = CH1 codo, `datos[0::2]` = CH2
  referencia — mapeo confirmado por golpe de cable, pendiente re-confirmar con sensor
  real puesto, ver "Historial de desarrollo dual" al final).

**No abrir con un editor de texto** — son datos binarios.

**JSON de sesión:** mismo nombre y ubicación para mono y dual — el campo `"canales": 1`
o `"canales": 2` adentro indica cuál es. Con `"canales": 2` además incluye un bloque
`mapeo_canales` con la posición de cada canal y la advertencia de reconfirmarlo.

---

## Logs (errores y eventos) — en la placa, no en el USB

**Dónde están:** `/root/logs_campo/` en la Red Pitaya. No están en el USB/SSD de campo a
propósito — así sobreviven si el storage externo se desconecta a mitad de sesión.

```
/root/logs_campo/
  log_campo_reposo_20260702_183536.txt        ← una por sesión, mono o dual (mismo prefijo "campo")
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

| Decimación | fs (1 canal) | Chunk 1 min (1 canal) | Chunk 1 min (2 canales) |
|---|---|---|---|
| 32 | 3.906 MHz | ~469 MB | ~938 MB (no recomendado, pierde muestras) |
| 64 | 1.953 MHz | ~235 MB | ~469 MB (recomendado para dual) |

Con dec=64 dual, el combinado de los 2 canales pesa lo mismo que 1 canal a dec=32 en mono.

### Capacidad de storage (1 canal, dec=32 — para dual a dec=64 son los mismos numeros)

| Storage | Capacidad útil | Chunks de 1 min |
|---|---|---|
| Pendrive 8 GB | ~7.5 GB | ~16 chunks (~16 min) |
| HDD 500 GB | ~500 GB | ~1.065 chunks (~17.7 hs) |
| HDD 1 TB | ~1 TB | ~2.130 chunks (~35.5 hs) |

### Velocidades de transferencia medidas (esta placa, dec=32 1 canal, chunk=1min)

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

**Fórmula:** `limite_min = SD_libre_MB / 130 * 1`  (chunks de 1 min, dec=32, 1 canal)

---

## Revisar los archivos en la PC

`revisar.py` detecta automáticamente si cada archivo es mono o dual leyendo el JSON de
sesión — no hace falta indicarlo. Si el lote tiene de los dos tipos, se muestran en tablas
separadas.

```bash
# Revisar todo el directorio (USB o red) — mono y/o dual
.venv/bin/python3 analisis/revisar.py /ruta/al/directorio/stream_adc/

# Revisar archivos específicos
.venv/bin/python3 analisis/revisar.py campo_reposo_*.bin
```

Salida de ejemplo (mono):

```
archivo                                     cond        chunk   dur     kurt   crest   fa%     MB   deteccion
campo_reposo_20260630_134042_0001.bin       reposo          1  1.0m      3.1     5.2   0.0%  469.0  reposo
campo_con_arena_20260630_150000_0001.bin    con_arena       1  1.0m    412.5   101.8  68.0%  469.0  *** ARENA ***
```

Con capturas dual en el lote, `revisar.py` agrega ademas metricas cruzadas por canal:
kurtosis por canal (k1/k2), su diferencia (dk = k1-k2), fraccion_activa por canal
(fa1%/fa2%) y rms_ratio (CH1/CH2) — usadas para separar arena localizada de ruido comun
a ambos sensores.

### Leer un archivo .bin manualmente en Python

```python
import numpy as np, json

info  = json.load(open('/ruta/al/directorio/session_reposo_20260630_134042_info.json'))
canales = info.get('canales', 1)
raw = np.fromfile('campo_reposo_20260630_134042_0001.bin', dtype='<i2')

if canales == 1:
    volts = raw * (20.0 / 32767)   # escala aproximada ±20V
else:
    ch1 = raw[1::2] * (20.0 / 32767)   # codo
    ch2 = raw[0::2] * (20.0 / 32767)   # referencia
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

El script para automáticamente cuando quedan menos de 500 MB × `--canales` libres e
imprime un mensaje (1 GB con `--canales 2`). Montar un storage más grande o borrar
capturas ya copiadas a la PC.

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
| Sensor (medición, IN1) | Vallen VS150-RI (100–450 kHz, preamp 40 dB) |
| Sensor (referencia, IN2 — solo dual) | Vallen VS150-RI, mismo modelo |
| ADC | Red Pitaya STEMlab 125-14 (125 MHz, 14 bits, 2 canales sincrónicos) |
| Jumper | HV → rango ±20 V |
| Attenuator config | `A_1_20` (ambos canales en dual) |
| Acceso SSH | `root@<IP_PLACA>` / pass: `edge1234` (ver sección de IPs) |
| Storage campo | USB/HDD externo en `/mnt/usb` |

---

## Script alternativo: HDF5 (capturar_campo.py)

Si necesitás archivos auto-descriptos sin depender de `session_info.json`. Solo soporta
mono (1 canal).

```bash
PYTHONPATH=/opt/redpitaya/lib/python \
  python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

| | `capturar_stream.py` | `capturar_campo.py` |
|---|---|---|
| Eficiencia | **98%** | 54% |
| Formato | raw int16 (.bin) | float32 HDF5 (.h5) |
| Canales | 1 o 2 | solo 1 |
| Tamaño/min (dec=32, 1 canal) | **~469 MB** | ~940 MB |
| Metadata | `session_*_info.json` aparte | dentro del archivo |
| Modos destino | USB o RED (scp) | USB solo |

---

## Historial de desarrollo dual (hallazgos empíricos, no operativo día a día)

Migración de la captura dual desde la librería `rp` vieja (HDF5, ~54% eficiencia,
`test_dual_adc.py`/`capturar_dual.py`, descartados) al esquema de streaming FILE mode,
y su unificación con el script mono. Placa conectada por link directo (10.42.0.180)
durante las pruebas, salvo que se indique otra cosa.

**Verificación del doble ADC (2026-07-01):** confirmado con `probar_dual_stream.py`
(captura corta de solo lectura, no mueve ni borra nada del USB/red, sirve para
investigar el formato de salida antes de confiar en él).

**Hallazgos:**

1. **Un solo archivo intercalado**, no dos archivos separados por canal. Confirmado con
   un archivo de prueba: el tamaño coincide con "2 canales intercalados" (78.16 MB vs
   78.125 MB esperados a dec=32, 5s), y la separación por paridad (`datos[0::2]` /
   `datos[1::2]`) da estadisticas estables (std constante) en todo el archivo. La
   documentación oficial de Red Pitaya no especifica esto ("Streaming always creates
   three files" por sesión, no por canal) — se resolvió empíricamente.

2. **Mapeo de canales confirmado por golpe físico** (cable IN1 sin sensor conectado,
   ambas entradas al aire, 2026-07-01 15:06 UTC-3): posiciones **impares**
   (`datos[1::2]`) = CH1 (codo), posiciones **pares** (`datos[0::2]`) = CH2
   (referencia). El std de CH1 subió de 42.7 (baseline) a picos de 300-410 en los
   momentos irregulares del golpe; CH2 se mantuvo plano. **Re-confirmar este mapeo con
   el sensor VS150-RI puesto** — la prueba se hizo golpeando el cable, no un transductor
   real (ver bloqueante en "Sensor de referencia" al principio de este documento).

3. **Entradas flotantes generan artefacto periódico** — con ambas entradas al aire, CH2
   mostró un valor idéntico repetido exactamente cada ~65.631 muestras (~30 Hz), sin
   relación con eventos reales (un evento físico no repite el mismo valor bit a bit). Es
   ruido de entrada sin terminar, mismo fenómeno que el "reposo contaminado" de la
   prueba de campo del 30/06. No es un bug — hay que tenerlo presente al interpretar
   capturas de banco sin sensor conectado.

4. **dec=32 con los 2 canales activos pierde muestras de verdad** — ver tabla en
   "Decimación segura con 2 canales" más arriba.

5. **Unificación con mono (2026-07-03):** `capturar_dual_stream.py` y
   `capturar_campo_stream.py` compartían ~80% del código fuera de `campo_common.py` —
   se unificaron en `capturar_stream.py --canales 1|2`. Mismo criterio para
   `revisar_campo.py`/`revisar_dual.py` (~55% duplicado) → `revisar.py` único, que
   detecta canales por el JSON. Los `.bin`/JSON de salida pasaron a usar siempre el
   prefijo `campo_`/`session_..._info.json` (antes dual usaba `dual_`/`session_dual_`) —
   el campo `"canales"` adentro del JSON es lo que distingue, no el nombre de archivo.
   Un archivo de prueba de banco viejo con el prefijo `dual_` (10s, entradas al aire,
   01/07) quedó sin poder re-analizarse con `revisar.py` nuevo — aceptado porque no era
   dato real:

   > Probado en su momento con esa captura de 10s (entradas al aire): separó los
   > canales bien y el resultado fue coherente — k2 (CH2, flotante) dio kurtosis 9266 y
   > fa2%=100% por el artefacto periódico ya documentado (falso positivo esperado, no
   > arena); k1 se mantuvo en baseline (~3) porque no hubo golpe durante esa captura.

**Prueba mecánica del script dual (2026-07-01):** 3 chunks de ~20s a dec=64, modo USB,
94-97% eficiencia, sin errores, JSON y move a USB correctos. Con las entradas al aire,
no es dato válido — solo valida que el script funciona.

---

## Estado del proyecto (julio 2026)

- [x] Captura via streaming FILE mode — 97–99% eficiencia, 0 muestras perdidas (mono y dual a dec=64)
- [x] SD interna como buffer intermedio (evita cuello de botella del USB)
- [x] Modo USB — move en background mientras captura el siguiente chunk
- [x] Modo RED via gateway — scp directo a PC (6–15 MB/s)
- [x] Modo RED via link directo RJ45 — sin router, 5.6 MB/s concurrente, límite ~2.9 h (1 canal)
- [x] Librería `rpsa_client` con persistencia automática vía systemd (`rpsa-lib.service`)
- [x] Loop continuo con Ctrl+C limpio, chequeo de espacio, chunks numerados
- [x] Captura dual (`--canales 2`) unificada con mono en un solo script (2026-07-03)
- [x] Revisión rápida en PC (`revisar.py`, mono y dual unificados) para .bin
- [ ] Reconfirmar mapeo de canales y ausencia de artefactos con sensores VS150-RI reales puestos en dual — **bloqueante para campo real con dual**
- [ ] Análisis post-campo con métricas completas (kurtosis, espectro, clasificación)
