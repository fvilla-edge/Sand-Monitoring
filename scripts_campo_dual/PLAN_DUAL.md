# Etapa Dual — Medición Diferencial con Dos Sensores

## Objetivo

Agregar un segundo sensor VS150-RI como **referencia de ruido de línea**, aprovechando que el STEMlab 125-14 tiene dos ADC que sampean sincrónicamente por hardware.

```
[Línea de producción]

       IN1 (CH1)              IN2 (CH2)
       Sensor codo       Sensor referencia
           |                   |
      [Evento arena]     [Ruido de fondo/línea]
           |                   |
           +---[Red Pitaya]----+
               Adquisición
               simultánea
```

**Idea**: Al restar la contribución del sensor de referencia (CH2) a la señal del codo (CH1), se puede aislar el evento de arena del ruido mecánico y de la línea que afecta a ambos sensores por igual.

## Hardware

| Elemento | Detalle |
|---|---|
| ADC | STEMlab 125-14 — 2 canales, 125 MS/s, 14 bits |
| Sensor medición | VS150-RI → **IN1 (CH1)** — montado en el codo |
| Sensor referencia | VS150-RI → **IN2 (CH2)** — aguas arriba o abajo del codo |
| Ganancia | RP_GAIN_5X (modo HV ±20V) |
| Acoplamiento | DC |
| Decimación | 32 (→ fs = 3.906 MHz) por defecto |

**Sincronía**: garantizada por el FPGA del RP. Ambos canales se sampean en el mismo ciclo de clock — no hay offset temporal entre CH1 y CH2.

## Pasos de implementación

### Paso 1 — Verificar doble ADC ✅ COMPLETO (reemplazado)
Verificado con `probar_dual_stream.py` (ver mas abajo) usando el modo streaming
FILE en vez del `rp` viejo. `test_dual_adc.py` y `capturar_dual.py` (basados en
la libreria `rp` directa, HDF5, ~54% eficiencia) fueron **reemplazados** por el
esquema de streaming FILE mode (98% eficiencia, igual que `capturar_campo_stream.py`).

---

### Paso 1b — Adaptar a streaming FILE mode ✅ COMPLETO (2026-07-01)

**Script de prueba:** `probar_dual_stream.py` — captura corta de solo lectura
para investigar el formato de salida con CH1+CH2 activos antes de escribir el
script final. No mueve ni borra nada del USB/red.

**Hallazgos (placa conectada por link directo, 10.42.0.180):**

1. **Un solo archivo intercalado**, no dos archivos separados por canal.
   Confirmado con un archivo de prueba: el tamaño coincide con "2 canales
   intercalados" (78.16 MB vs 78.125 MB esperados a dec=32, 5s), y la
   separación por paridad (`datos[0::2]` / `datos[1::2]`) da estadisticas
   estables (std constante) en todo el archivo. La documentación oficial de
   Red Pitaya no especifica esto ("Streaming always creates three files" por
   sesión, no por canal), se resolvió empíricamente.

2. **Mapeo de canales confirmado por golpe físico** (cable IN1 sin sensor
   conectado, ambas entradas al aire, 2026-07-01 15:06 UTC-3): posiciones
   **impares** (`datos[1::2]`) = CH1 (codo), posiciones **pares**
   (`datos[0::2]`) = CH2 (referencia). El std de CH1 subió de 42.7 (baseline)
   a picos de 300-410 en los momentos irregulares del golpe; CH2 se mantuvo
   plano. **Re-confirmar este mapeo con el sensor VS150-RI puesto** — la
   prueba se hizo golpeando el cable, no un transductor real.

3. **Entradas flotantes generan artefacto periódico** — con ambas entradas al
   aire, CH2 mostró un valor idéntico repetido exactamente cada ~65.631
   muestras (~30 Hz), sin relación con eventos reales (un evento físico no
   repite el mismo valor bit a bit). Es ruido de entrada sin terminar, mismo
   fenómeno que el "reposo contaminado" de la prueba de campo del 30/06. No
   es un bug — hay que tenerlo presente al interpretar capturas de banco sin
   sensor conectado.

4. **dec=32 con los 2 canales activos pierde muestras de verdad:** test
   sostenido de 60s midió 982.068 muestras perdidas por canal (~0.42%,
   reportado por el FPGA, `log.txt` del streaming-server). A **dec=64**, mismo
   test de 60s: **0 pérdidas**. El ancho de banda combinado a dec=32 dual
   (~15.6 MB/s) supera lo que la SD interna sostiene (15 MB/s medido); a
   dec=64 combinado (~7.8 MB/s) queda con el mismo margen que el mono a
   dec=32.

---

### Paso 2 — Captura y guardado dual ✅ COMPLETO (2026-07-01)
**Script:** `capturar_dual_stream.py` — calcado de `capturar_campo_stream.py`.

