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
| Relé biestable (`relay/`) | Corta/habilita alimentación del kit Starlink, pulsado desde `PS_MIO10` de la Red Pitaya — ver `starlink_remoto/` |
| LED de estado (`indicador_estado/`) | Parpadeo distinto segun captura/transmision/standby, pulsado desde `PS_MIO11` |
| Puente BLE→USB (`panel_solar_ble/`) | ESP32-C3 — la Red Pitaya no tiene soporte de Bluetooth en el kernel; lee el panel solar Victron SmartSolar por USB serial |

## Estructura

```
Sand Monitoring/
├── scripts_campo/          # Captura en campo (corren en la Red Pitaya)
│   ├── capturar_stream.py     # Recomendado — streaming FILE mode, ~98% eficiencia, --canales 1|2
│   ├── probar_dual_stream.py  # Prueba de banco de solo lectura (2 canales)
│   ├── PLAN_CAMPO.md          # Indice de la guia operativa, mono y dual (--canales 1|2)
│   └── plan_campo/            # Guias detalladas: setup, operacion, formato, troubleshooting
├── scripts_campo_comun/    # Codigo y supervisor compartidos
│   ├── campo_common.py        # Funciones compartidas de captura (FPGA, ADC, formato .bin)
│   ├── cfg.py                 # Lectura de config_campo.json — fuente unica de parametros operativos
│   ├── config_campo.json      # Umbrales, horarios y rutas — compartido con starlink_remoto/ y panel_solar_ble/
│   ├── relanzar_captura.sh    # Supervisor: relanza capturar_stream.py si el streaming-server se cae
│   ├── repetir_captura.sh     # Repite una captura corta N veces (carpetas livianas, mas faciles de transmitir)
│   └── udev-automount/        # Montaje/desmontaje automatico del storage de campo (USB/SSD) en /mnt/usb
├── analisis/               # Scripts de analisis local (corren en la PC)
│   ├── revisar.py          # Revision rapida de capturas, mono o dual (.bin) — fuente de verdad en texto
│   ├── graficar.py         # Graficos de barras para demo, mismas metricas que revisar.py
│   ├── INTERPRETACION_RESULTADOS.md  # Guia de lectura de metricas: deteccion vs clasificacion
│   └── tests/              # Tests del parser de .bin y la logica de deteccion (pytest)
├── indicador_estado/       # LED de estado (PS_MIO11) — parpadeo distinto en captura/transmision/standby
├── starlink_remoto/        # Control del rele que energiza el kit Starlink (PS_MIO10)
│   ├── control_starlink.sh    # Prender/apagar, idempotente por feedback de HW
│   ├── decidir_objetivo.sh    # Unica logica de decision (rescate > manual > reloj no confiable > horario)
│   ├── aplicar_objetivo.sh    # Aplica lo que decide decidir_objetivo.sh (reconciliador de 5 min)
│   ├── aplicar_horario.sh     # Aplica hora_on/hora_off de config_campo.json a los timers
│   ├── starlink_manual.sh     # Entrar/salir de modo manual
│   ├── estado_starlink.sh     # Lectura pasiva del ultimo estado conocido
│   ├── asegurar_mux_ps10.sh   # Fuerza el mux de PS_MIO10 al boot
│   ├── mux_ps10_common.sh     # Registros/funciones compartidas del pulso por PS_MIO10
│   ├── aliases.sh             # Alias de bash para controlar el rele a mano por SSH
│   ├── systemd/                # Units y timers (mux al boot, rele on/off, reconciliador)
│   └── HISTORIAL_STARLINK.md  # Arquitectura y hallazgos de hardware (no es guia de uso)
├── panel_solar_ble/        # Panel solar Victron SmartSolar via puente ESP32-C3 BLE→USB serial (ver su README)
│   ├── esp32_victron_scan/    # Sketch del ESP32-C3 (el puente en si)
│   ├── victron_scanner.py     # Desencriptado AES-CTR + parser de las lineas del ESP32
│   ├── leer_smartsolar_serial.py  # Lectura por pantalla, para probar el puente
│   ├── publicar_losant.py     # Publica por MQTT a Losant (por conexion y cada N minutos)
│   └── systemd/                # Servicio que corre publicar_losant.py en la placa
├── relay/                  # Foto/referencia del modulo de rele biestable
├── datos_campo/            # Capturas de campo (gitignoreado)
├── docs/                   # Roadmap del proyecto y notas tecnicas
├── Click_shield_for_Red_Pitaya_v102_Schematic.pdf  # Esquematico de la Click Shield
├── requirements.txt        # Dependencias de analisis/ (PC) — numpy, scipy, pytest
├── COMANDOS.md             # Referencia rapida de todos los scripts y sus argumentos
└── GUIA_USO_BASICO.md      # Guia de uso dia a dia, paso a paso, para alguien nuevo
```

## Setup (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Flujo basico

Para alguien nuevo en el proyecto, empezar por `GUIA_USO_BASICO.md` — flujo tipico
paso a paso (encender, prender Starlink, capturar, sacar datos, revisar, apagar).

Para captura en campo (loop continuo, storage externo, mono o dual con `--canales`) ver
`scripts_campo/PLAN_CAMPO.md`.

Revision rapida de una captura de campo:

```bash
.venv/bin/python3 analisis/revisar.py /ruta/a/la/captura/
```

Para la lista completa de scripts y argumentos ver `COMANDOS.md`.
