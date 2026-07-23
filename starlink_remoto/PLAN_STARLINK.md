# Acceso remoto vía Starlink con relé

## Contexto

Fase 1: equipo en campo con el usuario presente, haciendo pruebas y validando datos.
Fase 2: equipo queda solo en el sitio. La Red Pitaya no captura todo el tiempo — arranca
y para las capturas a demanda (orden del usuario, ej. para actualizar scripts). El
acceso remoto es por SSH a la Red Pitaya vía Starlink.

Para ahorrar energía, el kit Starlink (dish + router) se energiza solo durante una
ventana horaria fija, controlada por un relé. **Hoy el relé todavía no existe** — se
simula escribiendo un registro de LED de la propia Red Pitaya, para poder probar toda la
lógica de horarios y de sincronización de reloj sin depender del hardware (ver nota en
"Cómo funciona" — esa escritura no prende nada mientras corre una captura).

## Arquitectura

| Componente | Rol | Alimentación |
|---|---|---|
| Red Pitaya (la misma que corre `scripts_campo/`) | Corre los timers, controla el relé, corre las capturas cuando se le pide | Siempre encendida, fuente propia del sitio |
| Relé (simulado hoy con LED0) | Corta/habilita alimentación del kit Starlink | Controlado por escritura directa de registro desde la Red Pitaya |
| Starlink (dish + router) | Da conectividad para el SSH entrante | Detrás del relé — apagado por default |

Asunción a reconfirmar en sitio: el plan de Starlink da IP pública/gestionable, así que
el SSH entrante llega directo sin túnel intermedio (Tailscale, WireGuard, etc.). Si en
la práctica resulta ser CGNAT, este plan no alcanza y hace falta agregar esa capa.

## Cómo funciona

No hay `cron` instalado en esta placa (Ubuntu 24.04 mínimo, sin el paquete). Se usa
**systemd timers**, el reemplazo nativo — mismo concepto que cron, pero como parte del
propio systemd (que ya está siempre corriendo), sin instalar nada extra.

Son 3 archivos, todos en `starlink_remoto/`:

| Archivo | Qué es |
|---|---|
| `control_starlink.sh` | El script que prende/apaga — **hoy escribe un registro que no es el relé real, ver nota abajo** |
| `systemd/starlink-rele@.service` | La "tarjeta" que dice qué hacer: correr `control_starlink.sh on` o `control_starlink.sh off` |
| `systemd/starlink-rele-on.timer` / `-off.timer` | Las "tarjetas" que dicen cuándo: 08:55 y 17:00 hora Argentina, todos los días |

El `on` además reintenta forzar la hora: reinicia `ntpsec` (que ya viene instalado en
esta placa), lo que dispara un `STEP` — corrección inmediata del reloj — en vez de
esperar el ciclo de sincronización normal, que puede tardar minutos. Esto importa
porque la placa no tiene RTC: el reloj sigue corriendo solo con el oscilador local
durante las ~16 hs sin red, así que puede llegar levemente desviado a cada ventana.

**Nota importante (2026-07-15):** `control_starlink.sh` escribe hoy en `0x40000030`
pensando que es el registro del LED0. Confirmado con los regsets oficiales de FPGA que
esa dirección solo es "LED" en el bitstream **default** (`v0.94`) — mientras
`streaming-server` corre (bitstream `stream_app`), esa misma dirección es en realidad
el **factor de decimación del ADC en vivo**. O sea: hoy esta escritura no prende nada
durante una captura, y en el peor caso puede pisar la decimación de una captura activa.
El diseño real del relé necesita reprogramar la FPGA a `v0.94` para tocar ese registro
(ver siguiente sección) — no alcanza con "cambiar dos líneas" como se pensaba original.

## Instalación

```bash
cd starlink_remoto

# copiar los scripts (control + configuracion de mux compartida + boot)
scp control_starlink.sh mux_ps10_common.sh asegurar_mux_ps10.sh root@<IP_PLACA>:/root/starlink_remoto/

# copiar las unidades systemd
scp systemd/starlink-mux-ps10.service systemd/starlink-rele@.service \
    systemd/starlink-rele-on.timer systemd/starlink-rele-off.timer \
    root@<IP_PLACA>:/etc/systemd/system/

# instalar y activar (starlink-mux-ps10 primero, corre al boot y de una vez)
ssh root@<IP_PLACA> "
  chmod +x /root/starlink_remoto/control_starlink.sh /root/starlink_remoto/asegurar_mux_ps10.sh
  systemctl daemon-reload
  systemctl enable --now starlink-mux-ps10.service
  systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer
"

# alias para prender/apagar a mano por SSH (opcional, comodidad)
scp aliases.sh root@<IP_PLACA>:/root/starlink_remoto/
ssh root@<IP_PLACA> "grep -q 'prender-starlink' /root/.bashrc || cat /root/starlink_remoto/aliases.sh >> /root/.bashrc"
```

## Operación día a día

```bash
# ver cuándo dispara cada timer a continuación
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"

# prender/apagar a mano, sin esperar el horario — una vez logueado por SSH en la placa
prender-starlink   # = systemctl start starlink-rele@on.service
apagar-starlink    # = systemctl start starlink-rele@off.service

# ver si corrió bien y cuándo (incluye errores si los hay)
ssh root@<IP_PLACA> "journalctl -u starlink-rele@on.service"

# ver el estado actual simulado (1 = "prendido", 0 = "apagado")
ssh root@<IP_PLACA> "/opt/redpitaya/bin/monitor 0x40000018"
```

