# Compresión de archivos .bin — investigación (2026-07-03)

Referencia para decidir si conviene comprimir los `.bin` crudos antes de guardarlos o transferirlos, y en qué momento del flujo conviene hacerlo.

**Contexto:** hoy los `.bin` se guardan crudos en la memoria externa de campo (`/mnt/usb`). A futuro se van a dejar corridas guardadas ahí y en algún momento conectarse remotamente para ir trayendo los paquetes. La pregunta no es "¿ahorra espacio?" sino "¿conviene comprimir antes de mandar por esa conexión futura, y en qué punto del proceso?".

---

## Resultado empírico: sí comprime, más de lo esperado

Antes de medir, la expectativa era que la señal cruda (ruido de banda 100-450kHz, cerca del Nyquist) comprimiera mal con herramientas genéricas — es básicamente ruido de alta entropía. La medición en archivos reales lo contradijo: comprime bastante bien, entre 30% y 58% según condición y herramienta.

**Prueba en PC (x86), archivos de 234 MB:**

| Compresor | Reposo | Con arena | Tiempo (234MB) |
|---|---|---|---|
| gzip -1 | 48.4% | 35.3% | ~2-3s |
| zstd -3 | 48.6% | 36.2% | ~0.4s |
| zstd -19 | 55.5% | 45.4% | ~63-84s |
| xz -1 | 54.3% | 44.7% | ~4-5s |
| bzip2 -9 | 58.1% | 50.7% | ~11s |

**Por qué reposo comprime mejor que con_arena:** reposo tiene más patrón repetido (el EMI periódico de ~16V ya caracterizado en pruebas de campo). Con arena tiene más energía real de banda ancha (impactos), que es información genuina y por eso más difícil de comprimir. Esperar esta diferencia en cualquier prueba futura — no es un error de medición.

---

## El dato que cambia la decisión: el ARM de la placa es muy débil

La prueba en PC no sirve para decidir nada por sí sola, porque la compresión (si se hace en campo) corre en la Red Pitaya, no en una PC de escritorio. Repetir la misma prueba en el ARM de la placa (2 núcleos, Zynq) dio otro panorama:

| Compresor | Reposo (469MB) | Con arena (234MB) |
|---|---|---|
| gzip -1 | 46.7% / 166s | — |
| gzip -6 | 47.0% / **911s (15 min)** | — |
| zstd -1 | 41.6% / 61s | 30.6% / 28s |
| zstd -3 | 47.6% / 159s | 36.1% / 89s |
| zstd -9 | 50.6% / 523s (8.7 min) | 41.2% / 211s |

`zstd -3`, que en la PC tardaba 0.4s para 234MB, tarda **89s** en el ARM — unas 220 veces más lento. `xz` y `bzip2 -9` se descartaron de plano en la placa por lentitud extrema (`gzip -6` solo, ya dio 15 minutos para un chunk de 1 minuto de captura).

**Conclusión de esta tabla:** en la placa, `zstd` es la única familia viable (mejor balance velocidad/ratio de las probadas). Dentro de `zstd`, el nivel `-9` no vale la pena ahí — gana apenas 3-9 puntos porcentuales más que `-1` a cambio de 3.5-7 veces más tiempo.

---

## Por qué no conviene comprimir durante la captura

Un chunk de captura dura 60s (duración configurable, pero ese es el valor típico de campo). `zstd -1`, el nivel más rápido, tarda **61s** en comprimir un chunk de ese tamaño en la placa — prácticamente el mismo tiempo que dura la captura del chunk siguiente.

Esto significa que no hay margen: si se intentara comprimir cada chunk en tiempo real, apenas se sume cualquier otra carga (el thread que ya existe hoy para copiar a USB, por ejemplo) el proceso de compresión se atrasa respecto a la captura y el atraso se acumula sin límite — nunca vuelve a ponerse al día. Es la misma razón por la que en su momento se descartó calcular FFT en tiempo real en la placa (ver `informe_deteccion_arena.md` / notas de esa decisión): el ARM está justo al límite con la captura sola, no hay CPU de sobra para sumarle trabajo en paralelo sin arriesgar la eficiencia de captura (~98%) que costó conseguir.

---

## Cuándo sí conviene comprimir

El espacio en el disco de campo hoy no es el problema: `/mnt/usb` tiene 916GB, de los cuales varios días de pruebas solo gastaron 34GB (836GB libres). El motivo real para comprimir no es "no se llena el disco", es achicar lo que hay que transferir el día que alguien se conecta remotamente a buscar los paquetes.

Esa conexión remota es un evento puntual, no continuo — no compite con la captura en tiempo real. Ahí sí hay margen para pagar 30-90s de compresión por archivo sin que le cueste nada al sistema de captura.

| Momento | ¿Conviene comprimir? | Por qué |
|---|---|---|
| Durante la captura (en paralelo, cada chunk) | **No** | Sin margen de CPU en el ARM — genera atraso acumulativo |
| Guardado en el USB de campo, sin necesidad de transferir | No es necesario hoy | Sobra espacio (836GB libres) |
| Al momento de conectarse remotamente para traer archivos | **Sí** | Evento puntual, sin presión de tiempo real; el beneficio (30-42% menos para mandar) compensa los 30-90s de espera si el enlace remoto es lento |

---

## Recomendación

Usar `zstd -1` (no niveles más altos) aplicado únicamente en el momento de la transferencia remota — nunca en la ruta de captura. Con `zstd --rm` se puede comprimir y borrar el original en un solo comando, solo si la compresión terminó bien.

Ejemplo de ganancia esperada por archivo de ~450MB: ~30-42% menos para transferir, a cambio de ~30-60s de espera en la placa. Vale la pena si la conexión remota es lenta (celular/satelital); el margen es menor si la conexión es rápida.

**Pendiente si se decide implementar:** definir el punto exacto del flujo de "conectarse y traer paquetes" donde se dispara la compresión (antes de mandar cada archivo, bajo demanda), sin tocar `capturar_campo_stream.py`/`capturar_dual_stream.py`.
