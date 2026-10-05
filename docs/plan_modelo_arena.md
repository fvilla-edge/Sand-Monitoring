# Plan: modelo de arena que aprende con cada purga (PAD-7, BPO-2072)

Plan de trabajo y bitácora del modelo que estima la arena a partir del sensor.
**Se anota acá cada decisión, cambio de modelo y resultado, con fecha, en el
momento en que pasa.** Si algún día el modelo deja de funcionar, este archivo,
el registro de predicciones y `docs/estudio_arena_vs_kg.md` (el estudio que le
dio origen) tienen que alcanzar para reconstruir qué se hizo y por qué.

## 1. Objetivo

Por ahora no un número exacto de kg sino un **nivel: poca, media o mucha arena**,
por turno (intervalo entre purgas) y por hora. Más adelante, si los datos lo
sostienen, kg con incertidumbre y el indicador en Losant.

## 2. Restricciones (no cambian)

- **La verdad de campo son las purgas del BBS**, que llegan con la planilla al
  terminar cada turno. Los turnos duran distinto: hay días con más purgas y días
  con menos. **No se pueden pedir purgas más seguidas** (lo dijo el usuario el 2/10/2026).
- Una purga dice cuántos kg salieron en el intervalo, no cuándo.
- Datos continuos del sensor solo desde el **29/9/2026 09:00 local** (CSV del modo
  evento, una fila por ventana de 50 ms con área y kurtosis). Lo anterior son
  mediciones sueltas: no se usan para ajustar.
- Por ventana hay solo 2 números (área, kurtosis). Ningún modelo puede sacar
  más información que la que hay ahí.

## 3. Reglas del juego (para no engañarnos)

1. **Predecir antes de ver.** Cada purga se predice solo con las purgas
   anteriores. Lo que cuenta como prueba son las predicciones "anticipadas":
   hechas con una versión del modelo fijada antes de que terminara el intervalo.
2. **El registro no se edita.** `analisis/estudio_arena/registro_predicciones.csv`
   solo crece. Un modelo nuevo es una versión nueva (v2, v3...) con sus propias
   filas; las de la versión anterior quedan.
3. **No agregar un ingrediente al modelo hasta que mejore las predicciones
   anticipadas**, no el ajuste sobre datos viejos. Con N purgas, a lo sumo
   ~N/5 parámetros.
4. **Toda decisión va a la bitácora (sec.9)** con fecha y por qué, sobre todo
   si se toma después de ver un resultado.

## 4. El modelo actual (v1, fijado 2026-10-02 14:00 UTC)

Script: `analisis/estudio_arena/modelo_arena.py`.

Cada hora aporta `kg = a × picos + b`:
- **picos** = ventanas de 50 ms con kurtosis > 3.5 en esa hora;
- **a** = kg por pico (la arena que se ve como impactos);
- **b** = fondo en kg/h (arena que sale pareja, sin picos visibles).

Como la purga solo da la suma, el ajuste es `kg del intervalo = a × picos totales + b × horas`.
Es una regresión bayesiana: a y b se guardan con su incertidumbre y cada purga
nueva los corrige (al principio mucho, después cada vez menos).

| Parámetro | Valor | Por qué |
|---|---|---|
| Prior a | 0.04 ± 0.04 kg/pico | orden del factor de la sec.9 del estudio (OJO: sale de los mismos datos) |
| Prior b | 0.3 ± 0.5 kg/h | débil; 0 a ~1 kg/h es lo típico de la planilla |
| Ruido por intervalo | 3 kg | ~ error medio de la sec.9 del estudio |
| Intervalo usable | ≥ 80 % de horas con dato | los parciales se predicen pero no se usan para ajustar |
| Niveles (kg/h promedio) | poca < 0.5, media 0.5-3, mucha ≥ 3 | 3 kg/12 h = poca; 12-15 kg/12-16 h = media |

Salida: para cada intervalo, kg predichos ± incertidumbre, probabilidad de
poca/media/mucha y el nivel más probable; para cada hora, kg/h estimados y nivel.

**Estado al fijarlo (4 purgas usables, todas "retro"):** a = 0.028 ± 0.011
kg/pico, b = 0.26 ± 0.24 kg/h. Nivel acertado 2 de 4, error medio 4.4 kg.
Falla el intervalo de 12 kg (lo ve tranquilo) y el de 3 kg (lo ve media).

## 5. Procedimiento cada vez que llega una planilla

1. Guardar la planilla en `datos_campo/planillas/` con la fecha en el nombre
   (`...BPO-2072_<dia><mes>.csv`).
2. Bajar los CSV nuevos de la placa de campo (disco `/mnt/usb/eventos/`, o la SD
   `/root/eventos_sd/` si midió sin disco) a `datos_campo/placa_campo/_bajadas/<AAAAMMDD>/`,
   verificando md5. (O desde GCS: `campo/csv_ventanas/rp-f0fbda/AAAA/MM/DD/`.)
