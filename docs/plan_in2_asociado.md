# Plan: IN2 asociado al IN1

Estado: **plan, sin código** (2026-10-15). Rama `integracion-campo`.

## Qué es

Hoy, en dual, el IN2 es un sensor **independiente** (`docs/plan_in2_independiente.md`):
graba su cruda cuando **su** kurtosis cruza **su** umbral. Se agrega un segundo
modo, **asociado**: el IN2 graba su cruda **solo cuando graba el IN1**, el mismo
tramo de tiempo; si el IN1 no graba, el IN2 no graba aunque vea algo.

Decisiones del usuario (2026-10-15):

1. En asociado el IN2 **sigue** con su CSV por ventana y los `_in2` en Losant;
   solo cambia qué dispara la grabación de su cruda.
2. La cruda del IN2 asociado va en `<destino>/in2/`, **con el mismo nombre**
   que el evento del IN1 (se emparejan por nombre).
3. El modo se elige en el config (`modo_evento.in2_modo`) **y** por Losant
   (comando `canales`), con el mismo mecanismo seguro que mono/dual.
4. Por defecto: **independiente** (lo de hoy no cambia).

## Diseño

### `capturar_eventos.cpp`

- Flag nuevo `--in2-modo independiente|asociado` (default `independiente`;
  sin `--canales 2` no hace nada).
- Asociado: cuando una ventana del IN1 cruza el umbral, se encola la **misma
  ventana** (mismo `wc`) en los pendientes del IN2. El IN2 deja de encolar por
  su propia kurtosis. El resto (buffer, extracción, escritor, margen) es el
  mismo camino que hoy: mismo `idx_ini`, así que el tramo es idéntico.
- **Nombre:** hoy `nuevo_evento()` toma la hora al escribir, así que IN1 e IN2
  quedarían con nombres distintos. Se fija el nombre (`base` e `iso`) **al
  detectar** y viaja en el pendiente; los dos eventos usan el mismo.
- JSON del evento del IN2: `"canal": "IN2"`, `"disparo": "IN1"` (campo nuevo;
  en independiente `"disparo": "IN2"`, y en los del IN1 `"disparo": "IN1"`),
  `area`/`kurtosis` = los **del IN2** en esa ventana.
- **Con el bitstream viejo** (sin cálculo del IN2): asociado igual graba la
  cruda del IN2 (el stream trae los dos canales), pero sin área/kurtosis del
  IN2 (`null` en el JSON) y sin CSV del IN2. Independiente sigue como hoy
  (mide solo el IN1).
- Si la cruda del IN1 no se pudo guardar (espacio, buffer pisado), el IN2
  asociado sigue su propio resultado: puede quedar uno sin el otro, y se
  cuenta como hoy.
- Log al arrancar: `IN2: modo asociado (graba cuando graba el IN1)`.

### Config, supervisor y cambio remoto

- `config_campo.json`: `modo_evento.in2_modo = "independiente"` (la fusión lo
  agrega en las placas que no lo tienen).
- `supervisor_eventos.sh`: lee la clave (valor inválido → independiente, con
  aviso, como `canales`), pasa `--in2-modo` y lo agrega a
  `/run/modo-evento/medicion`: `canales=2 dec=64 in2=asociado`.
- `cambiar_canales.sh`: acepta un segundo argumento opcional,
  `cambiar_canales.sh 2 asociado|independiente`; escribe las dos claves,
  reinicia y verifica que `medicion` diga las dos; si falla vuelve a las dos
  anteriores. Sin segundo argumento, el modo del IN2 no se toca.
- Losant, comando `canales`: `{"canales": 2, "in2": "asociado"}` (o
  `"independiente"`); `"in2"` opcional, cualquier otro valor se rechaza.
- `resumen_modo_evento.py`: atributo nuevo `me_in2_modo` (String) en dual.
  Crearlo en `test_SC` y en el Device de campo.

## Etapas

1. **C++** (`--in2-modo`, nombre fijado al detectar, `disparo`). Prueba en el
   lab a mano, con la captura parada y lanzando el binario con
   `--prueba-pulsos` (loopback OUT1→IN1, ya existe): cada pulso del IN1 tiene
   que dejar el par IN1/IN2 con el mismo nombre; un pulso solo en el IN2 no
   tiene que grabar nada en asociado.
