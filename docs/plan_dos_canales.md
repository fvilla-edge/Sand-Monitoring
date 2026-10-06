# Plan — modo evento con 2 canales (IN1 + IN2 de referencia)

Estado: **plan, sin implementar** (2026-10-05). Todo se prueba en la placa de
pruebas (`rp-f0fd8c`); la placa de campo (`rp-f0fbda`) no se toca hasta cerrar
las pruebas de lab y decidir cuándo desplegar.

## Qué se quiere

- Poder correr el modo evento en **mono** (solo IN1, como hoy) o **dual**
  (IN1 + IN2), elegido por configuración.
- **IN2 = sensor de referencia** (ruido de línea). En campo está conectado pero
  hoy no se usa.
- **Opción A** (decidida): la FPGA sigue calculando área/kurtosis **solo del
  IN1**; el IN1 es el único que dispara eventos. En dual, cada evento guarda
  además la cruda del IN2 en el mismo tramo de tiempo, para comparar en la PC
  (¿el pico del IN1 también está en la referencia? -> ruido de línea, no arena).
- Sin cambios de FPGA ni bitstream nuevo.

## Punto de partida (código actual)

- `scripts_campo/c/capturar_eventos.cpp`: `channel_state_2 OFF` (configuración
  del server) y el callback solo lee `p.channel1`. La API del vendor entrega
  `p.channel2` si el canal está encendido.
- `--dec` existe en el C++ y en el lanzador, pero **solo funciona bien con 32**:
  el programa abre los registros de la FPGA en solo lectura y nunca escribe
  - `AREA_WINDOW_SAMPLES` (0x40000328): default 195312 del bitstream = 50ms a
    dec32. A dec64 la FPGA haría ventanas de **100ms** mientras el C++ asume
    97656 muestras -> eventos recortados mal.
  - coeficientes del pasabanda (0x40000300-0x324, 2 biquads): defaults
    calculados para fs = 3.906MHz. A dec64 (fs = 1.953MHz) la banda se corre a
    **~25-200kHz** en vez de 50-400kHz.
  Los dos son registros R/W de la FPGA, así que se arregla por software.

## Decimación configurable (independiente de mono/dual)

`--dec` (y `DEC=` en la unit) queda como parámetro propio, separado de
`--canales`. Mono puede seguir a 32 aunque dual termine en 64.

Lo que el programa hace al arrancar según `dec`:

1. Escribe `AREA_WINDOW_SAMPLES = round(125e6/dec × 0.05)` y verifica que se
   leyó lo mismo.
2. Escribe los coeficientes del pasabanda calculados para `fs = 125e6/dec`
   (Butterworth 50-400kHz, misma cuantización que el bitstream; tabla
   precalculada en la PC para las decimaciones permitidas, no scipy en la
   placa).
3. Solo acepta decimaciones con tabla (32 y 64 al principio); otra -> error.
4. Anota `dec` y `fs` en el `.json` de cada evento y en el encabezado/log del
   CSV (para no mezclar corridas en la PC).

Ojo, **a dec64 la medición no es comparable con dec32 sin recalibrar**:

- El umbral 3.4 se eligió a dec32; la kurtosis cambia con el ancho de banda y
  la cantidad de muestras por ventana. Re-medir el reposo del banco (HV) a
  dec64 antes de usar el mismo umbral.
- `ESCALA_FPGA_DEFAULT` / `PISO_FPGA_DEFAULT` de `reconstruir_senal.py` están
  medidos a dec32: re-medir a dec64.
- El área (suma |x| / fs) es comparable en unidades, pero el piso de ruido no.

## Fases

### Fase 0 — ¿aguanta dual a dec32? (medir antes de programar todo)

- C++ mínimo: `--canales 2` enciende el IN2 (`channel_state_2 ON`,
  `channel_attenuator_2 A_1_20`, igual que en `capturar_stream.py`) y cuenta
  paquetes, muestras y `fpgaLost` **por canal** en la línea `ESTADO`. Todavía
  no guarda el IN2.
- Corrida en la placa de pruebas: dual dec32, umbral 3.4, a `/mnt/usb`, sin
  DAC, jumper HV, 15 min (tipo HV15) y después 90 min (tipo L1).
- Criterio: 0 ventanas saltadas y ~100% de muestras en los dos canales, CPU y
  RAM planas. Si pasa -> dual queda en dec32. Si pierde de forma sostenida ->
  Fase 1b y dual en dec64.
- Antes: `systemctl stop modo-evento` (un solo cliente por server).

### Fase 1 — C++: guardar el IN2

- Segundo buffer circular para el IN2, con el **mismo índice de muestra** que
  el IN1 (llegan en el mismo paquete). Pérdidas/huecos por canal.
- Por cada evento: `evento_..._wcNNN.bin` (IN1, igual que hoy) +
  `evento_..._wcNNN_ch2.bin` (IN2, mismo tramo, mismo largo). Archivo aparte
  para que las herramientas actuales sigan leyendo el `.bin` sin cambios.
