# Plan: de equipo de demo a equipo de campo (y vuelta)

Pedido (24/11/2026): la placa de laboratorio (`rp-f0fd8c`) viaja al sur
**preparada como demo** para mostrar a clientes (Oscilloscope, DFT, Arena) y
**después ese mismo equipo se instala en campo**. Hay que probar el cambio
demo → campo (y campo → demo) antes de que salga.

Rama: `demo-presentacion` para este plan; lo que haya que programar va en una
rama nueva.

## 1. Lo incómodo primero

- **La placa de lab no es una placa de campo con la demo encima.** Es la de
  pruebas: tiene software y configuración de laboratorio. El cambio es
  *convertir el lab en placa de campo*, no solo "pasar a modo evento".
  Inventario de solo lectura 24/11
  (`datos_campo/inventarios/inventario_rp-f0fd8c_demo_20261124.txt`) contra el
  de campo:
  - **SSH con `root`/`root` de fábrica y password abierto.** Con Starlink
    queda expuesta a internet: el hardening (`setup_placa.md` 4b: solo clave,
    `fail2ban`) es obligatorio antes de campo.
  - **Losant y GCS del lab:** `losant_config.py` y `credenciales_gcs.json`
    son los de la placa de pruebas (Device `test_SC`). En campo tiene que
    reportar como un Device de campo.
  - `config_campo.json` del lab es mínimo (sin las secciones que tiene campo).
  - Ramas de prueba en `/root` (`prueba_eth0`, `tmp_compilar_csv`, …) y la
    demo (`demo_presentacion`, Arena en `/opt/redpitaya/www/apps`,
    `fpga.sh` parcheados, Starlink deshabilitado por `lab_demo.sh`).
  - **Hardware** (no se arregla por software; ver `reference_placa_pruebas`):
    RTC DS3231 (la de campo lo tiene soldado), cableado/capacitor del relé de
    Starlink, ESP32 del panel solar. Hay que confirmar qué lleva esta placa
    antes de salir.
- **Hallazgo que afecta a la placa de campo actual (PAD-118)** [Seguro en el
  lab, Probable en campo]: abrir la **pantalla de inicio** de la web de la
  placa (es la app `main_menu`) recarga el FPGA con v0.94. Si `modo-evento`
  está corriendo, eso es recargar el FPGA debajo de la captura = el escenario
  del cuelgue por watchdog. Lo mismo al abrir Scope/DFT. En el lab se vio
  (24/11 12:46:03: la captura leyó 0 y abortó). En campo nadie abre la web
  normalmente, pero el equipo que salga como demo + campo **sí** va a tener
  gente abriéndola. Ver Fase 2, paso 6.

## 2. Decisiones del usuario (24/11)

1. **El cambio lo hacemos nosotros, remoto por SSH**, con la placa ya en el
   sur. => el script tiene que sobrevivir a un corte de SSH (lanzado con
   `systemd-run`/`nohup`), verificarse solo y no dejar nunca el equipo a medias.
2. **Device nuevo en Losant (ej. `SC2`) y carpeta propia en GCS.**
3. ~~**Ida y vuelta:** demo → campo → demo → … tantas veces como haga falta.~~
   **Cambiada el 24/11 (tarde): solo ida, demo → campo.** El equipo de campo
   nunca vuelve a demo (la demo es un caso especial por la presentación).
   => el comando `equipo` de Losant acepta solo `{"modo":"campo"}`; `demo`
   queda solo por SSH, para preparar el equipo en el lab. Se mantiene la
   vuelta automática a demo si campo no queda andando (estado conocido que
   sigue recibiendo comandos de Losant, para reintentar).
4. **Web en campo: bloquear la recarga.** Con `modo-evento` activo, los
   `fpga.sh` (pantalla de inicio, Scope, DFT) no recargan el FPGA y la web
   avisa; la captura nunca se interrumpe por abrir la web.
5. **Hardware: igual que el equipo de PAD-118** (Starlink + relé con su
   cableado/capacitor, panel solar con ESP32, RTC DS3231, pendrive, sensores
   IN1/IN2). La placa de lab no tiene RTC soldado: es trabajo físico antes de
   que salga (`setup_placa.md` 5b, 5, 6).
6. **En la demo la placa va a estar en la red del cliente.**

