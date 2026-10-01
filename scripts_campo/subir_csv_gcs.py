#!/usr/bin/env python3
"""
subir_csv_gcs.py — sube a Google Cloud Storage los CSV horarios de ventanas
del modo evento una vez que la hora se cerro, comprimidos con gzip
(~3 MB -> ~1 MB). Dos origenes:
  - /mnt/usb/eventos/ventanas_AAAAMMDD_HH.csv, si hay disco;
  - rutas.eventos_sd (/root/eventos_sd), donde mide la placa sin disco
    (supervisor_eventos.sh arrancar): esos suben con sufijo _sd
    (ventanas_AAAAMMDD_HH_sd.csv.gz), porque la misma hora puede existir
    partida en los dos lados (p.ej. el disco se cae a mitad de hora) y con
    ifGenerationMatch=0 la segunda no subiria nunca.

Lo corre subir-csv-gcs.timer cada pocos minutos (oneshot): si no hay
internet (de noche, sin Starlink) falla rapido y los CSV quedan para la
proxima corrida, sin cola aparte: el CSV del USB ES la cola, y
gcs.registro_sd registra los que ya subieron.

- El registro de subidos va a la SD, nunca al USB: en campo los dos
  congelamientos con reset por watchdog del 30/9 fueron segundos despues de
  una subida (justo al escribir+fsync del registro en el disco USB, que
  despues no volvio a enumerar). gcs.subidos_file (el registro viejo en
  /mnt/usb) solo se LEE, si existe, para no volver a subir lo ya subido.
- Carga acotada: pocos archivos por corrida, pausa entre archivos y gzip 1
  (~4x menos CPU que el 6, ~20% mas grande; el tramo caro era el gzip).

- Hora cerrada = mas vieja que la hora UTC actual y sin escrituras en los
  ultimos MARGEN_CIERRE_S (capturar_eventos rota el archivo a la hora justa).
- Nunca lista la carpeta de eventos (puede tener decenas de miles de
  archivos): los nombres salen de las horas de los ultimos gcs.dias_atras.
- Objeto: <gcs.prefijo>/<hostname>/AAAA/MM/DD/ventanas_AAAAMMDD_HH[_sd].csv.gz,
  con ifGenerationMatch=0: nunca pisa. Si ya existe (412, p.ej. se corto la
  conexion despues de que GCS lo guardo), se da por subido.
- Se verifica el md5 que devuelve GCS contra el del gzip local.
- La cuenta de servicio solo tiene storage.objects.create (no puede leer,
  listar ni borrar): la clave (gcs.credenciales_file, fuera de git) sirve
  solo para subir. El token (1h) se firma aca con openssl; la clave va a un
  archivo temporal en /run (tmpfs, solo root) que se borra al terminar.

Uso:
    python3 subir_csv_gcs.py [--max N] [--seco]
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/root/scripts_campo_comun")
import cfg  # noqa: E402 (import tardio, necesita el sys.path de arriba)

DIR_EVENTOS = "/mnt/usb/eventos"
SUFIJO_SD = "_sd"
MARGEN_CIERRE_S = 120
TIMEOUT_S = 60
# gzip 1: en PC 0.024s contra 0.109s del 6 por CSV, 1.0 MB contra 0.82 MB
# (medido 2026-10-01). En la placa el 6 tardaba ~2.7-5.7s, el 9 ~14.7s y
# coincidia con perdidas de muestras: menos CPU vale mas que 180 KB.
NIVEL_GZIP = 1
# 2 por corrida cada 10 min = 12/h: la noche (~16 h) sale en ~1.5 h.
MAX_POR_CORRIDA = 2
PAUSA_ENTRE_S = 30
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def pedir_token(credenciales):
    """Access token de 1h para la cuenta de servicio (JWT firmado con openssl)."""
    with open(credenciales) as f:
        cred = json.load(f)
    ahora = int(time.time())
    cabecera = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    cuerpo = _b64url(json.dumps({
        "iss": cred["client_email"], "scope": SCOPE, "aud": cred["token_uri"],
        "iat": ahora, "exp": ahora + 3600}).encode())
    firmar = cabecera + b"." + cuerpo
    with tempfile.NamedTemporaryFile("w", dir="/run", prefix="gcs_", suffix=".pem", delete=False) as k:
        os.chmod(k.name, 0o600)
        k.write(cred["private_key"])
    try:
        firma = subprocess.run(["openssl", "dgst", "-sha256", "-sign", k.name],
                               input=firmar, capture_output=True, check=True).stdout
    finally:
        os.remove(k.name)
    datos = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": (firmar + b"." + _b64url(firma)).decode()}).encode()
    with urllib.request.urlopen(cred["token_uri"], datos, timeout=TIMEOUT_S) as r:
        return json.load(r)["access_token"]


def disco_montado():
    """True si /mnt/usb es un disco de verdad (no la carpeta de la SD ni un tmpfs)."""
    if not os.path.ismount("/mnt/usb"):
        return False
    tipo = None
    try:
        with open("/proc/mounts") as f:
            for linea in f:   # el ultimo montaje sobre /mnt/usb es el que se ve
                partes = linea.split()
                if len(partes) > 2 and partes[1] == "/mnt/usb":
                    tipo = partes[2]
    except OSError:
        pass
    return tipo != "tmpfs"


def origenes():
    """(carpeta, sufijo) de donde subir: el disco solo si esta montado."""
    lista = [(DIR_EVENTOS, "")] if disco_montado() else []
    return lista + [(cfg.obtener("rutas.eventos_sd"), SUFIJO_SD)]


def horas_cerradas(dias_atras, subidos, fuentes):
    """CSV de horas ya cerradas que existen y no subieron, del mas viejo al mas
    nuevo: (hora, ruta, nombre con el que sube y se registra)."""
    ahora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    pendientes = []
    for h in range(dias_atras * 24, 0, -1):
        t = ahora - timedelta(hours=h)
        for carpeta, sufijo in fuentes:
            nombre = f"ventanas_{t:%Y%m%d_%H}{sufijo}.csv"
            if nombre in subidos:
                continue
            ruta = os.path.join(carpeta, f"ventanas_{t:%Y%m%d_%H}.csv")
            try:
                mtime = os.stat(ruta).st_mtime
            except FileNotFoundError:
                continue
            if time.time() - mtime >= MARGEN_CIERRE_S:
                pendientes.append((t, ruta, nombre))
    return pendientes


def subir(token, bucket, objeto, datos):
    """True si quedo subido (o ya existia). Levanta en errores de red/HTTP."""
    url = ("https://storage.googleapis.com/upload/storage/v1/b/%s/o"
           "?uploadType=media&ifGenerationMatch=0&name=%s"
           % (bucket, urllib.parse.quote(objeto, safe="")))
    req = urllib.request.Request(url, data=datos, method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/gzip"})
    md5 = base64.b64encode(hashlib.md5(datos).digest()).decode()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 412:
            log(f"{objeto}: ya existia en GCS (412), se da por subido")
            return True
        raise
    if resp.get("md5Hash") != md5:
        raise RuntimeError(f"{objeto}: md5 distinto (local {md5}, GCS {resp.get('md5Hash')})")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=MAX_POR_CORRIDA,
                    help=f"maximo de archivos por corrida (default {MAX_POR_CORRIDA}, reparte la carga tras la noche)")
    ap.add_argument("--seco", action="store_true", help="solo listar lo que subiria, sin conectarse")
    args = ap.parse_args()

    if not cfg.obtener("gcs.habilitado"):
        log("gcs.habilitado=false, no se sube nada")
        return 0
    registro = cfg.obtener("gcs.registro_sd")
    subidos = set()
    for ruta in (registro, cfg.obtener("gcs.subidos_file")):
        try:
            with open(ruta) as f:
                subidos.update(l.strip() for l in f if l.strip())
        except FileNotFoundError:
            pass

    pendientes = horas_cerradas(cfg.obtener("gcs.dias_atras"), subidos, origenes())
    if not pendientes:
        log("nada pendiente")
        return 0
    log(f"{len(pendientes)} CSV pendientes (se suben hasta {args.max})")
    if args.seco:
        for _, ruta, nombre in pendientes[:args.max]:
            log(f"  subiria {ruta} como {nombre}.gz")
        return 0

    bucket = cfg.obtener("gcs.bucket")
    base = f"{cfg.obtener('gcs.prefijo')}/{socket.gethostname()}"
    try:
        token = pedir_token(cfg.obtener("gcs.credenciales_file"))
    except (OSError, urllib.error.URLError, subprocess.CalledProcessError) as e:
        log(f"sin token (¿sin internet?): {e} — se reintenta en la proxima corrida")
        return 0

    n_ok = 0
    for i, (t, ruta, nombre) in enumerate(pendientes[:args.max]):
        if i:
            time.sleep(PAUSA_ENTRE_S)
        objeto = f"{base}/{t:%Y/%m/%d}/{nombre}.gz"
        with open(ruta, "rb") as f:
            crudo = f.read()
        datos = gzip.compress(crudo, NIVEL_GZIP)
        t0 = time.time()
        try:
            subir(token, bucket, objeto, datos)
        except (OSError, urllib.error.URLError, RuntimeError) as e:
            log(f"{objeto}: fallo ({e}) — se corta la corrida, se reintenta en la proxima")
            break
        with open(registro, "a") as f:
            f.write(nombre + "\n")
            f.flush()
            os.fsync(f.fileno())
        n_ok += 1
        log(f"{objeto}: {len(crudo)} -> {len(datos)} B en {time.time() - t0:.1f}s, md5 ok")
    log(f"subidos {n_ok}/{min(len(pendientes), args.max)}, quedan {len(pendientes) - n_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
