# Visor de CSV portable para Windows

`armar_exe_windows.sh` arma `visor_windows/VisorSandMonitoring.exe` (fuera de
git) a partir de `analisis/visores/visor_csv.py`: un solo archivo, se abre con
doble click, sin instalar Python ni nada en la PC con Windows.

```bash
bash analisis/visores/empaquetar/armar_exe_windows.sh
```

Rearmarlo cada vez que cambien `visor_csv.py`, `vista_reducida.py` o
`analisis/placa/ventanas_a_paquete.py`. `visor_windows/VERSION.txt` dice de
qué commit salió (`+cambios` si había cambios sin commitear en `analisis/`).

## Entorno (preparado una sola vez, 2026-09-30)

Todo dentro de un prefijo de Wine propio, `~/.wine_visor_csv` (no toca `~/.wine`):

1. Wine 9.0 del sistema (`wine64`). **No** hay `wine32`, por eso el
   instalador `.exe` de python.org (32 bits) no corre.
2. Python 3.12.10 de 64 bits instalado desde sus `.msi` sueltos
   (`https://www.python.org/ftp/python/3.12.10/amd64/{core,exe,lib,tcltk,dev}.msi`):
   ```bash
   export WINEPREFIX=~/.wine_visor_csv
   wine msiexec /i 'C:\msi_py\core.msi' 'TARGETDIR=C:\Python312' ALLUSERS=0 /qn   # idem exe, lib, tcltk, dev
   wine 'C:\Python312\python.exe' -m ensurepip
   ```
   (`msiexec /a` no sirve: esos `.msi` no tienen instalación administrativa.)
3. Paquetes: `matplotlib==3.11.0`, `numpy==1.26.4`, `pyinstaller`,
   `tkinterdnd2`. **numpy 1.26**, no 2.x: los wheels de numpy 2.2+ para
   Windows llaman a `ucrtbase.crealf`, que Wine 9.0 no implementa (en Windows
   real andarían, pero PyInstaller tiene que importar numpy para armar el
   `.exe`). El visor solo usa funciones básicas de numpy, iguales en 1.26.

## Qué no se probó

El `.exe` se arma y se puede abrir bajo Wine, pero la prueba de verdad es en
un Windows real (antivirus, SmartScreen: un `.exe` sin firmar puede pedir
"Ejecutar de todas formas" la primera vez).