**Consecuencia de 1 + 3:** lo pesado (paquete de campo, config `SC2`,
hardening) se hace **una sola vez, en la empresa, antes de que salga**: con
SSH abierto a internet no puede viajar con `root`/`root`. El equipo queda
como **placa de campo con la demo encima**, y el cambio remoto es solo
`demo` ↔ `campo` (modo clásico + Arena ↔ modo evento), que es liviano y
reversible.

**Punto abierto: cómo se llega a la placa estando en la red del cliente.**
[Seguro] A `rp-f0fbda` se entra por la IP pública de Starlink, sin VPN (VPN
descartada por el usuario, `starlink_remoto/HISTORIAL_STARLINK.md`). Detrás
del router del cliente no hay SSH entrante salvo que el cliente redirija un
puerto. Lo que sí funciona detrás de cualquier router es lo saliente: la
conexión con Losant ya recibe comandos (`canales`, `modo`, `starlink`).
**Decidido 24/11: comando de Losant.** Opciones que se evaluaron:
- **Comando de Losant `equipo` (`demo`/`campo`)** (elegida): mismo patrón que
  `canales` (tag o botón, la placa ejecuta el script y responde con
  `RESULTADO`). No depende de la red ni de abrir puertos.
- SSH por un puerto que redirija el cliente (depende de su IT).
- Hacer el cambio recién al instalar en campo, cuando ya hay Starlink
  (SSH por su IP pública, como hoy). Ojo: en demo `lab_demo.sh` deshabilita
  los servicios de Starlink (leían el FPGA y competían con la web al
  arrancar): al pasar a campo hay que reactivarlos antes de depender de la
  antena.

## 3. Estado objetivo

- **Demo** (hoy, 24/11): modo clásico, `lab_demo.sh aplicar` (Starlink
  deshabilitado), Arena instalada, web simplificada, sin modo evento.
- **Campo**: lo mismo que `rp-f0fbda` = paquete integrado de campo vigente
  (tag `campo-2026-10-21b`, `ff47f40`) + bitstream de campo (md5 `b34cd26f`)
  + config de campo propia de esta placa + hardening + modo evento.
  Se instala con el **procedimiento ya probado** de la guía de campo
  (`scripts_campo/plan_campo/actualizar_placa_campo.md` sec. 6-7: paquete,
  `aplicar_actualizacion.sh` con vuelta atrás automática, ajustes 7.3,
  inventario). No se inventa otro camino.

## 4. Fases

### Fase 0 — Respaldo y foto del estado demo
- Respaldo completo (`tar` de `/root` + `/etc` + `/opt/stream_app` + las
  carpetas de `/opt/redpitaya/www/apps` que toca la demo) en el pendrive y
  copia en la PC (como 7.1).
- Inventario de solo lectura guardado como `inventario_rp-f0fd8c_demo_<fecha>`.

### Fase 1 — Script de transición + comando de Losant (rama nueva)
- Script en la placa, lanzado con `systemd-run` (no depende de quién lo
  llamó), con log y `RESULTADO` como `cambiar_canales.sh`; si falla a mitad
  vuelve al estado de partida.
- **Disparo: comando de Losant `equipo`** `{"modo": "demo"|"campo"}`, con el
  mismo camino que `canales` (lo recibe el cliente MQTT de
  `panel-solar-informe`, que corre en los dos modos). Atributo nuevo en el
  Device (ej. `me_equipo` = `demo`/`campo`) en el resumen, para ver en Losant
  en qué modo quedó. SSH por Starlink queda como respaldo en campo.
- A revisar al programarlo: el comando no puede llegar dos veces ni pisarse
  con `canales`/`modo` (lock compartido, como el del relé).
`demo_presentacion/cambiar_equipo.sh demo|campo|estado` (nombre a definir),
que solo **orquesta** lo que ya existe:
- `campo`: parar `arena-demo`; `instalar_web_arena.sh quitar` (devuelve los
  `fpga.sh`, `desktop.js`, lista de apps); `lab_demo.sh revertir` (Starlink);
  `cambiar_modo.sh evento`; verificar.
- `demo`: `cambiar_modo.sh clasico`; `lab_demo.sh aplicar`;
  `instalar_web_arena.sh instalar`; verificar.
- `estado`: una línea por cosa (modo, Starlink, Arena, FPGA, Losant
  reportando).
El paquete de campo, la config y el hardening **no** van en este script: son
una vez (Fase 2).

