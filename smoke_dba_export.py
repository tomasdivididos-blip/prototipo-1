"""smoke_dba_export.py — regresión del bug del profesor (1 Oct 2026):
"luego de optimizar fuentes, no te deja exportar ningún archivo del gráfico".

Causa: `DBADialog._export` se guardaba con `self._last` (solo el modo DISEÑO), así
que tras EVALUAR u OPTIMIZAR (que no poblaban `_last`) no exportaba NADA. Fix:
exportar según `_last_plot_kind` ("calc"|"eval") -> imagen siempre + CSV con las
columnas del modo dibujado.

Verifica (offscreen, con QFileDialog/QMessageBox stubeados):
  - modo DISEÑO (_calc): CSV + PNG se escriben.
  - modo EVALUAR (curva sintética): CSV con columnas real/ideal + SVG se escriben.
  - sin gráfico: no escribe archivo y avisa (no crash).

Correr:  QT_QPA_PLATFORM=offscreen python smoke_dba_export.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import dba_dialog
from dba_dialog import DBADialog

fails = []
def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

_tmp = tempfile.mkdtemp(prefix="dbaexp_")
_info = {"n": 0}

# Stubs: QFileDialog devuelve una ruta temporal por formato; QMessageBox.info cuenta.
def _fake_save(parent, title, default, filt):
    ext = default.rsplit(".", 1)[-1]
    return os.path.join(_tmp, f"out.{ext}"), filt
dba_dialog.QFileDialog.getSaveFileName = staticmethod(_fake_save)
dba_dialog.QMessageBox.information = staticmethod(
    lambda *a, **k: _info.__setitem__("n", _info["n"] + 1))
dba_dialog.QMessageBox.warning = staticmethod(lambda *a, **k: None)

def _path(ext):
    return os.path.join(_tmp, f"out.{ext}")

def _fresh(ext):
    p = _path(ext)
    if os.path.exists(p):
        os.remove(p)
    return p

if not getattr(dba_dialog, "_HAS_MPL", False):
    print("  SKIP matplotlib no disponible; el export de gráfico no aplica")
    raise SystemExit(0)

d = DBADialog((5.0, 6.5, 3.0), (3.5, 4.0, 1.5))

# --- sin gráfico todavía: _export avisa y NO escribe ---
_info["n"] = 0
p = _fresh("csv")
d._export("csv")
ck(not os.path.exists(p) and _info["n"] == 1,
   "sin gráfico: no exporta y avisa (no crash)")

# --- modo DISEÑO: _calc puebla _last + _last_plot_kind='calc' ---
d.sb_fmax.setValue(160.0)
d.combo_drive.setCurrentIndex(0)
d._calc()
ck(d._last_plot_kind == "calc", "tras _calc, _last_plot_kind='calc'")
p = _fresh("csv"); d._export("csv")
ok_csv = os.path.exists(p) and os.path.getsize(p) > 0
head = ""
if ok_csv:
    with open(p, encoding="utf-8") as fh:
        head = fh.readline().strip()
ck(ok_csv and head == "freq_hz,cabs_off_db,cabs_on_db",
   f"diseño: CSV escrito con header correcto ({head!r})")
p = _fresh("png"); d._export("png")
ck(os.path.exists(p) and os.path.getsize(p) > 0, "diseño: PNG escrito")

# --- modo EVALUAR: curva sintética en _last_eval + _last_plot_kind='eval' ---
fa = np.linspace(20, 160, 50)
d._last_eval = {
    "freq": fa,
    "total_db_mean_real": 80.0 + 3.0 * np.sin(fa / 10.0),
    "total_db_mean_ideal": 80.0 + np.zeros_like(fa),
}
d._last_plot_kind = "eval"
p = _fresh("csv"); d._export("csv")
ok_csv = os.path.exists(p) and os.path.getsize(p) > 0
head = ""
if ok_csv:
    with open(p, encoding="utf-8") as fh:
        head = fh.readline().strip()
ck(ok_csv and head == "freq_hz,total_real_db,cabs_ideal_db",
   f"evaluar: CSV escrito con columnas real/ideal ({head!r})")
p = _fresh("svg"); d._export("svg")
ck(os.path.exists(p) and os.path.getsize(p) > 0, "evaluar: SVG (imagen) escrito")

print()
print("RESULTADO:", "TODO VERDE" if not fails else f"{len(fails)} FALLARON")
raise SystemExit(1 if fails else 0)
