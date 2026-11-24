# Plan: demo con la web de Red Pitaya (presentacion 10/12/2026)

Objetivo: mostrar en vivo, tirando arena, la señal y el espectro del sensor con
las apps web que trae Red Pitaya (Oscilloscope y DFT Spectrum Analyser), con la
interfaz simplificada de `~/web_pitaya`.

- Placa: **laboratorio** (`rp-f0fd8c`). La de campo sigue instalada en PAD-118 y no se toca.
- Conexion el dia de la demo: probablemente **cable directo** placa <-> notebook.
- Decision del usuario (20/11): la placa de laboratorio queda en **modo clasico
  por defecto**; el modo evento se activa a mano solo cuando se quiera usar.

## Como funciona (y por que hay que sacar el modo evento)

- Oscilloscope (`scopegenpro`) y DFT (`spectrumpro`) **no usan el streaming**:
  leen bloques del buffer de adquisicion y al abrirse **cargan su propio bitstream**.
- `modo-evento` usa otro bitstream (`stream_app_propio`) y `capturar_eventos`
  lee el FPGA por `/dev/mem`. Recargar el bitstream mientras se lee el PL
  cuelga la placa (watchdog). Por eso las dos cosas **no pueden convivir**.
- Durante la demo no hay captura de eventos, kurtosis ni datos `me_*` en Losant.
  Lo que se ve es la señal cruda (sin el pasabanda ni la kurtosis del bitstream propio).

| Componente | Choca con la web | Que hacer |
|---|---|---|
| `modo-evento` (+ `streaming-server`, `capturar_eventos`) | Si (riesgo de cuelgue) | `cambiar_modo.sh clasico` (lo deshabilita: no vuelve al reiniciar) |
| Comando "capturar" de Losant | Si (recarga bitstream) | En el lab no corre el escuchador; no mandarlo ese dia |
| `resumen-modo-evento`, panel solar, Starlink (PS_MIO10), indicador (PS_MIO11) | Probablemente no (GPIO del PS, no del FPGA) | Dejarlos; confirmar en el paso 1 |

Cambio de modo (en la placa, como root):

```bash
bash /root/scripts_campo/cambiar_modo.sh clasico   # default del lab / demo
bash /root/scripts_campo/cambiar_modo.sh evento    # volver a medir eventos
journalctl -u cambiar-modo -f                      # seguir el cambio
```

`evento` verifica solo que quede el bitstream propio midiendo.

## Pasos

### 1. Pasar el lab a clasico y prueba en seco
- [x] `cambiar_modo.sh clasico` en el lab (20/11 17:16 UTC, OK).
- [x] Abrir Oscilloscope y DFT con el sensor conectado; tirar arena (OK usuario 20/11).
- [ ] Anotar ajustes que mejor muestran la arena (canal, escala V, base de
      tiempo, span/decimacion del DFT, ventana, waterfall).
- [ ] Confirmar que rele Starlink e indicador siguen funcionando con la app abierta.
- [ ] Probar abrir/cerrar/alternar entre las dos apps varias veces (sin cuelgues).

### 2. Simplificar la web del lab (`~/web_pitaya/instrucciones.md`)
El lab esta **de fabrica** (`black_list_app.js` del 5/7, sin `allowed_root`);
las modificaciones solo estan en la placa de campo.
- [x] **Antes**: corregir el paso 4 de `instrucciones.md`. El script todavia
      tiene los valores del waterfall del ecosistema 2.07 (188px / 220 / 210px).
      Para 3.00 van los de la tabla: canvas 300, holder 320, multiplicador 335,
      escala 305, y tambien `.waterfall_canvas` 300 (y `createWaterfall`/`setSize` en JS).
- [x] Verificar valores de stock en el lab antes de tocar (deberian ser los del 3.00).
- [x] Backups (`.bak`), aplicar, `remount,ro`, Ctrl+Shift+R.
- [x] Revisar (OK usuario 20/11): inicio solo con System, Development, Oscilloscope y DFT; titulo "Edge"; logos; waterfall sin hueco.

### 3. Ensayo de robustez
- [x] Reiniciar la placa en clasico: `modo-evento` no arranca, la web abre sola (20/11 OK).
- [ ] Ida y vuelta `clasico -> evento -> clasico` sin problemas.

