"""
bench_capa0_5d.py - Etapa 5d: editor de construccion, modelos NUEVOS en la GUI
=============================================================================
Valida que el `ConstructionEditorDialog` expone correctamente los dos modelos
que ya existian en impedance.py pero no estaban en la GUI: el resonador de
Helmholtz (cuello+cavidad) y la pila multicapa (TMM). Chequea la traduccion
de unidades de la UI al `spec`, que `build_surface` los reconstruye, la
resonancia/absorcion fisica, la edicion de la pila (agregar/quitar/mover), el
round-trip por `_load_spec` y la equivalencia de una multicapa de 1 capa con
el constructor `porous()` ya validado.

  H1  Helmholtz: spec + conversiones de unidad (cm2->m2, mm->m, L->m3).
  H2  Helmholtz: build_surface -> beta finita.
  H3  Helmholtz: hint de resonancia = f0 = (c/2pi) sqrt(S/(l_eff V)) analitico.
  H4  Helmholtz: pico de alpha(f) cerca de f0 (fisica del resonador).
  H5  Helmholtz: round-trip UI -> spec -> UI.
  M1  Multicapa: 3 capas (poroso/aire/poroso-db) en orden superficie->fondo.
  M2  Multicapa: build_surface -> alpha finita en [0,1].
  M3  Multicapa: mover capa (up) reordena la pila.
  M4  Multicapa: quitar capa.
  M5  Multicapa vacia -> ValueError controlado.
  M6  Multicapa: round-trip UI -> spec -> UI (n capas + espesores).
  M7  Multicapa 1 capa porosa == constructor porous() (beta identica).
  L1  spec_label no rompe para ambos.

Correr:  QT_QPA_PLATFORM=offscreen /c/Users/aceve/anaconda3/python.exe bench_capa0_5d.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtWidgets import QApplication

import impedance as imp
from acoustic_panel import ConstructionEditorDialog

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_app = QApplication.instance() or QApplication([])
C0 = 343.0

# ------------------------------------------------------------------ Helmholtz
d = ConstructionEditorDialog()
d.combo_type.setCurrentIndex(4)          # Helmholtz (cuello+cavidad)
d._sync()
d.h_S.setValue(20.0); d.h_l.setValue(50.0); d.h_V.setValue(5.0); d.h_A.setValue(1.0)
spec_h = d._current_spec()
check("H1 spec type helmholtz", spec_h["type"] == "helmholtz", str(spec_h))
check("H1 S cm2->m2", abs(spec_h["neck_area"] - 20e-4) < 1e-12)
check("H1 l mm->m", abs(spec_h["neck_length"] - 50e-3) < 1e-12)
check("H1 V L->m3", abs(spec_h["cavity_volume"] - 5e-3) < 1e-12)
check("H1 A m2", abs(spec_h["wall_area"] - 1.0) < 1e-12)

surf_h = imp.build_surface(spec_h)
fg = np.geomspace(20.0, 500.0, 400)
bh = surf_h.beta(fg)
check("H2 beta finita", bool(np.all(np.isfinite(bh))))

S, V, l = spec_h["neck_area"], spec_h["cavity_volume"], spec_h["neck_length"]
dd = 2.0 * np.sqrt(S / np.pi); leff = l + 0.85 * dd
f0 = (C0 / (2 * np.pi)) * np.sqrt(S / (leff * V))
check("H3 hint = f0 analitico", f"{f0:.0f}" in d._resonance_hint(spec_h),
      d._resonance_hint(spec_h) + f"  (f0={f0:.1f})")

a_h = surf_h.alpha_random(fg)
f_peak = fg[int(np.argmax(a_h))]
check("H4 pico de alpha cerca de f0",
      0.6 * f0 <= f_peak <= 1.6 * f0, f"f_peak={f_peak:.1f}, f0={f0:.1f}")

d_rt = ConstructionEditorDialog(spec=spec_h)
spec_h2 = d_rt._current_spec()
check("H5 round-trip helmholtz",
      all(abs(spec_h[k] - spec_h2[k]) < 1e-12
          for k in ("neck_area", "neck_length", "cavity_volume", "wall_area")),
      str((spec_h, spec_h2)))

# ------------------------------------------------------------------ Multicapa
d3 = ConstructionEditorDialog()
d3.combo_type.setCurrentIndex(5)          # Multicapa (pila TMM)
d3._sync()
d3.ml_type.setCurrentIndex(0); d3.ml_th.setValue(50.0); d3.ml_sigma.setValue(15000.0); d3._ml_add_layer()
d3.ml_type.setCurrentIndex(1); d3.ml_th.setValue(100.0); d3._ml_add_layer()
d3.ml_type.setCurrentIndex(0); d3.ml_model.setCurrentIndex(1); d3.ml_th.setValue(30.0); d3._ml_add_layer()
spec_m = d3._current_spec()
check("M1 tres capas", len(spec_m["layers"]) == 3, str(spec_m))
check("M1 capa1 poroso miki", spec_m["layers"][0]["type"] == "porous"
      and spec_m["layers"][0]["model"] == "miki")
check("M1 capa2 aire", spec_m["layers"][1]["type"] == "air")
check("M1 capa3 poroso db", spec_m["layers"][2].get("model") == "db")

surf_m = imp.build_surface(spec_m)
a_m = surf_m.alpha_random(np.geomspace(20.0, 500.0, 120))
check("M2 alpha finita en [0,1]",
      bool(np.all(np.isfinite(a_m))) and a_m.min() >= -1e-9 and a_m.max() <= 1.0001,
      f"[{a_m.min():.3f}, {a_m.max():.3f}]")

d3.ml_list.setCurrentRow(2); d3._ml_move(-1)
check("M3 move: capa db sube a idx1", d3._ml_layers[1].get("model") == "db",
      str([ly.get("model", ly["type"]) for ly in d3._ml_layers]))
d3.ml_list.setCurrentRow(0); d3._ml_del_layer()
check("M4 del: quedan 2 capas", len(d3._ml_layers) == 2)

d4 = ConstructionEditorDialog()
d4.combo_type.setCurrentIndex(5); d4._sync()
try:
    d4._current_spec(); check("M5 vacia levanta ValueError", False)
except ValueError:
    check("M5 vacia levanta ValueError", True)

d5 = ConstructionEditorDialog(spec=spec_m)
spec_m2 = d5._current_spec()
check("M6 round-trip n capas", len(spec_m2["layers"]) == 3)
check("M6 round-trip espesores",
      all(abs(spec_m["layers"][i]["thickness"] - spec_m2["layers"][i]["thickness"]) < 1e-12
          for i in range(3)))

# M7: una multicapa de 1 sola capa porosa (miki 50mm) == constructor porous()
d6 = ConstructionEditorDialog()
d6.combo_type.setCurrentIndex(5); d6._sync()
d6.ml_type.setCurrentIndex(0); d6.ml_model.setCurrentIndex(0)
d6.ml_th.setValue(50.0); d6.ml_sigma.setValue(15000.0); d6._ml_add_layer()
surf_ml1 = imp.build_surface(d6._current_spec())
surf_por = imp.porous(15000.0, 0.050, model="miki")
fq = np.geomspace(20.0, 500.0, 80)
b_ml1 = surf_ml1.beta(fq); b_por = surf_por.beta(fq)
check("M7 multicapa 1 capa == porous()",
      np.allclose(b_ml1, b_por, rtol=1e-9, atol=1e-12),
      f"max|dif|={np.max(np.abs(b_ml1 - b_por)):.2e}")

# ------------------------------------------------------------------ etiquetas
check("L1 spec_label helmholtz", "Helmholtz" in imp.spec_label(spec_h),
      imp.spec_label(spec_h))
check("L1 spec_label multicapa", "multicapa" in imp.spec_label(spec_m).lower(),
      imp.spec_label(spec_m))

# --- Resumen ---
print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
