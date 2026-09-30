"""vista_reducida.py — dibujo de area+kurtosis por ventana reduciendo por
maximo, compartido por ver_paquete.py y visor_csv.py. Solo numpy+matplotlib
(sin scipy): lo usa tambien el ejecutable portable del visor de CSV."""
import numpy as np


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


class VistaReducida:
    """Dibuja area (escalon relleno) y kurtosis reduciendo a lo sumo MAX_PUNTOS
    grupos por vista: cada grupo muestra el MAXIMO de sus ventanas (un pico de
    arena de una sola ventana no desaparece al alejar). Al hacer zoom/pan se
    recalcula solo el tramo visible — un dia entero (1.7M ventanas) sin
    reducir tardaba ~7s por redibujo.

    `t` y `ventana_s` van en la misma unidad que el eje x (segundos, o dias
    de matplotlib si el eje es de fechas)."""
    MAX_PUNTOS = 4000

    def __init__(self, ax_area, ax_kurt, t, area, kurt, ventana_s, ax_acum=None, acum=None):
        orden = np.argsort(t)
        self.t = np.asarray(t, dtype=float)[orden]
        self.area = np.asarray(area, dtype=float)[orden]
        self.kurt = np.asarray(kurt, dtype=float)[orden]
        # opcional: tercera serie (area acumulada, creciente) en su propio eje
        self.acum = None if acum is None else np.asarray(acum, dtype=float)[orden]
        self.ventana_s = ventana_s
        self.ax_area, self.ax_kurt, self.ax_acum = ax_area, ax_kurt, ax_acum
        self.relleno = None
        (self.linea,) = ax_kurt.plot([], [], linewidth=0.8)
        self.linea_acum = None
        if ax_acum is not None:
            (self.linea_acum,) = ax_acum.plot([], [], linewidth=1.2, color="#d6612a")
        self._actualizar(self.t[0] - ventana_s, self.t[-1] + ventana_s)
        ax_area.set_xlim(self.t[0] - ventana_s, self.t[-1] + ventana_s)
        ax_area.set_ylim(0, np.nanmax(self.area) * 1.05)
        ax_kurt.set_ylim(min(0, np.nanmin(self.kurt)), np.nanmax(self.kurt) * 1.05)
        if ax_acum is not None:
            ax_acum.set_ylim(0, max(np.nanmax(self.acum), 1e-9) * 1.05)
        ax_area.callbacks.connect("xlim_changed", lambda ax: self._actualizar(*ax.get_xlim()))

    def _actualizar(self, x0, x1):
        i0 = max(0, np.searchsorted(self.t, x0) - 1)
        i1 = min(len(self.t), np.searchsorted(self.t, x1) + 1)
        t, a, k = self.t[i0:i1], self.area[i0:i1], self.kurt[i0:i1]
        c = self.acum[i0:i1] if self.acum is not None else np.zeros_like(t)
        paso = max(1, int(np.ceil(len(t) / self.MAX_PUNTOS)))
        if paso > 1:
            # grupos de `paso` ventanas, pero cortando tambien en cada hueco: un
            # grupo a caballo de un hueco quedaba con su hora promedio en el medio
            # del hueco (se veia al unir horas de dias distintos)
            huecos = np.nonzero(np.diff(t) > 1.5 * self.ventana_s)[0] + 1
            ini = np.union1d(np.arange(0, len(t), paso), huecos)  # el ultimo grupo puede quedar incompleto
            tg = np.add.reduceat(t, ini) / np.diff(np.append(ini, len(t)))
            a = np.maximum.reduceat(a, ini)
            k = np.maximum.reduceat(k, ini)
            c = np.maximum.reduceat(c, ini)  # creciente: el maximo del grupo es su ultimo valor
            cortes = np.nonzero(np.isin(ini, huecos))[0]  # la linea se corta antes de cada grupo que empieza tras un hueco
            t_c, a_c, k_c, c_c = (np.insert(v, cortes, np.nan) for v in (tg, a, k, c))
        else:
            t_c, a_c, k_c, c_c = _cortar_en_huecos(t, a, k, c, ventana_s=self.ventana_s)
        if self.relleno is not None:
            self.relleno.remove()
        self.relleno = self.ax_area.fill_between(t_c, a_c, step="mid", color="#2a78d6", linewidth=0)
        self.linea.set_data(t_c, k_c)
        if self.linea_acum is not None:
            self.linea_acum.set_data(t_c, c_c)
