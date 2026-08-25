# Telemetria del dish Starlink (GPS + estado del link) para Losant

`starlink_get_location.py` lee posicion GPS y estado del link de la antena
Starlink via su API gRPC no oficial (`192.168.100.1:9200`), y expone
`build_telemetry_payload()` + `to_losant_data()` para convertir eso al formato
plano que espera Losant.

**Este modulo no corre solo en produccion.** Lo consume
`panel_solar_ble/publicar_losant.py`, que publica el estado a Losant en el
mismo Device que ya usa el panel solar (mismo `DEVICE_ID`, a proposito — ver
`panel_solar_ble/losant_config.py`). No hay un servicio ni credenciales
propias en esta carpeta: dos conexiones MQTT simultaneas con el mismo
`client_id` se pisarian entre si.

`publicar_losant.py` publica el estado de Starlink una sola vez por cada
evento `connect`/`reconnect` de Losant (la señal mas directa de "hay
internet y llega a destino") — no hay reporte periodico para esto, a
diferencia del panel solar.

## Modo hardcoded vs live

Controlado por `starlink_api.modo` en `config_campo.json` (`"hardcoded"` o
`"live"`), leido una sola vez al importar `publicar_losant.py` (mismo
reinicio de servicio que cualquier otra config leida asi, ver
`DESPLIEGUE.md`).

- **`hardcoded`** (default): usa `HARDCODED_TELEMETRY` de este archivo — un
  ejemplo real capturado el 2026-08-24. Sirve para probar toda la cadena
  (config → Losant → dashboard) sin estar conectado a la antena.
- **`live`**: llama a `build_telemetry_payload()`, que habla de verdad con el
  dish por gRPC.

## Por que los imports de grpc estan diferidos

`build_telemetry_payload`, `extract_lla` y `to_losant_data` son puro Python.
Los imports de `grpc`/`grpc_reflection`/`google.protobuf` estan **dentro** de
las funciones que los usan (`_open_dish`, `_collect_reflected_files`,
`_call`, `main`), no a nivel de modulo — asi el modo `hardcoded` no toca esas
librerias para nada.

No es cosmetico: `pip install grpcio` en la placa (Red Pitaya, `armv7l`,
Python 3.12) SI encuentra un wheel binario en PyPI
(`grpcio-1.83.0-cp312-cp312-linux_armv7l.whl`) y se instala sin compilar
nada — pero al importarlo tira `Illegal instruction`. El Cortex-A9 de esta
placa no soporta alguna instruccion que ese wheel generico da por sentada
(confirmado en la placa real, no una suposicion). `piwheels` tampoco sirve:
no publica grpcio para esta combinacion de plataforma/version de Python.

**Camino validado para `live`:** el binario estatico `grpcurl` (Go, build
`linux_armv7`) corre limpio en esta placa (sin compilacion C, sin el
problema de instrucciones del wheel de grpcio). La implementacion de
`_open_dish()`/`build_telemetry_payload()` para modo `live` tiene que
invocarlo por `subprocess` y parsear su salida JSON en vez de usar la
libreria `grpcio` de Python — **todavia no implementado**, queda para
cuando se prueba contra la antena real.

## Atributos que hay que crear en Losant

Mismo Device que panel solar. Nombre → tipo, segun `to_losant_data()`:

| Atributo | Tipo |
|---|---|
| `posit` | string ("lat,lon") |
| `altitude` | number |
| `gps_valid` | boolean |
| `gps_satellites` | number |
| `ping_ms` | number |
| `ping_drop_rate` | number |
| `downlink_bps` | number |
| `uplink_bps` | number |
| `obstruction_fraction` | number |
| `alerts` | string |
| `uptime_s` | number |
| `hardware_version` | string |
| `software_version` | string |
| `starlink_device_id` | string |
| `starlink_error` | string |

Si no existen en el Device antes del primer publish, Losant probablemente
los descarta silenciosamente.

`starlink_error` no viene de `to_losant_data()` — lo agrega
`publicar_losant.py` aparte: vacío (`""`) cuando el informe salió bien,
mensaje de la excepción cuando falló obtener o publicar la telemetría (ver
`_publicar_starlink`). Es la forma de enterarse en campo, sin SSH a mano,
de que algo del lado Starlink dejó de funcionar.

## Probar la transformacion sin la placa ni grpcio instalado

```bash
python3 -c "from starlink_get_location import to_losant_data, HARDCODED_TELEMETRY; print(to_losant_data(HARDCODED_TELEMETRY))"
```
