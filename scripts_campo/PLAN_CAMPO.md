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
| Formato | HDF5, solo raw_signal | Sin métricas. Compresión gzip liviana |
| Storage | /mnt/usb | Ver sección "Montar el USB" abajo |

### Cuánto ocupa cada chunk según configuración

| Decimación | fs efectiva | Chunk 1 min | Chunk 10 min |
|---|---|---|---|
| 32 | 3.906 MHz | ~216 MB | ~2.1 GB |
| 64 | 1.953 MHz | ~108 MB | ~1.1 GB |

### Cuánto entra en el storage (dec=32, chunks de 1 min)

| Storage | Capacidad útil | Cantidad de chunks | Tiempo total aprox. |
|---|---|---|---|
| Pendrive 8 GB (prueba) | ~7.5 GB | ~34 chunks | ~34 min |
| HDD externo 500 GB | ~500 GB | ~2.300 chunks | ~38 horas |
| HDD externo 1 TB | ~1 TB | ~4.600 chunks | ~77 horas |

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
  scripts_rp/           → LAB (no tocar)
    capturar.py         → captura + métricas + fraccion_activa, HDF5
  scripts_campo/        → CAMPO (rama activa)
    capturar_campo.py   → loop continuo, raw, streaming al USB
  analisis/             → análisis local en PC
```

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
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion_chunk 1 \
  --directorio /mnt/usb
```

**Parar con Ctrl+C** — el chunk que estaba capturando se guarda completo hasta donde llegó, luego muestra el resumen de la sesión.

---

## Ejemplos de uso

```bash
# Corre indefinidamente, chunks de 1 minuto (default)
python3 /root/scripts_campo/capturar_campo.py --condicion reposo

# 2 horas de captura, chunks de 10 minutos
python3 /root/scripts_campo/capturar_campo.py \
  --condicion con_arena \
  --duracion_total 120 \
  --duracion_chunk 10

# Misma frecuencia pero decimacion 64 (1.95 MHz, archivos más chicos)
python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo \
  --decimacion 64 \
  --duracion_chunk 5
```

> Siempre anteponer: `PYTHONPATH=/opt/redpitaya/lib/python`

---

## Qué se ve mientras corre

```
=== CAPTURA CAMPO — LOOP CONTINUO ===
  condicion      : reposo
  decimacion     : 32  ->  fs = 3.9062 MHz
  duracion chunk : 1.0 min  (14306 buffers)
  duracion total : indefinida  (Ctrl+C para detener)
  directorio     : /mnt/usb

--- Chunk 0001 | 7.50 GB libres ---
  chunk 0001 | 1.1 s capturados
  chunk 0001 | 2.1 s capturados
  ...
  [OK] campo_reposo_20260626_143000_0001.h5  (60.00 s | 234M muestras | 216.0 MB)

--- Chunk 0002 | 7.28 GB libres ---
  ...
```

---

## Estructura de archivos generados

Nombre: `campo_{condicion}_{fecha}_{numero}.h5`  
Ejemplo: `campo_reposo_20260626_143000_0001.h5`

Contenido del HDF5:
- `raw_signal` → array float32 con toda la señal cruda
- Atributos: condicion, sensor, decimacion, fs_ef_hz, n_muestras, duracion_s, chunk_num, fecha, gain

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
