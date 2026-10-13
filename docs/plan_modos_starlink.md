# Plan — Modos de operación de Starlink (ventana / permanente)

Creado 2026-10-09. Estado: **plan, sin código**. Rama `modos-starlink`, sale
de `comando-starlink` (`2a34d88` = `main` 52df573 + comando Losant
`starlink {"accion":"off"}`, que se mantiene "por las dudas").

Va **antes** que los perfiles de energía (`docs/plan_perfiles_energia.md`,
etapa 4): es un pre-paso más simple, sin mirar la batería.

## Por qué

La placa de campo se volvió a apagar por tensión (6/10 y de nuevo después
del 8/10). Con Starlink prendida 08:55-17:15 todos los días el consumo es
~400 Wh/día y el panel de 120 W no lo repone en días nublados (8/10: 20 Wh
de generación en todo el día).

Cuentas con los valores de diseño ya aprobados (Starlink +25 W, 2 Wh y
5 min por encendido; base 180-220 Wh/día que no cambia porque la captura
sigue 24 h):

| Starlink | Wh/día Starlink | Total aprox. |
|---|---|---|
| Horario actual (8 h 20 min) | ~210 | ~400 |
| Ventana cada 2 h (~10 min c/u) | ~50 | ~250 |

La duración real de cada ventana es una suposición (~5 min de arranque +
~5 min de subida): se mide en el lab (Fase 6). Con ~1150 Wh útiles, un
día de 20 Wh sigue siendo déficit (~230 Wh): el modo ventana estira la
autonomía de ~3 a ~4-5 días sin sol, **no la vuelve infinita**.

## Decisiones (usuario + jefe, 2026-10-09)

1. Dos modos, elegidos desde Losant: **ventana** y **permanente**. El
   horario 08:55/17:15 deja de existir.
2. **Ventana:** Starlink prende cada **2 h fijas**, alineada al reloj, a los
   **:05 de las horas pares** (hora local, igual que los timers de hoy).
   Transmite lo pendiente y se apaga. Corre las 24 h.
3. **Un intento por ventana:** espera internet hasta 15 min, intenta subir
   una vez y apaga, haya subido o no. Lo que falla queda para la próxima.
   No hay otro tope de duración.
4. "Lo pendiente" = los CSV horarios a GCS: ventanas (kurtosis/área) y
   energía, ~4 por ventana (2 horas × 2 tipos).
5. **Permanente:** Starlink prendida las 24 h, sin vencimiento automático
   (no se sabe cuánto van a trabajar). Sin piso de batería: eso llega con
   los perfiles.
6. **Losant:** solo en vivo. Lo que se informa sale mientras hay conexión o
   se pierde; nada se guarda para mandar después. Misma regla en los dos
   modos (en permanente informa todo el día como hoy; en ventana, solo
   esos minutos).
7. La placa informa en Losant en qué modo quedó (`sl_modo`).
8. Si nunca pudo leer el modo de Losant, usa el de `config_campo.json`
   (`ventana`).
9. Se mantienen: rescate de 24 h del manual "off", "reloj no confiable =>
   prender", `starlink_manual.sh on|off|auto` y el comando `starlink` "off".
10. Atraso de GCS (lo decidí yo, a pedido): dentro de una ventana se sube
    sin el cupo de 2 por corrida, hasta **24 CSV de ventanas** (un día) más
    todos los de energía; `gcs.dias_atras` pasa de 7 a 30.

Revisión del plan con el usuario (2026-10-13):

11. Losant elige el modo con **tag del Device + workflow** (Fase 0).
12. Informes en vivo cada **15 min** (`panel_solar.informe_intervalo_min`
    no cambia).
13. **Ventana al arrancar la placa:** sí.
14. **Se elimina la cola** de Losant (`losant_pendientes`). Al conectar
    se publica solo el **último** resumen de energía (`en_*`) y el
    último del modo evento: es el estado actual, no una cola.
