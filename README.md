# Sand Monitoring — Deteccion acustica de arena en tuberias

La produccion de arena en pozos petroleros daña equipos y obstruye tuberias.
Este proyecto detecta y clasifica ese flujo de arena escuchando la tuberia con un sensor piezoacustico,
sin cortar la produccion ni instalar nada invasivo.

## Idea general

Un sensor acustico pegado a la tuberia capta las vibraciones que genera la arena al chocar contra las paredes.
Una placa Red Pitaya digitaliza esa senal y su FPGA calcula, en tiempo real, el area y la kurtosis
de cada ventana de 50 ms. La placa mide las 24 h (**modo evento**): guarda esos dos valores de todas
las ventanas y la senal cruda solo de las ventanas con kurtosis alta.

```
tuberia → sensor(es) VS150-RI → Red Pitaya (FPGA: area/kurtosis por ventana, modo evento 24 h)
        → USB: CSV por hora + crudos de eventos → cada 2 h por Starlink: CSV a GCS → SandVision (web)
                                                → resumen por minuto a Losant
```

Estado (2026-11-02): placa de campo `rp-f0fbda` instalada en PAD-118 (BPO-21182H) desde el 29/10,
en dual independiente y Starlink en modo ventana.

## Hardware

| Componente | Detalle |
|---|---|
| Sensor | Vallen VS150-RI — banda 100–450 kHz, preamp 40 dB integrado |
| ADC | Red Pitaya STEMlab 125-14 — 125 MS/s, 14 bits |
| Modo | High Voltage (jumper HV) — rango ±20 V |
| Relé biestable (`relay/`) | Corta/habilita alimentación del kit Starlink, pulsado desde `PS_MIO10` de la Red Pitaya — ver `starlink_remoto/` |
| LED de estado (`indicador_estado/`) | Parpadeo distinto segun captura/transmision/standby, pulsado desde `PS_MIO11` |
| Puente BLE→USB (`panel_solar_ble/`) | ESP32-C3 — la Red Pitaya no tiene soporte de Bluetooth en el kernel; lee el panel solar Victron SmartSolar por USB serial |
| RTC DS3231 (`rtc_ds3231/`) | Por I2C (bus 0) — mantiene la hora durante cortes de energia; al boot restaura la hora del sistema antes de ntpsec y de la logica de Starlink |

## Estructura

