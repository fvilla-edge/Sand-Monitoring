# Investigacion: kurtosis, area y acumulado en la web de la placa

Pedido (20/11/2026): ver en vivo en la web de la placa, mientras se tira arena,
la kurtosis, el area y el acumulado. Primero investigar si se puede y como;
avanzar de a poco. Rama: `demo-presentacion` (no va a campo).

## 1. Lo que ya existe (no hay que inventarlo)

- **Nuestro bitstream propio (`stream_app_propio`, `/opt/stream_app/fpga.bin`) ya
  calcula area y kurtosis en la FPGA**, por ventana de 50 ms (20 por segundo),
  con el pasabanda, para IN1 (y el IN2 si esta habilitado). Registros
  `0x40000328..0x348` (+ IN2), los lee `capturar_eventos` por `/dev/mem`.
- **`modo-evento` ya produce los numeros en vivo:** `capturar_eventos` escribe
  area y kurtosis de TODAS las ventanas en `ventanas_AAAAMMDD_HH.csv` (en
  `--destino`, hoy `/mnt/usb/eventos`), bajando al archivo **cada ~1 s**.
- Ese acumulador **depende del streaming**: la decimacion y el arranque del
  flujo los configura `streaming-server` (lo que hace `modo-evento`). Sin
  streaming corriendo, la FPGA no cierra ventanas.

## 2. Como funcionan las apps web de Red Pitaya (verificado en el lab, 3.00)

Cada app es una carpeta en `/opt/redpitaya/www/apps/<app>/` con:
- `fpga.sh`: lo que corre al abrirla (Oscilloscope y DFT: `overlay.sh v0.94`).
- `controllerhf.so`: el "backend" en C++ (exporta `rp_app_init/exit/desc`),
  hecho con el SDK de Red Pitaya (`CDataManager`, parametros y señales).
- `index.html` + `js/` + `css/`: el frontend, que habla con el backend por WebSocket.
- `nginx.conf`: rutas extra (ej. Lua que lee un archivo y lo devuelve).

En la placa estan el SDK (`/opt/redpitaya/rp_sdk`: headers + `librp_sdk.a`),
los headers de `librp` y `g++`/`make`/`cmake`: **se puede compilar una app
propia en la misma placa**. Del Oscilloscope/DFT solo esta el `.so` compilado;
su codigo fuente NO esta aca (esta en el repo del ecosistema de Red Pitaya).

[Probable] Corre una sola app por vez (abrir otra descarga la anterior y
recarga su bitstream).

## 3. El limite de fondo

Oscilloscope y DFT necesitan **v0.94**; area/kurtosis estan en **nuestro**
bitstream (basado en `stream_app`). En la FPGA hay uno solo a la vez. Por eso:

- **Ver kurtosis AL LADO del osciloscopio de Red Pitaya** exige meter nuestro
  bloque dentro de v0.94 (FPGA) **y** cambiar el codigo del Oscilloscope/DFT
  (que no tenemos). Es el camino "de muy bajo nivel".
- **Ver kurtosis en una pagina propia, alternando con Oscilloscope/DFT** no
  toca la FPGA: usa nuestro bitstream tal como esta en campo.

## 4. Opciones

| | Que se ve | Toca FPGA | Toca codigo de Red Pitaya | Esfuerzo | Riesgo |
|---|---|---|---|---|---|
| **A. Panel "Arena" sobre modo evento** | kurtosis, area, acumulado (graficos en vivo, ~1-2 s de retraso); se alterna con Oscilloscope/DFT | No | No (solo `fpga.sh` de scope/DFT en el lab) | Bajo | Bajo |
| **B. App propia todo-en-uno** | A + señal cruda + espectro dibujados por nosotros, todo en una pagina | No | No | Alto (backend C++ + graficos) | Medio |
| **C. Bloque en v0.94 + Oscilloscope/DFT modificados** | kurtosis dentro de la app de Red Pitaya, a la vez | Si (portar pasabanda+acumulador a v0.94) | Si (conseguir fuentes, recompilar para 3.00) | Muy alto | Alto |

Por que C es muy dificil (dato, no opinion):
- Nuestro bitstream ya usa **58 de 80 DSP (72 %)** y 52 % de LUT; v0.94 trae
  osciloscopio + generador + PID. [Suposicion] que entre todo junto: hay que
  sintetizar para saberlo.
