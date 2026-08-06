# esp32_victron_scan

Sketch del ESP32-C3 Super Mini: escanea BLE, filtra los advertisements del
SmartSolar (Company ID `0x02E1`, record type `0x10`) y tira la manufacturer
data cruda por USB serial. El ESP32 no desencripta nada — eso lo hace
`leer_smartsolar_serial.py` (en la carpeta de arriba) del lado que lo lee,
ya sea la notebook o la Red Pitaya. Ver `../README.md` para el por qué de
este puente (la Red Pitaya no tiene soporte de Bluetooth en el kernel).

## Dónde se compila y dónde se flashea (importante)

El ESP32 vive enchufado por USB a la Red Pitaya en producción (no a la
notebook). La Pitaya es ARMv7l (armhf) y el toolchain de compilación de
Espressif para Linux ARM tiene un bug de empaquetado real (etiquetan el
build como `arm-linux-gnueabihf` pero el archivo es en realidad
`arm-linux-gnueabi`, soft-float) — la compilación en la placa falla
siempre con `riscv32-esp-elf-g++: no such file or directory`. Por eso:

- **Compilar siempre en la notebook** (x86_64, sin ese bug).
- **Flashear desde la Pitaya**, con el ESP32 conectado ahí — el flasheo
  usa `esptool`, que es un binario aparte y sí funciona bien en armhf (no
  necesita el compilador). No hace falta mover el ESP32 a la notebook.

Esto significa transferir el binario compilado de la notebook a la
Pitaya antes de flashear (ver más abajo).

## Una sola vez: instalar el toolchain de compilación (en la notebook)

```bash
mkdir -p ~/.local/bin
curl -fsSL -o /tmp/arduino-cli.tar.gz https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz
tar -xzf /tmp/arduino-cli.tar.gz -C ~/.local/bin arduino-cli

arduino-cli config init
arduino-cli config set board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli lib install "NimBLE-Arduino"
```

En la Pitaya **no hace falta instalar nada de esto** — ver la sección de
flasheo, que solo necesita el binario `esptool` (mucho más chico, sin el
compilador).

## Compilar (en la notebook)

