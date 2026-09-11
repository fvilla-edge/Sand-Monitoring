import sys
from pathlib import Path

_ANALISIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ANALISIS))          # revisar.py
sys.path.insert(0, str(_ANALISIS / "lote"))  # acumulado_lote.py, timeline_lote.py
