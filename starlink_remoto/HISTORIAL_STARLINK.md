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

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Starlink no queda usable al instante (boot + actualización de firmware) | Margen de 5 min antes de la hora "oficial"; el firmware update puede igual comerse parte de la ventana, sin mitigación total posible |
| Red Pitaya se cuelga/reinicia a mitad de ventana | `Persistent=true` en ambos timers dispara el que se perdió al volver a bootear. **Resuelto:** el fail-safe del relé físico ante ausencia total de señal de control quedó definido por el modelo elegido — relé biestable/latching, mantiene el último estado mecánicamente sin necesitar señal sostenida ni alimentación en el circuito de control, así que un cuelgue o corte de la Red Pitaya no lo mueve solo. |
| Drift real de reloj en 16 hs sin red | Mitigado con el restart de `ntpsec` en el `on`, pero no medido en campo real todavía |
| Asunción de IP pública resulta ser CGNAT | Reconfirmar con Starlink activo en sitio |
| El pin del relé no sostiene el nivel al cambiar de bitstream | **Confirmado con analizador lógico (2026-07-15):** al pasar de `v0.94` a `stream_app`, el pin cae limpio, siempre, ~800ms. Un relé normal se desenergizaría en cada cambio → **decidido usar relé biestable/latching** (mantiene su estado solo, sin señal sostenida) |

## Pendientes reales

- ~~Probar el rescate por modo manual vencido con los timers/reconciliador reales disparando solos (no solo invocación manual de `decidir_objetivo.sh`), y con un reboot en el medio~~ — **cerrado (2026-08-03):** validado en placa real, ver sección correspondiente en "Historial de cambios".
- ~~`starlink_manual.sh` escribe `modo_manual_file` sin `sync` explícito, a diferencia de `control_starlink.sh` (que sí tiene uno para `STATE_FILE` desde 2026-07-24)~~ — **cerrado (2026-07-29):** se agregó el mismo `sync` después del `printf`. No se repitió una prueba de corte de energía dedicada — usa el mismo mecanismo (`sync` sobre ext4) ya probado en sec.84 con un archivo genérico, que sí sobrevivió un reboot real.
- ~~Confirmar el comportamiento fail-safe deseado del relé real (qué pasa sin señal de control)~~ — **cerrado (2026-07-28):** era una redacción vieja sin cruzar contra la decisión de relé biestable/latching, ver "Riesgos abiertos" arriba. Lo que sigue sin cubrir es un cuelgue de *software* (no del relé) — para eso ya hay un watchdog de hardware de systemd activo en la placa, `RuntimeWatchdogSec=5s` vía `cdns-wdt`/`/dev/watchdog0`, confirmado por SSH — resetea si systemd se cuelga, no decide nada sobre el estado del relé.
- Decidir si esta carpeta se fusiona con `scripts_campo_comun/` (infraestructura compartida) una vez que el relé esté instalado en campo, o queda separada.
- Asunción de IP pública de Starlink sin CGNAT, a reconfirmar en sitio con el kit real conectado — nada de esto se probó todavía con Starlink real, todo el trabajo hasta ahora fue en banco.
- Probar los timers en su horario real (`08:55`/`17:00`, ya aplicado en la placa el 2026-08-03) en más de un ciclo día/noche seguido, antes de confiar del todo en uso normal de varios días — lo probado hasta ahora fue siempre con horarios forzados a pocos minutos.
- ~~Validar de punta a punta el fix de `STATE_FILE`/`aplicar_objetivo.sh` (2026-07-31): que el reconciliador de 5 min corrija solo un drift real sin intervención manual, sin captura activa de por medio~~ — **cerrado (2026-08-03):** validado en placa real con un drift inyectado a propósito, ver sección correspondiente en "Historial de cambios".
- ~~Confirmar con multímetro si `DIO2_P` (feedback) realmente queda flotante al desconectar el cable~~ — **cerrado (2026-07-28):** medido físicamente con multímetro por el usuario, confirma el comportamiento que ya se había visto por registro (`control_starlink.sh on` con cable desconectado disparaba `ADVERTENCIA` + `exit 1`). Ya no es una lectura de registro sin verificar contra el hardware real.

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
registro, y más adelante mover el pulso de control a `PS_MIO10`, ver historial más abajo).

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

