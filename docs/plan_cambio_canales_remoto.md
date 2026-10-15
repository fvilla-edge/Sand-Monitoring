# Diseño — cambiar mono/dual desde Losant

Estado: **implementado y probado en la placa de pruebas** (2026-10-06); faltan pruebas 4, 6 y 7 y algunos casos de la 2 (fallo forzado, cruce con el lock y corte de eth0 ya están, 2026-10-07). Decisiones del usuario:
modo en `config_campo.json` (no drop-in de systemd), el comando lleva solo
`canales` (la decimación sale sola: mono 32, dual 64) y Losant recibe el
resultado del último cambio.

## Qué hace y qué no

- Cambia `modo-evento` entre **mono** (solo IN1) y **dual** (IN1 + IN2 como
  sensor independiente, `docs/plan_in2_independiente.md`).
- Solo se reinicia `modo-evento`: hueco de ~1-2 min en el CSV (igual que
  cualquier reinicio). El cartero, el resumen a Losant, el panel solar y
  Starlink siguen andando.
- El comando solo llega con Starlink encendido (horario del relé).
- No cambia el bitstream ni el software: si la placa tiene el bitstream
  viejo, en dual mide solo el IN1 (el C++ ya lo avisa) y el resultado del
  cambio lo informa.

## Piezas

### 1. Fuente del modo: `config_campo.json`

- Clave nueva `modo_evento.canales` (1 o 2, default 1). `fusionar_config.py`
  conserva el valor de la placa en las actualizaciones.
- `supervisor_eventos.sh arrancar` la lee con `cfg.py`. Si existe la
  variable `CANALES` (drop-in puesto a mano) gana la variable, para pruebas;
  la unit deja de traer `Environment=CANALES=1`.
- **Sin `daemon-reload`** para cambiar de modo (fue lo que reinició las dos
  placas el 1/10): cambiar = escribir la clave + `systemctl restart`.
- Escritura segura: `cfg.py --poner modo_evento.canales 2` escribe a un
  temporal en la misma carpeta, `fsync`, `rename` atómico y `fsync` de la
  carpeta. Nunca queda un `config_campo.json` a medias (hoy vimos un archivo
  recién escrito quedar en ceros después de un cuelgue).

### 2. Comando de Losant `canales`

- Payload `{"canales": 1}` o `{"canales": 2}`. Lo recibe el cartero
  (`panel_solar_ble/publicar_losant.py`, mismo lugar que `capturar`).
- Valida: `canales` en {1, 2}; si no, lo ignora y lo deja en el log y en el
  atributo de resultado.
- Lanza `cambiar_canales.sh N` **desacoplado** con `systemd-run
  --unit=cambiar-canales` (mismo esquema que `cambiar_modo.sh`): sobrevive a
  un corte de Starlink y a un reinicio del cartero; si ya hay un cambio en
  curso, `systemd-run` rechaza el segundo.

### 3. `scripts_campo/cambiar_canales.sh N`

1. Toma el lock del relé (`/run/lock/starlink_rele.lock`, el mismo de
   `control_starlink.sh` y `aplicar_actualizacion.sh`), espera hasta 200 s.
2. Si `modo-evento` no está habilitado (modo clásico), no hace nada:
   resultado `error: modo clasico`.
3. Si ya está en N (según `/run/modo-evento/medicion`), resultado
   `ok N (sin cambio)`, sin reiniciar.
4. Guarda el valor anterior, escribe `modo_evento.canales = N`,
   `systemctl restart modo-evento`.
5. Espera (tope 4 min) el primer `ESTADO` del arranque nuevo **y** que
   `/run/modo-evento/medicion` diga `canales=N`. No lee registros de la FPGA
   durante el arranque (cuelga la placa).
6. Si no llega: vuelve al valor anterior, reinicia otra vez y deja
   `error: ... (volvio a M)`.
7. En dual, si el log del arranque dice "bitstream sin calculo del IN2",
   resultado `ok 2 (sin IN2 en la FPGA)`.
8. Log en `logs_campo/cambiar_canales.log`; resultado en
   `logs_campo/cambio_canales_estado` (una línea, escritura atómica).

### 4. Resultado en Losant

- `resumen_modo_evento.py` lee `cambio_canales_estado` y manda
  `me_cambio` (texto), por ejemplo `"ok 2 2026-10-06T20:15Z"`,
  `"error: no midio en 4 min (volvio a 1) ..."`. Junto con `me_canales` y
  `me_dec`, que ya se mandan cada minuto.