15. **Firmware de la antena:** si la antena informa una actualización en
    curso, la ventana se extiende hasta un tope antes de apagar.
16. Un manual `on` en modo ventana dura **hasta la próxima ventana** (se
    autolimpia ahí). Para más tiempo está el modo permanente.
17. Espera de un comando de modo: **120 s** desde que hay internet.
18. El último resumen se publica con su **hora original**. Los huecos de
    2 h en Losant no importan: el backend futuro va a usar los datos de
    GCS, no los de Losant.

## Cómo queda (resumen)

```
cada 2 h, :05 ──> abrir ventana ──> rele ON ──> ¿internet? (hasta 15 min)
                                                   │ sí            │ no
                                                   v               │
                                     subir GCS (1 intento)         │
                                     + Losant: sl_modo / comando   │
                                                   v               v
                                              cerrar ventana ──> rele OFF
                                              (salvo modo permanente)
```

La placa siempre decide con lo que tiene guardado. Losant solo cambia
el modo guardado.

## Fase 0 — Verificar Losant (antes de escribir código)

Lo que dicen los docs de Losant (a confirmar en la cuenta real):

- El disparador "Device: Connect" existe, y el nodo "Device: Command" manda
  un comando a un device **conectado**. Un comando mandado con la placa
  desconectada **no se guarda** ni se entrega al reconectar.
- Riesgo de carrera: justo al conectar la placa puede no estar suscripta
  todavía a los comandos, y el comando se pierde sin error.

Diseño propuesto para esquivar la carrera y los bucles:

- El modo deseado vive en un **tag del Device** (`modo_starlink` =
  `ventana` | `permanente`), editable desde la página del Device. No hace
  falta dashboard.
- El disparador del workflow es el **estado** que manda la placa, no la
  conexión: al conectar (ya suscripta) la placa publica `sl_modo`. El
  workflow compara `sl_modo` con el tag y **solo si difieren** manda el
  comando `modo {"modo": "<tag>"}`. Si coinciden no hace nada => no hay
  bucle.
- Un cambio de tag con la placa conectada (modo permanente) se aplica a
  la próxima publicación de `sl_modo`: la placa la repite cada
  `panel_solar.informe_intervalo_min` (15 min) mientras está conectada.

Hay que probarlo con el Device de pruebas `test_SC` antes de cerrar la
Fase 4. **Quién crea el workflow y el tag: el usuario** (yo no tengo acceso
a la cuenta).

### Resultado (2026-10-13, workflow "test sc" en `test_SC`) — CERRADA

Workflow que funciona:

```
Device: State (test_SC) ──> Conditional 1 ──true──> Conditional 2 ──true──> Device: Command
                                 │ false                 │ false              (modo)
                              (nada)                  Debug
```

- **Conditional 1:** `{{data.sl_modo}} == 'ventana' || {{data.sl_modo}} == 'permanente'`
- **Conditional 2:** `({{deviceTags.modo_starlink.[0]}} == 'ventana' || {{deviceTags.modo_starlink.[0]}} == 'permanente') && {{deviceTags.modo_starlink.[0]}} != {{data.sl_modo}}`
- **Device: Command:** nombre `modo`, payload `{"modo": "{{deviceTags.modo_starlink.[0]}}"}`.

Lo que se aprendió (no repetir):

1. En el Conditional las plantillas se insertan **con comillas** (como
   JSON): se escriben `{{data.sl_modo}} == 'x'`, **sin** comillas
   simples alrededor. Con `'{{...}}'` da false siempre.
2. El disparador ya trae los tags del Device en `deviceTags`
   (`modo_starlink` es una lista: `.[0]`). No hace falta Device: Get (con
   `{{deviceId}}` devolvía null; el id del Device viene en `triggerId`).