### Diseño del cambio (decidido 24/11: dejar config y reiniciar)

- `demo_presentacion/cambiar_equipo.sh demo|campo` (se desacopla con
  `systemd-run`, unidad `cambiar-equipo`; toma el lock del relé y rechaza si
  hay un cambio de canales/modo en curso):
  1. deja escrito el pedido (`objetivo`, `anterior`, `intento`) en la SD;
  2. **campo**: habilita `modo-evento` y los servicios de Starlink que
     estaban antes de la demo; **demo**: deshabilita `modo-evento` y los de
     Starlink (guarda cuáles para la vuelta, como `lab_demo.sh`). Solo
     `enable/disable`, sin parar ni arrancar nada en vivo;
  3. `sync` y **reinicia**.
- `verificar-equipo.service` (oneshot al arrancar): si hay un pedido, espera
  hasta 4 min el estado esperado **sin leer el FPGA** (journal,
  `loaded_fpga.inf`, `systemctl`):
  - campo: `modo-evento` activo con un `ESTADO muestras=`, bitstream propio,
    `arena-demo` inactivo, Starlink habilitado;
  - demo: `modo-evento` inactivo, v0.94, `sysinfo.json`, nginx activo.
  OK → `ok <modo>`. Falla en el 1er intento → vuelve a la config anterior y
  reinicia una vez más; falla en el 2do → `error: …` y no reintenta (sin bucle).
- Resultado en una línea (`log_dir/cambio_equipo_estado`) que el resumen
  manda como **`me_equipo`**; comando de Losant **`equipo`**
  `{"modo": "demo"|"campo"}` en `publicar_losant.py` (si la placa no tiene
  `demo_presentacion`, como `SC1`, lo ignora).
- **Web protegida en campo:** los `fpga.sh` (inicio, Scope, DFT) no recargan
  el FPGA si `modo-evento` está activo, y `/arena_iniciar` no arranca Arena;
  la página Arena avisa "equipo en modo campo". Arena queda instalada en los
  dos modos (no se escribe `/opt/redpitaya` en cada cambio).
- Pruebas en el lab con `test_SC`.

### Fase 2 — Primera conversión a campo, en el lab
1. Aplicar el paquete de campo vigente con `aplicar_actualizacion.sh` (sec. 6-7).
2. Config de campo de esta placa: Device nuevo en Losant (ej. `SC2`, con
   los atributos de `SC1` + `me_equipo`, y el workflow del comando `equipo`),
   carpeta propia en GCS, umbral, canales, modo Starlink.
3. Hardening SSH + `fail2ban` (`setup_placa.md` 4b), dejando la clave de la PC.
4. Limpiar ramas de prueba de `/root` (con respaldo).
5. Hardware que corresponda (decisión 4): RTC, relé, ESP32.
6. Protección de la web en campo (decisión 4): los `fpga.sh` de
   `main_menu`/Scope/DFT **no recargan el FPGA si `modo-evento` está activo**
   y la web muestra un aviso. [Probable] También le serviría a `rp-f0fbda`
   (sería otro paquete y otra decisión; no se toca sin pedido).
7. Inventario y diferencia contra `rp-f0fbda` (solo deben diferir el config
   propio, credenciales y hostname).

### Fase 3 — Ensayo en el lab (solo ida desde el 24/11)
Con la decisión 3 cambiada queda: demo → campo **por comando de Losant**
(el camino real) y el corte de luz a mitad de ese cambio. Lo de abajo era
el ensayo de ida y vuelta:
- demo → campo → (reinicio) → campo midiendo y reportando a Losant →
  demo → (reinicio) → demo con Arena/Scope/DFT → campo otra vez.
- En cada paso: `estado`, uptime (sin reinicios inesperados), sin cuelgues,
  Losant al día, la web en el modo que corresponde.
- Probar el corte a mitad de camino (SSH cortado, corte de luz) como en la
  sec. 6: el equipo tiene que quedar en uno de los dos estados, nunca a medias.

### Fase 4 — Dejarlo como demo para el viaje
Lista del día del cambio (SC2 + demo): `docs/procedimiento_paso_a_sc2.md`.
- `cambiar_equipo.sh demo` + `HOJA_DEMO.md` completa.
- Hoja corta "de demo a campo" para quien haga el cambio en el sur
  (decisión 1), con el equivalente a la sec. 7.5 (primeros días en el sitio).

