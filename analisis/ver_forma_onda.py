#!/usr/bin/env python3
"""
ver_forma_onda.py — Visor de la señal cruda en el tiempo (sin métricas) de
una captura de campo. Punto 1 de la propuesta de "estudiar la señal en
crudo": una vista general del archivo completo (envolvente min/max, porque
un chunk tiene millones de muestras y no entra pintado punto a punto) más
una vista de resolución completa de la ventana que se seleccione
arrastrando sobre la vista general. Cada canal real tiene su propia pestaña
tal cual se capturó, más una pestaña con un pasabanda 25kHz-400kHz aplicado
(descarta ruido de fluido por abajo y frecuencias sin interés por arriba) y
una tercera con el RMS de esa señal filtrada (|x|, misma resolución
temporal, siempre positiva en vez de la oscilación +/- original), más dos
pestañas de espectro (Welch, escala log-frecuencia/dB) de la cruda y de la
filtrada (para confirmar que componentes hay y si 25kHz-400kHz son los
cortes correctos), y una pestaña con el área bajo la curva del RMS (suma de
Riemann de la envolvente rectificada) con un combobox para elegir la
ventana (50/100/200/500/1000ms) y recalcular al vuelo — por defecto
AREA_VENTANA_S (50ms, igual a FA_WINDOW_S de revisar.py, para quedar
alineada en el tiempo con la kurtosis/fracción activa de ese mismo
archivo), y una pestaña combinada (señal filtrada arriba, kurtosis por
ventana de AREA_VENTANA_S al medio, RMS diferencial autocalibrado abajo,
mismo eje de tiempo compartido — a diferencia de overview/zoom, acá SI
tiene sentido porque las tres cubren el archivo completo). Kurtosis
calculada sobre el filtrado de 25-400kHz de este visor, NO la banda de
100-450kHz de revisar.py — el número no es directamente comparable con los
umbrales ~3 reposo / >20 arena de ese script. Un slider de umbral de
kurtosis clasifica cada ventana como "señal" o "fondo"; el RMS diferencial
usa la mediana del RMS de las ventanas de FONDO del propio archivo como
baseline (misma formula que rms_diferencial de revisar.py,
sqrt(max(0,rms²-b²))/b, pero autocalibrado por archivo en vez de depender
de una carpeta "reposo" externa — comparar contra el RMS de una sesión de
otro día no tiene sentido, varía por causas ajenas a la arena). Defaults de
los sliders (kurtosis=6, rd=0.5, ambos en KURT_FIJO_ACUMULADO para la
pestaña "Acumulado" y el mismo valor a mano acá) calibrados contra el lote
datos_campo/42_1_reposo_20260903_1*_mono_dec32 (purga de 8kg confirmada por
planilla BPE-2421 a las 14:00 UTC = 11:00 ART) CON la banda real de este
visor (25-400kHz, no la de revisar.py — un primer calibrado se hizo con la
banda equivocada y quedo corregido despues): con baseline autocalibrado,
kurtosis>6 aisla ~5.9% de ventanas como evento sobre un fondo muy estable
(~3.0, gaussiano; el baseline autocalibrado da ~5.99mV pase lo que pase
entre umbral 5 y 10, no es sensible a ese numero); rd es más ruidoso
(turbulencia de fluido eleva rd>0.1 en ~40% de las ventanas sin ser arena),
pero con kurtosis=6 el 99% de lo que kurtosis marca ya supera rd>0.5 sin
filtrar eventos reales.

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
from scipy.signal import butter, sosfiltfilt, welch

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _leer_canales_bin, _cargar_info, V_REF, FA_WINDOW_S  # noqa: E402

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

# Tamaño de ventana de Welch para el espectro: buen compromiso entre
# resolucion en frecuencia (~60Hz con fs~3.9MHz) y tiempo de calculo
# (~3s por canal en un archivo de ~112M muestras).
FFT_NPERSEG = 65536

# Umbral de kurtosis para el acumulado de área (pestaña "Acumulado"): fijo
# por ahora a pedido del usuario, no un slider — arrancamos con un solo
# archivo para ver como se comporta antes de pensar en hacerlo configurable
# o en pegar varios archivos como timeline_lote.py.
KURT_FIJO_ACUMULADO = 6.0


def _filtrar_pasabanda(volts, fs, banda=FILTRO_BANDA_HZ, orden=FILTRO_ORDEN):
    nyq = fs / 2
    sos = butter(orden, [banda[0] / nyq, banda[1] / nyq], btype="bandpass", output="sos")
    return sosfiltfilt(sos, volts).astype(np.float32)


def _rms_muestra_a_muestra(volts):
    """RMS con ventana de 1 muestra (sqrt(x^2) = |x|): la señal completa,
    misma resolucion temporal que la original, pero siempre >= 0."""
    return np.abs(volts)


# Mismo tamaño de ventana que fraccion_activa/kurtosis en revisar.py y
# timeline_lote.py, para que esta curva de area quede alineada en el tiempo
# con esas metricas del mismo archivo (50ms daba mas granularidad que 1s
# para no diluir impactos cortos de arena entre si).
AREA_VENTANA_S = FA_WINDOW_S


def _area_por_ventana(rms, fs, ventana_s=AREA_VENTANA_S):
    """(t_centro_s, area) del area bajo la curva de rms (ya siempre >= 0)
    en ventanas de ventana_s no superpuestas — suma de Riemann (rectangular,
    area_i = sum(muestras de la ventana) * dt) por ventana."""
    n_ventana = max(1, int(fs * ventana_s))
    n_total = len(rms) // n_ventana
    if n_total == 0:
        return np.array([]), np.array([], dtype=np.float32)
    mat = rms[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)
    area = (mat.sum(axis=1) / fs).astype(np.float32)
    t = (np.arange(n_total) + 0.5) * ventana_s
    return t, area


def _kurtosis_por_ventana(volts, fs, ventana_s=AREA_VENTANA_S):
    """(t_centro_s, kurtosis) en ventanas de ventana_s no superpuestas —
    mismo criterio y formula que _metricas_por_ventana de timeline_lote.py
    (y el calculo de kurtosis de revisar.py): dentro de cada ventana se le
    resta la media, y kurt = m4/m2^2 con m2=E[(x-x̄)^2], m4=E[(x-x̄)^4]. Para
    ruido gaussiano da ~3; picos aislados grandes (impactos) la disparan
    mucho mas arriba porque m4 pesa los valores extremos a la 4ta potencia."""
    n_ventana = max(1, int(fs * ventana_s))
    n_total = len(volts) // n_ventana
    if n_total == 0:
        return np.array([]), np.array([], dtype=np.float32)
    mat = volts[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)
    mat = mat - mat.mean(axis=1, keepdims=True)
    m2 = np.mean(mat ** 2, axis=1)
    m4 = np.mean(mat ** 4, axis=1)
    kurt = (m4 / np.where(m2 > 0, m2 ** 2, 1e-30)).astype(np.float32)
    t = (np.arange(n_total) + 0.5) * ventana_s
    return t, kurt


def _rms_por_ventana_directo(volts, fs, ventana_s=AREA_VENTANA_S):
    """(t_centro_s, rms) en ventanas de ventana_s no superpuestas — RMS
    verdadero (sqrt(mean(x^2))) de la señal filtrada, mismo criterio de
    ventana que _kurtosis_por_ventana (mismo t_centro_s resultante) — base
    para el baseline de fondo del RMS diferencial (ver _crear_tab_combinado):
    NO es lo mismo que el area bajo |x| de _area_por_ventana."""
    n_ventana = max(1, int(fs * ventana_s))
    n_total = len(volts) // n_ventana
    if n_total == 0:
        return np.array([]), np.array([], dtype=np.float32)
    mat = volts[: n_total * n_ventana].reshape(n_total, n_ventana).astype(np.float64)
    rms = np.sqrt(np.mean(mat ** 2, axis=1)).astype(np.float32)
    t = (np.arange(n_total) + 0.5) * ventana_s
    return t, rms


def _calcular_espectro(volts, fs, nperseg=FFT_NPERSEG):
    """(freqs, psd_db) via Welch (promedia varios segmentos con overlap —
    mas robusto que una FFT unica sobre millones de muestras, y evita tener
    que guardar un array complejo del tamaño del archivo)."""
    n = min(nperseg, len(volts))
    freqs, psd = welch(volts, fs=fs, nperseg=n)
    psd_db = 10 * np.log10(psd + 1e-20)
    return freqs, psd_db


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
        self.canales_graf_cache = {}  # Path -> lista [(nombre, volts, fs), ...] (incluye filtrados y RMS, cacheado por costo del filtro)

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

    def _crear_crosshair_en_ax(self, ax):
        vline = ax.axvline(color="#888888", linewidth=0.6, linestyle="--", visible=False)
        hline = ax.axhline(color="#888888", linewidth=0.6, linestyle="--", visible=False)
        texto = ax.text(
            0.02, 0.98, "", transform=ax.transAxes, va="top", ha="left", fontsize=8,
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="#888888", alpha=0.85),
            visible=False,
        )
        return vline, hline, texto

    def _registrar_crosshair(self, estado, ax):
        """(Re)crea los artistas de la cruz en ax y los agrega/reemplaza en
        estado — se usa tanto en _agregar_crosshair como despues de un
        ax.clear() (el clear borra los artistas viejos, quedan huerfanos)."""
        vline, hline, texto = self._crear_crosshair_en_ax(ax)
        estado[ax] = {"vline": vline, "hline": hline, "texto": texto, "bg": None}

    def _agregar_crosshair(self, canvas, axes):
        """Cruz + lectura numerica de (x,y) bajo el mouse en cada ax, en vez
        de tener que mirar la barra de coordenadas del toolbar (abajo a la
        izquierda, dificil de seguir con el ojo). Usa blitting (redibuja
        SOLO la cruz sobre un fondo cacheado, no la figura entera) — mover
        el mouse forzaba un canvas.draw() completo por evento (~40-90ms con
        tight_layout en estos graficos), y eso era lo que se sentia lento.
        Devuelve {ax: {"vline","hline","texto","bg"}} — ver
        _registrar_crosshair para reemplazar una entrada tras un ax.clear()."""
        estado = {}
        for ax in axes:
            self._registrar_crosshair(estado, ax)

        def _on_draw(event):
            for ax, info in estado.items():
                try:
                    info["bg"] = canvas.copy_from_bbox(ax.bbox)
                except Exception:
                    pass

        def _on_move(event):
            for ax, info in estado.items():
                if info["bg"] is None:
                    continue  # todavia no hubo un draw completo que capturar
                visible = event.inaxes is ax and event.xdata is not None and event.ydata is not None
                if not visible and not info["vline"].get_visible():
                    continue  # ya estaba oculta en este ax, nada que borrar
                canvas.restore_region(info["bg"])
                info["vline"].set_visible(visible)
                info["hline"].set_visible(visible)
                info["texto"].set_visible(visible)
                if visible:
                    info["vline"].set_xdata([event.xdata, event.xdata])
                    info["hline"].set_ydata([event.ydata, event.ydata])
                    info["texto"].set_text(f"x={event.xdata:.4g}\ny={event.ydata:.4g}")
                    ax.draw_artist(info["vline"])
                    ax.draw_artist(info["hline"])
                    ax.draw_artist(info["texto"])
                canvas.blit(ax.bbox)

        canvas.mpl_connect("draw_event", _on_draw)
        canvas.mpl_connect("motion_notify_event", _on_move)
        return estado

    def _limpiar_tabs(self):
        for tab in self._tabs:
            self.notebook.forget(tab["frame"])
            plt.close(tab["fig"])
            tab["frame"].destroy()
        self._tabs = []

    def _construir_canales(self, ruta: Path):
        """{"tiempo": [(nombre, volts_ndarray, fs), ...], "fft": [(nombre,
        freqs, psd_db), ...], "area": [(nombre, rms_ndarray, fs), ...],
        "combinado": [(nombre, filtrado_ndarray, fs, t_s, kurt, rms_w,
        area_vals), ...]}.
        Por cada canal real: crudo, filtrado (pasabanda 25kHz-400kHz), RMS
        del filtrado (|x|, misma resolucion — solo le saca el signo), espectro
        (Welch) del crudo y del filtrado, el RMS de nuevo para el area bajo
        la curva (la pestaña de area recalcula la ventana al vuelo, ver
        _crear_tab_area), y esa señal filtrada + su kurtosis + su RMS
        (directo, sqrt(mean(x^2)), no |x|) por ventana de AREA_VENTANA_S
        juntas para la pestaña combinada (señal, kurtosis y RMS diferencial,
        mismo eje de tiempo — a diferencia de overview/zoom, acá SI tiene
        sentido compartir el eje porque las tres cubren el archivo completo).
        El RMS por ventana es la base del RMS diferencial autocalibrado: el
        umbral de kurtosis de la pestaña combinada clasifica cada ventana
        como fondo o señal, y el baseline sale de la mediana del RMS de las
        ventanas de FONDO del propio archivo (en vez de depender de una
        carpeta "reposo" externa, ver _crear_tab_combinado). Cacheado por
        archivo porque filtrar+Welch sobre millones de muestras tarda unos
        segundos por canal."""
        if ruta in self.canales_graf_cache:
            return self.canales_graf_cache[ruta]
        ch0, ch1, fs, meta, info = self._cargar(ruta)
        dual = ch1 is not None

        tiempo = []
        fft = []
        area = []
        combinado = []

        def _agregar_canal(nombre, volts):
            filtrado = _filtrar_pasabanda(volts, fs)
            rms = _rms_muestra_a_muestra(filtrado)
            tiempo.extend([
                (nombre, volts, fs),
                (f"{nombre} filtrado (25-400kHz)", filtrado, fs),
                (f"{nombre} filtrado — RMS", rms, fs),
            ])
            f_crudo, psd_crudo = _calcular_espectro(volts, fs)
            f_filt, psd_filt = _calcular_espectro(filtrado, fs)
            fft.extend([
                (f"{nombre} — FFT", f_crudo, psd_crudo),
                (f"{nombre} filtrado — FFT", f_filt, psd_filt),
            ])
            area.append((f"{nombre} filtrado — Área", rms, fs))
            t_k, kurt_vals = _kurtosis_por_ventana(filtrado, fs)
            _, rms_w = _rms_por_ventana_directo(filtrado, fs)
            # Misma ventana (AREA_VENTANA_S) y misma fuente (rms muestra a
            # muestra) que la pestaña de área — area_vals[i] es el area de la
            # MISMA ventana que kurt_vals[i] (t_k identico en ambas, ver
            # _area_por_ventana/_kurtosis_por_ventana).
            _, area_vals = _area_por_ventana(rms, fs)
            combinado.append((f"{nombre} filtrado — Señal+Kurtosis", filtrado, fs, t_k, kurt_vals, rms_w, area_vals))

        ch0_v = ch0.astype(np.float32) / 32767.0 * V_REF
        _agregar_canal("IN1", ch0_v)
        if dual:
            ch1_v = ch1.astype(np.float32) / 32767.0 * V_REF
            _agregar_canal("IN2", ch1_v)
            # IN1 y IN2 SI estan sincronizados (mismo reloj, misma captura) —
            # a diferencia del caso mono, acá restar en el tiempo es valido:
            # restar directamente en Volts (ya son lineales) es lo mismo que
            # restar los int16 y convertir despues.
            limpia_v = ch0_v - ch1_v
            _agregar_canal("Limpia (IN1-IN2)", limpia_v)

        resultado = {"tiempo": tiempo, "fft": fft, "area": area, "combinado": combinado}
        self.canales_graf_cache[ruta] = resultado
        return resultado

    def _graficar(self, ruta: Path):
        ch0, ch1, fs, meta, info = self._cargar(ruta)
        canales = self._construir_canales(ruta)

        self._limpiar_tabs()
        for nombre, volts, fs_canal in canales["tiempo"]:
            self._crear_tab(nombre, volts, fs_canal)
        for nombre, freqs, psd_db in canales["fft"]:
            self._crear_tab_fft(nombre, freqs, psd_db)
        for nombre, rms, fs_canal in canales["area"]:
            self._crear_tab_area(nombre, rms, fs_canal)
        for nombre, filtrado, fs_canal, t_k, kurt_vals, rms_w, area_vals in canales["combinado"]:
            self._crear_tab_combinado(nombre, filtrado, fs_canal, t_k, kurt_vals)
            nombre_rd = nombre.replace("Señal+Kurtosis", "RMS diferencial")
            self._crear_tab_rmsdif(nombre_rd, t_k, kurt_vals, rms_w)
            nombre_ac = nombre.replace("Señal+Kurtosis", "Acumulado")
            self._crear_tab_acumulado(nombre_ac, t_k, kurt_vals, area_vals)
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

        crosshair = self._agregar_crosshair(canvas, [ax_overview, ax_zoom])

        def _al_seleccionar(xmin, xmax):
            try:
                self._dibujar_zoom(ax_zoom, volts, fs, xmin, xmax, nombre)
                self._registrar_crosshair(crosshair, ax_zoom)
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

    def _crear_tab_fft(self, nombre, freqs, psd_db):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        ax = fig.subplots(1, 1)
        ax.axvspan(*FILTRO_BANDA_HZ, color="orange", alpha=0.15, label="pasabanda 25-400kHz")
        ax.semilogx(freqs, psd_db, linewidth=0.7, color="#2a78d6")
        ax.set_xlim(max(freqs[1], 10.0), freqs[-1])
        ax.set_xlabel("frecuencia (Hz)")
        ax.set_ylabel("PSD (dB/Hz)")
        ax.set_title(f"{nombre} (Welch, {FFT_NPERSEG:,} muestras/segmento)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()
        self._agregar_crosshair(canvas, [ax])
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})

    def _crear_tab_area(self, nombre, rms, fs):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        controles = tk.Frame(frame)
        controles.pack(side="top", fill="x", padx=4, pady=(4, 0))
        tk.Label(controles, text="Ventana:").pack(side="left")
        opciones_ms = [50, 100, 200, 500, 1000]
        combo = ttk.Combobox(
            controles, state="readonly", width=8,
            values=[f"{ms} ms" for ms in opciones_ms],
        )
        combo.pack(side="left", padx=(4, 0))
        combo.set(f"{int(AREA_VENTANA_S * 1000)} ms")

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        ax = fig.subplots(1, 1)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()

        crosshair = self._agregar_crosshair(canvas, [ax])

        def _redibujar(ventana_ms):
            ventana_s = ventana_ms / 1000.0
            t, area = _area_por_ventana(rms, fs, ventana_s)
            ax.clear()
            if len(t):
                ax.bar(t, area, width=ventana_s * 0.9, color="#2a78d6", align="center")
            else:
                ax.text(0.5, 0.5, f"Archivo mas corto que {ventana_ms}ms, sin ventanas completas",
                         ha="center", va="center", transform=ax.transAxes, color="gray")
            ax.set_xlabel("tiempo (s) desde el inicio del archivo")
            ax.set_ylabel("área (V·s)")
            ax.set_title(f"{nombre} — ventana de {ventana_ms}ms")
            ax.grid(True, axis="y", alpha=0.3)
            self._registrar_crosshair(crosshair, ax)
            canvas.draw_idle()

        def _al_elegir_ventana(event=None):
            ventana_ms = int(combo.get().split()[0])
            _redibujar(ventana_ms)

        combo.bind("<<ComboboxSelected>>", _al_elegir_ventana)

        _redibujar(int(AREA_VENTANA_S * 1000))
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})

    def _crear_tab_combinado(self, nombre, filtrado, fs, t_kurt, kurt):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        controles = tk.Frame(frame)
        controles.pack(side="top", fill="x", padx=4, pady=(4, 0))
        tk.Label(controles, text="Umbral kurtosis (señal si supera este valor):").pack(side="left")

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        # sharex=True aca SI es correcto (a diferencia de overview/zoom en
        # _crear_tab): las dos filas cubren el archivo completo con el mismo
        # eje de tiempo, asi que hacer zoom/pan en una mueve la otra igual.
        ax_signal, ax_kurt = fig.subplots(2, 1, sharex=True)

        t_env, ymin, ymax = _envolvente(filtrado, N_BINS_OVERVIEW)
        ax_signal.fill_between(t_env / fs, ymin, ymax, linewidth=0, color="#2a78d6")
        ax_signal.set_ylabel(f"{nombre.replace(' — Señal+Kurtosis', '')} (V)")
        ax_signal.set_title(f"{nombre}")

        ventana_ms = int(AREA_VENTANA_S * 1000)
        if len(t_kurt):
            ax_kurt.plot(t_kurt, kurt, linewidth=0.8, color="#1baf7a")
            ax_kurt.axhline(3.0, color="gray", linestyle="--", linewidth=0.8, label="kurtosis gaussiana (~3, ruido)")
        else:
            ax_kurt.text(0.5, 0.5, f"Archivo mas corto que {ventana_ms}ms, sin ventanas completas",
                          ha="center", va="center", transform=ax_kurt.transAxes, color="gray")
        ax_kurt.set_ylabel(f"kurtosis ({ventana_ms}ms)")
        ax_kurt.set_xlabel("tiempo (s) desde el inicio del archivo")
        ax_kurt.grid(True, alpha=0.3)

        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()
        self._agregar_crosshair(canvas, [ax_signal, ax_kurt])

        # Umbral SIN valor fijo adivinado: sin un archivo de fondo puro en
        # esta banda (25-400kHz) para calibrar contra que comparamos, un
        # numero fijo en el codigo (10, 15, 20...) seria arbitrario — mejor
        # un slider que se ajusta a ojo mirando donde la kurtosis se dispara
        # contra los picos reales de la señal de arriba.
        linea_umbral = {"artista": None}

        def _al_mover_umbral(valor):
            if linea_umbral["artista"] is not None:
                linea_umbral["artista"].remove()
            umbral = float(valor)
            if len(kurt):
                n_senal = int((kurt > umbral).sum())
                linea_umbral["artista"] = ax_kurt.axhline(
                    umbral, color="red", linestyle="--", linewidth=0.9, label=f"umbral={umbral:.1f}",
                )
                ax_kurt.legend(loc="upper right", fontsize=8)
                label_conteo.config(text=f"{n_senal}/{len(kurt)} ventanas ≥ umbral ({100 * n_senal / len(kurt):.1f}%)")
            canvas.draw_idle()

        umbral_max = max(20.0, float(np.ceil(kurt.max()))) if len(kurt) else 20.0
        umbral_inicial = min(KURT_FIJO_ACUMULADO, umbral_max)
        slider = tk.Scale(
            controles, from_=3, to=umbral_max, resolution=0.5, orient="horizontal",
            length=280, command=_al_mover_umbral,
        )
        slider.set(umbral_inicial)
        slider.pack(side="left", padx=(4, 8))
        label_conteo = tk.Label(controles, text="")
        label_conteo.pack(side="left")

        _al_mover_umbral(umbral_inicial)
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})

    def _crear_tab_rmsdif(self, nombre, t_kurt, kurt, rms_w):
        """RMS diferencial autocalibrado + clasificador combinado. El
        umbral de kurtosis define que ventanas son "fondo" (kurt <= umbral)
        para calcular el baseline = mediana del RMS de esas ventanas de
        fondo, en vez de depender de una carpeta "reposo" externa
        (rms_diferencial de revisar.py usa la mediana de reposo del LOTE;
        acá, del archivo mismo). Formula identica:
        sqrt(max(0, rms^2 - baseline^2)) / baseline.

        Kurtosis alta y rd alto NO siempre coinciden en la misma ventana
        (kurtosis mide forma/picos, rd mide energia — confirmado con datos
        reales del archivo 143538: una ventana con kurt=23.9 dio rd=1.05,
        y otra con kurt=7.1 dio rd=1.9). Por eso el conteo final exige
        pasar AMBOS umbrales a la vez (AND), no cualquiera de los dos solo."""
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        controles = tk.Frame(frame)
        controles.pack(side="top", fill="x", padx=4, pady=(4, 0))
        tk.Label(controles, text="Umbral kurtosis (fondo/baseline):").pack(side="left")

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        ax = fig.subplots(1, 1)
        ax.set_ylabel("RMS diferencial")
        ax.set_xlabel("tiempo (s) desde el inicio del archivo")
        ax.grid(True, alpha=0.3)

        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()
        self._agregar_crosshair(canvas, [ax])

        linea_rd = {"artista": None}
        linea_umbral_rd = {"artista": None}

        def _recalcular(_=None):
            umbral_kurt = float(slider_kurt.get())
            umbral_rd = float(slider_rd.get())
            if not len(kurt):
                canvas.draw_idle()
                return
            mask_kurt = kurt > umbral_kurt
            fondo = rms_w[~mask_kurt]
            n_fondo = len(fondo)
            if n_fondo > 0 and float(np.median(fondo)) > 0:
                baseline = float(np.median(fondo))
                rd = np.sqrt(np.maximum(0.0, rms_w.astype(np.float64) ** 2 - baseline ** 2)) / baseline
                texto_baseline = f"baseline: {baseline:.4f}V ({n_fondo} ventanas de fondo)"
            else:
                rd = np.full(len(rms_w), np.nan)
                texto_baseline = "sin ventanas de fondo para el baseline"

            if linea_rd["artista"] is None:
                linea_rd["artista"], = ax.plot(t_kurt, rd, linewidth=0.8, color="#c0392b")
            else:
                linea_rd["artista"].set_ydata(rd)
            if linea_umbral_rd["artista"] is not None:
                linea_umbral_rd["artista"].remove()
            linea_umbral_rd["artista"] = ax.axhline(
                umbral_rd, color="gray", linestyle="--", linewidth=0.8, label=f"umbral rd={umbral_rd:.2f}",
            )
            ax.legend(loc="upper right", fontsize=8)
            ax.relim()
            ax.autoscale_view()

            mask_rd = rd > umbral_rd
            mask_final = mask_kurt & mask_rd
            label_conteo.config(text=(
                f"kurtosis>{umbral_kurt:.1f}: {int(mask_kurt.sum())} | "
                f"rd>{umbral_rd:.2f}: {int(np.nansum(mask_rd))} | "
                f"AMBOS (señal confirmada): {int(mask_final.sum())}/{len(kurt)} — {texto_baseline}"
            ))
            canvas.draw_idle()

        umbral_kurt_max = max(20.0, float(np.ceil(kurt.max()))) if len(kurt) else 20.0
        umbral_kurt_inicial = min(KURT_FIJO_ACUMULADO, umbral_kurt_max)
        slider_kurt = tk.Scale(
            controles, from_=3, to=umbral_kurt_max, resolution=0.5, orient="horizontal",
            length=220, command=_recalcular,
        )
        slider_kurt.set(umbral_kurt_inicial)
        slider_kurt.pack(side="left", padx=(4, 12))

        tk.Label(controles, text="Umbral RMS diferencial:").pack(side="left")
        slider_rd = tk.Scale(
            controles, from_=0, to=10.0, resolution=0.1, orient="horizontal",
            length=220, command=_recalcular,
        )
        slider_rd.set(0.5)
        slider_rd.pack(side="left", padx=(4, 8))

        label_conteo = tk.Label(controles, text="")
        label_conteo.pack(side="left")

        _recalcular()
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})

    def _crear_tab_acumulado(self, nombre, t_kurt, kurt, area_vals):
        """Acumulado corriente del área bajo la curva de RMS, sumando SOLO
        las ventanas (AREA_VENTANA_S) con kurtosis >= KURT_FIJO_ACUMULADO —
        las ventanas de fondo aportan 0. Umbral fijo por ahora (no slider),
        primer paso antes de pensar en pegar varios archivos como hace
        timeline_lote.py con la kurtosis."""
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre)

        fig = plt.Figure(figsize=(9, 7), tight_layout=True)
        ax = fig.subplots(1, 1)

        if len(t_kurt):
            mask = kurt >= KURT_FIJO_ACUMULADO
            area_contada = np.where(mask, area_vals, 0.0)
            acumulado = np.cumsum(area_contada, dtype=np.float64)
            ax.step(t_kurt, acumulado, where="post", linewidth=1.2, color="#2a78d6")
            n_contadas = int(mask.sum())
            texto = (
                f"kurtosis≥{KURT_FIJO_ACUMULADO:.1f}: {n_contadas}/{len(kurt)} ventanas sumadas "
                f"({100 * n_contadas / len(kurt):.1f}%) — total acumulado: {acumulado[-1]:.4f} V·s"
            )
            ax.text(0.02, 0.98, texto, transform=ax.transAxes, ha="left", va="top", fontsize=8)
        else:
            ax.text(0.5, 0.5, f"Archivo mas corto que {int(AREA_VENTANA_S * 1000)}ms, sin ventanas completas",
                     ha="center", va="center", transform=ax.transAxes, color="gray")

        ax.set_xlabel("tiempo (s) desde el inicio del archivo")
        ax.set_ylabel("área acumulada (V·s)")
        ax.set_title(f"{nombre} (kurtosis≥{KURT_FIJO_ACUMULADO:.1f}, ventana {int(AREA_VENTANA_S * 1000)}ms)")
        ax.grid(True, alpha=0.3)

        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, frame)
        toolbar.update()
        self._agregar_crosshair(canvas, [ax])
        canvas.draw()

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})


def main():
    root = TkinterDnD.Tk() if _CON_DND else tk.Tk()
    VisorFormaOnda(root)
    root.mainloop()


if __name__ == "__main__":
    main()
