"""
bench_capa0_5c.py - Etapa 5c: Capa 0 VISIBLE (tabla + read-out por modo)
=======================================================================
Valida la capa de PRESENTACION de la Etapa 5c (mostrar Delta f_n y xi_n
explicitos), SIN depender de la fisica (ya cubierta por bench_capa0_wiring
W4/W7): formateo de la tabla `ModeTableDialog`, el RT60_n del modo aislado,
el export CSV/TXT, y las ramas de borde (xi=None, RT60=inf, Delta~0).

  T1  RT60_n = 6.908/(xi*2*pi*f)  y  xi<=0 -> inf.
  T2  _rows: Delta con signo; "0.00" cuando |Delta|<5e-3; f efectiva = rigida+Delta.
  T3  xi=None -> columnas xi/RT60 = "—" (guion) en todas las filas.
  T4  export CSV: header correcto + inf/"" limpios + sin signo "+".
  T5  export TXT: mismas filas, ancho fijo, parseables.
  T6  construcciones -> etiqueta de corrimiento maximo presente y correcta.
  T7  sin corrimiento (Delta=0 en todos) -> ninguna celda Delta en negrita.

Correr:  QT_QPA_PLATFORM=offscreen /c/Users/aceve/anaconda3/python.exe bench_capa0_5c.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import tempfile
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from acoustic_panel import ModeTableDialog

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_app = QApplication.instance() or QApplication([])


def make_data(constructions=True, xi_none=False, no_shift=False):
    f_rig = np.array([48.0, 61.5, 77.0, 92.3], dtype=float)
    if no_shift:
        f_eff = f_rig.copy()
    else:
        # modo 0: +0.42, modo 1: 0 (por debajo del umbral 5e-3), modo 2: -1.30,
        # modo 3: +0.004 (por debajo del umbral).
        f_eff = f_rig + np.array([0.42, 0.0, -1.30, 0.004])
    xi = None if xi_none else np.array([0.010, 0.020, 0.0, 0.015])
    return {
        "f_rig": f_rig, "f_eff": f_eff, "dfreq": f_eff - f_rig, "xi": xi,
        "model": "Perturbación de frontera" if constructions else "Sabine por modo (A36)",
        "constructions": constructions,
        "max_abs_shift": float(np.max(np.abs(f_eff - f_rig))),
    }


# --- T1: RT60_n ---
rt = ModeTableDialog._rt60_from_xi(48.0, 0.010)
ref = 6.908 / (0.010 * 2 * math.pi * 48.0)
check("T1 RT60_n formula", abs(rt - ref) < 1e-9, f"{rt:.4f} vs {ref:.4f}")
check("T1 RT60_n xi=0 -> inf", not np.isfinite(ModeTableDialog._rt60_from_xi(48.0, 0.0)))
check("T1 RT60_n xi<0 -> inf", not np.isfinite(ModeTableDialog._rt60_from_xi(48.0, -0.01)))

# --- T2: filas con corrimiento ---
dlg = ModeTableDialog(make_data(constructions=True), parent=None)
rows = dlg._rows()
check("T2 nro de filas", len(rows) == 4, str(len(rows)))
check("T2 Delta modo0 +0.42", rows[0][3] == "+0.42", rows[0][3])
check("T2 Delta modo1 ~0 -> 0.00", rows[1][3] == "0.00", rows[1][3])
check("T2 Delta modo2 -1.30", rows[2][3] == "-1.30", rows[2][3])
check("T2 Delta modo3 sub-umbral -> 0.00", rows[3][3] == "0.00", rows[3][3])
# f efectiva mostrada = rigida + Delta (modo0: 48.00 -> 48.42)
check("T2 f_eff modo0", rows[0][2] == "48.42", rows[0][2])
check("T2 f_rig modo0", rows[0][1] == "48.00", rows[0][1])
# RT60 del modo con xi=0 es infinito -> "∞"
check("T2 RT60 xi=0 -> inf glifo", rows[2][5] == "∞", rows[2][5])
check("T2 xi formato 5 dec", rows[0][4] == "0.01000", rows[0][4])

# --- T3: xi None ---
dlg_none = ModeTableDialog(make_data(xi_none=True), parent=None)
rows_n = dlg_none._rows()
check("T3 xi None -> guion en xi", all(r[4] == "—" for r in rows_n))
check("T3 xi None -> guion en RT60", all(r[5] == "—" for r in rows_n))

# --- T4/T5: export ---
tmp = tempfile.mkdtemp()
csv_path = os.path.join(tmp, "modos.csv")
txt_path = os.path.join(tmp, "modos.txt")


def _fake_getsave(path):
    # Parchea el QFileDialog para no abrir GUI.
    import acoustic_panel as ap_mod
    ap_mod.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (path, ""))


_fake_getsave(csv_path)
dlg._export("csv")
with open(csv_path, encoding="utf-8") as fh:
    csv_lines = fh.read().strip().splitlines()
check("T4 CSV header", csv_lines[0] ==
      "modo_n,f_rigida_hz,f_efectiva_hz,delta_f_hz,xi_n,rt60_n_s", csv_lines[0])
check("T4 CSV nro filas", len(csv_lines) == 5, str(len(csv_lines)))
# modo2: delta -1.30 (mantiene el signo -), xi 0 -> rt inf
row2 = csv_lines[3].split(",")
check("T4 CSV delta negativo preserva signo", row2[3] == "-1.30", row2[3])
check("T4 CSV inf limpio", row2[5] == "inf", row2[5])
# modo0: delta +0.42 -> el "+" se saca en CSV
row0 = csv_lines[1].split(",")
check("T4 CSV delta positivo sin '+'", row0[3] == "0.42", row0[3])

# xi None export -> columnas vacias
_fake_getsave(os.path.join(tmp, "modos_none.csv"))
dlg_none._export("csv")
with open(os.path.join(tmp, "modos_none.csv"), encoding="utf-8") as fh:
    csv_n = fh.read().strip().splitlines()
check("T4 CSV xi None -> celda vacia", csv_n[1].split(",")[4] == "", csv_n[1])

_fake_getsave(txt_path)
dlg._export("txt")
with open(txt_path, encoding="utf-8") as fh:
    txt_lines = fh.read().strip().splitlines()
check("T5 TXT nro filas", len(txt_lines) == 5, str(len(txt_lines)))
check("T5 TXT header tiene modo_n", "modo_n" in txt_lines[0])
check("T5 TXT inf presente", "inf" in txt_lines[3])

# --- T6: etiqueta de corrimiento maximo ---
lbl = dlg._shift_summary_label(make_data(constructions=True))
txt = lbl.text()
check("T6 label menciona modo 2 (max |Delta|=1.30)", "modo 2" in txt, txt)
check("T6 label muestra el par f0->f1", "77.00 → 75.70" in txt, txt)

# --- T7: sin corrimiento -> ninguna celda Delta en negrita ---
dlg_flat = ModeTableDialog(make_data(no_shift=True), parent=None)
bold_deltas = [dlg_flat.table.item(r, 3).font().bold()
               for r in range(dlg_flat.table.rowCount())]
check("T7 sin shift -> Delta no-negrita", not any(bold_deltas))
# con shift, modo0 y modo2 (los que superan umbral) van en negrita
bold_shift = [dlg.table.item(r, 3).font().bold()
              for r in range(dlg.table.rowCount())]
check("T7 con shift -> modo0/modo2 negrita",
      bold_shift == [True, False, True, False], str(bold_shift))

# --- T8: glue del panel `_collect_mode_table` (sin instanciar la GUI) ---
from types import SimpleNamespace
from acoustic_panel import AcousticPanel

p = AcousticPanel.__new__(AcousticPanel)   # sin __init__ (no arma Qt/geometria)
freqs = np.array([48.0, 61.5, 77.0, 92.3])
f_new = freqs + np.array([0.42, 0.0, -1.30, 0.004])
p.modal_result = SimpleNamespace(freqs=freqs)
p._freq_shift_per_mode = f_new
p._xi_per_mode = np.array([0.010, 0.020, 0.0, 0.015])
p._damping_model = "perturbation"
p._construction_map = {"__wall__(0,0,1)": {"kind": "perforated"}}
d = p._collect_mode_table()
check("T8 dfreq = f_new - f_rig",
      np.allclose(d["dfreq"], f_new - freqs), str(d["dfreq"]))
check("T8 f_eff = f_new", np.allclose(d["f_eff"], f_new))
check("T8 constructions=True", d["constructions"] is True)
check("T8 model legible", d["model"] == "Perturbación de frontera", d["model"])
check("T8 max_abs_shift = 1.30", abs(d["max_abs_shift"] - 1.30) < 1e-9,
      f"{d['max_abs_shift']:.4f}")

# sin corrimiento cacheado -> f_eff == f_rig, dfreq 0
p2 = AcousticPanel.__new__(AcousticPanel)
p2.modal_result = SimpleNamespace(freqs=freqs)
p2._freq_shift_per_mode = None
p2._xi_per_mode = np.array([0.01, 0.01, 0.01, 0.01])
p2._damping_model = "a36"
p2._construction_map = {}
d2 = p2._collect_mode_table()
check("T8 sin shift -> dfreq 0", np.allclose(d2["dfreq"], 0.0))
check("T8 sin construcciones -> constructions False", d2["constructions"] is False)
check("T8 modelo a36 legible", d2["model"] == "Sabine por modo (A36)", d2["model"])

# --- T9: exclusion mutua alpha vs construccion (logica del panel) ---
pk = AcousticPanel.__new__(AcousticPanel)
spec_wall = {"kind": "membrane", "mass_per_area": 5.0, "cavity_depth": 0.1}
pk._construction_map = {"wallA": dict(spec_wall)}
# tres parches: sobre wallA sin construccion propia (CONFLICTO), sobre wallB
# (ok), y sobre wallA pero con su propia construccion (NO conflicto).
p_confl = SimpleNamespace(face_signature="wallA", key="patchA1")
p_ok = SimpleNamespace(face_signature="wallB", key="patchB1")
p_own = SimpleNamespace(face_signature="wallA", key="patchA2")
pk._construction_map["patchA2"] = {"kind": "perforated"}
pk._patches = [p_confl, p_ok, p_own]

check("T9 construction_keys", pk._construction_keys() == {"wallA", "patchA2"},
      str(pk._construction_keys()))
confl = pk._patch_finish_conflicts()
check("T9 detecta solo el parche que pisa la construccion",
      confl == [p_confl], str([getattr(c, "key", None) for c in confl]))
changed = pk._resolve_patch_finish_conflicts(interactive=False)
check("T9 resolver (no interactivo) hereda", changed is True)
check("T9 parche heredo la construccion de su cara",
      pk._construction_map.get("patchA1") == spec_wall,
      str(pk._construction_map.get("patchA1")))
check("T9 herencia es COPIA (no alias)",
      pk._construction_map["patchA1"] is not pk._construction_map["wallA"])
check("T9 idempotente: sin conflicto tras heredar",
      pk._resolve_patch_finish_conflicts(interactive=False) is False)

# sin construcciones -> sin claves ni conflictos
pk2 = AcousticPanel.__new__(AcousticPanel)
pk2._construction_map = {}
pk2._patches = [p_ok]
check("T9 sin construcciones -> keys vacio", pk2._construction_keys() == set())
check("T9 sin construcciones -> sin conflicto",
      pk2._patch_finish_conflicts() == [])

# --- Resumen ---
print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
