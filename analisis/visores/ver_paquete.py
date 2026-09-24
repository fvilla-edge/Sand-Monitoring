#!/usr/bin/env python3
"""
ver_paquete.py — Visor interactivo (estilo ver_forma_onda.py) de uno o mas
.paquete.json (formato de exportar_paquete_area.py/exportar_paquete_area_c.py):
area+kurtosis por ventana, una pestaña por canal, sin generar ningun archivo
de salida. No necesita el .bin crudo — el paquete no lo tiene, solo area y
kurtosis agregados por ventana.

Uso: doble-click en abrir_paquete.sh (mismo directorio), o:
  .venv/bin/python3 analisis/placa/ver_paquete.py
"""
import sys
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

sys.path.insert(0, str(Path(__file__).parent.parent))  # analisis/ (revisar.py)
from revisar import FA_THRESH  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _CON_DND = True
except ImportError:
    _CON_DND = False


def _cortar_en_huecos(t, *series, ventana_s):
    """Inserta NaN donde falta al menos una ventana (saltadas, o entre tramos
    de corridas distintas del registro continuo), para que la linea no una
    los dos lados del hueco."""
    t = np.asarray(t, dtype=float)
    series = [np.asarray(v, dtype=float) for v in series]
    if len(t) < 2:
        return (t, *series)
    cortes = np.nonzero(np.diff(t) > 1.5 * ventana_s)[0] + 1
    t = np.insert(t, cortes, np.nan)
    return (t, *[np.insert(v, cortes, np.nan) for v in series])


class _VistaReducida:
    """Dibuja area (escalon relleno) y kurtosis reduciendo a lo sumo MAX_PUNTOS
    grupos por vista: cada grupo muestra el MAXIMO de sus ventanas (un pico de
    arena de una sola ventana no desaparece al alejar). Al hacer zoom/pan se
    recalcula solo el tramo visible — un dia entero (1.7M ventanas) sin
    reducir tardaba ~7s por redibujo."""
    MAX_PUNTOS = 4000

    def __init__(self, ax_area, ax_kurt, t, area, kurt, ventana_s):
        orden = np.argsort(t)
        self.t = np.asarray(t, dtype=float)[orden]
        self.area = np.asarray(area, dtype=float)[orden]
        self.kurt = np.asarray(kurt, dtype=float)[orden]
        self.ventana_s = ventana_s
        self.ax_area, self.ax_kurt = ax_area, ax_kurt
        self.relleno = None
        (self.linea,) = ax_kurt.plot([], [], linewidth=0.8)
        self._actualizar(self.t[0] - ventana_s, self.t[-1] + ventana_s)
        ax_area.set_xlim(self.t[0] - ventana_s, self.t[-1] + ventana_s)
        ax_area.set_ylim(0, np.nanmax(self.area) * 1.05)
        ax_kurt.set_ylim(min(0, np.nanmin(self.kurt)), np.nanmax(self.kurt) * 1.05)
        ax_area.callbacks.connect("xlim_changed", lambda ax: self._actualizar(*ax.get_xlim()))

    def _actualizar(self, x0, x1):
        i0 = max(0, np.searchsorted(self.t, x0) - 1)
        i1 = min(len(self.t), np.searchsorted(self.t, x1) + 1)
        t, a, k = self.t[i0:i1], self.area[i0:i1], self.kurt[i0:i1]
        paso = max(1, int(np.ceil(len(t) / self.MAX_PUNTOS)))
        if paso > 1:
            ini = np.arange(0, len(t), paso)  # el ultimo grupo puede quedar incompleto
            hueco = np.diff(t, prepend=t[0]) > 1.5 * self.ventana_s
            tg = np.add.reduceat(t, ini) / np.diff(np.append(ini, len(t)))
            hg = np.logical_or.reduceat(hueco, ini)
            a = np.maximum.reduceat(a, ini)
            k = np.maximum.reduceat(k, ini)
            cortes = np.nonzero(hg)[0]  # la linea se corta antes de cada grupo con un hueco adentro
            t_c, a_c, k_c = (np.insert(v, cortes, np.nan) for v in (tg, a, k))
        else:
            t_c, a_c, k_c = _cortar_en_huecos(t, a, k, ventana_s=self.ventana_s)
        if self.relleno is not None:
            self.relleno.remove()
        self.relleno = self.ax_area.fill_between(t_c, a_c, step="mid", color="#2a78d6", linewidth=0)
        self.linea.set_data(t_c, k_c)


