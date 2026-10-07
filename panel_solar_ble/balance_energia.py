"""
Balance de energia (docs/plan_perfiles_energia.md, etapa 2).

registro_energia.py le pasa cada fila de minuto que escribe; con eso se
lleva el SOC de la bateria por conteo de Ah, la energia de la hora y del
dia, y los consumos promedio con y sin Starlink. Al cerrar cada hora deja
un resumen en la cola del cartero (publicar_losant.py lo manda a Losant con
su hora original, igual que los del modo evento).

- SOC: cada minuto soc_ah += i_bat / 60 (i_bat es la corriente NETA de la
  bateria), limitado a 0..capacidad_ah. Entrar en float = 100 %. En una
  LiFePO4 la tension casi no se mueve entre ~20 y ~90 %, por eso se cuenta.
- Al arrancar se usa el ultimo SOC guardado: si la placa estuvo apagada
  porque se corto la salida LOAD, la bateria solo pudo cargarse, asi que es
  una cota inferior. Sin estado previo arranca en 50 %, no confiable.
- "Confiable" = hubo float en los ultimos DIAS_CONFIABLE dias.
- Promedios de consumo: media movil exponencial por minuto (~7 dias), con
  valores de partida del historial del MPPT (base ~7,5 W, Starlink +20 W).
- Dia local = UTC-3 (Argentina, sin horario de verano).
- El estado va a la SD con escritura atomica + fsync en cada minuto: el
  corte de LOAD apaga la placa sin aviso.

Nivel de energia (etapa 4): normal / ahorro / critico / supervivencia, cada
minuto, a nivel_file (en /run) para starlink_remoto/decidir_objetivo.sh:
  1. por la energia restante (umbrales 70/40/20 %); para SUBIR de nivel
     hace falta histeresis_pct mas (Ahorro -> Normal con >= 80 %);
  2. SOC no confiable: como maximo Ahorro;
  3. float o absorcion hoy (dia local): Normal (sobra sol);
  4. tension promedio de los ultimos 30 min (solo baja): < v_critico ->
     como maximo Critico, < v_supervivencia -> Supervivencia. Promedio y no
     minima: el historial tiene minimas de 12,6 V en dias que terminaron
     en float (caidas momentaneas).
"""
import json
import os
from datetime import datetime, timedelta, timezone

DIAS_CONFIABLE = 7
TAU_PROMEDIO_MIN = 7 * 24 * 60      # media movil de ~7 dias
LOCAL = timezone(timedelta(hours=-3))
VERSION_ESTADO = 1
NIVELES = ("supervivencia", "critico", "ahorro", "normal")   # de menor a mayor
MINUTOS_V_PROM = 30
MIN_MINUTOS_V_PROM = 10      # con menos datos la regla de tension no se aplica
PERFILES_DEFAULT = {
    "umbrales_pct": [70, 40, 20],    # normal, ahorro, critico
    "histeresis_pct": 10,
    "v_critico": 12.9,
    "v_supervivencia": 12.7,
    "nivel_file": "/run/energia_nivel.json",
}


def _float(fila, clave):
    try:
        return float(fila[clave])
    except (KeyError, TypeError, ValueError):
        return None


def horas_starlink(hora_on, hora_off):
    """Duracion de la ventana diaria de Starlink en horas ("08:55", "17:15")."""
    h1, m1 = map(int, hora_on.split(":"))
    h2, m2 = map(int, hora_off.split(":"))
    return ((h2 * 60 + m2) - (h1 * 60 + m1)) % (24 * 60) / 60