- En v0.94 la decimacion la cambia el usuario con la base de tiempo del
  osciloscopio; el acumulador necesita una decimacion fija propia (rama aparte
  desde el ADC = mas recursos).
- El codigo del Oscilloscope/DFT hay que bajarlo del repo de Red Pitaya,
  adaptarlo a la version 3.00 y recompilarlo; build del bitstream ~20 min.
- Muy poco probable para el 10/12.

## 5. Recomendacion: A para la demo; B o C despues, si se quiere

**Opcion A, en etapas** (cada una se prueba antes de pasar a la siguiente):

1. **Medir lo que ya hay.** Con `modo-evento` corriendo en el lab, tirar arena y
   ver cuanto tarda una ventana en aparecer en el CSV (esperado ~1-2 s). Si es
   poco para la demo, agregar una salida "en vivo" a `/run` (cambio chico en
   `capturar_eventos`, solo en esta rama).
2. **Pagina "Arena" sola.** HTML+JS estatico en la web de la placa con 3
   graficos: kurtosis (con linea del umbral), area por ventana y acumulado (con
   boton "reiniciar"). Una ruta Lua en nginx devuelve las ultimas filas (igual
   que `/get_sysinfo`). Sin backend C++.
3. **Integrarla como app de la pantalla de inicio** (icono "Arena" junto a
   Oscilloscope y DFT). Exclusion mutua para que nunca coincidan una recarga
   del FPGA y una lectura (= cuelgue):
   - `fpga.sh` de "Arena": arranca `modo-evento` (`systemctl start`, sin `enable`:
     el lab sigue en clasico al prender).
   - `fpga.sh` de Oscilloscope y DFT (solo lab, via `aplicar_mods.py`): paran
     `modo-evento` antes de cargar v0.94.
   - Probar alternar ~20 veces sin cuelgue ni reinicio.
4. **Ensayo de demo completo** por cable directo, sin internet.

Puntos a verificar en las etapas:
- Arrancar `modo-evento` tarda ~15 s (streaming-server + calibracion): al abrir
  "Arena" hay que mostrar "iniciando..." para que no parezca colgada.
- `modo-evento` necesita el pendrive en `/mnt/usb` (destino y 2 GB libres).
- [Probable] el orden "fpga.sh antes que el backend" en el cargador de apps:
  confirmar en la etapa 3.

## 6. Preguntas abiertas para el usuario

1. ¿Alcanza con **alternar** (Oscilloscope/DFT en una pestaña, "Arena" en otra)
   o es indispensable verlos **al mismo tiempo** en la misma pantalla?
2. "Acumulado": ¿suma de areas desde que se abre el panel (con boton para
   reiniciar), o algo distinto (ej. por hora, solo ventanas sobre el umbral)?
3. ¿IN1 solo, o IN1 + IN2?

## 7. Decisiones del usuario (20/11)

- **Alternar alcanza** (Oscilloscope/DFT en una pestaña, "Arena" en otra). Va la **opcion A**.
- **Nada se acumula en el tiempo**: ni archivos en el pendrive ni historial.
  El panel es tiempo real.

Ajuste del diseño por esa decision (reemplaza la etapa 1-2 de la seccion 5):
- **Sin pendrive y sin CSV.** Una copia aparte de `capturar_eventos`
  (`capturar_eventos_demo`, solo esta rama; la del lab/campo no se toca) agrega
  `--en-vivo /run/arena/ventanas.json`: cada ~200 ms reescribe ese archivo con
  las ultimas N ventanas (anillo en RAM, ej. 30 s = 600 ventanas). `/run` es RAM
  (92 MB libres): se pisa siempre, no crece, se borra al apagar.
- Corre con `--sin-registro` (sin CSV) y sin guardar señal cruda de eventos.
- La pagina lee ese archivo cada ~250 ms: retraso esperado **< 0,5 s** (la FPGA
  cierra una ventana cada 50 ms y se sondea cada 2 ms).
- El acumulado lo suma el navegador mientras el panel esta abierto (boton
  reiniciar); al cerrar o recargar, vuelve a cero.
- La demo no usa el servicio `modo-evento`: "Arena" levanta un servicio propio
  (`arena-demo`) con estos argumentos y Oscilloscope/DFT lo paran.

