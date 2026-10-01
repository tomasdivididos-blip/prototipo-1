"""
bench_impedance_defaults_wiring.py - GUI wiring del link material->impedancia
=============================================================================
Valida (headless) el WallConstructionsDialog con las sugerencias automaticas:
mostrar sugerencia/aviso, y el boton «Aplicar sugerencias» que las convierte en
impedancias asignadas (sin pisar las manuales ni tocar los inespecificos).

Correr:  QT_QPA_PLATFORM=offscreen python bench_impedance_defaults_wiring.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from PyQt5.QtWidgets import QApplication

import impedance_defaults as idf
from acoustic_panel import WallConstructionsDialog

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_app = QApplication.instance() or QApplication([])

# tres paredes: A con sugerencia poroso, B inespecifica (aviso), C ya asignada.
groups = [SimpleNamespace(signature="A", label="Pared A", area=10.0, normal=(1, 0, 0)),
          SimpleNamespace(signature="B", label="Pared B", area=8.0, normal=(0, 1, 0)),
          SimpleNamespace(signature="C", label="Pared C", area=6.0, normal=(0, 0, 1))]
spec_A = {"type": "porous", "sigma": 15000.0, "thickness": 0.05, "model": "miki",
          "air_gap": 0.0}
info_A = idf.MaterialImpedance(spec=spec_A, has_model=True, kind="porous",
                               justification="contiene «lana» -> poroso Miki")
info_B = idf.MaterialImpedance(nonspecific=True, kind="flat",
                               justification="alpha plano -> sin modelo")
default_specs = {"A": spec_A}
default_info = {"A": info_A, "B": info_B}
manual = {"C": {"type": "membrane", "mass_per_area": 5.0, "cavity_depth": 0.1}}

dlg = WallConstructionsDialog(groups, manual, default_specs=default_specs,
                              default_info=default_info)

check("W1 arranca con la manual C intacta", dlg.result_map.get("C") is not None)
check("W1 la sugerencia A NO esta aplicada aun", "A" not in dlg.result_map)
check("W1 lista tiene 3 filas", dlg.list_faces.count() == 3)
# el label resumen menciona la sugerencia y el aviso
txt = dlg.lbl_sug.text().lower()
check("W1 resumen menciona sugerencia y sin-modelo",
      "sugerencia" in txt and "sin modelo" in txt, dlg.lbl_sug.text())

# aplicar todas las sugerencias
dlg._apply_suggestions()
check("W2 tras aplicar, A queda asignada con el spec sugerido",
      dlg.result_map.get("A") == spec_A, str(dlg.result_map.get("A")))
check("W2 B (inespecifica) NO se aplico (no hay sugerencia)",
      "B" not in dlg.result_map)
check("W2 C (manual) intacta", dlg.result_map.get("C") == manual["C"])
check("W2 aplicar es COPIA (no alias del default)",
      dlg.result_map["A"] is not spec_A)

# aplicar de nuevo no rompe ni pisa
dlg._apply_suggestions()
check("W3 idempotente: A sigue con su spec", dlg.result_map.get("A") == spec_A)

# no pisa una asignada manual aunque tenga sugerencia
dlg2 = WallConstructionsDialog(groups, {"A": manual["C"]},
                               default_specs=default_specs, default_info=default_info)
dlg2._apply_suggestions()
check("W4 no pisa una impedancia ya asignada con la sugerencia",
      dlg2.result_map["A"] == manual["C"])

# W5: hover sobre una fila emite el OBJETO de esa superficie (para resaltar 3D).
patch = SimpleNamespace(key="P1", label="parche test", area=2.0,
                        polygon_uv=lambda: [(0, 0), (1, 0), (1, 1)])
dlg3 = WallConstructionsDialog(groups, {}, patches=[patch],
                               default_specs=default_specs, default_info=default_info)
got = []
dlg3.hovered.connect(lambda o: got.append(o))
# fila 0 = Pared A (grupo), fila con el parche al final
it_A = dlg3.list_faces.item(0)
dlg3._on_item_hovered(it_A)
check("W5 hover pared A emite el FaceGroup A", got and got[-1] is groups[0],
      str(got[-1]))
it_P = dlg3.list_faces.item(dlg3.list_faces.count() - 1)
dlg3._on_item_hovered(it_P)
check("W5 hover parche emite el AbsorptionPatch", got[-1] is patch)
dlg3._on_item_hovered(None)
check("W5 hover vacio emite None", got[-1] is None)
check("W5 _obj_by_key mapea clave->objeto",
      dlg3._obj_by_key["A"] is groups[0] and dlg3._obj_by_key["P1"] is patch)

print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
