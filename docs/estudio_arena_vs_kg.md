# Estudio: área del sensor vs kg de arena (PAD-7, BPO-2072)

Objetivo final: poder decir "esta cantidad de área corresponde a X kg de arena".
Se avanza de a un paso, agregando un punto por cada purga.

Iniciado el 2026-10-01. Script: `analisis/estudio_arena/metricas_purgas.py`.

## 1. Qué es la verdad de campo

- Planilla del pozo (`datos_campo/planillas/Planilla de Ensayo PAD-7.xlsx - BPO-2072.csv`,
  fuera de git como el resto de `datos_campo/`).
- **La medición real son las purgas del BBS**: "Purga de BBS del pozo BPO-2072,
  Aporte: N kg de arena", con su hora. Entre una purga y la siguiente salieron
  N kg, sin saber cuándo dentro de ese intervalo.
- **El kg/hora de la planilla no es un dato horario**: es N dividido por las
  horas desde la purga anterior (verificado: 15 kg / 12 h = 1.25 kg/h).
  Puede haber salido todo junto en minutos.
- Purgas cada ~12 h (02:00 y 14:00 local), a veces 14 h. El 21-22/9 hubo
  purgas cada 1 h (500, 50, 35, 30, 23, 8 kg...).
- **Supuesto sin confirmar:** la planilla está en hora local (UTC−3). Los CSV
  del sensor están en UTC.

## 2. Métricas (definiciones FIJADAS el 2026-10-01, antes de ver la purga que cierra D)

Con los CSV del modo evento (`ventanas_*.csv`, una fila por ventana de 50 ms):

| Métrica | Qué mide | Definición |
|---|---|---|
| M1 | picos, cantidad | ventanas con kurtosis > 3.5 (hasta el 2/10: > 3.8, ver sec.8) |
| M2 | picos, energía | suma de (área − base) en esas ventanas |
| M3 | "lomas" lentas | suma de (área − base) en las ventanas con exceso > 0.008 |

Base = percentil 20 de la mediana por minuto del área, en una ventana móvil
de ±90 min. No cambiar estas definiciones sin anotar aquí por qué y cuándo
(si se cambian después de ver un resultado, ese resultado deja de ser prueba).

Por qué tres: la arena confirmada del 21/9 se vio como **picos impulsivos**
(kurtosis hasta 841), pero el 29/9 y el 1/10 aparecieron **lomas** de área
(+19% durante 51 min el 29/9 15:40 local, +87% durante 70 min el 1/10 05:47
local) con la kurtosis en ~3.0, que un umbral de kurtosis no ve. Hipótesis
abiertas: arena densa (muchos impactos superpuestos vuelven la estadística
gaussiana) o un fenómeno del flujo (gas, caudal) que no es arena.

## 3. Tabla de intervalos

| Inicio (local) | Fin (local) | kg | h | h con dato | M1 | M2 | M3 | En control (h) | P línea (psi) |
|---|---|---|---|---|---|---|---|---|---|
| 29/09 02:00 | 29/09 14:00 | 8 | 12 | **5.0 (parcial)** | 114 | 4.08 | 1382 | 8 | 464 |
| 29/09 14:00 | 30/09 02:00 | **15** | 12 | 11.0 | 190 | 14.68 | 3690 | 0 | 421 |
| 30/09 02:00 | 30/09 14:00 | **3** | 12 | 11.7 | 85 | 3.44 | 734 | 6 | 455 |
| 30/09 14:00 | 01/10 04:00 | **12** | 14 | 12.4 | 79 | 2.84 | 1142 | 0 | 417 |
| 01/10 04:00 | 01/10 20:00 | **14** | 16 | 15.7 | 210 | 33.77 | 10034 | 6 | 447 |
| 01/10 20:00 | (abierto) | ? | — | 13.8 hasta 2/10 09:45 | 29 | 0.89 | 212 | 3 | 438 |