`apagar-starlink` es la forma prevista para cortar antes de la hora fija (ej. si el
usuario termina la jornada más temprano) — al apagarlo, la propia sesión SSH se corta
en el acto (depende del Starlink que se está apagando), es lo esperado. El `off`
programado a las 17:00 igual va a disparar después, pero no hace nada si ya estaba
apagado (idempotente).

Para cambiar el horario: editar la línea `OnCalendar=` del `.timer` correspondiente
(local y en la placa), y en la placa correr `systemctl daemon-reload && systemctl
restart starlink-rele-on.timer` (o `-off.timer`). No hay que tocar el script.

## Desactivar/activar la programación automática (ej. durante pruebas de campo)

```bash
# desactivar los dos horarios (08:55 / 17:00) sin perder la instalación
ssh root@<IP_PLACA> "systemctl disable --now starlink-rele-on.timer starlink-rele-off.timer"

# reactivarlos cuando se quiera volver al horario fijo
ssh root@<IP_PLACA> "systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer"

# confirmar el estado (0 timers listados = desactivados)
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"
```

`disable` evita que el timer se reactive solo si la placa reinicia; `--now` además lo
corta ya. Los alias `prender-starlink` / `apagar-starlink` **no dependen del timer**:
llaman directo a `systemctl start starlink-rele@on.service` / `@off.service`, así que
siguen funcionando igual (a mano) esté el timer activado o no. Desactivado el
2026-07-17 en la placa 10.42.0.180 para no interferir con pruebas en curso.

## Validado en banco (placa real, sin Starlink conectado)

- `rp.rp_LEDSetState()` (propuesta inicial) **falla**: `rp_Init()` inicializa también
  el osciloscopio y choca (`Bus error`) con el `streaming-server` corriendo, que tiene
  el UIO del osciloscopio tomado en exclusiva. Por eso el control se hace con
  `/opt/redpitaya/bin/monitor 0x40000030 <valor>` — accede a la región de housekeeping,
  no a la del ADC, y no interfiere con una captura en curso.
- Ciclo completo `on`→`off`→`off` (idempotencia) probado disparando los `.service` a
  mano, registro confirmado en cada paso, `streaming-server` sin interrupciones. (El
  LED en sí nunca se vio prender — ver nota de 2026-07-15 más arriba, esta prueba
  validaba el ciclo de los timers, no el LED físico.) **Desactualizado:** esa prueba
  fue antes de agregar el `overlay.sh v0.94` incondicional al script (necesario tras el
  hallazgo de que el registro solo existe en el bitstream default). Con analizador
  lógico se confirmó que, sin un chequeo de estado previo, pedir `on`/`off` ya estando
  en ese estado igual reprograma la FPGA y genera el mismo pulso espurio de tri-state
  (~800ms) que un cambio de estado real — se agregó un archivo de estado local
  (`/root/starlink_remoto/estado`) para saltar la reprogramación cuando no hace falta.
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

No se implementó todavía "volver a `stream_app` y reiniciar
`streaming-server`" después del toggle — eso depende del pulso del relé
biestable (ver pendiente de abajo), que corta la dependencia del bitstream
apenas se pulsa, así que puede no hacer falta reiniciar nada automáticamente.

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

**Pendiente para la próxima sesión, antes de llevarlo a producción:**

1. **[RESUELTO 2026-07-23] El mux no persiste un reboot** — al reiniciar la
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
   seguridad idempotente. **Validado en placa real (10.42.0.180) con reboot
   real:** la unit corrió sola al boot (`systemctl status` → `Finished`,
   exit 0), togglé el relé una sola vez de forma aislada (confirmado con
   analizador — un solo pulso limpio, sin pedido de `on`/`off` de por
   medio), y después `control_starlink.sh off`/`on` corridos a mano
   funcionaron correctos: `off` tomó el atajo (ya estaba en ese estado),
   `on` pulsó una sola vez sin `ADVERTENCIA` y quedó confirmado por HW
   (LED). Falta probar con los timers reales (`starlink-rele-on/off.timer`)
   disparando solos, no invocando el script a mano.
2. **[RESUELTO/CORREGIDO 2026-07-23] Cableado directo a la Red Pitaya, no a
   través de la Click Shield** — esta nota estaba mal desde que se escribió:
   el cableado siempre fue a través de la Click Shield (con su traductor de
   nivel), nunca directo al pin 3 del conector E2 sin pasar por la shield.
   Confirmado por el usuario: apenas se identificó que `PS_MIO10` andaba
   como se buscaba, se cableó directo *desde la shield* hacia el módulo del
   relé — todas las pruebas de esta sesión (round-trip de bitstream,
   persistencia de mux, auto-corrección al boot) fueron con ese cableado,
   no con uno que bypasee la shield. No hay pendiente real acá.
3. **[Atendido por el diseño del punto 1] El propio cambio de mux genera un
   pulso único en el pin** — pasa una sola vez por reboot (cuando se
   reconfigura por primera vez), no en cada `on`/`off` dentro del mismo
   boot. Con el reconfigurado aislado en `starlink-mux-ps10.service`, ese
   toggle único queda absorbido antes de cualquier pedido real de
   `on`/`off` (que decide según el feedback real, no según lo que se pidió) —
   no debería volver a mezclarse con un pulso intencional salvo que la
   unit de boot falle.

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

## Pendientes (histórico, hardware ya resuelto)

- Confirmar el comportamiento fail-safe deseado del relé real.
- Decidir si esta carpeta se fusiona con `scripts_campo_comun/` (infraestructura
  compartida) una vez que el relé esté instalado, o queda separada.
