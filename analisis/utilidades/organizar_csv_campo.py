#!/usr/bin/env python3
"""
organizar_csv_campo.py — junta los CSV de ventanas del modo evento (ventanas_AAAAMMDD_HH.csv,
hora UTC) bajados de la placa de campo en una carpeta por dia, sin duplicados.

Por cada hora junta todas las copias que haya en las carpetas de origen y decide:
  - copias identicas                      -> una sola;
  - una contenida en otra (bajada a medias) -> la mas completa;
  - partes sin solaparse (misma hora escrita en la SD y en el disco, antes y
    despues de un corte o reinicio)       -> se unen en un archivo, ordenadas por tiempo;
  - partes que se solapan con valores distintos -> NO se toca la hora, se avisa.
Las filas con bytes NUL (corte de energia en medio de una escritura) se limpian
(se descartan los NUL y las lineas incompletas).

Salida: DESTINO/AAAA-MM-DD/ventanas_*.csv (dia UTC, igual que el nombre del archivo)
+ DESTINO/indice.csv (por hora: filas, desde-hasta, origenes, accion, md5).
Se puede volver a correr incluyendo DESTINO como origen: es idempotente.
No borra ni modifica los origenes.

Uso:
    python3 analisis/utilidades/organizar_csv_campo.py DESTINO ORIGEN [ORIGEN ...] [--aplicar]
    (sin --aplicar solo muestra lo que haria)
"""
import argparse, collections, csv, glob, hashlib, os, re, sys
from datetime import datetime, timezone

PATRON = re.compile(r"^ventanas_(\d{8})_(\d{2})\.csv(\.con_nul)?$")
# columna dec desde 2026-10-06 (mono dec32 / dual dec64); las filas viejas de 6
# columnas son todas dec32 y se completan con ",32" para que el archivo quede parejo
ENCABEZADO = b"window_count,t_utc_ms,area,kurtosis,estado,perdidas_fpga,dec"


def leer_filas(ruta):
    raw = open(ruta, "rb").read()
    filas = []
    for linea in raw.replace(b"\0", b"").split(b"\n"):
        p = linea.split(b",")
        if len(p) not in (6, 7) or linea.startswith(b"window_count"):
            continue
        if len(p) == 6:
            linea += b",32"
        try:
            t = int(p[1])
        except ValueError:
            continue
        filas.append((t, linea))
    return filas, raw.count(b"\0")


def decidir(copias):
    """copias: lista de (ruta, filas). Devuelve (filas_resultado, accion) o (None, motivo)."""
    conjuntos = [dict(f) for _, f in copias]
    # ordenar de mas a menos filas
    orden = sorted(range(len(copias)), key=lambda i: -len(conjuntos[i]))
    resultado = dict(conjuntos[orden[0]])
    acciones = set()
    for i in orden[1:]:
        c = conjuntos[i]
        comunes = c.keys() & resultado.keys()
        if any(c[t] != resultado[t] for t in comunes):
            return None, f"CONFLICTO: {copias[i][0]} tiene filas con el mismo tiempo y otros valores"
        if not comunes:
            acciones.add("unida (partes sin solaparse)")
        elif len(comunes) == len(c):
            acciones.add("identica" if len(c) == len(resultado) else "contenida (copia parcial descartada)")
        else:
            acciones.add("unida (partes que se solapan en parte, valores iguales)")
        resultado.update(c)
    filas = sorted(resultado.items())
    return filas, ", ".join(sorted(acciones)) or "unica"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("destino"); ap.add_argument("origenes", nargs="+")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()

    horas = collections.defaultdict(list)
    for o in a.origenes:
        for f in sorted(glob.glob(os.path.join(o, "**", "ventanas_*.csv*"), recursive=True)):
            m = PATRON.match(os.path.basename(f))
            if m:
                horas[(m.group(1), m.group(2))].append(f)

    indice, problemas = [], 0
    for (dia, hh), rutas in sorted(horas.items()):
        copias, nul = [], 0
        for r in rutas:
            filas, n = leer_filas(r)
            nul += n
            if filas:
                copias.append((r, filas))
        if not copias:
            continue
        filas, accion = decidir(copias)
        nombre = f"ventanas_{dia}_{hh}.csv"
        carpeta = os.path.join(a.destino, f"{dia[:4]}-{dia[4:6]}-{dia[6:]}")
        if filas is None:
            problemas += 1
            print(f"!! {nombre}: {accion} — no se escribe")
            continue
        contenido = ENCABEZADO + b"\n" + b"\n".join(l for _, l in filas) + b"\n"
        md5 = hashlib.md5(contenido).hexdigest()
        if nul:
            accion += f", {nul} bytes NUL limpiados"
        fm = lambda t: datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%H:%M:%S")
        origenes = sorted({os.path.relpath(os.path.dirname(r), a.destino if os.path.commonpath([os.path.abspath(r), os.path.abspath(a.destino)]) == os.path.abspath(a.destino) else ".") for r in rutas})
        indice.append(dict(dia_utc=f"{dia[:4]}-{dia[4:6]}-{dia[6:]}", hora_utc=hh, archivo=nombre, filas=len(filas),
                           desde_utc=fm(filas[0][0]), hasta_utc=fm(filas[-1][0]), accion=accion,
                           copias=len(rutas), origenes=" ".join(os.path.dirname(r) for r in rutas), md5=md5))
        destino = os.path.join(carpeta, nombre)
        igual = os.path.exists(destino) and hashlib.md5(open(destino, "rb").read()).hexdigest() == md5
        print(f"{'  ' if igual else '->'} {nombre}: {len(filas):6d} filas {fm(filas[0][0])}-{fm(filas[-1][0])}  {accion}  ({len(rutas)} copias)")
        if a.aplicar and not igual:
            os.makedirs(carpeta, exist_ok=True)
            tmp = destino + ".tmp"
            open(tmp, "wb").write(contenido)
            os.replace(tmp, destino)

    if a.aplicar:
        os.makedirs(a.destino, exist_ok=True)
        with open(os.path.join(a.destino, "indice.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, list(indice[0].keys())); w.writeheader(); w.writerows(indice)
    dias = collections.Counter(i["dia_utc"] for i in indice)
    print(f"\n{len(indice)} horas en {len(dias)} dias: " + ", ".join(f"{d} ({n} h)" for d, n in sorted(dias.items())))
    if problemas:
        print(f"{problemas} horas con conflicto (no escritas)"); sys.exit(1)
    if not a.aplicar:
        print("(prueba: nada escrito; agregar --aplicar)")


if __name__ == "__main__":
    main()
