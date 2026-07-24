# Historial y arquitectura — relé de Starlink

> Para instalación, comandos día a día y cómo cambiar el horario: ver `COMANDOS.md`
> (raíz del repo) → sección "Starlink / control remoto del relé". Este archivo es
> historial de decisiones, hallazgos de hardware y riesgos — no una guía de uso.

## Contexto

Fase 1: equipo en campo con el usuario presente, haciendo pruebas y validando datos.
Fase 2: equipo queda solo en el sitio. La Red Pitaya no captura todo el tiempo — arranca
y para las capturas a demanda (orden del usuario, ej. para actualizar scripts). El
acceso remoto es por SSH a la Red Pitaya vía Starlink.

Para ahorrar energía, el kit Starlink (dish + router) se energiza solo durante una
ventana horaria fija, controlada por un relé.

## Arquitectura

| Componente | Rol | Alimentación |
|---|---|---|
| Red Pitaya (la misma que corre `scripts_campo/`) | Corre los timers, controla el relé, corre las capturas cuando se le pide | Siempre encendida, fuente propia del sitio |
| Relé biestable (modulo flip-flop 12V) | Corta/habilita alimentación del kit Starlink | Pulso desde `PS_MIO10` (Red Pitaya), no necesita nivel sostenido |
| Starlink (dish + router) | Da conectividad para el SSH entrante | Detrás del relé — apagado por default |

Asunción a reconfirmar en sitio: el plan de Starlink da IP pública/gestionable, así que
el SSH entrante llega directo sin túnel intermedio (Tailscale, WireGuard, etc.). Si en
la práctica resulta ser CGNAT, este plan no alcanza y hace falta agregar esa capa.

## Por qué systemd timers

No hay `cron` instalado en esta placa (Ubuntu 24.04 mínimo, sin el paquete). Se usa
**systemd timers**, el reemplazo nativo — mismo concepto que cron, pero como parte del
propio systemd (que ya está siempre corriendo), sin instalar nada extra. `Persistent=true`
en ambos timers da recuperación automática si la placa se reinicia a mitad de ventana:
al volver, dispara el que se perdió.

El `on` además reintenta forzar la hora: reinicia `ntpsec` (que ya viene instalado en
esta placa), lo que dispara un `STEP` — corrección inmediata del reloj — en vez de
esperar el ciclo de sincronización normal, que puede tardar minutos. Esto importa
porque la placa no tiene RTC: el reloj sigue corriendo solo con el oscilador local
durante las ~16 hs sin red, así que puede llegar levemente desviado a cada ventana.

**Hallazgo histórico (2026-07-15):** la primera versión de `control_starlink.sh`
escribía en `0x40000030` pensando que era el registro del LED0. Confirmado con los
regsets oficiales de FPGA que esa dirección solo es "LED" en el bitstream **default**
(`v0.94`) — mientras `streaming-server` corre (bitstream `stream_app`), esa misma
dirección es en realidad el **factor de decimación del ADC en vivo**. Esta escritura no
prendía nada durante una captura, y en el peor caso podía pisar la decimación de una
captura activa. Esto llevó al diseño real (reprogramar a `v0.94` antes de tocar el
registro, y más adelante mover el pulso de control a `PS_MIO10`, ver sección de
migración más abajo).

## Validado en banco (placa real, sin Starlink conectado)

- `rp.rp_LEDSetState()` (propuesta inicial) **falla**: `rp_Init()` inicializa también
  el osciloscopio y choca (`Bus error`) con el `streaming-server` corriendo, que tiene
  el UIO del osciloscopio tomado en exclusiva. Por eso el control se hace con
  `/opt/redpitaya/bin/monitor`, que accede a la región de housekeeping directamente.
- Ciclo completo `on`→`off`→`off` (idempotencia) probado disparando los `.service` a
  mano. Con analizador lógico se confirmó que, sin un chequeo de estado previo, pedir
  `on`/`off` ya estando en ese estado igual reprogramaba la FPGA y generaba un pulso
  espurio — se agregó un archivo de estado local (`/root/starlink_remoto/estado`) para
  saltar la reprogramación cuando no hace falta.
- Reloj desfasado a propósito (+30s, +45s) y corregido con `STEP` en menos de 10s tras
  el restart de `ntpsec` disparado por el propio `on`.
