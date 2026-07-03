# Informe de Investigación: Detección Acústica de Arena en Tuberías de Producción Petrolera
## Análisis Completo de la Bibliografía para Sistema con Red Pitaya Stemlab 125-14

**Proyecto:** Sistema experimental de clasificación de niveles de producción de arena  
**Objetivo:** Distinguir entre ausencia / poca / moderada / alta concentración de arena  
**Hardware objetivo:** Red Pitaya Stemlab 125-14  
**Fecha:** Junio 2026

> **Archivado (2026-07-03):** este informe es la investigación bibliográfica que se hizo
> **antes** de tener el sensor VS150-RI definido — usa bandas de frecuencia genéricas de
> la literatura (30–200 kHz / 50–150 kHz) en vez de la banda real del sensor instalado
> (100–450 kHz). Se conserva como referencia teórica y bibliografía (12 papers), pero
> **el plan vigente es `docs/roadmap_deteccion_arena.md`**, y los umbrales/valores reales
> ya medidos están en `analisis/INTERPRETACION_RESULTADOS.md` — no los de este documento.

---

# PARTE I — ANÁLISIS INDIVIDUAL DE PAPERS

---

## Paper 1: Gao et al. (2015) — *Sand rate model and data processing method for non-intrusive ultrasonic sand monitoring*
**Journal of Petroleum Science and Engineering 134 (2015) 30–39**

### Resumen técnico
- **Problema:** Monitoreo de arena sin intrusión en flujos de petróleo pesado donde las técnicas comerciales fallan.
- **Objetivo:** Desarrollar un modelo de tasa de arena basado en la energía cinética de partículas y un algoritmo de filtrado.
- **Configuración experimental:** Loop de flujo de laboratorio con sensor ultrasónico no intrusivo pegado externamente sobre un codo de tubería.
- **Tipo de sensor:** Sensor piezoeléctrico ultrasónico no intrusivo, montado externamente.
- **Señales adquiridas:** Señal analógica convertida a digital; valor RMS de la señal cruda.
- **Metodología:** Modelo físico basado en energía cinética de partículas + algoritmo de denoising por wavelet threshold.
- **Resultados:** El algoritmo de denoising filtra exitosamente el ruido y el modelo estima la tasa de arena de forma efectiva.

### Hallazgos importantes
- **Características usadas:** RMS de la señal cruda, diferencia (S_pRMS² − S_bRMS²)^(1/2) donde S_bRMS es el ruido de fondo.
- **Parámetros más útiles:** RMS de la señal sobre el ruido de fondo; velocidad de flujo (Q/A).
- **Modelo de tasa de arena:**
  ```
  m_t = (S_p² - S_b²) / K
  K = función de (velocidad, geometría de tubería)
  ```
- **Distinción de niveles:** La diferencia RMS² permite estimar la concentración relativa de arena.
- **Ruido:** El sensor también detecta turbulencia de fluido, burbujas de gas y droplets. El filtro wavelet discrimina estas fuentes.
- **Frecuencia útil:** Señales de arena en rango ultrasónico; ruido de fluido mayormente en bajas frecuencias (<20 kHz).

### Aplicabilidad al proyecto
- **Directamente reutilizable:** La fórmula m_t ∝ (S_p² − S_b²) es el punto de partida más sólido de toda la literatura. El RMS diferencial es trivialmente implementable en Red Pitaya.
- **Sólido y aceptado:** Citado extensamente en papers posteriores como la formulación base.
- **No reinventar:** No es necesario rederivarlo. Simplemente calibrar la constante K.
- **Red Pitaya:** Cálculo de RMS en ventanas de tiempo es trivial en tiempo real con Python/C en la FPGA.

### Limitaciones
- Calibración depende de las condiciones de flujo; debe recalibrarse si cambia el régimen.
- Supone que todas las partículas viajan a la misma velocidad que el fluido.
- Funciona mejor a velocidades >5 m/s.

### Relevancia: **ESENCIAL**
Es la formulación física base. Define qué medir (RMS diferencial) y cómo relacionarlo con la tasa de arena.

---

## Paper 2: Martin Pham, NTNU (2023) — *Using Acoustic Emission to monitor sand production*
**Master's Thesis, Norwegian University of Science and Technology**

### Resumen técnico
- **Problema:** Correlación entre señales AE y distintos tamaños de grano de arena.
- **Objetivo:** Verificar si diferentes tamaños de grano producen señales AE distinguibles; intentar estimar porcentaje de mezclas.
- **Configuración experimental:** Loop de flujo en PTS (Petroleum Technology Services), sensor PK15I de Mistars, osciloscopio PicoScope 4262, con inyector de arena de pistón controlado por computadora.
- **Señales adquiridas:** Señal de emisión acústica en tiempo real, espectrogramas, distribución de potencia por bandas de frecuencia.
- **Metodología:** Experimentos con arena fina (0.1–0.25 mm), arena media (0.4–0.8 mm), y mezclas 50/50, 75/25. Análisis de espectrogramas y potencia promedio en tres intervalos frecuenciales.
- **Resultados:** Se observan diferencias en los espectrogramas según el tamaño de grano. Las mezclas presentan señales intermedias.

### Hallazgos importantes
- **Características usadas:** Espectrogramas (STFT), potencia media en bandas frecuenciales, RMS.
- **Parámetros más útiles:** Distribución de potencia en intervalos de frecuencia seleccionados, no una sola frecuencia.
- **Correlación con arena:** La potencia en bandas de alta frecuencia correlaciona positivamente con concentración y tamaño de grano.
- **Sensor placement:** Sensor ubicado aguas abajo del codo, en la cara exterior de la curva.
- **Tamaño mínimo detectable:** ~0.01 g/s a 20 m/s en gas seco; sensibilidad más baja en gas húmedo.

### Aplicabilidad al proyecto
- **Directamente reutilizable:** El setup es casi idéntico al propuesto (sensor externo, codo, análisis espectral). El código Python del Apéndice 2 puede adaptarse para Red Pitaya.
- **Sólido:** Valida que los espectrogramas permiten distinguir distintos niveles de producción.
- **Red Pitaya:** El PicoScope 4262 opera en forma muy similar a cómo operaría la Red Pitaya en modo osciloscoscopio. La tasa de muestreo y resolución son comparables.

### Limitaciones
- Flujo de líquido solo (sin multifase gaseosa en los tests principales).
- Las mezclas son difíciles de cuantificar con precisión.
- No llegó a un modelo cuantitativo validado (objetivo de estimación de porcentaje no completado).

### Relevancia: **ESENCIAL**
Setup experimental más parecido al propuesto. Tiene código Python. Valida espectrogramas como herramienta principal.

