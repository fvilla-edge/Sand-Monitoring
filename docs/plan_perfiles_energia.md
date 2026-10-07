# Plan — Perfiles de energía (registro de batería + Starlink según autonomía)

Creado 2026-10-07. Estado: **plan, sin código**. Rama `perfiles-energia`,
sale de `main` = tag de campo `campo-2026-10-05b` (`3dd05e9`): va a campo
antes que el IN2, sin arrastrarlo. De `in2-sensor` no se trae el comando
`canales` (depende de `cambiar_canales.sh` y del IN2). Datos de partida en
`datos_campo/bateria.csv` (export de Losant, 7/9 → 6/10).

## Por qué

El 6/10 la placa de campo se apagó y no volvió a prender: varios días de
lluvia y, desde el 5/10, Starlink los 7 días (antes solo días hábiles). Hoy
no hay forma de ver la batería de noche ni de decidir cuántas horas de
Starlink se pueden pagar.

## Hardware (dato del usuario, 2026-10-07)

- Batería LiFePO4 12 V 100 Ah (1280 Wh nominales), cargador configurado
  para LiFePO4.
- Panel 120 W. SmartSolar MPPT 75/15.
- **Todas las cargas en la salida LOAD del MPPT** (Pitaya, ESP32, hub,
  Starlink Mini). El corte por baja tensión de LOAD es lo que apaga todo.

## Lo que ya está confirmado con los datos

- `battery_charging_current` es la corriente **neta** de la batería:
  `I = solar_power / V − external_device_load` (error mediano 0,15 A; como
  corriente bruta da 2,05 A). El MPPT ve todo el balance: no hace falta
  shunt y el SOC se puede contar en la placa.
- Con Starlink (ventana ~8,2 h): carga ~26 W (mediana), ~222 Wh por
  ventana; generación 103–506 Wh/día (mediana 349); la batería gana
  +113 Wh de mediana en la ventana y 5 de 20 días pierde aun de día.
- La batería llegó a absorción/float 10 de 20 días; desde el 23/9 solo 2.
- La carga subió de 23–24 W (7–15/9) a 26–28 W (desde 17/9), causa sin
  identificar.
- `yield_today` es por "día solar" (el MPPT no tiene reloj) y tiene pasos
  de 10 Wh: para cuentas por hora se integra `solar_power`.
- Hay lecturas basura (2 de 710: 231 V / 514 kWh, 44,9 A): hay que filtrar.

## Decisiones del usuario

1. Starlink sigue los 7 días, con menos horas de encendido.
2. Guardar los datos en CSV en la placa y seguir publicando como hoy; de
   noche, sin internet, se acumulan.
3. Perfiles de carga según la autonomía: por ejemplo, prender Starlink cada
   tanto para mandar lo pendiente y apagarla; por debajo de un umbral,
   Starlink apagada y la captura sigue normal.

## Etapa 0 — Starlink ya, sin código nuevo (POSTERGADA)

- 2026-10-07, decisión del usuario: no se acortan las horas todavía (hace
  falta el acceso de 08:55 a 17:15 para hacer cambios); primero las etapas
  1-4, después se reducen las horas.

- Hoy el horario admite una sola ventana por día (`starlink.hora_on` /
  `hora_off`). Más de una ventana es código nuevo (va con la etapa 4).
- Mientras tanto: una ventana más corta, en las horas de más sol, para
  que la pague el panel y no la batería. En los datos el panel rinde más
  de 10:00 a 12:00 local; a la tarde `solar_power` cae a ~26–28 W, lo que
  consume el equipo: en días con batería llena el MPPT recorta y el sol
  sobrante se pierde.
- Riesgo al volver de un corte de LOAD: si la placa prende dentro de la
  ventana, Starlink suma ~20 W sobre una batería casi vacía y puede volver
  a cortar.

## Etapa 1 — Registro en la placa

- Lo hace `publicar_losant.py`, que ya es el único que abre el puerto
  serie del ESP32 (un segundo lector no puede abrirlo a la vez).
- Una fila por minuto (promedio del minuto, no la última lectura) en CSV
  por hora en el USB (`/mnt/usb/energia/energia_AAAAMMDD_HH.csv`; sin USB,
  en la SD), con escritura atómica y `fsync`: el corte de LOAD apaga la
  placa sin aviso.
- Columnas: hora UTC, `hora_confiable` (NTP sincronizado o RTC DS3231
  restaurado en este boot), V, I neta, `external_device_load`,
  `solar_power`, `yield_today`, `charge_state`, `charger_error`, relé de
  Starlink (on/off), modo evento (canales), cantidad de lecturas del
  minuto.
