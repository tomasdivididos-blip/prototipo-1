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
    def __init__(self, dims, rec, parent=None, apply_callback=None):
        captured["dims"] = dims
        captured["rec"] = rec
        captured["has_apply"] = apply_callback is not None
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

# --- 3) aplicar el preset DBA a la sala ------------------------------------
from dba import build_dba_sources
n0 = len(panel.sources)
specs = build_dba_sources(exp_dims, axis=1, n_x=2, n_z=2, drive="naive", fmax=180)
panel._apply_dba_to_room(specs, vmin)
ck(len(panel.sources) == n0 + len(specs),
   f"apply agrega {len(specs)} fuentes ({n0}->{len(panel.sources)})")
dba_srcs = [s for s in panel.sources if str(s.label).startswith("DBA-")]
ck(len(dba_srcs) == 8, f"8 fuentes DBA-* ({len(dba_srcs)})")
rear = [s for s in dba_srcs if s.label.startswith("DBA-R")][0]
ck(abs(rear.delay_s - exp_dims[1] / 343.0) < 1e-3 and rear.polarity == -1,
   "rear naive: delay=Ly/c + polaridad -1")
# posiciones dentro de la caja (shift por vmin)
ins = all(np.all(np.asarray(s.position) >= vmin - 1e-6) and
          np.all(np.asarray(s.position) <= v.max(axis=0) + 1e-6) for s in dba_srcs)
ck(ins, "posiciones DBA dentro de la caja (shift por vmin)")
# re-aplicar (LS) NO duplica: reemplaza las DBA
specs2 = build_dba_sources(exp_dims, axis=1, n_x=2, n_z=2, drive="ls", fmax=180)
panel._apply_dba_to_room(specs2, vmin)
ck(len([s for s in panel.sources if str(s.label).startswith("DBA-")]) == 8,
   "re-aplicar reemplaza (no duplica) las fuentes DBA")
ck(all(s.response is not None for s in panel.sources
       if str(s.label).startswith("DBA-")),
   "fuentes DBA-LS traen curva q(f) por fuente")

# --- 3b) auto-mute de las otras fuentes al aplicar --------------------------
from sources import OmniSource
panel.sources.add(OmniSource((1.0, 1.0, 1.0), label="baseline", active=True))
ap.QMessageBox.question = staticmethod(lambda *a, **k: ap.QMessageBox.Yes)
panel._apply_dba_to_room(build_dba_sources(exp_dims, axis=1, n_x=2, n_z=2,
                                           drive="naive", fmax=180), vmin)
base = [s for s in panel.sources if s.label == "baseline"][0]
ck(base.active is False, "auto-mute: la fuente baseline queda inactiva")
ck(all(s.active for s in panel.sources if str(s.label).startswith("DBA-")),
   "las fuentes DBA quedan activas")

# --- 4) apply desde el diálogo (callback + QMessageBox mockeado) ------------
import dba_dialog as dd
dd.QMessageBox.question = staticmethod(lambda *a, **k: dd.QMessageBox.Yes)
dd.QMessageBox.information = staticmethod(lambda *a, **k: None)
grabbed = {}
d2 = DBADialog(exp_dims, exp_rec, apply_callback=lambda sp: grabbed.setdefault("n", len(sp)))
d2.sb_nx.setValue(2); d2.sb_nz.setValue(2); d2.combo_drive.setCurrentIndex(1)
d2._apply()
ck(grabbed.get("n") == 8, "botón «Aplicar a la sala» invoca el callback con 8 specs")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