- `.json`: `canales` (1/2), `dec`, `fs_hz`, `con_hueco_ch2`.
- En mono, todo igual que hoy (mismos archivos y campos; `canales: 1`).
- Disco: en dual cada evento ~1MB (doble). Mismo control de espacio libre; el
  `.bin` y el `_ch2.bin` se escriben o se descartan juntos.
- PASE2 en dual duplica los MB/s del peor caso -> repetirlo (Fase 4).

### Fase 1b — decimación configurable (si dec32 dual no aguanta, o igual)

Lo de "Decimación configurable" arriba. Conviene hacerlo de todas formas:
hoy `--dec 64` está roto en silencio.

### Fase 2 — elegir mono/dual (y dec) en la operación

- `Environment=CANALES=1|2` y `Environment=DEC=32|64` en
  `modo-evento.service` (drop-in, igual que `UMBRAL`); `--canales` en
  `capturar_eventos.py`.
- Cambiar = reiniciar el servicio (hueco conocido de ~74s en el CSV). No se
  cambia en caliente: el server recibe la configuración de canales al conectar.
- Opcional: comando desde Losant que cambie el drop-in y reinicie, con el
  mismo esquema de `cambiar_modo.sh` (unidad transitoria, resistente a cortes
  de Starlink, rechaza dos cambios a la vez).
- `resumen_modo_evento.py`: mandar `me_canales` y `me_dec` a Losant.

### Fase 3 — PC

- `reconstruir_senal.py`, `verificar_etapaB.py`, visores: leer `_ch2.bin` si
  existe; usar `dec`/`fs_hz` del `.json` en vez de asumir dec32.
- Vista comparativa IN1 vs IN2 por evento (para ver si un pico es de línea).
- `ventanas_a_paquete.py`: sin cambios en la opción A (el CSV sigue siendo
  del IN1); solo respetar el `dec` si cambia la duración de ventana (no
  cambia: siempre 50ms).

### Fase 4 — pruebas de banco (placa de pruebas)

| Prueba | Para qué |
|---|---|
| Loopback OUT1->IN1 y OUT2->IN2 con señales distintas | que los canales no se crucen y queden alineados (mismo índice) |
| Tramo real por OUT1 + ruido por OUT2 | eventos con `_ch2.bin` coherente |
| HV15 y L1 en dual | 0 saltadas, pérdidas por canal, CPU/RAM |
| PASE2 en dual (umbral 1 a `/mnt/usb`) | peor caso de escritura, ~doble MB/s |
| Espacio (disco chico) en dual | pausa de cruda / fallidos sin archivos sueltos |
| Mono después de dual (y al revés) con el supervisor | que mono quede idéntico a hoy |
| Si se usa dec64: reposo HV 15 min a dec64 | nuevo umbral / piso |

Al terminar: jumper de IN1 (e IN2) en **HV**, como en campo.

### Fase 5 — campo (más adelante)

Recién cuando las pruebas de lab cierren y se decida la fecha. Cada cambio
se anota en `scripts_campo/plan_campo/actualizar_placa_campo.md` al hacerlo.
Antes de pasar campo a dual: confirmar físicamente qué hay en el IN2 de campo
y su jumper.

## Decisiones tomadas

- IN2 = referencia; opción A (sin FPGA).
- Probar dual primero a dec32; si no aguanta, dec64 para dual.
- Decimación configurable aparte de los canales (mono no queda atado a 64).

## Bitácora

- 2026-10-05: plan escrito. Hallado que `--dec` distinto de 32 no ajusta la
  ventana ni el pasabanda de la FPGA.
- 2026-10-05: Fase 0, código listo en la rama `dos-canales` (sin commitear):
  `--canales 1|2` en `capturar_eventos.cpp` y `capturar_eventos.py`. Con 2
  enciende el IN2 (A_1_20) y la línea `ESTADO` agrega
  `IN2: muestras=% perdidas_fpga=+ raw_max=`; al final, totales del IN2.
  Compilado en `rp-f0fd8c` sin warnings (respaldos `/root/*.bak_fase0`). Script
  de prueba en la placa: `/root/prueba_eth0/fase0_dual.sh NOMBRE SEGUNDOS
  [CANALES] [DEC]` (para modo-evento, mide en `/mnt/usb/fase0_NOMBRE`, log en
  `/root/prueba_eth0/fase0_NOMBRE.log`, rearranca modo-evento al terminar).
  Todavía sin correr.