```
Sand Monitoring/
├── scripts_campo/          # Captura en campo (corren en la Red Pitaya)
│   ├── capturar_eventos.py    # Modo evento (lo que corre hoy): lanzador del nucleo C++ — ver docs/modo_evento.md
│   ├── c/                     # Nucleo C++ del modo evento (capturar_eventos.cpp, compilar en la placa)
│   ├── supervisor_eventos.sh  # Arranque/destino del modo evento (lo usa modo-evento.service)
│   ├── resumen_modo_evento.py # Anotador: resumen por minuto a Losant (me_activo, kurt_max_1min, ...)
│   ├── subir_csv_gcs.py       # Sube los CSV horarios (ventanas y energia) a Google Cloud Storage
│   ├── cambiar_canales.sh     # Mono / dual (IN2 independiente o asociado), con vuelta atras sola
│   ├── cambiar_modo.sh        # Modo evento <-> modo clasico
│   ├── systemd/               # modo-evento, resumen-modo-evento, subir-csv-gcs (.service/.timer)
│   ├── actualizacion/         # Paquetes de actualizacion: armar, enviar, aplicar, revertir
│   ├── capturar_stream.py     # Modo clasico: captura continua a pedido (.bin), streaming FILE mode
│   ├── probar_dual_stream.py  # Modo clasico: prueba de banco de solo lectura (2 canales)
│   ├── PLAN_CAMPO.md          # Indice de la guia operativa
│   └── plan_campo/            # Guias detalladas: setup, actualizaciones, troubleshooting, modo clasico
├── scripts_campo_comun/    # Codigo y supervisor compartidos
│   ├── campo_common.py        # Funciones compartidas de captura (FPGA, ADC, formato .bin)
│   ├── cfg.py                 # Lectura de config_campo.json — fuente unica de parametros operativos
│   ├── config_campo.json      # Umbrales, horarios y rutas — compartido con starlink_remoto/ y panel_solar_ble/
│   ├── estado_placa.sh        # Resumen de solo lectura de una placa (se corre desde la PC por ssh)
│   ├── inventario_placa.sh    # Inventario de lo instalado (antes de una actualizacion)
│   ├── relanzar_captura.sh    # Modo clasico: relanza capturar_stream.py si el streaming-server se cae
│   ├── repetir_captura.sh     # Modo clasico: repite una captura corta N veces
│   └── udev-automount/        # Montaje/desmontaje automatico del storage de campo (USB/SSD) en /mnt/usb
├── analisis/               # Scripts de analisis (mayoria corre en la PC, placa/ es la excepcion)
│   ├── revisar.py          # Revision rapida de capturas del modo clasico, mono o dual (.bin)
│   ├── visores/            # GUIs de matplotlib/tkinter (ver_forma_onda.py, ver_acumulado_lote.py + abrir_*.sh)
│   ├── lote/               # Analisis de un lote completo pegado en el tiempo (acumulado_lote.py)
│   ├── utilidades/         # organizar_csv_campo.py (CSV de campo por dia), graficar.py, extraer_canal.py, generar_baseline.py
│   ├── placa/              # Modo evento en la PC: reconstruir_senal.py, comparar_in1_in2.py (ventanas_a_paquete.py: solo para el visor viejo, en desuso)
│   ├── INTERPRETACION_RESULTADOS.md  # Guia de lectura de metricas: deteccion vs clasificacion
│   └── tests/              # Tests del parser de .bin y la logica de deteccion (pytest)
├── indicador_estado/       # LED de estado (PS_MIO11) — parpadeo distinto en captura/transmision/standby
├── starlink_remoto/        # Control del rele que energiza el kit Starlink (PS_MIO10)
│   ├── control_starlink.sh    # Prender/apagar, idempotente por feedback de HW
│   ├── decidir_objetivo.sh    # Unica logica de decision (rescate > manual > reloj no confiable > modo permanente/ventana); reloj confiable = NTP sincronizado o RTC DS3231 restaurado en este boot
│   ├── aplicar_objetivo.sh    # Aplica lo que decide decidir_objetivo.sh (reconciliador de 5 min)
│   ├── ventana_starlink.sh    # Una ventana del modo ventana (cada 2 h): prende, sube a GCS, apaga
│   ├── modo_operacion.sh      # Ver/cambiar el modo de Starlink (ventana | permanente)
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
│   ├── publicar_losant.py     # "Cartero": publica a Losant por MQTT y recibe sus comandos (modo, canales, starlink)
│   ├── registro_energia.py    # CSV por minuto/hora de la energia (con o sin internet)
│   ├── balance_energia.py     # SOC por conteo de Ah y balance horario/diario
│   └── systemd/                # Servicio que corre publicar_losant.py en la placa
├── rtc_ds3231/             # RTC DS3231 por I2C — reloj confiable sin conectividad
│   ├── ds3231.py               # Lectura/escritura por I2C via smbus2 (sin dependencias del proyecto)
│   ├── leer_epoch.py           # Imprime el epoch Unix (UTC) leido del RTC
│   ├── probar_rtc.py           # Prueba aislada por linea de comandos (lee, opcionalmente setea, compara con el sistema)
│   ├── restaurar_hora.sh       # Al boot, setea la hora del sistema desde el RTC antes de ntpsec y Starlink
│   └── systemd/                # Unit que corre restaurar_hora.sh en el boot (antes de ntpsec y del mux de PS_MIO10)
├── comandos_losant/        # modo_starlink.py: cambiar el tag modo_starlink desde la PC (API REST); el resto es la prueba vieja de comandos
├── relay/                  # Foto/referencia del modulo de rele biestable
├── datos_campo/            # Capturas de campo (gitignoreado)
├── docs/                   # modo_evento.md (como funciona hoy) + planes/bitacoras de cada feature (plan_*.md)
├── Click_shield_for_Red_Pitaya_v102_Schematic.pdf  # Esquematico de la Click Shield
├── requirements.txt        # Dependencias de analisis/ (PC) — numpy, scipy, pytest
├── COMANDOS.md             # Referencia rapida de todos los scripts y sus argumentos
├── DESPLIEGUE.md           # Que reiniciar despues de tocar cada archivo en la placa
└── GUIA_USO_BASICO.md      # Guia de uso dia a dia, paso a paso, para alguien nuevo
```

## Setup (PC local — una sola vez)

