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
| Storage | USB/HDD externo conectado directo a la placa |
| Acceso | SSH desde notebook (IP: 10.42.0.180, user: root, pass: edge1234) |

---

## Parámetros de adquisición en campo

| Parámetro | Valor default | Notas |
|---|---|---|
| Decimación | 32 | → fs = 3.906 MHz. Configurable por parámetro al ejecutar |
| Duración por chunk | 10 s | Configurable. Ver tabla abajo |
| Condición | reposo / con_arena | Se define al ejecutar o cambia entre sesiones |
| Formato | HDF5, solo raw_signal | Sin métricas. Compresión gzip liviana |
| Storage | /mnt/usb | Montar con: `mount /dev/sda1 /mnt/usb` |

### Cuánto ocupa cada chunk según configuración

| Decimación | fs efectiva | Tamaño 10s (aprox. comprimido) |
|---|---|---|
| 32 | 3.906 MHz | ~28 MB |
| 64 | 1.953 MHz | ~14 MB |

### Cuánto entra en el storage

| Storage | Cap. útil | Chunks de 10s (dec=32) | Tiempo total aprox. |
|---|---|---|---|
| Pendrive 8 GB (prueba) | 7.5 GB | ~270 chunks | ~45 min |
| HDD externo 500 GB | ~500 GB | ~17.000 chunks | ~50 horas |

---

## Condiciones de captura

| Condición | Cuándo usarla |
|---|---|
| `reposo` | El operador del pozo confirma que no hay producción de arena |
| `con_arena` | El operador confirma que hay producción de arena |

> En campo no sabemos la cantidad de arena (no hay gramos ni clasificación baja/media/alta).  
> Eso se analiza después en PC.

---

## Scripts

```
Sand Monitoring/
  scripts_rp/           → LAB (no tocar)
    capturar.py         → captura + métricas + fraccion_activa, HDF5
  scripts_campo/        → CAMPO (rama activa)
    capturar_campo.py   → captura raw, guarda en USB (paso a paso)
  analisis/             → análisis local en PC
```

### Cómo ejecutar en campo

```bash
# 1. Montar el USB (solo la primera vez o si se desconectó)
mount /dev/sda1 /mnt/usb

# 2. Ejecutar la script
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/scripts_campo/capturar_campo.py \
  --condicion reposo \
  --decimacion 32 \
  --duracion 10 \
  --directorio /mnt/usb
```

---

## Roadmap — pasos de la script de campo

### Paso 1 — chunk único ✅ LISTO
Captura un solo chunk de N segundos, guarda en USB, termina.  
Sirve para verificar que todo funciona antes de ir al loop.

### Paso 2 — loop continuo (pendiente)
La script captura chunks indefinidamente hasta que el operador presiona Ctrl+C.  
Cada chunk es un archivo separado, numerado secuencialmente.  
Mientras corre, muestra cuánto espacio queda en el USB.

### Paso 3 — por definir
Probablemente: script de lectura rápida en PC para revisar los archivos del USB.

---

## Estructura de archivos generados

Nombre: `campo_{condicion}_{fecha}_{numero}.h5`  
Ejemplo: `campo_reposo_20260626_142850_0001.h5`

Contenido del HDF5:
- `raw_signal` → array float32 con toda la señal cruda
- Atributos: condicion, sensor, decimacion, fs_ef_hz, n_muestras, duracion_s, fecha, gain
