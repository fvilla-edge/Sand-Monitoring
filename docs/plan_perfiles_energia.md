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

Al cerrar cada hora, un resumen con su hora original va a la cola de
pendientes (mismo mecanismo que los resúmenes del modo evento,
`_enviar_pendientes`), así Losant recibe también la noche.

| Variable | Cálculo |
|---|---|
| `p_carga_w` (prom/máx) | carga × V |
| `p_pv_w` | `solar_power` |
| `e_carga_wh`, `e_pv_wh`, `e_bat_wh` | Σ P·Δt de la hora |
| `balance_dia_wh` | Σ `e_bat_wh` del día local |
| `soc_pct` | conteo de Ah sobre la capacidad; vuelve a 100 % al entrar en float |
| `energia_restante_wh` | SOC × capacidad útil |
| `autonomia_h_con_sl`, `autonomia_h_sin_sl` | energía restante / carga promedio con y sin Starlink (últimos días) |
| `capacidad_util_wh` | arranca en 1150 Wh (supuesto: 90 % de 1280); se corrige con los Ah descargados entre un float y un corte real de LOAD |
| `cortes_load` | hueco en el registro + primera lectura al volver |

El SOC se guarda en disco (con `fsync`) para sobrevivir reinicios; después
de un corte de LOAD arranca en "desconocido" hasta el próximo float, y
mientras tanto se usa una cota por tensión.

## Etapa 3 — Medir lo que falta (antes de fijar umbrales)

1. Carga de noche (sin Starlink): sale sola de la etapa 1.
2. **Costo de un encendido de Starlink**: tiempo desde el pulso del relé
   hasta la primera conexión a Losant, y Wh del arranque (picos de
   40–60 W). Define si conviene prender seguido y poco o pocas veces y más
   tiempo.
3. Tiempo para vaciar lo pendiente: hoy los resúmenes salen de a uno por
   segundo (`PENDIENTES_INTERVALO_S = 1`); un día de resúmenes del modo
   evento por minuto (1440) tarda ~24 min. Más el subir CSV a GCS.

## Etapa 4 — Perfiles

- Nivel calculado con la energía restante (variable principal), la
  tendencia (balance de las últimas 24 h) y una cota por tensión como
  respaldo (el SOC deriva si pasan días sin float).
- Niveles propuestos, umbrales a definir con los datos de las etapas 1–3:

| Nivel | Starlink | Captura |
|---|---|---|
| Normal | horario actual | normal |
| Ahorro | ventanas cortas N veces por día (vaciar pendientes y apagar) | normal |
| Crítico | una ventana corta por día | normal |
| Supervivencia | apagada | normal (o mono, a decidir) |

- Se integra en `starlink_remoto/decidir_objetivo.sh` como una capa más,
  por debajo del modo manual y del rescate, y sin tocar la regla de "reloj
  no confiable → on".
- Histéresis entre niveles, para no alternar en cada hora.
- El nivel, la autonomía y el motivo de cada decisión van a Losant.

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
  partida USB/SD, nada dos veces, corte de red y recuperación). Falta una
  subida real a GCS desde la placa de pruebas.

