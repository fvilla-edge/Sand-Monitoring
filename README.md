# Sand Monitoring — Deteccion acustica de arena en tuberias

Sistema experimental para detectar y clasificar niveles de produccion de arena
usando un sensor piezoacustico **Vallen VS150-RI** y una placa **Red Pitaya STEMlab 125-14**.

## Hardware

| Componente | Detalle |
|---|---|
| Sensor | Vallen VS150-RI — banda 100-450 kHz, preamp 40 dB integrado |
| ADC | Red Pitaya STEMlab 125-14 — 125 MS/s, 14 bits |
| Modo ADC | High Voltage (jumper HV) — rango ±20 V |
| Red Pitaya | IP: x.x.x.x — usuario: `root` |

## Estructura del repositorio

```
Sand Monitoring/
├── scripts_rp/               # Scripts que corren en la Red Pitaya
│   ├── capturar.py           # Adquisicion + metricas, guarda HDF5
│   └── leer_h5.py            # Lector rapido de metadatos y metricas
├── analisis/
│   ├── analisis_semana1.py   # Analisis local: espectrogramas, FFT, boxplots
│   └── outputs/              # Imagenes generadas (gitignoreado)
├── capturas/                 # Archivos HDF5 locales (gitignoreado)
├── .venv/                    # Entorno virtual Python (gitignoreado)
├── informe_deteccion_arena.md
├── roadmap_deteccion_arena.md
└── README.md
```

## Setup inicial (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install h5py scipy matplotlib numpy
```

## Flujo de trabajo

### 1. Copiar script actualizado a la Red Pitaya

```bash
scp scripts_rp/capturar.py root@192.168.0.55:/root/
```

### 2. Conectarse a la placa

```bash
ssh root@192.168.0.55
# password: edge1234
```

### 3. Capturar en la Red Pitaya

```bash
# Sin arena (linea de base)
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/capturar.py --condicion reposo

# Arena en vacio (sin flujo)
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/capturar.py --condicion alta

# Con flujo y arena (cuando haya banco de pruebas)
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/capturar.py \
    --condicion baja --masa_g 2.0 --caudal_Ls 0.5 --tamanio_mm 0.4
```

**Condiciones disponibles:** `reposo` | `flujo_limpio` | `baja` | `media` | `alta`

El script avisa con cuenta regresiva y muestra `>>> TIRA LA ARENA AHORA <<<`
antes de iniciar la adquisicion. Cada captura dura ~2.5 s.

El archivo HDF5 queda en `/root/captura_<condicion>_<timestamp>.h5`.

### 4. Copiar capturas a la PC

```bash
# Copia manual
scp root@192.168.0.55:/root/captura_*.h5 capturas/

# O renombrar con contexto antes de copiar (ejemplo)
# En la RPi: mv captura_alta_20260624_150618.h5 arena_vacio_alta_20260624_150618.h5
# En la PC:
scp root@192.168.0.55:/root/arena_vacio_*.h5 capturas/
```

### 5. Ver metadatos de un archivo HDF5

```bash
.venv/bin/python3 scripts_rp/leer_h5.py capturas/*.h5
```

### 6. Analizar capturas y generar graficos

```bash
# Analiza todos los .h5 en capturas/
.venv/bin/python3 analisis/analisis_semana1.py

# Sincroniza desde RPi y luego analiza
.venv/bin/python3 analisis/analisis_semana1.py --sync

# Directorio alternativo
.venv/bin/python3 analisis/analisis_semana1.py --dir /ruta/a/capturas
```

Los graficos se guardan en `analisis/outputs/`:

| Archivo | Descripcion |
|---|---|
| `senal_raw.png` | Primeros 2 ms de senal cruda por captura |
| `fft_comparativa.png` | FFT superpuesta de todas las capturas |
| `espectrogramas.png` | STFT completa con escala de color compartida |
| `espectrograma_peak.png` | STFT centrada en el instante de maxima energia (vista instantanea) |
| `boxplots_metricas.png` | Boxplots de RMS, kurtosis, crest factor, etc. |

## Metricas calculadas por captura

| Metrica | Descripcion | Reposo tipico | Arena tipico |
|---|---|---|---|
| `rms` | Nivel RMS en la banda 100-450 kHz [V] | ~4 mV | ~5 mV |
| `kurtosis` | Impulsividad de la senal (gaussiana = 3) | ~3 | 70-900 |
| `crest_factor` | Relacion pico/RMS | ~5 | 60-150 |
| `conteo_eventos` | Cruces de umbral (3σ) en la banda | bajo | alto |
| `energia` | Energia total en la banda [V²] | — | — |

La **kurtosis** es el discriminador principal: ruido gaussiano = 3.0, eventos de arena = 24–300×.

## Parametros de adquisicion

```
fs_base   = 125 MHz
decimacion = 64  →  fs_efectiva = 1,953,125 Hz
buffer    = 16,384 muestras × 300 = 4,915,200 muestras (~2.5 s)
filtro    = Butterworth ord 4, pasa-banda 100-450 kHz
ganancia  = RP_GAIN_5X (modo HV, jumper ±20 V)
```
