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
