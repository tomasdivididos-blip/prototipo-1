"""smoke_test_dba_dialog.py — wiring S1+S5: herramienta DBA/CABS en la GUI.

Verifica (offscreen): (1) DBADialog construye y calcula por los dos drives;
(2) el botón del panel existe y _open_dba arma dims/receptor desde la caja AABB
y abre la herramienta (DBADialog stubeado para no bloquear en exec_).

Correr:  QT_QPA_PLATFORM=offscreen python smoke_test_dba_dialog.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROTO1_WATCHDOG"] = "0"

import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

fails = []
def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

# --- 1) DBADialog directo ---------------------------------------------------
from dba_dialog import DBADialog
d = DBADialog((5.0, 6.5, 3.0), (3.5, 4.0, 1.5))
ck(d.combo_axis.currentIndex() == 1, "eje default = Y (el más largo)")
d.sb_fmax.setValue(160.0)
d.combo_drive.setCurrentIndex(0)      # LS
d._calc()
ck("CABS off" in d.lbl_res.text(), "cálculo LS puebla resultados")
d.combo_drive.setCurrentIndex(1)      # naive
d._calc()
ck("CABS off" in d.lbl_res.text(), "cálculo naive puebla resultados")

# --- 2) glue del panel: _open_dba arma dims/receptor y abre la herramienta --
from geometry import make_room
from viewer import IsoViewer
import acoustic_panel as ap

W, L, H = 6.0, 8.0, 3.0
v, t, _, _ = make_room(width=W, length=L, height=H, n_walls=4)
viewer = IsoViewer()
panel = ap.AcousticPanel(viewer=viewer, get_surface=lambda: (v, t),
                         get_dims_hint=lambda: (W, L, H))
ck(hasattr(panel, "btn_dba"), "el panel tiene el botón «Subs enfrentados»")
ck(callable(getattr(panel, "_open_dba", None)), "_open_dba es invocable")

# Stub de DBADialog para no bloquear en exec_(); captura dims/receptor.
captured = {}
class _Stub:
    def __init__(self, dims, rec, parent=None):
        captured["dims"] = dims
        captured["rec"] = rec
    def exec_(self):
        return 0
import dba_dialog
_orig = dba_dialog.DBADialog
dba_dialog.DBADialog = _Stub
try:
    panel.receiver = np.array([2.0, 3.0, 1.2])
    panel._open_dba()
finally:
    dba_dialog.DBADialog = _orig

vmin = v.min(axis=0)
exp_dims = tuple((v.max(axis=0) - vmin).tolist())
exp_rec = tuple((np.array([2.0, 3.0, 1.2]) - vmin).tolist())
ck("dims" in captured and np.allclose(captured["dims"], exp_dims),
   f"dims desde AABB {tuple(round(x,2) for x in captured.get('dims',()))}")
ck("rec" in captured and np.allclose(captured["rec"], exp_rec),
   "receptor relativo a la esquina mínima de la caja")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
