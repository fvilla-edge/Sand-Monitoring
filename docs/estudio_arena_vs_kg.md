# Estudio: área del sensor vs kg de arena (PAD-7, BPO-2072)

Objetivo final: poder decir "esta cantidad de área corresponde a X kg de arena".
Se avanza de a un paso, agregando un punto por cada purga.

Iniciado el 2026-10-01. Script: `analisis/estudio_arena/metricas_purgas.py`.

## 1. Qué es la verdad de campo

- Planilla del pozo (`Planilla de Ensayo PAD-7.xlsx - BPO-2072.csv`).
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
| M1 | picos, cantidad | ventanas con kurtosis > 3.8 |
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
| 01/10 04:00 | (abierto) | ? | — | 5.0 hasta 09:00 | 176 | 30.84 | 9582 | 3 | 492 |

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

## Registro

- 2026-10-01: inicio; planilla hasta 1/10 06:00 local; métricas y predicción
  de la sección 4 fijadas antes del reporte del mediodía.