3. El filtro "Allowed Attributes: Only the following… sl_modo" del
   disparador **no frena** los demás informes de la placa (resúmenes por
   minuto, estado, espacio). Por eso el Conditional 1 va aparte.
4. Con una sola expresión larga, los informes **sin** `sl_modo` daban
   true y mandaban el comando cada minuto. Separada en dos Conditionals,
   no (4 resúmenes seguidos sin comando).
5. Un estado escrito por un nodo Device: State de otro workflow (botón de
   prueba) **sí** vuelve a disparar el Device: State.

Pruebas hechas (journal del lab, `Comando desconocido ignorado:
nombre='modo' payload={'modo': 'ventana'}`):

| Caso | Resultado |
|---|---|
| tag `ventana`, `sl_modo` = `permanente` | comando `modo {"modo": "ventana"}` llega |
| tag `ventana`, `sl_modo` = `ventana` | nada |
| tag `Permanente` (mal escrito) | nada |
| informes de la placa sin `sl_modo` | nada |

Pendiente para campo: el Device: Command apunta fijo a `test_SC`; en el
Device de campo, otro workflow igual (o `{{triggerId}}` si se usa uno
solo para varios Devices).

Consecuencia para la placa (Fase 4): publicar `sl_modo` siempre con un
valor válido (`ventana` | `permanente`); otro valor no dispara nada.

## Fase 1 — El modo vive en la placa

- Archivo persistente `/root/starlink_remoto/modo_operacion` (`ventana` o
  `permanente`, con `sync` al escribir, igual que `modo_manual`).
- Si no existe o es inválido => `starlink.modo_defecto` del config.
- Config (`config_campo.json`, sección `starlink`):
  - `modo_defecto`: `"ventana"`
  - `ventana_cada_h`: `2` (fijo por ahora; queda como parámetro)
  - `ventana_minuto`: `5`
  - `ventana_espera_internet_min`: `15`
  - `ventana_espera_losant_s`: `120` (tiempo para que llegue un comando de
    modo antes de apagar)
  - `ventana_extension_update_min`: `30` (tope extra si la antena está
    actualizando firmware; valor a revisar con la Fase 6)
  - `hora_on`, `hora_off`, `dias_habilitados` **se quedan por ahora**:
    además de los timers, el balance de energía usa `hora_on`/`hora_off`
    para las horas de Starlink por día (`publicar_losant.py` =>
    `horas_starlink`, autonomías). Se resuelve en la Fase 2.
- `gcs.dias_atras`: 7 => 30. **Ojo:** `fusionar_config.py` solo agrega
  claves nuevas, no pisa valores: en el lab y en campo hay que cambiarlo a
  mano al instalar (Fase 7).
- Hecho (2026-10-13): `starlink_remoto/modo_operacion.sh` (sin argumento
  imprime el modo vigente; `ventana|permanente` lo guarda con `sync`,
  escritura atómica) + claves en el config. No cambia ningún
  comportamiento: nadie lee el modo hasta la Fase 2. Prueba en la PC
  13/13; en el lab rp-f0fd8c 8/8 (respaldo
  `/root/respaldo_modos_fase1_20261013`, claves agregadas con
  `fusionar_config.py`, `dias_atras` quedó en 7 como se esperaba).

## Fase 2 — La decisión del relé (`decidir_objetivo.sh`)

Prioridad nueva, de mayor a menor (lo de arriba no cambia):

0. Rescate del manual "off" vencido (24 h) => `on`.
1. Manual `on`/`off` (`starlink_manual.sh`, comando `starlink`).
   Autolimpieza igual que hoy: se borra cuando coincide con lo que diría
   el modo.
2. Reloj no confiable => `on`.
3. Modo **permanente** => `on`.
4. Modo **ventana** => `on` si hay una ventana abierta
   (`/run/starlink_ventana`), `off` si no.

Cambios alrededor:

