#!/usr/bin/env python3
"""
visor_csv.py — Visor de los CSV horarios del modo evento
(`ventanas_AAAAMMDD_HH.csv`, o `.csv.gz` como quedan en Google Cloud Storage):
área y kurtosis de cada ventana de 50ms, una o varias horas unidas, con la
hora en Argentina o UTC. Es el que se arma como ejecutable portable
(`empaquetar/`), así que solo usa numpy + matplotlib + tkinter (nada de
scipy ni de revisar.py).

Uso: agregar archivos o una carpeta, elegir una o varias horas en la lista
(Ctrl/Shift para varias) y se grafican unidas. Zoom y desplazamiento con la
barra de abajo del gráfico: al acercarse aparecen las ventanas una por una.

Desde el repo: .venv/bin/python3 analisis/visores/visor_csv.py [CSV o carpeta ...]
"""
import sys
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

sys.path.insert(0, str(Path(__file__).resolve().parent))                  # vista_reducida
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "placa"))  # ventanas_a_paquete
from vista_reducida import VistaReducida  # noqa: E402
from ventanas_a_paquete import VENTANA_S, armar_paquete, leer_filas  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _CON_DND = True
except ImportError:
    _CON_DND = False

# Mismo umbral que el modo evento de la placa y FA_THRESH de revisar.py (no se
# importa para no arrastrar scipy al ejecutable; un test verifica que coincidan).
UMBRAL_KURT = 5.0
ZONAS = {"Argentina (UTC-3)": timezone(timedelta(hours=-3), "ART"), "UTC": timezone.utc}
MAX_EVENTOS_LISTA = 200
DIA_S = 86400.0


def cargar_hora(ruta: Path):
    """Un CSV horario -> arrays (t en dias de matplotlib, area, kurtosis) +
    saltadas y tramos, sin guardar las filas (un dia entero entra holgado)."""
    paquete = armar_paquete(leer_filas([ruta]), ruta.name)
    canal = paquete["canales"][0]
    t0 = mdates.date2num(datetime.fromisoformat(paquete["inicio_utc"]))
    return {
        "t": t0 + np.asarray(canal["t_centro_s"], dtype=float) / DIA_S,
        "area": np.asarray(canal["area"], dtype=float),
        "kurt": np.asarray(canal["kurtosis"], dtype=float),
        "saltadas": paquete["ventanas_saltadas"],
        "tramos": len(paquete["segmentos"]),
    }


def _es_csv(ruta: Path):
    return ruta.name.startswith("ventanas_") and (ruta.name.endswith(".csv") or ruta.name.endswith(".csv.gz"))


