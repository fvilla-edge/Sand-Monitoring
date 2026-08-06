# Panel solar por BLE (Victron SmartSolar) en la Red Pitaya

Lee en vivo los datos del cargador solar **Victron SmartSolar Charger MPPT
75/15 rev2** (voltaje/corriente de batería, potencia solar, estado de
carga, etc.) directamente en la Red Pitaya, sin que la placa necesite
soporte de Bluetooth.

## Por qué existe esto

La Red Pitaya (`rp-f0fbda`) **no tiene soporte de Bluetooth en el
kernel** (sin `CONFIG_BT`, sin módulo `btusb`, ni con un dongle BLE USB
enchufado — se probó y no hay forma de habilitarlo sin recompilar el
kernel completo con el toolchain de Red Pitaya). El SmartSolar transmite
sus datos como "Instant Readout": un advertisement BLE cifrado
(AES-CTR con clave de 16 bytes) que cualquier equipo cercano puede leer
sin emparejar — pero hace falta radio BLE para escucharlo, y la Pitaya no
tiene.

La solución: un **ESP32-C3** (que sí tiene BLE) hace de puente. Corre un
sketch mínimo que escucha los advertisements del SmartSolar y los manda
**crudos, sin desencriptar**, por USB serial. Conectado por USB a la
Red Pitaya, aparece ahí típicamente como `/dev/ttyACM0` — un script
Python en la Pitaya lee esas líneas y hace el desencriptado (mismo
algoritmo y misma clave que se usaba para leerlo por Bluetooth directo en
la notebook, proyecto separado `BLe panel solar` en la notebook — este es
el camino alternativo para cuando el que escucha no tiene Bluetooth
propio). Ese nombre lo asigna el kernel por orden de enumeración y no
está garantizado si algún día hay otro dispositivo serial USB enchufado
a la misma placa: los scripts no lo hardcodean, lo resuelven solos por
VID:PID vía `/dev/serial/by-id/` (ver `puerto.py`), con `ttyACM0` como
último recurso si no lo encuentran.

```
SmartSolar  --BLE (advertisement cifrado)-->  ESP32-C3  --USB serial (hex crudo)-->  Red Pitaya
                                                                                      (desencripta y muestra)
```

## Qué hay en esta carpeta

- `esp32_victron_scan/` — sketch del ESP32-C3 (ver su propio README para
  compilar/flashear).
- `victron_scanner.py` — desencriptado AES-CTR (usa el paquete
  `victron-ble`) + `SerialDecoder`, que parsea las líneas `MAC=... DATA=...`
  del ESP32. Compartido entre `leer_smartsolar_serial.py` y
  `publicar_losant.py`.
- `config.py` — MAC + clave de encriptación del SmartSolar.
- `puerto.py` — resuelve el puerto serial del ESP32 por VID:PID en vez de
  asumir `/dev/ttyACM0` fijo. Compartido entre `leer_smartsolar_serial.py`
  y `publicar_losant.py`.
- `leer_smartsolar_serial.py` — lee el puerto del ESP32, desencripta y
  muestra por pantalla. Para probar que el puente ESP32→Pitaya funciona.
- `publicar_losant.py` — lo mismo, pero publica por MQTT en Losant en vez
  de mostrar por pantalla. Publica un informe cuando detecta conexión real
  a Losant (evento `connect`/`reconnect` de losantmqtt) y además cada
  `panel_solar.informe_intervalo_min` (`config_campo.json`, en minutos)
  mientras la conexión siga en pie — no hay streaming cada N segundos fijo.
  Pensado para cuando la única ventana de red disponible es la del rele de
  Starlink (ver `starlink_remoto/`).
- `losant_config.py` — Device ID + credenciales de Losant. **No está en
  git** (ver `.gitignore`) — hay que crearlo a mano en la placa (paso 5).

## Setup en la Red Pitaya

### 1. Conectar el ESP32 (ya flasheado) por USB

Enchufarlo a un puerto USB de la Pitaya. Confirmar que aparece:

```bash
ssh root@<IP_PLACA> "ls -la /dev/ttyACM0 && lsusb | grep -i espressif"
```

Si el sketch todavía no está cargado en el ESP32, ver
`esp32_victron_scan/README.md` — se compila en la notebook pero se
flashea con el ESP32 ya conectado a la Pitaya (vía `esptool`, sin mover
la placa).

### 2. Copiar los scripts a la placa

```bash
scp config.py puerto.py victron_scanner.py leer_smartsolar_serial.py publicar_losant.py root@<IP_PLACA>:/root/panel_solar_ble/
```

(crear el directorio antes si no existe: `ssh root@<IP_PLACA> "mkdir -p /root/panel_solar_ble"`)

`losant_config.py` (credenciales) va aparte — ver paso 5, no hace falta si
solo se quiere probar la lectura (`leer_smartsolar_serial.py`).

### 3. Instalar dependencias — **ojo con `bleak`**

**No usar `pip install victron-ble` a secas.** `victron-ble` declara
`bleak` como dependencia obligatoria (la librería para escuchar
Bluetooth), y `bleak` arrastra `dbus-fast`, que no tiene wheel
precompilada para esta arquitectura (ARMv7l) — pip intenta compilarla
desde código fuente, y esa compilación **se queda sin memoria y el
kernel mata el proceso** (la placa tiene ~460 MB de RAM y sin swap;
confirmado con `dmesg | grep -i oom`). No hace falta `bleak` para nada de
esto: solo se usa para escuchar Bluetooth en vivo (lo que hacen
`leer_smartsolar.py`/`publicar_losant.py` en la notebook), no para leer
por serial.

Instalar así, en orden, evitando que `bleak` se instale (usar
`python -m pip`, no el binario `.venv/bin/pip` — ver nota al final de
este paso):

```bash
ssh root@<IP_PLACA> "
  cd /root/panel_solar_ble
  python3 -m venv .venv
  .venv/bin/python3 -m pip install --upgrade pip -q
  .venv/bin/python3 -m pip install victron-ble --no-deps -q
  .venv/bin/python3 -m pip install pycryptodome click pyserial -q
"
```

`--no-deps` en la primera línea es lo que evita que se intente traer
`bleak`. `pycryptodome`, `click` y `pyserial` son las dependencias reales
que sí hacen falta (y sí compilan bien en esta placa). Esto es un setup
de una sola vez por placa — si se reflashea el firmware, repetir.

`victron_scanner.py` está preparado para esto: el import de `bleak` (via
`victron_ble.scanner.BaseScanner`) es diferido — solo se dispara si algo
pide `VictronScanner` (la clase que escucha Bluetooth en vivo), que ni
`leer_smartsolar_serial.py` ni `publicar_losant.py` usan (ambos usan
`SerialDecoder`, que no la necesita). Si en el futuro se agrega algo a
esta carpeta que sí necesite escuchar Bluetooth directo desde la Pitaya,
va a fallar de nuevo con el mismo error de memoria — no es un problema
resuelto en general, solo esquivado para este camino (serial).

**Si `publicar_losant.py` va a correr en esta placa**, instalar además:

```bash
ssh root@<IP_PLACA> "
  cd /root/panel_solar_ble
  .venv/bin/python3 -m pip install losant-mqtt -q
  .venv/bin/python3 -m pip install 'setuptools<81' -q
"
```

El pin de `setuptools<81` es necesario: `losantmqtt` todavía importa
`pkg_resources`, que las versiones de `setuptools` 81+ ya no incluyen
(deprecado por upstream, no es un problema de esta placa). Sin el pin,
falla con `ModuleNotFoundError: No module named 'pkg_resources'`. Con la
versión vieja anda, solo tira un `UserWarning` de deprecación al importar
— ignorable por ahora.

**Nota sobre `.venv/bin/pip` vs `python -m pip`:** el script `pip` del
venv tiene el path del venv *hardcodeado* en su primera línea (shebang).
Si la carpeta del venv se renombra o mueve después de crearlo (como pasó
acá: `ble_panel_solar` → `panel_solar_ble`), `.venv/bin/pip` deja de
ejecutar con `cannot execute: required file not found`, aunque el venv
en sí siga sano. `python -m pip` no tiene ese problema porque no depende
del shebang — por eso todos los comandos de este README lo usan así.

