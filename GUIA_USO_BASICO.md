# Guía de uso básico — Sand Monitoring

Cómo funciona hoy (desde la instalación del 29/10/2026 en PAD-118): **la placa mide
sola, las 24 h, desde que se enciende.** No hay que lanzar capturas a mano. Lo que hace
el operador es encender, mirar que esté midiendo y, si hace falta, cambiar el modo o
bajar datos.

```
sensor(es) → Red Pitaya (modo evento, 24 h) → USB: CSV por hora + señal cruda de los eventos
                                            → cada 2 h (ventana Starlink): CSV a GCS → SandVision
                                            → cada minuto con conexión: resumen a Losant
```

Detalle técnico del modo evento: `docs/modo_evento.md`. Comandos y argumentos:
`COMANDOS.md`.

---

## 1. Encender

Conectar la alimentación (batería + panel solar en campo, fuente en banco) con el
disco USB conectado. Al arrancar, solo y sin intervención:

- `modo-evento` empieza a medir (espera ~90 s de uptime) en el modo de canales
  guardado (mono = IN1, o dual = IN1 + IN2).
- El control de Starlink aplica el modo guardado (ventana o permanente). En modo
  ventana, la placa abre una ventana al arrancar.
- Si no hay disco, mide igual pero guarda solo los CSV, en la SD
  (`/root/eventos_sd`), sin señal cruda. Cuando el disco vuelve, retoma en el USB solo.

## 2. Ver que esté midiendo

**Sin entrar a la placa** (lo normal):

- **SandVision** (`vista-sandvision.web.app`): el resumen público muestra arena y
  energía de los últimos días; `/completa` (editores) tiene las solapas Arena,
  Energía, Estado y Planilla. Los datos llegan con cada ventana, o sea con hasta
  ~2 h de atraso en modo ventana.
- **Losant**, Device de campo: `me_activo = true`, `me_ventanas_1min` ~1200,
  `me_canales`, `sl_modo`. Solo se actualiza mientras hay conexión.

**Por SSH** (durante una ventana, en modo permanente, o en la empresa por cable):

```bash
ssh root@<IP_PLACA> 'bash -s' < scripts_campo_comun/estado_placa.sh   # desde la PC, solo lectura
```

Muestra modo, servicios, última línea `ESTADO` de la medición, salud, relé y
resultado de la última actualización. No escribe nada ni toca el relé.
IPs según cómo esté conectada la placa: `scripts_campo/PLAN_CAMPO.md` → "IPs según
topología de red" (en la empresa por cable directo: `10.42.0.180`, perfil
`directo-placa` de NetworkManager).

## 3. Starlink: ventana o permanente

| Modo | Qué hace |
|---|---|
| **ventana** (defecto) | Prende cada 2 h a los :05 (horas pares, hora Argentina) y al arrancar; espera internet hasta 15 min, sube los CSV a GCS, espera 2 min por Losant y apaga. Suele durar 3-5 min (algunas, hasta ~12). |
| **permanente** | Prendida las 24 h. Para trabajar remoto un rato largo o antes de una actualización. |

**Cambiarlo:** desde SandVision (`/completa` → Estado → Modos) o desde Losant con el
tag `modo_starlink` del Device. En modo ventana el cambio llega recién en la próxima
ventana (hasta 2 h). Otras formas (SSH, script de la PC): `COMANDOS.md` → "Modo de
operación".

**A mano por SSH**, sin cambiar el modo: `prender-starlink` / `apagar-starlink`
(entra en modo manual, se limpia solo) y `auto-starlink` para volver al control
automático. `apagar-starlink` corta la sesión si estás entrando por ese mismo Starlink:
es lo esperado. Desde Losant existe solo el apagado (comando `starlink`,
`{"accion": "off"}`).

## 4. Mono o dual

| Modo | Qué mide |
|---|---|
| Mono | Solo IN1, dec 32 |
| Dual independiente | IN1 + IN2, dec 64; cada sensor graba su cruda por su propia kurtosis |
| Dual asociado | IN1 + IN2, dec 64; el IN2 graba su cruda solo cuando graba el IN1 |

**Cambiarlo:** desde SandVision (Estado → Modos) o con los tags `canales` (`1` | `2`)
e `in2_modo` (`independiente` | `asociado`) del Device en Losant. **No mandar el
comando a mano en modo ventana**: Losant no guarda comandos y uno enviado con la placa
desconectada se pierde sin error. Si el modo nuevo no llega a medir en 4 min, la placa
vuelve sola al anterior; el resultado queda en `me_cambio`. Detalle y comando por SSH:
`COMANDOS.md` → "Mono / dual y modo del IN2".

