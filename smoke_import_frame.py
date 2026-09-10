"""
smoke_import_frame.py
=====================

Smoke HEADLESS (Qt offscreen) del arreglo de referencias de frame al importar un
CAD (9 Sep 2026). Reproduce el problema reportado: al importar un recinto
watertight, `set_imported_geometry` recentraba SOLO el receptor y dejaba las
fuentes/muebles varados en el frame anterior (quedaban fuera del recinto).

Fix elegido por el usuario ("trasladar con el recentrado"): al importar, los
objetos ya colocados reciben el MISMO desplazamiento que el receptor. Para una
importacion que es una TRASLACION PURA del recinto, eso los devuelve adentro.
(No arregla rotaciones; ese caso se reubica a mano.)

Se valida:
  1. set_imported_geometry recentra el receptor DENTRO del CAD nuevo.
  2. CONTRAPRUEBA: sin trasladar, fuente y mueble quedan FUERA del CAD nuevo.
  3. Con el traslado por el delta del receptor, fuente y mueble quedan DENTRO.

Correr:
  PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen \\
    /c/Users/aceve/anaconda3/python.exe smoke_import_frame.py
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
import trimesh as tm

from geometry import make_room
from viewer import IsoViewer
from acoustic_panel import AcousticPanel
from furniture import Furniture
from sources import OmniSource
from acoustic_mesh import points_inside_surface

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


def _inside(p, v, t):
    return bool(points_inside_surface(
        np.asarray(p, dtype=float).reshape(1, 3), np.asarray(v, float),
        np.asarray(t, int))[0])


def main():
    print("=" * 64)
    print("smoke_import_frame.py  —  referencias de frame al importar CAD")
    print("=" * 64)

    # Recinto parametrico (frame esquina) [0,6]x[0,8]x[0,3].
    W, L, H = 6.0, 8.0, 3.0
    v1, t1, _e, _n = make_room(width=W, length=L, height=H, n_walls=4)
    v1 = np.asarray(v1, float)
    t1 = np.asarray(t1, int)
    viewer = IsoViewer()
    panel = AcousticPanel(viewer=viewer, get_surface=lambda: (v1, t1),
                          get_dims_hint=lambda: (W, L, H))

    # Receptor en el CENTRO del recinto (asi su delta al recentrar == la
    # traslacion pura del CAD; ver nota del fix).
    c1 = 0.5 * (v1.min(0) + v1.max(0))
    panel.move_receiver_to(float(c1[0]), float(c1[1]), float(c1[2]))
    # Una fuente y un mueble, ambos DENTRO del recinto parametrico.
    panel.sources.add(OmniSource((1.5, 2.0, 1.2), label="S1"))
    panel.furniture.append(Furniture("box", position=(2.0, 3.0, 0.45),
                                     size=(0.6, 0.6, 0.9)))
    src0 = tuple(panel.sources.sources[0].position)
    fur0 = tuple(panel.furniture[0].position)
    check("fuente dentro del recinto parametrico (setup)", _inside(src0, v1, t1))
    check("mueble dentro del recinto parametrico (setup)", _inside(fur0, v1, t1))

    # Importar un CAD = MISMO recinto TRASLADADO lejos (traslacion pura T).
    T = np.array([10.0, 5.0, 0.0])
    mesh2 = tm.Trimesh(vertices=v1 + T, faces=t1, process=False)
    v2, t2 = np.asarray(mesh2.vertices, float), np.asarray(mesh2.faces, int)

    # CONTRAPRUEBA: antes de trasladar los objetos, quedan FUERA del CAD nuevo.
    check("CONTRAPRUEBA: fuente fuera del CAD nuevo (sin traslado)",
          not _inside(src0, v2, t2))
    check("CONTRAPRUEBA: mueble fuera del CAD nuevo (sin traslado)",
          not _inside(fur0, v2, t2))

    # set_imported_geometry recentra el receptor al centro del CAD nuevo.
    rcv_before = np.asarray(panel.receiver, float)
    panel.set_imported_geometry(mesh2)
    rcv_after = np.asarray(panel.receiver, float)
    delta = rcv_after - rcv_before
    check("el receptor quedo DENTRO del CAD nuevo (recentrado)",
          _inside(rcv_after, v2, t2),
          f"rcv={tuple(round(x,2) for x in rcv_after)}")

    # FIX: trasladar los objetos por el MISMO delta del receptor (lo que hace
    # _shift_scene_objects(delta, include_receiver=False) en main.py).
    for s in panel.sources.sources:
        s.position = tuple((np.asarray(s.position, float) + delta).tolist())
    for m in panel.furniture:
        m.position = tuple((np.asarray(m.position, float) + delta).tolist())

    src1 = tuple(panel.sources.sources[0].position)
    fur1 = tuple(panel.furniture[0].position)
    check("con el traslado la fuente queda DENTRO del CAD nuevo",
          _inside(src1, v2, t2), f"S1={tuple(round(x,2) for x in src1)}")
    check("con el traslado el mueble queda DENTRO del CAD nuevo",
          _inside(fur1, v2, t2), f"box={tuple(round(x,2) for x in fur1)}")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
