# Cómo funciona el script y formato de datos

Referencia interna — para entender resultados raros, debuggear, o estimar espacio/tiempos.
Para el uso día a día ver `operacion_campo.md`.

## Por qué la SD como buffer intermedio

El streaming-server de Red Pitaya genera datos a **7.8 MB/s por canal** (decimación 32,
2 bytes por muestra) — con `--canales 2` el ancho de banda combinado se duplica.
Un USB 2.0 típico escribe a 4–5 MB/s — más lento que la tasa de datos. Si el servidor escribiera
directo al USB, el buffer interno se llenaría y los datos se perderían o el servidor pararía antes
de tiempo. La SD interna de la placa escribe a **15 MB/s**, suficiente para 1 canal a
cualquier decimación válida, y para 2 canales a partir de dec=64 (ver más abajo).

## Flujo por chunk

```
     PLACA                                      DESTINO
  ┌──────────────────────────────┐
  │  1. startStreaming()         │
  │     servidor escribe a SD   │  ← 15 MB/s, ~60s para 1 min de señal
  │     Python espera callback  │
  │  2. callback stoppedSDDone  │
  │     renombra archivo en SD  │
  └──────────────────────────────┘
           │
           ├─── thread de fondo ──────────────────► USB: shutil.move()  4–5 MB/s
           │                                         RED: scp            6–15 MB/s
           │
  ┌──────────────────────────────┐
  │  3. startStreaming() chunk 2 │  ← arranca inmediatamente, no espera el move
  │     ...                     │
  └──────────────────────────────┘
```

El move del chunk anterior y la captura del siguiente corren **en paralelo**. Si el move no
terminó cuando la captura nueva termina, el script espera (`[esperando move anterior...]`)
antes de iniciar el siguiente move — nunca hay más de un archivo en tránsito a la vez, y
nunca se acumulan archivos en la SD.

## Eficiencia real

La **eficiencia** que imprime el script es `tiempo_de_señal / tiempo_de_reloj`. Con SD como
destino de captura se obtiene consistentemente 97–99%, en mono y en dual. El tiempo de move
al USB o red no cuenta en esa métrica — ocurre fuera del loop de captura.

**Para minimizar pérdida de muestras** (columna `perd`/`perd1`/`perd2` en `revisar.py`): usar
`--duracion_chunk` lo más grande que el caso de uso permita. La pérdida escala con la cantidad
de transiciones de chunk dentro de una sesión, no solo con el tiempo total capturado — menos
chunks para la misma duración total captura con menos pérdida.

**Tope acordado: 2 min/chunk en campo.** Un chunk más largo pierde menos muestras, pero un
crash a mitad de chunk pierde el chunk entero (ver `guardar_contexto_crash` en
`campo_common.py`) — con datos de arena real irremplazables, ese riesgo pesa más que la
mejora marginal en `perd`. No subir `--duracion_chunk` por encima de 2 min sin repetir esa
cuenta.

---

## Estructura de archivos

```
Sand Monitoring/
  scripts_campo/
    capturar_stream.py      ← RECOMENDADO para campo (98% eficiencia, --canales 1|2)
    probar_dual_stream.py   ← prueba de banco de solo lectura, para reconfirmar formato/canales
    repro_in1_file_bug.py   ← script de reproducción para el issue de Red Pitaya (referencia, ya resuelto)
    PLAN_CAMPO.md           ← índice de la guía operativa
    plan_campo/             ← guías detalladas (setup, operación, este documento, troubleshooting)
  scripts_campo_comun/
    campo_common.py         ← funciones compartidas (arranque servidor, logs, USB/red)
    relanzar_captura.sh     ← supervisor para sesiones largas desatendidas
    automount_usb.sh        ← monta/desmonta /mnt/usb automaticamente (invocado por systemd, no a mano)
    udev-automount/         ← reglas udev + unidad systemd que dispara automount_usb.sh
  analisis/
    revisar.py              ← revision rapida en PC (lee .bin, mono o dual)
```

---

## Logs (errores y eventos) — en la placa, no en el USB

**Dónde están:** `/root/logs_campo/` en la Red Pitaya. No están en el USB/SSD de campo a
propósito — así sobreviven si el storage externo se desconecta a mitad de sesión.

```
/root/logs_campo/
  log_campo_reposo_20260702_183536.txt        ← una por sesión, mono o dual (mismo prefijo "campo")
  crash_campo_reposo_20260702_183536_0007.txt ← solo aparece si la sesion crasheo, uno por crash
```

**Qué tiene el `log_*.txt`:** NO es todo lo que se ve en pantalla — solo errores, warnings
(los que arrancan con `[!]`) y los eventos que el script marca a propósito (inicio y fin de
sesión, chunks con eficiencia baja). Una sesión larga sin problemas genera un archivo de
apenas un par de líneas.