## 5. Calendario

Demo el **10/12**; hoy 24/11. Las fases 0-3 se hacen en el lab y no dependen
de la notebook. Si la decisión 1 es "lo hace alguien en el sur sin nosotros",
el ensayo de la Fase 3 tiene que hacerlo esa persona (o alguien con la hoja)
antes de que salga el equipo.

## Bitácora

- 24/11: plan escrito a partir del inventario de solo lectura del lab y la
  guía de campo. Decisiones 1-4 tomadas por el usuario el mismo día; después:
  hardware igual que PAD-118, en la demo red del cliente, y el cambio se
  dispara por **comando de Losant** (no hay SSH entrante detrás del router del
  cliente). Nada ejecutado.
- 24/11 ~15:07 UTC — **Rama `equipo-demo-campo`, instalado en el lab (sin
  probar el cambio todavía):** `demo_presentacion/cambiar_equipo.sh` +
  `verificar-equipo.service` (habilitado), comando `equipo` en
  `publicar_losant.py`, `me_equipo`/`me_equipo_cambio` en
  `resumen_modo_evento.py` (lab = main antes de pisar; copias
  `*.antes_equipo`), web con la protección de modo campo (`fpga.sh` de inicio,
  Scope y DFT salen sin recargar si `modo-evento` está habilitado o activo;
  `/arena_iniciar` responde `CAMPO`). Detalle: la condición es "habilitado",
  no "activo": al arrancar, `modo-evento` pasa hasta ~90 s en activating.
  Lab: equipo `demo`, `unidades_previas.txt` = mux PS10 + reconciliador +
  ventana. El resumen ya manda `me_equipo = demo`. Falta: atributos en
  `test_SC` y la primera prueba.
- 24/11 15:08-15:22 UTC — **Primera prueba demo → campo (SSH): `ok campo`**
  (reinicio, verificación OK a los ~2 min, modo evento midiendo, Starlink
  habilitado). **La protección de la web NO alcanzaba**:
  1. Abrir la pantalla de inicio en campo (15:13) **descargó el bitstream**:
     el lanzador de apps (`/bazaar?start=`, dentro del nginx de Red Pitaya)
     corre `/opt/redpitaya/sbin/rmoverlay.sh` (rmdir del overlay `Full`)
     ANTES de `fpga.sh`. Captura leyendo PL vacío: "external abort" del
     kernel, 0 % de muestras. Sin cuelgue; recuperado con reinicio.
  2. Con `rmoverlay.sh` protegido, el lanzador **igual arranca el backend**
     (`main_menu`), que escribe registros de v0.94 sobre el bitstream propio:
     overlay intacto pero contadores basura (412 % muestras, 40870 ventanas
     en 10 s) y un abort. Recuperado con reinicio. (El reconciliador de
     Starlink, que leyó el relé en el mismo minuto, se descartó: en los otros
     arranques leyó sin aborts.)
  3. **Solución:** chequeo en la entrada `/bazaar` de nginx
     (`demo_presentacion/web/bazaar_campo.conf`, `access_by_lua`): en campo
     `?start=` responde 409 "equipo en modo campo" sin que el lanzador haga
     nada. Quedan además `rmoverlay.sh` y los `fpga.sh` protegidos.
     Verificado en campo: inicio/Scope/DFT → 409, `/arena_iniciar` → CAMPO,
     página Arena "equipo en modo campo", Scope queda en "LOADING…"; overlay
     intacto, 0 aborts, captura 100 % sin saltadas. `/bazaar?apps=` (listado)
     deja cargadas las librerías de la_pro/streaming_manager sin efecto en la
     captura.
  - **[Seguro en el lab, Probable en PAD-118]: en la placa de campo actual
    abrir la pantalla de inicio de la web descarga el bitstream con la
    captura corriendo.** No se tocó `rp-f0fbda`.
- 24/11 tarde — **Decisión: solo ida (demo → campo).** Placa del lab ahora
  por LAN (`192.168.0.134`), arrancó sola en campo (captura 100 %, 0 aborts).
  Comando `equipo` limitado a `{"modo":"campo"}` (`publicar_losant.py`,
  instalado en el lab y `panel-solar-informe` reiniciado, conectado). Placa
  pasada a demo por SSH para probar demo → campo por Losant.
