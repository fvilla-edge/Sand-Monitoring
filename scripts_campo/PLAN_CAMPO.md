# Guía operativa de campo — Sand Monitoring

## Resumen

El script recomendado es **`capturar_campo_stream.py`**.  
Lo corre el operador con un solo comando en la placa. Captura al 98% de eficiencia y guarda
archivos `.bin` directamente en el USB sin pasar los datos por Python.

---

## Estructura de archivos

```
Sand Monitoring/
  scripts_campo/
    capturar_campo_stream.py   ← RECOMENDADO para campo (98% eficiencia, int16 raw)
    capturar_campo.py          ← alternativa HDF5 (54% eficiencia, float32 autodescrip.)
    PLAN_CAMPO.md              ← este documento
  analisis/
    revisar_campo.py           ← revision rapida en PC (lee .bin y .h5)
```

---

## Setup inicial en la placa (una sola vez)

Estos pasos se hacen una vez por placa. Después de un reset de firmware hay que repetirlos.

### 1. Copiar el script a la placa

```bash
scp scripts_campo/capturar_campo_stream.py root@10.42.0.180:/root/scripts_campo/
```

### 2. Instalar la librería de streaming en la placa

La librería `rpsa_client` debe estar en `/root/rpsa_client/python_lib/` (directorio permanente).
Si está en `/tmp/rpsa_client/` se pierde con cada reinicio.

```bash
# Verificar si ya está instalada
ssh root@10.42.0.180 "ls /root/rpsa_client/python_lib/streaming.py 2>/dev/null && echo OK || echo FALTA"
```

Si dice FALTA, copiar desde la PC donde se descargó la librería:

```bash
scp -r ruta/a/rpsa_client/python_lib root@10.42.0.180:/root/rpsa_client/
```

> La librería viene en el paquete `rpsa_client` del repositorio oficial de Red Pitaya.
> Una vez copiada queda permanente aunque se reinicie la placa.

### 3. Actualizar la ruta en el script (si se movió a /root)

El script tiene esta línea al inicio:

```python
sys.path.insert(0, '/tmp/rpsa_client/python_lib')
```

Si la librería está en `/root/rpsa_client/python_lib/`, cambiarla:

```bash
ssh root@10.42.0.180 \
  "sed -i 's|/tmp/rpsa_client/python_lib|/root/rpsa_client/python_lib|g' /root/scripts_campo/capturar_campo_stream.py"
```

### 4. Configurar el modo FILE en la placa

El servidor de streaming necesita tener `adc_pass_mode = FILE` antes de arrancar.
Editar el archivo de configuración en la placa:

```bash
ssh root@10.42.0.180 "cat /root/.config/redpitaya/apps/streaming/streaming_config.json"
```

Verificar que dice `"adc_pass_mode" : "FILE"`. Si dice `"NET"`, corregirlo:

```bash
ssh root@10.42.0.180 \
  "sed -i 's/\"adc_pass_mode\" : \"NET\"/\"adc_pass_mode\" : \"FILE\"/' \
   /root/.config/redpitaya/apps/streaming/streaming_config.json"
```

Verificar también que tenga el attenuator correcto para el jumper HV:

```bash
ssh root@10.42.0.180 \
  "grep -E 'adc_pass_mode|attenuator_1' /root/.config/redpitaya/apps/streaming/streaming_config.json"
# Debe mostrar:
#   "adc_pass_mode" : "FILE"
#   "channel_attenuator_1" : "A_1_20"
```

---

## Captura en campo — paso a paso

### 1. Conectar por SSH

```bash
ssh root@10.42.0.180
# password: edge1234
```

### 2. Montar el USB

```bash
lsblk
# Buscar el USB/HDD externo en la lista (por tamaño).
# Generalmente aparece como sda1 o sdb1.

mount /dev/sda1 /mnt/usb    # ajustar según lsblk
df -h /mnt/usb              # verificar espacio disponible
```

> **Antes de salir al campo:** formatear el USB limpio y verificar que tiene espacio suficiente.

### 3. Ejecutar la captura

```bash
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --directorio /mnt/usb
```

**Parar:** Ctrl+C. El chunk que está corriendo termina y se guarda antes de parar.

### Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| `--condicion` | obligatorio | `reposo` o `con_arena` |
| `--decimacion` | `32` | Factor de decimación → fs = 125 MHz / dec |
| `--duracion_chunk` | `1` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales. Sin esto corre hasta Ctrl+C |
| `--directorio` | `/mnt/usb` | Dónde guardar |

### Ejemplos de uso

```bash
# Loop indefinido, chunks de 1 minuto (uso típico)
python3 /root/scripts_campo/capturar_campo_stream.py --condicion reposo

# 2 horas con chunks de 10 minutos
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion con_arena --duracion_total 120 --duracion_chunk 10

# Menor frecuencia de muestreo (archivos más chicos, misma eficiencia)
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion reposo --decimacion 64 --duracion_chunk 5
```