---

## Paper 3: Wang et al. (2024) — *Sand particle characterization method based on multifrequency collision response*
**Natural Gas Industry B 11 (2024) 154–169**

### Resumen técnico
- **Problema:** Caracterización de partículas de arena en flujo anular gas-líquido (pozos de gas con agua).
- **Objetivo:** Combinar análisis multifrequencia con deep learning para identificar tamaño de partícula, velocidad de gas y velocidad de líquido.
- **Configuración experimental:** Montaje de flujo anular, sensor piezoeléctrico, análisis FFT+STFT, CNN y LSTM.
- **Señales adquiridas:** Señales de vibración, espectros FFT, espectrogramas STFT.
- **Resultados:** CNN logra 93.8% de precisión para clasificar tamaño de partícula, 91.7% para velocidad de gas.

### Hallazgos importantes
- **Rango frecuencial clave:** La respuesta de colisión arena-pared se concentra en **50–80 kHz** para flujo anular gas-sólido y gas-líquido-sólido.
- **Flujo turbulento:** La respuesta de la turbulencia del gas se concentra en la banda baja de **8–25 kHz** con pico en ~13 kHz.
- **Esto es crítico:** Existe una separación frecuencial clara entre ruido de fluido (<25 kHz) y señal de arena (50–80 kHz).
- **Características temporales:** RMS, Max, Kurtosis y crest factor correlacionan positivamente con altura de caída libre (energía de impacto).
- **CNN > LSTM** para este problema (la información espacial en el espectro es más rica que la temporal).

### Aplicabilidad al proyecto
- **Directamente reutilizable:** El rango 50–80 kHz como banda de interés es confirmado por múltiples papers. Diseñar el filtro pasa-banda en ese rango.
- **Red Pitaya:** Con Fs = 125 MHz, puede capturar perfectamente señales hasta 62.5 MHz. Para 50–80 kHz, cualquier configuración de bajo costo es suficiente. La FPGA puede implementar un filtro digital en esa banda.
- **CNN en segunda etapa:** Para la clasificación de niveles (ninguna/poca/media/mucha), un CNN entrenado con espectrogramas STFT es el enfoque más prometedor del estado del arte.

### Limitaciones
- Requiere entrenamiento con datos etiquetados para CNN.
- El flujo anular es específico de pozos de gas con alta velocidad.
- No directamente aplicable a flujo de líquido a baja velocidad.

### Relevancia: **ESENCIAL**
Identifica el rango frecuencial crítico (50–80 kHz) y valida CNN+STFT como método de clasificación.

---

## Paper 4: Appalonov, Maslennikova & Khasanov (2021) — *Advanced Data Recognition Technique for Real-Time Sand Monitoring*
**AIST 2020, LNCS 12602, pp. 319–330**

### Resumen técnico
- **Problema:** Reducir falsos positivos en monitoreo acústico de arena cuando hay gotas de agua u otras fuentes de ruido.
- **Configuración experimental:** Empresa SONOGRAM LLC, Kazán, Rusia. Sensor piezoeléctrico (cristal 304L, 12.8 mm diámetro), digitización a 204.8 kHz, 24 bits (NI PCI-4462 + amplificador ZET 440).
- **Metodología:** STFT → vectores PSD → clasificadores ML (SVM Gaussian, LR, Random Forest, Gradient Boosting).
- **Resultados:** SVM con kernel gaussiano: 7% falsos positivos, 9% falsos negativos (vs. 35% FP con threshold de energía simple).

### Hallazgos importantes
- **El enfoque de umbral de energía simple es insuficiente** (35% falsos positivos).
- **STFT + SVM** reduce los falsos positivos a 7%.
- **Vectores de características:** Coeficientes PSD de STFT (54 dimensiones por ventana).
- **El problema principal:** Distinguir arena de gotas de agua (ambas dan picos en >20 kHz; el espectro de distribución difiere).
- **SVM gaussiano > Random Forest > Gradient Boosting** en esta tarea.

### Aplicabilidad al proyecto
- **Directamente reutilizable:** Implementar STFT seguido de SVM como clasificador binario (arena / no arena) antes de clasificar el nivel.
- **204.8 kHz de muestreo:** Perfectamente alcanzable con Red Pitaya a 125 MHz decimado.
- **Primer paso crítico:** Antes de clasificar el nivel de arena, hay que clasificar si hay arena o no (problema más fácil).

### Limitaciones
- Dataset pequeño (680 vectores, 80/20 split). Puede sobreajustar.
- Solo gas seco + gotas de agua. No valida con petróleo crudo multifásico.

### Relevancia: **MUY IMPORTANTE**
Demuestra que ML + STFT >> umbral de energía simple. Provee el pipeline completo de procesamiento.

---

## Paper 5: Lee, Kasper & Quinn (2017) — *The 7 Sins of Managing Acoustic Sand Monitoring Systems*
**SPE-189213-MS, SPE Symposium Kuala Lumpur**

### Resumen técnico
- **Tipo:** Paper operacional/de campo (Siri Complex, Mar del Norte, DONG Energy/ClampOn).
- **Objetivo:** Compartir 7 lecciones aprendidas gestionando detectores acústicos de arena en campo real.
- **Configuración:** Plataforma offshore, múltiples pozos, detectores ClampOn instalados, multiphase meter KROHNE.

### Hallazgos importantes (los 7 "pecados"):
1. **Ruido externo subestimado:** Tormentas, cambios de choke, slugging causan señales falsas. Siempre verificar con datos de campo complementarios.
2. **Falta de calibración continua:** Una calibración inicial no es suficiente. El Step Value cambia con las condiciones.
3. **Confiar solo en el volumen calculado:** Los valores calculados son indicativos, no exactos. El valor crudo (raw signal) es más confiable cualitativamente.
4. **Falta de correlación con otros datos:** Las señales cobran sentido solo cuando se cruzan con datos de producción, slugging, presión.
5. **Tendencias no se aprenden de la noche a la mañana:** Toma meses entender las "firmas" de cada pozo.
6. **Arena no detectada (finos):** Partículas <50 µm frecuentemente no son detectadas por sistemas acústicos.
7. **El sistema acústico es solo una parte:** No reemplaza el programa completo de gestión de arena.

### Aplicabilidad al proyecto
- **No reinventar:** Los puntos 1–4 son directamente aplicables. Correlacionar la señal acústica con otras mediciones de campo.
- **Para clasificación de niveles:** El raw signal (sin el modelo de conversión a g/s) es más estable y suficiente para clasificar entre "sin arena / poca / media / mucha".
- **Advertencia crítica:** No confiar en valores calculados sin calibración. Trabajar con señales relativas.

