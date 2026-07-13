# Guía operativa de campo — Sand Monitoring

El script recomendado es **`capturar_stream.py`**, con `--canales 1` (mono, default)
o `--canales 2` (dual — sensor de referencia además del sensor de medición, ver
`plan_campo/operacion_campo.md` → "Sensor de referencia").

Captura a ~98% de eficiencia escribiendo primero a la SD interna de la placa (15 MB/s,
suficiente para los 7.8 MB/s de datos a 1 canal) y luego mueve cada chunk al destino elegido en
un thread de fondo mientras ya empieza el siguiente chunk.

**Tres modos de operación (mono y dual):**

| Modo | Topología de red | Velocidad típica | Límite de sesión |
|---|---|---|---|
| `usb` | Sin PC | 4–5 MB/s | Storage del USB |
| `red` via gateway | Placa y PC en la misma red (router) | 6–15+ MB/s | Sin límite en SD |
| `red` via link directo | RJ45 placa ↔ PC directamente | 5.6 MB/s concurrente | ~2.9 horas (ver `plan_campo/formato_y_funcionamiento.md`, 1 canal) |

---

## Guías detalladas

| Documento | Contenido | Cuándo leerlo |
|---|---|---|
| [`plan_campo/setup_placa.md`](plan_campo/setup_placa.md) | Setup único por placa: copiar scripts, librería de streaming, montaje automático de USB, autosuspend, modo red | Antes de la primera salida a campo con una placa, o después de reflashearla |
| [`plan_campo/operacion_campo.md`](plan_campo/operacion_campo.md) | Sensor de referencia (dual), conectar, verificar USB, ejecutar captura, parámetros, ejemplos, sesiones largas/relanzado, archivos generados, revisar en la PC | Cada vez que se sale a capturar |
| [`plan_campo/formato_y_funcionamiento.md`](plan_campo/formato_y_funcionamiento.md) | Cómo funciona el script por dentro (buffer SD, eficiencia), estructura del repo, formato `.bin`, logs, core dumps, espacio en disco y velocidades | Para entender resultados raros, estimar espacio/tiempo, o debuggear |
| [`plan_campo/troubleshooting.md`](plan_campo/troubleshooting.md) | Qué hacer si algo falla, organizado por síntoma | Cuando algo no anda |

---

## IPs según topología de red

La placa obtiene su IP del router o de la PC según cómo esté conectada:

| Topología | IP placa | IP PC (en esa interfaz) | Notas |
|---|---|---|---|
| Placa → gateway/router → PC | según DHCP del router | según DHCP del router | Red compartida |
| Placa → RJ45 directo → PC | `10.42.0.180` | `10.42.0.1` | Linux "connection sharing" |

> Con link directo (RJ45), Linux asigna automáticamente `10.42.0.1` al lado PC y
> da `10.42.0.180` a la placa por DHCP. No hay que configurar nada extra.

---

## Referencia de hardware

| Componente | Detalle |
|---|---|
| Sensor (medición, IN1) | Vallen VS150-RI (100–450 kHz, preamp 40 dB) |
| Sensor (referencia, IN2 — solo dual) | Vallen VS150-RI, mismo modelo |
| ADC | Red Pitaya STEMlab 125-14 (125 MHz, 14 bits, 2 canales sincrónicos) |
| Jumper | HV → rango ±20 V |
| Attenuator config | `A_1_20` (ambos canales en dual) |
| Storage campo | USB/HDD externo en `/mnt/usb`, vía hub USB alimentado |