## Historial de cambios

Bitácora cronológica de decisiones y hallazgos de hardware. Para el estado actual del
diseño y lo que falta, ver las secciones de arriba ("Riesgos abiertos", "Pendientes
reales") — no hace falta leer todo esto para saber dónde está parado el proyecto hoy.

### Corte limpio de captura antes de tocar el bitstream (2026-07-16)

Antes, un toggle de relé a mitad de `capturar_stream.py` solo avisaba (`ADVERTENCIA`)
y cambiaba el bitstream igual — cortaba la captura a la fuerza sin coordinarse con
`relanzar_captura.sh` (que la relanzaba a los 5s, peleando contra el cambio de
bitstream) y dejaba `streaming-server` huérfano en `stream_app` indefinidamente.

Fix: `control_starlink.sh`, antes de tocar el bitstream, manda SIGTERM a
`capturar_stream.py` (mismo handler que Ctrl+C) y espera hasta `TIMEOUT_STOP`
(`config_campo.json` → `starlink.timeout_stop_s`, default 150s) a que corte solo y
salga con exit 0 — así `relanzar_captura.sh` decide por su propio chequeo de exit code
no relanzar, en vez de que el corte se le imponga desde afuera. Si no corta a tiempo,
se fuerza (`pkill -9`).

**Bug real encontrado (placa `10.42.0.180`):** el patrón de `pgrep`/`pkill` no puede
ser `capturar_stream.py` a secas — `relanzar_captura.sh` invoca el script pasándole la
ruta completa como argumento, así que su propia línea de comando también contiene ese
string, y un `pkill -f` amplio mata al supervisor junto con el proceso python (el corte
"funciona" mucho por accidente, no porque `relanzar_captura.sh` haya visto el exit 0).
Patrón correcto: `python3.*capturar_stream\.py` (`PATRON_CAPTURA` en el script) — solo
matchea el proceso real. Confirmado en placa real comparando el log del supervisor con
cada patrón.

**Segundo bug, más importante por ser el caso de uso real:** el kill de
`streaming-server` estaba anidado dentro del `if` de "hay captura corriendo" — si la
captura ya había terminado sola (el caso típico: `prender-starlink` → captura →
`apagar-starlink`), el toggle reprogramaba a `v0.94` con `streaming-server` todavía
vivo y huérfano, desincronizado del bitstream. Eso rompe la próxima captura
(`asegurar_servidor()` ve el proceso viejo y no recarga nada). Fix: el kill de
`streaming-server` corre siempre, no solo dentro de ese `if`. Reproducido y verificado
en placa real con una captura de 10s terminando sola.

Anomalía sin explicar: 2 pruebas en placa cortaron la sesión SSH a mitad de comando
(exit 255, placa siempre arriba después, resultado final correcto) — no hay evidencia
de que sea el script, podría ser el link USB-Ethernet. Investigar solo si se repite en
campo con Starlink real.

### Migración del pulso de control a PS_MIO10 (2026-07-23)

El pulso original iba por `DIO1_P` (PL) — funcionaba, pero se encontró que cualquier
reprogramado de FPGA (arrancar o cortar una captura) podía togglear el relé solo, sin
pasar por el script (glitch de ~12-19ms en el cambio de bitstream). Filtro de hardware
(RC+Schmitt) evaluado y descartado.

Fix: mover el pulso a `PS_MIO10` (lado PS del Zynq, pin 3 del conector E2, "SPI MOSI"
de fábrica, vía Click Shield) — un GPIO del lado PS no se resetea con un reprogramado
de PL. Requiere reconfigurar el mux del pin (`MIO_PIN_10` del SLCR, `0xf8000728` =
`0x1600`) antes de usarlo como salida (ver `asegurar_mux_gpio()`/`asegurar_salida_ps()`/
`pulsar_ps()` en `control_starlink.sh`). Validado con analizador lógico y round-trip
real de bitstream (`v0.94` → `stream_app` → `v0.94`): mux y pin quedan intactos, el
relé ya no se ve afectado por el reprogramado de FPGA.

**Persistencia del mux tras reboot — resuelta:** el mux vuelve a su función de fábrica
al reiniciar la placa hasta que algo reescriba `MIO_PIN_10`. Confirmado en banco que
aplicar mux+salida *sin pulso* igual togglea el relé (toggle real, no artefacto de
analizador) — por eso no alcanza con resolverlo dentro del primer `on`/`off`, hay que
aislarlo. Se separó en `mux_ps10_common.sh` (compartido) + `asegurar_mux_ps10.sh`,
aplicado una sola vez al boot por el service correspondiente (el service que dispara
el pulso depende de esta unit al bootear, `Requires=`/`After=`, para garantizar el
orden sin importar qué dispare el `on`/`off`). Validado con reboot real: la unit corrió
sola al boot, togglé el relé una sola vez de forma aislada, y después `on`/`off` a mano
funcionaron correctos.

**Timers probados y OK, las dos direcciones:** catch-up de `Persistent=true` al
reactivar el timer, y disparo natural al horario programado — ambos confirmados (ver
más abajo, sec. "Reloj sin RTC", para el caso donde ese mismo catch-up SÍ falla, con el
reloj atrasado de por medio).

**Con esto, la migración del pulso de control a `PS_MIO10` quedó cerrada por completo.**

### PS_MIO50 (I2C SCL) evaluado como alternativa y descartado (2026-07-23)

Se probó usar `PS_MIO50` (I2C SCL, pin 9 de E2) en vez de `PS_MIO10` para dejar el bus
SPI libre a futuro (`starlink_remoto/test_pulso_ps_mio50.sh`, script aparte, no
integrado a `control_starlink.sh`). El pulso funcionó en ambas direcciones, pero **el
intento de round-trip de bitstream reveló que convertir ese pin a GPIO corta el I2C que
usa `profiles -f` para leer la EEPROM de modelo de la placa** — con eso `overlay.sh`
falla (`profiles -f` devuelve `undefined`), rompiendo toda captura y todo
`control_starlink.sh`. Descartado con evidencia directa, no solo por el riesgo teórico
de pin compartido. Producción sigue con `PS_MIO10`.

### Persistencia de `STATE_FILE` ante corte de energía (2026-07-24)

Probado con un corte de energía real (reset duro del kernel sin sync, no solo un
`reboot` ordenado): la escritura de `STATE_FILE` (`echo > archivo`, sin `fsync`) se
podía perder si el corte caía en la ventana de hasta ~5s antes de que ext4 confirmara
la escritura en el journal — el sistema volvía a arrancar creyendo que el último
comando real nunca pasó, sin ningún aviso. Se agregó un `sync` después de escribir
`STATE_FILE` en `control_starlink.sh`. Reprobado con el mismo mecanismo de corte real
en ambas direcciones (`off→on` y `on→off`): la escritura sobrevive en los dos sentidos.

### Horario configurable vía `config_campo.json` (2026-07-24)

El horario de los timers (`08:55`/`17:00` por default) dejó de estar hardcodeado en
los `.timer` — ahora vive en `config_campo.json` → `starlink.hora_on`/`hora_off`,
aplicado con `aplicar_horario.sh` (ver `COMANDOS.md`). Se descartó a propósito un
chequeo periódico de alta frecuencia (ej. cada un minuto comparando la hora) en vez de
timers de systemd: `control_starlink.sh` corta cualquier captura activa en cada
invocación (necesario para reprogramar a `v0.94` y leer el feedback), así que un
chequeo frecuente mataría capturas constantemente. Los timers de systemd solo invocan
el script las veces que hace falta (dos por día).

Probado en banco con horarios forzados a pocos minutos: los dos disparos corrieron
limpios, confirmados por HW. Configuración restaurada al cerrar la prueba.

### Reloj sin RTC + `Persistent=true` + carrera on/off — hallazgo y rediseño (2026-07-27)

**Problema planteado:** la placa corre a batería+panel solar, sin RTC. Si se queda sin
batería muchas horas o un día entero, al rearrancar el reloj queda atrasado esa misma
cantidad. Duda: ¿qué hacen los timers si el horario configurado ya "pasó" según el
reloj real pero la placa recién arranca con un reloj que todavía no lo sabe?

**Reproducido en placa real (banco, `10.42.0.180`):**

1. Confirmado en journal que ya le había pasado antes: `fake-hwclock` restauró al
   bootear un reloj 3 días atrasado; al llegar la red, `ntpsec` corrigió con un salto
   atómico (`stepped by 232775s`), no gradual.
2. Reproducido a mano (reloj atrasado 2 días + reboot real): journal mostró `Not using
   persistent file timestamp ... as it is in the future` — **`Persistent=true` no
   sirve de red de seguridad acá**: systemd descarta la marca de "última corrida" por
   verse "del futuro" desde el reloj recién restaurado (atrasado). No hay catch-up al
   bootear; el relé se queda como estaba hasta que el reloj (atrasado pero corriendo
   normal) llegue solo al próximo horario — acotado a ~24h pero impredecible desde
   afuera.
3. **Hallazgo no buscado:** si el salto de corrección de `ntpsec` cruza un horario de
   encendido Y uno de apagado pendientes a la vez (típico tras un corte de varios
   días), los dos servicios arrancan en simultáneo y compiten por el mismo relé —
   reproducido dos veces, ganó uno cada vez, no determinístico.

Placa restaurada al estado original al cerrar las pruebas.

**Diseño: una sola decisión, no tres independientes.** Antes había tres puntos de
decisión que no se hablaban entre sí (boot restaura `STATE_FILE` a ciegas, timer
on/off pulsan a ciegas). Se reemplazan por una única función, `decidir_objetivo.sh`
(no toca hardware, solo calcula "on"/"off"), con prioridad fija:

1. **Modo manual** (`starlink_manual.sh {on|off|auto}`) — gana siempre, con una
   excepción (ver "Modo manual con autolimpieza" más abajo): se borra solo en cuanto
   el cálculo de 2+3 coincide por su cuenta con lo que el manual ya venía forzando.
2. **Reloj no confiable** (`timedatectl show -p NTPSynchronized` = no) → fuerza "on"
   (rescate), ignorando el horario — reemplaza la idea original de "franja de
   encendido de emergencia": no hacía falta una franja nueva, hacía falta una señal
   de si el reloj vale la pena mirarlo.
3. **Horario normal** (`config_campo.json` → `hora_on`/`hora_off`), solo si ninguna
   de las dos anteriores aplica.

`aplicar_objetivo.sh` decide y aplica (vía `control_starlink.sh`, ya idempotente).
Boot, los dos timers diarios y un timer nuevo (`starlink-reconciliador.timer`, cada 5
min) llaman todos a este mismo script — si dos disparan juntos, calculan el mismo
objetivo y ya no compiten. La carrera de HW residual se cierra aparte con un `flock`
en `control_starlink.sh`.

El reconciliador de 5 min tiene un cuidado explícito para no repetir el error ya
evitado en "Horario configurable" (arriba): un chequeo de alta frecuencia sin filtro
mataría capturas constantemente. Por eso `aplicar_objetivo.sh` sin `--forzar` compara
el objetivo contra `STATE_FILE` *antes* de llamar a `control_starlink.sh`, y solo
actúa si de verdad hay que cambiar algo. El boot es la única excepción (`--forzar`,
siempre verifica por HW real) porque ahí sí puede haber un mismatch real (el mux de
`PS_MIO10` puede togglear el relé solo al habilitarse, ver arriba).

Se agregó también `estado_starlink.sh` (lectura pasiva de `STATE_FILE`) y, en
`control_starlink.sh`, mensaje explícito de éxito al pulsar y `exit 1` real cuando el
feedback no coincide con lo pedido (antes salía con éxito igual, silencioso).
`starlink-rele@.service` (template viejo) quedó retirado — los timers apuntan a
`starlink-aplicar-objetivo.service`.

### Modo manual con autolimpieza (2026-07-27, misma sesión)

**Motivo:** el usuario quería poder cortar el relé a mano antes de horario (ej. a las
15:00 en vez de esperar las 17:00, para no gastar batería al pedo) sin quedar pegado
en modo manual para siempre — el modo manual original no expira solo, así que un
corte de energía largo después de apagarlo a mano lo dejaría apagado indefinidamente
sin rescate automático (agrava el riesgo de fail-safe de "Riesgos abiertos": el único
camino de acceso remoto es el propio Starlink que este relé corta).

**Diseño:** `decidir_objetivo.sh` calcula siempre el valor de reloj-no-confiable/
horario (prioridad 2+3), incluso con modo manual activo. Si el manual coincide con ese
valor, se borra el archivo de modo manual solo (sin tocar HW) antes de devolver el
resultado — "apagar antes de horario" se autolimpia en cuanto el horario real llega a
ese mismo valor, sin que nadie tenga que acordarse de `auto-starlink` después.

**Validado en placa real (192.168.0.55) con 3 casos:**
1. Manual coincidía de entrada con el horario natural → se autolimpió sin pedirlo.
2. Manual="off" en medio de la ventana de "on" (caso real de uso) → se mantuvo forzado, archivo intacto.
3. `hora_off` forzada a un horario ya pasado con manual="off" puesto → coincidió y se autolimpió.

**Qué NO resuelve:** si el corte de energía largo ocurre mientras el manual está en un
valor que nunca va a coincidir con el rescate por reloj (ej. manual="off" durante todo
un apagón, donde el rescate diría "on"), el manual sigue ganando sin límite de tiempo
— el riesgo de fail-safe sigue exactamente igual, esto solo resuelve el caso de uso
cotidiano, no el escenario de emergencia.

### Rescate por modo manual "off" vencido (2026-07-28)

**Motivo:** cierra el hueco que "Modo manual con autolimpieza" dejaba explícitamente
sin resolver — modo manual="off" que nunca coincide solo con el rescate por
reloj/horario (ej. puesto en pleno día) se queda forzado sin límite de tiempo. Si en
el medio hay un corte de energía largo, el sitio queda inaccesible para siempre.

**Diseño:** `starlink_manual.sh` guarda un timestamp (epoch) junto con el valor en
`modo_manual_file` (2 líneas, se reescribe cada `on`/`off`). `decidir_objetivo.sh`
agrega una prioridad 0, por encima de "honrar el modo manual": si el valor es "off" y
pasaron `starlink.rescate_manual_horas` (default 24) sin renovarse, se lo ignora y se
fuerza "on" — sin borrar el archivo. Renovar (`starlink_manual.sh off` de nuevo)
reinicia el reloj de rescate desde cero; es un dead-man's switch, no un límite
absoluto (con re-confirmación periódica se puede mantener apagado indefinidamente).

Formato viejo de `modo_manual_file` (una línea, sin timestamp): se trata como
timestamp desconocido → rescate vencido de entrada, más seguro que asumir que es
reciente.

**Validado en placa real (192.168.0.55), 4 casos:**
1. Formato viejo (sin timestamp), manual="off" preexistente → `on` (rescatado de entrada).
2. Manual="off" recién puesto → `off` (no vencido, se respeta).
3. Manual="off" con timestamp simulado de hace 25hs → `on` (rescatado), archivo intacto.
4. Manual="off" con timestamp simulado de hace 23hs → `off` (todavía no vencido).

Regresión de la autolimpieza confirmada sin cambios.

**Qué NO resuelve:** el umbral (24hs, para cubrir una noche normal de ~16hs más
margen) sigue siendo una ventana de exposición real — un corte de menos de 24hs con
manual="off" en mal momento sigue dejando el sitio inaccesible durante ese corte,
ahora con techo en vez de indefinido. Tampoco resuelve un cuelgue de software que
impida bootear/ejecutar el reconciliador — este mecanismo corrige una decisión de
estado, no un cuelgue (para eso está el watchdog de hardware de systemd, ver arriba en
"Pendientes reales").

**Fix (2026-07-28, encontrado al re-explicar el mecanismo):** el cálculo de horas
transcurridas usaba `date +%s` sin chequear antes si el reloj está sincronizado por
NTP. Sin RTC, justo después de un reboot el reloj puede estar atrasado hasta que
`ntpsec` lo corrige — si ese reboot cae en medio de un corte largo con manual="off"
puesto, la resta contra el timestamp guardado daba horas de menos (o negativo),
demorando el rescate justo cuando más importa. Se agregó el mismo chequeo
`NTPSynchronized` que ya usaba la prioridad 2: si no está sincronizado, se trata como
timestamp desconocido → vencido de entrada. Validado con dry-run local
(`cfg.py`/`timedatectl` mockeados, sin tocar la placa): los 4 casos de arriba dan el
mismo resultado, más el caso nuevo (NTP no sincronizado + manual="off" recién puesto →
ahora `"on"`, antes daba `"off"`). Commiteado (`54338ec`).

**Validado en placa real con reboot real (2026-07-29):** manual="off" puesto en pleno
horario "on" (diverge del horario, condición necesaria para que el rescate importe) y
reboot real. `journalctl -b 0` mostró `NTPSynchronized` en `no` desde el arranque de
`ntpsec` hasta el step de reloj real (`time stepped by ~15.9s`) y unos segundos más de
asentamiento — con flapping (`yes` momentáneo apenas arranca `ntpsec`, antes de que fije
el estado real en `no`). Invocando `aplicar_objetivo.sh` a mano en esa ventana: forzó
`on` de verdad (pulso real confirmado por HW), sin borrar `modo_manual_file` ni su
timestamp. A los ~2 min (`starlink-reconciliador.timer`, ya con reloj sincronizado)
volvió solo a `off`, honrando el manual todavía no vencido. Ciclo completo (rescate →
auto-corrección) confirmado en hardware, no solo en dry-run.

### Pulsos espurios en PS_MIO10 con Starlink real conectado — polaridad invertida + capacitor, y bug de `STATE_FILE` desactualizado (2026-07-31)

**Contexto:** primera vez con el kit Starlink real conectado y con carga real detrás del
relé — todo el trabajo anterior (arriba) fue en banco, sin Starlink real. Placa usada:
`rp-f0fbda` (la de banco, ver referencia de placas), llevada físicamente afuera y
conectada directo a la Starlink real para esta prueba.

**Corrección (2026-08-03):** el párrafo anterior decía que esta placa no era "la placa
de campo de IP pública `153.67.6.182`". Eso quedó en duda — en sesión posterior, esa
misma IP pública respondió con hostname `rp-f0fbda`, es decir, esta placa de banco. No
está confirmado si alguna vez hubo una placa de campo físicamente distinta, o si
siempre fue esta misma llevada afuera. No dar por sentado que son dos equipos
separados sin volver a verificar el hostname.

**Síntoma:** al pedir `on`, el relé prendía y a los pocos segundos se apagaba solo, sin
que ningún script lo pidiera. Con analizador lógico sobre `PS_MIO10` se confirmaron
pulsos chicos ajenos al pulso intencional del script — el relé es biestable por flanco
(cualquier pulso lo togglea, sin importar el origen), así que un pulso espurio alcanza
para apagarlo. No se había visto nunca en banco porque ahí no hay una carga real de
Starlink (inrush/ruido) detrás del relé.

**Fix de hardware, confirmado por el usuario:** se invirtió la polaridad del pulso en
`pulsar_ps()` (`control_starlink.sh`) — reposo en 1 en vez de 0, pulso como flanco de
bajada (1→0→1) en vez de subida — más un capacitor agregado por el usuario en la línea
de control. El bloque original (reposo en 0, flanco de subida) quedó comentado en el
mismo archivo, no borrado, para poder revertir. No se aisló cuál de los dos cambios
(polaridad vs. capacitor) fue el determinante, se probaron juntos. No cambia el glitch
ya conocido del primer enable del mux al bootear (ver "Migración del pulso de control a
PS_MIO10" más arriba) — ese pasa antes de que la polaridad de reposo importe.

**Bug de software encontrado en paralelo, real y separado:** `aplicar_objetivo.sh`
comparaba el objetivo contra `STATE_FILE` y, si coincidían, se saltaba la verificación
real por HW sin límite de tiempo — así, un pulso espurio como el de arriba (o cualquier
cambio de estado por fuera del script) nunca se detectaba hasta que el objetivo mismo
cambiara por otro motivo (próximo horario). Reproducido en placa real: tres corridas
seguidas del reconciliador (`18:09`, `18:14`, `18:19`) se saltearon la verificación por
HW porque `STATE_FILE` ya coincidía con el objetivo, mientras el relé real ya había
cambiado de estado sin que nada lo registrara.

**Fix:** `aplicar_objetivo.sh` ahora solo aplica el atajo de caché si hay una captura
activa que proteger (verificar de verdad exige el bitstream `v0.94`, que corta
`stream_app`) — sin captura activa, siempre verifica contra el HW real, aunque el
objetivo ya coincida con la caché. `PATRON_CAPTURA` (antes solo en
`control_starlink.sh`) se movió a `mux_ps10_common.sh`, compartido por los dos scripts
en vez de duplicado.

**Desplegado en la placa (`10.42.0.180`), con backups de los tres archivos tocados
(`*.bak_pre_invertido`, `*.bak_pre_statefile_fix`). Commiteado el 2026-07-31 (`1a8a3bc`).**

### Fix de `STATE_FILE` validado con un drift real inyectado, y horario real aplicado (2026-08-03)

**Prueba rápida de los timers on/off, en banco (`10.42.0.180`):** el relé había quedado
`on` por un modo manual viejo de una sesión anterior, con `hora_on`/`hora_off` invertidos
(`12:35`/`12:05`, on > off — con esa combinación el horario puro nunca da "on", solo el
manual lo sostenía). Se limpió el manual (`auto-starlink`) y el relé pasó a `off` al
instante, **confirmado por HW** (no por caché, gracias al fix de arriba). Se forzó
`hora_on` a +5 min y se corrió `aplicar_horario.sh`: al llegar la hora,
`starlink-rele-on.timer` disparó en punto y `aplicar_objetivo.sh` confirmó `on` por HW en
el log, sin intervención manual. Después se aplicó el horario real de producción,
`hora_on=08:55`/`hora_off=17:00`.

**Validación del fix de `STATE_FILE` con un drift real inyectado — el pendiente que
quedaba abierto desde la sección anterior:** para simular un pulso espurio real sin
depender de que ocurra solo, se inyectó un pulso externo directo sobre `DATA_REG`/
`PS_BIT` (mismos valores de `mux_ps10_common.sh`) por SSH, **bypaseando a propósito**
`control_starlink.sh`/`aplicar_objetivo.sh` — así el relé cambia de estado real pero
`STATE_FILE` queda desactualizado, igual que haría un pulso de ruido real. Sin captura
activa corriendo (precondición necesaria: con captura activa el atajo de caché se
activa a propósito y no verificaría por HW, eso no sería un bug).

Hecho sobre la placa ya devuelta a un sitio con Starlink real conectado (ver nota de
corrección más arriba sobre la identidad de esta placa), con el riesgo aceptado
explícitamente por el usuario de perder el único acceso remoto al sitio si el
reconciliador no corregía como se esperaba.

**Resultado, confirmado por `journalctl`:**
- `15:08:56 UTC` — corrida normal previa del reconciliador, relé ya en `on`, sin acción (antes del pulso).
- `~15:13 UTC` — pulso externo inyectado; el relé se apagó de verdad (SSH y toda la conectividad se cortaron al toque, porque este mismo relé corta la alimentación/conexión de Starlink, no solo una señal de control).
- `15:13:58–15:14:02 UTC` — la corrida programada del reconciliador (le tocó caer justo después del pulso) detectó el mismatch (objetivo `on` vs. HW real `off`) y lo corrigió sola en 4 segundos: `"rele ahora en 'on' (confirmado por HW)"`. Cero intervención manual.
- `15:15:19 UTC` — SSH recuperado. Los ~77s extra después de la corrección del relé son el propio terminal Starlink reconectándose al satélite, no el mecanismo del relé.

**Corte real de acceso remoto: ~2 minutos en total** — menos que el peor caso teórico de
5 min, porque el pulso cayó justo antes de una corrida ya programada del reconciliador.
Con esto, el fix de `STATE_FILE` de la sección anterior queda **validado en hardware
real de punta a punta**, no solo por lectura de código.

### Rescate por modo manual "off" vencido, validado con timers reales y reboot real (2026-08-03, misma sesión)

**Motivo:** cierra el pendiente que quedaba desde la sección "Rescate por modo manual
'off' vencido" — ahí solo se había probado invocando `decidir_objetivo.sh` a mano con un
timestamp simulado (dry-run de lógica), nunca dejando que el propio
`starlink-reconciliador.timer` o el arranque real lo detectaran y corrigieran solos, ni
combinado con un reboot real en el medio de la ventana vencida.

**Método, sin esperar las 24hs reales:** lo único que importa para el mecanismo es el
timestamp guardado en `modo_manual_file`, no el tiempo real transcurrido. Se escribió
directamente `off` + un timestamp ya "vencido" (epoch de ~25hs atrás) en ese archivo, se
apagó el relé de verdad con `control_starlink.sh off` (simulando que alguien lo apagó a
mano hace un día y nunca lo renovó), y se programó un reboot real desacoplado de la
sesión SSH (`systemd-run --on-active=15s systemctl reboot --force --force` — necesario
porque apagar el relé corta la conexión al toque, la placa no tiene Magic SysRq). Todo
en una sola tanda de comandos, antes de perder la conexión.

**Resultado, confirmado por `journalctl`:**
- El reboot programado se disparó solo, sin depender de la sesión SSH (que ya estaba cortada).
- Al arrancar, `starlink-mux-ps10.service` (que llama `aplicar_objetivo.sh --forzar`, ver sección "Migración del pulso de control a PS_MIO10") corrigió el relé a `on` en los primeros segundos del boot — pero en ese momento el NTP todavía no había sincronizado, así que técnicamente fue el rescate por "reloj no confiable" el que disparó primero, no el de manual vencido (los dos mecanismos conviven y el primero que evalúa gana). SSH recuperado en **~2 minutos** desde el corte.
- El NTP tardó **~17 minutos** en sincronizar del todo después de este reboot — mucho más que el <1 minuto visto en banco (sec. "Reloj sin RTC", 2026-07-29); probablemente por tener que rearmar las asociaciones DNS/pool de `ntpd` desde cero sobre esta conexión. No es un bug, pero conviene tenerlo presente: en campo, el reloj puede tardar bastante más en volverse confiable después de un reboot que lo que la prueba de banco hacía suponer.
- Una vez confirmado `NTPSynchronized=yes` (17:17:42 UTC), se esperó a la siguiente corrida ya programada del reconciliador (17:21:52 UTC, con el NTP sincronizado sin ninguna ambigüedad) — ahí el único camino posible para que decidir_objetivo.sh devuelva `on` es el de manual vencido (el chequeo de reloj no confiable ya no aplica). Confirmado: `"OK: el rele ya esta en 'on' (verificado por HW), no hago nada"`, y una verificación directa aparte con `control_starlink.sh on` lo reconfirmó. `modo_manual_file` siguió intacto en todo momento (no se borra, como corresponde al diseño).

**Con esto, el camino de rescate por manual vencido queda validado en hardware real,
disparando por su cuenta vía los timers/servicios reales (no invocación manual), y
sobreviviendo correctamente un reboot real en el medio de la ventana vencida — aislado
del rescate por reloj no confiable, que ya estaba validado desde antes.**