### 4. Red con cable directo
- [x] Probar por cable directo (20/11, OK con la PC de trabajo Linux). Si la notebook de la demo es OTRA, repetir ahi:
      perfil de red cableada en modo "compartida con otros equipos" (IPv4 shared).
      En la PC de trabajo ya existe `directo-placa` (`nmcli con up directo-placa`);
      la placa toma una 10.42.0.x (la de campo tomaba 10.42.0.180).
- [x] Entrar por `http://rp-f0fd8c.local/` (la IP puede cambiar). Resuelve por el cable (20/11).
- [ ] Plan B si no resuelve `.local`: ver la IP asignada en la notebook
      (`ip neigh` / leases de NetworkManager).

### 5. Hoja de pasos para el 10/12
Borrador 24/11: **`demo_presentacion/HOJA_DEMO.md`** (incluye Arena). Faltan
los ajustes de Scope/DFT (paso 1) y lo de la notebook (paso 4).
- [ ] Checklist corto: conectar cable, abrir la web, ajustes preseleccionados
      (del paso 1), que hacer si se cuelga (esperar el reinicio del watchdog,
      la placa vuelve en clasico).
- [ ] Despues de la demo: dejar en clasico, o pasar a evento si se va a medir.

## Bitacora

- 20/11: relevamiento de solo lectura del lab (192.168.0.136, uptime 23 min,
  `modo-evento` activo con `stream_app_propio`, web de fabrica, nginx activo,
  watchdog 30 s). Plan acordado; nada ejecutado todavia.
- 20/11 17:16 UTC: lab pasado a **clasico** con `cambiar_modo.sh clasico` -> OK.
  Verificado: sin reinicio (uptime 43 min), `modo-evento` disabled/inactive,
  `loaded_fpga.inf` = `stream_app`, sin `streaming-server` ni `capturar_eventos`;
  resumen, indicador, panel solar y nginx activos.
- 20/11 17:21 UTC: web simplificada aplicada al lab con `~/web_pitaya/aplicar_mods.py`
  (nuevo; verifica stock antes de escribir, .bak de los 21 archivos + favicon,
  conserva CRLF). Stock del lab = tabla 3.00. `black_list_app.js` NO se piso
  con el local (era de 2.07): se inserto solo `allowed_root`. HTTP 200 en todo,
  titulo "Edge". `instrucciones.md` pasos 2-4 y revert actualizados (sin commit).
  Falta: revision visual del usuario (inicio, logos, waterfall).
- 20/11: usuario confirma web OK (inicio con 4 entradas, logos/pestaña Edge, waterfall bien). Paso 2 cerrado.
- 20/11 17:58 UTC: reinicio por SSH en clasico -> vuelve en 39 s; modo-evento disabled/inactive, FPGA de arranque `v0.94` (el default del sistema), sin streaming-server; nginx, resumen, indicador, panel solar y mux PS10/PS11 activos; sin unidades failed; /opt/redpitaya ro; web con mods persiste (HTTP 200 en /, scopegenpro, spectrumpro).
- 20/11 ~18:04 UTC: tras el 1er reinicio la pagina principal quedo EN NEGRO:
  faltaba `/tmp/sysinfo.json`. Causa (journal): al arrancar, `redpitaya_startup`
  (mkoverlay v0.94 + getsysinfo.sh) y `starlink-mux-ps10` (control_starlink.sh ->
  overlay.sh v0.94) cargan el FPGA a la vez; si la recarga de Starlink cae
  mientras corre getsysinfo, overlay.sh borra `loaded_fpga.inf` y getsysinfo no
  escribe nada (ademas lee el DNA del FPGA durante la recarga = riesgo de cuelgue).
  Intermitente: el 2do reinicio salio bien. Ademas: cada vez que se abre
  Oscilloscope o DFT se reprograma v0.94 (~0,5 s), y el reconciliador/ventana de
  Starlink leen el FPGA (0x40000020) -> misma carrera durante la demo.
- 20/11 18:17 UTC: rama **`demo-presentacion`** (solo demo, NO va a campo; no
  toca codigo de produccion). `demo_presentacion/lab_demo.sh aplicar|revertir|estado`
  deshabilita en el lab los servicios de Starlink (mux PS10, reconciliador,
  ventana, rele-on/off) y guarda cuales estaban habilitados en
  `/root/demo_presentacion/unidades_previas.txt` para `revertir`. Aplicado.