3. Juntarlos en la carpeta por día (README del repo, "CSV de ventanas"):
   ```
   python3 analisis/utilidades/organizar_csv_campo.py datos_campo/placa_campo/csv_por_dia datos_campo/placa_campo/csv_por_dia datos_campo/placa_campo/_bajadas/<AAAAMMDD> --aplicar
   ```
4. Correr:
   ```
   .venv/bin/python analisis/estudio_arena/modelo_arena.py "datos_campo/planillas/<planilla>.csv" datos_campo/placa_campo/csv_por_dia/* --registrar --horas 24
   ```
5. Mirar las purgas nuevas: nivel predicho contra real, error en kg.
6. Anotar en la bitácora (sec.9) una línea por purga nueva: real, predicho,
   acierto, y cualquier cosa rara (horas sin dato, comentario del pozo).
7. Commit del registro + la bitácora.

## 6. Etapas

| Etapa | Cuándo | Qué | Estado |
|---|---|---|---|
| A | ya | Factor que aprende con cada purga (bayesiano) | **hecho en v1** |
| B | ya | Aporte por hora con 2 ingredientes (picos + fondo) | **hecho en v1** |
| C | 2026-10-02 | Agrupar picos en tipos sin usar los kg (`tipos_picos.py`, sec.7 de este plan) | **hecho, 1ra pasada** |
| D | ~15 purgas | Probar un 3er ingrediente (horas en control de separador, caudal, presión de línea) solo si mejora las anticipadas | pendiente |
| E | ~30-50 purgas (~2-4 semanas) | ML con varias variables (regresión regularizada, gradient boosting), validado por tiempo (entrenar con el pasado, predecir el futuro) | pendiente |
| F | cuando acierte | Llevar el nivel a Losant: "arena desde la última purga: poca/media/mucha" | pendiente |
| G | a futuro | Más variables por ventana desde la FPGA (pico, factor de cresta, energía por banda): cambio de firmware y CSV | idea |

## 7. Etapa C: tipos de picos (2026-10-02, primera pasada)

Script: `analisis/estudio_arena/tipos_picos.py` (necesita `scikit-learn`, en `requirements.txt`).
Datos: 78 h de `csv_por_dia` (29/9 12 UTC → 2/10 17 UTC).

**Método.** Ráfaga = ventanas con kurtosis > 3.5 separadas menos de 1 s (1174 ráfagas, la
mayoría de 1 sola ventana). Por ráfaga: cantidad de ventanas, duración, kurtosis máxima,
exceso de área máximo y **"loma" = exceso de área mediano en ±60 s alrededor**. Mezcla
gaussiana elegida por BIC; contexto (hora, control de separador, Starlink, kg) solo para
interpretar, no entra al agrupamiento.

**Qué es robusto.** El BIC no marca un número "natural" de grupos (sigue bajando hasta
k = 8-9): las subdivisiones finas no son estables. Lo que sí es estable (4 semillas, ~90 %)
y se ve como dos poblaciones en el histograma (valle en 0.02-0.03) es la separación por la loma:

| Tipo | Ráfagas | De día (08-16) | En control | Qué parece |
|---|---|---|---|---|
| sin loma (< 0.025) | 773 | 46 % | 36 % | fondo: ~120-180 por intervalo, **igual con 3 que con 15 kg** (r = 0.29) |
| loma moderada (0.025-0.2) | 320 | 28 % | 44 % | episodios |
| loma grande (≥ 0.2) | 81 | 0 % | 100 % | el episodio del 1/10 05:47-07 local |

(Referencia: 38 % de las horas son de día y 23 % en control.)

| Intervalo (local) | kg | sin loma | loma moderada | loma grande |
|---|---|---|---|---|
| 29/09 02 → 14 (parcial) | 8 | 182 | 0 | 0 |
| 29/09 14 → 30/09 02 | **15** | 142 | **178** | 0 |
| 30/09 02 → 14 | 3 | 128 | 0 | 0 |
| 30/09 14 → 01/10 04 | 12 | 130 | 0 | 0 |
| 01/10 04 → 20 | **14** | 122 | **142** | **81** |
| 01/10 20 → (abierto) | ? | 69 | 0 | 0 |

**Lectura.**
- Los picos "con loma" aparecen solo en **dos episodios** (29/9 ~15-16 local y 1/10 ~05:47-07
  local) y esos caen en **los dos intervalos de más kg**. Los picos "sin loma" son un fondo
  parejo que no tiene relación con los kg: hoy M1 los cuenta y eso lo diluye.
- **Lo incómodo:** fuera de esos episodios, el sensor no distingue 3 kg de 12 kg. El intervalo de
  12 kg no tiene ningún episodio. Lo que hoy da el sensor se parece más a "hubo episodio / no hubo"
  que a una cantidad.