## Bitacora

- 20/11 ~20:17 UTC — **Etapa 1 (salida en vivo)**, lab por cable directo:
  - `demo_presentacion/c/capturar_eventos_demo.cpp` = copia de
    `scripts_campo/c/capturar_eventos.cpp` + clase `EnVivo` y `--en-vivo RUTA`
    (produccion sin cambios: diff de `scripts_campo` contra main vacio).
    Compila en la placa sin warnings (`make -C /root/demo_presentacion/c`, ~1 min).
  - `demo_presentacion/arena_demo.py`: bitstream propio + streaming-server y exec
    con `--sin-registro`, umbral 1e9 (sin eventos), destino `/run/arena`,
    `--minimo-libre-mb 0`, `--en-vivo /run/arena/ventanas.json`. Sin pendrive.
  - Antes de cargar el bitstream propio: el backend de `spectrumpro` seguia
    cargado en nginx sin la pagina abierta -> `GET /bazaar?stop=spectrumpro`
    lo descarga (verificado en /proc/<nginx>/maps). La etapa 3 tiene que hacer
    esto siempre antes de cambiar de bitstream.
  - Resultado sin arena: JSON reescrito cada 201-204 ms; atraso de la ultima
    ventana 52-214 ms (prom 132 ms); 176 ventanas seguidas sin huecos;
    kurtosis 2,94-3,04 (ruido ~3, esperado); area ~0,54. Placa sin reinicios.
- 20/11 20:19 UTC: captura de demo PARADA (sin capturar_eventos ni
  streaming-server). Queda cargado `stream_app_propio` en la FPGA, sin nadie
  leyendolo: abrir Oscilloscope/DFT es seguro (cargan v0.94).
  **Pendiente martes:** prueba con arena real (IN1) de la etapa 1; despues etapa 2.
- 24/11 ~12:30 UTC — **Etapa 2 (pagina "Arena") armada, SIN placa** (no estaba
  conectada; la prueba con arena de la etapa 1 sigue pendiente):
  - `demo_presentacion/web/arena/index.html` + `arena.js`: HTML+JS sin librerias
    externas (canvas propio; la demo va sin internet). Lee `ventanas.json` cada
    250 ms. Cifras grandes (kurtosis, area, acumulado + Reiniciar) y 3 graficos
    de los ultimos 30 s; linea roja punteada = umbral 3,4 en kurtosis.
  - Acumulado: suma por numero de ventana (cada una una sola vez), arranca al
    abrir la pagina, se reinicia con el boton o recargando. Si la captura se
    reinicia (wc vuelve para atras) sigue sumando desde ahi.
  - Estados: "en vivo" + atraso (hora placa al escribir − ultima ventana);
    "sin datos nuevos" si el archivo no cambia en 2 s; "parada o iniciando" si
    da error/404.
  - `instalar_web_arena.sh instalar` copia la pagina a
    `/opt/redpitaya/www/apps/arena` (remount rw y vuelve a ro). La idea inicial
    de un symlink NO sirve: `/opt/redpitaya` es FAT (vfat). El JSON se sirve con
    `arena/nginx.conf` (`location = /arena/ventanas.json { alias /run/arena/... }`,
    igual que scopegenpro con /tmp), que nginx incluye por `../apps/*/nginx.conf`;
    el script hace `nginx -t` y `-s reload`. URL: `http://<placa>/arena/`.
  - `demo_presentacion/web/simular_ventanas.py`: JSON falso (ruido 3/0,54 +
    golpes inventados) para probar en la PC con `python3 -m http.server`.
  - Probado en la PC con el simulador (Chrome): graficos y cifras en vivo,
    Reiniciar, captura parada, archivo inexistente y reinicio de la captura OK.
  - **Ojo para la prueba real:** el area con ruido es ~0,54 por ventana, asi
    que el acumulado sube ~11 por segundo SIN arena. Con arena se ve el escalon,
    pero en la demo puede parecer que "siempre hay arena". Decidir con datos
    reales si se resta un piso o se suma solo sobre el umbral.
  - **Pendiente:** instalar en la placa y probar con arena (etapa 1 + 2 juntas).