- Filtro de rangos antes de promediar (V 9–16 V, |I| < 20 A, carga < 15 A,
  panel < 150 W); las lecturas descartadas se cuentan aparte.
- Los CSV suben a GCS con el mismo timer que los del modo evento
  (carpeta propia).

## Etapa 2 — Cálculo y resumen horario

Módulo `panel_solar_ble/balance_energia.py`: `registro_energia.py` le pasa
cada fila de minuto que escribe. Corre en el mismo proceso
(`publicar_losant.py`), sin tocar hardware.

**Valores de partida** (historial del MPPT, `datos_campo/cargador/SolarHistory.csv`,
7/9–7/10; las fechas del historial están corridas 1–2 días respecto del
calendario): consumo de la salida LOAD 320–380 Wh/día con Starlink y
150–220 Wh/día sin Starlink ⇒ base ≈ 7,5 W las 24 h y Starlink ≈ +20 W
mientras está prendida. Se usan solo hasta que haya datos propios: los
promedios se actualizan minuto a minuto (media móvil de ~7 días).

**Estado en disco** (`energia.estado_file`, en la SD, escritura atómica +
`fsync` cada minuto): SOC en Ah, hora del último float, acumuladores de la
hora y del día local (UTC−3), promedios de consumo con y sin Starlink.

**SOC**
- Cada minuto: `soc_ah += i_bat × 1/60`, limitado a 0–`capacidad_ah`
  (100 Ah).
- `estado_carga = float` ⇒ 100 %.
- Al arrancar: el último SOC guardado. Si la salida LOAD estuvo apagada,
  la batería solo pudo cargarse, así que es una cota inferior (el 6/10 se
  cortó LOAD con la batería ~90 %: asumir "casi vacía" habría sido falso).
- Sin estado previo (primera vez): 50 %, marcado no confiable.
- `en_soc_confiable` = hubo float en los últimos 7 días.

**Resumen horario** a la cola del cartero (`<ms>.energia.json`, mismo
formato `{"time", "data"}` que los del modo evento; el cartero ordena por el
número del nombre):

| Atributo Losant | Cálculo |
|---|---|
| `en_soc_pct`, `en_soc_confiable` | SOC al cierre de la hora |
| `en_energia_restante_wh` | SOC × `capacidad_util_wh` (1150 Wh, supuesto 90 % de 1280) |
| `en_autonomia_sin_sl_h` | energía restante / consumo promedio sin Starlink |
| `en_autonomia_con_sl_dias` | energía restante / consumo de un día con el horario actual de Starlink |
| `en_p_carga_w` | consumo promedio de la hora |
| `en_e_carga_wh`, `en_e_pv_wh`, `en_e_bat_wh` | Σ P·Δt de la hora |
| `en_balance_dia_wh` | Σ `e_bat` del día local hasta el cierre de la hora |
| `en_v_min` | tensión mínima de la hora |
| `en_starlink_min`, `en_minutos` | minutos con Starlink y minutos con datos en la hora |

Control cruzado: el consumo diario calculado tiene que parecerse al
"Consumption" del historial del MPPT.

Pendiente: corregir `capacidad_util_wh` con los Ah descargados entre un
float y un corte real de LOAD; detectar cortes de LOAD (hueco + vuelta).

## Etapa 3 — Valores de diseño (cerrada con estimaciones, 2026-10-07)

Decisión del usuario: no medir aparte, usar el historial del MPPT y los
datos de Losant con margen.

| Dato | Medido | Valor de diseño |
|---|---|---|
| Base (Pitaya + ESP32 + hub) | ~7,5 W | **9 W** (216 Wh/día) |
| Starlink prendida | ~+20 W | **+25 W** (25 Wh por hora) |
| Costo de un encendido | sin medir | **2 Wh y 5 min** sin servicio (supuesto: arranque ~30 W) |
| Energía útil de la batería | — | 1150 Wh |
| Generación | lluvia 60–230, mediana 350, sol 400–590 Wh/día | la medida |

El límite real de una ventana corta no es la energía sino lo pendiente:
los CSV de ventanas suben de a 2 cada 5 min (una noche de 16 h ≈ 40 min) y
los resúmenes de a uno por segundo (1 h de resúmenes ≈ 1 min). Por eso las
ventanas son de 1 h, no menos.

## Etapa 4 — Perfiles

### Niveles (umbrales y horarios decididos por el usuario, 2026-10-07)

| Nivel | Energía restante | Starlink (hora local) | Consumo/día (diseño) | Días sin sol desde llena |
|---|---|---|---|---|
| **Normal** | ≥ 70 % | horario actual (`hora_on`–`hora_off`, `dias_habilitados`) | ~430 Wh | ~2,7 |
| **Ahorro** | 40–70 % | 09:00–10:00, 12:30–13:30, 16:00–17:00 | ~300 Wh | ~3,8 |
| **Crítico** | 20–40 % | 12:30–13:30 | ~245 Wh | ~4,7 |
| **Supervivencia** | < 20 % | apagada (la captura sigue) | ~216 Wh | ~5,3 |

