#!/usr/bin/env python3
"""
ver_acumulado_lote.py — Visor interactivo del acumulado de UN LOTE (varias
capturas seguidas del mismo tipo, pegadas en un solo eje de tiempo real),
misma ventana/estilo que ver_forma_onda.py (lista de carpetas con
arrastrar-y-soltar, canvas de matplotlib embebido con zoom/pan) en vez del
script de linea de comandos acumulado_lote.py — pensado para que lo use
alguien que no arma un comando con glob en una terminal.

A diferencia de ver_forma_onda.py (una pestaña por archivo, y varias vistas
DE ESE archivo — cruda, filtrada, FFT, etc.), acá no hay pestañas por
archivo: se agregan TODAS las carpetas del lote a la lista y un solo boton
"Procesar lote" arma UNA vista de 2 paneles (kurtosis, acumulado) con todos
los archivos pegados en el tiempo — es la unica vista que tiene sentido si
lo que se quiere es el acumulado del lote, no quedaria bien mezclada con el
resto de pestañas de ver_forma_onda.py.

(Tuvo un tercer panel de rms_diferencial — sacado a pedido del usuario
porque no aportaba nada por encima del acumulado.)

No reimplementa el calculo — usa las funciones de acumulado_lote.py
(_leer_lote, _armar_serie, _acumulado, _tramos_activos, _etiqueta_lote), que
a su vez reusan revisar.py (banda 25-400kHz, umbral kurtosis 6 — ver ahi
para el porque). También guarda el mismo PNG que la version CLI en
analisis/outputs/acumulado_lote/, por si hace falta para un informe.

El procesamiento (leer+filtrar+ventanear todos los archivos) corre en un
hilo aparte — con un lote real de 13 archivos (~20min de captura) tarda
unos 40s, y bloquear la ventana ese tiempo la deja "trabada" sin feedback.

Uso: doble-click en abrir_acumulado_lote.sh (mismo directorio), o:
  .venv/bin/python3 analisis/ver_acumulado_lote.py
"""
import os
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