- 20/11 18:18-18:23 UTC: 5 reinicios seguidos en modo demo: los 5 con UNA sola
  carga del FPGA, `sysinfo.json` OK, `/get_sysinfo` 200 (530 B), modo-evento off,
  vuelve en 41-45 s. La IP del lab paso de .136 a .133 por DHCP sin reiniciar.

## Estado del lab para la demo (resumen)

```bash
bash /root/scripts_campo/cambiar_modo.sh clasico     # sin modo evento
bash /root/demo_presentacion/lab_demo.sh aplicar     # sin Starlink
bash /root/demo_presentacion/lab_demo.sh estado      # verificar
# volver al estado de pruebas:
bash /root/demo_presentacion/lab_demo.sh revertir
bash /root/scripts_campo/cambiar_modo.sh evento
```
- 20/11 ~19:05 UTC: **cable directo OK** (PC de trabajo, adaptador USB WCH
  `enxdc045a9e9074` via hub). Sin internet: la web solo tiene links de ayuda
  externos, nada que cargue de afuera. Con la placa ya prendida, cambiar el cable
  NO dio enlace (NO-CARRIER, con dos cables distintos); **apagar y prender la placa
  con el cable puesto** lo resolvio. Perfil que se activa solo: `linescout`
  (shared, 192.168.137.1, autoconnect si); placa en 192.168.137.225,
  `rp-f0fd8c.local` resuelve. Ping 0,65 ms; `/`, scopegenpro, spectrumpro 200;
  modo demo intacto, 1 carga de FPGA al arrancar (la 2da = app abierta).
  Sin internet la placa no tiene NTP (no tiene RTC): la hora viene de
  fake-hwclock; no afecta a la web.
  **Procedimiento del dia: conectar el cable a la notebook y RECIEN AHI prender la placa.**
- 20/11: la notebook de la presentacion va a ser OTRA (a definir por el usuario); las pruebas se hacen con la PC de trabajo. Pendiente: repetir paso 4 en esa notebook cuando se sepa cual es (SO, perfil compartido, orden cable->encender).

## Como funciona la conexion directa (resumen para el equipo)

- **La notebook NO necesita internet.** La pagina corre dentro de la placa; la
  notebook solo abre el navegador y le habla a la placa por el cable.
- **Nadie asigna la IP a mano:** la conexion cableada de la notebook se configura
  una vez en modo "compartida con otros equipos" y la notebook le da la IP a la
  placa sola, como un router chico solo para ese cable. (Si la notebook es Windows,
  se configura distinto; ver cuando se sepa cual es.)
- **No es `localhost`, es una red local de dos equipos:** los datos van
  placa -> cable -> notebook y nunca salen a internet. Latencia medida 20/11:
  0,65 ms -> tiempo real.
- Si la notebook ademas tiene internet (WiFi, Starlink), no molesta ni agrega
  lag: el navegador llega a la placa por el cable, no por internet.
- Orden: cable puesto primero, despues prender la placa. Entrar por
  `http://rp-f0fd8c.local/`.
- 20/11 16:18 (hora AR): el usuario no pudo entrar "sin internet". Causa real: el ENLACE del cable se cayo (hub/adaptador re-enumerado 16:18:10, enlace 16:18:14, perdido 16:18:20 y no volvio), no la falta de internet. Riesgo para la demo: adaptador WCH via hub inestable (ya habia dado NO-CARRIER antes). Script nuevo `demo_presentacion/probar_sin_internet.sh` (corre en la notebook: apaga WiFi, verifica sin internet, prueba placa por cable, restaura WiFi).
- 20/11 ~16:25 (hora AR): `probar_sin_internet.sh` corrido con enlace OK: WiFi apagado y SIN internet confirmado; placa en 192.168.137.225 (rp-f0fd8c.local resuelve sin internet); ping 0,36 ms; /, /get_sysinfo, scopegenpro, spectrumpro = 200. WiFi restaurado. Queda demostrado que NO hace falta internet.
- 20/11: el usuario lo probo el mismo en el navegador sin internet: OK. Tema "hace falta internet" CERRADO.
