"""smoke_test_driver_ui.py — wiring S2: grupo Driver (Thiele-Small) en
SourceEditDialog. Construye el diálogo offscreen, aplica el driver por los dos
modos (fc/Qtc y TS crudos) y verifica que la curva se compone en la fuente.

Correr:  QT_QPA_PLATFORM=offscreen python smoke_test_driver_ui.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROTO1_WATCHDOG"] = "0"

import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
from acoustic_panel import SourceEditDialog

fails = []
def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

d = SourceEditDialog(dims_hint=(5, 4, 3))
ck(True, "SourceEditDialog construye con el grupo Driver")

# modo directo fc/Qtc
d.sb_drv_fc.setValue(45.0); d.sb_drv_qtc.setValue(0.9)
d._apply_driver()
ck(d._response is not None, "driver directo setea la curva")
g = d._response.gain_spectrum(np.array([15., 45., 200., 1000.]))
p = np.array([15., 45., 200., 1000.]) * np.abs(g); p /= p[-1]
ck(p[0] < 0.3, f"presión cae bajo fc (p(15Hz)/p_ref={p[0]:.3f})")
ck(abs(p[1] - 0.9) < 0.03, f"presión en fc = Qtc (p(45)/p_ref={p[1]:.3f})")

# modo TS crudos
d.combo_drv_mode.setCurrentIndex(1); d._on_drv_mode_changed()
d.sb_drv_fs.setValue(25.); d.sb_drv_qts.setValue(0.35)
d.sb_drv_vas.setValue(100.); d.sb_drv_vb.setValue(50.)
d._apply_driver()
ck(d._response is not None and "fc=43" in d._response.name,
   f"driver TS: fc=fs·√(1+Vas/Vb) ({d._response.name})")

# get_source preserva la curva y effective_Q_spectrum es finito
src = d.get_source()
ck(src.response is not None, "get_source preserva la curva del driver")
q = src.effective_Q_spectrum(np.array([30., 80., 120.]))
ck(np.all(np.isfinite(q)), "effective_Q_spectrum finito con driver")

# quitar limpia
d._clear_resp()
ck(d._response is None, "Quitar limpia la curva del driver")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
