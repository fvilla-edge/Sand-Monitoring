# Diseño — cambiar mono/dual desde Losant

Estado: **diseño, sin implementar** (2026-10-06). Decisiones del usuario:
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
