# Operación de campo — captura paso a paso

Requiere el setup de `setup_placa.md` ya hecho una vez en esta placa.

## Sensor de referencia (dual, `--canales 2`)

Un segundo sensor VS150-RI actúa como **referencia de ruido de línea**, aprovechando que
el STEMlab 125-14 tiene dos ADC que sampean sincrónicamente por hardware. Comparando la
señal del sensor de medición (CH1/IN1) contra la del sensor de referencia (CH2/IN2), se
puede separar el evento de arena del ruido mecánico/de línea que afecta a ambos por igual.

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
ciclo de clock — no hay offset temporal entre CH1 y CH2. El canal de cada sensor es fijo
por construcción del formato de archivo (IN1 = primer bloque, IN2 = segundo), no depende
de cableado ni decimación.

**Consideraciones de posicionamiento:**
- **Posición sensor referencia:** aguas arriba preferido — el flujo pasa primero por la
  referencia y luego por el codo, evitando que arena que ya pasó vuelva a afectar CH2.
- **Distancia mínima:** suficiente para que las ondas de impacto del codo no lleguen al
  sensor de referencia (regla de dedo: >0.5 m en tubería metálica).
- **Cables:** misma longitud de cable BNC posible para ambos sensores — reduce diferencia
  de ganancia.

---

## 1. Conectar por SSH

```bash
ssh root@<IP_PLACA>
```

IP según topología: ver `../PLAN_CAMPO.md` → "IPs según topología de red".

## 2. Verificar que el USB está montado (solo para modo `usb`)

Con el automontaje instalado (ver `setup_placa.md` → 3) no hace falta montar a mano —
alcanza con verificar que ya está listo:

```bash
df -h /mnt/usb
```

**Si no aparece montado** (automontaje no instalado en esta placa, o falló — ver su log
en `/root/logs_campo/automount_usb.log`), montar a mano como antes:

```bash
lsblk
# Buscar el USB/HDD externo en la lista (por tamaño).
# El nombre de dispositivo puede cambiar entre reconexiones (sda1, sdb1, ...) — siempre
# verificar con lsblk antes de montar, no asumir el mismo nombre de la vez anterior.

mount /dev/sda1 /mnt/usb    # ajustar según lsblk
df -h /mnt/usb              # verificar espacio disponible
```

> **Antes de salir al campo:** formatear el USB limpio y verificar que tiene espacio suficiente.
> Usar un hub USB alimentado si el storage pide más corriente de la que sostiene el puerto de
> la placa (ver `lsusb -v` → `bMaxPower`; 500 mA es el máximo del estándar y una señal de alerta).

## 3. Ejecutar la captura

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
  --pc_host facu-edge@<IP_PC> \
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

**Parar:** matar el proceso (`Ctrl+C` no corta una sesión con streaming activo, ver
`troubleshooting.md` → "Ctrl+C no corta la sesión"). El chunk en curso se pierde si se mata
a mitad — para un corte limpio, esperar a que termine el chunk actual antes de matar el
proceso, o usar `--duracion_total` para que la sesión termine sola.

### Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| `--condicion` | obligatorio | `reposo` o `con_arena` |
| `--canales` | `1` | `1` = mono (IN1), `2` = dual (IN1+IN2, ver "Sensor de referencia" arriba) |
| `--decimacion` | `32` | Factor de decimación, por canal → fs = 125 MHz / dec. Con `--canales 2`, usar `64` (ver "Decimación segura con 2 canales" abajo) |
| `--duracion_chunk` | `1` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales. Sin esto corre hasta matar el proceso |
| `--directorio` | `/mnt/usb` | Storage externo (siempre requerido, aunque sea modo red) |
| `--destino` | `usb` | Destino de los chunks: `usb` o `red` |
| `--pc_host` | — | `usuario@ip` de la PC (solo con `--destino red`) |
| `--pc_ruta` | — | Ruta en la PC donde guardar (solo con `--destino red`) |
| `--verbosidad` | `completo` | `completo` (todo, con color) o `minimo` (solo warnings/errores) |

### Decimación segura con 2 canales

Con los dos canales activos el ancho de banda se duplica y la SD interna (15 MB/s) empieza
a ser el límite. `--decimacion 64` es la única configuración de dual validada sin pérdida
sostenida — `capturar_stream.py` avisa en consola (sin bloquear) si se usa `--canales 2`
con otra decimación.

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
  --destino red --pc_host facu-edge@<IP_PC> --pc_ruta /home/facu-edge/datos_campo

# Menor frecuencia de muestreo (archivos más chicos)
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 64 --duracion_chunk 5
```

### Sesiones largas desatendidas: relanzado automático si crashea

**Para cualquier corrida larga o desatendida, lanzar SIEMPRE con
`relanzar_captura.sh` (no el script de captura solo) — sin este wrapper un
crash deja la sesión muerta sin relanzar.**

Si el script termina limpio (`--duracion_total` alcanzado, o problema de USB detectado)
el wrapper **no** relanza — esos casos son intencionales, no un crash.

```bash
# Mono
bash /root/relanzar_captura.sh \
  /root/scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb

# Dual
bash /root/relanzar_captura.sh \
  /root/scripts_campo/capturar_stream.py \
  --condicion reposo --canales 2 --decimacion 64 --duracion_chunk 1 --directorio /mnt/usb
```

Cada relanzamiento arranca una **sesión nueva** (`session_ts` y chunk 0001
distintos) — una noche con 2 crashes deja 3 sesiones separadas en el
directorio, cada una válida y legible por separado con `revisar.py`.
Máximo 10 reintentos con 5s de espera entre cada uno (mata el
`streaming-server` residual antes de reintentar, para forzar arranque en
frío) — configurable en `config_campo.json` → `reintentos.max`/`espera_s`
(ver `formato_y_funcionamiento.md`). Si se supera el máximo, el wrapper
termina con error — revisar `/root/logs_campo/` para diagnosticar antes de
relanzar a mano.

### Lo que se ve mientras corre

**Modo USB, mono:**

```
=== CAPTURA CAMPO (1 canal) — SD intermedia + USB destino ===
  condicion  : reposo
  decimacion : 32  →  fs = 3.9062 MHz
  chunk      : 1.0 min  (234,375,000 muestras | 469 MB)
  destino    : /mnt/usb/stream_adc
  total      : indefinido

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
  total      : indefinido

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
  total      : indefinido

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
  campo_reposo_20260630_134042_0001.bin     ← datos de la sesión
  campo_reposo_20260630_135042_0002.bin
  ...
```

**Modo RED** — los archivos llegan directamente a la PC en `--pc_ruta`.

**Formato `.bin`:** NO es raw plano — es un tren de segmentos `[header][datos IN1][datos
IN2 si es dual][marcador de fin]`, repetido. Cada canal es un bloque contiguo dentro del
segmento (IN1 siempre primero, IN2 segundo) — no está intercalado por muestra. **No leer
con `np.fromfile` directo ni abrir con un editor de texto** — usar
`analisis/revisar.py` o, para un consumidor propio, reusar
`analisis/revisar.py::_leer_canales_bin`. Detalle del formato: ver
`formato_y_funcionamiento.md`.

**JSON de sesión:** mismo nombre y ubicación para mono y dual — el campo `"canales": 1`
o `"canales": 2` adentro indica cuál es.

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

Con capturas dual en el lote, `revisar.py` agrega además métricas por canal (k1/k2, cf1/cf2,
fa1%/fa2%, rms_ratio) para separar arena localizada de ruido común a ambos sensores.
