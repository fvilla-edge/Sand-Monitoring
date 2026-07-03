# Sand Monitoring — Deteccion acustica de arena en tuberias

La produccion de arena en pozos petroleros daña equipos y obstruye tuberias.
Este proyecto detecta y clasifica ese flujo de arena escuchando la tuberia con un sensor piezoacustico,
sin cortar la produccion ni instalar nada invasivo.

## Idea general

Un sensor acustico pegado a la tuberia capta las vibraciones que genera la arena al chocar contra las paredes.
Una placa ADC digitaliza esa senal a alta frecuencia, y un script calcula metricas (kurtosis, RMS, crest factor,
rms diferencial) que permiten distinguir reposo de produccion de arena.

```
tuberia  →  sensor(es) VS150-RI  →  Red Pitaya (ADC)  →  captura .bin en campo  →  analisis en PC
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
├── scripts_campo/          # Captura en campo (corren en la Red Pitaya)
│   ├── capturar_stream.py  # Recomendado — streaming, raw .bin, ~98% eficiencia, --canales 1|2
│   ├── capturar_campo.py   # Alternativa HDF5, ~54% eficiencia, solo mono
│   ├── probar_dual_stream.py  # Prueba de banco para mapeo de canales (2 canales)
│   ├── PLAN_CAMPO.md       # Parametros, procedimiento y ejemplos de uso en campo
│   └── PLAN_DUAL.md        # Especifico de --canales 2 (mapeo, consideraciones de sensor referencia)
├── scripts_campo_comun/    # Codigo y supervisor compartidos (campo_common.py, relanzar_captura.sh)
├── analisis/               # Scripts de analisis local (corren en la PC)
│   ├── revisar.py          # Revision rapida de capturas, mono o dual (.bin)
│   └── espectrograma.py    # Espectrograma STFT de una captura de campo
├── capturas/               # Capturas de campo (gitignoreado)
└── docs/                   # Informes y roadmap
```

## Setup (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install h5py scipy matplotlib numpy
```

## Flujo basico

Para captura en campo (loop continuo, storage externo) ver `scripts_campo/PLAN_CAMPO.md`.
Para dual-canal (`--canales 2`) ver `scripts_campo/PLAN_DUAL.md`.

Revision rapida de una captura de campo:

```bash
.venv/bin/python3 analisis/revisar.py /ruta/a/la/captura/
```