### Cómo se decide el nivel (cada minuto, en `balance_energia.py`)

1. **Energía restante (SOC)**: nivel por los umbrales 70 / 40 / 20 %.
   Histéresis: para **subir** de nivel hace falta +10 % sobre el umbral
   (Ahorro → Normal con ≥ 80 %); para bajar alcanza con cruzarlo.
2. **SOC no confiable** (sin float en 7 días, o recién instalado): como
   máximo **Ahorro**.
3. **Float o absorción hoy** (día local): la batería ya se llenó, sobra
   sol: se permite **Normal** (el float además pone el SOC en 100 %).
4. **Tensión** (respaldo, solo baja el nivel): promedio de los últimos 30
   minutos < 12,9 V ⇒ como máximo **Crítico**; < 12,7 V ⇒
   **Supervivencia**. Umbrales iniciales supuestos (con carga), a ajustar
   con una descarga real del registro. Se usa el promedio y no la mínima:
   el historial tiene mínimas de 12,6 V en días que terminaron en float
   (caídas momentáneas).

El nivel y el motivo van a `/run/energia_nivel.json` (tmpfs: se recalcula
al arrancar con el primer minuto) y a Losant (`en_nivel`, `en_nivel_motivo`,
`en_v_prom_30min`).

### Cómo se aplica a Starlink

- `starlink_remoto/decidir_objetivo.sh`: el perfil entra entre "reloj no
  confiable → on" y el horario. Orden: rescate manual vencido > modo manual
  > reloj no confiable > **perfil** > horario. Normal = el horario de hoy.
  La autolimpieza del modo manual compara contra el resultado nuevo.
- Nivel vencido (archivo con más de 15 min o inexistente: sin ESP32,
  `publicar_losant.py` caído, clave del Victron cambiada): **horario
  normal**, igual que hoy (decisión del usuario, 2026-10-07: una falla del
  sensor no tiene que dejar sin acceso remoto para arreglarla).
- Bordes de las ventanas: un timer nuevo (`starlink-perfil.timer`) con un
  `OnCalendar` por cada borde (09:00, 10:00, 12:30, 13:30, 16:00, 17:00,
  hora local) que corre `aplicar_objetivo.sh` (sin `--reconciliar`: el
  borde se aplica en el momento). Un cambio de nivel entre bordes lo aplica
  el reconciliador (≤ ~10 min). Si cambian los horarios en el config, hay
  que regenerar el timer.
- Supervivencia: Starlink **apagada del todo** hasta que la batería se
  recupere y el nivel suba solo (decisión del usuario, 2026-10-07: sin
  ventana de rescate).
- GCS: en Ahorro y Crítico, más archivos por corrida (6 en vez de 2) para
  vaciar lo pendiente dentro de la ventana de 1 h.

### Config (`config_campo.json`, sección nueva `perfiles`)

`umbrales_pct` [70, 40, 20], `histeresis_pct` 10, `v_critico` 12.9,
`v_supervivencia` 12.7, `ventanas_ahorro` ["09:00-10:00", "12:30-13:30",
"16:00-17:00"], `ventanas_critico` ["12:30-13:30"], `nivel_file`
`/run/energia_nivel.json`, `nivel_vencido_min` 15, `gcs_max_por_corrida_ventanas` 6.

### Pruebas en la placa de pruebas

La decisión (`decidir_objetivo.sh`) no toca hardware: se prueba escribiendo
el archivo de nivel a mano y moviendo la hora. El relé del lab no confirma
"off" (DIO2_P a GND = siempre "on"), así que la parte de hardware solo se
verifica en el pedido, no en el feedback.

## Etapa 5 — Placa de pruebas

Sin ESP32 ni batería real: probar el registro con lecturas simuladas por el
puerto serie, cortes de energía y los cambios de nivel con el relé simulado
(DIO2_P a GND = relé siempre "on").

## Etapa 6 — Campo

Después de la placa de pruebas, anotado en
`scripts_campo/plan_campo/actualizar_placa_campo.md`.

## Riesgos

- Prender Starlink muy seguido puede costar más de lo que ahorra
  (arranque); se decide con la medición de la etapa 3.
- SOC sin float por días de lluvia: deriva; por eso la cota por tensión.
- Un corte de LOAD apaga todo sin aviso: todo lo que se escribe, con `fsync`.

## Bitácora

