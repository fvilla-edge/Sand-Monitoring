# Guía de interpretación de resultados — Detección acústica de arena

Referencia rápida para evaluar capturas y entender qué indica cada métrica.

---

## Marco general: detección vs clasificación

Las métricas tienen dos roles distintos. Confundirlos lleva a interpretaciones incorrectas.

| Rol | Pregunta | Métrica principal |
|---|---|---|
| **Detección** | ¿Hay arena o no? | Kurtosis global, Crest Factor |
| **Clasificación** | ¿Cuánta arena? (baja/media/alta) | Fracción activa |

---

## Kurtosis global — detección binaria

Mide la **impulsividad** de toda la señal: qué tan "pesadas" son las colas de la distribución de amplitudes. Un ruido gaussiano puro tiene kurtosis = 3.0. Cada impacto de arena introduce picos muy por encima del ruido, elevando la kurtosis.

**Por qué el valor se infla con eventos cortos:** la kurtosis usa la cuarta potencia de cada sample. Un sample con amplitud 10× el ruido contribuye 10⁴ = 10.000 veces más que uno normal. Entonces un burst breve pero intenso (arena tirada fuerte desde altura) puede dar la misma kurtosis global que actividad sostenida más suave. **La kurtosis global no distingue un pico corto de actividad sostenida.**

| Rango kurtosis | Interpretación |
|---|---|
| 2.5 – 4 | Reposo / sin eventos. Señal gaussiana. |
| 4 – 20 | Actividad leve. Puede ser artefacto o arena muy escasa. |
| 20 – 100 | Evento de arena confirmado. |
| > 100 | Evento de arena claro. Mayor kurtosis = más energía concentrada en el impacto. |

**Valores de referencia semana 2 (n=10 por condición):**

| Condición | Kurtosis media | Kurtosis std |
|---|---|---|
| Reposo | 3.00 | ±0.00 |
| Baja (3 g) | 323 | ±390 |
| Media (10 g) | 641 | ±222 |
| Alta (25 g) | 910 | ±197 |

El std de baja (±390) es mayor que la media (323) — un solo evento intenso puede triplicar el valor. **No usar la kurtosis global como único criterio para clasificar cuánta arena hay.**

> En condiciones reales con fluido, la kurtosis de reposo puede subir a 5–15 por turbulencia. El umbral de detección deberá ajustarse con la captura de `flujo_limpio`.

---

## Fracción activa — clasificación de cantidad

Divide la captura de 2.5 s en **50 ventanas de 50 ms**. Calcula la kurtosis de cada ventana por separado y cuenta cuántas superan el umbral de 20. La fracción activa es el porcentaje de ventanas que superaron ese umbral.

```
fraccion_activa = ventanas con kurtosis > 20 / total de ventanas
```

**Por qué resuelve el problema de la kurtosis global:** un burst corto infla solo la ventana donde ocurrió. Las 49 ventanas restantes no se ven afectadas. El resultado es una métrica proporcional a cuánto tiempo duró la actividad de arena dentro de la captura.

| Fracción activa | Interpretación |
|---|---|
| 0% | Reposo — ninguna ventana activa |
| 1–30% | Arena muy escasa o evento muy breve |
| 30–55% | Nivel baja (3 g en condición estática) |
| 55–70% | Nivel media (10 g) |
| > 70% | Nivel alta (25 g) |

**Valores de referencia semana 2 (n=10 por condición):**

| Condición | Fracción activa media | Std |
|---|---|---|
| Reposo | 0% | ±0% |
| Baja (3 g) | 43% | ±6% |
| Media (10 g) | 55% | ±14% |
| Alta (25 g) | 68% | ±13% |

El std de baja es ±6% (CV=14%) vs la kurtosis global que tenía CV=121%. **Esta es la métrica más estable para clasificar cantidad de arena.**

> Parámetros actuales: ventana = 50 ms · umbral kurtosis = 20 · fs = 1.953 MHz. Estos valores pueden ajustarse en `analisis_semana2.py`.

---

## Crest Factor — respaldo de la detección

Relación entre el pico máximo y el RMS. Mismo principio que la kurtosis: señal impulsiva → crest factor alto. Útil como **confirmación de detección**, pero satura rápido con la cantidad de arena.

| Rango crest factor | Interpretación |
|---|---|
| < 8 | Ruido continuo / reposo |
| 8 – 30 | Actividad moderada |
| > 30 | Señal impulsiva (arena) |
| > 100 | Evento intenso |

**Valores de referencia semana 2:**

| Condición | Crest Factor media | Std |
|---|---|---|
| Reposo | 5.3 | ±0.2 |
| Baja (3 g) | 94 | ±32 |
| Media (10 g) | 108 | ±25 |
| Alta (25 g) | 107 | ±18 |

Media y alta tienen casi el mismo crest factor. La métrica satura después de los primeros gramos — útil para detección, no para clasificación.

Kurtosis y crest factor deben coincidir. Si uno dice arena y el otro no, el dato es sospechoso.

---

## RMS diferencial — energía sobre el baseline

Fórmula: `sqrt(max(0, RMS² − RMS_baseline²)) / RMS_baseline`

Adimensional. Calculado automáticamente usando la mediana RMS de las capturas de reposo del mismo set.