- Se borran `starlink-rele-on.timer` y `starlink-rele-off.timer`.
- Nuevo `starlink-ventana.timer` (`OnCalendar=*-*-* 00/2:05:00
  America/Argentina/Buenos_Aires`) => `starlink-ventana.service` (oneshot,
  Fase 3). En modo permanente el servicio no hace nada.
- El reconciliador (cada 5 min) sigue igual: lee la misma decisión, así
  que respeta la ventana abierta.
- **Hecho (2026-10-13), solo la decisión:** `decidir_objetivo.sh` con la
  prioridad nueva + `modo_operacion_common.sh` (lectura del modo
  compartida, para no sumar otra llamada a python3 cada 5 min). Una marca
  de ventana más vieja que `ventana_cada_h` se ignora (ventana muerta sin
  cerrar). Prueba 26/26 en la PC y en el lab (copia aislada en
  `/root/prueba_modos_fase2`; el script instalado NO se tocó: con el
  defecto ventana y sin timer de ventana apagaría la Starlink del lab).
- **Pasa a la Fase 3** (van juntos o la placa queda sin Starlink): borrar
  los timers `rele-on/off`, `aplicar_horario.sh`, el timer nuevo, el
  instalador (`aplicar_actualizacion.sh`: `TIMERS_STARLINK`) y los docs
  (COMANDOS, GUIA_USO_BASICO, DESPLIEGUE, setup_placa, README).
- Al arrancar la placa se abre una ventana (decisión 13): después de un
  corte de energía la placa avisa que volvió sin esperar hasta 2 h.
  Costo ~2 Wh por arranque; si la batería está al límite, el pico de la
  Starlink puede volver a tirarla (aceptado).

## Fase 3 — Una ventana (`ventana_starlink.sh`, nuevo)

1. Si el modo es permanente: salir.
2. Crear `/run/starlink_ventana` (con hora de apertura) y aplicar objetivo
   => relé `on`.
3. Esperar internet hasta `ventana_espera_internet_min` (prueba liviana
   cada 30 s contra el host de GCS). Si no llega: ir al paso 6.
4. Subida GCS, **un intento**: `subir_csv_gcs.py --ventana` (sin cupo de 2,
   hasta 24 ventanas + todas las de energía, misma pausa y gzip 1 que hoy
   para no afectar la captura).
5. Losant: en paralelo con la subida, `panel-solar-informe` conecta y
   publica `sl_modo`. Esperar hasta `ventana_espera_losant_s` desde que
   hay internet, por si llega un comando de modo.
6. Firmware (decisión 15): antes de apagar, leer `softwareUpdateState`
   de la antena (ya lo leemos por grpcurl en
   `starlink_api/starlink_get_location.py`). Si no es `IDLE`, seguir
   esperando, consultando cada 30 s, hasta `ventana_extension_update_min`.
   Qué valores toma durante una actualización real (y si conviene esperar
   también al reinicio posterior) no lo sabemos: se mira en la Fase 6.
7. Borrar `/run/starlink_ventana` y aplicar objetivo => relé `off` (salvo
   que el modo haya pasado a permanente en el paso 5).
8. Una línea en `/root/logs_campo/ventanas_starlink.log`: apertura,
   segundos hasta internet, archivos subidos/fallidos, extensión por
   firmware (si hubo), cierre. Solo local, no va a Losant.

Detalles:

- `subir_csv_gcs.py` toma un `flock`: el timer de cada 5 min sigue
  existiendo (en permanente es el que sube) y no tiene que pisarse con la
  ventana. Sin internet falla rápido, como hoy.
- Cambio a ventana estando en permanente: la placa guarda el modo y
  aplica el objetivo después de ~10 s (como el comando "off", para que
  salga la confirmación) => Starlink se apaga hasta la próxima ventana.
- Cambio a permanente estando en ventana: llega recién en la próxima
  ventana (hasta 2 h de demora). Es una consecuencia del diseño, no un bug.

### Resultado Fase 3a (2026-10-13)