class VisorCSV:
    def __init__(self, root):
        self.root = root
        root.title("Sand Monitoring — área y kurtosis por ventana (modo evento)")
        root.geometry("1250x820")

        self.archivos = []   # Path, ordenados por nombre (= por hora)
        self.cache = {}      # Path -> dict de cargar_hora()
        self._fig = None
        self._canvas = None
        self._toolbar = None
        self._vista = None

        izq = tk.Frame(root, width=300)
        izq.pack(side="left", fill="y", padx=6, pady=6)
        izq.pack_propagate(False)

        tk.Label(izq, text="Horas (Ctrl/Shift para ver varias juntas):").pack(anchor="w")
        marco_lista = tk.Frame(izq)
        marco_lista.pack(fill="both", expand=True, pady=4)
        self.listbox = tk.Listbox(marco_lista, selectmode="extended", exportselection=False)
        barra = tk.Scrollbar(marco_lista, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=barra.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._al_elegir)
        if _CON_DND:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._al_soltar)

        botones = tk.Frame(izq)
        botones.pack(fill="x")
        tk.Button(botones, text="Agregar archivo(s)...", command=self._agregar_archivos).pack(fill="x")
        tk.Button(botones, text="Agregar carpeta...", command=self._agregar_carpeta).pack(fill="x", pady=(4, 0))
        tk.Button(botones, text="Seleccionar todo", command=self._seleccionar_todo).pack(fill="x", pady=(4, 0))
        tk.Button(botones, text="Vaciar lista", command=self._vaciar).pack(fill="x", pady=(4, 0))

        marco_zona = tk.Frame(izq)
        marco_zona.pack(fill="x", pady=(8, 0))
        tk.Label(marco_zona, text="Hora:").pack(side="left")
        self.zona = tk.StringVar(value="Argentina (UTC-3)")
        for nombre in ZONAS:
            tk.Radiobutton(marco_zona, text=nombre, variable=self.zona, value=nombre,
                           command=self._redibujar).pack(side="left")

        self.info = tk.Text(izq, height=16, width=38, font=("Courier", 8), state="disabled", wrap="none")
        self.info.pack(fill="both", pady=(8, 0))

        der = tk.Frame(root)
        der.pack(side="right", fill="both", expand=True, padx=6, pady=6)
        self.der = der
        self._mensaje(f"Agregá los CSV (ventanas_*.csv o .csv.gz) con los botones"
                      f"{' o arrastrándolos a la lista' if _CON_DND else ''}.\n"
                      f"Umbral de evento: kurtosis ≥ {UMBRAL_KURT:g}.")

    # --- lista ---

    def _al_soltar(self, event):
        for ruta in self.root.tk.splitlist(event.data):
            self.agregar_ruta(Path(ruta))

    def _agregar_archivos(self):
        rutas = filedialog.askopenfilenames(
            title="Elegí uno o más CSV del modo evento",
            filetypes=[("CSV del modo evento", "*.csv *.csv.gz"), ("Todos", "*.*")])
        for ruta in rutas:
            self.agregar_ruta(Path(ruta))

    def _agregar_carpeta(self):
        ruta = filedialog.askdirectory(title="Elegí una carpeta con ventanas_*.csv")
        if ruta:
            self.agregar_ruta(Path(ruta))

    def agregar_ruta(self, ruta: Path):
        if ruta.is_dir():
            nuevos = [p for p in ruta.iterdir() if _es_csv(p)]
        elif ruta.is_file():
            nuevos = [ruta]
        else:
            messagebox.showwarning("No encontrado", str(ruta))
            return
        if not nuevos:
            messagebox.showinfo("Sin CSV", f"No hay ventanas_*.csv en {ruta}")
            return
        for f in nuevos:
            if f not in self.archivos:
                self.archivos.append(f)
        self.archivos.sort(key=lambda p: p.name)
        self.listbox.delete(0, "end")
        for f in self.archivos:
            self.listbox.insert("end", f.name)

    def _seleccionar_todo(self):
        self.listbox.select_set(0, "end")
        self._al_elegir(None)

    def _vaciar(self):
        self.archivos, self.cache = [], {}
        self.listbox.delete(0, "end")
        self._escribir_info("")
        self._mensaje("Lista vacía.")

    # --- datos ---

    def _seleccion(self):
        return [self.archivos[i] for i in self.listbox.curselection()]

    def _cargar(self, rutas):
        partes, errores = [], []
        for n, ruta in enumerate(rutas, 1):
            if ruta not in self.cache:
                self._escribir_info(f"Cargando {n}/{len(rutas)}:\n{ruta.name}")
                self.root.update()
                try:
                    self.cache[ruta] = cargar_hora(ruta)
                except Exception as exc:  # un CSV roto no tapa a los demas
                    errores.append(f"{ruta.name}: {exc}")
                    continue
            partes.append(self.cache[ruta])
        if errores:
            messagebox.showwarning("Algunos archivos no se pudieron leer", "\n".join(errores))
        if not partes:
            return None
        t = np.concatenate([p["t"] for p in partes])
        orden = np.argsort(t, kind="stable")
        return {
            "t": t[orden],
            "area": np.concatenate([p["area"] for p in partes])[orden],
            "kurt": np.concatenate([p["kurt"] for p in partes])[orden],
            "saltadas": sum(p["saltadas"] for p in partes),
            "tramos": sum(p["tramos"] for p in partes),
            "horas": len(partes),
        }

    # --- graficado ---

    def _al_elegir(self, _event):
        self._redibujar()

    def _redibujar(self):
        rutas = self._seleccion()
        if not rutas:
            return
        self.root.config(cursor="watch")
        self.root.update()
        try:
            datos = self._cargar(rutas)
            if datos is not None and len(datos["t"]):
                self._graficar(datos)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
        finally:
            self.root.config(cursor="")

    def _limpiar_grafico(self):
        for w in self.der.winfo_children():
            w.destroy()
        if self._fig is not None:
            plt.close(self._fig)
        self._fig = self._canvas = self._toolbar = self._vista = None

    def _mensaje(self, texto):
        self._limpiar_grafico()
        tk.Label(self.der, text=texto, justify="left", font=("TkDefaultFont", 11)).pack(expand=True)

    def _graficar(self, d):
        tz = ZONAS[self.zona.get()]
        t, area, kurt = d["t"], d["area"], d["kurt"]
        sobre = kurt >= UMBRAL_KURT
        i_max = int(np.nanargmax(kurt))

        def hora(x, fmt="%d/%m %H:%M:%S"):
            return mdates.num2date(x, tz=tz).strftime(fmt)

        self._limpiar_grafico()
        fig, (ax_area, ax_kurt) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True)
        self._fig = fig
        self._vista = VistaReducida(ax_area, ax_kurt, t, area, kurt, VENTANA_S / DIA_S)
        ax_area.set_ylabel("Área")
        ax_area.set_title(f"{hora(t[0])} a {hora(t[-1])} ({self.zona.get()})")
        ax_kurt.axhline(UMBRAL_KURT, linestyle="--", linewidth=0.8, color="gray")
        ax_kurt.set_ylim(min(0, np.nanmin(kurt)), max(np.nanmax(kurt), UMBRAL_KURT) * 1.05)
        ax_kurt.set_ylabel("Kurtosis")
        localizador = mdates.AutoDateLocator(tz=tz)
        ax_kurt.xaxis.set_major_locator(localizador)
        ax_kurt.xaxis.set_major_formatter(mdates.ConciseDateFormatter(localizador, tz=tz))
        ax_kurt.text(0.01, 0.97,
                     f"{int(sobre.sum())} ventanas ≥ {UMBRAL_KURT:g} de {len(kurt)}   "
                     f"kurtosis máx {kurt[i_max]:.2f} ({hora(t[i_max], '%d/%m %H:%M:%S')})",
                     transform=ax_kurt.transAxes, va="top", fontsize=9)
        fig.tight_layout()

        self._canvas = FigureCanvasTkAgg(fig, master=self.der)
        self._canvas.draw()
        self._toolbar = NavigationToolbar2Tk(self._canvas, self.der)
        self._toolbar.pack(side="bottom", fill="x")
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

        lineas = [
            f"Horas cargadas : {d['horas']}",
            f"Ventanas       : {len(kurt)}",
            f"Saltadas       : {d['saltadas']}",
            f"Tramos         : {d['tramos']}",
            f"Área mediana   : {np.nanmedian(area):.4f}",
            f"Área máx       : {np.nanmax(area):.4f}",
            f"Kurt mediana   : {np.nanmedian(kurt):.3f}",
            f"Ventanas ≥ {UMBRAL_KURT:g}  : {int(sobre.sum())}",
            "",
            f"Ventanas ≥ {UMBRAL_KURT:g} ({self.zona.get()}):",
        ]
        idx = np.nonzero(sobre)[0]
        for i in idx[:MAX_EVENTOS_LISTA]:
            lineas.append(f"  {hora(t[i], '%d/%m %H:%M:%S.%f')[:-4]}  k={kurt[i]:7.2f}")
        if len(idx) > MAX_EVENTOS_LISTA:
            lineas.append(f"  ... y {len(idx) - MAX_EVENTOS_LISTA} más")
        self._escribir_info("\n".join(lineas))

    def _escribir_info(self, texto):
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", texto)
        self.info.config(state="disabled")


def main():
    root = TkinterDnD.Tk() if _CON_DND else tk.Tk()
    visor = VisorCSV(root)
    for arg in sys.argv[1:]:
        visor.agregar_ruta(Path(arg))
    # quit() antes de destroy(): ver ver_paquete.py (callback de Tk pendiente al cerrar)
    root.protocol("WM_DELETE_WINDOW", lambda: (root.quit(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