| Valor | Interpretación |
|---|---|
| 0.0 | Es el baseline (reposo) |
| < 0.1 | Diferencia insignificante |
| 0.1 – 0.4 | Actividad leve sobre el baseline |
| > 0.4 | Actividad significativa |

**Valores de referencia semana 2:** reposo = 0.02 · baja = 0.40 · media = 0.86 · alta = 1.32

> Este índice cobra más sentido cuando haya fluido: el RMS del flujo limpio sube, el diferencial lo absorbe y la arena sigue dando valores positivos sobre ese nuevo piso.

---

## RMS absoluto

El RMS crudo de la señal filtrada en 100–450 kHz. Discriminador débil — depende del caudal y la ganancia.

- Reposo: **4.18 mV** (semana 2, mediana de 10 capturas)
- Baja: ~4.5 mV · Media: ~5.2 mV · Alta: ~6.4 mV

Solo útil como indicador de estabilidad del sistema. Si el RMS del reposo cambia mucho entre sesiones sin causa aparente (ej. 4 mV → 12 mV), puede indicar problema de acoplamiento del sensor o cambio en ganancia.

---

## Conteo de eventos — usar con precaución

Cuenta cruces de umbral (3σ de la propia señal). Problema: cuando hay un impacto muy fuerte, la σ de la señal sube, lo que sube el umbral y reduce el conteo. Resultado contraintuitivo: en los datos de semana 1 el reposo muestra **más** eventos que la arena. Tratar como indicador secundario. No usar como criterio principal.

---

## Tabla de referencia completa — semana 2

| Condición | Masa | Kurtosis | Crest Factor | Fracción activa | RMS dif. |
|---|---|---|---|---|---|
| Reposo | 0 g | 3.00 ±0.00 | 5.3 ±0.2 | 0% ±0% | 0.02 ±0.02 |
| Baja | 3 g | 323 ±390 | 94 ±32 | 43% ±6% | 0.40 ±0.07 |
| Media | 10 g | 641 ±222 | 108 ±25 | 55% ±14% | 0.86 ±0.69 |
| Alta | 25 g | 910 ±197 | 107 ±18 | 68% ±13% | 1.32 ±1.04 |

Hardware: Red Pitaya STEMlab 125-14 · Sensor VS150-RI · Modo HV ±20V · Filtro 100–450 kHz · fs = 1.953 MHz · Captura = 2.5 s · n=10 por condición

**Nota sobre los datos de semana 2:** arena tirada manualmente en condición estática (sin flujo). La variabilidad en baja (std alto en kurtosis) se explica por diferencias en altura y velocidad de la tirada. La fracción activa compensa este efecto porque mide duración, no intensidad de pico.

---

## Cómo leer los gráficos

### Semana 1 (`analisis/outputs/`)

**`senal_raw.png`** — Primeros 2 ms de señal sin filtrar. Sirve para detectar saturación (señal recortada) o contaminación de baja frecuencia.

**`fft_comparativa.png`** — Espectro pico (max-hold) sobre toda la captura. La arena debe mostrar más energía en la banda 100–450 kHz (región sombreada amarilla).

**`espectrogramas.png`** — STFT de la captura completa (2.5 s). Con arena se debe ver un flash brillante en la banda del sensor en algún momento.

**`espectrograma_peak.png`** — STFT centrada en el instante de máxima energía (±250 ms). Vista más útil: si hubo arena, muestra el evento limpio. Si se ve igual al reposo, la captura no tiene arena válida.

**`boxplots_metricas.png`** — Distribución de métricas por condición.

### Semana 2 (`analisis/outputs_semana2/`)

**`boxplots_semana2.png`** — Kurtosis (escala log), Crest Factor y Fracción activa por condición. La escala log en kurtosis es necesaria para ver la separación real — en escala lineal el outlier de baja aplasta todo lo demás.

**`timeline_kurtosis.png`** — Kurtosis por ventana de 50 ms a lo largo del tiempo, un archivo representativo por condición. Este es el gráfico más informativo: muestra visualmente la diferencia entre un burst corto (baja) y actividad sostenida (media/alta). La línea punteada es el umbral = 20.

**`scatter_masa_semana2.png`** — Kurtosis, Fracción activa y RMS diferencial vs gramos de arena. Muestra la monotonicidad de cada métrica: a mayor masa, mayor valor. La fracción activa es la más lineal de las tres.

---

## Checklist para evaluar una captura nueva

1. **¿Kurtosis global > 20?** → hay evento de arena. Si es < 5, la captura probablemente no tiene arena. *(detección)*
2. **¿Crest Factor > 30?** → confirma señal impulsiva. Debe coincidir con la kurtosis. *(detección)*
3. **Si hay arena: ¿cuál es la fracción activa?** → 30–55% = baja · 55–70% = media · >70% = alta. *(clasificación)*
4. **¿RMS absoluto razonable (3–10 mV en HV)?** → si es >20 mV puede haber saturación del ADC.
5. **¿La kurtosis global es muy alta pero la fracción activa es baja (<40%)?** → fue un evento breve e intenso, no actividad sostenida. El nivel real puede ser menor al que indica la kurtosis.

Si kurtosis y crest factor coinciden → hay arena. La fracción activa dice cuánta.