- `starlink_remoto/ventana_starlink.sh` + `starlink-ventana.{timer,service}`
  (`OnCalendar=*-*-* 00/2:05:00 America/Argentina/Buenos_Aires` +
  `OnBootSec=3min`, sin `Persistent`) + `subir_csv_gcs.py --ventana`
  (hasta 24 de ventanas y toda la energía) con lock
  `/run/lock/subir_csv_gcs.lock` (el timer de 5 min no hace nada si está
  tomado; la ventana espera hasta 10 min).
- Firmware: el estado se pregunta con `get_status` por grpcurl; sin antena
  (lab) no hay extensión. `ESTADO_UPDATE_CMD` solo para pruebas.
- Log: una línea por ventana en `/root/logs_campo/ventanas_starlink.log`,
  con `fin=normal` o `fin=cortada` (si el proceso muere, el trap cierra la
  ventana igual).
- Instalado a mano en el lab (respaldo `/root/respaldo_modos_fase3_20261013`),
  timers `rele-on/off` deshabilitados. 11/11 pruebas con el usuario moviendo
  el cable de feedback (cable a GND = on): permanente→ventana, ventana
  completa, reconciliador durante la ventana, `systemctl stop` en el medio,
  manual on/off, marca vieja/basura, permanente durante la ventana, lock de
  GCS, 24 vs 2 en `--seco` (315 pendientes reales), ventana cortada en el
  log, reinicio (ventana de arranque a +3 min), timer con hora local
  (transitorio 14:36 local => 17:36 UTC).
- Lab sin RTC: al arrancar, antes de NTP, la verificación del boot pide "on"
  (reloj no confiable). Esperado; en campo hay RTC.
- Sube primero los CSV más viejos: 12 ventanas × 24 = 288/día contra 24
  generados, un atraso de días se pone al día en uno o dos.

## Fase 4 — Losant (placa)

En `publicar_losant.py`:

- Comando nuevo `modo {"modo": "ventana" | "permanente"}`: valida, escribe
  `modo_operacion`, publica `sl_modo` y aplica objetivo (Fase 3).
  Cualquier otro valor se ignora con un aviso en el journal.
- `sl_modo` (String): al conectar y cada 15 min mientras haya conexión.
- Workflow y tag del lado de Losant: Fase 0.

## Fase 5 — Informes solo en vivo

Hoy (`resumen_modo_evento.py` + el "cartero" de `publicar_losant.py`) los
resúmenes por minuto se encolan en `/mnt/usb/losant_pendientes` y salen
con su hora original al reconectar. El informe del panel cada 15 min ya
es en vivo.

Cambio (decisión 14): **se elimina la cola**.

- El anotador del modo evento y el resumen horario de energía dejan de
  acumular archivos: cada uno **sobrescribe** un único archivo "último"
  en `/run` (RAM), p.ej. `/run/losant_ultimo/evento.json` y
  `/run/losant_ultimo/energia.json`.
- `publicar_losant.py` deja de ser cartero: mientras está conectado,
  publica cada "último" cuando cambia; **al conectar** publica una vez
  los dos que haya (aunque sean de hace hasta 2 h, son el estado actual).
  Se publican con su **hora original** (decisión 18): sigue siendo un
  solo mensaje, no una cola.
- Sin conexión no se guarda nada más: el resumen siguiente pisa al
  anterior. El detalle completo sigue en los CSV de GCS.

Al instalar en campo se borra `/mnt/usb/losant_pendientes`.

Sin cambios: telemetría del dish al conectar, `en_sin_lecturas_min`,
estado del equipo y espacio en disco (todos ya son en vivo).

## Fase 6 — Pruebas en la placa de pruebas (`rp-f0fd8c`)

Con el relé del lab **sin el cable a GND**, para que confirme el estado.
Pruebas que dependen de la hora: adelantar el reloj, no esperar.

