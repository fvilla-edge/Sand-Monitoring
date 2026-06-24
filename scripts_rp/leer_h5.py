#!/usr/bin/env python3
"""
leer_h5.py — Muestra los metadatos y metricas de archivos HDF5 del proyecto.

Uso:
  python3 leer_h5.py archivo.h5
  python3 leer_h5.py capturas/*.h5
"""
import sys
from pathlib import Path
import h5py


def leer(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        print(f"[ERROR] No existe: {ruta}")
        return

    with h5py.File(ruta, 'r') as f:
        print(f"\n{'='*55}")
        print(f"  {ruta.name}")
        print(f"{'='*55}")

        print("\n  METADATOS")
        print(f"  {'-'*40}")
        for k, v in sorted(f.attrs.items()):
            print(f"  {k:<18}: {v}")

        if 'metricas' in f:
            print("\n  METRICAS")
            print(f"  {'-'*40}")
            for k in sorted(f['metricas']):
                val = f['metricas'][k][()]
                print(f"  {k:<18}: {val}")

        if 'raw_signal' in f:
            ds = f['raw_signal']
            size_kb = ds.id.get_storage_size() / 1024
            print(f"\n  RAW SIGNAL")
            print(f"  {'-'*40}")
            print(f"  {'shape':<18}: {ds.shape}")
            print(f"  {'dtype':<18}: {ds.dtype}")
            print(f"  {'tamanio disco':<18}: {size_kb:.1f} KB (comprimido)")


if len(sys.argv) < 2:
    print("Uso: python3 leer_h5.py archivo.h5 [archivo2.h5 ...]")
    sys.exit(1)

for ruta in sys.argv[1:]:
    leer(ruta)