2. **Config + supervisor + `cambiar_canales.sh` + resumen.** Prueba en la PC
   (resumen) y en el lab: independiente ↔ asociado por script.
3. **Comando de Losant** desde `test_SC`: `{"canales": 2, "in2": "asociado"}`,
   payload inválido rechazado, `me_in2_modo` en Losant.
4. **Rearmar el paquete** y anotarlo en `actualizar_placa_campo.md` sección 7
   (atributo `me_in2_modo`, prueba en la empresa con los dos sensores).

## Riesgos

- Los pulsos de prueba entran por el IN1 (loopback): para ver "el IN2 vio algo
  y el IN1 no" hace falta señal en el IN2 (en el lab, el ruido no cruza el
  umbral; puede que solo se pruebe con el sensor real en la empresa).
- Asociado duplica la escritura de cruda por evento (IN1 + IN2): con mucha
  arena, el doble de disco y de E/S en el mismo instante (a dec64 el dual ya
  se eligió por perder menos muestras escribiendo, plan de dos canales).

## Bitácora

- 2026-10-15: **etapa 1 (C++) hecha y probada en el lab** (binario en `/tmp`,
  captura real parada ~2 min, bitstream del IN2, dec64, pulsos por el
  loopback digital DAC→IN1: el IN2 solo tiene ruido;
  `/root/prueba_asociado.sh`):
  - asociado, 8 pulsos: 9 eventos del IN1 y 9 del IN2, los 9 con el **mismo
    nombre**; `.bin` del mismo tamaño; JSON del IN2 con `"canal": "IN2"`,
    `"disparo": "IN1"` y área/kurtosis del IN2 (~3, ruido); CSV del IN2 sigue.
  - asociado con `--umbral2 0` (el IN2 "ve algo" en todas las ventanas), 5
    pulsos: 6 y 6 — el IN2 no dispara solo.
  - independiente, 5 pulsos: 6 del IN1 y 0 del IN2 (como antes).
  - El evento de más en cada corrida es el primero (kurtosis ~15000, al
    activar el loopback), no un pulso.
  - Cambio de paso: el nombre del evento ahora se fija al detectar (antes al
    extraer la señal, unos ms después), también en el IN1.
- 2026-10-15: **etapa 2 hecha y probada**. Config `modo_evento.in2_modo`;
  supervisor (llamada aparte para no arrastrar a `canales` si falta la
  clave) pasa `--in2-modo` y escribe `in2=<modo>` en `medicion`;
  `capturar_eventos.py --in2-modo`; `cambiar_canales.sh 1|2
  [independiente|asociado]` (rechaza args de más y el modo con `1`; vuelve a
  las dos claves anteriores si falla); comando `canales` con `"in2"`
  opcional; `me_in2_modo` en el resumen; el archivo `in2` dice `si` también
  en asociado con el bitstream viejo (graba la cruda del IN2).
  - PC: resumen 10/10, comando 10/10 (válidos e inválidos), args del script.
  - Lab (instalado a mano, respaldo `/root/respaldo_in2_asociado_20261015`,
    clave agregada con `fusionar_config.py`): independiente → `me_in2_modo =
    independiente`; `2 asociado` → `ok 2 asociado` en 30 s, log "modo
    asociado", Losant `me_in2_modo = asociado` y `_in2`; `2` con asociado →
    `ok 2 asociado (ya estaba)`; `1` → `ok 1` (config conserva asociado);
    `2` → `ok 2 asociado`; `2 independiente` → `ok 2 independiente`.
  - Dos caídas del vendor al arrancar (`startStreaming` →
    `requestStopStreamingCommon`, SEGV y `length_error`/ABRT): hoy 3 de 26
    arranques, una antes de este cambio. Cada cambio de modo reinicia la
    captura: ~1 de cada 10 tarda 60 s más (systemd la relanza);
    `cambiar_canales.sh` lo tolera (espera hasta 4 min).
- 2026-10-15: **etapa 3 (Losant) OK** desde `test_SC` (atributo
  `me_in2_modo` String creado): `{"canales": 2, "in2": "asociado"}` → `ok 2
  asociado` en 30 s y `me_in2_modo = asociado` en Losant;
  `{"canales": 1, "in2": "asociado"}` → ignorado (payload inválido);
  `{"canales": 2, "in2": "independiente"}` → `ok 2 independiente`.