- Bug de zona horaria encontrado y corregido: la placa corre en UTC, así que
  `OnCalendar` sin zona explícita disparaba 3 hs antes de lo esperado. Se fijó con el
  sufijo `America/Argentina/Buenos_Aires` en cada `OnCalendar=`, sin tocar el reloj del
  sistema.

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Starlink no queda usable al instante (boot + actualización de firmware) | Margen de 5 min antes de la hora "oficial"; el firmware update puede igual comerse parte de la ventana, sin mitigación total posible |
| Red Pitaya se cuelga/reinicia a mitad de ventana | `Persistent=true` en ambos timers dispara el que se perdió al volver a bootear, pero el estado *fail-safe* del relé físico (qué pasa sin señal de control) todavía no está definido — depende del modelo de relé |
| Drift real de reloj en 16 hs sin red | Mitigado con el restart de `ntpsec` en el `on`, pero no medido en campo real todavía |
| Asunción de IP pública resulta ser CGNAT | Reconfirmar con Starlink activo en sitio |
| El pin del relé no sostiene el nivel al cambiar de bitstream | **Confirmado con analizador lógico (2026-07-15):** al pasar de `v0.94` a `stream_app`, el pin cae limpio, siempre, ~800ms. Un relé normal se desenergizaría en cada cambio → **decidido usar relé biestable/latching** (mantiene su estado solo, sin señal sostenida) |

## Corte limpio de captura antes de tocar el bitstream (2026-07-16)

Hasta ahora, si el toggle del relé caía mientras `capturar_stream.py` estaba
corriendo, el script solo avisaba (`ADVERTENCIA: ...`) y cambiaba el bitstream
igual — cortando la captura en curso a la fuerza, sin coordinarse con
`relanzar_captura.sh` (que la iba a relanzar a los 5s, peleando contra el
cambio de bitstream). Eso además dejaba la placa colgada en `stream_app`
indefinidamente después de que una sesión de captura terminara sola: nada
recarga `v0.94` salvo la próxima vez que corra este mismo script.

`control_starlink.sh` ahora, antes de tocar el bitstream: si detecta
`capturar_stream.py` corriendo, le manda SIGTERM (mismo handler que Ctrl+C) y
espera a que corte solo (hasta `TIMEOUT_STOP`, configurable en
`config_campo.json` → `starlink.timeout_stop_s`, default 150s — más que el
tope de `duracion_chunk` de 2 min; si se sube el tope de chunk hay que subir
este valor a mano, no hay validación cruzada entre los dos) — así
`capturar_stream.py` termina el chunk en curso, hace su propio
`finally` (incluye esperar el move a USB), y sale con exit 0. Con eso,
`relanzar_captura.sh` decide por su cuenta no relanzar (su propio chequeo de
exit code), en vez de que el corte se lo imponga desde afuera. Si no corta a
tiempo, recién ahí se fuerza (`pkill -9`). `streaming-server` queda huérfano
tras el corte limpio (no se cae solo con el proceso padre) y se mata aparte.

**Detalle importante encontrado en la prueba real (placa 10.42.0.180):** el
patrón de `pgrep`/`pkill` NO puede ser `-f capturar_stream.py` a secas —
`relanzar_captura.sh` invoca el script pasándole la ruta completa como
argumento, así que su propia línea de comando (`bash relanzar_captura.sh
/root/scripts_campo/capturar_stream.py ...`) también contiene ese string. Un
`pkill -f capturar_stream.py` mata al supervisor bash junto con el proceso
python — el corte "funciona" (no se relanza) pero por accidente, no porque
`relanzar_captura.sh` haya visto un exit 0. El patrón correcto es
`python3.*capturar_stream\.py` (ver `PATRON_CAPTURA` en el script), que solo
matchea el proceso python real. Verificado en placa real: con el patrón
amplio el log de la sesión no tenía la línea final del supervisor; con el
patrón corregido sí aparece `[supervisor] sesion termino limpio (exit 0). No
se relanza.`.

Probado en banco con captura real de 1 min/chunk, toggle disparado a mitad de
chunk, en ambas direcciones (`on` y `off`): corte limpio, sin relanzamiento
del supervisor, registro y `estado` correctos al final. También probado
disparando `on`/`off` a través de los `.service` reales (no llamando al
script a mano) — `TimeoutStartUSec=infinity` en este unit, systemd no mata el
script aunque la espera del corte tarde >90s (el default de
`DefaultTimeoutStartUSec`).