Columnas M1/M2 de esta tabla con kurtosis > 3.8. Con > 3.5 (sec.8), en el mismo orden:
M1 = 189, 354, 141, 137, 384, 56; M2 = 6.22, 26.66, 4.83, 4.36, 60.76, 1.49.

Lo que se ve con 3 intervalos completos (no alcanza para una curva):
- M1 no separa 3 kg de 12 kg (85 contra 79).
- M3 ordena igual que los kg (15 > 12 > 3); kg por unidad de M3: 0.0041,
  0.0041 y 0.0105 (al de 12 kg le falta la 1.6 h siguiente a su purga).

## 4. Predicción registrada ANTES de la purga que cierra D (2026-10-01 ~14:00 UTC)

Factor = 30 kg (A+B+C) / suma de la métrica en A+B+C. Con los datos de D
hasta el 1/10 09:00 local (es un piso: se suma lo que pase hasta la purga):

| Métrica | Factor | D hasta 09 local | kg predichos |
|---|---|---|---|
| M1 | 0.085 kg/ventana | 176 | ~15 |
| M2 | 1.43 kg/unidad | 30.8 | ~44 |
| M3 | 0.0054 kg/unidad | 9582 | ~52 (39-100) |

Lectura: si la purga da ~10-20 kg, las lomas no son arena (gana M1); si da
~40 kg o más, la arena densa no se ve con kurtosis (ganan M2/M3).

### 4.1 Resultado (2026-10-02, planilla del 2/10)

Purga que cierra D: **1/10 20:00 local, 14 kg** (intervalo de 16 h, no de 12 h;
15.7 h con dato). Con los datos completos de D: M1 = 210, M2 = 33.8, M3 = 10034.

| Métrica | Predicción con D completo | Real | Error |
|---|---|---|---|
| M1 | 0.085 × 210 = **~18 kg** | 14 | +28 % |
| M2 | 1.43 × 33.8 = ~48 kg | 14 | +245 % |
| M3 | 0.0054 × 10034 = ~54 kg | 14 | +290 % |

Conclusión según la lectura fijada de antemano: **ganó M1; la loma del 1/10
05:47-07:00 local no fue arena** (o, si lo fue, no en la proporción que
supone M3). Esto no prueba que M1 funcione: con 4 intervalos completos su
correlación con los kg es r = 0.70 (no significativa) y el factor kg/M1 varía
4 veces entre intervalos (0.035 a 0.15).

Dato a preguntar: el 64 % de las ventanas > 3.5 de D (254 de 384) cayeron en
**una sola hora, 1/10 06 local**, dentro de la loma, con kurtosis hasta 30.5.
Esa noche BPO-2072 entró en control a las 03:00 local, pero la noche
siguiente (2/10 03:00) entró en control igual y no hubo ráfaga: el cambio de
control solo no la explica.

## 5. Otros parámetros que pueden influir (registrarlos en cada intervalo)

Del pozo (planilla), con por qué importan:
- **Caudal de gas y de líquido**: la energía del impacto crece con la velocidad
  del fluido; el mismo kg a más velocidad da más área. Solo se miden mientras
  BPO-2072 está en control de separador.
- **Control de separador** (horas de BPO-2072 en control): cambia el camino
  del flujo y la presión de línea (~490 psi en control contra ~420 fuera).
  Observación sin explicar: los intervalos con control (3 kg, y los de 8 kg y
  D) contra los sin control (15 y 12 kg).
