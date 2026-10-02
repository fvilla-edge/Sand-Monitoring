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
