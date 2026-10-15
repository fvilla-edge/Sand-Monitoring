"""
Cambia el tag `modo_starlink` (ventana | permanente) de un Device de Losant
por la API REST, desde la PC. El workflow del Device lo compara con el
`sl_modo` que publica la placa y, si difieren, le manda el comando `modo`
(ver docs/plan_modos_starlink.md). La placa recien se entera cuando esta
conectada: en modo ventana, en la proxima ventana (hasta 2 h).

El PATCH de Losant reemplaza la lista ENTERA de tags: por eso se lee el
Device, se cambia solo `modo_starlink` y se manda la lista completa (los
demas tags quedan como estaban). Al final se vuelve a leer para verificar.

Token: Application API Token con scope device.get + device.patch, en
losant_api_token.txt en la raiz del repo (fuera de git, permisos 600). Es el
txt que descarga Losant tal cual: se toma la linea que empieza con "eyJ".
Nunca va a la placa.

Uso (desde la raiz del repo):
    python3 comandos_losant/modo_starlink.py <device_id> ventana|permanente [--seco]
    python3 comandos_losant/modo_starlink.py <device_id> --ver
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

APP_ID = "6a85af0d0a0c5812f97c1828"
TAG = "modo_starlink"
MODOS = ("ventana", "permanente")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "losant_api_token.txt")
TIMEOUT_S = 20


def leer_token():
    with open(TOKEN_FILE) as f:
        for linea in f:
            if linea.strip().startswith("eyJ"):
                return linea.strip()
    sys.exit(f"no encontre el token en {TOKEN_FILE}")


def pedir(token, device_id, metodo="GET", cuerpo=None):
    url = f"https://api.losant.com/applications/{APP_ID}/devices/{device_id}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Losant respondio {e.code} a {metodo}: {e.read().decode(errors='replace')}")


def modo_de(tags):
    valores = [t.get("value") for t in tags if t.get("key") == TAG]
    return ", ".join(valores) if valores else "(sin tag)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("device_id")
    ap.add_argument("modo", nargs="?", choices=MODOS)
    ap.add_argument("--ver", action="store_true", help="solo mostrar el modo actual")
    ap.add_argument("--seco", action="store_true", help="mostrar lo que mandaria, sin cambiar nada")
    args = ap.parse_args()
    if not args.ver and not args.modo:
        ap.error("falta el modo (ventana | permanente) o --ver")

    token = leer_token()
    dev = pedir(token, args.device_id)
    tags = dev.get("tags", [])
    conectado = dev.get("connectionInfo", {}).get("connected")
    print(f"{dev.get('name')}: {TAG} = {modo_de(tags)} (conectado: {'si' if conectado else 'no'})")
    if args.ver:
        return

    nuevos = [t for t in tags if t.get("key") != TAG] + [{"key": TAG, "value": args.modo}]
    if nuevos == tags:
        print("ya esta en ese modo, no se cambia nada")
        return
    if args.seco:
        print("mandaria tags:", json.dumps(nuevos))
        return

    pedir(token, args.device_id, "PATCH", {"tags": nuevos})
    final = pedir(token, args.device_id).get("tags", [])
    print(f"{TAG} = {modo_de(final)}")
    if sorted(map(json.dumps, final)) != sorted(map(json.dumps, nuevos)):
        sys.exit(f"ADVERTENCIA: los tags quedaron distintos a lo pedido: {final}")
    if not conectado:
        print("la placa no esta conectada: lo aplica en la proxima conexion (modo ventana: proxima ventana)")


if __name__ == "__main__":
    main()