1. Ventana normal: abre a los :05, internet, sube 4 CSV, cierra. Medir
   los segundos hasta internet y la duración total (=> corrige la tabla
   de energía).
2. Sin internet: abre, espera 15 min, cierra sin subir; la próxima sube
   lo pendiente.
3. Atraso: 30 CSV de ventanas pendientes => sube 24, el resto en la
   siguiente.
4. Cambio de modo por tag en `test_SC`: ventana => permanente (aplica en
   la próxima ventana) y permanente => ventana (apaga a los ~10 s).
5. Reinicio de la placa en cada modo (modo guardado, ventana al
   arrancar).
6. Manual "off" en permanente: rescate a las 24 h. Comando `starlink`
   "off" sigue andando.
7. Losant caído / workflow apagado: la placa sigue en el modo guardado.
8. Captura: sin pérdidas nuevas por las conmutaciones (12 por día en vez
   de 2) y por la subida sin cupo.
9. Al conectar llegan a `test_SC` el último `en_*` y el último resumen
   del modo evento, una sola vez; nada viejo acumulado.
10. Firmware: anotar qué `softwareUpdateState` aparece en cada ventana.
    Si en el lab no sale ninguna actualización, la extensión se prueba
    simulando el estado (no forzar una actualización real).
11. Manual `on` en ventana: se borra solo al abrir la próxima ventana.

## Fase 7 — Campo

- Cuando el usuario lo decida, con su entrada en
  `scripts_campo/plan_campo/actualizar_placa_campo.md`.
- Va por paquete (`aplicar_actualizacion.sh`): cambian units de systemd
  (timers nuevos y borrados), no alcanza con copiar archivos.
- Durante la instalación la Starlink es el único acceso: poner
  `modo_operacion = permanente` por SSH **antes** de reiniciar servicios, y
  pasar a ventana desde el tag de Losant al terminar.
- Crear en el Device de campo el atributo `sl_modo`, el tag
  `modo_starlink` y el workflow (el usuario).
- Merge a `main` y tag de campo recién después de validar en campo.
  Incluye el commit del comando `starlink` "off".

## Riesgos

- **Cambio a permanente demorado hasta 2 h** (decisión 3 + ventana): si
  hace falta entrar urgente, hay que esperar la próxima ventana.
- **El tag de Losant mal escrito** (p.ej. "Permanente "): la placa lo
  ignora y queda en su modo; el workflow vuelve a mandarlo cada 15 min
  solo mientras haya conexión. Validar el valor en el workflow.
- **Modo permanente olvidado:** sin vencimiento ni piso de batería, vacía
  la batería como esta semana. Aceptado hasta los perfiles.
- **Subida sin cupo dentro de la ventana:** el cupo de 2 se puso por
  pérdidas de muestras con gzip pesado; con gzip 1 + pausa debería
  alcanzar, se verifica en la Fase 6 (punto 8).
- **Firmware cortado:** si la antena no informa bien que está
  actualizando, el relé la puede apagar a la mitad. No sabemos qué tan
  tolerante es; se observa en la Fase 6.
- **Base de 180-220 Wh/día:** este plan no la toca. Sigue abierto el
  aumento de ~4 W desde el 17/9.

## Bitácora

- 2026-10-09: plan armado con el usuario (preguntas y respuestas en la
  sesión). Sin código.
- 2026-10-13: revisión con el usuario, decisiones 11-17 (tag + workflow,
  15 min, ventana al arrancar, sin cola + último al conectar, extensión
  por firmware, manual `on` hasta la ventana, 120 s) y 18 (hora
  original; huecos en Losant aceptados, GCS es la fuente). Sin código.
- 2026-10-13: Fase 0 cerrada en `test_SC` (workflow con dos Conditionals,
  ver "Resultado" en la Fase 0). Sin código en la placa.
- 2026-10-13: Fases 1, 2 y 3a hechas y probadas en el lab (11/11).
