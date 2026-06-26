# Sand Monitoring — Deteccion acustica de arena en tuberias

La produccion de arena en pozos petroleros daña equipos y obstruye tuberias.
Este proyecto detecta y clasifica ese flujo de arena escuchando la tuberia con un sensor piezoacustico,
sin cortar la produccion ni instalar nada invasivo.

## Idea general

Un sensor acustico pegado a la tuberia capta las vibraciones que genera la arena al chocar contra las paredes.
Una placa ADC digitaliza esa senal a alta frecuencia, y un script calcula metricas (kurtosis, RMS, crest factor)
que permiten distinguir reposo de produccion de arena.

```
tuberia  →  sensor VS150-RI  →  Red Pitaya (ADC)  →  HDF5  →  analisis en PC
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
├── scripts_rp/          # Scripts de laboratorio (corren en la Red Pitaya)
│   ├── capturar.py      # Captura + metricas, guarda HDF5
│   └── leer_h5.py       # Lectura rapida de metadatos
├── scripts_campo/       # Scripts de campo (corren en la Red Pitaya)
│   ├── capturar_campo.py  # Loop continuo, raw, streaming a storage externo
│   └── PLAN_CAMPO.md    # Parametros, procedimiento y ejemplos de uso en campo
├── analisis/            # Scripts de analisis local (corren en la PC)
│   └── analisis_semana*.py
├── capturas/            # Archivos HDF5 (gitignoreado)
└── docs/                # Informes y roadmap
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