- 2026-10-07: plan escrito tras el apagón del 6/10 y el análisis de
  `datos_campo/bateria.csv`.
- 2026-10-07: etapa 1 escrita (sin commitear): `panel_solar_ble/registro_energia.py`
  + llamada desde `publicar_losant.py` + clave `energia` en
  `config_campo.json`. Probada en la PC con lecturas armadas (15 chequeos:
  minutos con hueco, basura descartada, cambio de hora, sin USB a la SD,
  línea cortada por un apagón, archivo vacío, disco que falla). Encontrado
  y arreglado en la prueba: tras una línea cortada la fila nueva se pegaba
  al pedazo. Falta: prueba en placa (sin ESP32 real) y subida a GCS (1b).

- 2026-10-07: **prueba en la placa de pruebas con ESP32 simulado, OK.**
  Simulador (pty + líneas `MAC=.. DATA=..` cifradas con la clave real,
  AES-CTR como el SmartSolar) y `publicar_losant.py` de esta rama desde
  `/root/prueba_energia/` (servicio `panel-solar-informe` parado durante la
  prueba, 15:03-15:12 UTC, y vuelto a arrancar). 7 minutos con valores
  conocidos, hueco en 15:07-15:08, una lectura de 231 V y líneas con hex
  roto por minuto: el CSV salió idéntico a lo enviado (5 filas, 58
  lecturas y 1 descartada por minuto, sin fila en el hueco), en
  `/mnt/usb/energia/` con la clave `energia` ausente del config (usó los
  valores por defecto). El informe a Losant (`test_SC`) siguió igual, y al
  cerrarse el puerto siguió sin ESP32. El CSV de la prueba quedó en
  `/root/prueba_energia/` de la placa.
- 2026-10-07: etapa 1b escrita: `scripts_campo/subir_csv_gcs.py` sube los
  CSV de energía (USB y `_sd`) con prefijo propio (el de `gcs.prefijo` con
  `energia` como última parte: `campo/energia`, `pruebas/energia`), cupo de
  12 por corrida y 2 s de pausa, después de los de ventanas; un corte de red
  corta la corrida entera. Probada en la PC con subida simulada (11
  chequeos: una noche de 16 h en 2 corridas, hora en curso no sube, hora
  partida USB/SD, nada dos veces, corte de red y recuperación).
- 2026-10-07 16:29 UTC: **subida real OK** desde la placa de pruebas (copia
  aparte del script, registro temporal, sin tocar `gcs.habilitado=false`):
  `pruebas/energia/rp-f0fd8c/2026/10/07/energia_20261007_15.csv.gz`, 581 ->
  259 B, md5 ok; la cuenta de servicio acepta el prefijo nuevo. Segunda
  corrida: nada pendiente.
- 2026-10-07: historial del MPPT y capturas de VictronConnect
  (`datos_campo/cargador/`): el corte del 6/10 NO fue por batería baja
  (13,20 V a las 11:41 local, float el 4/10, ~90 % al cortar; hoy LOAD
  apagada con 13,52 V cargando). Causa sin identificar: revisar la
  configuración de la salida de carga en el sitio. Consumo LOAD: 320–380
  Wh/día con Starlink, 150–220 sin Starlink.
- 2026-10-07: etapa 2 escrita (sin commitear): `balance_energia.py` +
  callback desde `registro_energia.py` + claves nuevas en `energia`.
  Probada en la PC (20 chequeos: conteo de Ah, cierre de hora y resumen en
  la cola, cambio de día local, reinicio y hueco con el estado de disco,
  float, minuto basura, límites, promedios, autonomía, estado corrupto).
  La hora se cierra con el primer minuto de la hora siguiente (sin datos
  del ESP32, la última hora queda abierta hasta que vuelvan).

- 2026-10-07 17:11-17:22 UTC: **prueba de punta a punta de la etapa 2 en la
  placa de pruebas, OK.** Simulador ESP32 + `publicar_losant.py` de la rama
  con el reloj del registro adelantado 45 min (17:12 real = 17:57
  simulado) para cruzar una hora en punto sin esperar. CSV de 17 y 18 con
  las filas esperadas (hueco en 18:00-18:01); al llegar el minuto 18:02 se
  cerró la hora 17 y el cartero mandó `1791392400000.energia.json`
  (17:00 UTC) a `test_SC`: SOC 49,9 %, restante 574 Wh, autonomía 76,5 h
  sin Starlink / 1,66 días con Starlink, 3 minutos, 27,4 W, -1,0 Wh,
  13,0 V. Reprocesar las mismas filas en la PC da el mismo SOC final que
  la placa (49,815 Ah). Estado y CSV de la prueba movidos a
  `/root/prueba_energia/` (la placa de pruebas queda sin estado de balance).