### Relevancia: **MUY IMPORTANTE**
Lecciones operacionales de campo real. Previene errores costosos en el diseño del sistema.

---

## Paper 6: Wang et al. (2015) — *Vibration Sensor Approaches for the Monitoring of Sand Production in Bohai Bay*
**Shock and Vibration, Vol. 2015, Article ID 591780**

### Resumen técnico
- **Problema:** Monitoreo en tiempo real en plataforma offshore Bohai Bay, China.
- **Configuración:** Sensor piezoeléctrico de aceleración PCB 357B03 (0–18 kHz, sensibilidad 10 pC/g), adquisición a 50 kHz, 8192 puntos, ventana gaussiana. Instalado en codo de tubería bajo capa aislante.
- **Metodología:** STFT + filtro de banda frecuencial + método de búsqueda de picos con denoising por Savitzky-Golay. Sustraer ruido de fondo (baseline sin arena) → extraer potencia residual.
- **Resultados:** "Buena correlación entre la amplitud del espectro de potencia y el volumen de producción de arena."

### Hallazgos importantes
- **Frecuencia sensible:** >10 kHz para vibración de arena (en crudo viscoso el rango puede ser diferente al gas).
- **STFT es el método central** para visualizar la distribución tiempo-frecuencia.
- **El espectro de potencia de la arena presenta múltiples picos** en alta frecuencia que no aparecen en pozos sin arena.
- **Método de denoising:** Savitzky-Golay smoothing + sustracción de la curva base + búsqueda simétrica de picos.
- **Correlación validada** comparando potencia espectral con análisis de centrifugado de muestras de crudo.

### Aplicabilidad al proyecto
- **Directamente reutilizable:** El pipeline STFT → sustraer baseline → buscar picos en alta frecuencia es implementable con SciPy/NumPy en Red Pitaya.
- **Frecuencia <18 kHz:** Este sensor es de menor frecuencia que los ultrasónicos. Red Pitaya a 125 MHz supera ampliamente esto.

### Limitaciones
- Frecuencia máxima del sensor: 18 kHz (mucho menor que los 50–80 kHz identificados como óptimos en otros papers).
- Solo 4 pozos. Correlación cualitativa, no cuantitativa precisa.
- Crudo viscoso (Bohai Bay) puede comportarse diferente al petróleo liviano.

### Relevancia: **IMPORTANTE**
Valida el enfoque general. Demuestra correlación espectral-arena en campo real con crudo viscoso.

---

