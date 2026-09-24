# Modo evento — captura continua 24h, guardando solo lo que importa

Rama `modo-evento`. Estado al 2026-09-24: **validado en la placa de pruebas
(`rp-f0fd8c`)**, todavía **no desplegado en la placa de campo (`rp-f0fbda`)**.

## Idea

Capturar la señal del sensor **todo el tiempo**, sin cortes, pero sin guardar
~230MB cada 30s. La FPGA calcula área y kurtosis de cada ventana de 50ms en
tiempo real; el programa de la placa guarda:

| Qué | Cuándo | Tamaño aprox. |
|---|---|---|
| Área + kurtosis de **cada** ventana (CSV) | siempre, 24h | ~30MB/día |
| Señal cruda de la ventana ±10ms (`evento_*.bin` + `.json`) | solo si kurtosis ≥ umbral (default 5) | ~0.5MB por evento |

Por qué guardar siempre el área y la kurtosis, además de los eventos:

1. **Señal de vida.** Sin el registro continuo, una carpeta sin eventos puede
   significar "no pasó arena" o "el sensor se desconectó" — no hay forma de
   distinguirlo. Con el registro, un sensor muerto se ve (área en cero o
   anormal).
2. **Historia completa del pozo**: duración de los pases, horarios,
   tendencias; no solo picos sueltos.
3. **Reanalizar hacia atrás.** Si el umbral correcto resulta ser otro (el 21/9
   el criterio viejo `fa%>25%` no vio arena real), se recalcula con los datos
   ya grabados. Lo que quedó bajo el umbral no se pierde.
4. **Validar contra el campo**: cuando el pozo dice "hubo arena de 14:50 a
   15:17", se ve qué midió el sensor en todo ese intervalo.
5. **Reconstruir la señal** en la PC con un relleno realista (ver abajo).

## Piezas

```
Placa (rp-f0fd8c / campo)                      PC
─────────────────────────                      ──
FPGA (bitstream port-2026.1)                   ventanas_a_paquete.py
  pasabanda 50-400kHz + área/kurtosis            CSV -> paquete liviano (JSON)
  por ventana (registros 0x40000328..)          ver_paquete.py
        │ registros                              visor área/kurtosis, horas/días
        ▼                                      reconstruir_senal.py
scripts_campo/c/capturar_eventos (C++)           eventos + CSV -> señal continua
  - stream NET de la señal CRUDA -> buffer        (dominio filtrado, relleno
    circular en RAM                                con ruido de fondo)
  - sondea los registros de la FPGA c/2ms      verificar_etapaB.py
  - kurtosis >= umbral -> guarda la cruda        banco: eventos vs tramo real
  - escribe el CSV de todas las ventanas
scripts_campo/capturar_eventos.py (lanzador)
```

- `scripts_campo/c/capturar_eventos.cpp` — núcleo. Compilar **en la placa**:
  `make -C /root/scripts_campo/c` (usa `/root/rpsa_client/streaming_api`).
  Está en C++ porque en Python el callback no daba abasto (~63% de muestras
  perdidas, ver el comentario de cabecera).
- `scripts_campo/capturar_eventos.py` — lanzador (bitstream + streaming-server
  + `exec` del binario).
- `analisis/placa/ventanas_a_paquete.py`, `analisis/placa/reconstruir_senal.py`,
  `analisis/visores/ver_paquete.py`, `analisis/placa/verificar_etapaB.py` — PC.

## Formatos

### Registro continuo: `ventanas_AAAAMMDD_HH.csv` (uno por hora UTC)

En la carpeta `--destino`, junto a los eventos. Se apaga con `--sin-registro`.

```
window_count,t_utc_ms,area,kurtosis,estado,perdidas_fpga
7995,1790257893778,0.634819,3.24481,ok,0
7217,1790258000123,,,saltada,0
```

- `window_count`: contador de ventanas de la FPGA. **Es la referencia de
  tiempo exacta** (cada ventana dura 50ms justos). No es continuo entre
  corridas (reinicios de captura/bitstream).
- `t_utc_ms`: hora UTC en que el programa **leyó** la ventana (jitter de
  ~±35ms). Sirve para anclar a la hora real, no para ubicar muestras.
- `estado=saltada`: el sondeo no llegó a leer esa ventana (el registro de la
  FPGA solo guarda la última). Área y kurtosis vacías: no hay dato.
- `perdidas_fpga`: muestras que el streaming-server reportó perdidas desde la
  fila anterior.
- Escritura en un hilo propio (flush cada 1s, cota de 10 min en RAM) para que
  la SD no frene el sondeo.

### Evento: `evento_<fecha>_<hora>_<us>_wc<window_count>.bin` + `.json`