**Segundo hallazgo, más importante que el primero porque es el caso de uso
real (2026-07-16):** el chequeo de arriba solo mataba `streaming-server`
dentro del `if` de "hay captura corriendo". Si la captura ya había terminado
sola (lo más común: `prender-starlink` → correr una captura → esperar que
termine → `apagar-starlink`), `capturar_stream.py` ya no estaba, la función
retornaba antes de llegar al `pkill` de `streaming-server`, y el toggle hacía
`overlay.sh v0.94` con `streaming-server` todavía vivo y huérfano —
confirmado en placa real con una captura de 10s: `streaming-server` seguía
corriendo después de un `apagar-starlink` "exitoso" (`Result=success`),
ahora completamente desincronizado del bitstream. Eso rompe la próxima
captura: `asegurar_servidor()` en `campo_common.py` hace `pgrep
streaming-server`, encuentra ese proceso viejo, asume que el servidor ya
está listo, y no recarga nada. Se corrigió sacando el chequeo/`pkill` de
`streaming-server` del `if` — ahora corre siempre, haya o no captura activa.
Reproducido el bug y verificada la corrección con el mismo escenario (captura
de 10s terminando sola + `apagar-starlink` real vía `.service`).

Anomalía sin explicar: 2 de las pruebas en placa (ambas veces que el fix
efectivamente mataba un huérfano + recargaba el bitstream) cortaron la
sesión SSH a mitad de comando (exit 255), con la placa siempre arriba después
y el resultado final correcto. No hay evidencia de que sea el script — puede
ser el link directo por USB-Ethernet. Si se repite en campo con Starlink real,
ahí sí ameritaría investigarse.

## Migración del pulso de control a PS_MIO10 (2026-07-23)

Relé y `control_starlink.sh` con pulso real ya funcionando desde el 22/07 (pin
`DIO1_P`, PL) — pero se encontró que **cualquier reprogramado de FPGA
(arrancar o cortar una captura) puede togglear el relé solo**, sin pasar por
el script y sin aviso (glitch de ~12-19ms en el cambio de bitstream). Filtro
de hardware (RC+Schmitt) evaluado y descartado.

Solución encontrada y validada en banco: mover el pulso de control de
`DIO1_P` (PL, housekeeping de la FPGA) a `PS_MIO10` (lado PS del Zynq, pin 3
del conector E2, "SPI MOSI" de fábrica) — un GPIO del lado PS no se resetea
con un reprogramado de PL. Requiere reconfigurar el multiplexor del pin
(registro `MIO_PIN_10` del SLCR, `0xf8000728`, escribir `0x1600` para
seleccionar función GPIO) antes de poder usarlo como salida — ver
`asegurar_mux_gpio()`/`asegurar_salida_ps()`/`pulsar_ps()` en
`control_starlink.sh`.

Validado con analizador lógico y con round-trip real de bitstream
(`v0.94` → `stream_app` → `v0.94`, arrancando y cortando una captura de
prueba): el registro del mux y el estado del pin quedaron intactos durante
todo el ciclo — el relé ya no se ve afectado por el reprogramado de FPGA.

**Persistencia del mux tras reboot — resuelta (2026-07-23):** al reiniciar la
placa, `PS_MIO10` vuelve a su función de fábrica (`SPI1_MOSI`) hasta que
algo vuelva a escribir `MIO_PIN_10`. Se confirmó en banco (placa
recién reiniciada) que aplicar mux+salida **sin pulso** igual togglea el
relé (no es solo un evento de analizador, es un toggle real) — por eso
no alcanza con resolverlo dentro del primer `on`/`off` de
`control_starlink.sh` (ese toggle accidental se sumaría al intencional
en la misma corrida y se cancelarían entre sí, dejando el pedido sin
efecto real). Se separó la configuración de mux en
`mux_ps10_common.sh` (compartido) + `asegurar_mux_ps10.sh`, aplicado una
sola vez al boot por `systemd/starlink-mux-ps10.service`, del que
`starlink-rele@.service` depende (`Requires=`/`After=`) para garantizar
el orden sin importar qué dispare el `on`/`off` (timer, alias manual).
`control_starlink.sh` sigue llamando a las mismas funciones como red de
seguridad idempotente. Validado en placa real con reboot real: la unit
corrió sola al boot, togglé el relé una sola vez de forma aislada
(confirmado con analizador — un solo pulso limpio, sin pedido de
`on`/`off` de por medio), y después `control_starlink.sh off`/`on`
corridos a mano funcionaron correctos.