class VisorPaquete:
    def __init__(self, root):
        self.root = root
        root.title("Paquete liviano — área/kurtosis por ventana")
        root.geometry("1150x800")

        self.archivos = []       # lista de Path, en el orden agregado
        self.paquete_cache = {}  # Path -> dict ya parseado del json

        marco_izq = tk.Frame(root, width=260)
        marco_izq.pack(side="left", fill="y", padx=6, pady=6)
        marco_izq.pack_propagate(False)

        tk.Label(marco_izq, text="Paquetes (arrastrá acá o usá los botones):").pack(anchor="w")
        self.listbox = tk.Listbox(marco_izq, height=25)
        self.listbox.pack(fill="both", expand=True, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._al_elegir)

        if _CON_DND:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._al_soltar)

        marco_botones = tk.Frame(marco_izq)
        marco_botones.pack(fill="x")
        tk.Button(marco_botones, text="Agregar archivo(s)...", command=self._agregar_archivos).pack(fill="x")
        tk.Button(marco_botones, text="Agregar carpeta...", command=self._agregar_carpeta).pack(fill="x", pady=(4, 0))
        tk.Button(marco_botones, text="Quitar seleccionada(s)", command=self._quitar_seleccionadas).pack(fill="x", pady=(4, 0))
        tk.Button(marco_botones, text="Vaciar lista", command=self._vaciar).pack(fill="x", pady=(4, 0))

        self.info_label = tk.Label(marco_izq, text="", justify="left", anchor="w", font=("monospace", 8))
        self.info_label.pack(fill="x", pady=(8, 0))
        if not _CON_DND:
            self.info_label.config(text="[!] Arrastrar y soltar no disponible\n(falta tkinterdnd2)")

        marco_der = tk.Frame(root)
        marco_der.pack(side="right", fill="both", expand=True, padx=6, pady=6)

        self.notebook = ttk.Notebook(marco_der)
        self.notebook.pack(fill="both", expand=True)
        self._tabs = []  # lista de dicts (frame/fig/canvas) del archivo actual, para no perder referencias vivas (GC)

    # --- manejo de la lista ---

    def _al_soltar(self, event):
        for ruta in self.root.tk.splitlist(event.data):
            self._agregar_ruta(Path(ruta))

    def _agregar_archivos(self):
        rutas = filedialog.askopenfilenames(title="Elegí uno o más .paquete.json",
                                             filetypes=[("Paquete liviano", "*.paquete.json")])
        for ruta in rutas:
            self._agregar_ruta(Path(ruta))

    def _agregar_carpeta(self):
        ruta = filedialog.askdirectory(title="Elegí una carpeta con .paquete.json")
        if ruta:
            self._agregar_ruta(Path(ruta))

    def _agregar_ruta(self, ruta: Path):
        if ruta.is_dir():
            nuevos = sorted(ruta.glob("*.paquete.json"))
        elif ruta.is_file():
            nuevos = [ruta]
        else:
            messagebox.showwarning("No encontrado", str(ruta))
            return
        for f in nuevos:
            if f not in self.archivos:
                self.archivos.append(f)
                self.listbox.insert("end", f.name)

    def _quitar_seleccionadas(self):
        for i in reversed(self.listbox.curselection()):
            ruta = self.archivos.pop(i)
            self.paquete_cache.pop(ruta, None)
            self.listbox.delete(i)

    def _vaciar(self):
        self.archivos = []
        self.paquete_cache = {}
        self.listbox.delete(0, "end")
        self._limpiar_tabs()

    # --- graficado ---

    def _al_elegir(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        ruta = self.archivos[sel[0]]
        self.root.config(cursor="watch")
        self.root.update()
        try:
            self._graficar(ruta)
        except Exception as exc:
            messagebox.showerror("Error leyendo archivo", f"{ruta.name}:\n{exc}")
        finally:
            self.root.config(cursor="")

    def _cargar(self, ruta: Path):
        if ruta in self.paquete_cache:
            return self.paquete_cache[ruta]
        with open(ruta) as f:
            paquete = json.load(f)
        self.paquete_cache[ruta] = paquete
        return paquete

    def _limpiar_tabs(self):
        for tab in self._tabs:
            self.notebook.forget(tab["frame"])
            plt.close(tab["fig"])
            tab["frame"].destroy()
        self._tabs = []

    def _graficar(self, ruta: Path):
        paquete = self._cargar(ruta)
        self._limpiar_tabs()

        info_txt = f"{ruta.name}\nfs={paquete['fs_hz']:.0f}Hz  ventana={paquete['ventana_s']*1000:.0f}ms"
        self.info_label.config(text=info_txt)

        for canal in paquete["canales"]:
            t, area, kurt = canal["t_centro_s"], canal["area"], canal["kurtosis"]
            n_sobre_umbral = sum(1 for k in kurt if k >= FA_THRESH)

            frame = tk.Frame(self.notebook)
            self.notebook.add(frame, text=canal["canal"])

            fig, (ax_area, ax_kurt) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
            # escalon relleno en vez de ax.bar: una barra por ventana (72000 por
            # hora en el registro continuo) tardaba ~25s en abrir y ~4s por zoom
            vista = _VistaReducida(ax_area, ax_kurt, t, area, kurt, paquete["ventana_s"])
            ax_area.set_ylabel("Área")
            ax_area.set_title(canal["canal"])

            ax_kurt.axhline(FA_THRESH, linestyle="--", linewidth=0.8, color="gray")
            ax_kurt.set_ylabel("Kurtosis")
            ax_kurt.set_xlabel(f"t (s) desde {paquete['inicio_utc']}" if "inicio_utc" in paquete else "t (s)")
            ax_kurt.text(0.02, 0.95, f"{n_sobre_umbral}/{len(kurt)} ventanas ≥ {FA_THRESH}",
                         transform=ax_kurt.transAxes, va="top", fontsize=8)
            fig.tight_layout()

            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            NavigationToolbar2Tk(canvas, frame).pack(side="bottom", fill="x")
            canvas.get_tk_widget().pack(fill="both", expand=True)

            self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas, "vista": vista})


def main():
    root = TkinterDnD.Tk() if _CON_DND else tk.Tk()
    VisorPaquete(root)
    # root.quit() antes de destroy(): al cerrar con la X, un autoscan
    # pendiente del listbox (tk::ListboxAutoScan, programado por Tk con
    # `after` al arrastrar cerca del borde) puede dispararse DESPUES de
    # destruir la ventana y tirar "application has been destroyed" sin
    # terminar el proceso -- quit() corta el mainloop de una antes de que
    # ese callback llegue a ejecutarse.
    root.protocol("WM_DELETE_WINDOW", lambda: (root.quit(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