### Lo que se ve mientras corre

```
=== CAPTURA CAMPO — STREAMING FILE MODE ===
  condicion  : reposo
  decimacion : 32  →  fs = 3.9062 MHz
  chunk      : 1.0 min  (234,375,000 muestras)
  directorio : /mnt/usb/stream_adc
  total      : indefinido  (Ctrl+C para detener)

--- Chunk 0001 | 7.50 GB libres ---
  [OK] campo_reposo_20260630_134042_0001.bin  (60.0s señal | 60.6s reloj | 99% eficiencia | 469 MB)

--- Chunk 0002 | 7.03 GB libres ---
  [OK] campo_reposo_20260630_135042_0002.bin  (60.0s señal | 60.6s reloj | 99% eficiencia | 469 MB)
```

---

## Archivos generados

```
/mnt/usb/stream_adc/
  session_info.json                        ← parámetros de la sesión (leer primero)
  campo_reposo_20260630_134042_0001.bin    ← muestras CH1, int16 raw
  campo_reposo_20260630_135042_0002.bin
  ...
```

**Formato `.bin`:** int16 little-endian, muestras secuenciales del Canal 1, sin header.  
**No abrir con un editor de texto** — son datos binarios.

---

## Espacio en disco

| Decimación | fs | Chunk 1 min | Chunk 10 min |
|---|---|---|---|
| 32 | 3.906 MHz | ~469 MB | ~4.7 GB |
| 64 | 1.953 MHz | ~235 MB | ~2.4 GB |

| Storage | Capacidad útil | Chunks de 1 min (dec=32) |
|---|---|---|
| Pendrive 8 GB | ~7.5 GB | ~16 chunks (~16 min) |
| HDD 500 GB | ~500 GB | ~1.065 chunks (~17.7 hs) |
| HDD 1 TB | ~1 TB | ~2.130 chunks (~35.5 hs) |

---

## Revisar los archivos en la PC

Copiar el USB completo (incluyendo `session_info.json`) a la PC y correr:

```bash
# Revisar todo el directorio
.venv/bin/python3 analisis/revisar_campo.py /ruta/al/usb/stream_adc/

# Revisar archivos específicos
.venv/bin/python3 analisis/revisar_campo.py campo_reposo_*.bin

# También funciona con archivos .h5 (capturar_campo.py)
.venv/bin/python3 analisis/revisar_campo.py capturas/*.h5
```

Salida de ejemplo:

```
archivo                                     cond        chunk   dur     kurt   crest   fa%     MB   deteccion
campo_reposo_20260630_134042_0001.bin       reposo          1  1.0m      3.1     5.2   0.0%  469.0  reposo
campo_con_arena_20260630_150000_0001.bin    con_arena       1  1.0m    412.5   101.8  68.0%  469.0  *** ARENA ***

  2 archivos | 2.0 min total | 1 con arena | 1 en reposo
```

### Leer un archivo .bin manualmente en Python

```python
import numpy as np, json

info  = json.load(open('/ruta/al/usb/stream_adc/session_info.json'))
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

Verificar que el `adc_pass_mode` en el JSON de configuración sea `"FILE"` (ver Setup inicial paso 4).
Si dice `"NET"`, corregirlo y reiniciar el streaming-server.

### Espacio insuficiente

El script para automáticamente cuando quedan menos de 500 MB libres e imprime un mensaje.
Montar un storage más grande o borrar capturas ya copiadas a la PC.

### El USB no aparece con lsblk

```bash
dmesg | tail -20    # ver últimos mensajes del kernel al conectar el USB
```

Probar desconectar y volver a conectar el USB. Si el sistema de archivos es exFAT y no monta:

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
| Acceso SSH | `root@10.42.0.180` / pass: `edge1234` |
| Storage campo | USB/HDD externo en `/mnt/usb` |

---

## Script alternativo: HDF5 (capturar_campo.py)

Si necesitás archivos auto-descriptos sin depender de `session_info.json`:

```bash
PYTHONPATH=/opt/redpitaya/lib/python \
  python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

| | `capturar_campo_stream.py` | `capturar_campo.py` |
|---|---|---|
| Eficiencia | **98%** | 54% |
| Formato | raw int16 (.bin) | float32 HDF5 (.h5) |
| Tamaño/min (dec=32) | **~469 MB** | ~940 MB |
| Metadata | `session_info.json` aparte | dentro del archivo |
| Dependencia | rpsa_client + streaming-server | librp solo |

---

## Estado del proyecto (junio 2026)

- [x] Captura via streaming FILE mode — 98% eficiencia, 0 muestras perdidas
- [x] Loop continuo con Ctrl+C limpio, chequeo de espacio, chunks numerados
- [x] Revisión rápida en PC (`revisar_campo.py`) para .bin y .h5
- [ ] Análisis post-campo con métricas completas (kurtosis, espectro, clasificación)