- Corrige en parte la sec.4.1 del estudio: la loma del 1/10 no escala con los kg (era enorme y dio
  14 kg, como la chica del 29/9 con 15), pero **su presencia** coincide con los intervalos de más arena.
- El episodio grande del 1/10 fue 100 % con BPO-2072 en control de separador; el del 29/9, fuera de
  control (el control había terminado 11:10). El control solo no lo explica.
- Todo esto se armó mirando los datos (post hoc) y son solo 2 episodios. **Candidato** para el modelo
  v2: "picos con loma" o "hubo episodio". Se prueba con las purgas anticipadas antes de adoptarlo.
  Para el intervalo abierto E (hasta 2/10 14 local: 0 episodios), el candidato dice "sin episodio".

**Siguientes pasos posibles.** (1) Mirar la señal cruda de los episodios: el disco de campo tiene
~200 grabaciones `evento_*` del 29-30/9 (kurtosis ≥ 5) que incluyen el episodio del 29/9; comparar su
forma de onda con picos "sin loma". (2) Revisar con el pozo qué pasó el 29/9 15-16 local (la planilla
no dice nada a esa hora).

### 7.1 Frente: umbral mínimo y actividad sostenida (2026-10-02)

Script: `analisis/estudio_arena/umbral_reposo.py`. Pregunta del usuario: el reposo da kurtosis
≈ 3 y desde ~3.2 se podrían suponer impactos leves; ¿cuál es el umbral mínimo?

**Reposo medido** (20 horas más tranquilas, 1.44 M ventanas): mediana **2.974** (no 3.000),
p1 2.929, p99 3.022, dispersión ≈ **0.020**. Estable entre días (mediana horaria mínima
2.9731-2.9739 los 4 días). Aun en reposo hay 13 ventanas/h > 3.1 y 6/h > 3.2: a 6-11
dispersiones eso no es ruido gaussiano, son eventos chicos reales de origen desconocido.

**Contraste por umbral** (ventanas/h; episodios = las 5 horas con loma de la sec.7):

| Umbral | Piso (reposo) | Episodio | Resto | Episodio / piso |
|---|---|---|---|---|
| 3.03 | 270 | 6021 | 404 | 22 |
| **3.05** | 40 | 3020 | 113 | **76** |
| **3.08** | 18 | 1522 | 62 | **85** |
| **3.10** | 13 | 1048 | 49 | **81** |
| 3.20 | 6 | 376 | 20 | 63 |
| 3.50 | 1 | 136 | 5 | 136 (piso con muy pocos casos) |
| 5.00 | 0 | 14 | 0 | 28 |

**Lectura:**
- **Umbral mínimo de detección ≈ 3.05-3.10**: por debajo el piso del reposo crece rápido; entre
  3.05 y 3.10 el contraste es máximo (~80×) con 10-20 veces más ventanas que con 3.5.
- **Detectar no es cuantificar.** Con umbral bajo el conteo por intervalo predice peor los kg
  (k > 3.05: error LOO 12 kg; k > 3.2: 6.8; k > 3.5: 3.0) porque el episodio del 1/10 suma
  ~20 000 ventanas para 14 kg: el tamaño del episodio no escala con los kg.
- **En los episodios se corre toda la distribución**, no solo la cola: la mediana de la
  kurtosis sube a 2.985-3.008 y va con el exceso de área minuto a minuto (r = 0.86). Coherente
  con muchos impactos leves superpuestos (la "loma" de área sería lo mismo visto de otro lado).
- **Candidato "minutos activos"** (minutos con mediana k > 2.978): en los 4 completos da error LOO
  2.9 kg, r = 0.85 (separa algo 12 kg de 3 kg: 40 contra 25 min). **Pero** falla en el
  intervalo parcial de 8 kg: 153 minutos activos el 29/9 09-14 local (control extendido por la
  falla del mando a distancia) → ~30 kg sin extrapolar. La mediana también se corre con poca arena.
- **Hoy 2/10 09-13 local** la mediana se corrió de nuevo (2.978-2.985, área +0.005), sin loma
  de picos. No es la carga de CPU (sigue después del arreglo de GCS de las 15:28 UTC) ni el
  Starlink (los otros días con Starlink no pasó). Puede ser arena leve o actividad del pad.

**Predicciones registradas para la purga que cierre E** (fijadas 2026-10-02 ~18 UTC, con datos
hasta 2/10 14:16 local; al cerrar se recalculan hasta la hora de la purga):

| Modelo | Qué dice para E | Si la purga da... |
|---|---|---|
| v1 (registro) | ~6 kg, poca 66 % | ≤ 8 kg → v1 acierta |
| C1 "hubo episodio" (picos con loma) | sin episodio → poca | ≤ 8 kg → acierta |
| C2 "minutos activos" (176 min × 0.194) | **~34 kg**, mucha arena | ≥ 20 kg → C2 ve algo que los otros no; ≤ 8 kg → la mediana corrida de día no es arena |