- 24/11 17:18-17:22 UTC — **demo → campo por comando de Losant (test_SC): OK.**
  `equipo {"modo":"demo"}` (17:18:34) ignorado ("solo se acepta campo");
  `equipo {"modo":"campo"}` (17:18:59) → reinicio 17:19:12 → `ok campo`
  17:22:28 (~3,5 min de punta a punta). Captura 100,1 %, 0 saltadas, 0
  aborts, FPGA `stream_app_propio`, `/bazaar?start=` → 409. Losant recibió
  `me_equipo=demo` / `reiniciando hacia campo` durante el arranque y después
  `me_equipo=campo` / `ok campo 2026-11-24T17:22:28Z`. (Antes, campo → demo
  por SSH 17:15: `ok demo`.)
- 24/11 ~17:27 UTC — **Corte de luz a mitad de demo → campo (comando Losant +
  desenchufe a los 3-5 s): el equipo NO quedó a medias, pero tardó ~8 min y
  terminó en demo.** El pedido (`objetivo=campo intento=1`, escrito con sync)
  sobrevivió; los `systemctl enable` de `config_campo` NO (symlinks de /etc
  sin sync). Al arrancar: modo-evento deshabilitado → el verificador esperó
  5 min → "volviendo a demo" → reinicio → "error: no anduvo campo, volvio a
  demo". Starlink deshabilitado, `unidades_previas.txt` intacto (17:24:39,
  3 unidades). El final del log quedó con bytes nulos (escritura sin sync).
  Journal volátil: no hay logs de los arranques anteriores. Después del
  corte la placa tardó ~5 min en responder (reloj sin RTC: horas del arranque
  intermedio no confiables).
  **Hallazgo latente [Probable]:** `config_campo` borra `unidades_previas.txt`
  y lo sincroniza, pero los enable no; un corte en ese instante pierde la
  lista de Starlink y, al volver a demo, se graba vacía → el próximo campo
  daría "ok" sin Starlink (`ok_campo` no lo mira).
- 24/11 ~17:40 UTC — **Arreglos en `cambiar_equipo.sh`:** (1) `sync` después
  de los enable/disable; (2) `unidades_previas.txt` se borra recién con campo
  verificado (no en `config_campo`); (3) `ok_campo`/`falta_campo` exigen las
  unidades de Starlink de la lista habilitadas; (4) `verificar`: si la config
  del objetivo no está en disco, la reaplica y reinicia una vez
  (`reaplicado=1` en el pedido, sin bucles).
  **Corte simulado** (pedido `objetivo=campo intento=1` con config de demo
  intacta + reboot, 17:44): "reaplicando config de campo" → reinicio →
  `ok campo` 17:46:16 (~2,3 min). Starlink habilitado, lista borrada,
  captura 100 %, 0 aborts.
- 24/11 ~18:00 UTC — **Corte de luz REAL repetido con el arreglo: OK.**
  Comando Losant `equipo {"modo":"campo"}` + desenchufe a los 3-5 s. Al
  enchufar: "la config de campo no esta en disco" → reaplicada → reinicio →
  `ok campo` (reloj de la placa 18:02:21, ~4 min atrasado respecto de la PC:
  sin RTC y NTP aún sin sincronizar). Starlink habilitado, lista borrada,
  FPGA `stream_app_propio`, captura 100 %, 0 saltadas, 0 aborts.
- 24/11 tarde — **Device `SC2` creado por el usuario** (misma aplicación).
  Lectura por API: 71 atributos y tags idénticos a `SC1` (`canales=2`,
  `in2_modo=independiente`, `modo_starlink=permanente`); faltan
  `me_equipo`/`me_equipo_cambio`. Credenciales probadas con una conexión
  MQTT de prueba desde la placa (copia temporal en /run, borrada): conecta.
  La placa sigue como `test_SC`. Credenciales fuera del repo
  (`~/credenciales_losant/sc2.txt`, 600). Workflows de SC2 no verificables
  con el token (scope device.get/patch).
- 24/11 tarde — **SC2 completo en atributos:** 73 = los 71 de SC1 +
  `me_equipo`/`me_equipo_cambio` (String). Tag `canales=1` (decisión del
  usuario). **Decisiones:** carpeta GCS de SC2 = ~~`campo_sc2/csv_ventanas`~~ → `campo/csv_ventanas` (cambiada el mismo día: la subida ya separa por hostname, `campo/csv_ventanas/rp-f0fd8c/`, y SandVision lo ve sin cambios);
  la placa pasa a SC2 **al final** (junto con hardening SSH, antes de dejarla
  en demo para el viaje). Falta: workflow de SC2 (lo crea el usuario).
