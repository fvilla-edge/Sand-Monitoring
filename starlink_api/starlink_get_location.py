#!/usr/bin/env python3
"""Lee posicion GPS y estado del link de una antena Starlink via su API gRPC local.

Requisitos:
  - Esta maquina debe estar conectada a la red WiFi/LAN de la antena
    (por defecto el router Starlink escucha en 192.168.100.1:9200).
  - "Location Sharing" debe estar habilitado para ese dish en la app
    de Starlink; si no, get_location responde sin datos de posicion.

Esta API no es publica ni documentada por SpaceX: se obtiene el esquema
de los mensajes en tiempo real via gRPC Server Reflection, que el dish
expone. Por eso el script no trae .proto embebidos: los descarga del
propio dish en cada ejecucion.

Los imports de grpc/protobuf estan diferidos (dentro de las funciones que
los usan, no a nivel de modulo): permite importar este archivo y usar
build_telemetry_payload()/to_losant_data() con HARDCODED_TELEMETRY sin
tener esas librerias instaladas. Motivo real, no cosmetico: el wheel de
grpcio en PyPI para esta placa (armv7l, cp312) instala pero tira
"Illegal instruction" al importarlo (Cortex-A9 sin soporte de alguna
instruccion que el wheel generico da por sentada) - confirmado en la
placa real. El camino validado para el modo --live es invocar el binario
`grpcurl` (Go, sin compilacion C, corre limpio en esta CPU) via
subprocess en vez de esta libreria - pendiente de implementar cuando se
pruebe contra la antena real.

Uso:
    pip install -r requirements.txt
    python3 starlink_get_location.py
    python3 starlink_get_location.py --host 192.168.100.1:9200 --json
"""

import argparse
import json
import sys
from datetime import datetime, timezone

SERVICE = "SpaceX.API.Device.Device"
METHOD = "Handle"
PACKAGE = "SpaceX.API.Device"

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


def _collect_reflected_files(stub, pool, seen, symbol=None, filename=None):
    """Descarga (recursivamente) los FileDescriptorProto que definen `symbol` o `filename`."""
    from google.protobuf.descriptor_pb2 import FileDescriptorProto
    from grpc_reflection.v1alpha import reflection_pb2

    if filename is not None:
        request = reflection_pb2.ServerReflectionRequest(file_by_filename=filename)
    else:
        request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    responses = stub.ServerReflectionInfo(iter([request]))

    for resp in responses:
        if resp.HasField("error_response"):
            raise RuntimeError(
                f"El dish rechazo la consulta de reflection para '{symbol or filename}': "
                f"{resp.error_response.error_message}"
            )
        for fdp_bytes in resp.file_descriptor_response.file_descriptor_proto:
            fdp = FileDescriptorProto()
            fdp.ParseFromString(fdp_bytes)
            if fdp.name in seen:
                continue
            seen.add(fdp.name)
            for dep in fdp.dependency:
                if dep not in seen:
                    _collect_reflected_files(stub, pool, seen, filename=dep)
            try:
                pool.Add(fdp)
            except TypeError:
                pass  # ya estaba registrado en el pool por defecto (p.ej. tipos google/protobuf)


def _open_dish(target: str, timeout: float):
    """Abre el canal y descubre el esquema (Request/Response) por reflection una sola vez."""
    import grpc
    from google.protobuf import descriptor_pool, message_factory
    from grpc_reflection.v1alpha import reflection_pb2_grpc

    channel = grpc.insecure_channel(target)
    grpc.channel_ready_future(channel).result(timeout=timeout)

    reflection_stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    pool = descriptor_pool.Default()
    _collect_reflected_files(reflection_stub, pool, seen=set(), symbol=SERVICE)

    try:
        request_cls = message_factory.GetMessageClass(
            pool.FindMessageTypeByName(f"{PACKAGE}.Request")
        )
        response_cls = message_factory.GetMessageClass(
            pool.FindMessageTypeByName(f"{PACKAGE}.Response")
        )
    except KeyError as exc:
        raise RuntimeError(
            "No se encontraron los mensajes Request/Response esperados. "
            "El esquema interno de la antena puede haber cambiado; "
            "inspeccionalo con 'grpcurl -plaintext "
            f"{target} list {SERVICE}'."
        ) from exc

    return channel, request_cls, response_cls