No editar `config_campo.json` a mano para esto.

## 5. Los datos

**Qué se guarda (en el USB, `/mnt/usb/eventos/`):**

- `ventanas_AAAAMMDD_HH.csv`: área y kurtosis de **todas** las ventanas de 50 ms,
  uno por hora **UTC** (= hora Argentina + 3), ~3 MB/h por canal.
- `evento_*.bin` + `.json`: señal cruda de cada ventana con kurtosis ≥ 3.4 (±10 ms).
- En dual, lo del IN2 va igual en `/mnt/usb/eventos/in2/`.

Los CSV no se borran del USB después de subirlos. Si queda poco lugar, la placa pausa
la señal cruda y sigue con los CSV (`me_cruda_pausada` en Losant).

**CSV (lo de todos los días):** suben solos a GCS en cada ventana. Se miran en
SandVision; no hace falta bajarlos de la placa. Para analizarlos en la PC (paquete
liviano y visor): `README.md` → "Analizar las mediciones del modo evento".

**Señal cruda de los eventos:** no sube a GCS (pesa demasiado para Starlink). Se trae
a mano:

- Con acceso físico: desconectar el disco (el automontaje lo desmonta solo, y la
  captura sigue en la SD solo con CSV hasta que vuelva) y copiar en la PC.
- Remoto, con Starlink prendida (permanente o durante una ventana), solo lo que haga
  falta, no la carpeta entera (puede tener decenas de miles de archivos):

  ```bash
  ssh root@<IP_PLACA> 'ls /mnt/usb/eventos/ | grep "^evento_20261029_15"'
  mkdir -p datos_campo/placa_campo/eventos
  scp 'root@<IP_PLACA>:/mnt/usb/eventos/evento_20261029_15*' datos_campo/placa_campo/eventos/
  ```

Reconstruir un tramo de señal en la PC a partir de eventos + CSV:

```bash
.venv/bin/python analisis/placa/reconstruir_senal.py CARPETA --desde 120 --duracion-s 10 --png
```

Cómo leer área/kurtosis (reposo, pico aislado, pase de arena): `README.md`, al final
de "Analizar las mediciones del modo evento".

## 6. Pausar la medición sin tocar lo demás

```bash
systemctl stop modo-evento      # para la captura (Starlink, Losant y energía siguen)
systemctl start modo-evento     # la retoma
systemctl is-active modo-evento
```

`stop` no la deshabilita: al reiniciar la placa vuelve a medir.

## 7. Apagar la placa

Apagado prolijo por SSH antes de cortar la alimentación, si se puede:

```bash
shutdown -h now
```

Un corte de energía sin apagado no rompe nada: al volver la placa retoma la medición
y recorta la última línea del CSV que haya quedado a medias.

---

## Otros casos

| Caso | Qué hacer |
|---|---|
| **Actualizar el software o el bitstream** | Por paquete, con la placa en permanente: `scripts_campo/plan_campo/actualizar_placa_campo.md` → sección 6. Vuelve sola si algo falla. |
| **Captura clásica a pedido** (`.bin` continuos, como antes del modo evento) | `bash /root/scripts_campo/cambiar_modo.sh clasico` deshabilita el modo evento; después `capturar_stream.py` como en `scripts_campo/plan_campo/operacion_campo.md`. Volver: `cambiar_modo.sh evento`. Mientras está en clásico **no se registra nada** salvo lo que se capture a mano. |
| **Dejar el relé quieto en una prueba** | `prender-starlink`/`apagar-starlink` o modo permanente. Desactivar los timers (`COMANDOS.md` → "Activar/desactivar la programación automática") solo si además no querés que la placa reevalúe nada. |
| **Panel solar / batería** | Llegan a Losant (`panel-solar-informe`) y a SandVision → Energía. Detalle: `panel_solar_ble/README.md`. |

---

## Referencias

- Todos los comandos: `COMANDOS.md`
- Modo evento (formatos, supervisor, mono/dual, qué llega a Losant): `docs/modo_evento.md`
- Modos de Starlink: `docs/plan_modos_starlink.md`; arquitectura del relé: `starlink_remoto/HISTORIAL_STARLINK.md`
- Actualizaciones de la placa de campo: `scripts_campo/plan_campo/actualizar_placa_campo.md`
- Después de tocar un archivo en la placa, qué reiniciar: `DESPLIEGUE.md`