`.bin`: int16 little-endian, señal **cruda** (sin filtrar), ventana oficial +
margen a cada lado. `.json`:

| Campo | Qué es |
|---|---|
| `window_count` | ventana de la FPGA que cruzó el umbral |
| `ventana_muestras`, `margen_muestras` | 195312 y 39062 a decimación 32 (50ms, ±10ms) |
| `inicio_ventana_en_archivo` | dónde empieza la ventana oficial dentro del `.bin` (ver "alineación" abajo) |
| `area`, `kurtosis` | los que calculó la FPGA |
| `con_hueco` | `true` si faltaron muestras en ese tramo (ver "huecos") |

## Comandos

En la placa (compilar una vez):
```bash
make -C /root/scripts_campo/c
```

Captura (umbral 5, destino por defecto `/root/eventos`):
```bash
python3 /root/scripts_campo/capturar_eventos.py --umbral 5 --destino /root/eventos
```

Pruebas de banco (loopback OUT1->IN1 con cable, reproduciendo un tramo real
por el DAC): scripts en `/root/prueba_eth0/` de `rp-f0fd8c` (fuera de git):
`etapaB_lv.sh T RATE` (umbral 5, a la SD), `etapaB_lv_todo.sh` (umbral 1),
`etapaB_lv_shm.sh` (umbral 1, a RAM), `larga.sh T SEGUNDOS` (sin DAC, con
monitor de RAM/CPU). **Antes de lanzar, verificar que el nombre `T` no exista**
(los scripts borran `ev_T` y pisan los logs), y **espaciar las corridas
~60s** (el streaming-server queda residual si se lanzan en ráfaga).

En la PC:
```bash
# CSV -> paquete liviano (uno por hora, o todos juntos)
.venv/bin/python analisis/placa/ventanas_a_paquete.py CARPETA/ventanas_20260924_15.csv
.venv/bin/python analisis/placa/ventanas_a_paquete.py CARPETA --unir -o dia.paquete.json

# visor (abrir el .paquete.json)
./analisis/visores/abrir_paquete.sh

# reconstruir un tramo (máx. 300s) + vista rápida
.venv/bin/python analisis/placa/reconstruir_senal.py CARPETA --desde 120 --duracion-s 10 --png

# banco: eventos guardados vs el tramo reproducido por el DAC
.venv/bin/python analisis/placa/verificar_etapaB.py tramo.bin CARPETA
```

## Reconstrucción de la señal

Idea: unir las ventanas crudas guardadas con ruido de fondo para ver una
señal continua. Decisiones:

- **Dominio filtrado.** El área de la FPGA es de la señal filtrada (50-400kHz),
  así que solo se puede imitar la parte dentro de la banda. Pegar relleno entre
  ventanas **crudas** deja un salto en cada unión (la cruda trae continua y baja
  frecuencia que el relleno no tiene). Los eventos se filtran en la PC
  (`area_kurtosis._filtrar_pasabanda`); la cruda queda en cada `.bin` para
  estudios aparte. No se guarda la filtrada de la FPGA: el DMA lleva una sola
  señal (la cruda), y guardar las dos duplicaría SD y Starlink.
- **Relleno**: ruido gaussiano pasado por el mismo pasabanda, con una
  envolvente que sigue el área de cada ventana del CSV (interpolada entre
  centros, sin escalones cada 50ms).
- **Uniones**: cada evento con peso 1 en su ventana oficial y rampa en el
  margen; eventos consecutivos se promedian (son copias del mismo stream).
- **Máscara**: 1 = real, 0 = relleno, 2 = relleno sin dato (ventana saltada).
  **El relleno es inventado: sirve para ver, no para calcular.**
- **Tamaño**: 15.6MB por segundo (float32) — una hora serían ~56GB. Se
  reconstruyen tramos de hasta 300s; para mirar días enteros está el paquete
  liviano en `ver_paquete.py`.
- **Área FPGA -> software**: `sw = sqrt((c·fpga)² − q²)`. Con señal fuerte
  c ≈ 0.999; en reposo la FPGA mide de más (piso de ruido). `c` se mide con ≥5
  eventos fuertes y `q` con eventos de reposo real (kurtosis < 4); si no hay,
  se usan los valores del banco `ESCALA_FPGA_DEFAULT = 0.9992` y
  `PISO_FPGA_DEFAULT = 0.3074` (bitstream port-2026.1, decimación 32, **jumper
  HV** como en campo; en LV da 0.2333 — **re-medir si cambia el bitstream o el
  jumper**). Que el piso cambie con el jumper indica que no es solo redondeo
  interno de la FPGA (causa sin confirmar). En HV, `c` no está medido (falta
  una prueba con señal fuerte en HV). Con umbral 5, casi nunca hay reposo
  guardado.

