#!/usr/bin/env python3
"""Lee posicion GPS y estado del link de una antena Starlink via su API gRPC local.

Requisitos:
  - Esta maquina debe estar conectada a la red WiFi/LAN de la antena
    (por defecto el router Starlink escucha en 192.168.100.1:9200).
  - "Location Sharing" debe estar habilitado para ese dish en la app
    de Starlink; si no, get_location responde sin datos de posicion.
  - El binario `grpcurl` (ver bin/, o en el PATH) - ver mas abajo por que.

Esta API no es publica ni documentada por SpaceX. En vez de la libreria
`grpcio` de Python, este script invoca el binario `grpcurl` (Go) por
`subprocess` y parsea su salida JSON - `grpcurl` resuelve el esquema de los
mensajes en tiempo real via gRPC Server Reflection, que el dish expone, asi
que no hace falta ningun .proto embebido ni tampoco `grpcio` instalado.

Motivo real, no cosmetico: el wheel de grpcio en PyPI para la placa donde
corre esto (armv7l, cp312) instala pero tira "Illegal instruction" al
importarlo (Cortex-A9 sin soporte de alguna instruccion que el wheel
generico da por sentada) - confirmado en la placa real, ver README.
`grpcurl` (binario estatico de Go, build linux_armv7, sin compilacion C)
corre limpio en esa misma CPU. Validado tambien contra el dish real:
`grpcurl` devuelve las claves en camelCase (mapeo JSON estandar de proto3:
"getLocation", "dishGetStatus", "gpsStats", etc.), no en snake_case - el
parseo de abajo usa esos nombres.

Uso:
    python3 starlink_get_location.py
    python3 starlink_get_location.py --host 192.168.100.1:9200 --json
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "SpaceX.API.Device.Device"
METHOD = "Handle"

# grpcurl no viene por pip: se descarga aparte (ver README, "por que grpcurl
# y no grpcio"). Primero busca en el PATH, y si no, en bin/ junto a este
# archivo (donde se lo deja al desplegar en la placa).
GRPCURL_BIN = shutil.which("grpcurl") or str(Path(__file__).parent / "bin" / "grpcurl")

# Mismo shape que build_telemetry_payload(), con un ejemplo real (Starlink Mini)
# capturado el 2026-08-24, para poder probar la integracion (Losant, atributos,
# etc.) sin estar conectado a la antena.
HARDCODED_TELEMETRY = {
    "device_id": "ut41109197-46602c0e-1ad5b334",
    "ts": "2026-08-24T17:43:25+00:00",
    "location": {
        "lat": -31.411168,
        "lon": -64.230164,
        "alt": 475.0,
        "gps_valid": True,
        "gps_sats": 13,
    },
    "link": {
        "ping_ms": 22.3,
        "ping_drop_rate": 0.05,
        "downlink_bps": 8153,
        "uplink_bps": 6350,
    },
    "obstruction_fraction": 0.0126,
    "alerts": [],
    "uptime_s": 1330,
    "hardware_version": "mini1_pez_proto1",
    "software_version": "2026.07.24.mr83021",
}


def _call(target: str, field: str, timeout: float) -> dict:
    """Invoca SpaceX.API.Device.Device/Handle con el campo `field` seteado
    (ej. "get_location", "get_status") via grpcurl, y devuelve el JSON
    (camelCase, ver docstring del modulo) ya parseado."""
    body = json.dumps({field: {}})
    try:
        resultado = subprocess.run(
            [
                GRPCURL_BIN,
                "-plaintext",
                "-connect-timeout", str(timeout),
                "-max-time", str(timeout),
                "-d", body,
                target,
                f"{SERVICE}/{METHOD}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"No se encontro el binario grpcurl ({GRPCURL_BIN}). Ver README de starlink_api/."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"grpcurl no respondio en {timeout}s contra {target}.") from exc

    if resultado.returncode != 0:
        raise RuntimeError(f"grpcurl fallo contra {target}: {resultado.stderr.strip()}")

    return json.loads(resultado.stdout)


def get_dish_location(target: str, timeout: float) -> dict:
    return _call(target, "get_location", timeout)


def extract_lla(response_dict: dict):
    """Intenta ubicar lat/lon/alt dentro de la respuesta, tolerando variaciones
    de esquema (la API no es oficial y puede cambiar entre firmwares)."""
    location = response_dict.get("getLocation") or {}
    lla = location.get("lla")
    if lla and all(k in lla for k in ("lat", "lon")):
        return {
            "lat": lla.get("lat"),
            "lon": lla.get("lon"),
            "alt": lla.get("alt"),
        }
    return None


def build_telemetry_payload(target: str, timeout: float) -> dict:
    """Combina get_location + get_status en un paquete compacto para publicar por MQTT.

    Dos invocaciones de grpcurl (una por llamada) en vez de compartir un canal:
    mas simple, a costa de resolver la reflection dos veces en vez de una. El
    dish esta marcado 'treatAsMetered' (confirmado contra el dish real) -
    trafico extra minimo (un par de KB), aceptable por la simplicidad.
    """
    location_resp = _call(target, "get_location", timeout)
    status_resp = _call(target, "get_status", timeout)

    coords = extract_lla(location_resp) or {}
    status = status_resp.get("dishGetStatus", {})
    device_info = status.get("deviceInfo", {})
    gps = status.get("gpsStats", {})
    obstruction = status.get("obstructionStats", {})
    alerts = status.get("alerts", {})

    alt = coords.get("alt")

    return {
        "device_id": device_info.get("id"),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {
            "lat": coords.get("lat"),
            "lon": coords.get("lon"),
            "alt": round(alt, 1) if alt is not None else None,
            "gps_valid": gps.get("gpsValid", False),
            "gps_sats": gps.get("gpsSats"),
        },
        "link": {
            "ping_ms": round(float(status.get("popPingLatencyMs", 0.0)), 1),
            "ping_drop_rate": round(float(status.get("popPingDropRate", 0.0)), 3),
            "downlink_bps": int(float(status.get("downlinkThroughputBps", 0))),
            "uplink_bps": int(float(status.get("uplinkThroughputBps", 0))),
        },
        "obstruction_fraction": round(float(obstruction.get("fractionObstructed", 0.0)), 4),
        "alerts": [name for name, active in alerts.items() if active],
        "uptime_s": int(status.get("deviceState", {}).get("uptimeS", 0)),
        "hardware_version": device_info.get("hardwareVersion"),
        "software_version": device_info.get("softwareVersion"),
    }


def to_losant_data(payload: dict) -> dict:
    """Convierte el payload de build_telemetry_payload() al formato plano que espera Losant.

    GPS en Losant es un string "lat,lon" en grados decimales (no un objeto lat/lon).
    """
    loc = payload["location"]
    link = payload["link"]
    lat, lon = loc.get("lat"), loc.get("lon")
    return {
        "posit": f"{lat},{lon}" if lat is not None and lon is not None else None,
        "altitude": loc.get("alt"),
        "gps_valid": loc.get("gps_valid"),
        "gps_satellites": loc.get("gps_sats"),
        "ping_ms": link.get("ping_ms"),
        "ping_drop_rate": link.get("ping_drop_rate"),
        "downlink_bps": link.get("downlink_bps"),
        "uplink_bps": link.get("uplink_bps"),
        "obstruction_fraction": payload.get("obstruction_fraction"),
        "alerts": ",".join(payload.get("alerts", [])) or None,
        "uptime_s": payload.get("uptime_s"),
        "hardware_version": payload.get("hardware_version"),
        "software_version": payload.get("software_version"),
        "starlink_device_id": payload.get("device_id"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--host",
        default="192.168.100.1:9200",
        help="host:puerto del dish/router Starlink (default: 192.168.100.1:9200)",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="timeout en segundos")
    parser.add_argument(
        "--json", action="store_true", help="imprime la respuesta completa como JSON"
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="imprime un paquete JSON compacto (ubicacion + salud del link) para publicar por MQTT",
    )
    args = parser.parse_args()

    if args.telemetry:
        try:
            payload = build_telemetry_payload(args.host, args.timeout)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(payload, separators=(",", ":")))
        return

    try:
        data = get_dish_location(args.host, args.timeout)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    coords = extract_lla(data)
    if coords is None:
        print(
            "La antena respondio pero sin coordenadas GPS validas "
            "(probablemente 'Location Sharing' esta deshabilitado en la app, "
            "o el dish no tiene fix GPS todavia). Respuesta cruda:",
            file=sys.stderr,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)

    print(f"lat: {coords['lat']}")
    print(f"lon: {coords['lon']}")
    print(f"alt: {coords['alt']}")


if __name__ == "__main__":
    main()
