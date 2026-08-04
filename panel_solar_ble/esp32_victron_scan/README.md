# esp32_victron_scan

Sketch del ESP32-C3 Super Mini: escanea BLE, filtra los advertisements del
SmartSolar (Company ID `0x02E1`, record type `0x10`) y tira la manufacturer
data cruda por USB serial. El ESP32 no desencripta nada — eso lo hace
`leer_smartsolar_serial.py` (en la carpeta de arriba) del lado que lo lee,
ya sea la notebook o la Red Pitaya. Ver `../README.md` para el por qué de
este puente (la Red Pitaya no tiene soporte de Bluetooth en el kernel).

## Una sola vez: instalar el toolchain

En la notebook (`arduino-cli` en `~/.local/bin`, en el PATH). Si hay que
repetirlo en otra máquina:

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

## Compilar

Desde `panel_solar_ble/` (la carpeta que tiene este README adentro de
`esp32_victron_scan/`):

```bash
arduino-cli compile --fqbn esp32:esp32:nologo_esp32c3_super_mini esp32_victron_scan
```

`nologo_esp32c3_super_mini` es el board definido para el "ESP32-C3 Super
Mini" (la placa genérica sin marca). Si compila mal por esto, buscar el
FQBN correcto con `arduino-cli board listall | grep -i c3`.

## Flashear

Con la placa conectada por USB a la notebook (aparece como `/dev/ttyACM0`):

```bash
arduino-cli upload -p /dev/ttyACM0 --fqbn esp32:esp32:nologo_esp32c3_super_mini esp32_victron_scan
```

Si el puerto es otro, confirmarlo con `ls /dev/ttyACM*` o `ls /dev/ttyUSB*`.
Una vez flasheado, el ESP32 escanea solo apenas se le da alimentación por
USB — no hace falta la notebook para que funcione, alcanza con enchufarlo
a la Red Pitaya (ver `../README.md`).

## Ver los datos crudos por terminal (solo para debug del sketch)

```bash
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
