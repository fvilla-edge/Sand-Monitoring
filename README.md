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
│   ├── capturar_stream.py     # Recomendado — streaming FILE mode, ~98% eficiencia, --canales 1|2
│   ├── probar_dual_stream.py  # Prueba de banco de solo lectura (2 canales)
│   ├── PLAN_CAMPO.md          # Indice de la guia operativa, mono y dual (--canales 1|2)
│   └── plan_campo/            # Guias detalladas: setup, operacion, formato, troubleshooting
├── scripts_campo_comun/    # Codigo y supervisor compartidos (campo_common.py, relanzar_captura.sh)
├── analisis/               # Scripts de analisis local (corren en la PC)
│   ├── revisar.py          # Revision rapida de capturas, mono o dual (.bin)
│   └── tests/              # Tests del parser de .bin y la logica de deteccion (pytest)
├── datos_campo/            # Capturas de campo (gitignoreado)
├── docs/                   # Roadmap del proyecto y notas tecnicas
├── requirements.txt        # Dependencias de analisis/ (PC) — numpy, scipy, pytest
└── COMANDOS.md             # Referencia rapida de todos los scripts y sus argumentos
```

## Setup (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Flujo basico

Para captura en campo (loop continuo, storage externo, mono o dual con `--canales`) ver
`scripts_campo/PLAN_CAMPO.md`.

Revision rapida de una captura de campo:

```bash
.venv/bin/python3 analisis/revisar.py /ruta/a/la/captura/
```

Para la lista completa de scripts y argumentos ver `COMANDOS.md`.
