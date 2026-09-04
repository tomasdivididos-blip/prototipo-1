"""
bench_material_form.py - material propio por tercios de octava (pedido profesor)
================================================================================
Valida (a) que Material.alpha(f) HONRE la resolucion de tercios de octava sin
regresionar los materiales de catalogo (octava), y (b) el formulario nuevo
`MaterialFormDialog` (recoleccion de casillas, armado del dict, validaciones).

  M1  material de octava (8 bandas): alpha en las octavas = valores cargados
      (sin regresion; _alpha == _alpha_table para catalogo completo).
  M2  material en tercios: alpha(160 Hz) = el valor CARGADO a 160 (no el
      interpolado octava 125-250) -> la resolucion fina se preserva.
  M3  tercios ralos: interpola entre bandas cargadas, clampa afuera.
  M4  formulario: _collect_alpha lee casillas (coma/punto, clamp 0..1, vacias
      fuera); _on_save arma result_data (alpha dict str, categoria/source),
      y valida nombre + al menos una banda.
  M5  round-trip: el dict del formulario -> Material -> alpha(f) honra tercios.

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_material_form.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PyQt5.QtWidgets import QApplication
from material_library import Material
import face_materials as fm

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_app = QApplication.instance() or QApplication([])
# Silenciar los popups (no bloquear en offscreen).
fm.QMessageBox.warning = staticmethod(lambda *a, **k: None)
fm.QMessageBox.information = staticmethod(lambda *a, **k: None)

# --- M1: octava, sin regresion ---
coefs = [0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.55, 0.60]  # 63..8000
mo = Material({"name": "oct", "absorption_coef": coefs})
octs = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
check("M1 alpha en octavas = cargado",
      all(abs(mo.alpha(b) - c) < 1e-9 for b, c in zip(octs, coefs)))
check("M1 alpha entre bandas queda acotado",
      coefs[2] <= mo.alpha(354) <= coefs[3])   # 354 Hz entre 250 y 500

# --- M2: tercios, preserva resolucion ---
# Curva con un valor DISTINTO al interpolado octava en 160 Hz.
third = {"125": 0.10, "160": 0.80, "200": 0.12, "250": 0.15}
mt = Material({"name": "third", "alpha": third})
check("M2 alpha(160) = valor cargado (preserva tercio)",
      abs(mt.alpha(160) - 0.80) < 1e-9, f"{mt.alpha(160):.3f}")
# El colapso a octava (comportamiento viejo) daria algo cercano a interpolar
# 125->250, MUY por debajo de 0.8; confirmamos que NO pasa eso.
check("M2 no colapsa a octava", mt.alpha(160) > 0.5, f"{mt.alpha(160):.3f}")

# --- M3: tercios ralos ---
sparse = {"100": 0.10, "500": 0.50}
ms = Material({"name": "sparse", "alpha": sparse})
check("M3 clamp por debajo", abs(ms.alpha(50) - 0.10) < 1e-9)
check("M3 clamp por encima", abs(ms.alpha(5000) - 0.50) < 1e-9)
check("M3 interpola en el medio", 0.10 < ms.alpha(250) < 0.50, f"{ms.alpha(250):.3f}")

# --- M4: formulario ---
dlg = fm.MaterialFormDialog(parent=None)
check("M4 tiene 21 casillas de tercio", len(dlg._cells) == 21, str(len(dlg._cells)))
# completar algunas (coma decimal, un valor fuera de rango para el clamp)
dlg._cells[125].setText("0,10")
dlg._cells[160].setText("0.8")
dlg._cells[200].setText("1.5")     # se clampa a 1.0
dlg._cells[250].setText("")        # vacia -> fuera
a = dlg._collect_alpha()
check("M4 coma decimal", abs(a.get(125, -1) - 0.10) < 1e-9)
check("M4 clamp a 1.0", abs(a.get(200, -1) - 1.0) < 1e-9)
check("M4 casilla vacia excluida", 250 not in a)
# guardar sin nombre -> no arma result_data
dlg.ed_name.setText("")
dlg._on_save()
check("M4 sin nombre -> result_data None", dlg.result_data is None)
# guardar OK
dlg.ed_name.setText("Panel medido")
dlg.ed_notes.setPlainText("Cámara reverberante, ISO 354, 12 m2.")
dlg._on_save()
rd = dlg.result_data
check("M4 result_data armado", rd is not None)
check("M4 categoria Personalizado", rd["category"] == "Personalizado")
check("M4 source Medicion propia", rd["source"] == "Medición propia")
check("M4 notas -> description", "ISO 354" in rd["description"])
check("M4 alpha claves str", all(isinstance(k, str) for k in rd["alpha"]))
check("M4 alpha incluye las cargadas", set(rd["alpha"]) == {"125", "160", "200"},
      str(sorted(rd["alpha"])))

# --- M5: round-trip formulario -> Material ---
m5 = Material(rd)
check("M5 round-trip honra tercio(160)", abs(m5.alpha(160) - 0.8) < 1e-9,
      f"{m5.alpha(160):.3f}")

# --- Resumen ---
print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
