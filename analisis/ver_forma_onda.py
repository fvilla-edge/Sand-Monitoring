#!/usr/bin/env python3
"""
ver_forma_onda.py — Visor de la señal cruda en el tiempo (sin métricas) de
una captura de campo. Punto 1 de la propuesta de "estudiar la señal en
crudo": una vista general del archivo completo (envolvente min/max, porque
un chunk tiene millones de muestras y no entra pintado punto a punto) más
una vista de resolución completa de la ventana que se seleccione
arrastrando sobre la vista general. Cada canal real se muestra tal cual se
capturó y, debajo, con un pasabanda 25kHz-400kHz aplicado (descarta ruido
de fluido por abajo y frecuencias sin interés por arriba).

No reimplementa la lectura del formato .bin — usa _leer_canales_bin y
_cargar_info de revisar.py (misma fuente de verdad que revisar.py y
timeline_lote.py).

Uso: doble-click en abrir_forma_onda.sh (mismo directorio), o:
  .venv/bin/python3 analisis/ver_forma_onda.py
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import SpanSelector
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _leer_canales_bin, _cargar_info, V_REF  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _CON_DND = True
except ImportError:
    _CON_DND = False

N_BINS_OVERVIEW = 2000       # columnas de la envolvente de vista general
MAX_MUESTRAS_CRUDAS = 200_000  # por encima de esto, la ventana de zoom tambien se decima

# Banda de interes para arena: <25kHz es ruido de fluido, >400kHz no aporta
# (fuera del rango de interes del sensor). Pasabanda Butterworth zero-phase.
FILTRO_BANDA_HZ = (25_000, 400_000)
FILTRO_ORDEN = 4


def _filtrar_pasabanda(volts, fs, banda=FILTRO_BANDA_HZ, orden=FILTRO_ORDEN):
    nyq = fs / 2
    sos = butter(orden, [banda[0] / nyq, banda[1] / nyq], btype="bandpass", output="sos")
    return sosfiltfilt(sos, volts).astype(np.float32)


def _envolvente(x, n_bins):
    """(t_centro, minimos, maximos) por bloque de x, o (t, x, x) si x ya es chico."""
    n = len(x)
    if n <= n_bins * 2:
        return np.arange(n), x, x
    bin_size = n // n_bins
    recortado = x[: bin_size * n_bins].reshape(n_bins, bin_size)
    return (
        np.arange(n_bins) * bin_size + bin_size / 2,
        recortado.min(axis=1),
        recortado.max(axis=1),
    )


class VisorFormaOnda:
    def __init__(self, root):
        self.root = root
        root.title("Forma de onda — señal cruda en el tiempo")
        root.geometry("1150x800")

        self.archivos = []      # lista de Path, en el orden agregado
        self.canales_cache = {}  # Path -> (ch0, ch1, fs, meta, info)
        self.canales_graf_cache = {}  # Path -> lista [(nombre, volts), ...] (incluye filtrados, cacheado por costo del filtro)

        marco_izq = tk.Frame(root, width=260)
        marco_izq.pack(side="left", fill="y", padx=6, pady=6)
        marco_izq.pack_propagate(False)

        tk.Label(marco_izq, text="Carpetas/archivos (arrastrá acá o usá el botón):").pack(anchor="w")
        self.listbox = tk.Listbox(marco_izq, height=25)
        self.listbox.pack(fill="both", expand=True, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._al_elegir)

        if _CON_DND:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._al_soltar)

        marco_botones = tk.Frame(marco_izq)
        marco_botones.pack(fill="x")
        tk.Button(marco_botones, text="Agregar carpeta...", command=self._agregar_carpeta).pack(fill="x")
        tk.Button(marco_botones, text="Quitar seleccionada(s)", command=self._quitar_seleccionadas).pack(fill="x", pady=(4, 0))
        tk.Button(marco_botones, text="Vaciar lista", command=self._vaciar).pack(fill="x", pady=(4, 0))

        self.info_label = tk.Label(marco_izq, text="", justify="left", anchor="w", font=("monospace", 8))
        self.info_label.pack(fill="x", pady=(8, 0))

        marco_der = tk.Frame(root)
        marco_der.pack(side="right", fill="both", expand=True, padx=6, pady=6)

        # Una pestaña por canal (cruda y filtrada) — cada una con su propia
        # figura de solo 2 filas (vista general + zoom), asi ocupan todo el
        # espacio disponible en vez de amontonarse todas apiladas en una sola
        # figura cada vez mas chica a medida que hay mas canales (dual triplica
        # a 6 canales: IN1, IN2, Limpia, cada uno con su version filtrada).
        self.notebook = ttk.Notebook(marco_der)
        self.notebook.pack(fill="both", expand=True)
        self._tabs = []  # lista de dicts (frame/fig/canvas/span) del archivo actual, para no perder referencias vivas (GC) y para poder destruirlas al graficar otro archivo

        if not _CON_DND:
            self.info_label.config(text="[!] Arrastrar y soltar no disponible\n(falta tkinterdnd2)")

    # --- manejo de la lista ---

    def _al_soltar(self, event):
        for ruta in self.root.tk.splitlist(event.data):
            self._agregar_ruta(Path(ruta))

    def _agregar_carpeta(self):
        ruta = filedialog.askdirectory(title="Elegí una carpeta de captura")
        if ruta:
            self._agregar_ruta(Path(ruta))

    def _agregar_ruta(self, ruta: Path):
        if ruta.is_dir():
            nuevos = sorted(ruta.glob("campo_*.bin"))
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
            self.canales_cache.pop(ruta, None)
            self.canales_graf_cache.pop(ruta, None)
            self.listbox.delete(i)

    def _vaciar(self):
        self.archivos = []
        self.canales_cache = {}
        self.canales_graf_cache = {}
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
        if ruta in self.canales_cache:
            return self.canales_cache[ruta]
        info = _cargar_info(ruta)
        ch0, ch1, meta = _leer_canales_bin(ruta)
        dual = int(info.get("canales", 1)) == 2
        fs = float(info["fs_hz_por_canal"]) if dual else float(info["fs_hz"])
        resultado = (ch0, ch1 if dual else None, fs, meta, info)
        self.canales_cache[ruta] = resultado
        return resultado

    def _limpiar_tabs(self):
        for tab in self._tabs:
            self.notebook.forget(tab["frame"])
            plt.close(tab["fig"])
            tab["frame"].destroy()
        self._tabs = []

    def _construir_canales(self, ruta: Path):
        """Lista [(nombre, volts_ndarray), ...]: cada canal real seguido de su
        version filtrada (pasabanda 25kHz-400kHz). Cacheada por archivo porque
        filtrar (sosfiltfilt sobre millones de muestras) tarda ~1-2s por canal."""
        if ruta in self.canales_graf_cache:
            return self.canales_graf_cache[ruta]
        ch0, ch1, fs, meta, info = self._cargar(ruta)
        dual = ch1 is not None

        ch0_v = ch0.astype(np.float32) / 32767.0 * V_REF
        canales = [("IN1", ch0_v), ("IN1 filtrado (25-400kHz)", _filtrar_pasabanda(ch0_v, fs))]
        if dual:
            ch1_v = ch1.astype(np.float32) / 32767.0 * V_REF
            canales += [("IN2", ch1_v), ("IN2 filtrado (25-400kHz)", _filtrar_pasabanda(ch1_v, fs))]
            # IN1 y IN2 SI estan sincronizados (mismo reloj, misma captura) —
            # a diferencia del caso mono, acá restar en el tiempo es valido:
            # restar directamente en Volts (ya son lineales) es lo mismo que
            # restar los int16 y convertir despues.
            limpia_v = ch0_v - ch1_v
            canales += [("Limpia (IN1-IN2)", limpia_v), ("Limpia filtrado (25-400kHz)", _filtrar_pasabanda(limpia_v, fs))]

        self.canales_graf_cache[ruta] = canales
        return canales

    def _graficar(self, ruta: Path):
        ch0, ch1, fs, meta, info = self._cargar(ruta)
        canales = self._construir_canales(ruta)

        self._limpiar_tabs()
        for nombre, volts in canales:
            self._crear_tab(nombre, volts, fs)
        if self._tabs:
            self.notebook.select(0)

        dec = info.get("decimacion")
        cond = info.get("condicion")
        fecha = info.get("fecha_inicio", "")
        self.info_label.config(
            text=(f"{ruta.name}\ncondicion: {cond}\ndecimacion: {dec}\n"
                  f"fs: {fs/1e6:.4f} MHz\ninicio: {fecha}\n"
                  + (f"lost0: {meta.get('lost0', 'N/A')}\nlost1: {meta.get('lost1', 'N/A')}" if meta else "sin metadata de header"))
        )

    def _crear_tab(self, nombre, volts, fs):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        # Sin sharex entre vista general y zoom: son rangos de tiempo
        # distintos (todo el archivo vs. la ventana arrastrada) — compartir
        # el eje hacia que al graficar el zoom, matplotlib reescalara TAMBIEN
        # la vista general al rango angosto (bug ya presente antes de las
        # pestañas, confirmado con overview.get_xlim() cambiando tras zoom).
        ax_overview, ax_zoom = fig.subplots(2, 1)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()

        t, ymin, ymax = _envolvente(volts, N_BINS_OVERVIEW)
        t_s = t / fs
        ax_overview.fill_between(t_s, ymin, ymax, linewidth=0, color="#2a78d6")
        ax_overview.set_ylabel(f"{nombre} (V)")
        ax_overview.set_title(f"{nombre} — vista general (envolvente, {len(volts):,} muestras)")
        ax_overview.set_xlabel("tiempo (s) desde el inicio del archivo")

        ax_zoom.set_ylabel(f"{nombre} zoom (V)")
        ax_zoom.text(0.5, 0.5, "Arrastrá sobre la vista general de arriba\npara ver esta ventana en detalle",
                     ha="center", va="center", transform=ax_zoom.transAxes, color="gray")
        ax_zoom.set_xlabel("tiempo (s)")

        def _al_seleccionar(xmin, xmax):
            try:
                self._dibujar_zoom(ax_zoom, volts, fs, xmin, xmax, nombre)
            except Exception:
                import traceback
                messagebox.showerror("Error al graficar el zoom", traceback.format_exc())
                print(traceback.format_exc(), file=sys.stderr)
                return
            canvas.draw_idle()

        span = SpanSelector(
            ax_overview, _al_seleccionar, "horizontal",
            useblit=True, props=dict(alpha=0.3, facecolor="orange"),
            interactive=True, drag_from_anywhere=True,
        )

        prensado = {"val": None}

        def _on_press(event):
            prensado["val"] = (event.x, event.y, event.inaxes, event.xdata)

        def _on_release(event):
            """Respaldo de SpanSelector: si el usuario solo hizo click (sin
            arrastre real), SpanSelector no llama a onselect y no pasa nada —
            acá se detecta ese caso (distancia en pixeles chica) y se abre
            una ventana de 1s centrada en el click, en vez de dejarlo sin
            efecto."""
            if prensado["val"] is None:
                return
            x0, y0, ax0, xdata0 = prensado["val"]
            prensado["val"] = None
            if ax0 is not ax_overview or event.xdata is None:
                return
            distancia_px = ((event.x - x0) ** 2 + (event.y - y0) ** 2) ** 0.5
            if distancia_px > 3:
                return  # fue un arrastre real, ya lo maneja el SpanSelector
            _al_seleccionar(xdata0, xdata0)

        canvas.mpl_connect("button_press_event", _on_press)
        canvas.mpl_connect("button_release_event", _on_release)
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas, "span": span})

    def _dibujar_zoom(self, ax, volts, fs, t0, t1, nombre):
        VENTANA_MIN_S = 0.05  # si el "arrastre" fue casi un click, usar esta ventana centrada en t0
        if (t1 - t0) < 0.02:
            centro = t0
            t0, t1 = centro - VENTANA_MIN_S / 2, centro + VENTANA_MIN_S / 2
        i0 = max(0, int(t0 * fs))
        i1 = min(len(volts), int(t1 * fs))
        if i1 <= i0:
            return
        recorte = volts[i0:i1]
        n = len(recorte)
        ax.clear()
        titulo_extra = ""
        if n > MAX_MUESTRAS_CRUDAS:
            t, ymin, ymax = _envolvente(recorte, N_BINS_OVERVIEW)
            ax.fill_between((t + i0) / fs, ymin, ymax, linewidth=0, color="#1baf7a")
            titulo_extra = " (decimado, todavia es mucho para ver crudo)"
        else:
            t = (np.arange(i0, i1)) / fs
            ax.plot(t, recorte, linewidth=0.6, color="#1baf7a")
        ax.set_title(f"{nombre} zoom — {n:,} muestras{titulo_extra}")
        ax.set_ylabel(f"{nombre} zoom (V)")


def main():
    root = TkinterDnD.Tk() if _CON_DND else tk.Tk()
    VisorFormaOnda(root)
    root.mainloop()


if __name__ == "__main__":
    main()
