# Guía de interpretación de resultados — Detección acústica de arena

Referencia rápida para evaluar si una captura nueva tiene sentido y qué indican los números.

---

## Discriminador principal: Kurtosis

La kurtosis mide la **impulsividad** de la señal. Un ruido gaussiano puro (sin eventos) tiene kurtosis = 3.0. Cada impacto de arena introduce un pico muy por encima del ruido de fondo, lo que eleva la kurtosis.

| Rango kurtosis | Interpretación |
|---|---|
| 2.5 – 4 | Reposo / sin eventos. Señal gaussiana. |
| 4 – 20 | Actividad leve. Puede ser artefacto o arena muy escasa. |
| 20 – 100 | Evento de arena confirmado. |
| > 100 | Evento de arena claro. Mayor kurtosis = más energía concentrada en el impacto. |

**Valores de referencia obtenidos:**
- Reposo: **3.02** → piso de ruido electrónico, correcto
- Arena en vacío: **1563** → impacto impulsivo muy limpio (sin ruido de fluido)

> En condiciones reales con fluido, el kurtosis de reposo puede subir a 5–15 por turbulencia. El umbral de detección deberá ajustarse una vez obtenida la captura de `flujo_limpio`.

---

## Crest Factor — respaldo de la kurtosis

Relación entre el pico máximo y el RMS. Mismo principio que la kurtosis: señal impulsiva → crest factor alto.

| Rango crest factor | Interpretación |
|---|---|
| < 8 | Ruido continuo / reposo |
| 8 – 30 | Actividad moderada |
| > 30 | Señal impulsiva (arena) |
| > 100 | Evento intenso |

**Valores de referencia:** reposo = 5 · arena = 157

Kurtosis y crest factor suelen coincidir. Si uno dice arena y el otro no, el dato es sospechoso.

---

## RMS diferencial — comparación contra baseline

Fórmula: `sqrt(max(0, RMS² − RMS_baseline²)) / RMS_baseline`

Adimensional. Indica cuánta energía extra hay sobre el piso de ruido del reposo. Calculado automáticamente en el análisis usando la mediana RMS de las capturas de reposo del mismo set.

| Valor | Interpretación |
|---|---|
| 0.0 | Es el baseline (reposo) |
| < 0.1 | Diferencia insignificante |
| 0.1 – 0.4 | Actividad leve sobre el baseline |
| > 0.4 | Actividad significativa |

**Valores de referencia:** reposo = 0.00 · arena = 0.75

> Este índice cobra más sentido cuando haya fluido: el RMS del flujo limpio sube, el diferencial lo absorbe y la arena sigue dando valores positivos sobre ese nuevo piso.

---

## RMS absoluto

El RMS crudo de la señal filtrada en 100–450 kHz. Es el discriminador más débil porque depende directamente del caudal y la ganancia.

- Reposo: **4.17 mV**
- Arena: **5.22 mV** (solo un 25% más)

Solo útil como referencia de estabilidad del sistema. Si el RMS del reposo cambia mucho entre sesiones sin causa aparente (ej. 4 mV → 12 mV), puede indicar problema de acoplamiento del sensor o cambio en la ganancia.

---

## Conteo de eventos — usar con precaución

Cuenta cruces de umbral (3σ de la propia señal). El problema: cuando hay un impacto de arena muy fuerte, la σ de la señal sube (el propio impulso eleva la varianza), lo que sube el umbral y reduce el conteo. Resultado contraintuitivo: en nuestros datos el reposo muestra **más** eventos que la arena.

Por ahora tratar este número como indicador secundario. No usarlo como criterio principal.

---

## Valores de referencia completos

| Condición | RMS [mV] | RMS dif. | Kurtosis | Crest Factor |
|---|---|---|---|---|
| Reposo (HV, sin flujo) | 4.17 | 0.00 | 3.02 | 5.08 |
| Arena en vacío (alta) | 5.22 | 0.75 | 1563 | 157 |

Hardware: Red Pitaya STEMlab 125-14 · Sensor VS150-RI · Modo HV ±20V · Filtro 100–450 kHz · fs = 1.953 MHz · Captura = 2.5 s

---

## Cómo leer los gráficos generados

**`senal_raw.png`** — Primeros 2 ms de señal sin filtrar. Sirve para detectar problemas de saturación (señal recortada en los límites) o contaminación de baja frecuencia.

**`fft_comparativa.png`** — FFT promediada de toda la captura. Muestra la distribución de energía en frecuencia. La arena debe mostrar más energía en la banda 100–450 kHz (región sombreada amarilla) que el reposo.

**`espectrogramas.png`** — Espectrograma STFT de la captura completa (2.5 s). Con arena se debe ver un flash de color brillante en la banda del sensor en algún momento de la captura. Si toda la imagen se ve igual al reposo, la arena no fue capturada en la ventana de adquisición.

**`espectrograma_peak.png`** — Espectrograma centrado en el instante de máxima energía (±250 ms). Esta es la vista más útil: si hubo arena, este gráfico muestra el evento limpio, similar a lo que muestra el GUI web de la Red Pitaya. Si se ve igual al reposo, la captura no tiene arena válida.

**`boxplots_metricas.png`** — Distribución de cada métrica por condición. Con pocas capturas los "boxplots" son puntos individuales. Se vuelven útiles al tener ≥5 capturas por condición.

---

## Checklist para evaluar una captura nueva

1. **¿Kurtosis > 20?** → hay evento de arena. Si es < 5, la captura probablemente no tiene arena.
2. **¿Crest factor > 30?** → confirma señal impulsiva. Debe coincidir con la kurtosis.
3. **¿RMS diferencial > 0.2?** → hay energía extra sobre el baseline.
4. **¿El `espectrograma_peak.png` muestra un flash brillante en 100–250 kHz?** → confirma visualmente el evento.
5. **¿RMS absoluto razonable (3–10 mV en HV)?** → si es muy alto (>20 mV) puede haber saturación del ADC.

Si kurtosis y crest factor coinciden y el espectrograma_peak muestra actividad, el resultado es válido.