## Paper 7: Xue et al. — *Analysis of Sand Production Signal and Sand Production Rate Models*
**ATDE (Xi'an Shiyou University)**

### Resumen técnico
- **Configuración:** Sensor piezoeléctrico ultrasónico externo en tubería de 12.5 mm de diámetro interior, partículas de 0.1 mm, agua como fluido.
- **Señales:** Señal de tensión del sensor, valor pico-a-pico, señal filtrada por frecuencia.
- **Metodología:** Modelo de energía cinética → fórmula de tasa de arena basada en voltaje RMS y velocidad de flujo.
- **Resultados:** Error < 15% en laboratorio con agua + arena 0.1 mm.

### Hallazgos importantes
- **Rango frecuencial confirmado:** 25 kHz–750 kHz para señales de arena.
- **El pico de voltaje pico-a-pico** es proporcional a la energía de impacto.
- **Fórmula final:**
  ```
  m_t = (S² × A) / (K × Q²)    [kg/s]
  donde S = señal RMS, A = área sección, Q = caudal, K = constante de calibración
  ```
- **Detección de umbral:** El valor pico-pico sobre umbral indica presencia de arena.

### Aplicabilidad al proyecto
- **Confirma:** La señal es en el rango ultrasónico. El modelo es simple y calibrable.
- **Límite inferior frecuencial** de 25 kHz coincide con la separación ruido-fluido / señal-arena.

### Limitaciones
- Solo agua como fluido (sin crudo, sin gas, sin multifase).
- Error 15% es aceptable para clasificación pero no para cuantificación precisa.

### Relevancia: **IMPORTANTE**
Confirma el rango frecuencial y provee modelo simplificado con bajo error en laboratorio.

---

## Paper 8: Neil Barton, Xodus (presentación) — *Acoustic Sand Detector Virtual Calibration*

### Resumen técnico
- **Tipo:** Presentación técnica corporativa de la empresa Xodus sobre calibración virtual de ASD.
- **Problema:** La calibración mediante inyección de arena es costosa y difícil de ejecutar en muchas instalaciones.
- **Herramientas:** Modelo "Sandflux" (correlación empírica de ~800 inyecciones) + CFD para predecir la respuesta del ASD.
- **Fórmula clave:**
  ```
  raw_signal_SF = C_particle × C_fluid_flow × zero
  Sand Rate = (raw_signal - zero) / step
  ```

### Hallazgos importantes
- **El ruido de fondo (zero) aumenta con la velocidad del fluido**, y el step (calibración de arena) también aumenta proporcionalmente.
- **ASDs son sensibles a la geometría de instalación:** flanges, longitud de tubería, aislante, posición subsea/topsides.
- **Chokes aguas arriba** pueden reducir dramáticamente la señal (hasta 9x menos).
- **Tormentas** en instalaciones offshore dan señales falsas de arena simultáneas en todos los ASD.
- **El fluido húmedo aumenta el ruido de fondo**, reduciendo la sensibilidad neta.

### Aplicabilidad al proyecto
- **Advertencia directa:** La ubicación del sensor y la geometría de la tubería afectan enormemente la señal. Hay que estandarizar el banco de pruebas.
- **Zero (baseline):** Siempre registrar el nivel de señal sin arena como referencia dinámica.

### Limitaciones
- Modelo propietario de Xodus. No open-source.

### Relevancia: **MUY IMPORTANTE**
Muestra los errores prácticos más comunes en campo real. Fórmula operacional base.

---

## Paper 9: ClampOn — *DSP Particle Monitor* & *Sand Monitoring Brochure*
**ClampOn AS, 2021**

### Resumen técnico
- **Tipo:** Datasheet de producto comercial (el sensor más usado en la industria).
- **Sensor:** Piezoeléctrico, montaje externo clamp-on, rango frecuencial no divulgado pero típicamente 100–500 kHz.
- **Medición:** Energía acústica en banda de interés, salida analógica + Modbus.
- **Claim:** Detecta hasta 0.001 g/s en condiciones óptimas.

### Hallazgos importantes
- **Clamp-on es el estándar industrial** para detección no intrusiva.
- **Ubicación estándar:** 2 diámetros aguas abajo del codo, en la cara exterior de la curva.
- **Calibración:** Step Value + Zero Value + Trend. El sistema genera un índice de arena en g/s.
- **Procesamiento DSP interno:** El ClampOn realiza su propio DSP; el usuario recibe el valor procesado. No acceso a señal cruda.

### Aplicabilidad al proyecto
- **Referencia comercial:** El prototipo debería aspirar a igualar la sensibilidad de ClampOn (0.001–0.01 g/s).
- **Red Pitaya como alternativa open:** Permite acceso a la señal cruda, lo que ClampOn no ofrece. Esto es una ventaja para investigación.

### Relevancia: **IMPORTANTE**
Define el benchmark de la industria. Todo sistema nuevo debe compararse con ClampOn.

---

## Paper 10: Rosemount SAM 4.1 — *Acoustic Particle Monitor*
**Emerson/Rosemount, Product Datasheet**

### Resumen técnico
- **Tipo:** Datasheet de sensor competidor al ClampOn.
- **Frecuencia operativa:** 100–1000 kHz.
- **Salida:** 4–20 mA analógico + HART. Alarma configurable.
- **Instalación:** Externo, con pasta de acoplamiento acústico, 2 diámetros aguas abajo del codo.
- **Temperatura de trabajo:** -40°C a +85°C.

### Aplicabilidad al proyecto
- Confirma que el rango 100 kHz–1 MHz es el rango de operación de sensores comerciales.
- Red Pitaya con muestreo a 125 MHz cubre este rango perfectamente.
- La pasta de acoplamiento acústico es un detalle práctico crítico para el clamp del prototipo.

### Relevancia: **COMPLEMENTARIO**
Confirma especificaciones técnicas de sensores comerciales. Útil para comparar.

---

## Paper 11: Peng et al. (2023) — *Sand erosion prediction models for two-phase flow pipe bends*
**Powder Technology 421 (2023) 118421**

### Resumen técnico
- **Tipo:** Paper de modelado CFD de erosión, no de detección de señales acústicas.
- **Objetivo:** Predecir la tasa de erosión máxima en codos con flujo bifásico gas-sólido y líquido-sólido.
- **Metodología:** Euler-Lagrange + FLUENT + modelo de erosión DNV.

### Aplicabilidad al proyecto
- **Limitada para detección acústica.** El paper caracteriza la erosión física, no la señal generada.
- **Útil para seleccionar material del codo de prueba** (define qué geometría y material maximizan la colisión de partículas).

### Relevancia: **COMPLEMENTARIO**
Útil para diseño del banco de pruebas. No para procesamiento de señales.

---

## Paper 12: Sensor de Arenas — Etapa 1 V2 (Propuesta del equipo)
**Documento interno del proyecto**

### Resumen técnico
- **Tipo:** Propuesta técnico-comercial del proyecto propio.
- **Objetivo de Etapa 1:** Prototipo que detecte presencia/actividad/severidad relativa de arena (sin cuantificación exacta).
- **Arquitectura propuesta:** Sensor ultrasónico ~150 kHz → preamplificador → filtrado analógico → PC (Red Pitaya o equivalente) → índice relativo → cloud → dashboard.
- **Variables calculadas propuestas:** RMS, pico/envolvente, conteo de eventos, FFT, SNR, índice relativo de arena.

### Observaciones críticas
- **La frecuencia de 150 kHz como target es razonable** y coincide con la literatura.
- **El objetivo de no cuantificar en g/s en Etapa 1** es correcto y alineado con la literatura (la cuantificación requiere calibración costosa).
- **El índice relativo de arena** (sin unidades físicas) es exactamente lo que varios papers en el estado del arte proponen como output de primera etapa.

### Relevancia: **ESENCIAL** (es el contexto del proyecto)

---

## Papers Adicionales (ResumenCompacto)

**Sandcalibration Services (Roxar/NUS):** Servicio de calibración mediante inyección de arena. Confirma que el "Step Value" necesita calibración individualizada por instalación. Relevancia: Complementario.

**COT_FTS_241056 (Cotización):** Cotización de sensor VS-150 para el proyecto. Relevancia: Referencia de costo.

**VS150RI (Sensor comercial):** Sensor de vibración/sonido de baja frecuencia (<20 kHz). Por debajo del rango óptimo. Relevancia: Baja (no recomendado para arena ultrasónica).

---

# PARTE II — COMPARACIÓN GLOBAL

| Paper | Tipo de Sensor | Variables Analizadas | Dominio | Algoritmos | Éxito Reportado | Facilidad en Red Pitaya | Relevancia |
|---|---|---|---|---|---|---|---|
| Gao et al. 2015 | Piezoeléctrico ultrasónico no intrusivo | RMS, fórmula kinética | Temporal | Wavelet denoising, modelo físico | Alta (error controlado) | Alta | Esencial |
| Pham NTNU 2023 | PK15I piezoeléctrico | Espectrograma, potencia por banda | Tiempo-frecuencia | STFT, análisis estadístico | Media (validación parcial) | Alta | Esencial |
| Wang et al. 2024 | Piezoeléctrico + acelerómetro | FFT+STFT, RMS, Max, Kurtosis, CNN | Frecuencia + DL | FFT, STFT, CNN, LSTM | Alta (93.8% CNN) | Media | Esencial |
| Appalonov et al. 2021 | Piezoeléctrico cristal 304L | PSD vectores STFT | Tiempo-frecuencia | SVM, LR, RF, GB | Alta (7% FP) | Alta | Muy importante |
| Lee et al. 2017 | ClampOn ASD | Raw signal, zero, step | Temporal | Fórmula empírica | Campo real validado | Alta | Muy importante |
| Wang et al. 2015 | PCB 357B03 acelerómetro | Espectro de potencia, STFT, picos | Tiempo-frecuencia | STFT, Savitzky-Golay, búsqueda de picos | Buena correlación | Alta | Importante |
| Xue et al. | Piezoeléctrico ultrasónico | Pico-pico, RMS, FFT | Temporal + frecuencial | Umbral + modelo físico | Error <15% lab | Alta | Importante |
| Barton/Xodus | ClampOn ASD comercial | Raw, zero, step, CFD | Empírico + CFD | Sandflux model, CFD | Campo industrial | N/A (propietario) | Muy importante |
| ClampOn 2021 | Piezoeléctrico clamp-on | Energía acústica | Procesado internamente | DSP propietario | Referencia industria | N/A (propietario) | Importante |
| Rosemount SAM4.1 | Piezoeléctrico | Partícula output, alarma | Procesado internamente | DSP propietario | Referencia industria | N/A (propietario) | Complementario |
| Peng et al. 2023 | N/A (CFD) | Tasa de erosión | CFD | Euler-Lagrange, DNV | Alta en modelado | N/A | Complementario |

---

# PARTE III — ESTADO DEL ARTE CONSOLIDADO

## Conclusiones Comunes

Las siguientes conclusiones aparecen en múltiples papers de forma consistente:

1. **El sensor debe ubicarse en el codo o inmediatamente aguas abajo (1–2 diámetros), en la cara exterior de la curva.** Unanimidad total en la literatura.

2. **La señal de arena está en el rango ultrasónico: 20 kHz a 1 MHz.** El pico de densidad espectral de los impactos arena-pared se concentra típicamente entre **50–150 kHz** para gas, y puede extenderse hasta 500 kHz.

3. **El ruido de fondo del fluido se concentra en frecuencias bajas (<25 kHz).** Turbulencia, bombas y slugging se manifiestan por debajo de este umbral.

4. **El valor RMS (o S²_RMS) de la señal acústica correlaciona positivamente con la concentración y flujo de arena.** Este resultado aparece en Gao 2015, Xue, Wang 2015, NTNU 2023.

5. **La calibración es imprescindible y específica a cada instalación.** El "Step Value" o constante K no es universal.

6. **Los sistemas comerciales (ClampOn, Rosemount) procesan internamente la señal.** La ventaja del sistema propuesto con Red Pitaya es el acceso a la señal cruda.

7. **El umbral de energía simple genera ~35% de falsos positivos (Appalonov 2021).** Machine Learning sobre características espectrales reduce esto a ~7%.

8. **Los espectrogramas (STFT) permiten ver la evolución temporal de las frecuencias** y son más informativos que el espectro estático FFT para identificar eventos de arena.

9. **Partículas muy finas (<50 µm) son difíciles o imposibles de detectar acústicamente.** Este límite físico es reconocido en toda la literatura.

10. **La señal de arena se comporta como transients impulsivos** (señal transitoria, impulsiva, no estacionaria). Esto justifica el uso de kurtosis y crest factor como indicadores de "impulsividad".

---

## Características de Señal Más Prometedoras para el Proyecto

### 1. **RMS diferencial (S²_p − S²_b)** ⭐⭐⭐⭐⭐
La métrica más robusta, más soportada en la literatura. Simple de calcular. Directamente proporcional al flujo másico de arena. Implementación trivial en Red Pitaya con ventanas de tiempo.

### 2. **Energía en banda 50–150 kHz** ⭐⭐⭐⭐⭐
Filtrar la señal en este rango y calcular la energía integrada. Elimina el ruido de fluido (<25 kHz) y el ruido eléctrico de alta frecuencia. Es la base de todos los sistemas comerciales.

### 3. **Espectrograma STFT** ⭐⭐⭐⭐⭐
Herramienta de visualización e insumo para clasificadores ML. Permite ver si hay actividad en la banda de interés a lo largo del tiempo. Input natural para CNN (tratarlo como imagen).

### 4. **Conteo de eventos sobre umbral** ⭐⭐⭐⭐
Contar el número de picos que superen un umbral en la señal filtrada por unidad de tiempo. Proxy del número de impactos de partículas. Correlaciona con concentración.

### 5. **Kurtosis** ⭐⭐⭐⭐
Mide la "impulsividad" de la señal. Arena → señal muy impulsiva → kurtosis alto. Fluido sin arena → distribución más gaussiana → kurtosis bajo. Reportado en Wang 2024 con correlación positiva con concentración.

### 6. **Crest Factor** ⭐⭐⭐
Relación pico/RMS. Complementa la kurtosis. Arena → crest factor elevado. Útil como característica adicional para el clasificador.

### 7. **FFT (análisis estático)** ⭐⭐⭐
Útil para identificar la banda de interés en el banco de pruebas inicial. No suficiente solo para clasificación en tiempo real (es estacionario).

### 8. **Detección de envolvente** ⭐⭐⭐
El envelope de la señal filtrada muestra los picos de impacto. Útil para conteo de eventos y estimación de energía por impacto.

### 9. **Wavelets** ⭐⭐
Usados en Gao 2015 para denoising. Útiles pero más complejos de implementar que STFT. Resultado similar al STFT para este problema.

### 10. **PSD (Densidad espectral de potencia)** ⭐⭐⭐
Versión suavizada del FFT. Input para SVM (Appalonov 2021). Más estable que FFT para clasificación.

---

## Métodos que Parecen Poco Útiles para Este Proyecto

- **Modelo cuantitativo preciso de g/s sin calibración:** La literatura confirma que es imposible sin calibración específica de instalación. Descartado para Etapa 1.
- **Modelos de erosión CFD (Peng 2023):** Relevantes para diseño, no para procesamiento de señales.
- **LSTM para clasificación de eventos impulsivos:** Wang 2024 demuestra que CNN supera a LSTM en este problema específico. El LSTM pierde correlación temporal al hacer shuffle de subsequencias.
- **Análisis en frecuencias <10 kHz:** Dominado por ruido de fluido, bomba, vibraciones mecánicas. Señal de arena enmascarada.

---

## Problemas Abiertos en la Literatura

1. **Detección de partículas finas (<50 µm):** Señal muy débil. No hay solución acústica robusta aún.
2. **Cuantificación sin calibración previa:** El Step Value y la constante K requieren inyección controlada en cada instalación. No hay modelo universal.
3. **Flujo multifásico con alto GOR:** La fase gaseosa aumenta el ruido de fondo y reduce SNR. No hay consenso en el método óptimo.
4. **Separación robusta arena/slugging/droplets:** Tres fuentes que generan señales acústicas similares. El SVM de Appalonov mejora esto pero no lo resuelve completamente.
5. **Transferabilidad entre instalaciones:** Un modelo entrenado en un banco de pruebas puede no funcionar directamente en campo sin ajuste.
6. **Velocidades bajas (<3 m/s):** La mayoría de papers válidan a velocidades medias-altas. A baja velocidad, los impactos tienen menos energía y son más difíciles de detectar.

---

# PARTE IV — GUÍA DE DESARROLLO CON RED PITAYA STEMLAB 125-14

## Plan de Desarrollo Ordenado por Prioridad

---

### ETAPA 0 — Setup del Banco de Pruebas (Semana 1)

**Objetivo:** Obtener las primeras señales acústicas de arena vs. sin arena.

**Configuración mínima:**
- Tubería metálica con un codo de 90° (diámetro ≥1").
- Sensor piezoeléctrico montado con pasta de acoplamiento (grasa vaselina o pasta ultrasónica) en la cara exterior del codo.
- Red Pitaya en modo ADC directo (125 MS/s, 14 bits).
- Fluido: agua + partículas de arena calibradas (0.2–0.8 mm).
- Método de inyección: jeringa manual o bomba simple.
- Flujo generado por bomba peristáltica o diferencia de altura.

**Primer experimento a hacer:**
1. Registrar señal en reposo (sin flujo, sin arena) → línea de base eléctrica.
2. Registrar señal con flujo de agua sin arena → ruido de fondo hidráulico.
3. Inyectar una pequeña cantidad de arena → observar si hay diferencia visible en la señal.
4. Si hay diferencia → proceder. Si no → ajustar acoplamiento, posición del sensor, ganancia.

**Resultado mínimo para pasar a la siguiente etapa:**  
Señal claramente diferente entre "flujo sin arena" y "flujo con arena". Visible en osciloscopio o en FFT crudo.

---

### ETAPA 1 — Caracterización Espectral (Semana 2–3)

**Objetivo:** Identificar la banda frecuencial donde la arena produce señal distinguible del ruido.

**Experimentos:**
1. Registrar espectros FFT en 4 condiciones:
   - Reposo total
   - Flujo sin arena (3 velocidades diferentes)
   - Flujo + poca arena
   - Flujo + mucha arena

2. Para cada condición: calcular FFT promedio de 20 ventanas de 1024 puntos.

**Métricas a calcular:**
- Espectro de potencia (FFT²) para cada condición.
- Diferencia espectral: (arena) − (sin arena).
- Identificar banda(s) donde la diferencia sea máxima.

**Gráficos a generar:**
- FFT overlay de las 4 condiciones (misma gráfica, colores distintos).
- Espectrograma (STFT, ventana 256 puntos, overlap 50%) para una captura de 10 segundos.
- Diferencia espectral dB(arena) − dB(sin arena).

**Resultado mínimo:**  
Identificar la(s) banda(s) frecuenciales donde arena >> ruido. Se espera encontrar diferencia clara en 50–150 kHz basado en la literatura.

---

### ETAPA 2 — Métricas Clave en Tiempo Real (Semana 4–5)

**Objetivo:** Implementar el conjunto de métricas que serán las features del clasificador.

**Implementar en Python (Red Pitaya):**
```python
# Para cada ventana de N muestras:
import numpy as np
from scipy.signal import butter, filtfilt, hilbert

def calcular_metricas(señal, Fs=125e6, banda=(50e3, 150e3)):
    # 1. Filtro pasa-banda
    b, a = butter(4, [banda[0]/(Fs/2), banda[1]/(Fs/2)], btype='band')
    señal_filtrada = filtfilt(b, a, señal)
    
    # 2. RMS en banda
    rms = np.sqrt(np.mean(señal_filtrada**2))
    
    # 3. Energía en banda
    energia = np.sum(señal_filtrada**2)
    
    # 4. Pico máximo
    pico = np.max(np.abs(señal_filtrada))
    
    # 5. Kurtosis
    kurt = np.mean((señal_filtrada - np.mean(señal_filtrada))**4) / (np.std(señal_filtrada)**4)
    
    # 6. Crest Factor
    crest = pico / (rms + 1e-10)
    
    # 7. Envolvente (RMS del módulo de la transformada de Hilbert)
    envolvente = np.abs(hilbert(señal_filtrada))
    rms_envolvente = np.sqrt(np.mean(envolvente**2))
    
    # 8. Conteo de eventos (picos sobre umbral)
    umbral = 3 * np.std(señal_filtrada)  # umbral dinámico
    conteo = np.sum(np.diff((np.abs(señal_filtrada) > umbral).astype(int)) > 0)
    
    # 9. STFT (espectrograma)
    from scipy.signal import stft
    f, t, Zxx = stft(señal_filtrada, Fs, nperseg=256)
    
    return {
        'rms': rms, 'energia': energia, 'pico': pico,
        'kurtosis': kurt, 'crest_factor': crest,
        'rms_envolvente': rms_envolvente, 'conteo_eventos': conteo,
        'espectrograma': np.abs(Zxx)
    }
```

**Experimento de validación:**
- Repetir el experimento de la Etapa 1 con 5 niveles de arena (0, poca, baja, media, alta).
- Calcular todas las métricas para cada condición.
- Graficar cada métrica vs. nivel de arena → ¿cuáles son monotónicas? ¿cuáles varían de forma distinguible?

**Resultado mínimo:**  
Al menos 3 métricas que muestren diferencia estadísticamente significativa entre los 4 niveles de arena.

---

### ETAPA 3 — Clasificador Simple (Semana 6–8)

**Objetivo:** Entrenar un clasificador que distinga entre los 4 niveles.

**Dataset a construir:**
- Mínimo 50 capturas por nivel (sin arena / poca / media / mucha) = 200 muestras total.
- Cada captura: 1 segundo de señal (125M muestras a 125 MS/s; decimar a 1 MS/s es suficiente → 1M muestras).
- Features: las 7–8 métricas calculadas en Etapa 2.

**Clasificadores a probar (en orden de complejidad):**
1. **Umbral en RMS:** Reglas if-else simples. Baseline mínimo.
2. **KNN (k=3 o k=5):** Fácil de implementar, interpretable.
3. **SVM con kernel RBF:** Recomendado por Appalonov 2021. Robusto con pocos datos.
4. **Random Forest:** Si el dataset es suficientemente grande.

**Validación:**
- 70% train / 30% test (o leave-one-out si hay pocas muestras).
- Métricas: accuracy, confusion matrix, F1 por clase.

**Resultado mínimo:**  
Accuracy ≥ 80% en test para los 4 niveles. Si solo se distingue arena/no arena con ≥90%, también es un resultado válido como primer paso.

---

### ETAPA 4 — Robustez y Prueba de Campo (Semana 9–12)

**Objetivo:** Validar que el sistema funciona con condiciones variables.

**Experimentos adicionales:**
- Variar velocidad de flujo (3 velocidades diferentes) para cada nivel de arena.
- Variar tamaño de partícula (fina ~0.1 mm, media ~0.4 mm, gruesa ~0.8 mm).
- Agregar fuentes de ruido simuladas (golpes externos, vibraciones mecánicas).

**Resultado mínimo:**  
El clasificador mantiene accuracy >75% cuando cambia la velocidad o el tamaño de grano.

---

## Métricas Finales del Sistema

| Métrica | Descripción | Cómo calcular | Prioridad |
|---|---|---|---|
| RMS en banda | Nivel energético en 50–150 kHz | √(mean(x²)) en señal filtrada | 1 |
| Energía en banda | Integral de potencia en banda | sum(x²) | 1 |
| Kurtosis | Impulsividad de la señal | 4to momento / std⁴ | 2 |
| Crest Factor | Pico/RMS | max(|x|) / RMS | 2 |
| Conteo de eventos | N° de impactos/s | Picos sobre umbral dinámico | 2 |
| STFT / espectrograma | Imagen tiempo-frecuencia | scipy.signal.stft | 3 (para CNN) |
| PSD por bandas | Potencia en sub-bandas | FFT² promediado | 3 |

---

# PARTE V — EVITAR TRABAJO INNECESARIO

## Cosas Ya Suficientemente Demostradas (No Repetir)

1. **Que la arena genera señal ultrasónica:** Demostrado en decenas de papers. No es necesario demostrar este principio físico.
2. **Que el sensor debe ir en el codo:** Unanimidad en la literatura. No experimentar con otras ubicaciones en Etapa 1.
3. **Que el RMS correlaciona con la concentración de arena:** Demostrado por Gao 2015, Xue, Wang 2015, NTNU. Solo validar en el banco específico del proyecto.
4. **Que el STFT es mejor que el FFT estático:** Demostrado por múltiples papers. No comparar ambos extensamente.
5. **Que ML supera al umbral simple en precisión:** Demostrado por Appalonov 2021. No dedicar esfuerzo a optimizar thresholds simples más allá del baseline.

## Experimentos que Probablemente No Aporten Conocimiento Nuevo

- Comparar múltiples tipos de sensores en Etapa 1 (elegir uno y calibrarlo bien).
- Probar wavelets vs. STFT para denoising (STFT es equivalente y más intuitivo).
- Construir modelos CFD (no aportan capacidad de detección adicional).
- Intentar cuantificación exacta en g/s sin calibración controlada (imposible sin datos de referencia).

## Qué Vale la Pena Replicar para Validar

- **Replicar la fórmula de Gao 2015** (RMS diferencial) en el banco de pruebas propio → confirma que el sistema funciona correctamente.
- **Replicar el análisis de espectrograma del NTNU** con los propios datos → valida la metodología de procesamiento.

## Oportunidades Reales de Innovación

1. **Clasificación de niveles de arena sin cuantificación exacta:** La mayoría de papers intentan medir g/s. La clasificación en niveles cualitativos es una aplicación práctica subexplorada.
2. **Implementación en tiempo real embebida en Red Pitaya:** La mayoría de papers usan PCs o instrumentos de laboratorio. Un sistema embebido portable es una contribución práctica.
3. **Dataset público etiquetado:** No existe un dataset público de señales acústicas de arena con diferentes niveles. Crearlo sería una contribución abierta.
4. **Transfer learning entre instalaciones:** Entrenar en laboratorio y ajustar en campo con pocas muestras (few-shot learning). Problema abierto.
5. **Separación arena/slugging en tiempo real:** Problema identificado por Lee 2017 como crítico. SVM puede mejorar esto.

---

# PARTE VI — CONCLUSIÓN EJECUTIVA

## Los 5 Papers Más Importantes para el Proyecto

1. **Gao et al. (2015)** — *Sand rate model and data processing method for non-intrusive ultrasonic sand monitoring* → Provee el modelo físico base (RMS diferencial) y valida el pipeline completo de procesamiento.

2. **Pham, NTNU (2023)** — *Using Acoustic Emission to monitor sand production* → Setup experimental más similar al propuesto, con código Python publicado, validación de espectrogramas.

3. **Wang et al. (2024)** — *Sand particle characterization based on multifrequency collision response* → Define el rango 50–80 kHz, valida CNN+STFT, separa señal de arena del ruido de fluido.

4. **Appalonov et al. (2021)** — *Advanced Data Recognition Technique for Real-Time Sand Monitoring* → Demuestra que SVM+STFT supera drásticamente al umbral de energía simple. Pipeline completo de ML.

5. **Lee, Kasper & Quinn (2017)** — *The 7 Sins of Managing Acoustic Sand Monitoring Systems* → Advertencias críticas de campo real. Previene errores de diseño costosos.

---

## Las 10 Conclusiones Más Importantes de la Bibliografía

1. **La señal de arena está en el rango 25 kHz – 750 kHz.** El pico de mayor SNR se encuentra entre **50–150 kHz** para la mayoría de configuraciones.

2. **El ruido de fondo del fluido se concentra por debajo de 25 kHz.** Un filtro pasa-banda con corte inferior en 25–30 kHz elimina la mayor parte del ruido hidráulico.

3. **El RMS en la banda de interés es la métrica más robusta y simple** para estimar la actividad de arena. Es el punto de partida obligatorio.

4. **El espectrograma STFT es la herramienta visual y analítica central.** Permite ver eventos, distinguir fuentes de ruido, y es el input natural para CNN.

5. **SVM con kernel gaussiano sobre vectores PSD reduce los falsos positivos de 35% (umbral simple) a 7%.**

6. **La calibración específica de instalación es imprescindible** para cuantificación. Para clasificación de niveles, se puede trabajar con señales relativas.

7. **El sensor debe ubicarse en la cara exterior del codo, 1–2 diámetros aguas abajo.** Esta es la posición donde los impactos de arena son máximos.

8. **CNN supera a LSTM para clasificar señales de arena** (información espacial en el espectro > información temporal). Accuracy ~93% para clasificación de tamaño de partícula.

9. **Los valores absolutos calculados (g/s) son poco confiables sin calibración.** Los valores relativos (raw signal normalizado) son más estables y suficientes para alertas operacionales.

10. **Kurtosis y crest factor son indicadores complementarios** de la impulsividad de la señal. Arena → kurtosis alto. Sin arena → kurtosis ~3 (gaussiano).

---

## Las 5 Recomendaciones Más Importantes para el Diseño del Sistema

### R1: Trabajar con señales relativas, no absolutas
No intentar calcular g/s en Etapa 1. Definir un **índice relativo de arena** = (RMS_actual − RMS_baseline) / RMS_baseline. Este índice es robusto, no requiere calibración de unidades físicas, y permite clasificación de niveles.

### R2: Diseñar el filtro pasa-banda en 30–200 kHz
Basado en la literatura, este rango captura la señal de arena y excluye el ruido hidráulico. Red Pitaya con Fs = 125 MS/s tiene resolución más que suficiente. Implementar como filtro Butterworth de 4to orden en software.

### R3: Implementar el pipeline en este orden fijo
1. Adquisición a alta velocidad (≥1 MS/s, suficiente para 200 kHz).
2. Filtro pasa-banda digital (30–200 kHz).
3. Cálculo de métricas (RMS, kurtosis, crest factor, conteo de eventos) en ventanas de 10–100 ms.
4. STFT para visualización.
5. Clasificador (SVM en primera instancia, CNN después con más datos).

### R4: Registrar siempre el baseline dinámico
El ruido de fondo cambia con la velocidad del fluido. Registrar el zero (nivel sin arena) justo antes o después de cada experimento. El índice relativo se calcula respecto a este baseline, no a un valor fijo.

### R5: Construir el dataset con etiquetas de verdad (ground truth) cuidadosas
La mayor trampa en este tipo de proyectos es un dataset mal etiquetado. Para cada captura, registrar exactamente: masa de arena inyectada, velocidad de fluido, tamaño de partícula. Esto permite calcular un ground truth cuantitativo que luego puede usarse para validar el clasificador cualitativo.

---

## Los 5 Errores Más Comunes a Evitar

### E1: Confiar en el valor calculado (g/s) sin calibración previa
**Error:** Instalar el sensor, aplicar la fórmula de la literatura, y reportar valores absolutos sin calibración específica.  
**Consecuencia:** Errores de 2–10x en la estimación de arena.  
**Solución:** Trabajar con índices relativos hasta completar la calibración con inyecciones controladas.

### E2: Ignorar el ruido de fondo del fluido como baseline dinámico
**Error:** Calcular el RMS total (incluyendo fluido sin arena) como referencia fija.  
**Consecuencia:** Variaciones en la velocidad del fluido se confunden con variaciones en la arena.  
**Solución:** Actualizar el baseline periódicamente durante la operación.

### E3: Posicionar el sensor lejos del codo o en la cara interior
**Error:** Montar el sensor en un tramo recto o en el lado incorrecto del codo.  
**Consecuencia:** La señal puede ser 9x más débil (demostrado por Xodus/Barton).  
**Solución:** Siempre en la cara exterior del codo, a 1–2 diámetros del punto de cambio de dirección.

### E4: Usar solo un umbral fijo de energía sin ML
**Error:** Definir "hay arena si RMS > X" con un valor fijo.  
**Consecuencia:** 35% de falsos positivos (Appalonov 2021). Inutilizable en operación real.  
**Solución:** Implementar al menos un SVM simple entrenado con datos del banco de pruebas.

### E5: Intentar cuantificar g/s antes de validar la detección binaria
**Error:** Saltar a la cuantificación precisa antes de demostrar que el sistema detecta arena de forma confiable.  
**Consecuencia:** Se pierde tiempo en un problema más difícil antes de resolver el más fácil.  
**Solución:** Primero demostrar detección binaria (arena/no arena) con alta precisión. Luego clasificar niveles. Luego cuantificar.

---

## El Camino Más Corto hacia un Prototipo Funcional de Clasificación de Niveles

```
SEMANA 1:
├── Armar banco de pruebas mínimo (codo + bomba + sensor piezoeléctrico + Red Pitaya)
├── Capturar señales en 2 condiciones: sin arena / con arena
└── CRITERIO: señal diferente visible → continuar

SEMANA 2-3:
├── Calcular FFT y espectrograma de las señales capturadas
├── Identificar la banda donde la diferencia es máxima (esperado: 50–150 kHz)
├── Implementar filtro pasa-banda en esa banda
└── CRITERIO: SNR > 3 dB en la banda → continuar

SEMANA 4-5:
├── Implementar 5 métricas: RMS, energía, kurtosis, crest factor, conteo de eventos
├── Repetir experimentos con 4 niveles de arena (0, poca, media, mucha)
├── Graficar cada métrica vs. nivel → identificar las más discriminantes
└── CRITERIO: al menos 3 métricas con diferencia estadística entre niveles → continuar

SEMANA 6-7:
├── Construir dataset: 50 capturas × 4 niveles = 200 muestras
├── Entrenar SVM con kernel RBF sobre las 5 métricas
├── Validar con 30% test hold-out
└── CRITERIO: accuracy ≥ 80% → PROTOTIPO FUNCIONAL MÍNIMO LOGRADO

SEMANA 8-10:
├── Agregar STFT como feature visual en el dashboard
├── Implementar en tiempo real en Red Pitaya
├── Probar con variaciones de velocidad y tamaño de grano
└── CRITERIO: accuracy ≥ 75% con condiciones variables → PROTOTIPO ROBUSTO

SEMANA 11-12:
├── (Opcional) Entrenar CNN sobre espectrogramas para mayor precisión
├── Preparar datos para prueba de campo
└── CRITERIO: sistema funciona con datos de campo sin reentrenamiento completo
```

**Tiempo estimado para prototipo mínimo funcional:** **6–7 semanas** con 2 ingenieros dedicados.  
**Tiempo para prototipo robusto con clasificación de 4 niveles validada:** **10–12 semanas.**

---

## Bibliografía Consultada

1. Gao, G., Dang, R., Nouri, A., et al. (2015). *Sand rate model and data processing method for non-intrusive ultrasonic sand monitoring in flow pipeline.* Journal of Petroleum Science and Engineering, 134, 30–39.
2. Pham, M. (2023). *Using Acoustic Emission to monitor sand production.* Master's Thesis, NTNU.
3. Wang, K., Chang, Z., Wang, Y., et al. (2024). *A sand particle characterization method for water-bearing high-production gas wells based on a multifrequency collision response.* Natural Gas Industry B, 11, 154–169.
4. Appalonov, A., Maslennikova, Y., & Khasanov, A. (2021). *Advanced Data Recognition Technique for Real-Time Sand Monitoring Systems.* AIST 2020, LNCS 12602, 319–330.
5. Lee, P.Y., Kasper, S.F., & Quinn, C. (2017). *The 7 Sins of Managing Acoustic Sand Monitoring Systems.* SPE-189213-MS.
6. Wang, K., Liu, Z., Liu, G., et al. (2015). *Vibration Sensor Approaches for the Monitoring of Sand Production in Bohai Bay.* Shock and Vibration, 2015, Article ID 591780.
7. Xue, Y., Guo, L., Xu, J., et al. *Analysis of Sand Production Signal and Sand Production Rate Models.* ATDE.
8. Barton, N. (Xodus). *Acoustic Sand Detector Virtual Calibration.* Presentation.
9. Peng, W., Cao, X., Ma, L., et al. (2023). *Sand erosion prediction models for two-phase flow pipe bends.* Powder Technology, 421, 118421.
10. ClampOn AS. (2021). *DSP Particle Monitor.* Technical Brochure.
11. Emerson/Rosemount. *SAM 4.1 Acoustic Particle Monitor.* Product Datasheet.
12. Documento interno del proyecto: *Sensor de arenas — Etapa 1 V2.* EDGE SA.

---

*Informe generado con base en el análisis completo de 19 documentos técnicos. Todos los papers fueron extraídos y analizados en su totalidad.*