### 7.2 Frentes abiertos (anotados 2026-10-02, en pausa)

1. **Origen de las lomas / mediana corrida**: ¿arena (impactos leves superpuestos) o actividad del
   pad / control de separador? Próximo paso cuando se retome: mirar la señal cruda de los episodios
   (grabaciones `evento_*` del disco de campo del 29-30/9) contra picos "sin loma". **En pausa por
   decisión del usuario.**
2. **Cantidad**: cómo pasar de "hubo actividad" a kg. Hoy lo mejor es v1 (k > 3.5); C1 y C2 se
   juzgan con las purgas anticipadas (sec.7.1).
3. **Umbral mínimo**: detección en 3.05-3.10 (sec.7.1); falta confirmarlo con más días de reposo y
   con episodios nuevos.
4. **Fondo sin loma**: eventos chicos reales que aparecen incluso en reposo (13/h > 3.1); origen
   desconocido (¿eléctrico, mecánico, arena muy fina?).

## 8. Preguntas abiertas para el pozo

- Hora exacta de cada purga (algunas vienen redondeadas a la hora).
- Qué pasa en el pad de día (08-16 local): maniobras, vehículos, otros pozos.
- Qué pasó el 1/10 06:00 local (ráfaga de 254 picos en una hora) y el 29/9 15-16 local (episodio sin comentario en la planilla).
- Qué pasó hoy 2/10 de 09 a 13 local (actividad sostenida leve en el sensor).
- El intervalo de 12 kg (30/9 14:00 → 1/10 04:00) se ve tranquilo en el sensor: ¿algo distinto ese turno?
- Qué pasó en el pad el vie 2/10 de 15 a 17 local y el **sáb 3/10 de 12 a 17 local** (golpes secos fuertes,
  hasta 1275 picos/h, con Starlink apagado): ¿maniobras, equipos, trabajos cerca de la línea?

## 9. Bitácora

- **2026-10-01** — Inicio del estudio (`docs/estudio_arena_vs_kg.md`). Métricas
  M1/M2/M3 fijadas y predicción registrada para el intervalo D antes de la purga.
- **2026-10-02** — Purga D = 14 kg (1/10 20:00 local). Ganó M1 (conteo de picos,
  pred ~18); las métricas de área erraron ×3: las "lomas" no son arena (estudio sec.4.1).
- **2026-10-02** — Umbral de kurtosis de M1 bajado de 3.8 a 3.5 (decisión del
  usuario, después de ver D). Umbral de captura de la placa de campo: sigue en 5.0
  (no se toca; todo esto es post-procesamiento).
- **2026-10-02** — Estudio completo con 32 métricas (estudio sec.9): picos > 3.5
  2.9 kg de error contra 4.2 sin sensor (p ≈ 0.08); validación externa con el 21/9:
  ~220 kg predichos para una purga de 500 kg.
- **2026-10-02** — Indicador cualitativo por hora (estudio sec.10, `nivel_arena.py`):
  cortes 15/80 picos por hora. Desde el 29/9 no hubo ningún intervalo de mucha arena.
- **2026-10-02** — El usuario aclara: purgas más seguidas imposibles (siguen los turnos).
  Se decide ir por el modelo que aprende (etapas A+B) y dejar ML para cuando haya ~30-50 purgas.
- **2026-10-02 14:00 UTC** — **Modelo v1 fijado** (sec.4). Registro creado con 5
  filas retro + el intervalo abierto E (desde 1/10 20:00 local): hasta 2/10 09:45 local
  predice 5.2 ± 4.1 kg, **poca 66 %** / media 34 %. Primera predicción anticipada:
  la purga que cierre E.
- **2026-10-02 ~16 UTC** — CSV reorganizados en `datos_campo/placa_campo/csv_por_dia/<día UTC>/`
  (`organizar_csv_campo.py`, índice en `csv_por_dia/indice.csv`); las carpetas viejas quedan en
  `_carpetas_anteriores/`. Del disco USB de campo se recuperaron horas que faltaban
  (30/9 16 completa, 17 y la 1ra parte de 18 UTC): el intervalo 30/9 14:00 → 1/10 04:00
  pasa de 155 a 144 picos extrapolados (predicción retro 5.0 → 4.7 kg). Las filas del
  registro de v1 calculadas antes quedan como están (regla 2).