### 4. Correr (lectura por pantalla, para probar el puente)

```bash
ssh root@<IP_PLACA> "cd /root/panel_solar_ble && .venv/bin/python3 -u leer_smartsolar_serial.py"
```

El `-u` (salida sin buffer) es necesario para ver algo en vivo por SSH —
sin eso, Python bufferea la salida por completo porque no hay terminal
del otro lado, y no se ve nada hasta que el proceso corta.

Salida esperada, una lectura cada 20s (ajustable con `INTERVALO_PANTALLA`
en el script):

```
[18:35:20] cb:ea:5b:96:33:6c  RSSI: -61 dBm
    battery_charging_current: -2.4 A
    battery_voltage: 12.64 V
    charge_state: bulk
    charger_error: no_error
    external_device_load: 2.7 A
    model_name: SmartSolar Charger MPPT 75/15 rev2
    solar_power: 2 W
    yield_today: 0 Wh
```

Si el puerto es otro: `.venv/bin/python3 -u leer_smartsolar_serial.py /dev/ttyUSB0`.

Ctrl+C para cortar.

### 5. Publicar en Losant

`losant_config.py` no está en git — crearlo a mano en la placa (mismo
contenido que el de la notebook, `BLe panel solar/losant_config.py`, o
copiarlo desde ahí):

```bash
scp "/home/facu-edge/BLe panel solar/losant_config.py" root@<IP_PLACA>:/root/panel_solar_ble/
```

Correr:

```bash
ssh root@<IP_PLACA> "cd /root/panel_solar_ble && .venv/bin/python3 -u publicar_losant.py"
```

Publica en dos momentos, mientras haya conexión con Losant:
- Apenas el script logra conectarse (evento `connect`, o `reconnect` si ya
  se había conectado antes y se cortó) — manda un único informe con la
  última lectura conocida del SmartSolar; si todavía no llegó ninguna
  lectura por serial en ese momento, espera a la próxima línea que mande
  el ESP32 (1-3s) y recién ahí publica.
- Cada `panel_solar.informe_intervalo_min` minutos (`config_campo.json`
  del paso 1, mismo archivo que usa `starlink_remoto/`) mientras la
  conexión siga en pie, para tener un reporte de batería periódico y no
  solo el del instante de conectar.

No hay streaming cada N segundos fijo. Si todavía no hay red al arrancar
(lo normal la mayor parte del día), reintenta conectar cada 30s
(`REINTENTO_CONEXION_S`) sin caerse.

**No correr esto al mismo tiempo que `publicar_losant.py` de la
notebook** — usan el mismo `DEVICE_ID` de Losant (es el mismo SmartSolar
físico), así que publicarían por duplicado al mismo dispositivo. Este
camino (Pitaya + ESP32) reemplaza al de la notebook, no lo complementa.

**Servicio systemd:** `publicar_losant.py` corre como servicio
(`systemd/panel-solar-informe.service`, instalación en
`scripts_campo/plan_campo/setup_placa.md` → paso 6) — arranca solo con la
placa y se reinicia si se cae, sin esperar a que haya red (ver
comentarios del propio archivo `.service` para el porqué). No correrlo a
mano mientras el servicio esté activo (competirían por el mismo puerto
serie) — pararlo primero (`systemctl stop panel-solar-informe.service`)
si hace falta debuggear a mano. `leer_smartsolar_serial.py` sigue siendo
solo para probar el puente manualmente, no tiene servicio propio.

## Actualizar la clave de encriptación

Si el SmartSolar se resetea o se regenera la clave desde VictronConnect,
`config.py` queda desactualizado. Ver el `README.md` del proyecto en la
notebook (`BLe panel solar/`) para el procedimiento de renovarla — es el
mismo `config.py`, solo hay que volver a copiarlo a la placa (paso 2).