sys.path.insert(0, str(Path(__file__).parent))
from revisar import _recopilar_rutas  # noqa: E402
from acumulado_lote import (  # noqa: E402
    _leer_lote, _armar_serie, _acumulado, _tramos_activos, _etiqueta_lote,
    FA_THRESH, ART, COLOR_K1, COLOR_K2, INK_MUTED, OUT_DIR,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _CON_DND = True
except ImportError:
    _CON_DND = False


def _procesar_grupo(items, canales):
    """Corre el mismo pipeline que _graficar de acumulado_lote.py (armar
    serie, acumulado, tramos) por canal, pero devuelve los resultados en vez
    de dibujar/imprimir directo — separa el calculo (se llama desde el hilo
    de fondo) de la construccion del grafico y el texto (thread principal de
    Tk, ver _Aplicacion._mostrar)."""
    canales_info = (
        [(0, COLOR_K1, 'ch1 (codo)'), (1, COLOR_K2, 'ch2 (referencia)')]
        if canales == 2 else [(0, COLOR_K1, 'mono')]
    )
    resultado = {'canales': canales, 'por_canal': [], 'huecos': []}
    for idx, color, etiqueta in canales_info:
        tiempos, kurt, area, huecos = _armar_serie(items, idx)
        resultado['huecos'] = huecos  # mismos huecos para todos los canales del grupo
        acumulado, mask = _acumulado(kurt, area)
        tramos = _tramos_activos(tiempos, kurt)
        resultado['por_canal'].append({
            'idx': idx, 'color': color, 'etiqueta': etiqueta,
            'tiempos': tiempos, 'kurt': kurt,
            'acumulado': acumulado, 'mask': mask, 'tramos': tramos,
        })
    return resultado


def _texto_reporte(nombre_lote, resultado):
    lineas = [f'=== {nombre_lote} ===']
    for c in resultado['por_canal']:
        tramos = c['tramos']
        if not tramos:
            lineas.append(f"  [{c['etiqueta']}] ningun tramo con kurtosis > {FA_THRESH} — reposo de punta a punta")
        else:
            lineas.append(f"  [{c['etiqueta']}] {len(tramos)} tramo(s) con arena:")
            for t_ini, t_fin, dur_s, pico in tramos:
                ini_art = t_ini.astimezone(ART).strftime('%H:%M:%S')
                fin_art = t_fin.astimezone(ART).strftime('%H:%M:%S')
                lineas.append(f"      {ini_art} - {fin_art} ART  ({dur_s:5.1f}s, kurtosis pico {pico:7.1f})")
    lineas.append('')
    for c in resultado['por_canal']:
        kurt, mask, acumulado = c['kurt'], c['mask'], c['acumulado']
        n_total = int((~np.isnan(kurt)).sum())
        n_contadas = int(np.nansum(mask))
        total_v = acumulado[-1] if len(acumulado) else 0.0
        pct = f'{100 * n_contadas / n_total:.1f}%' if n_total else 'N/A'
        lineas.append(
            f"  acumulado (kurtosis>={FA_THRESH}) [{c['etiqueta']}]: {n_contadas}/{n_total} ventanas "
            f"({pct}) — total {total_v:.4f} V·s"
        )
    huecos = resultado['huecos']
    if huecos:
        dur_huecos = sum(h[2] for h in huecos)
        lineas.append(
            f"  Huecos entre archivos: {len(huecos)}, {dur_huecos:.1f}s sin datos en total "
            f"(recarga de bitstream entre chunks — no es reposo confirmado, es tiempo sin medir)."
        )
    return '\n'.join(lineas)


class VisorAcumuladoLote:
    def __init__(self, root):
        self.root = root
        root.title("Acumulado de lote — señal pegada en el tiempo real")
        root.geometry("1250x820")
        root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self.archivos = []  # lista de Path (carpetas o archivos), en el orden agregado
        self._cerrando = False  # ver _al_cerrar / _notificar

        marco_izq = tk.Frame(root, width=260)
        marco_izq.pack(side="left", fill="y", padx=6, pady=6)
        marco_izq.pack_propagate(False)

        tk.Label(marco_izq, text="Carpetas del lote (arrastrá acá o usá el botón).\nSi arrastrás/elegís la carpeta padre, se agregan\ntodas sus subcarpetas con capturas juntas.",
                 justify="left").pack(anchor="w")
        self.listbox = tk.Listbox(marco_izq, height=18, selectmode="extended")
        self.listbox.pack(fill="both", expand=True, pady=4)

        if _CON_DND:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._al_soltar)

        marco_botones = tk.Frame(marco_izq)
        marco_botones.pack(fill="x")
        tk.Button(marco_botones, text="Agregar carpeta...", command=self._agregar_carpeta).pack(fill="x")
        tk.Button(marco_botones, text="Quitar seleccionada(s)", command=self._quitar_seleccionadas).pack(fill="x", pady=(4, 0))
        tk.Button(marco_botones, text="Vaciar lista", command=self._vaciar).pack(fill="x", pady=(4, 0))

        tk.Frame(marco_izq, height=1, bg="#cccccc").pack(fill="x", pady=8)

        self.boton_procesar = tk.Button(marco_izq, text="Procesar lote", command=self._procesar,
                                         bg="#2a78d6", fg="white", font=("TkDefaultFont", 10, "bold"))
        self.boton_procesar.pack(fill="x", pady=(10, 0), ipady=6)

        self.estado_label = tk.Label(marco_izq, text="", justify="left", anchor="w", wraplength=240, fg="#666666")
        self.estado_label.pack(fill="x", pady=(6, 0))

        if not _CON_DND:
            self.estado_label.config(text="[!] Arrastrar y soltar no disponible\n(falta tkinterdnd2)")

        marco_der = tk.Frame(root)
        marco_der.pack(side="right", fill="both", expand=True, padx=6, pady=6)

        # Notebook con un tab por grupo (mono/dual) — normalmente 1 solo tab,
        # 2 solo si el lote mezcla mono y dual (caso raro, ver docstring de
        # acumulado_lote.py: un lote deberia ser de un solo tipo).
        self.notebook = ttk.Notebook(marco_der)
        self.notebook.pack(fill="both", expand=True)
        self._tabs = []  # [{"frame","fig","canvas"}, ...] del resultado actual

        tk.Label(marco_der, text="Arrastrá/agregá las carpetas del lote a la izquierda y apretá \"Procesar lote\".",
                 fg="#888888").pack(side="bottom", pady=(4, 0))

    # --- manejo de la lista ---

    def _al_soltar(self, event):
        for ruta in self.root.tk.splitlist(event.data):
            self._agregar_ruta(Path(ruta))

    def _agregar_carpeta(self):
        ruta = filedialog.askdirectory(title="Elegí una carpeta del lote, o la carpeta PADRE que las contiene a todas")
        if ruta:
            self._agregar_ruta(Path(ruta))

    def _agregar_ruta(self, ruta: Path):
        """Agrega `ruta` a la lista. Si `ruta` no es en si misma una carpeta
        de captura (no tiene campo_*.bin propios) se asume que es la carpeta
        PADRE de un lote — caso comun, ej. datos_campo/ tiene una carpeta
        hermana por archivo — y se agregan TODAS sus subcarpetas que si
        tengan capturas, en vez de obligar a elegirlas una por una a mano
        (askdirectory de Tk no permite selección múltiple)."""
        if not ruta.exists():
            messagebox.showwarning("No encontrado", str(ruta))
            return
        if ruta.is_file() or list(ruta.glob("campo_*.bin")):
            self._agregar_una(ruta)
            return
        hijas = sorted(p for p in ruta.iterdir() if p.is_dir() and list(p.glob("campo_*.bin")))
        if not hijas:
            messagebox.showwarning("Sin capturas", f"{ruta.name} no tiene archivos campo_*.bin ni subcarpetas con ellos.")
            return
        for hija in hijas:
            self._agregar_una(hija)

    def _agregar_una(self, ruta: Path):
        if ruta not in self.archivos:
            self.archivos.append(ruta)
            self.listbox.insert("end", ruta.name)

    def _quitar_seleccionadas(self):
        for i in reversed(self.listbox.curselection()):
            self.archivos.pop(i)
            self.listbox.delete(i)

    def _vaciar(self):
        self.archivos = []
        self.listbox.delete(0, "end")

    # --- procesamiento ---

    def _procesar(self):
        if not self.archivos:
            messagebox.showinfo("Lista vacía", "Agregá al menos una carpeta del lote.")
            return
        rutas = sorted(_recopilar_rutas([str(r) for r in self.archivos]), key=lambda p: p.name)
        if not rutas:
            messagebox.showwarning("Sin archivos", "No se encontraron archivos campo_*.bin en lo agregado.")
            return

        self.boton_procesar.config(state="disabled", text="Procesando...")
        self.estado_label.config(text=f"Leyendo y filtrando {len(rutas)} archivo(s)... puede tardar varios segundos.")
        self.root.update_idletasks()

        hilo = threading.Thread(target=self._procesar_en_hilo, args=(rutas,), daemon=True)
        hilo.start()

    def _procesar_en_hilo(self, rutas):
        try:
            items = _leer_lote(rutas)
            mono = [it for it in items if it['canales'] == 1]
            dual = [it for it in items if it['canales'] == 2]
            grupos = []
            if mono:
                grupos.append((_etiqueta_lote('mono', mono[0]['archivo'], mono[-1]['archivo']),
                                _procesar_grupo(mono, canales=1)))
            if dual:
                grupos.append((_etiqueta_lote('dual', dual[0]['archivo'], dual[-1]['archivo']),
                                _procesar_grupo(dual, canales=2)))
            if not grupos:
                raise ValueError("ningun archivo tuvo ventanas completas (¿archivos muy cortos?)")
        except Exception:
            error = traceback.format_exc()
            self._notificar(self._al_fallar, error)
            return
        self._notificar(self._mostrar, grupos)

    def _notificar(self, callback, *args):
        """Puente hilo de fondo -> hilo principal de Tk (via root.after).
        Si la ventana ya se esta cerrando, no llama a Tcl — el filtrado con
        scipy no se puede cancelar a mitad de camino, asi que este hilo
        puede seguir corriendo un rato despues de que el usuario cerro la
        ventana; llamar a root.after() sobre un root ya destruido es lo que
        dejaba el proceso colgado esperando Ctrl+C."""
        if self._cerrando:
            return
        try:
            self.root.after(0, callback, *args)
        except Exception:
            pass

    def _al_cerrar(self):
        self._cerrando = True
        for tab in self._tabs:
            try:
                plt.close(tab["fig"])
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        # Salida inmediata en vez de un shutdown "prolijo": si el hilo de
        # fondo seguia procesando, root.destroy() no siempre alcanza para
        # que mainloop() vuelva (visto en la practica con la combinacion
        # tkinterdnd2+hilo — hacia falta Ctrl+C varias veces en la
        # terminal). No hay nada que perder por salir asi: el PNG ya se
        # guardo si el procesamiento habia terminado, y si no, no hay
        # resultado que conservar.
        os._exit(0)

    def _al_fallar(self, error_texto):
        self.boton_procesar.config(state="normal", text="Procesar lote")
        self.estado_label.config(text="")
        messagebox.showerror("Error procesando el lote", error_texto)
        print(error_texto, file=sys.stderr)

    def _mostrar(self, grupos):
        self.boton_procesar.config(state="normal", text="Procesar lote")
        self.estado_label.config(text=f"Listo — {len(grupos)} grupo(s) (mono/dual) procesado(s).")

        for tab in self._tabs:
            self.notebook.forget(tab["frame"])
            plt.close(tab["fig"])
            tab["frame"].destroy()
        self._tabs = []

        for nombre_lote, resultado in grupos:
            self._crear_tab_resultado(nombre_lote, resultado)
        if self._tabs:
            self.notebook.select(0)

    def _crear_tab_resultado(self, nombre_lote, resultado):
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=nombre_lote)

        marco_grafico = tk.Frame(frame)
        marco_grafico.pack(side="top", fill="both", expand=True)

        fig, (ax_k, ax_a) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
        fig.suptitle(nombre_lote, fontsize=11)

        for c in resultado['por_canal']:
            multi = len(resultado['por_canal']) > 1
            label = c['etiqueta'] if multi else None
            ax_k.plot(c['tiempos'], c['kurt'], color=c['color'], linewidth=0.8, label=label)
            ax_a.step(c['tiempos'], c['acumulado'], where='post', color=c['color'], linewidth=1.2, label=label)
        if len(resultado['por_canal']) > 1:
            ax_k.legend(fontsize=8)
            ax_a.legend(fontsize=8)

        ax_k.set_yscale('symlog', linthresh=10)
        ax_k.set_ylabel('kurtosis (log)')
        ax_k.axhline(FA_THRESH, color=INK_MUTED, linestyle='--', linewidth=0.8)

        ax_a.set_ylabel('área acumulada (V·s)')
        ax_a.set_xlabel('hora (ART)')
        ax_a.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S', tz=ART))
        ax_a.grid(True, alpha=0.3)
        for ax in (ax_k, ax_a):
            ax.grid(True, alpha=0.2)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=marco_grafico)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, marco_grafico)
        toolbar.update()
        canvas.draw()

        marco_texto = tk.Frame(frame)
        marco_texto.pack(side="bottom", fill="x")
        texto = tk.Text(marco_texto, height=10, font=("monospace", 8), wrap="none")
        scroll = tk.Scrollbar(marco_texto, command=texto.yview)
        texto.config(yscrollcommand=scroll.set)
        texto.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        texto.insert("1.0", _texto_reporte(nombre_lote, resultado))
        texto.config(state="disabled")

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_png = OUT_DIR / f'{nombre_lote}.png'
        fig.savefig(out_png, dpi=150)
        texto.config(state="normal")
        texto.insert("1.0", f'[guardado en {out_png}]\n\n')
        texto.config(state="disabled")

        self._tabs.append({"frame": frame, "fig": fig, "canvas": canvas})


def main():
    root = TkinterDnD.Tk() if _CON_DND else tk.Tk()
    VisorAcumuladoLote(root)
    root.mainloop()


if __name__ == "__main__":
    main()