Desde `panel_solar_ble/` (la carpeta que tiene este README adentro de
`esp32_victron_scan/`):

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32c3:CDCOnBoot=cdc" esp32_victron_scan --export-binaries
```

**El flag `CDCOnBoot=cdc` no es opcional.** Sin él, la opción de placa
"USB CDC On Boot" queda en su default (`Disabled`) y el `Serial` del
sketch no sale por el puerto USB nativo (`/dev/ttyACM0`) — el ESP32
arranca y corre bien, pero se queda mudo: no se ve ni el mensaje de boot
ni ninguna lectura BLE, aunque `esptool` sí puede hablarle (usa el
bootloader ROM, no depende de esto). Este bug ya se pisó una vez (sesión
del 2026-08-06): dos flasheos y como media hora de diagnóstico remoto
(reintentos de reset, sospecha de reenumeración USB, sospecha de bug de
hardware GPIO9) antes de encontrar que era solo esta opción de compilación.
Si algún día vuelve a pasar "flasheé bien pero no sale nada por serial",
**revisar esto primero.**

El FQBN genérico `esp32:esp32:esp32c3` (en vez del más específico
`nologo_esp32c3_super_mini` que se usaba antes) también funciona — no se
detectó ninguna diferencia relevante para este sketch (no usa el LED de a
bordo ni nada específico de la variante de placa). Si en algún momento
hace falta algo propio de la "Super Mini", usar
`esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc` en su lugar.

Esto genera, entre otros archivos, uno solo que hace falta para flashear:

```
build/esp32.esp32.esp32c3/esp32_victron_scan.ino.merged.bin
```

Es la imagen completa de 4MB (bootloader + partition table + app, ya en
sus offsets correctos) — alcanza con este archivo, no hace falta ninguno
de los otros `.bin`/`.elf`/`.map` de esa carpeta. `build/` está en
`.gitignore`: son artefactos de compilación, se regeneran con el comando
de arriba, no hace falta (ni conviene) versionarlos.

## Flashear (con el ESP32 conectado a la Pitaya)

### 1. Copiar el binario a la Pitaya

```bash
ssh root@<IP_PLACA> "mkdir -p /root/panel_solar_ble/esp32_victron_scan"
scp panel_solar_ble/esp32_victron_scan/build/esp32.esp32.esp32c3/esp32_victron_scan.ino.merged.bin root@<IP_PLACA>:/root/panel_solar_ble/esp32_victron_scan/esp32_victron_scan.ino.merged.bin
```

### 2. Liberar el puerto serie

Si `panel-solar-informe.service` está corriendo, tiene `/dev/ttyACM0`
abierto y el flasheo va a fallar (puerto ocupado):

```bash
ssh root@<IP_PLACA> "systemctl stop panel-solar-informe.service"
```

### 3. Flashear con `esptool`

En la Pitaya alcanza con el binario `esptool` (sin el resto del core de
arduino-cli, ver la sección de limpieza más abajo). Ubicación esperada:
`/root/bin/esptool`.

```bash
ssh root@<IP_PLACA> "/root/bin/esptool --chip esp32c3 --port /dev/ttyACM0 write_flash 0x0 /root/panel_solar_ble/esp32_victron_scan/esp32_victron_scan.ino.merged.bin"
```

Tarda ~25s. Al final hace un reset automático ("Hard resetting via RTS
pin...") y el ESP32 arranca solo con el firmware nuevo.

### 4. Reactivar el servicio

```bash
ssh root@<IP_PLACA> "systemctl start panel-solar-informe.service"
```

### 5. Verificar que anduvo

```bash
ssh root@<IP_PLACA> "journalctl -u panel-solar-informe.service -f"
```

Con la placa conectada al SmartSolar, debería aparecer `Conectado a
Losant.` y, apenas llegue la primera línea del ESP32 (1-3s), un `Informe
publicado (<mac>): {...}` con los datos reales de batería/potencia solar.
Si pasan varios minutos sin ningún `Informe publicado`, algo anda mal —
revisar primero el gotcha de `CDCOnBoot` de arriba antes de sospechar del
hardware.

Para debug más crudo (ver las líneas `MAC=... DATA=...` tal como las
manda el ESP32, sin pasar por el script de Losant), parar el servicio y
leer el puerto directo:

```bash
ssh root@<IP_PLACA> "systemctl stop panel-solar-informe.service && timeout 15 cat /dev/ttyACM0"
```

## Instalación de `esptool` en la Pitaya (una sola vez)

No hace falta instalar el core completo de arduino-cli en la Pitaya — de
hecho conviene no hacerlo (ver "Limpieza" abajo, esto ocupaba ~5.5GB
inútiles ya que la compilación real pasa siempre por la notebook). Alcanza
con el binario `esptool` solo. Si no está en `/root/bin/esptool` en una
placa nueva, la forma más simple de conseguirlo es descargar el core de
`esp32:esp32` una vez en cualquier máquina (o en la Pitaya, temporalmente)
y copiar el binario:

```bash
arduino-cli core install esp32:esp32   # una sola vez, en cualquier maquina
# el binario queda en <arduino15>/packages/esp32/tools/esptool_py/<version>/esptool
cp .../esptool_py/<version>/esptool /root/bin/esptool   # copiar SOLO este archivo a la Pitaya
```

Es un binario autocontenido (PyInstaller), no depende de Python ni de
nada más instalado en la placa. Después de copiarlo, se puede desinstalar
el core completo (`arduino-cli core uninstall esp32:esp32`) sin perder la
capacidad de flashear.

## Limpieza (2026-08-06): no instalar el toolchain completo en la Pitaya

Hasta esta fecha, `/root/.arduino15` en la Pitaya tenía el core
`esp32:esp32` completo (compiladores `riscv32-esp-elf`/`xtensa-esp-elf`,
gdb, openocd, libs de cada variante de chip, ~5.5GB) instalado para un
intento fallido de compilar directo en la placa (bloqueado por el bug de
toolchain ARM mencionado arriba). Como la compilación siempre se hace en
la notebook, todo eso era espacio desperdiciado — se desinstaló
(`arduino-cli core uninstall esp32:esp32` + borrar `~/.arduino15/staging`
+ la librería `NimBLE-Arduino` de `~/Arduino/libraries`, que tampoco hace
falta en la placa) y solo se dejó el binario `esptool` copiado a
`/root/bin/esptool`, fuera de `~/.arduino15`, más `arduino-cli` en sí
(34MB, no hace daño dejarlo, pero ya no compila nada útil ahí). Resultado:
~5.4GB liberados. Si una placa nueva alguna vez necesita este setup, no
repetir el error — instalar el core en la notebook, copiar solo el
binario `esptool`.

## Ver los datos crudos por terminal (solo para debug del sketch, con el ESP32 en la notebook)

Si el ESP32 está conectado a la notebook en vez de a la Pitaya (por
ejemplo, para debug del sketch antes de llevarlo a producción):

```bash
arduino-cli upload -p /dev/ttyACM0 --fqbn "esp32:esp32:esp32c3:CDCOnBoot=cdc" esp32_victron_scan
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=115200
```

Al conectar, la placa se resetea sola (mensajes de boot del ROM) y después
tira líneas del tipo:

```
Iniciando escaneo BLE (Victron, Company ID 0x02E1)...
MAC=cb:ea:5b:96:33:6c RSSI=-95 LEN=22 DATA=E102100275A0012C393A21AE2614AF458B466539DA40
```

Salir con `Ctrl+C`. Alternativa si `arduino-cli monitor` no anda:
`screen /dev/ttyACM0 115200` (`Ctrl+A` `k`, confirmar con `y` para salir).

Para ver los datos ya decodificados (voltaje, corriente, etc.) en vez del
hex crudo, usar `leer_smartsolar_serial.py` — ver `../README.md`.

## Notas

- El RSSI suele verse débil si el SmartSolar está lejos o hay obstáculos —
  no es un problema del sketch.
- Solo filtra el tipo de paquete que importa (`0x10`, Instant Readout
  cifrado). Victron manda otros advertisements con el mismo Company ID que
  se descartan a propósito.
- `wantDuplicates=true` en `scan->setScanCallbacks()` es necesario: sin
  eso, NimBLE avisa solo la primera vez que ve cada MAC, aunque el
  contenido del anuncio cambie después (que es exactamente lo que pasa:
  el SmartSolar manda datos cifrados nuevos en cada anuncio, misma MAC).