```bash
cd "Sand Monitoring"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Flujo basico

Para alguien nuevo en el proyecto, empezar por `GUIA_USO_BASICO.md`: encender, ver que
este midiendo, modos de Starlink y de canales, datos y apagado.

- Como funciona el modo evento por dentro: `docs/modo_evento.md`.
- Setup, actualizaciones y troubleshooting de una placa: `scripts_campo/PLAN_CAMPO.md`.
- Lista completa de scripts y argumentos: `COMANDOS.md`.
- Ver los datos: SandVision (`vista-sandvision.web.app`, repo aparte `SandVision-web-app`)
  lee los CSV que la placa sube a GCS.

Modo clasico (capturas `.bin` continuas a pedido, como antes del modo evento): ver
`scripts_campo/plan_campo/operacion_campo.md`; revision rapida en la PC con
`.venv/bin/python3 analisis/revisar.py /ruta/a/la/captura/`.

## Analizar las mediciones del modo evento (CSV de ventanas)

En modo evento la placa guarda, ademas de la señal cruda de cada evento, un CSV
por hora con el area y la kurtosis de TODAS las ventanas de 50 ms
(`/mnt/usb/eventos/ventanas_AAAAMMDD_HH.csv`, ~3 MB/hora, hora en UTC = local + 3).
Es liviano para bajarlo por Starlink y alcanza para ver la linea de tiempo del dia.
Detalle del modo en `docs/modo_evento.md`. En dual, los del IN2 estan en
`/mnt/usb/eventos/in2/` con el mismo nombre.

**Lo normal es no bajarlos de la placa:** suben solos a GCS en cada ventana de Starlink
(`<prefijo>/<hostname>/AAAA/MM/DD/ventanas_AAAAMMDD_HH[_sd][_in2].csv.gz`, bucket en
`config_campo.json` → `gcs`) y se miran en SandVision. Los pasos de abajo son para
analizarlos en la PC; si ya estan en GCS, se pueden bajar
de ahi (descomprimir el `.gz`) y saltear los pasos 1-2.

Desde la carpeta del proyecto, con Starlink prendido (modo permanente, o durante una ventana).
`<IP_CAMPO>` es la IP publica actual de la placa de campo.

1. Ver que horas hay en la placa (la hora en curso todavia se esta escribiendo;
   si se la trae, viene cortada):
   ```bash
   ssh root@<IP_CAMPO> 'ls -la /mnt/usb/eventos/*.csv'
   ```
2. Traerlos a una carpeta de bajada y verificar md5 (`datos_campo/` no va a git).
   Pueden estar en el disco (`/mnt/usb/eventos/`) o, si la placa midio sin disco,
   en la SD (`/root/eventos_sd/`):
   ```bash
   mkdir -p datos_campo/placa_campo/_bajadas/AAAAMMDD
   scp 'root@<IP_CAMPO>:/mnt/usb/eventos/ventanas_20260929_*.csv' datos_campo/placa_campo/_bajadas/AAAAMMDD/
   ```
3. Juntarlos en la carpeta por dia (`csv_por_dia/AAAA-MM-DD/`, dia UTC como el
   nombre del archivo; une la misma hora si quedo repartida entre SD y disco,
   descarta copias parciales, limpia NUL; primero sin `--aplicar` para ver que hace):
   ```bash
   python3 analisis/utilidades/organizar_csv_campo.py datos_campo/placa_campo/csv_por_dia datos_campo/placa_campo/csv_por_dia datos_campo/placa_campo/_bajadas/AAAAMMDD --aplicar
   ```
4. Lista de ventanas sobre el umbral de la placa (3.4) con su hora (el `LC_ALL=C` es
   necesario: con el idioma en español awk usa coma decimal y cuenta mal):
   ```bash
   LC_ALL=C awk -F, 'NR>1 && $4>=3.4 {printf "%s UTC  kurt=%.2f  area=%.3f\n", strftime("%H:%M:%S",$2/1000,1), $4, $3}' datos_campo/placa_campo/csv_por_dia/2026-09-29/ventanas_*.csv
   ```

Como leerlo:

- **Reposo:** kurtosis ~3 y area plana.
- **Pico aislado:** una sola ventana sobre el umbral con las vecinas en ~3. Solo, no
  alcanza para decir que es arena (puede ser ruido electrico del lugar).
- **Pase de arena** (como los del 21/9): muchas ventanas seguidas sobre el umbral
  durante minutos, valores altos (decenas a cientos) y el area subiendo.
- Lo que valida es cruzar esos horarios con el informe de arena del pozo.