- **2026-10-02 ~16:30 UTC** — Estudio re-corrido con `csv_por_dia` (sin purgas nuevas; solo +1.2 h
  en el intervalo de 12 kg y +0.2 h en el de 3 kg). Se mantiene todo: N(k>3.5) error LOO 3.0 kg
  (antes 2.9) contra 4.2 sin sensor; el de 12 kg sigue sin verse (estimado 5.6 kg, 0 horas "mucha").
  Aparece N(k>8) como la mejor del barrido (2.5 kg, r = 0.99, azar 8 %), pero es elegida a posteriori
  y es la que sobreestimó ×7 la purga de 500 kg del 21/9: no se cambia la métrica del modelo (regla 3).
- **2026-10-02 ~17:45 UTC** — Etapa C, primera pasada (sec.7): los picos se separan en "sin loma"
  (fondo parejo, no sigue los kg) y "con loma" (solo 2 episodios, en los intervalos de 15 y 14 kg).
  Fuera de episodios el sensor no distingue 3 de 12 kg. Candidato v2 (post hoc): "hubo episodio".
  Se instaló `scikit-learn` en `.venv`.
- **2026-10-02 ~18 UTC** — Frente umbral mínimo (sec.7.1): reposo = 2.974 ± 0.020; umbral de
  detección 3.05-3.10 (contraste ~80×); detectar ≠ cuantificar. Predicciones de v1, C1 y C2 para
  la purga que cierre E registradas antes de la planilla (C2 dice ~34 kg, los otros ≤ 8).
- **2026-10-05 ~13 UTC** — Planilla 2-5/10 (`...BPO-2072-2-5oct.csv`) + 67 CSV de campo
  (2/10 17 → 5/10 11 UTC, md5 OK contra la placa, sin NUL): `csv_por_dia` = 144 h continuas
  (29/9 12 → 5/10 11 UTC). Tres purgas nuevas, las primeras **anticipadas** de v1:
  - **E** 1/10 20:00 → 2/10 14:00 local (18 h; la purga fue 6 h antes de lo supuesto el 2/10):
    real **10 kg**; v1 7.0 ± 4.7 poca (nivel errado, −3 kg); C1 sin episodio → poca (errado);
    C2 176 min activos → ~34 kg (errado ×3.4). Solo horas: 14.7.
  - **F** 2/10 14:00 → 3/10 10:00 (20 h): real **14 kg**; v1 **34.4 ± 8.3** (1172 picos, +20 kg).
    Solo horas: 15.0.
  - **G** 3/10 10:00 → 4/10 08:00 (22 h): real **15 kg**; v1 **26.0 ± 10.8** (3434 picos, +11 kg).
    Solo horas: 16.3.
  - **Con las 7 purgas completas v1 queda a = 0.0001 ± 0.0011 kg/pico, b = 0.70 kg/h**: los picos
    k > 3.5 no aportan nada; el modelo se reduce a "0.7 kg por hora de intervalo". En anticipadas,
    error medio v1 11.5 kg contra 2.3 kg de "solo horas" (prequential, misma regla). En LOO "solo
    horas" 3.4 kg y "siempre el promedio" 3.6 kg: con 7 purgas de 10-15 kg (salvo una de 3) nada
    le gana a la constante. r(kg, horas) = 0.46.
  - Los picos de F y G vienen de dos tardes: vie 2/10 15-17 local (hasta 556/h) y **sáb 3/10
    12-17 local (hasta 1275/h, Starlink apagado por ser fin de semana)**. Etapa C re-corrida
    (2679 ráfagas, k = 6 por BIC): aparecen tipos casi inexistentes antes del 2/10, golpes secos
    sin loma — g4 (~1.3 s, kurt máx ~21) y g5 (~3.5 s, kurt máx ~71, exceso de área 0.66):
    0-4 por intervalo hasta E, 63+6 en F, 145+24 en G, mayormente de día. No escalan con los kg.
  - C2 re-ajustado (0.114 kg/min) tampoco: F 4.4, G 1.8 kg.
  - Registro: 4 filas nuevas (E, F, G anticipadas + abierto 4/10 08:00 → 5/10 08:59 local,
    25 h, 374 picos, 17.6 ± 3.7 kg).