- Mismo esquema SD-intermedia + move en background, 98% eficiencia esperada.
- `channel_state_1` y `channel_state_2` ambos `ON`, mismo attenuator `A_1_20`.
- Salida: `dual_{condicion}_{ts}_{NNNN}.bin` — raw int16 LE intercalado, un
  solo archivo (no se de-intercala en captura, eso queda para el análisis).
- `session_dual_{condicion}_{ts}_info.json` con el mapeo de canales y la
  advertencia de re-confirmarlo con sensor puesto.
- Advertencia en consola si `--decimacion` < 64 (con los números medidos de
  pérdida arriba). No bloquea — la decimación queda a criterio del operador.
- `ESPACIO_MIN` = 1 GB (el `capturar_dual.py` viejo tenía un bug: el
  comentario decía "el doble que campo simple" pero el valor puesto era
  *menor* — 400 MB vs 500 MB del mono).
- Mismos 3 destinos que campo: `usb`, `red` via gateway, `red` via link directo.

Uso:
```bash
python3 capturar_dual_stream.py --condicion reposo --decimacion 64 --directorio /mnt/usb
python3 capturar_dual_stream.py --condicion con_arena --decimacion 64 \
    --duracion_total 30 --destino red --pc_host facu-edge@10.42.0.1 --pc_ruta /home/facu-edge/datos_campo
```

**Para leer el .bin y separar canales:**
```python
import numpy as np
datos = np.fromfile('dual_....bin', dtype='<i2')
ch1 = datos[1::2]   # codo — a reconfirmar con sensor puesto
ch2 = datos[0::2]   # referencia
```

---

### Paso 3 — Análisis diferencial ✅ COMPLETO (2026-07-01)
**Script:** `revisar_dual.py` — adaptado para leer los `.bin` intercalados de
`capturar_dual_stream.py` (ya no soporta `.h5`, no se va a usar más). Lee el
mapeo de canales desde `session_dual_*_info.json` en vez de asumirlo fijo.
Probado con una captura real de 10s (entradas al aire): separó los canales
bien y el resultado fue coherente — k2 (CH2, flotante) dio kurtosis 9266 y
fa2%=100% por el artefacto periódico ya documentado (falso positivo esperado,
no arena); k1 se mantuvo en baseline (~3) porque no hubo golpe durante esa
captura.

Aplica filtro 100–450 kHz a ambos canales y calcula:

| Métrica | Descripción |
|---|---|
| kurtosis_ch1 | Impulsividad en sensor codo |
| kurtosis_ch2 | Impulsividad en sensor referencia |
| kurtosis_diff | Diferencia — indica contenido de arena no presente en ref |
| fraccion_activa_ch1 | % ventanas con kurt > umbral en CH1 |
| fraccion_activa_ch2 | Idem CH2 |
| rms_ratio | CH1_rms / CH2_rms — >1 indica exceso de energía en codo |

---

## Logs (errores y eventos)

Mismo mecanismo que en mono (comparten `campo_common.py`) — ver la sección
"Logs (errores y eventos)" en `scripts_campo/PLAN_CAMPO.md`. En la placa, el
archivo de esta captura queda en `/root/logs_campo/log_dual_<condicion>_<timestamp>.txt`.

---

## Consideraciones de campo

- **Posición sensor referencia**: aguas arriba preferido — el flujo pasa primero por la referencia y luego por el codo, evitando que arena que ya pasó vuelva a afectar CH2.
- **Distancia mínima**: suficiente para que las ondas de impacto del codo no lleguen al sensor de referencia (regla de dedo: >0.5 m en tubería metálica).
- **Cables**: misma longitud de cable BNC posible para ambos sensores — reduce diferencia de ganancia.
- **Storage**: a dec=64 (recomendado para dual) el combinado de los 2 canales
  pesa lo mismo que 1 canal a dec=32 en el script mono: ~469 MB/min. A dec=32
  dual (no recomendado, pierde muestras) serían ~938 MB/min.

## Estado

| Paso | Estado |
|---|---|
| 1 — Verificar doble ADC | ✅ Completo (`probar_dual_stream.py`) |
| 1b — Formato, mapeo de canales, decimación segura | ✅ Completo (2026-07-01) |
| 2 — `capturar_dual_stream.py` (streaming FILE mode) | ✅ Completo (2026-07-01) |
| 2b — Prueba mecánica del script (3 chunks, dec=64, USB) | ✅ Completo (2026-07-01) — 94-97% efic, sin errores. **Con entradas al aire, no es dato válido** — solo valida que el script funciona. |
| 2c — Prueba con sensores VS150-RI conectados | ⬜ **Pendiente — bloqueante antes de usar en campo real.** Repetir mapeo de canales (golpe con sensor puesto) y verificar el ruido de base real (sin las entradas flotantes debería desaparecer el artefacto periódico de ~30 Hz). |
| 3 — `revisar_dual.py` (adaptar a `.bin` intercalado) | ✅ Completo (2026-07-01) |