- Crear el atributo `me_cambio` (String) en `test_SC` y en el Device de
  campo.

## Riesgos y cómo se cubren

| Riesgo | Cobertura |
|---|---|
| Cambio cruzado con `hora_on`/`hora_off` del relé (que también para modo-evento) | lock compartido |
| Corte de Starlink o del cartero en medio | `systemd-run` desacoplado |
| Dos comandos seguidos | unidad única `cambiar-canales` |
| Config a medias por cuelgue | escritura atómica + fsync |
| El modo nuevo no arranca | vuelta automática al anterior |
| Placa en modo clásico | no hace nada, lo informa |
| Bitstream viejo en dual | mide IN1, lo informa |

## Pruebas (placa de pruebas, Device `test_SC`)

1. `cfg.py --poner`: valor nuevo, valor inválido, permisos; archivo siempre
   válido (también cortando el proceso en el medio).
2. `cambiar_canales.sh` a mano: 1→2, 2→1, 2→2 (sin cambio), con modo
   clásico, forzando un fallo (para ver la vuelta automática).
3. Comando desde Losant: mono→dual→mono, viendo `me_canales`, `me_dec`,
   `me_cambio`.
4. `ip link set eth0 down` en medio del cambio (como un corte de Starlink).
5. Dos comandos seguidos.
6. Cambio mientras `control_starlink.sh` tiene el lock.
7. Dual con el bitstream viejo.

## Instalación en campo

Va junto con el resto del IN2 (etapa 9 del plan del IN2): la unit cambia
(sin `Environment=CANALES`), así que se instala con la captura parada y un
solo `daemon-reload`. Anotar en `scripts_campo/plan_campo/actualizar_placa_campo.md`.

## Bitácora

- 2026-10-06: implementado. Lab (`rp-f0fd8c`, respaldo
  `/root/respaldo_canales_remoto_20261006/`): clave agregada con
  `fusionar_config.py` (conserva `gcs.habilitado: false` del lab), dual por
  config (sin drop-in). A mano: pedir el modo actual -> `ok 2 (ya estaba)`
  sin reiniciar; 2->1 `ok 1` en 30s; segundo pedido con uno en curso ->
  rechazado. `me_cambio` en el resumen. Desde Losant (`test_SC`, usuario):
  dual->mono->dual, `ok` los tres (20:15, 20:17, 20:18 UTC). Queda en dual
  para la noche (etapa 8 del plan del IN2).
  - Pendiente: corte de eth0 en medio, cruce con el lock del relé, modo
    clásico, fallo forzado (vuelta automática), dual con bitstream viejo.
  - De paso: `fusionar_config.py` ahora hace fsync (archivo y carpeta).
- 2026-10-07: **fallo forzado (prueba 2), OK en las dos variantes**, lab en
  dual pidiendo `1`, con un drop-in temporal `zz_prueba_fallo.conf` (borrado
  al terminar):
  - (a) arranque que falla (`ExecStartPre` con exit 1 si `canales=1`):
    `systemctl restart` falla en el acto -> vuelve a `2` y mide en 33 s.
    No pasa por la espera de 4 min.
  - (b) arranca pero queda colgado sin medir (`ExecStart` con
    `sleep infinity` si `canales=1`): espera los 4 min (12:42:21 -> 12:46:27
    UTC), vuelve a `2` y mide en 28 s. Total ~4,5 min sin medir.
  - Las dos dejan `error: no midio con canales=1 (volvio a 2)` en
    `cambio_canales_estado` y `modo_evento.canales=2` en el config.
- 2026-10-07: **cruce con el lock del relé (prueba 6), OK**, lab, objetivo
  del relé "on" (lectura directa, el relé no para la captura):
  - (A) lock tomado 60 s a mano (`flock ... sleep 60`), pedido `1`: espera,
    toma el lock al soltarse (12:51:18) y `ok 1`. De paso el reconciliador
    (12:50:25) esperó detrás del cambio y leyó el relé al terminar (12:51:46).
  - (B) pedido `2` y a los 4 s `starlink-aplicar-objetivo`: el relé esperó
    al cambio (12:51:59 -> 12:52:25) y después `OK ya está en on`.
  - (C) lock tomado 215 s, pedido `1`: a los 200 s `error: lock del rele
    ocupado (control_starlink?), sin cambio`, sin reiniciar modo-evento,
    config sigue en `2`.
  - Sin probar (sale del código): `control_starlink.sh` espera el lock solo
    180 s, y un cambio que falla lo retiene ~8,5 min (4 min + vuelta). Si
    eso cae en `hora_on`/`hora_off`, el timer del relé se rinde y queda para
    el reconciliador (confirmación doble, ~10 min más). Aceptado por el
    usuario (2026-10-07): el reconciliador está para eso.