- **2026-10-05 ~14 UTC** — Modelos sin sensor con toda la historia de la planilla (sec.10, `planilla_historia.py`): 91 intervalos desde el 18/8. Mejor referencia: **tasa de las últimas 24 h × horas** (3.2 kg de error desde el 29/9). Las horas en control de separador casi no dejan arena en el BBS (fracción ajustada 0.00). La planilla no muestra nada raro el sáb 3/10 12-17 local (presiones y orificio planos, sin comentarios).
- **2026-10-05 ~14:30 UTC** — Paso 1 (sec.10.1, `sensor_vs_referencia.py`): el sensor **no explica el residuo** de la referencia "tasa 24 h" en los 7 intervalos con sensor. 8 medidas (k>3.5, k>3.05, k>10, minutos activos; todo el intervalo y solo fuera de control): ninguna correlaciona (p ≥ 0.28) y todas empeoran el LOO (3.2 → 4.5-6.2 kg).
- **2026-10-05 ~15 UTC** — Paso 2 (sec.10.2, `evento_21sep.py`): antes de los 500 kg hubo dos purgas seguidas en 0 kg (38 h, único caso largo) y una baja de ~20 psi en boca de pozo con cambio de ramal el 20/9. El sensor muestra el 21/9 de 09 a 13 local una firma de kurtosis extrema (hasta 2.7 ventanas k > 300 por minuto) que **no aparece en ninguna de las 144 h continuas** desde el 29/9 (máximo 1 ventana k > 300 y 2 k > 200 por hora, incluido el sábado de golpes). Candidato a alarma de evento grande, no a cantidad. Corrección a la sec.10: alternar 0 / X kg es habitual desde el 13/9 y solo 5 de 11 ceros tuvieron control; el "efecto control" está mezclado con esa alternancia.
- **2026-10-05 ~15:30 UTC** — Enfoque del equipo, "área acumulada con k ≥ 3.5" (sec.10.3): el factor kg/área varía 150× entre intervalos (3 a 457 kg por 100 de área neta); LOO 8.3 kg (neta) y 5.3 kg (bruta) contra 3.6 de la constante y 3.2 de la referencia de la planilla. El 80 % del área neta sale de las tardes del 2/10 y 3/10 (14-15 kg). Queda como indicador de actividad, no de kg.
- **2026-10-05 ~16 UTC** — Señal cruda del modo evento (sec.11, `crudas_rasgos.py`): 2646 eventos de 70 ms (29/9 → 5/10, md5 OK) en `datos_campo/crudas_campo/eventos/`; cubren el 98 % de las ventanas k ≥ 5 del CSV (0 % el 1/10 sin disco). A igual kurtosis, los golpes del vie 2/10 y sáb 3/10 son **otro tipo**: menos energía arriba de 400 kHz (~la mitad), centroide más bajo, impacto más largo (0.7-0.8 ms contra 0.3-0.6) y +2-3 dB de SNR. Llegan en trenes de pocos segundos con 7-10 golpes por segundo, sin período fijo. Sin dato de qué son.

## 10. Modelos sin sensor, solo con la planilla (2026-10-05)

Script: `analisis/estudio_arena/planilla_historia.py`. La planilla trae **91 intervalos entre purgas
desde el 18/8** (42 con arena, 1186 kg en total), no solo los 7 que tienen sensor. Es la vara que
el sensor tiene que superar.

- **Arena y orificio:** sin arena hasta 14/64; aparece con 16/64 (13/9) y cada aumento (17, 18, 20/64)
  la sube y después decae. Desde 20/64 (23/9): ~3-5 kg/h → 0.7 kg/h hoy (τ ≈ 5 días).
- **Horas en control de separador (03-09 local):** con ≥ 4 h de control 1.05 kg/h (n = 12), con ≤ 1 h
  3.43 kg/h (n = 9); el ajuste da **fracción 0.00 en horas de control** (26-27/9: 0 kg en los
  intervalos 02→14 y 30 kg en los 14→02). Confundido con la hora del día (los intervalos con control
  son siempre los de la mañana). Pregunta física: ¿la arena de esas horas va al separador de control
  y no al BBS?
- La columna "Producción sólidos kg/hora" no sirve: es la purga repartida hacia atrás.
- **Prequential desde 20/64** (error medio; los últimos 7 son los que tienen sensor):

| Modelo | Todos (13) | Desde 29/9 (7) |
|---|---|---|
| constante | 9.0 | 8.6 |
| solo horas (tasa de todo lo previo) | 14.8 | 17.7 |
| última tasa × horas | 11.4 | 5.3 |
| **tasa de las últimas 24 h × horas** | **7.4** | **3.2** |
| decaimiento exponencial | 9.2 | 5.2 |
| decaimiento + control | 7.3 | 3.6 |
| (sensor v1, solo 3 anticipadas) | — | 11.5 |

  "Solo horas" anduvo bien en sec.9 únicamente porque arrancaba el 29/9, con la tasa ya estable.

### 10.1 Paso 1: ¿el sensor explica lo que le erra la referencia? (2026-10-05)

Script: `analisis/estudio_arena/sensor_vs_referencia.py`. Residuo = kg real − (tasa de los 2
intervalos previos × horas). 7 intervalos completos con sensor (30/9 02:00 → 4/10 08:00 local).

| Medida del sensor | ρ con el residuo | p (permutación exacta) | LOO ref + sensor |
|---|---|---|---|
| (referencia sola) | | | **3.2 kg** |
| n k > 3.5 / solo fuera de control | 0.32 / 0.14 | 0.50 / 0.78 | 5.4 / 4.6 |
| n k > 3.05 / fuera | 0.39 / −0.14 | 0.40 / 0.78 | 4.8 / 5.2 |
| n k > 10 / fuera | 0.16 / 0.02 | 0.73 / 0.99 | 4.6 / 4.5 |
| minutos activos / fuera | 0.09 / −0.49 | 0.86 / 0.28 | 6.2 / 4.6 |

