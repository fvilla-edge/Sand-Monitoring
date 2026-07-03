# Roadmap — Sistema de Detección de Arena
## VS150-RI · Red Pitaya Stemlab 125-14 · Clasificación por niveles

**Proyecto:** Sistema experimental de detección y clasificación de producción de arena en pozos petroleros  
**Hardware:** Sensor Vallen VS150-RI (preamplificador integrado 40 dB, pico de resonancia 150 kHz, rango 100–450 kHz) + Red Pitaya Stemlab 125-14  
**Objetivo:** Clasificar el nivel de producción de arena en 4 categorías: sin arena / baja / moderada / alta  
**Estado:** Sensor instalado, señal capturada, firma acústica de arena verificada

> **Nota (2026-07-03):** este roadmap se escribió antes de tener datos de campo reales —
> los umbrales de kurtosis/fracción activa que aparecen abajo son objetivos de diseño, no
> valores medidos. Los valores reales ya medidos (campo y laboratorio) están en
> `analisis/INTERPRETACION_RESULTADOS.md` — consultar ahí antes de calibrar nada, no acá.
> `docs/informe_deteccion_arena.md` es la investigación bibliográfica previa (archivada,
> banda de frecuencia genérica en vez de la real del VS150-RI).

---

## Índice

1. [Roadmap técnico — 4 fases](#1-roadmap-técnico--4-fases)
2. [Product Backlog](#2-product-backlog)
3. [Historias de usuario técnicas](#3-historias-de-usuario-técnicas)
4. [Plan detallado — primeras 8 semanas](#4-plan-detallado--primeras-8-semanas)
5. [Mapa de incertidumbres](#5-mapa-de-incertidumbres)
6. [Roadmap de Machine Learning](#6-roadmap-de-machine-learning)
7. [MVP — el camino más corto](#7-mvp--el-camino-más-corto)
8. [Definición de éxito por hito](#8-definición-de-éxito-por-hito)

---

## 1. Roadmap técnico — 4 fases

### Fase 1 · Semanas 1–3 · Caracterización y dataset

**Objetivo**  
Convertir las señales ya capturadas en un dataset etiquetado, identificar las métricas más discriminantes y establecer el pipeline de procesamiento definitivo.

**Hipótesis a validar**
- La energía RMS en la banda 100–450 kHz del VS150-RI discrimina los 4 niveles de arena sin clasificador ML.
- La kurtosis y el crest factor son monotónicos con el nivel de arena inyectada.
- El ruido de fondo (fluido sin arena) es estacionario dentro de un experimento.

**Entregables**
- Pipeline Python funcional: filtrado → métricas → CSV etiquetado.
- Dataset inicial: ≥30 capturas × 4 niveles = 120 muestras mínimo.
- Boxplots de cada métrica vs. nivel de arena.
- Espectrograma estándar documentado para cada nivel.

**Riesgos**
- Sin ground truth cuantitativo (masa de arena inyectada medida en balanza), el etiquetado es subjetivo y genera sesgo en el clasificador.
- El VS150-RI tiene resonancia centrada en 150 kHz; fuera de ese pico la SNR puede ser insuficiente.

**Criterio de éxito**  
Al menos 3 métricas muestran diferencia estadística (Kruskal-Wallis, p < 0.05) entre los 4 niveles con un mismo caudal de fluido.

---

### Fase 2 · Semanas 4–6 · Clasificador inicial y MVP

**Objetivo**  
Entrenar y validar un clasificador simple (umbral → SVM) capaz de distinguir los 4 niveles. Demostrar el MVP funcional en tiempo real.

**Hipótesis a validar**
- Un SVM con kernel RBF entrenado sobre 5–7 features alcanza accuracy ≥ 80% en test set.
- El clasificador mantiene su performance ante variaciones de ±20% en el caudal.
- El índice relativo de arena (RMS normalizado al baseline) es más estable que el valor RMS absoluto.

**Entregables**
- Clasificador SVM entrenado y serializado (pickle).
- Confusion matrix documentada con F1 por clase.
- Dashboard mínimo: badge de nivel de arena en tiempo real + índice relativo + tendencia.
- Notebook reproducible con pipeline completo.

**Riesgos**
- Dataset pequeño (120–200 muestras): riesgo de overfitting. Mitigar con leave-one-out o k-fold estricto.
- Variaciones de caudal pueden hacer que el clasificador confunda "poca arena a alta velocidad" con "mucha arena a baja velocidad".

**Criterio de éxito**  
Accuracy ≥ 80% en test y el MVP es demostrable a un observador externo con inyección controlada en tiempo real.

---

### Fase 3 · Semanas 7–10 · Robustez y variabilidad

**Objetivo**  
Cuantificar el efecto de las variables de confusión (caudal, tamaño de partícula) sobre el clasificador y hacer el sistema robusto a ellas.

**Hipótesis a validar**
- El clasificador se degrada ≤10 puntos porcentuales cuando el caudal varía ±30%.
- El tamaño de partícula afecta el espectro pero no impide la clasificación por nivel.
- Normalizar al baseline dinámico compensa el efecto del caudal variable.

**Entregables**
- Matriz de sensibilidad: accuracy vs. caudal × nivel de arena.
- Clasificador v2 con normalización dinámica al baseline.
- Dataset expandido: ≥300 muestras con variaciones de condiciones.

**Criterio de éxito**  
Accuracy ≥ 75% con caudal variable. El sistema no requiere reentrenamiento ante cambios de caudal de ±30%.

---

### Fase 4 · Semanas 11–13 · Prototipo funcional y piloto

**Objetivo**  
Integrar el clasificador en el sistema embebido, validar en banco de pruebas continuo y preparar para piloto industrial en campo.

**Hipótesis a validar**
- El pipeline completo corre en Red Pitaya en tiempo real con latencia < 5 segundos por clasificación.
- El sistema mantiene su performance durante 8 horas de operación continua.

**Entregables**
- Sistema integrado: Red Pitaya + clasificador corriendo en tiempo real.
- Dashboard web con nivel de arena, tendencia e histórico.
- Protocolo de instalación documentado.
- Plan de piloto industrial.

**Criterio de éxito**  
Demostración continua de 8 horas sin intervención manual, con clasificación correcta ≥ 80% de las lecturas.

---

## 2. Product Backlog

### Must Have

| ID | Ítem | Descripción |
|---|---|---|
| PB-001 | Pipeline de métricas | Implementar en Python: filtro Butterworth pasa-banda 100–450 kHz → RMS, energía, kurtosis, crest factor, conteo de eventos → CSV etiquetado. |
| PB-002 | Protocolo de inyección con ground truth | Masa medida en balanza (±0.1 g), tamaño de partícula conocido, caudal registrado. Sin esto el dataset no tiene verdad de campo. |
| PB-003 | Dataset etiquetado (4 niveles) | ≥30 capturas/nivel = 120 muestras mínimo. Metadatos: masa_arena_g, tamaño_mm, caudal_Ls, timestamp, nivel_etiqueta. |
| PB-004 | Visualización diagnóstica de métricas | Boxplots de cada métrica por nivel. Espectrogramas comparativos. Scatter matrix de features. Test Kruskal-Wallis por feature. |
| PB-005 | Clasificador SVM con validación k-fold | RBF kernel, GridSearchCV para C y gamma, k=5. Accuracy, F1 por clase y confusion matrix documentados. |
| PB-006 | Índice relativo de arena con baseline dinámico | `(RMS_actual − RMS_baseline) / RMS_baseline`. Baseline actualizado cada 60 s. Adimensional y robusto a variaciones de ganancia. |
| PB-007 | Clasificación en tiempo real sobre Red Pitaya | Pipeline completo: adquisición → filtrado → métricas → SVM → salida. Latencia < 5 s por ciclo de clasificación. |

### Should Have

| ID | Ítem | Descripción |
|---|---|---|
| PB-008 | Dashboard web con badge de nivel + tendencia | Verde/amarillo/naranja/rojo según nivel. Índice relativo en tiempo real. Histórico de 24 h. Alarma configurable por umbral. |
| PB-009 | Análisis de robustez ante variaciones de caudal | Dataset con 3 velocidades distintas. Matriz accuracy vs. caudal. Normalización dinámica si degrada > 10 puntos. |
| PB-010 | Análisis de sensibilidad por tamaño de partícula | Repetir con arena fina (~0.1 mm), media (~0.4 mm) y gruesa (~0.8 mm). Evaluar generalización del clasificador. |
| PB-011 | Logging y almacenamiento local | Serie temporal de métricas, clasificaciones y eventos. Formato CSV o SQLite. Exportable desde el dashboard. |

### Could Have

| ID | Ítem | Descripción |
|---|---|---|
| PB-012 | Clasificador CNN sobre espectrogramas | Solo si SVM < 80% accuracy. Requiere > 200 espectrogramas etiquetados. |
| PB-013 | Detección de eventos individuales (conteo de impactos) | Picos sobre umbral dinámico para estimar tasa de impactos/s. Feature adicional y herramienta de análisis forense. |
| PB-014 | Transmisión remota y dashboard satelital | Integración Starlink/GPRS para piloto de campo en Neuquén. |
| PB-015 | Dataset público etiquetado | Publicar en Zenodo o GitHub. No existe dataset público de este tipo en la literatura. Contribución científica abierta. |

---

## 3. Historias de usuario técnicas

### Investigador

**HU-01**  
*Como investigador, quiero calcular automáticamente RMS, kurtosis, crest factor y conteo de eventos para cada captura, para comparar condiciones de forma objetiva sin depender de inspección visual.*

Criterios de aceptación:
- Dado un CSV de señal raw, el script produce en < 2 s un dict con las 5 métricas.
- Kurtosis ≈ 3 para señal gaussiana pura (sin arena).
- RMS aumenta monotónicamente con la masa de arena inyectada en el banco de pruebas.

**HU-02**  
*Como investigador, quiero visualizar el espectrograma antes y durante la inyección de arena, para confirmar en qué sub-banda del VS150-RI (100–450 kHz) aparece la firma acústica.*

Criterios de aceptación:
- El espectrograma muestra actividad en la banda de interés durante la inyección.
- La banda sin arena es claramente menor en energía.
- Se genera en < 10 s desde el CSV.

---

### Ingeniero de señales

**HU-03**  
*Como ingeniero de señales, quiero implementar un filtro Butterworth pasa-banda centrado en 100–450 kHz, para eliminar el ruido de fluido (< 25 kHz) antes de calcular las métricas.*

Criterios de aceptación:
- Orden 4, atenuación > 40 dB fuera de banda.
- Aplicado con `filtfilt` (cero desfase de fase).
- SNR ≥ 6 dB al inyectar arena media.

**HU-04**  
*Como ingeniero de señales, quiero definir el índice relativo de arena como `(RMS_actual − RMS_baseline) / RMS_baseline`, para que sea adimensional e independiente de la ganancia absoluta del sistema.*

Criterios de aceptación:
- Índice ≈ 0 sin arena, independientemente del caudal.
- Índice > 0.3 para nivel "poca arena" y > 1.0 para "mucha arena" en el banco.
- Baseline actualizado cada 60 s.

---

### Ingeniero de datos

**HU-05**  
*Como ingeniero de datos, quiero que cada muestra del dataset incluya metadatos (masa_arena_g, tamaño_mm, caudal_Ls, timestamp, nivel_etiqueta), para poder entrenar y auditar el clasificador con ground truth verificable.*

Criterios de aceptación:
- CSV de metadatos con todas las columnas obligatorias completas.
- Masa de arena pesada en balanza con resolución ± 0.1 g.
- Ninguna muestra con `nivel_etiqueta` vacío o ambiguo.

**HU-06**  
*Como ingeniero de datos, quiero entrenar un SVM con k-fold (k=5) y reportar accuracy, F1 macro y confusion matrix, para tener una estimación honesta del rendimiento sin overfitting.*

Criterios de aceptación:
- Accuracy promedio k-fold ≥ 80%.
- F1 ≥ 0.70 para cada clase.
- Modelo serializado carga y predice en < 100 ms.

---

### Operador de campo

**HU-07**  
*Como operador de campo, quiero ver en pantalla el nivel actual de arena (badge verde/amarillo/naranja/rojo) actualizado cada 5 segundos, para tomar decisiones operativas sin interpretar señales técnicas.*

Criterios de aceptación:
- Badge cambia de color en < 5 s ante un cambio de nivel.
- El operador entiende el estado sin capacitación técnica previa.

**HU-08**  
*Como operador de campo, quiero recibir una alerta cuando el sistema detecta producción alta de arena, para accionar el choke o notificar a ingeniería antes de que se produzca daño en el equipo.*

Criterios de aceptación:
- Alerta disparada en < 10 s desde la detección de nivel "alto".
- Incluye timestamp, nivel detectado y valor de índice relativo.
- Umbral de alarma configurable sin modificar código.

---

### Responsable de integridad de pozos

**HU-09**  
*Como responsable de integridad de pozos, quiero acceder al histórico de niveles de arena de las últimas 72 horas, para correlacionar eventos de arena con parámetros de producción y evaluar el estado del completion.*

Criterios de aceptación:
- Histórico descargable en CSV con columnas: timestamp, nivel_clasificado, índice_relativo, RMS.
- Resolución temporal ≤ 1 minuto.
- Datos persisten ante reinicios del sistema.

---

## 4. Plan detallado — primeras 8 semanas

### Semana 1 — Pipeline de métricas

**Actividades**
- Leer los CSVs ya capturados (`scope_0_1.csv`, test de grafito HB).
- Implementar filtro Butterworth pasa-banda 100–450 kHz con `scipy.signal.butter` + `filtfilt`.
- Calcular para cada captura: RMS, energía, kurtosis, crest factor, conteo de eventos sobre umbral dinámico.
- Generar espectrogramas STFT de las capturas existentes.

**Análisis**
- Comparar métricas entre la captura con grafito (impacto) y sin impacto.
- Verificar que el filtro no distorsiona la señal en la banda de interés.

**Resultado esperado**  
Script Python funcional que recibe un CSV y produce un dict con las 5 métricas en < 2 s. Espectrogramas comparativos generados.

---

### Semana 2 — Protocolo de inyección controlada

**Actividades**
- Definir los 4 niveles en gramos por minuto (ejemplo: 0 g/min / 2 g/min / 10 g/min / 30 g/min).
- Establecer el método de inyección: jeringa de 50 ml + balanza + cronómetro.
- Documentar cómo medir y registrar el caudal para cada captura.
- Capturar 10 muestras por nivel = 40 muestras totales con metadatos completos.

**Experimentos**
- 4 condiciones × 10 repeticiones cada una.
- Mantener el caudal de fluido constante durante toda la sesión.

**Resultado esperado**  
Protocolo documentado. 40 muestras etiquetadas con metadatos: masa_g, caudal_Ls, tamaño_mm, timestamp, nivel.

> **Advertencia crítica:** sin este protocolo de ground truth, el dataset no es utilizable para entrenar un clasificador confiable. Es la actividad más importante del proyecto en este momento.

---

### Semana 3 — Análisis discriminante de features

**Actividades**
- Aplicar el pipeline de métricas a las 40 muestras etiquetadas.
- Generar boxplots: cada métrica (RMS, kurtosis, crest factor, energía, conteo) vs. nivel de arena.
- Ejecutar test Kruskal-Wallis para cada métrica.
- Generar scatter matrix de todas las features.

**Análisis**
- Identificar top-3 features con mayor separación entre clases.
- Documentar cuáles métricas son monotónicas con el nivel de arena.

**Resultado esperado**  
Informe de features con boxplots y p-valores. Identificación de las métricas candidatas para el clasificador.

---

### Semana 4 — Dataset completo v1

**Actividades**
- Ampliar a 30 capturas por nivel = 120 muestras totales.
- Variar el caudal ±10% dentro de cada nivel para agregar variabilidad controlada.
- Verificar consistencia del etiquetado (no ambigüedades).
- Calcular todas las métricas sobre el dataset completo.

**Resultado esperado**  
`dataset_v1.csv` con 120 muestras y todos los metadatos. Listo para entrenar el clasificador.

---

### Semana 5 — Clasificador SVM

**Actividades**
- Implementar clasificador de umbral simple (if-else en RMS) como baseline de referencia.
- Entrenar SVM con kernel RBF usando `sklearn.svm.SVC` + `GridSearchCV` para C y gamma.
- Validar con k-fold estratificado (k=5).
- Calcular accuracy, F1 macro, F1 por clase y confusion matrix.

**Análisis**
- Comparar el accuracy del SVM vs. el umbral simple.
- Identificar qué clases son más difíciles de separar (confusion matrix).

**Resultado esperado**  
`modelo_svm_v1.pkl`. Reporte de accuracy con confusion matrix. Diferencia documentada entre SVM y umbral simple.

---

### Semana 6 — MVP funcional

**Actividades**
- Integrar el pipeline en tiempo real: adquisición desde Red Pitaya → filtrado → cálculo de métricas → clasificación con SVM → salida del nivel.
- Implementar el cálculo de baseline dinámico (ventana deslizante, actualización cada 60 s).
- Desarrollar dashboard mínimo: badge de nivel (verde/amarillo/naranja/rojo) + índice relativo en tiempo real.
- Demo en vivo con inyección controlada ante el equipo.

**Resultado esperado**  
MVP demostrable. El badge cambia en tiempo real al inyectar arena. Latencia < 5 s verificada.

---

### Semana 7 — Robustez ante variaciones de caudal

**Actividades**
- Repetir el dataset con 3 velocidades de fluido distintas (baja, media, alta).
- Evaluar la degradación del clasificador al cambiar el caudal sin reentrenar.
- Si la degradación supera 10 puntos porcentuales: implementar normalización dinámica al baseline y reentrenar.

**Análisis**
- Matriz de accuracy: filas = nivel de arena, columnas = caudal.
- Documentar el caudal mínimo para detección confiable.

**Resultado esperado**  
Matriz de sensibilidad documentada. Clasificador v2 con normalización dinámica si fue necesario.

---

### Semana 8 — Robustez ante variaciones de tamaño de partícula

**Actividades**
- Repetir experimentos con arena fina (~0.1 mm) y arena gruesa (~0.8 mm).
- Evaluar si el clasificador generaliza entre tamaños sin reentrenamiento.
- Documentar los límites de detección: tamaño mínimo detectable, caudal mínimo requerido.
- Preparar informe de cierre de Fases 1 y 2.

**Resultado esperado**  
Informe de robustez. `dataset_v2.csv` con variaciones de tamaño. Límites de detección documentados.

---

## 5. Mapa de incertidumbres

Ordenadas de mayor a menor impacto en el éxito del proyecto.

### 🔴 Críticas

**U-01 · ¿Qué features discriminan mejor los 4 niveles con el VS150-RI específico?**  
La literatura indica RMS y kurtosis en el rango 50–80 kHz para flujo de gas. El VS150-RI tiene pico de resonancia en 150 kHz y el banco de pruebas usa líquido. El resultado puede diferir significativamente de lo reportado. Esta incertidumbre se resuelve en la Semana 3.

**U-02 · ¿Es el protocolo de inyección suficientemente controlado para producir ground truth confiable?**  
Sin masa medida y reproducible, el dataset tiene etiquetas ruidosas y el clasificador aprende patrones espurios. Es el riesgo más subestimado del proyecto. Una jeringa de 50 ml + balanza + cronómetro es suficiente para empezar. Esta incertidumbre se resuelve en la Semana 2.

### 🟡 Altas

**U-03 · ¿Cómo afecta el caudal al nivel de ruido de fondo en la banda del sensor?**  
A mayor caudal, mayor ruido hidráulico. Si el incremento de ruido en la banda 100–450 kHz supera la señal de arena a baja concentración, "sin arena" y "poca arena" serán indistinguibles. Esta incertidumbre se resuelve en la Semana 7.

**U-04 · ¿El tamaño de partícula confunde el clasificador de nivel?**  
Partículas más grandes generan mayor energía por impacto. Si el clasificador confunde "poca arena gruesa" con "mucha arena fina", la clasificación es inútil en campo donde el tamaño varía. Esta incertidumbre se resuelve en la Semana 8.

### 🟢 Medias

**U-05 · ¿La normalización al baseline dinámico compensa suficientemente el efecto del caudal?**  
Es el mecanismo clave de robustez propuesto. Si no funciona, se necesita medir el caudal por otro medio o limitar el sistema a caudal fijo. Esta incertidumbre se resuelve en la Semana 7.

**U-06 · ¿Cuántas muestras de entrenamiento son mínimamente necesarias para un SVM estable?**  
Con < 50 muestras/clase el SVM puede variar ±15% de accuracy entre splits. Necesitamos cuantificar esto con curvas de aprendizaje. Esta incertidumbre se resuelve en la Semana 5.

**U-07 · ¿El sistema funciona con fluido multifásico (agua + gas)?**  
El banco usa agua sola. En campo hay mezcla de fases. Las burbujas de gas generan señal acústica que puede enmascarar la arena. Esta incertidumbre es relevante solo para el piloto industrial (Fase 4).

---

## 6. Roadmap de Machine Learning

### Principio de diseño

No pasar al siguiente método hasta que el anterior falle o esté validado. El SVM resuelve el 80% del problema con el 20% del esfuerzo. CNN es la mejora marginal que requiere 5× más datos y tiempo de desarrollo.

### Secuencia de incorporación

| Semana | Qué incorporar | Qué problema resuelve |
|---|---|---|
| 1 | RMS · Energía · FFT | Verificar que la señal cambia con la arena. Baseline del sistema. No requiere entrenamiento. Resultado inmediato desde los datos ya capturados. |
| 1–2 | Kurtosis · Crest factor · Conteo de eventos | Capturar la impulsividad de los impactos. Robustas al nivel absoluto de ganancia. Distinguen señal impulsiva de ruido estacionario. |
| 2–3 | STFT / Espectrograma | Diagnóstico visual. Confirmar en qué sub-banda del VS150-RI aparece la firma acústica. Insumo para CNN en fases futuras si el SVM no alcanza el objetivo. |
| 3–4 | Umbral simple en RMS | Demostrar el MVP mínimo sin ML. Si RMS > X → "hay arena". Baseline de referencia: la literatura reporta ~35% de falsos positivos con este método. |
| 5 | SVM con kernel RBF | Reducir falsos positivos del umbral simple a < 10%. Clasificar los 4 niveles usando el vector de features. Robusto con datasets pequeños (120–200 muestras). |
| 7+ | Random Forest | Si el dataset supera 300 muestras: ganar interpretabilidad vía feature importances. Ayuda a entender qué features son realmente relevantes en el banco específico. |
| 10+ | CNN sobre espectrogramas | Solo si SVM < 80% accuracy o si se quiere clasificar tamaño de partícula además del nivel. Requiere > 200 espectrogramas etiquetados. CNN aprende features automáticamente. |

### Notas sobre cada método

**RMS y energía** son los indicadores más directamente respaldados por la literatura (Gao et al. 2015, Xue et al.). Son el punto de partida obligatorio y no requieren entrenamiento.

**Kurtosis y crest factor** son métricas de impulsividad. La señal de arena es impulsiva (transients discretos); el ruido hidráulico es continuo y más gaussiano. Una señal gaussiana tiene kurtosis = 3. La presencia de arena eleva la kurtosis por encima de ese valor.

**STFT** es la herramienta de diagnóstico central. Permite ver si la actividad está en la banda correcta y si hay eventos distinguibles. No es un clasificador por sí sola, pero es el insumo visual más informativo.

**SVM con RBF** es el clasificador recomendado para este problema con datasets pequeños. El kernel gaussiano crea fronteras de decisión no lineales sin requerir grandes volúmenes de datos. Appalonov et al. (2021) reportan 7% de falsos positivos vs. 35% del umbral simple.

**CNN** es justificable solo como segunda etapa si el SVM no alcanza el objetivo. Wang et al. (2024) reportan 93.8% de accuracy clasificando tamaño de partícula con CNN sobre espectrogramas STFT.

---

## 7. MVP — el camino más corto

**Objetivo:** demostrar que el sistema distingue entre sin arena / poca arena / mucha arena en menos de 4 semanas, sin modelos complejos.

### Pasos del MVP

**Paso 1 — Usar los datos ya capturados**  
Los CSVs `scope_0_1.csv` y el test de grafito HB ya existen. Aplicar el filtro Butterworth y calcular RMS. Si hay diferencia visible entre el test con impacto y sin impacto → confirmar hipótesis central sin nuevo experimento.

**Paso 2 — Capturar solo 3 niveles en 1 sesión**  
Sin arena (fluido circulando), poca arena (2–3 g inyectados), mucha arena (20–30 g). 10 capturas por nivel = 30 muestras totales. Suficiente para el MVP.

**Paso 3 — Calcular solo RMS en banda filtrada**  
Una sola métrica. Si los 3 grupos son separables por RMS solo (boxplot sin overlap entre grupos), el MVP es demostrable con un clasificador if-else. No se necesita ML en este punto.

**Paso 4 — Dashboard mínimo: 1 número + 1 color**  
Mostrar el índice relativo de arena actualizado cada 5 s. Badge verde = sin arena, amarillo = poca, rojo = mucha. Eso es el MVP funcional.

**Paso 5 — Demo en vivo con inyección manual**  
Alguien inyecta arena en el banco mientras otro observa el dashboard cambiar en tiempo real. Suficiente para validar el concepto ante el cliente o stakeholder.

### Advertencia sobre el MVP

El MVP sin ground truth cuantitativo (masa medida en balanza) demuestra que el sistema *reacciona* a la arena, no que *clasifica correctamente*. Para el cliente puede ser suficiente en primera instancia; para el equipo técnico es solo el punto de partida. No confundir ambas cosas. El MVP es una herramienta de comunicación, no una validación técnica completa.

---

## 8. Definición de éxito por hito

### Hito 1 — Prueba de laboratorio

| Criterio | Valor objetivo |
|---|---|
| Pipeline de métricas | Funcional y documentado |
| Diferencia estadística de features | ≥3 features con p < 0.05 (Kruskal-Wallis) entre 4 niveles |
| Tamaño del dataset | ≥120 muestras etiquetadas con metadatos completos |
| Documentación de espectrogramas | Un espectrograma estándar por nivel de arena |
| **Plazo** | **≤ Semana 4** |

### Hito 2 — Clasificador inicial

| Criterio | Valor objetivo |
|---|---|
| Algoritmo | SVM con kernel RBF, validado con k-fold (k=5) |
| Accuracy en test (30% hold-out) | ≥ 80% |
| F1 por clase | ≥ 0.70 para cada una de las 4 clases |
| Documentación | Confusion matrix analizada y archivada |
| Demo en tiempo real | MVP demostrable con inyección controlada |
| **Plazo** | **≤ Semana 6** |

### Hito 3 — Prototipo funcional

| Criterio | Valor objetivo |
|---|---|
| Integración en Red Pitaya | Pipeline corriendo en tiempo real |
| Latencia | ≤ 5 s por clasificación |
| Dashboard | Badge de nivel + tendencia + histórico de 24 h |
| Robustez a caudal variable | Accuracy ≥ 75% con variación de ±30% en caudal |
| Operación continua | Demo de 2 horas sin intervención manual |
| **Plazo** | **≤ Semana 10** |

### Hito 4 — Piloto industrial

| Criterio | Valor objetivo |
|---|---|
| Instalación | En pozo real con fluido de producción |
| Operación continua | 8 horas sin fallas del sistema |
| Validación operacional | Alertas de nivel alto confirmadas por el operador de campo |
| Correlación con campo | ≥1 evento de arena documentado y correlacionado |
| Acceso remoto | Datos accesibles vía dashboard desde oficina |

> **Nota sobre el Hito 4:** el piloto industrial valida el sistema en condiciones reales, pero no valida la cuantificación en g/s. Para declararlo exitoso, es suficiente que el sistema clasifique de forma consistente con la percepción operativa del equipo en campo. La cuantificación exacta en g/s, kg/día o ppm es el objetivo de la Etapa 2 y requiere calibración con inyecciones controladas en la instalación real.

---

## Apéndice — Referencias bibliográficas clave

1. Gao, G. et al. (2015). *Sand rate model and data processing method for non-intrusive ultrasonic sand monitoring.* Journal of Petroleum Science and Engineering, 134, 30–39.
2. Pham, M. (2023). *Using Acoustic Emission to monitor sand production.* Master's Thesis, NTNU.
3. Wang, K. et al. (2024). *A sand particle characterization method based on a multifrequency collision response.* Natural Gas Industry B, 11, 154–169.
4. Appalonov, A. et al. (2021). *Advanced Data Recognition Technique for Real-Time Sand Monitoring Systems.* AIST 2020, LNCS 12602, 319–330.
5. Lee, P.Y., Kasper, S.F. & Quinn, C. (2017). *The 7 Sins of Managing Acoustic Sand Monitoring Systems.* SPE-189213-MS.
6. Wang, K. et al. (2015). *Vibration Sensor Approaches for the Monitoring of Sand Production in Bohai Bay.* Shock and Vibration, 2015, Article ID 591780.
7. Vallen Systeme GmbH. *VS150-RI AE Sensor Data Sheet.* VS150-RI_2208.

---

*Documento generado a partir del análisis de 19 referencias técnicas y del estado actual del proyecto.*  
*Versión 1.0 — Junio 2026*