- 2026-10-07: **corte de eth0 en medio del cambio (prueba 4), OK**, lab
  dual -> mono con `/root/prueba_eth0/prueba3_eth0.sh` (nohup en la placa:
  lanza el cambio, a los 5 s `ip link set eth0 down`, a los 90 s up). El
  cambio siguió solo con la red caída y dio `ok 1` (13:13:54 UTC); la IP
  volvió igual. Tardó 100 s en vez de ~30 s porque el primer arranque murió
  por SIGSEGV del vendor y lo relanzó systemd a los 60 s. Core: hilo
  principal en `ADCStreamClient::startStreaming()` ->
  `requestStopStreamingCommon` (copia de `std::string`), el mismo bug del
  vendor visto en julio con Python; distinto del de `connect()` que ya se
  parcheó. 1 SEGV en 24 arranques desde el boot. Que coincida con eth0
  abajo es una sola muestra.
- 2026-10-15: **dual con el bitstream viejo (prueba 7), OK**, en el lab con
  el paquete integrado (rama `ensayo-integracion-20261015`, IN2 + modos
  Starlink + float). Mono por comando, bitstream `7f23f7d` a mano (parar
  captura, copiar, `sync`, arrancar), `{"canales": 2}` desde `test_SC`:
  `ok 2 (bitstream sin IN2: mide solo IN1)` en 29 s, log de la captura
  "bitstream sin calculo del IN2 (ID 0x00000000)", dec 64 al 100 %, sin
  campos `_in2` en el resumen y el CSV del IN2 sin filas nuevas. Con el
  bitstream del IN2 de vuelta (ID `0x534D0002`) los `_in2` vuelven al
  segundo minuto.
  - Pendiente chico (Losant puede confundir): con el bitstream viejo
    `me_canales` dice `2` aunque se mida solo el IN1; y si el bitstream se
    cambia sin pasar por `cambiar_canales.sh` (a mano o
    `revertir_bitstream.sh`), `me_cambio` queda con el mensaje viejo.
    Propuesta: que `me_canales` informe lo que realmente se mide.
  - Ojo: el primer resumen después de pasar a dual no trae los `_in2` (el
    lector arranca al final del CSV); vienen desde el segundo minuto.
- 2026-10-15: **`cfg.py --poner` y valores inválidos (prueba 1), OK**, lab
  con el paquete integrado.
  - Valores inválidos, sistema real: clave inexistente (hoja o rama) ->
    `No existe la clave`, rc 1, config igual (md5); `cambiar_canales.sh`
    con `3`, `dos` o sin argumento -> uso, rc 1; desde `test_SC`
    `{"canales": 3}`, `{"canales": "dos"}` y `{}` -> "payload invalido",
    sin cambio. Valor inválido escrito en el config (`"tres"`) -> el
    supervisor avisa "canales invalido ('tres'), se mide en mono" y mide
    en mono; `cambiar_canales.sh 2` lo arregla (`ok 2` en 28 s) y el config
    queda idéntico al de antes.
  - Escritura atómica, copia aislada (`/root/prueba_cfg_atomico.sh`, no
    toca el config real): proceso matado antes del rename y en el fsync ->
    queda el config viejo; el `.tmp` que sobra se pisa en la siguiente
    escritura. Config inmutable (`chattr +i`; como root los permisos no
    frenan) -> `PermissionError`, rc 1, queda el viejo (y el `.tmp`).
    100 escrituras matadas al azar entre 383 y 702 ms (una completa tarda
    639 ms en la placa) -> el config siempre fue JSON válido. 7/7.
- 2026-10-15: **cambio con modo clásico (prueba 2, ese caso), OK**, lab con
  el paquete integrado. `cambiar_modo.sh clasico` (6 s) y después
  `cambiar_canales.sh 1`: `error: modo clasico (modo-evento deshabilitado),
  sin cambio` en el acto, config igual (md5, sigue en `2`), modo-evento sin
  arrancar. En Losant: `me_activo = false` y `me_cambio` con el error.
  Vuelta con `cambiar_modo.sh evento` (29 s): dual con el IN2 (ID
  `0x534D0002`), sin reinicios. Con esto quedan hechas todas las pruebas
  del plan (la 5, dos comandos seguidos, ya estaba el 6/10: el segundo se
  rechaza).