- Los dos residuos grandes no se ven en el sensor: 30/9 14:00 (3 kg, −8.5) es un intervalo común;
  2/10 14:00 (10 kg, −5.6) es el de más minutos activos (176).
- El episodio del 1/10 (20 324 ventanas k > 3.05) cayó 95 % **dentro** del control de separador, las
  horas que según la planilla casi no dejan arena en el BBS, y el intervalo dio 14 kg.
- Con 7 puntos, un efecto de ±3 kg no se podría ver: no prueba que el sensor no sirva, prueba que
  hoy no le agrega nada a la planilla.

### 10.2 Paso 2: ¿hubo precursores del evento de 500 kg (21/9)? (2026-10-05)

Script: `analisis/estudio_arena/evento_21sep.py`.

**Planilla.** Antes de la purga de 500 kg (21/9 20:00 local) hubo **dos purgas seguidas en 0 kg**,
19/9 07:00 → 20/9 21:00 (38 h), en una época de ~1 kg/h. Es el único caso largo: el otro par de
ceros (13/9, 6 h) fue al empezar la arena. En el medio, el 20/9 a las 08:00 "leve variable en presión
boca de pozo, una baja de ~20 psi" y a las 11:00 "cambio de ramal y chequeo de orificio, no se
observa obstrucción". Presiones, caudales, agua y GOR del control del 21/9 03-09: normales. Lectura
[suposición]: arena retenida en algún lado y liberada de golpe. Es un solo caso.

**Corrección a la sec.10:** alternar 0 / X kg es lo habitual desde el 13/9 (11 ceros) y solo 5 de los
11 tuvieron ≥ 2 h de control. El "efecto control" está mezclado con esa alternancia.

**Sensor.** Paquetes del 21/9 (69 min grabados de 23 h, nombrados `campo_con_arena`: se grabó cuando
se veía arena) contra los CSV continuos de la FPGA (144 h, 29/9 → 5/10):

| | k > 100 | k > 200 | k > 300 |
|---|---|---|---|
| 21/9 09 local (por hora, extrapolado) | ~335 | ~235 | ~160 |
| 21/9 13 local | ~25 | ~20 | ~16 |
| 21/9 15-17 y 22/9 09-10 | ~0 | 0 | 0 |
| **Peor hora de las 144 h** (sáb 3/10 12-17) | 11 | **2** | **1** |
| Horas con ≥ 3 ventanas, de 144 | 6 | **0** | **0** |

- La firma de k > 200-300 del 21/9 a la mañana **no aparece nunca** en 6 días continuos, ni con los
  golpes del sábado: separa sin falsas alarmas el único evento grande conocido.
- Decae de 09 a 13 y se apaga a las 15, pero las purgas horarias de esa noche dieron 25-35 kg/h
  (21-01 local), sin sensor en esas horas. Puede marcar el **comienzo** del evento y no su duración.
- Cuidados: un solo evento; umbrales elegidos después de mirar; los paquetes vienen de la cadena de
  software y no de la FPGA (validadas iguales en sec.182 de la memoria, no sobre este dato).
- **Candidato (no aplicado): alarma "evento grande" = ≥ 3 ventanas con k > 200 en una hora.** Con
  la tasa de hoy no hubiera saltado nunca; el 21/9 hubiera saltado ~11 h antes de la purga de 500 kg.
  Se juzga con el próximo evento grande, sin tocar el umbral.

### 10.3 Enfoque del equipo: área acumulada con k ≥ 3.5 (2026-10-05)

Propuesta del equipo (gráfico "Área acumulada" de su herramienta): sumar el área de cada ventana
con kurtosis ≥ 3.5 y relacionar el acumulado entre purgas con los kg. Es la métrica M2 del estudio
(`docs/estudio_arena_vs_kg.md` sec.2). Calculada igual que en la herramienta (base = mediana; la
neta de 1/10-4/10 da ~630 contra 642.91 en pantalla):

| Purga (fin, local) | kg | Área bruta | Área neta | kg por 100 de neta |
|---|---|---|---|---|
| 30/9 02:00 | 15 | 208.1 | 28.4 | 53 |
| 30/9 14:00 | 3 | 76.5 | 4.9 | 61 |
| 1/10 04:00 | 12 | 75.3 | 4.3 | 280 |
| 1/10 20:00 | 14 | 255.2 | 60.3 | 23 |
| 2/10 14:00 | 10 | 36.2 | 2.2 | 457 |
| 3/10 10:00 | 14 | 668.8 | 73.9 | 19 |
| 4/10 08:00 | 15 | 2230.5 | 487.7 | 3 |