- **Orificio/choke** (mm): cambia la velocidad; hubo cambios el 16/9 (16→18/64")
  y el 23/9 (18→20/64").
- **Presión de boca de pozo**: baja lento (3290 → 3200 psi en 3 días).
- **Temperatura de boca, % de agua, densidades**: cambian el amortiguamiento
  del sonido en el fluido y el acople del sensor.
- **Eficiencia del BBS**: si no atrapa toda la arena, los kg son un mínimo.
- **Hora real de la purga**: la planilla redondea a la hora; algunos
  comentarios traen la hora exacta ("07:30 hs") y el script la usa.

Del sensor:
- **Horas sin datos** en el intervalo (cortes, reinicios): la métrica sale baja.
- **Deriva de la base** (0.53 → 0.50 en 3 días): por eso se resta una base móvil.
- **Picos sueltos enormes** (kurtosis 220, 263): un solo valor así pesa mucho
  en M2; vigilar si corresponden a algo real.

## 6. Preguntas pendientes para el pozo

1. Purga que cierra D: hora exacta y kg.
2. Qué pasó el 29/9 entre 15:40 y 16:30 y el 1/10 entre 05:47 y 07:00 (local):
   gas, choke, purga de otro pozo, maniobra.
3. ¿El BBS está aguas abajo del sensor y recibe todo el flujo del pozo 2?
   ¿Cuánta arena se le escapa?
4. ¿La planilla está en hora local?

## 7. Próximos pasos

1. Al llegar la purga que cierra D: completar la fila y comparar con la
   predicción de la sección 4 (sin tocar las definiciones).
2. Agregar una fila por cada purga nueva (`metricas_purgas.py` las lee solas
   de la planilla; hacen falta los CSV del sensor del intervalo).
3. Con ~10-15 intervalos: ajustar kg = a·M para cada métrica, ver la
   dispersión, y probar si caudal / control / orificio explican el resto.

## 8. Umbral de M1 bajado a 3.5 (2026-10-02)

Decisión del usuario (2/10), tomada **después** de ver el resultado de D, así que
3.5 no tiene el valor de prueba que tuvo 3.8 en la sec.4. Valor por defecto
nuevo en `metricas_purgas.py` (`KURT_UMBRAL = 3.5`; `--kurt 3.8` reproduce lo anterior).

Comparación con los 4 intervalos completos (factor kg = a·M ajustado por el
origen; LOO = cada intervalo predicho con el factor de los otros 3):

| Umbral | M1: r | M1: error medio LOO | M2: error medio LOO |
|---|---|---|---|
| 3.8 | 0.70 | 3.7 kg | 11.0 kg |
| 3.5 | 0.72 | 3.5 kg | 11.1 kg |

Lectura: con estos datos 3.5 y 3.8 dan prácticamente lo mismo (la diferencia
está muy por debajo de lo que 4 puntos pueden distinguir). Lo que cambia es el
piso: de noche tranquila hay ~4 ventanas/h > 3.5 contra ~2/h > 3.8, así que
M1(3.5) suma ~50 ventanas de fondo en un intervalo de 12 h sin arena. Si se
ajusta kg = a·M1 + b, el término b absorbe ese piso.

Chequeo de confusión (2/10): con Starlink encendido hay más ventanas > 3.5
por hora (mediana 11/h contra 6/h apagado), pero en las 5 conmutaciones del
relé con datos (hora antes contra hora después) no hay escalón (ej. 2/10
11:55 UTC: 4 contra 3). La diferencia es por la hora del día (operación),
no por el Starlink. Además el área y la kurtosis se calculan en la FPGA
con la señal completa: las pérdidas del streaming (que sí dependen del
Starlink, ver memoria sec.195) no las afectan.

### 8.1 Predicción para el intervalo abierto E (registrada 2026-10-02 ~13 UTC)

E arranca en la purga del 1/10 20:00 local. Hasta el 2/10 09:45 local
(13.8 h): M1(3.5) = 56, M1(3.8) = 29, M2(3.5) = 1.49, M3 = 212. Es el
intervalo más tranquilo de todo el registro.

Factores de los 4 completos: M1(3.5) 0.041 kg/ventana, M1(3.8) 0.075.
- Hasta ahora: ~2.3 kg (3.5) y ~2.2 kg (3.8).
- Si sigue igual de tranquilo hasta una purga a las 20:00 local del 2/10 (24 h):
  **~4 kg** con los dos umbrales.
- Si la purga da ≥ 10 kg sin que aparezca una ráfaga de picos antes, M1 tampoco
  sirve y hay que buscar otra cosa.

## 9. Estudio completo con todos los datos (2026-10-02)

Script: `analisis/estudio_arena/estudio_completo.py` (32 métricas por intervalo,
modelos de un parámetro kg = a·x, evaluación leave-one-out, prueba de azar por
permutación). Umbral de captura de la placa de campo: sin cambios (5.0), por
decisión del usuario; todo esto es post-procesamiento.

### 9.1 Cuántos datos hay realmente

Los CSV continuos del sensor arrancan el 29/9 09:00 local. Entre purgas eso da
**4 intervalos completos** (15, 3, 12, 14 kg) + 1 parcial (8 kg, 5 h de 12) +
el abierto. Las purgas anteriores (90 en la planilla, desde el 18/8) no tienen
CSV del sensor. Aparte, los paquetes livianos del 21-22/9 (cadena de software,
no FPGA) cubren 2 intervalos más pero muestreados: 69 min de 23 h (500 kg) y
29 min de 5.5 h (4 kg).

### 9.2 Resultado con los 4 completos

| Modelo | Error medio LOO |
|---|---|
| kg = promedio de los otros (sin nada) | 5.3 kg |
| kg ∝ horas del intervalo (sin sensor) | 4.2 kg |
| **kg ∝ N ventanas con kurtosis > 3.5** | **2.9 kg** |
| kg ∝ N ventanas > 3.8 (la fijada antes) | 3.0 kg |
| mejor de las 32 (ráfagas con k > 6) | 2.7 kg |
| métricas de área (M2, M3, excesos) | 7-21 kg |

- La familia "cantidad de picos" (N ventanas sobre 3.5-4.5) le gana a la
  referencia sin sensor; las de área pierden contra todo: confirma la sec.4.1.
- **No es prueba todavía.** Prueba exacta (24 permutaciones de 4 kg):
  N > 3.5 queda 2/24 (p ≈ 0.08), N > 3.8 3/24. Elegir "la mejor de 32" no vale:
  con kg al azar la mejor de 32 iguala 2.7 kg el 31 % de las veces. Por eso se
  queda N > 3.5 (decidida antes del barrido) y no la ganadora del barrido.

### 9.3 Validación externa: el intervalo de 500 kg (21/9)

Factor de los 4 completos: **0.039 kg por ventana > 3.5** (≈ 26 ventanas por kg).
Aplicado a los paquetes del 21-22/9 (tasa en las ventanas grabadas × horas del
intervalo):

| Intervalo | Real | N > 3.5 | N > 3.8 | N > 8 | kg ∝ horas |
|---|---|---|---|---|---|
| 20/9 21:00 → 21/9 20:00 | **500 kg** | **~220 kg** | ~350 kg | ~3700 kg | 19 kg |
| 22/9 07:30 → 13:00 | **4 kg** | 0 kg | 0 kg | 0 kg | 5 kg |

Es el resultado más fuerte del estudio: un factor ajustado con 3-15 kg acierta
el orden de magnitud de una purga de 500 kg (se queda corto ~2.3×), y la
referencia sin sensor falla 25×. Cuidados: cobertura del 5 % (si las capturas
se hicieron más cuando había arena, la extrapolación exagera; si no, subestima),
y la kurtosis viene del filtro de software, no de la FPGA (validadas iguales
en sec.182 de la memoria, no en este dato). N > 8 sobreestima 7×: los picos
extremos no escalan lineal.

### 9.4 Algoritmo propuesto (versión 1)

**kg desde la última purga ≈ 0.039 × (ventanas de 50 ms con kurtosis > 3.5)**,
con incertidumbre ~±3 kg en el rango 3-15 kg y posiblemente subestimando
~2× en eventos grandes. Se puede llevar a Losant como acumulado que se reinicia
en cada purga (hoy `ventanas_umbral_1min` usa el umbral 5.0 de la captura).
No aplicar todavía: primero que acierte la purga de E (sec.8.1, ~4 kg) y las
siguientes.

### 9.5 Qué mejora el estudio de verdad

1. **Más intervalos**: cada purga suma un punto; con ~10-15 se puede probar
   kg = a·N + b y un término no lineal para eventos grandes.
2. **Purgas más seguidas** (cada 2-4 h algunos días): más puntos y menos
   incertidumbre de cuándo salió la arena. Es la palanca más grande y depende
   del pozo.
3. Hora exacta de cada purga (algunas vienen redondeadas).
4. ¿Las capturas del 21/9 se hicieron a horario fijo o cuando se veía arena?
   (define si 220 kg es piso o techo).

## 10. Indicador cualitativo poca / media / mucha (2026-10-02, versión 1)

Pedido del usuario: por ahora no un valor en kg sino un nivel. Base: solo los
datos continuos desde el 29/9 (72 h). Script: `analisis/estudio_arena/nivel_arena.py`.

**Regla (por hora):** ventanas de 50 ms con kurtosis > 3.5 en la hora:
- **poca** < 15 (≲ 0.6 kg/h equivalente)
- **media** 15-80
- **mucha** ≥ 80 (≳ 3 kg/h)

Los cortes son redondos, anclados al factor de la sec.9.4; coinciden con la
distribución de las 70 horas con dato (p75 = 20/h, p95 = 60/h, p99 = 179/h).

**Resultado 29/9 - 2/10:** 49 h poca, 18 media, 3 mucha (29/9 15 h y 16 h,
1/10 06 h). Por intervalo:

| Intervalo (local) | Real | Horas poca/media/mucha |
|---|---|---|
| 29/09 14 → 30/09 02 | 15 kg | 6 / 3 / **2** |
| 01/10 04 → 01/10 20 | 14 kg | 12 / 3 / **1** |
| 30/09 14 → 01/10 04 | 12 kg | 10 / 2 / 0  ← no lo ve |
| 30/09 02 → 30/09 14 | 3 kg | 8 / 4 / 0 |
| 29/09 02 → 29/09 14 (parcial) | 8 kg | 0 / 5 / 0 |

Lectura:
- Las horas "mucha" caen solo en los dos intervalos de más kg. El de 12 kg no se
  distingue del de 3 kg: o la arena salió de una forma que el sensor no ve, o
  esos kg son de antes (la planilla redondea la hora de purga).
- **Desde el 29/9 no hubo ningún intervalo de mucha arena** (máximo 15 kg en
  12 h). "Mucha" queda definida pero sin validar; la única referencia de
  mucha arena es el 21/9 (500 kg, ~240 ventanas/h, sería "mucha").
- [Suposición] Las horas "media" se juntan de día (08-16 local); puede ser
  arena o actividad del pad (maniobras, vehículos). Preguntar al pozo.

**Cómo se valida:** con cada purga nueva, que los intervalos con horas "mucha"
sean los de más kg y los "todo poca" los de menos. Primera prueba: el intervalo
abierto E (13 h poca + 1 media hasta 2/10 09:45) debería cerrar con pocos kg (~2-4).

## Registro

- 2026-10-01: inicio; planilla hasta 1/10 06:00 local; métricas y predicción
  de la sección 4 fijadas antes del reporte del mediodía.
- 2026-10-02: planilla hasta 2/10 06:00 local; D cerrado (14 kg, ganó M1,
  sec.4.1); umbral de M1 bajado a 3.5 por decisión del usuario (sec.8);
  predicción de E registrada (sec.8.1). CSV del sensor hasta 2/10 09:45
  local en `datos_campo/placa_campo/csv_sd_1oct_2oct/` (md5 OK contra la SD).
- 2026-10-02: estudio completo (sec.9): N ventanas k > 3.5 mejor que la referencia
  sin sensor (2.9 vs 4.2 kg LOO, p ≈ 0.08) y predice ~220 kg para la purga de
  500 kg del 21/9; algoritmo v1 = 0.039 kg/ventana.
- 2026-10-02: indicador cualitativo poca/media/mucha por hora (sec.10), solo con
  datos continuos desde el 29/9.
