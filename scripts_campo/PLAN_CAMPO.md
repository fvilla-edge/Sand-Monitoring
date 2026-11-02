# Guía operativa de campo — Sand Monitoring

Desde fines de septiembre de 2026 la placa corre en **modo evento**: mide sola las 24 h
desde que arranca (`modo-evento.service`), guarda área y kurtosis de todas las ventanas
de 50 ms en un CSV por hora y la señal cruda solo de las ventanas con kurtosis ≥ 3.4.
Los CSV suben a GCS en cada ventana de Starlink y se ven en SandVision. Cómo funciona:
`../docs/modo_evento.md`. Uso día a día: `../GUIA_USO_BASICO.md`.

El **modo clásico** (capturas `.bin` continuas a pedido con `capturar_stream.py`) sigue
disponible como vuelta atrás (`cambiar_modo.sh clasico`) y para pruebas de banco; sus
guías quedan abajo, marcadas.

---

## Guías detalladas

| Documento | Contenido | Cuándo leerlo |
|---|---|---|
| [`plan_campo/setup_placa.md`](plan_campo/setup_placa.md) | Setup base, una vez por placa: librería de streaming, `dummy0`, montaje automático del USB, autosuspend, journal, SSH, relé de Starlink, RTC, panel solar | Placa nueva o reflasheada (antes del primer paquete) |
| [`plan_campo/actualizar_placa_campo.md`](plan_campo/actualizar_placa_campo.md) | Historial de lo instalado en la placa de campo y procedimiento de actualización por paquete (sección 6) | Para instalar o actualizar el software/bitstream |
| [`plan_campo/troubleshooting.md`](plan_campo/troubleshooting.md) | Qué hacer si algo falla, por síntoma (modo evento primero, modo clásico después) | Cuando algo no anda |
| [`plan_campo/operacion_campo.md`](plan_campo/operacion_campo.md) | **Modo clásico:** captura a pedido con `capturar_stream.py`, parámetros, sesiones largas, archivos `.bin` | Solo con la placa en modo clásico |
| [`plan_campo/formato_y_funcionamiento.md`](plan_campo/formato_y_funcionamiento.md) | **Modo clásico:** buffer en SD, eficiencia, formato `.bin`. Vigente para todos: logs, core dumps, `config_campo.json` | Debug, o para entender una captura clásica |

---

## IPs según topología de red

La placa obtiene su IP del router o de la PC según cómo esté conectada:

| Topología | IP placa | IP PC (en esa interfaz) | Notas |
|---|---|---|---|
| Placa → gateway/router → PC | según DHCP del router | según DHCP del router | Red compartida |
| Placa → RJ45 directo → PC | `10.42.0.180` | `10.42.0.1` | Linux "connection sharing" (en la PC de la oficina: `nmcli con up directo-placa`) |
| Placa en el sitio → Starlink | IP pública del Starlink (cambia) | — | Solo accesible con Starlink prendida: modo permanente o durante una ventana |

> Con link directo (RJ45), Linux asigna automáticamente `10.42.0.1` al lado PC y
> da `10.42.0.180` a la placa por DHCP. No hay que configurar nada extra.

---

## Referencia de hardware

| Componente | Detalle |
|---|---|
| Sensor IN1 | Vallen VS150-RI (100–450 kHz, preamp 40 dB) |
| Sensor IN2 (solo dual) | Vallen VS150-RI, mismo modelo; hoy es un segundo sensor de medición, independiente o asociado al IN1 (`../docs/modo_evento.md` → "Mono y dual") |
| ADC | Red Pitaya STEMlab 125-14 (125 MHz, 14 bits, 2 canales sincrónicos) |
| Jumper | HV → rango ±20 V |
| Attenuator config | `A_1_20` (ambos canales en dual) |
| Storage campo | USB/HDD externo en `/mnt/usb`, vía hub USB alimentado |