- 24/11 tarde — **Comparación lab vs SC1** (sin tocar `rp-f0fbda`): inventario
  nuevo del lab (`datos_campo/inventarios/inventario_rp-f0fd8c_campo_20261124.txt`)
  contra el de SC1 del 20/10 y el tag `campo-2026-10-21b`.
  - Igual a lo instalado en SC1: los 10 archivos que difieren del inventario
    de SC1 son iguales al tag (el inventario de SC1 es anterior al paquete del
    21/10). El binario de captura del lab está compilado del `.cpp` del tag
    (la copia `.cpp` en `/root/scripts_campo/c/` es vieja, cosmético).
    Bitstream lab = `in2_20ac88b` (md5 b34cd26f, tag `campo-2026-10-20`);
    el inventario de SC1 muestra `7f23f7d` [Probable: SC1 lo recibió después
    del inventario; confirmar].
  - Más nuevo en el lab (esta rama): `publicar_losant.py`,
    `resumen_modo_evento.py` (sin efecto sin `demo_presentacion`).
  - **A corregir al pasar a SC2:** `gcs.prefijo` → `campo/csv_ventanas`;
    `url_aviso` del lab apunta a `127.0.0.1:9` (ensayo) → la real de SC1;
    `subir-csv-gcs.timer` **deshabilitado** en el lab (habilitado en SC1);
    `losant_config.py` de SC2; hardening (`sshd_config` + `fail2ban`, no
    instalado en el lab); `rtc-restaurar.service` (con el RTC);
    `wired.network` distinto (el lab tiene DHCP + IPForward/Masquerade para
    la LAN; ver el de campo); limpieza de `/root` (`*.bak*`, `prueba_eth0`,
    `tmp_compilar_csv`, `aplicar_mods_web.py`, `.antes_equipo`).
  - Menores: `bluetooth.service` habilitado en SC1 y no en el lab (el ESP32
    va por USB); timers del relé on/off habilitados en SC1 al 20/10 vs
    `starlink-ventana.timer` en el lab (lo maneja el modo Starlink).
- 26/11 — **Inventario fresco de SC1** en la ventana de las 10:05 AR (solo
  lectura, `datos_campo/inventarios/inventario_rp-f0fbda_20261126.txt`) contra
  el del lab del 24/11 (más una lectura del lab el mismo día):
  - **Hallazgo:** el lab tiene `control_starlink.sh` (cd19c27, 30/9) y
    `ventana_starlink.sh` (1213ff3, 13/10) viejos, sin la mitigación del reset
    del relé (ff47f40) que sí tiene SC1. La comparación del 24/11 lo dio por
    igual al tag: estaba mal. Las pruebas demo->campo del 24/11 (incluido el
    corte de luz) corrieron con esos scripts viejos y sin relé real. Agregado
    al paso 5 de `procedimiento_paso_a_sc2.md`.
  - Red: `wired.network` de SC1 = mismas claves que el lab (cerrado, paso 6).
  - Drop-ins `umbral.conf`, `sin-cpuquota.conf` y journald
    (`persistente.conf` en el lab, `persist.conf` en SC1): en el lab dicen
    UMBRAL=3.4, `CPUQuota=` vacío y journal persistente 200M; en SC1 solo
    hay sha256 [Probable: mismo contenido con otros comentarios, no
    verificado].
  - Ya previsto: `gcs.prefijo`, `url_aviso`, `subir-csv-gcs.timer`,
    `losant_config.py`, `fail2ban`/`sshd_config`, `rtc-restaurar.service`,
    `bluetooth` (no hace falta: ESP32 por USB). Nuevo: `gcs.dias_atras` 7 en
    el lab vs 30 en SC1 (con datos de prueba vaciados da igual; dejar 30).
    `canales` 2 en SC1 (dual) vs 1 en el lab = sigue al tag de cada Device.
  - SC1: bitstream `stream_app_propio`, sin reset desde el boot del 25/11
    17:08 UTC, 0 unidades failed; 9/9 ventanas OK desde el 25/11 19:05 UTC.