- 24/11 12:28 UTC — **Etapa 2 instalada en el lab** (cable directo, 192.168.137.225):
  placa en clasico, v0.94, sin backends de apps en nginx. `instalar` OK
  (`nginx -t` ok; el aviso "could not open error log" de `-t` es inofensivo),
  `/opt/redpitaya` vuelve a ro, `/arena/` 200, JSON 404 sin captura (esperado).
  `arena-prueba` lanzado: JSON 200 a los ~6 s, ventanas tras la calibracion
  (~10 s). Pagina en vivo en Chrome: kurtosis ~3,0, area ~0,54, atraso 20-45 ms;
  headers `application/json` + `no-store`. Acumulado sube ~11/s sin arena
  (confirmado). Placa sin reinicios. Falta: tirar arena.
- 24/11 12:31 UTC — **Acumulado redefinido (decision del usuario):** el usuario
  vio que el acumulado subia sin kurtosis sobre el umbral. Ahora es la **M2 del
  estudio arena vs kg** (`docs/estudio_arena_vs_kg.md`): suma de (area − fondo)
  solo en ventanas con kurtosis > 3,4; negativos a 0. Fondo = mediana del area
  de las ventanas bajo el umbral en los ultimos 30 s (el estudio usa p20 de
  medianas por minuto; para la demo alcanza con esto). Se muestra "fondo" bajo
  el area. Lab sin arena: fondo 0,54, acumulado 0,00 quieto. Prueba sintetica
  en node (5 ventanas con +2 sobre el fondo, una nula, una bajo el fondo,
  lectura repetida) = 10, OK. Falta: arena real.
- 24/11 ~12:45 UTC — **Etapa 3 (Arena como app) ESCRITA, SIN INSTALAR** (no se
  toca la placa para no cortar la `arena-prueba` que espera la arena). Lo
  relevado por SSH (solo lectura de archivos):
  - La pantalla de inicio arma la lista con `/bazaar?apps=` (carpetas con
    `info/info.json`), icono en `<app>/info/icon/{128,256,512}.png`; se ven solo
    las de `allowed_root` en `assets/black_list_app.js` (de aplicar_mods.py).
  - El Oscilloscope arranca desde su propia pagina (`/bazaar?start=scopegenpro`,
    que corre `fpga.sh` = `overlay.sh v0.94` y carga el backend).
  - Patron sin backend C++: "Remote control" (scpi_manager) arranca su servicio
    con rutas Lua (`io.popen("systemctl ...")`) en su nginx.conf; nginx corre
    como root.
  - Diseño hecho: `arena/info/` (info.json + icono), `arena-demo.service` (NO
    habilitado, `Conflicts=modo-evento`, `ExecStopPost` mata streaming-server),
    rutas `/arena_iniciar` y `/arena_estado` en `arena/nginx.conf`. La pagina
    al abrir hace `/bazaar?stop=scopegenpro|spectrumpro` y despues
    `/arena_iniciar`; muestra "iniciando la captura (~15 s)" hasta 45 s.
    Exclusion mutua: los `fpga.sh` de scope y DFT llevan al principio
    `systemctl stop arena-demo.service` (bloquea hasta que la captura termina,
    antes del overlay). `instalar_web_arena.sh instalar|quitar` hace todo y
    guarda copias `*.antes_arena`. Parches probados sobre copias de los
    archivos reales (sintaxis OK).
  - **Prueba pendiente (despues de la arena):** parar arena-prueba; instalar;
    icono visible; Arena -> datos en ~15 s; Scope -> arena-demo inactive y sin
    streaming-server antes del overlay (journal); DFT idem; alternar ~20 veces
    sin cuelgue ni reinicio (mirar uptime). [Probable] que bazaar corra fpga.sh
    antes de cargar el backend: confirmarlo en esta prueba.
- 24/11 12:40-12:45 UTC — **Etapa 3 instalada y probada en el lab** (prueba de
  arena postergada por el usuario; arena-prueba parada):
  - Hallazgo: `/bazaar?apps=` solo lista carpetas con `controllerhf.so`; Arena
    no tiene backend -> no aparecia. Se agrega como **entrada fija** en
    `assets/desktop.js` (`default_applications`, como las de Red Pitaya),
    marcada `// demo-arena`, con copia `desktop.js.antes_arena`. Icono visible
    entre Oscilloscope y System.
  - Arreglo en la pagina: la 1ra lectura del JSON (puede ser el archivo viejo
    de una captura anterior) ya no cuenta como "en vivo".
  - Ciclos reales en Chrome: Arena (datos ~11 s despues) -> Scope: arena-demo
    detenido 12:42:22.408, FPGA v0.94 12:42:22.853 (**orden correcto**: bazaar
    corre fpga.sh antes del overlay) -> Arena: backend de scope descargado
    antes de cargar el bitstream propio (12:42:47), "iniciando" y luego vivo.