| Modelo (LOO, 7 purgas) | Error medio |
|---|---|
| kg = a · área neta | 23.4 kg |
| kg = a · área neta + b | 8.3 kg |
| kg = a · área bruta + b | 5.3 kg |
| kg = a · N ventanas k ≥ 3.5 + b | 4.8 kg |
| constante | 3.6 kg |
| tasa de las últimas 24 h × horas (sin sensor) | 3.2 kg |

- El 80 % del área neta acumulada sale de las tardes del 2/10 y del 3/10 (golpes secos, sec.9),
  en intervalos de 14 y 15 kg; el de 10 kg acumula 2.2.
- **Decisión:** el área acumulada queda como **indicador de actividad** (cuándo pasó algo), no como
  estimador de kg. Para volver a probarla como kg hay que separar primero los golpes secos, lo que
  depende de saber qué pasó en el pad esas tardes (sec.8).

## 11. Señal cruda de los eventos (2026-10-05, primera pasada)

Pedido del usuario: empezar con lo medido con la cadena actual (CSV + eventos del modo evento); el
21/9 se midió de otra forma (paquetes de software, sin cruda) y queda solo como referencia.

**Datos.** 2646 eventos `evento_*.bin` + `.json` bajados del disco de campo a
`datos_campo/crudas_campo/eventos/` (1.4 GB, md5 OK): 70 ms de cruda int16 a 3.906 MHz por cada
ventana con kurtosis ≥ 5 (umbral de captura). Cobertura de las ventanas k ≥ 5 del CSV: 98 %
(29/9 100 %, 30/9 62 % por la caída del disco, **1/10 0 %** porque midió sin disco, 2-5/10 100 %).
**45 % viene con hueco** (tramo con datos viejos del buffer, posición desconocida): todo se
calculó con y sin ellos y da lo mismo.

**Rasgos** (`analisis/estudio_arena/crudas_rasgos.py`, salida `analisis/outputs/crudas/rasgos_eventos.csv`):
kurtosis, rms, pico y cresta de la filtrada 50-400 kHz; energía por banda de la cruda; y del
**impacto más fuerte** (bloque de 1 ms menos el fondo del propio evento): fracción por banda,
centroide, SNR, duración hasta −20 dB y frecuencia dominante.

- La energía por banda de la ventana entera no sirve: la domina el ruido electrónico (52 % arriba
  de 800 kHz). La frecuencia dominante tampoco: todo suena a ~172 kHz (resonancia del sensor).
- **A igual kurtosis** (golpes vie 15-18 + sáb 12-18 contra noche + resto del día, sin hueco):

| Kurtosis FPGA | 5-7 | 7-10 | 10-20 | > 20 |
|---|---|---|---|---|
| Centroide del impacto (kHz) | 318 / 441 | 268 / 348 | 241 / 253 | 196 / 229 |
| Fracción > 400 kHz | 0.15 / 0.29 | 0.10 / 0.18 | 0.07 / 0.10 | 0.03 / 0.05 |
| Duración del impacto (ms) | 0.78 / 0.76 | 0.79 / 0.63 | 0.72 / 0.29 | 0.75 / 0.51 |
| SNR del impacto (dB) | 6.6 / 4.2 | 7.9 / 5.9 | 9.3 / 8.0 | 13.3 / 10.1 |
| n | 399 / 139 | 270 / 31 | 314 / 25 | 270 / 14 |

  Los golpes son **otro tipo**, no los mismos con más frecuencia: más graves, más largos y más
  energéticos que los eventos sueltos del resto del tiempo.
- **Ritmo:** llegan en trenes (sáb 12-18: 94 trenes de ≥ 3 golpes, mediana 7 golpes y 3 s, máximo
  105 golpes y 32 s), con 50-150 ms entre golpes (7-10 por segundo) y sin período fijo; CV de los
  intervalos 2.5-5 (Poisson = 1; horas de referencia 1.3-1.7).
- [Suposición] Algo que traquetea en ráfagas (válvula o choke vibrando, pieza floja, tapones de
  sólidos más grandes) más que una maza manual (~1 golpe/s). Las purgas no muestran más arena
  esos días (14-15 kg) y la planilla está plana.
- **No hay verdad de campo de arena con esta cadena:** ningún evento del 29/9 en adelante está
  confirmado como arena; el 21/9 (arena confirmada) no tiene cruda en la PC y sus paquetes solo
  traen área y kurtosis, así que no se puede comparar el espectro.
- **Para la FPGA (pregunta del usuario):** los rasgos que separan los golpes del fondo son un
  cociente de bandas del impacto (100-400 kHz contra > 400 kHz) y la duración del impacto; ninguno
  sale de la kurtosis ni del área. Antes de implementarlos falta saber cuál de los dos tipos es arena.

