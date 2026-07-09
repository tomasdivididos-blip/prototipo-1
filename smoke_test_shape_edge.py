"""smoke_test_shape_edge.py
=========================

Smoke test de la lógica de "fijar longitud de arista" del dibujo de planta
(`ShapeCanvas.edge_length` / `set_edge_length`).

Regla: el PRIMER vértice de la arista queda fijo; el segundo se desliza sobre
la misma dirección hasta la longitud pedida (no se snapea a la grilla).

Headless (QApplication sin show). Uso: python smoke_test_shape_edge.py
"""

from __future__ import annotations
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"
from PyQt5.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from shape_dialog import ShapeCanvas

TESTS = []
def test(fn):
    TESTS.append(fn); return fn


def sq():
    # cuadrado 4 x 3, CCW
    return ShapeCanvas(initial_polygon=[(0, 0), (4, 0), (4, 3), (0, 3)])


@test
def t1_edge_length_axis():
    c = sq()
    assert abs(c.edge_length(0) - 4.0) < 1e-9, c.edge_length(0)   # (0,0)->(4,0)
    assert abs(c.edge_length(1) - 3.0) < 1e-9, c.edge_length(1)   # (4,0)->(4,3)
    return "edge_length de aristas axiales OK (4 y 3 m)"


@test
def t2_resize_keeps_start_moves_end():
    c = sq()
    c.set_edge_length(0, 6.0)            # arista (0,0)->(4,0), dir +x
    assert c.polygon[0] == (0.0, 0.0), f"el inicio se movió: {c.polygon[0]}"
    assert abs(c.polygon[1][0] - 6.0) < 1e-9 and abs(c.polygon[1][1]) < 1e-9, \
        f"el fin no quedó en (6,0): {c.polygon[1]}"
    assert abs(c.edge_length(0) - 6.0) < 1e-9
    return "inicio fijo, fin desliza en +x: (4,0)->(6,0), L=6"


@test
def t3_resize_diagonal():
    # arista (0,0)->(3,4): L=5, dir (0.6,0.8). Fijar L=10 -> (6,8).
    c = ShapeCanvas(initial_polygon=[(0, 0), (3, 4), (-2, 4)])
    assert abs(c.edge_length(0) - 5.0) < 1e-9
    c.set_edge_length(0, 10.0)
    assert abs(c.polygon[1][0] - 6.0) < 1e-9 and abs(c.polygon[1][1] - 8.0) < 1e-9, \
        f"esperaba (6,8): {c.polygon[1]}"
    return "diagonal 3-4-5: fin (3,4)->(6,8) al fijar L=10 (misma dirección)"


@test
def t4_shrink_and_wraparound():
    c = sq()
    # ultima arista (idx 3): (0,3)->(0,0), dir (0,-1). Achicar a 1 -> (0,2).
    c.set_edge_length(3, 1.0)
    assert c.polygon[3] == (0.0, 3.0), "el inicio de la última arista debe quedar fijo"
    assert abs(c.polygon[0][0]) < 1e-9 and abs(c.polygon[0][1] - 2.0) < 1e-9, \
        f"esperaba mover polygon[0] a (0,2): {c.polygon[0]}"
    return "arista que cierra (3->0): mueve polygon[0] (0,0)->(0,2)"


@test
def t5_degenerate_guard():
    c = ShapeCanvas(initial_polygon=[(1, 1), (1, 1), (2, 2)])  # arista 0 degenerada
    before = list(c.polygon)
    c.set_edge_length(0, 5.0)            # no debe crashear ni mover (sin dirección)
    assert c.polygon == before, "no debería tocar una arista degenerada"
    c.set_edge_length(0, -3.0)           # longitud no positiva: ignorar
    assert c.polygon == before
    return "aristas degeneradas / longitud <=0 ignoradas sin crash"


def run():
    ok = 0
    for fn in TESTS:
        try:
            print(f"  [OK]   {fn.__name__}: {fn()}")
            ok += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{ok}/{len(TESTS)} tests OK")
    return ok == len(TESTS)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