**Timers reales probados y OK (2026-07-23), las dos direcciones:** se forzó
un disparo de `starlink-rele-on.timer` y, por separado, de
`starlink-rele-off.timer` (horario temporal + reactivación en cada uno),
confirmando en ambos los dos caminos posibles — catch-up de
`Persistent=true` (dispara al reactivar, pulsa de verdad) y disparo
natural al horario programado (toma el atajo, sin error, porque ya
había quedado en el estado correcto por el catch-up).

**Cableado:** siempre fue a través de la Click Shield (con su traductor de
nivel), nunca directo al pin 3 del conector E2 sin pasar por la shield —
todas las pruebas de `PS_MIO10` (round-trip de bitstream, persistencia de
mux, auto-corrección al boot) fueron con ese cableado.

**Con esto, la migración del pulso de control a `PS_MIO10` quedó cerrada por
completo.**

## PS_MIO50 (I2C SCL) evaluado como alternativa y descartado (2026-07-23)

Se probó usar `PS_MIO50` (I2C SCL, pin 9 de E2) en vez de `PS_MIO10` para
dejar el bus SPI libre a futuro (`starlink_remoto/test_pulso_ps_mio50.sh`,
script aparte, no integrado a `control_starlink.sh`). El pulso funcionó en
ambas direcciones, pero **el intento de round-trip de bitstream reveló que
convertir ese pin a GPIO corta el I2C que usa `profiles -f` para leer la
EEPROM de modelo de la placa** — con eso `overlay.sh` falla (`profiles -f`
devuelve `undefined`), rompiendo toda captura y todo `control_starlink.sh`.
Descartado con evidencia directa, no solo por el riesgo teórico de pin
compartido. Producción sigue con `PS_MIO10`.

## Persistencia de `STATE_FILE` ante corte de energía (2026-07-24)

Probado con un corte de energía real (reset duro del kernel sin sync, no solo
un `reboot` ordenado): la escritura de `STATE_FILE` (`echo > archivo`, sin
`fsync`) se podía perder si el corte caía en la ventana de hasta ~5s antes de
que ext4 confirmara la escritura en el journal — el sistema volvía a arrancar
creyendo que el último comando real nunca pasó, sin ningún aviso. Se agregó
un `sync` después de escribir `STATE_FILE` en `control_starlink.sh`. Reprobado
con el mismo mecanismo de corte real en ambas direcciones (`off→on` y
`on→off`): la escritura sobrevive en los dos sentidos.

## Horario configurable vía `config_campo.json` (2026-07-24)

El horario de los timers (`08:55`/`17:00` por default) dejó de estar
hardcodeado en los `.timer` — ahora vive en `config_campo.json` →
`starlink.hora_on`/`hora_off`, aplicado con `aplicar_horario.sh` (ver
`COMANDOS.md`). Se descartó a propósito hacer esto con un chequeo periódico
(ej. cada un minuto comparando la hora actual) en vez de timers de systemd:
`control_starlink.sh` corta cualquier captura de arena activa en cada
invocación (necesario para reprogramar a `v0.94` y leer el feedback del
relé) — un chequeo de alta frecuencia mataría capturas en curso
constantemente. Los timers de systemd, en cambio, solo invocan el script
las veces que realmente hace falta (dos por día).

Probado en banco con horarios forzados a pocos minutos: los dos disparos
(`on` y `off`) corrieron limpios, sin `ADVERTENCIA`, confirmados por HW.
Horario devuelto a `08:55`/`17:00` y timers deshabilitados al cerrar la
prueba (mismo estado que tenían antes).

## Pendientes reales

- Confirmar el comportamiento fail-safe deseado del relé real (qué pasa sin señal de control — depende del modelo, nunca definido).
- Decidir si esta carpeta se fusiona con `scripts_campo_comun/` (infraestructura compartida) una vez que el relé esté instalado en campo, o queda separada.
- Asunción de IP pública de Starlink sin CGNAT, a reconfirmar en sitio con el kit real conectado — nada de esto se probó todavía con Starlink real, todo el trabajo hasta ahora fue en banco.
- Probar los timers en su horario real (sin forzar horarios cercanos) en más de un ciclo, antes de confiar del todo en uso normal de varios días seguidos.
