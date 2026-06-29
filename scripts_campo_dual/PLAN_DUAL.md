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

### Paso 1 — Verificar doble ADC ✅ COMPLETO
**Script:** `test_dual_adc.py`

Captura ambos canales y muestra RMS + pico en consola. Sin guardar nada.

```bash
PYTHONPATH=/opt/redpitaya/lib/python python3 /root/scripts_campo_dual/test_dual_adc.py
# Opciones:
#   --decimacion 32    (default)
#   --intervalo 10     buffers entre cada print (default)
```

**Resultado esperado en reposo (sin señal acústica):**
- CH1 y CH2: RMS en el orden de 0.01–0.03 V (ruido de fondo)
- CH2 puede ser algo mayor si el cable/input está flotando
- Al conectar ambos sensores: los dos deberían estar en nivel similar

**Resultado con evento de arena:**
- CH1 (codo): RMS sube, picos altos, señal impulsiva
- CH2 (referencia): sube poco o nada si el sensor está suficientemente alejado

---

### Paso 2 — Agregar kurtosis al print
**Script:** `test_dual_adc.py` (modificado)

Agrega kurtosis por buffer para confirmar que CH1 captura eventos impulsivos y CH2 se mantiene bajo.

```
Buf    CH1 RMS   CH1 Kurt   CH2 RMS   CH2 Kurt
  10   0.05000    45.200    0.01200     3.100   ← arena en CH1, no en CH2
```

Criterio de validación: con arena pasando por el codo, `kurt_CH1 >> kurt_CH2`.

---

### Paso 3 — Captura y guardado dual
**Script:** `capturar_dual.py` (a crear)

Loop continuo con guardado HDF5. Mismo esquema de streaming que `capturar_campo.py` pero con dos datasets.

**Estructura HDF5:**
```
dual_{condicion}_{fecha}_{NNNN}.h5
  ├── raw_ch1          float32 [N_muestras]   ← sensor codo
  ├── raw_ch2          float32 [N_muestras]   ← sensor referencia
  └── attrs:
        condicion, sensor, decimacion, fs_base_hz, fs_ef_hz,
        n_muestras, duracion_s, chunk_num, fecha, gain,
        canal_ch1, canal_ch2
```

Uso previsto:
```bash
python3 capturar_dual.py --condicion reposo
python3 capturar_dual.py --condicion con_arena --duracion_total 30
```

---

### Paso 4 — Análisis diferencial
**Script:** `revisar_dual.py` (a crear, análogo a `revisar_campo.py`)

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

## Consideraciones de campo

- **Posición sensor referencia**: aguas arriba preferido — el flujo pasa primero por la referencia y luego por el codo, evitando que arena que ya pasó vuelva a afectar CH2.
- **Distancia mínima**: suficiente para que las ondas de impacto del codo no lleguen al sensor de referencia (regla de dedo: >0.5 m en tubería metálica).
- **Cables**: misma longitud de cable BNC posible para ambos sensores — reduce diferencia de ganancia.
- **Storage**: un archivo dual es ~2x el tamaño de uno simple. A dec=32: ~430 MB/min por par.

## Estado

| Paso | Estado |
|---|---|
| 1 — test_dual_adc.py | ✅ Completo y probado en RP |
| 2 — kurtosis en print | ⬜ Pendiente |
| 3 — capturar_dual.py | ⬜ Pendiente |
| 4 — revisar_dual.py | ⬜ Pendiente |