class BalanceEnergia:
    def __init__(self, estado_file, dir_pendientes, capacidad_ah=100.0,
                 capacidad_util_wh=1150.0, p_base_w=7.5, p_starlink_w=20.0,
                 horas_sl=8 + 20 / 60, perfiles=None):
        self.perfiles = {**PERFILES_DEFAULT, **(perfiles or {})}
        self.estado_file = estado_file
        self.dir_pendientes = dir_pendientes   # funcion -> carpeta de la cola del cartero
        self.capacidad_ah = capacidad_ah
        self.capacidad_util_wh = capacidad_util_wh
        self.horas_sl = horas_sl
        self.e = self._cargar() or {
            "version": VERSION_ESTADO,
            "soc_ah": capacidad_ah / 2,
            "ultimo_float": None,          # epoch del ultimo minuto en float
            "hora": None,                  # epoch del inicio de la hora que se acumula
            "acum": self._acum_vacio(),
            "dia_local": None,
            "balance_dia_wh": 0.0,
            "p_sin_sl_w": p_base_w,
            "p_con_sl_w": p_base_w + p_starlink_w,
        }
        # estados guardados antes de la etapa 4 no tienen estas claves
        self.e.setdefault("nivel", None)
        self.e.setdefault("motivo", "")
        self.e.setdefault("lleno_dia", None)     # dia local en que hubo float/absorcion
        self.e.setdefault("v_ult", [])           # [minuto, v] de los ultimos 30 min

    @staticmethod
    def _acum_vacio():
        return {"minutos": 0, "starlink_min": 0, "e_carga_wh": 0.0,
                "e_pv_wh": 0.0, "e_bat_wh": 0.0, "v_min": None}

    def _cargar(self):
        try:
            with open(self.estado_file) as f:
                e = json.load(f)
        except (OSError, ValueError):
            return None
        return e if isinstance(e, dict) and e.get("version") == VERSION_ESTADO else None

    def _guardar(self):
        carpeta = os.path.dirname(self.estado_file) or "."
        os.makedirs(carpeta, exist_ok=True)
        tmp = self.estado_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.e, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.estado_file)
        fd = os.open(carpeta, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def minuto(self, fila, minuto):
        """Procesa la fila de un minuto (dict de strings, columnas de
        registro_energia.COLUMNAS). minuto = epoch // 60."""
        v, i_bat = _float(fila, "v_bat"), _float(fila, "i_bat")
        if v is None or i_bat is None:
            return                                 # minuto solo con lecturas basura
        i_carga = _float(fila, "i_carga") or 0.0
        p_panel = _float(fila, "p_panel") or 0.0
        v_min = _float(fila, "v_bat_min") or v
        starlink = fila.get("starlink") == "on"
        t = minuto * 60
        e = self.e

        hora = t - t % 3600
        if e["hora"] is not None and hora != e["hora"]:
            self._cerrar_hora()
        e["hora"] = hora
        dia = datetime.fromtimestamp(t, LOCAL).strftime("%Y-%m-%d")
        if dia != e["dia_local"]:
            e["dia_local"], e["balance_dia_wh"] = dia, 0.0

        # SOC
        estado_carga = fila.get("estado_carga")
        if estado_carga == "float":
            e["soc_ah"], e["ultimo_float"] = self.capacidad_ah, t
        else:
            e["soc_ah"] = min(self.capacidad_ah, max(0.0, e["soc_ah"] + i_bat / 60))
        if estado_carga in ("float", "absorption"):
            e["lleno_dia"] = dia
        e["v_ult"] = [x for x in e["v_ult"] if x[0] > minuto - MINUTOS_V_PROM] + [[minuto, v]]

        # energia del minuto
        p_carga = v * i_carga
        a = e["acum"]
        a["minutos"] += 1
        a["starlink_min"] += starlink
        a["e_carga_wh"] += p_carga / 60
        a["e_pv_wh"] += p_panel / 60
        a["e_bat_wh"] += v * i_bat / 60
        a["v_min"] = v_min if a["v_min"] is None else min(a["v_min"], v_min)
        e["balance_dia_wh"] += v * i_bat / 60

        # consumo promedio con / sin Starlink
        clave = "p_con_sl_w" if starlink else "p_sin_sl_w"
        e[clave] += (p_carga - e[clave]) / TAU_PROMEDIO_MIN

        self._calcular_nivel(t, dia)
        self._guardar()
        self._escribir_nivel(t)

    def v_prom(self):
        v = [x[1] for x in self.e["v_ult"]]
        return sum(v) / len(v) if len(v) >= MIN_MINUTOS_V_PROM else None

    def _nivel_por_soc(self, soc, previo):
        u = self.perfiles["umbrales_pct"]                 # [normal, ahorro, critico]
        piso = {3: u[0], 2: u[1], 1: u[2], 0: float("-inf")}
        n = max(k for k in piso if soc >= piso[k])
        if previo is not None and n > previo:
            # subir de nivel pide histeresis_pct por encima del umbral
            h = self.perfiles["histeresis_pct"]
            while n > previo and soc < piso[n] + h:
                n -= 1
        return n

    def _calcular_nivel(self, t, dia):
        e, p = self.e, self.perfiles
        previo = NIVELES.index(e["nivel"]) if e["nivel"] in NIVELES else None
        soc = self.soc_pct()
        n = self._nivel_por_soc(soc, previo)
        motivo = f"soc {soc:.0f} %"
        if not self.soc_confiable(t) and n > 2:
            n, motivo = 2, motivo + ", soc no confiable (max ahorro)"
        if e["lleno_dia"] == dia and n < 3:
            n, motivo = 3, "bateria llena hoy (float/absorcion)"
        vp = self.v_prom()
        if vp is not None:
            if vp < p["v_supervivencia"] and n > 0:
                n, motivo = 0, f"tension {vp:.2f} V < {p['v_supervivencia']} (30 min)"
            elif vp < p["v_critico"] and n > 1:
                n, motivo = 1, f"tension {vp:.2f} V < {p['v_critico']} (30 min)"
        e["nivel"], e["motivo"] = NIVELES[n], motivo

    def _escribir_nivel(self, t):
        ruta = self.perfiles["nivel_file"]
        carpeta = os.path.dirname(ruta) or "."
        os.makedirs(carpeta, exist_ok=True)
        vp = self.v_prom()
        tmp = ruta + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"nivel": self.e["nivel"], "motivo": self.e["motivo"], "ts": t,
                       "soc_pct": round(self.soc_pct(), 1), "soc_confiable": self.soc_confiable(t),
                       "v_prom_30min": round(vp, 2) if vp is not None else None}, f)
        os.replace(tmp, ruta)   # /run es tmpfs: sin fsync

    def soc_pct(self):
        return 100 * self.e["soc_ah"] / self.capacidad_ah

    def soc_confiable(self, ahora):
        f = self.e["ultimo_float"]
        return f is not None and ahora - f <= DIAS_CONFIABLE * 86400

    def resumen(self, ahora):
        """Atributos en_* para Losant con el estado actual (sin los de la hora)."""
        e = self.e
        restante = self.soc_pct() / 100 * self.capacidad_util_wh
        dia_con_sl = e["p_con_sl_w"] * self.horas_sl + e["p_sin_sl_w"] * (24 - self.horas_sl)
        return {
            "en_soc_pct": round(self.soc_pct(), 1),
            "en_soc_confiable": self.soc_confiable(ahora),
            "en_energia_restante_wh": round(restante),
            "en_autonomia_sin_sl_h": round(restante / e["p_sin_sl_w"], 1) if e["p_sin_sl_w"] > 0 else None,
            "en_autonomia_con_sl_dias": round(restante / dia_con_sl, 2) if dia_con_sl > 0 else None,
            "en_balance_dia_wh": round(e["balance_dia_wh"]),
            "en_nivel": e.get("nivel"),
            "en_nivel_motivo": e.get("motivo"),
            "en_v_prom_30min": round(self.v_prom(), 2) if self.v_prom() is not None else None,
        }

    def _cerrar_hora(self):
        e, a = self.e, self.e["acum"]
        if a["minutos"]:
            fin = e["hora"] + 3600
            data = self.resumen(fin)
            data.update({
                "en_minutos": a["minutos"],
                "en_starlink_min": a["starlink_min"],
                "en_p_carga_w": round(a["e_carga_wh"] * 60 / a["minutos"], 1),
                "en_e_carga_wh": round(a["e_carga_wh"], 1),
                "en_e_pv_wh": round(a["e_pv_wh"], 1),
                "en_e_bat_wh": round(a["e_bat_wh"], 1),
                "en_v_min": round(a["v_min"], 2) if a["v_min"] is not None else None,
            })
            self._encolar(e["hora"] * 1000, data)
        e["acum"] = self._acum_vacio()

    def _encolar(self, tiempo_ms, data):
        carpeta = self.dir_pendientes()
        os.makedirs(carpeta, exist_ok=True)
        final = os.path.join(carpeta, f"{tiempo_ms}.energia.json")
        tmp = final + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"time": tiempo_ms, "data": data}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