- 24/11 12:44-12:55 UTC — **20 alternancias automaticas** (mismos pedidos HTTP
  que las paginas, Scope/DFT alternados): 19 OK, sin reinicios; Arena da datos
  en 12-14 s; captura parada ~0,4 s antes de cada overlay. La falla (ciclos 3-4)
  fue una **recarga del FPGA con Arena corriendo** que no vino del script
  (12:46:03; [Probable] un navegador abierto en la web): la captura leyo 0 y
  aborto, sin cuelgue. **Hallazgos y arreglos:**
  - La **pantalla de inicio es una app** (`main_menu`, `/bazaar?start=main_menu`)
    y su `fpga.sh` carga v0.94: ahora tambien lleva la parada de Arena.
  - Al parar, systemd a veces no mata el streaming-server ("Failed to kill
    control group ... Invalid argument", "remains running"): los 3 `fpga.sh`
    ahora hacen `pkill -x streaming-serve` y esperan (hasta 5 s) a que no quede.
  - El **listado de apps** de la pantalla de inicio (`/bazaar?apps=`) deja
    cargados en nginx los backends de `la_pro` y `streaming_manager` sin
    abrirlos. [Probable] solo los dlopen-ea (no tocan el FPGA), pero la pagina
    Arena ahora descarga 5 backends (scope, DFT, main_menu, la_pro,
    streaming_manager) antes de arrancar.
  - Verificado en Chrome: Arena -> inicio = Arena parada (55.447) antes del
    overlay (56.053); inicio -> Arena = ningun backend cargado al cargar el
    bitstream propio.
- 24/11 12:57-13:08 UTC — **21 alternancias con los arreglos** (Arena ->
  Scope / DFT / pantalla de inicio, 7 de cada uno, descargando 5 backends):
  **21/21 con la captura parada antes del overlay** (0,6 s antes), v0.94 cargado,
  sin streaming-server, ningun backend cargado al arrancar Arena, Arena con
  datos en 13-15 s, **sin reinicios** (btime constante, uptime 44 min). En el
  journal: 0 "remains running" y 0 errores de ventana. Los 7 "SIN_BACKEND" son
  de los ciclos a la pantalla de inicio y son del script, no de la placa: con
  `curl /bazaar?start=main_menu` (sin la pagina/websocket) el backend no queda
  cargado; en Chrome si quedaba. Placa queda en v0.94, arena-demo inactivo.
  **Etapa 3 OK en el lab.** Pendiente: prueba con arena real; ensayo completo
  (etapa 4) con la notebook de la demo.
- 24/11 ~13:15-13:50 UTC — **Prueba con arena real (IN1), etapas 1-3 juntas.**
  Registro en la PC de cada ventana (scratchpad de la sesion, `arena_real.csv`).
  Primeros 63 s: fondo real 0,52; 312 ventanas con arena (area > 2, picos de
  area 20-30); **solo 61 (20 %) con kurtosis > 3,4** (mediana 3,15): con
  arena volcada en chorro la kurtosis sube solo al inicio de cada chorro.
  Area − fondo de toda la arena = 5462; M2 (kurtosis > 3,4) = 701 (13 %).
  [Probable] impactos superpuestos -> señal casi gaussiana -> kurtosis ~3. No es
  comparable con el pozo (estudio de campo): vale solo para la demo.
  - Bug encontrado: el fondo salia de las ventanas bajo el umbral de kurtosis
    -> con chorro incluia arena (llego a 4,11). **Corregido:** fondo = p20 del
    area de los ultimos 30 s, solo se acepta si < 2x el actual. Reprocesadas las
    3010 ventanas del ensayo: fondo 0,517-0,522 todo el tiempo, M2 = 1087.
  - **Decision del usuario: se mantiene M2** (area − fondo solo con kurtosis >
    3,4) aun sabiendo que con chorro suma ~13 %. No volver a proponer cambiarla.
