# Comandos — Sand Monitoring

Referencia rápida de todos los scripts del repo. Para el procedimiento completo de
campo (setup, topologías de red, troubleshooting) ver `scripts_campo/PLAN_CAMPO.md`.

---

## Captura (corren en la Red Pitaya)

### `scripts_campo/capturar_stream.py` — recomendado

Streaming FILE mode, ~98% eficiencia, raw `.bin`. Mono (1 canal) o dual (2 canales,
sensor de referencia) con el mismo script.

```bash
python3 scripts_campo/capturar_stream.py --condicion reposo --directorio /mnt/usb
```

| Argumento | Default | Descripción |
|---|---|---|
| `--condicion` | *obligatorio* | `reposo` o `con_arena` |
| `--canales` | `1` | `1` = mono (IN1), `2` = dual (IN1+IN2) |
| `--decimacion` | `32` | Factor de decimación, por canal → fs = 125 MHz / dec. Con `--canales 2` usar `64` |
| `--duracion_chunk` | `1.0` | Minutos por archivo |
| `--duracion_total` | sin límite | Minutos totales de la sesión |
| `--directorio` | `/mnt/usb` | Storage externo montado |
| `--destino` | `usb` | `usb` o `red` (scp SSH a la PC) |
| `--pc_host` | — | `usuario@ip` de la PC — solo con `--destino red` |
| `--pc_ruta` | — | Ruta destino en la PC — solo con `--destino red` |
| `--verbosidad` | `completo` | `completo` (todo, con color) o `minimo` (solo warnings/errores) |

### `scripts_campo/capturar_campo.py` — alternativa HDF5

Solo mono. Archivos auto-descriptos (float32), ~54% eficiencia, sin depender de un JSON aparte.

```bash
PYTHONPATH=/opt/redpitaya/lib/python python3 scripts_campo/capturar_campo.py --condicion reposo
```

| Argumento | Default | Descripción |
|---|---|---|
| `--condicion` | *obligatorio* | `reposo` o `con_arena` |
| `--decimacion` | `32` | Factor de decimación → fs = 125 MHz / dec |
| `--duracion_chunk` | `1.0` | Minutos por chunk/archivo |
| `--duracion_total` | sin límite | Minutos totales de la sesión |
| `--directorio` | `/mnt/usb` | Directorio de salida |
| `--compresion` | `False` (flag) | Activa compresión gzip-1 (menor tamaño, menor eficiencia) |

### `scripts_campo/probar_dual_stream.py` — prueba de banco

Captura corta de solo lectura para investigar formato/mapeo de canales con 2 canales
activos. No mueve ni borra nada del USB/red — usar antes de confiar en una captura dual.

```bash
python3 scripts_campo/probar_dual_stream.py --decimacion 32 --duracion 5
```

| Argumento | Default | Descripción |
|---|---|---|
| `--decimacion` | `32` | Factor de decimación |
| `--duracion` | `5.0` | Segundos de captura de prueba |

### `scripts_campo_comun/relanzar_captura.sh` — supervisor para sesiones largas

Relanza `capturar_stream.py` si crashea (bug conocido de la librería de Red Pitaya, no
arreglado del lado de ellos todavía). No relanza si el script termina limpio (Ctrl+C,
`--duracion_total` alcanzado, o problema de USB detectado). **Usar siempre para
sesiones de noche o sin supervisión.**

```bash
bash scripts_campo_comun/relanzar_captura.sh scripts_campo/capturar_stream.py \
  --condicion reposo --decimacion 32 --duracion_chunk 1 --directorio /mnt/usb
```

Primer argumento: ruta del script de captura. El resto se pasa tal cual a ese script
(cualquier combinación de los argumentos de `capturar_stream.py` de arriba, incluido
`--canales 2`). Constantes internas fijas: `MAX_REINTENTOS=10`, 5s de espera entre
reintentos, mata `streaming-server` residual antes de cada reintento.

---

## Análisis (corren en la PC)

### `analisis/revisar.py` — revisión rápida

Lee `.bin` + `session_*_info.json`, detecta automáticamente si cada archivo es mono o
dual (no hace falta indicarlo). Calcula kurtosis, crest factor, fracción activa y
rms_diferencial sobre la señal filtrada 100–450 kHz (más métricas cruzadas CH1/CH2 si
es dual). No usa `argparse` — rutas posicionales.

```bash
.venv/bin/python3 analisis/revisar.py /ruta/al/directorio/
.venv/bin/python3 analisis/revisar.py campo_reposo_*.bin campo_con_arena_*.bin
```

| Argumento | Descripción |
|---|---|
| rutas (posicional) | Archivos `.bin` o directorios (busca `campo_*.bin` recursivamente) |

### `analisis/espectrograma.py` — espectrograma STFT

Genera un PNG por archivo con el espectrograma (Hann, banda del sensor marcada con
líneas punteadas).

```bash
.venv/bin/python3 analisis/espectrograma.py /ruta/al/directorio/
```

| Argumento | Default | Descripción |
|---|---|---|
| `rutas` (posicional) | *obligatorio* | Archivos `.bin` o directorios con `campo_*.bin` |
| `--nperseg` | `4096` | Puntos por ventana FFT |
| `--overlap` | `0.5` | Fracción de solape (0–1) |
| `--fmin` | `0` | Frecuencia mínima a graficar (Hz) |
| `--fmax` | `600000` | Frecuencia máxima a graficar (Hz) |
| `--inicio` | `0.0` | Segundo de inicio dentro del archivo |
| `--duracion` | todo el archivo | Segundos a procesar desde `--inicio` |
| `--outdir` | `analisis/outputs` | Directorio de salida |

---

## Referencias

- Guía operativa completa (setup, topologías de red, troubleshooting): `scripts_campo/PLAN_CAMPO.md`
- Interpretación de métricas con valores reales medidos: `analisis/INTERPRETACION_RESULTADOS.md`
- Plan de proyecto vigente: `docs/roadmap_deteccion_arena.md`
