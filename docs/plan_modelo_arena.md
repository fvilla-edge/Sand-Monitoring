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
4. **Toda decisión va a la bitácora (sec.8)** con fecha y por qué, sobre todo
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
| Ruido por intervalo | 3 kg | ~ error medio de la sec.9 |
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
6. Anotar en la bitácora (sec.8) una línea por purga nueva: real, predicho,
   acierto, y cualquier cosa rara (horas sin dato, comentario del pozo).
7. Commit del registro + la bitácora.

## 6. Etapas

| Etapa | Cuándo | Qué | Estado |
|---|---|---|---|
| A | ya | Factor que aprende con cada purga (bayesiano) | **hecho en v1** |
| B | ya | Aporte por hora con 2 ingredientes (picos + fondo) | **hecho en v1** |
| C | cuando se decida | Agrupar picos en tipos (impactos sueltos, ráfagas, lomas) sin etiquetas, para separar arena de otras perturbaciones del pad (sospecha: las horas "media" se juntan de 08 a 16 local) | pendiente |
| D | ~15 purgas | Probar un 3er ingrediente (horas en control de separador, caudal, presión de línea) solo si mejora las anticipadas | pendiente |
| E | ~30-50 purgas (~2-4 semanas) | ML con varias variables (regresión regularizada, gradient boosting), validado por tiempo (entrenar con el pasado, predecir el futuro) | pendiente |
| F | cuando acierte | Llevar el nivel a Losant: "arena desde la última purga: poca/media/mucha" | pendiente |
| G | a futuro | Más variables por ventana desde la FPGA (pico, factor de cresta, energía por banda): cambio de firmware y CSV | idea |

## 7. Preguntas abiertas para el pozo

- Hora exacta de cada purga (algunas vienen redondeadas a la hora).
- Qué pasa en el pad de día (08-16 local): maniobras, vehículos, otros pozos.
- Qué pasó el 1/10 06:00 local (ráfaga de 254 picos en una hora).
- El intervalo de 12 kg (30/9 14:00 → 1/10 04:00) se ve tranquilo en el sensor: ¿algo distinto ese turno?

## 8. Bitácora

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
