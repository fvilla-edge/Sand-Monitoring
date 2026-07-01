# Sand Monitoring — Deteccion acustica de arena en tuberias

La produccion de arena en pozos petroleros daña equipos y obstruye tuberias.
Este proyecto detecta y clasifica ese flujo de arena escuchando la tuberia con un sensor piezoacustico,
sin cortar la produccion ni instalar nada invasivo.

## Idea general

Un sensor acustico pegado a la tuberia capta las vibraciones que genera la arena al chocar contra las paredes.
Una placa ADC digitaliza esa senal a alta frecuencia, y un script calcula metricas (kurtosis, RMS, crest factor,
rms diferencial) que permiten distinguir reposo de produccion de arena.

```
tuberia  →  sensor(es) VS150-RI  →  Red Pitaya (ADC)  →  captura (HDF5 en lab / .bin en campo)  →  analisis en PC
```

## Hardware

| Componente | Detalle |
|---|---|
| Sensor | Vallen VS150-RI — banda 100–450 kHz, preamp 40 dB integrado |
| ADC | Red Pitaya STEMlab 125-14 — 125 MS/s, 14 bits |
| Modo | High Voltage (jumper HV) — rango ±20 V |

## Estructura

```
Sand Monitoring/
├── scripts_rp/            # Scripts de laboratorio (corren en la Red Pitaya)
│   ├── capturar.py        # Captura + metricas, guarda HDF5
│   └── leer_h5.py         # Lectura rapida de metadatos
├── scripts_campo/         # Captura mono-canal en campo (corren en la Red Pitaya)
│   ├── capturar_campo_stream.py  # Recomendado — streaming, raw .bin, ~98% eficiencia
│   ├── capturar_campo.py         # Alternativa HDF5, ~54% eficiencia
│   └── PLAN_CAMPO.md      # Parametros, procedimiento y ejemplos de uso en campo
├── scripts_campo_dual/    # Captura dual-canal (codo + referencia), experimental
│   ├── capturar_dual_stream.py
│   └── PLAN_DUAL.md
├── analisis/              # Scripts de analisis local (corren en la PC)
│   ├── revisar_campo.py   # Revision rapida de capturas mono (.bin)
│   ├── revisar_dual.py    # Revision rapida de capturas dual (.bin)
│   └── analisis_semana*.py  # Analisis historico del dataset de laboratorio
├── capturas/              # Archivos HDF5 de laboratorio (gitignoreado)
└── docs/                  # Informes y roadmap
```

## Setup (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install h5py scipy matplotlib numpy
```

## Flujo basico

```bash
# 1. Copiar script a la Red Pitaya
scp scripts_rp/capturar.py root@<IP>:/root/

# 2. Capturar (en la Red Pitaya via SSH)
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/capturar.py --condicion reposo
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/capturar.py --condicion alta

# 3. Traer capturas a la PC
scp root@<IP>:/root/captura_*.h5 capturas/

# 4. Analizar
.venv/bin/python3 analisis/analisis_semana1.py
```

Para captura en campo (loop continuo, storage externo) ver `scripts_campo/PLAN_CAMPO.md`.
Para dual-canal ver `scripts_campo_dual/PLAN_DUAL.md`.

Revision rapida de una captura de campo:

```bash
.venv/bin/python3 analisis/revisar_campo.py /ruta/a/la/captura/
.venv/bin/python3 analisis/revisar_dual.py /ruta/a/la/captura/
```