def _call(channel, request_cls, response_cls, field: str, timeout: float) -> dict:
    from google.protobuf.json_format import MessageToDict

    req = request_cls()
    if not hasattr(req, field):
        raise RuntimeError(
            f"El mensaje Request no tiene el campo '{field}'. "
            "Revisa el esquema actual del dish con grpcurl."
        )
    getattr(req, field).SetInParent()

    call = channel.unary_unary(
        f"/{SERVICE}/{METHOD}",
        request_serializer=req.SerializeToString,
        response_deserializer=response_cls.FromString,
    )
    resp = call(req, timeout=timeout)
    return MessageToDict(resp, preserving_proto_field_name=True)


def get_dish_location(target: str, timeout: float) -> dict:
    channel, request_cls, response_cls = _open_dish(target, timeout)
    return _call(channel, request_cls, response_cls, "get_location", timeout)


def extract_lla(response_dict: dict):
    """Intenta ubicar lat/lon/alt dentro de la respuesta, tolerando variaciones
    de esquema (la API no es oficial y puede cambiar entre firmwares)."""
    location = response_dict.get("get_location") or {}
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

    Solo una conexion/reflection (via _open_dish) para las dos llamadas: el dish
    esta marcado 'treat_as_metered', asi que conviene evitar trafico de mas.
    """
    channel, request_cls, response_cls = _open_dish(target, timeout)

    location_resp = _call(channel, request_cls, response_cls, "get_location", timeout)
    status_resp = _call(channel, request_cls, response_cls, "get_status", timeout)

    coords = extract_lla(location_resp) or {}
    status = status_resp.get("dish_get_status", {})
    device_info = status.get("device_info", {})
    gps = status.get("gps_stats", {})
    obstruction = status.get("obstruction_stats", {})
    alerts = status.get("alerts", {})

    alt = coords.get("alt")

    return {
        "device_id": device_info.get("id"),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {
            "lat": coords.get("lat"),
            "lon": coords.get("lon"),
            "alt": round(alt, 1) if alt is not None else None,
            "gps_valid": gps.get("gps_valid", False),
            "gps_sats": gps.get("gps_sats"),
        },
        "link": {
            "ping_ms": round(status.get("pop_ping_latency_ms", 0.0), 1),
            "ping_drop_rate": round(status.get("pop_ping_drop_rate", 0.0), 3),
            "downlink_bps": int(status.get("downlink_throughput_bps", 0)),
            "uplink_bps": int(status.get("uplink_throughput_bps", 0)),
        },
        "obstruction_fraction": round(obstruction.get("fraction_obstructed", 0.0), 4),
        "alerts": [name for name, active in alerts.items() if active],
        "uptime_s": int(status.get("device_state", {}).get("uptime_s", 0)),
        "hardware_version": device_info.get("hardware_version"),
        "software_version": device_info.get("software_version"),
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
        "alerts": ",".join(payload.get("alerts", [])) or "none",
        "uptime_s": payload.get("uptime_s"),
        "hardware_version": payload.get("hardware_version"),
        "software_version": payload.get("software_version"),
        "starlink_device_id": payload.get("device_id"),
    }


def main():
    import grpc

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
        except grpc.FutureTimeoutError:
            print(
                f"No se pudo conectar a {args.host}. "
                "Verifica que esta maquina este conectada a la red del router Starlink.",
                file=sys.stderr,
            )
            sys.exit(1)
        except grpc.RpcError as exc:
            print(f"Error gRPC: {exc.details() if hasattr(exc, 'details') else exc}", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(payload, separators=(",", ":")))
        return

    try:
        data = get_dish_location(args.host, args.timeout)
    except grpc.FutureTimeoutError:
        print(
            f"No se pudo conectar a {args.host}. "
            "Verifica que esta maquina este conectada a la red WiFi de la antena.",
            file=sys.stderr,
        )
        sys.exit(1)
    except grpc.RpcError as exc:
        print(f"Error gRPC: {exc.details() if hasattr(exc, 'details') else exc}", file=sys.stderr)
        sys.exit(1)
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