**Cómo leerlo:** es texto plano, con cualquier editor o:

```bash
ssh root@<IP_PLACA> "cat /root/logs_campo/log_campo_reposo_20260702_183536.txt"
```

**Qué tiene el `crash_*.txt`:** si la sesión se cayó con una excepción, además del log
normal queda este archivo aparte con el traceback completo, el estado de
`streaming-server` (`pgrep`), las últimas líneas de `dmesg` y el espacio libre en la SD —
todo lo que antes había que ir a buscar a mano por SSH.

**Límite conocido:** esto solo funciona si Python ve la excepción. Un crash de la
librería C++ (`rpsa_client`, ej. `std::bad_alloc` no atrapado) dispara
`std::terminate()` → `abort()` → el proceso muere por señal antes de que el
`try/except` de Python se entere — no genera `crash_*.txt`, solo una línea suelta
`terminate called after throwing an instance of '...'` en el `log_*.txt`. Para esos
casos ver "Core dumps" abajo.

---

## Core dumps (debug de crashes C++ sin traceback)

Para crashes que no dejan traceback de Python (`std::bad_alloc`, `std::length_error`,
etc. no atrapados en la librería `rpsa_client`), la placa está configurada para generar
un core dump del proceso `python3` en el momento del abort.

**Ya configurado (no repetir salvo reflasheo):**
- `kernel.core_pattern` → `/root/logs_campo/core_%e_%p_%t` (persiste via
  `/etc/sysctl.d/99-core-campo.conf`, sobrevive reinicios).
- `relanzar_captura.sh` corre con `ulimit -c unlimited` — se hereda por el `python3`
  que lanza. **Corriendo `capturar_stream.py` directo (sin el supervisor) no queda
  core dump** salvo que se ponga `ulimit -c unlimited` a mano antes.

**Si aparece un core tras un crash:**

```bash
ssh root@<IP_PLACA> "ls -la /root/logs_campo/core_*"
```

Analizarlo con gdb (armv7l, gdb ya instalado en la placa):

```bash
ssh root@<IP_PLACA>
gdb python3 /root/logs_campo/core_python3_<pid>_<timestamp>
(gdb) bt full        # stack trace completo, con esto se identifica donde/por que
                      # la libreria pide la allocation que falla
```

**Espacio:** un core de un proceso con buffers de streaming cargados puede pesar
cientos de MB — revisar espacio libre en `/` (no en el USB de campo, los cores no
van ahí a propósito, mismo criterio que los logs).

---

## Espacio en disco y velocidades

### Tamaño de archivos

| Decimación | fs (1 canal) | Chunk 1 min (1 canal) | Chunk 1 min (2 canales) |
|---|---|---|---|
| 32 | 3.906 MHz | ~469 MB | ~938 MB (no recomendado, pierde muestras) |
| 64 | 1.953 MHz | ~235 MB | ~469 MB (recomendado para dual) |

Con dec=64 dual, el combinado de los 2 canales pesa lo mismo que 1 canal a dec=32 en mono.

### Capacidad de storage (1 canal, dec=32 — para dual a dec=64 son los mismos numeros)

| Storage | Capacidad útil | Chunks de 1 min |
|---|---|---|
| Pendrive 8 GB | ~7.5 GB | ~16 chunks (~16 min) |
| HDD 500 GB | ~500 GB | ~1.065 chunks (~17.7 hs) |
| HDD 1 TB | ~1 TB | ~2.130 chunks (~35.5 hs) |

### Velocidades de transferencia medidas (dec=32 1 canal, chunk=1min)

| Destino | Velocidad medida | Tiempo transfer / chunk | Espera entre chunks |
|---|---|---|---|
| SD interna (captura) | 15 MB/s | — | — |
| USB 2.0 pendrive | 4–5 MB/s | ~100s | ~40s |
| RED link directo (concurrente) | 5.6 MB/s | ~83s | ~23s |
| RED link directo (sin competencia) | 10.4 MB/s | ~45s | 0s |
| RED via gateway (100 Mbit) | 6–15 MB/s | 30–80s | 0–20s |

### Límite de sesión por acumulación en SD (modo RED link directo)

Con link directo la transferencia (83s) es más lenta que la captura (60s), por lo que
la SD acumula chunks no transferidos a un ritmo de ~130 MB por chunk capturado.

| SD libre | Límite de sesión |
|---|---|
| 22 GB | ~173 chunks ≈ **2.9 horas** |
| 16 GB | ~126 chunks ≈ **2.1 horas** |

**Para sesiones más largas:** usar modo gateway (si la red da >7.8 MB/s sostenido, no acumula)
o hacer pausas entre bloques para que la SD drene.

**Fórmula:** `limite_min = SD_libre_MB / 130 * 1`  (chunks de 1 min, dec=32, 1 canal)
