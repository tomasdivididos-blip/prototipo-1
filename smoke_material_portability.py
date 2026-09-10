"""
smoke_material_portability.py
=============================

Smoke HEADLESS (Qt offscreen) de dos arreglos de materiales (9 Sep 2026),
motivados por el .room del profesor (Control Ale.room):

  A. Limpieza al cargar (`AcousticPanel._prune_face_maps_to_geometry`): el mapa
     {firma->material} acumulaba firmas HUERFANAS de otros frames (tocar el origen
     rompia el material y el usuario reasignaba; las viejas no se borraban). La
     limpieza descarta las firmas que no corresponden a ninguna cara de la
     geometria ACTUAL, sin tocar la malla; si NINGUNA matchea (archivo de otra
     version) no limpia nada.

  B. Embeber materiales propios en el .room (`Material.to_dict` +
     `MaterialLibrary.add_material`): el .room solo guardaba el NOMBRE del
     material; en otra maquina sin ese .json se veia el default. Ahora la
     definicion (alpha por tercio) se embebe y se registra al cargar -> el .room
     es autocontenido.

Correr:
  PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen \\
    /c/Users/aceve/anaconda3/python.exe smoke_material_portability.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
except Exception as e:
    print(f"FATAL: no se pudo crear QApplication: {e}")
    sys.exit(2)

import numpy as np

from geometry import make_room
from viewer import IsoViewer
from acoustic_panel import AcousticPanel
from material_library import Material, MaterialLibrary

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def _custom_mat(name="Panel propio (tercios)", a=0.42):
    thirds = [50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
              800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]
    return Material({"name": name, "category": "propio",
                     "alpha": {str(f): a for f in thirds}})


def test_prune_orphans():
    print("T1  limpieza de firmas huerfanas al cargar (A)")
    v, t, _e, _n = make_room(width=6.0, length=4.0, height=3.0, n_walls=4)
    v = np.asarray(v, float); t = np.asarray(t, int)
    viewer = IsoViewer()
    panel = AcousticPanel(viewer=viewer, get_surface=lambda: (v, t),
                          get_dims_hint=lambda: (6.0, 4.0, 3.0))
    mat = _custom_mat()
    panel._mat_lib.add_material(mat)
    groups = panel._get_face_groups()[0]
    floor = next(g for g in groups if g.kind == "floor")
    # asignacion VIVA (cara real) + 3 HUERFANAS (firmas que no son de ninguna cara)
    panel._face_mat_map.assign(floor.signature, mat.name)
    for k in ("deadbeefdeadbeef", "0011223344556677", "8899aabbccddeeff"):
        panel._face_mat_map.assign(k, mat.name)
    n_before = len(panel._face_mat_map.to_dict())
    dropped = panel._prune_face_maps_to_geometry()
    n_after = len(panel._face_mat_map.to_dict())
    check("descarta las 3 huerfanas, conserva la viva",
          n_before == 4 and n_after == 1 and dropped == 3,
          f"{n_before}->{n_after}")
    check("la cara real sigue resolviendo su material",
          panel._face_mat_map.get(floor.signature) == mat.name)

    # Guarda: si NINGUNA firma matchea la geometria, NO limpia (mismatch version).
    panel2 = AcousticPanel(viewer=IsoViewer(), get_surface=lambda: (v, t),
                           get_dims_hint=lambda: (6.0, 4.0, 3.0))
    panel2._face_mat_map.assign("ffffffffffffffff", mat.name)
    d2 = panel2._prune_face_maps_to_geometry()
    check("guarda: sin matches no limpia nada (evita perder por mismatch)",
          d2 == 0 and len(panel2._face_mat_map.to_dict()) == 1,
          f"dropped={d2}")


def test_embed_material():
    print("\nT2  embeber + registrar material propio (B)")
    mat = _custom_mat(a=0.37)
    blob = mat.to_dict()                       # lo que se embebe en el .room
    check("to_dict preserva nombre y alpha por tercio",
          blob["name"] == mat.name and "alpha" in blob
          and abs(float(blob["alpha"]["125"]) - 0.37) < 1e-9)
    lib = MaterialLibrary("materials")         # biblioteca local (no tiene el propio)
    had = mat.name in lib.names
    added = lib.add_material(Material(blob))    # como hace el loader del .room
    check("se registra si falta (no estaba, se agrego)", (not had) and added)
    idx = lib.names.index(mat.name)
    check("alpha del material registrado coincide (tercios preservados)",
          abs(lib.materials[idx].alpha(125.0) - 0.37) < 1e-9)
    # No pisa un material local existente con el mismo nombre (add-if-missing).
    again = lib.add_material(_custom_mat(a=0.99))
    check("no pisa el existente con el mismo nombre (add-if-missing)",
          again is False
          and abs(lib.materials[lib.names.index(mat.name)].alpha(125.0) - 0.37) < 1e-9)


def test_merge_folder_from_room_dir():
    print("\nT3  cargar materiales de una carpeta junto al .room (merge_folder)")
    import tempfile, json, os
    root = tempfile.mkdtemp(prefix="room_")
    # Estructura: <root>/materiales test/materials/PanelX.json  (subdir con
    # 'material' en el nombre, como 'materiales ale' del profe).
    sub = os.path.join(root, "materiales test", "materials")
    os.makedirs(sub, exist_ok=True)
    mat = _custom_mat(name="Panel del profe X", a=0.55)
    with open(os.path.join(sub, "PanelX.json"), "w", encoding="utf-8") as fh:
        json.dump(mat.to_dict(), fh)
    lib = MaterialLibrary("materials")
    check("el material del profe NO esta en la lib local",
          "Panel del profe X" not in lib.names)
    # Replica del auto-scan del loader: subdirs cuyo nombre contiene 'material'.
    def _matching_subdirs(base):
        out = []
        for e in os.scandir(base):
            if e.is_dir() and "material" in e.name.lower():
                out.append(e.path)
        return out
    cands = [(root, False)]
    for d1 in _matching_subdirs(root):
        cands.append((d1, True))
    added = []
    for folder, rec in cands:
        added += lib.merge_folder(folder, recursive=rec)
    check("se detecta la carpeta y se carga el material propio",
          "Panel del profe X" in added and "Panel del profe X" in lib.names,
          f"agregados={len(added)}")
    idx = lib.names.index("Panel del profe X")
    check("alpha del material cargado es correcto (0.55)",
          abs(lib.materials[idx].alpha(125.0) - 0.55) < 1e-9)


def main():
    print("=" * 64)
    print("smoke_material_portability.py  —  limpieza + embebido de materiales")
    print("=" * 64)
    test_prune_orphans()
    test_embed_material()
    test_merge_folder_from_room_dir()
    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
