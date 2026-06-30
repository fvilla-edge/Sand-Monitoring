# Plan de captura en campo — Sand Monitoring

## Contexto

Pasamos de laboratorio controlado a captura en campo real.  
El objetivo es juntar la mayor cantidad posible de señal cruda para analizarla después en la PC.  
Todo el procesamiento (métricas, filtros, clasificación) queda para después — la placa solo captura y guarda.

---

## Hardware en campo

| Componente | Detalle |
|---|---|
| Sensor | Vallen VS150-RI (100–450 kHz, preamp 40 dB) |
| ADC | Red Pitaya STEMlab 125-14 (125 MHz clock, 14 bits) |
| Jumper | HV → rango ±20 V |
| Storage | USB/HDD externo dedicado, conectado directo a la placa |
| Acceso | SSH desde notebook (IP: 10.42.0.180, user: root, pass: edge1234) |

---

## Parámetros de adquisición en campo

| Parámetro | Valor default | Notas |
|---|---|---|
| Decimación | 32 | → fs = 3.906 MHz. Configurable por parámetro al ejecutar |
| Duración por chunk | 1 min | Configurable en **minutos** |
| Duración total | sin límite | Configurable en **minutos**. Si no se pone, corre hasta Ctrl+C |
| Condición | reposo / con_arena | Se define al ejecutar |
| Formato | HDF5, solo raw_signal | Sin métricas. Sin compresión (ver nota de eficiencia) |
| Storage | /mnt/usb | Ver sección "Montar el USB" abajo |

### Cuánto ocupa cada chunk según configuración

HDF5 sin compresión (modo actual, alta eficiencia):

| Decimación | fs efectiva | Chunk 1 min | Chunk 10 min |
|---|---|---|---|
| 32 | 3.906 MHz | ~940 MB (float32) | ~9.4 GB |
| 64 | 1.953 MHz | ~470 MB | ~4.7 GB |

> Con `--compresion` (gzip-1): archivos ~4x más chicos, pero eficiencia cae de 54% a ~20%.

### Cuánto entra en el storage (dec=32, chunks de 1 min, sin compresión)

| Storage | Capacidad útil | Cantidad de chunks | Tiempo total aprox. |
|---|---|---|---|
| Pendrive 8 GB (prueba) | ~7.5 GB | ~8 chunks | ~8 min |
| HDD externo 500 GB | ~500 GB | ~530 chunks | ~8.8 horas |
| HDD externo 1 TB | ~1 TB | ~1.060 chunks | ~17.7 horas |

---

## Condiciones de captura

| Condición | Cuándo usarla |
|---|---|
| `reposo` | El operador confirma que no hay producción de arena |
| `con_arena` | El operador confirma que hay producción de arena |

> En campo no sabemos la cantidad de arena.  
> No hay gramos ni clasificación baja/media/alta — eso se analiza después en PC.

---

## Scripts

```
Sand Monitoring/
  scripts_rp/                  → LAB (no tocar)
    capturar.py                → captura + métricas + fraccion_activa, HDF5
  scripts_campo/               → CAMPO (rama activa)
    capturar_campo.py          → HDF5 float32, 54% eficiencia, sin compresion
    capturar_campo_stream.py   → int16 raw, 98% eficiencia (RECOMENDADO)
  analisis/                    → análisis local en PC
```

### Cuál usar

| Script | Eficiencia | Formato | Tamaño/min | Notas |
|---|---|---|---|---|
| `capturar_campo.py` | 54% | HDF5 float32 | ~940 MB | Archivos auto-descriptos, listos para Python |
| `capturar_campo_stream.py` | **98%** | raw int16 | **~469 MB** | Requiere `session_info.json` para interpretar |

**Para campo usar `capturar_campo_stream.py`** — captura el doble de señal en el mismo tiempo y ocupa la mitad del storage.

> Necesita: streaming-server corriendo (el script lo inicia automáticamente) y bitstream stream_app.

---

## Pasos para ejecutar en campo

### 1. Conectarse a la placa por SSH

```bash
ssh root@10.42.0.180
# password: edge1234
```

### 2. Montar el USB

El nombre del dispositivo puede variar entre `sda1` y `sdb1`.  
Primero verificar cuál es:

```bash
lsblk
```

Buscar el pendrive/HDD externo en la lista (por tamaño). Luego montar:

```bash
mount /dev/sda1 /mnt/usb    # o sdb1 según lo que muestre lsblk
```

> **Importante:** el storage que se use en campo debe estar **dedicado y formateado limpio** antes de salir.  
> No mezclar con archivos personales — el FAT32 se puede corromper al escribir archivos grandes en un disco con otros datos.

### 3. Ejecutar la captura

```bash
# Recomendado: streaming FILE mode (98% eficiencia)
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --directorio /mnt/usb
```

Los archivos se guardan en `/mnt/usb/stream_adc/`. El script crea `session_info.json` con los parámetros de la sesión (fs, gain, formato).

**Parar con Ctrl+C** — el chunk actual se completa y guarda antes de parar.

```bash
# Alternativa: HDF5 float32 (54% eficiencia, archivos auto-descriptos)
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

---

## Ejemplos de uso

```bash
# Corre indefinidamente, chunks de 1 minuto (recomendado)
python3 /root/scripts_campo/capturar_campo_stream.py --condicion reposo