- 2026-10-05 Fase 0, corridas dual dec32 (rp-f0fd8c, umbral 3.4, a `/mnt/usb`,
  sin DAC):
  - `humo` 120s: 100% ambos canales, 0 saltadas.
  - `D15` 900s (20:01-20:16 UTC): 18000 ventanas, **0 saltadas**, 0 eventos
    perdidos, 1 evento (kurt 3.79), recalibraciones 0. Muestras 99.7-100.2% por
    línea en los dos canales; fpgaLost 259968 (0.0074%, igual en IN1 e IN2: se
    pierden juntos). Referencia mono del mismo día (8h): 0.0007%, o sea dual
    pierde ~10x más pero sigue siendo despreciable.
  - Deriva (atraso de entrega) máx. 341796 muestras (~87ms) en dual vs 120604
    (~31ms) en 8h de mono. Cubierto por el buffer de ~300ms, pero es lo que
    hay que vigilar (si llega a ~300ms se pierden eventos).
  - Ruido de base IN2 raw_max ~350-390 vs IN1 ~140 (en el lab, sin saber qué
    hay físicamente en el IN2).
  - `D90` 5400s (20:17-21:47 UTC): 107999 ventanas, **0 saltadas**, 0 eventos
    (lab sin señal: no prueba escritura), recalibraciones 0, salida 0.
    fpgaLost 529420 de 2.11e10 (0.0025%, igual IN1/IN2, en 56 de 539 líneas).
    Deriva máx. 306600 muestras (~78ms) contra ~300ms de buffer.
    **Dual dec32 aguanta en reposo -> no hace falta dec64 para dual.**
- 2026-10-06: Fase 1 en la rama `dos-canales` (sin commitear): segundo buffer
  circular del IN2, escrito ANTES que el IN1 en el callback (si la ventana del
  IN1 está completa, la del IN2 también). Por evento: `.bin` (IN1) +
  `_ch2.bin` (IN2, mismo tramo y largo); `.json` con `dec` y `canales` siempre
  y, en dual, `archivo_ch2` (null si no se pudo sacar) y `con_hueco_ch2`. Si
  algo falla al escribir se borran los tres juntos. ESTADO del IN2 agrega
  `desfase` (paquetes con distinto largo/pérdidas entre canales) y `sin_ch2`.
  Compilado sin warnings en `rp-f0fd8c:/root/staging_fase1/` (modo-evento
  sigue con el binario de la Fase 0).
  - `P1` (`/root/prueba_eth0/fase1_pulsos.sh`): 30 pulsos por loopback
    digital DAC->IN1, dual y después mono. Dual: 31 eventos, 31 `_ch2.bin`,
    desfase 0, sin_ch2 0, fallidos 0. IN1 con el pulso saturado (32765) dentro
    de la ventana; IN2 solo ruido (std ~35, máx ~160-190, sin pulso): **los
    canales no se cruzan**. Mono: 31 eventos sin `_ch2.bin`, `.json` igual
    que antes más `dec` y `canales: 1`.
  - **Dual + DAC pierde 7-29% de muestras** (fpgaLost, del lado del server,
    igual en ambos canales; mono + DAC 0.2%, dual sin DAC 0.0025%). El stream
    de bajada al DAC compite. En campo no hay DAC; sí afecta la prueba de
    Fase 4 "tramo real por OUT1" en dual (corta, aceptar huecos o generador
    externo).
  - Escritura sostenida sin DAC (`fase1_dual.sh NOMBRE SEG UMBRAL [CAN]`),
    umbral 3.01 (≈1 evento/s con el ruido del lab, ≈3x el pico de campo de
    1275/h), 900s cada una, binario de staging:

    | | eventos | a disco | pérdidas | saltadas | deriva máx. |
    |---|---|---|---|---|---|
    | `M15` mono | 1290 | 682MB | 0.014% | 1 | ~72ms |
    | `W15` dual | 1052 | 1.1GB | 0.12% | 5 | ~116ms |

    W15: 1052 `.json` = 1052 `_ch2.bin`, todos con el largo correcto y
    `archivo_ch2` bien; 0 fallidos, 0 eventos perdidos, desfase 0, sin_ch2 0;
    10 con hueco (los mismos en IN1 e IN2). Saltadas y ráfagas de pérdida
    (0.4-1M muestras) juntas en los últimos 4 min: mismo mecanismo que PASE2
    (vaciado de páginas sucias al USB). Dual escribe ~1.6x bytes y pierde ~8x
    más que mono a igual umbral; sigue lejos del buffer (~300ms) y a ~1/3 del
    ritmo de esta prueba en el peor caso de campo.
  - Disco lleno en dual (`fase1_lleno.sh`, destino tmpfs de 12MB):
    `L1` A sin control: 11 tríos completos, 79 fallidos (`No space left`),
    **0 archivos sueltos ni tríos incompletos**, medición siguió.
    `L1` B (pausa con mínimo 6MB): SIGSEGV del vendor al arrancar
    (`Operation aborted`, antes de cualquier evento), con el server relanzado
    ~4s después del anterior -> script corregido a 60s entre corridas.
    `L2` B repetida: pausa a los 6s, 8 tríos completos, 60
    `no_guardados_por_espacio`, 0 fallidos, 0 saltadas.
  - 12:44 UTC: binario + cpp + py instalados en el modo-evento de lab
    (respaldo `/root/respaldo_fase1_20261006/`). Arranca mono por el
    supervisor igual que antes (umbral 3.40, 100% muestras, 0 saltadas).
  - Nota del usuario: antes, en dual, se medía a dec64 por pérdidas. Eso era
    con la cadena Python (`capturar_stream.py`, 1.4-9% de pérdida en las
    sesiones del 16/9); con el C++ dual dec32 pierde 0.0025% en reposo y 0.12%
    escribiendo 1 evento/s.