Validación (R2, umbral 1, simulando umbral 5): nivel del relleno +4% de
mediana (p10-p90 0.996-1.057), kurtosis del relleno 3.00 (real 3.05), 0
ventanas de relleno ≥5, uniones sin salto.

## Pruebas en la placa de pruebas (2026-09-23/24)

Todas en `rp-f0fd8c`, bitstream port-2026.1, decimación 32, loopback por cable
OUT1->IN1 (jumper IN1 en LV) reproduciendo el tramo real
`campo_reposo_20260903_144456` (10s) por el DAC, salvo L1.

| Corrida | Condición | Resultado |
|---|---|---|
| Etapa A | pulsos conocidos | alineación OK, 0 eventos sin pulso, corte de eth0 60s sin recalibrar |
| V2 | umbral 1, a SD | 11 saltadas, 1.96M muestras perdidas — la SD a ~10MB/s tira todo abajo |
| W1, W3 | umbral 1, a RAM | 0 saltadas, **0 pérdidas de sensibilidad**, 200/200 ventanas del tramo |
| W2, R1, P1 | umbral 5, a SD (como producción) | 0 saltadas; W2: 3 "pérdidas", 2 explicadas por la alineación y 1 en el umbral (5.15) |
| R2 | umbral 1, a SD | 2 saltadas marcadas en el CSV, `perdidas_fpga` = total del log |
| **HV15** | umbral 5, a SD, sin DAC, **jumper HV**, 15 min | 18000 ventanas, 0 saltadas, 0 muestras perdidas, **0 eventos**, kurtosis p50 2.98 / máx 3.06, área de reposo 0.515 |
| **L1** | umbral 5, a SD, **sin DAC, 90 min** (15:06-16:36 UTC) | 107999 ventanas, 0 saltadas, 100% muestras; **rotación de hora OK**; RAM/CPU planas (29.6MB / 21.5%); 1 evento (pico aislado de ~1ms, probable interferencia del banco) |

Detector (FPGA vs software sobre las mismas muestras que llegaron): mediana
0.12-0.26%, 0 desacuerdos de clasificación, con la alineación corregida.

## Hallazgos y limitaciones conocidas

- **Alineación ventana FPGA vs buffer propio**: `inicio_ventana_en_archivo`
  queda **1.5-3.2ms antes** de la ventana real de la FPGA, y **varía entre
  corridas**. Causa probable: `calibrar()` toma el mínimo de
  `wc·N − muestras_recibidas` y no puede ver la latencia mínima de entrega
  DMA -> callback. El margen de ±10ms lo cubre (no se pierde señal). Decisión
  (2026-09-24): quedarse con el margen; la calibración por contenido al
  arranque no funcionaría en campo (casi todo reposo, sin contraste).
  Propuesto: alinear cada evento después, en la PC, y usarlo como monitor
  (si el desfase se acerca a 10ms, agrandar el margen).
- **Huecos** (`con_hueco: true`): en el tramo que no llegó, el `.bin` tiene
  **datos viejos** del buffer circular (~300ms antes), no ceros, y el JSON no
  dice dónde. `reconstruir_senal.py` omite esos eventos. Pendiente: guardar la
  posición del hueco en el JSON.
- **La SD es el cuello de botella**: escribir muchos eventos (~10MB/s) hace
  perder muestras y ventanas (V2). Con umbral 5 en reposo no pasa.
- **El streaming-server acepta una sola conexión de configuración**: un
  segundo cliente tira al primero y la librería del vendor muere por SIGSEGV.
  No correr otro cliente contra el server a la vez.
- **El DAC por red no es exacto en tiempo** (mete silencios, lee el archivo
  antes de reproducirlo): sirve para inyectar señal, no como referencia de
  tiempo. `--prueba-archivo` espera la duración real del replay antes de
  cortar.
- **Reposo del banco**: el 23/9 dio kurtosis ~5.3 (HV) / ~6.4 (LV); el 24/9
  ~3.0 en LV y 2.98 (máx 3.06, 15 min) en HV. Sin explicar qué cambió.
- **Sesgo +4%** del nivel del relleno en la reconstrucción, sin explicar.

## Pendientes

- Volver el jumper de IN1 a **HV** al terminar las pruebas de banco (campo
  está en HV).
- Posición del hueco en el JSON del evento.
- Herramienta de alineación por evento en la PC (monitor del margen).
- Desplegar en la placa de campo: requiere el bitstream port-2026.1 y un
  procedimiento de actualización remota segura (checksum + fallback + cortes
  de Starlink), todavía sin diseñar.
- Recalibrar `FA_THRESH` / `INTERPRETACION_RESULTADOS.md` con los eventos
  reales confirmados del 21/9.