# 2 horas, chunks de 10 minutos
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion con_arena --duracion_total 120 --duracion_chunk 10

# Menor frecuencia de muestreo (archivos más chicos, misma eficiencia)
python3 /root/scripts_campo/capturar_campo_stream.py \
  --condicion reposo --decimacion 64 --duracion_chunk 5
```

---

## Qué se ve mientras corre

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
  ...
```

---

## Estructura de archivos generados

### Modo stream (recomendado)

```
/mnt/usb/stream_adc/
  session_info.json                        ← parámetros de la sesión
  campo_reposo_20260630_134042_0001.bin    ← muestras int16 raw
  campo_reposo_20260630_135042_0002.bin
  ...
```

Formato `.bin`: int16 little-endian, muestras secuenciales del Canal 1, sin header.  
Para leer en PC:
```python
import numpy as np, json

info  = json.load(open('session_info.json'))
datos = np.fromfile('campo_reposo_20260630_134042_0001.bin', dtype='<i2')
fs    = info['fs_hz']          # 3906250.0
volts = datos * (20.0 / 32767) # escala aproximada ±20V
```

### Modo HDF5 (alternativo)

Nombre: `campo_{condicion}_{fecha}_{numero}.h5`  
Contenido: dataset `raw_signal` (float32) + atributos de metadata.

---

## Diagnóstico de eficiencia y mejoras aplicadas

### El problema original (21% de eficiencia)

El script original tardaba ~5 minutos de reloj por cada 1 minuto de señal capturada.

**Causa:** dos bugs independientes que se sumaban:

1. **`time.sleep(0.005)` innecesario** en `_capturar_buffer()` entre `rp_AcqStart()` y el trigger.  
   Agregaba 5ms artificiales a cada buffer (vs ~7ms necesarios). Alcanzaba con eliminarlo.

2. **Compresión gzip-1 bloqueaba la captura.** El script usaba `compression='gzip', compression_opts=1`  
   en el dataset HDF5. Benchmark en la RP:

   | Modo | ms por chunk de 256 buffers | Eficiencia (sin hilo) |
   |---|---|---|
   | gzip-1 (original) | 7.400 ms | 12% |
   | gzip-0 | 510 ms | 45% |
   | sin compresión | **351 ms** | **48%** |

   La escritura sincrónica bloqueaba la captura 3-7 segundos cada ~2 segundos de señal.

### La solución aplicada (54% de eficiencia)

Tres cambios en `capturar_campo.py`:

1. **Eliminar el sleep** — la función `_capturar_buffer()` quedó sin `time.sleep(0.005)`.

2. **Sin compresión por defecto** — `create_dataset(...)` sin kwargs de compresión.  
   El flag `--compresion` la reactiva para cuando el storage es el cuello de botella.

3. **Thread writer con doble buffer** — la escritura HDF5 corre en un hilo separado mientras  
   el hilo principal sigue capturando. Pool de 3 numpy arrays pre-asignados (sin allocaciones  
   en el loop caliente). La escritura (351ms) es mucho más rápida que la captura (1.9s por bloque),  
   así que el hilo escritor nunca bloquea al capturador.

**Resultado:** 54% de eficiencia estable. 1 minuto de señal tarda ~1 minuto 52 segundos.

> El API de streaming oficial de Red Pitaya fue evaluada pero NO aplica para captura local:
> fue diseñada para enviar datos a una PC remota. Correr cliente y servidor en la misma RP ARM
> da 29% de eficiencia con 80M muestras perdidas (el ARM se satura procesando ambos).

---

## Roadmap

### Paso 1 — chunk único ✅ LISTO
Verificación de que la placa captura y guarda en el USB correctamente.

### Paso 2 — loop continuo ✅ LISTO
Loop con streaming, Ctrl+C limpio, chequeo de espacio, chunks numerados, duración en minutos.

### Paso 3 — revision rapida en PC ✅ LISTO

Script `analisis/revisar_campo.py` — calcula kurtosis, crest factor y fraccion_activa sobre la senal filtrada (100–450 kHz) y muestra una tabla compacta con deteccion automatica.

```bash
# Revisar todo el USB de una
.venv/bin/python3 analisis/revisar_campo.py /mnt/usb/

# Despues de copiar a la PC
.venv/bin/python3 analisis/revisar_campo.py capturas/semana_campo/*.h5
```

Ejemplo de salida:

```
archivo                                     cond        chunk   dur     kurt   crest   fa%     MB   deteccion
campo_reposo_20260626_143000_0001.h5        reposo          1  1.0m      4.1     5.3   0.0%  216.0  reposo
campo_con_arena_20260626_150000_0001.h5     con_arena       1  1.0m    412.5   101.8  68.0%  216.0  *** ARENA ***

  2 archivos | 2.0 min total | 1 con arena | 1 en reposo

  Referencia: kurtosis reposo ~3 | arena >20  |  fa% reposo 0% | arena >25%
```

Tarda unos segundos por archivo (aplica filtro y computa metricas sobre toda la senal cruda).

### Paso 4 — captura via streaming FILE mode ✅ LISTO
`capturar_campo_stream.py`: el FPGA hace DMA directo al storage via streaming-server.
**98% eficiencia, 0 muestras perdidas, int16 raw, mitad del storage que HDF5 float32.**

> Para leer los `.bin` en análisis: `np.fromfile('archivo.bin', dtype='<i2')`
