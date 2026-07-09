"""smoke_test_section_edit.py
===========================

Smoke test de las dos features del editor de cortes laterales (paredes):
  1. Fijar la ALTURA exacta de un punto del perfil (`ProfileCanvas.set_point_height`):
     editable mueve, pinneado se ignora, clamp a [0, ymax].
  2. Pared opuesta: selector Libre/Espejo/Igual (`SectionWizard._on_opp_changed`).
     Espejo = (1-t); Igual = copia directa (t).

Headless (QApplication sin show). Uso: python smoke_test_section_edit.py
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

from section_dialog import ProfileCanvas, SectionWizard

TESTS = []
def test(fn):
    TESTS.append(fn); return fn


@test
def t1_set_height_editable_end():
    c = ProfileCanvas(length=5.0, ymax=6.0, grid=0.5,
                      z_start=3.0, z_end=3.0, pin_start=True, pin_end=False)
    # points = [[0,3],[5,3]]; idx1 = extremo final, editable (pin_end False)
    c.set_point_height(1, 4.2)
    assert abs(c.points[1][1] - 4.2) < 1e-9, c.points[1]
    return "altura del extremo libre fijada a 4.20 (sin snap)"


@test
def t2_pinned_start_ignored():
    c = ProfileCanvas(5.0, pin_start=True, pin_end=False)
    z0 = c.points[0][1]
    c.set_point_height(0, 5.0)            # inicio pinneado -> no cambia
    assert c.points[0][1] == z0, "el punto pinneado no debería moverse"
    assert c._is_pinned(0) and not c._is_pinned(len(c.points) - 1)
    return "punto de esquina pinneado: ignorado (lo manda el rim)"


@test
def t3_clamp_to_ymax():
    c = ProfileCanvas(5.0, ymax=6.0, pin_end=False)
    c.set_point_height(1, 99.0)
    assert c.points[1][1] == 6.0, c.points[1]
    c.set_point_height(1, -10.0)
    assert c.points[1][1] == 0.0, c.points[1]
    return "altura clampeada a [0, ymax]"


@test
def t4_interior_point():
    c = ProfileCanvas(5.0, ymax=6.0, pin_end=False)
    c.points.append([2.5, 3.0]); c.points.sort(key=lambda p: p[0])
    idx = next(k for k, (x, z) in enumerate(c.points) if abs(x - 2.5) < 1e-9)
    assert not c._is_pinned(idx)
    c.set_point_height(idx, 4.0)
    assert abs(c.points[idx][1] - 4.0) < 1e-9
    return "punto interior editable: altura fijada"


def _wiz():
    rect = [(-2.5, -2.0), (2.5, -2.0), (2.5, 2.0), (-2.5, 2.0)]
    w = SectionWizard(rect, default_height=3.0, grid=0.5)
    # dibujar pared 0 con pendiente (0->3, L->4) y guardarla
    w.canvas.points = [[0.0, 3.0], [w.lengths[0], 4.0]]
    w._store_current()
    w._load_wall(2)              # pared opuesta a la 0
    return w


@test
def t5_opposite_mirror():
    w = _wiz()
    w._on_opp_changed(1)         # Espejo (1-t)
    prof = w.canvas.get_profile()
    assert abs(prof[0][1] - 4.0) < 1e-9 and abs(prof[-1][1] - 3.0) < 1e-9, prof
    assert w.canvas.enabled_draw is False, "espejo debe bloquear el dibujo"
    return "espejo: perfil [3,4] -> [4,3] (reflejado) y bloqueado"


@test
def t6_opposite_equal():
    w = _wiz()
    w._on_opp_changed(2)         # Igual (copia directa)
    prof = w.canvas.get_profile()
    assert abs(prof[0][1] - 3.0) < 1e-9 and abs(prof[-1][1] - 4.0) < 1e-9, prof
    assert w.canvas.enabled_draw is False, "igual debe bloquear el dibujo"
    w._on_opp_changed(0)         # Libre -> desbloquea
    assert w.canvas.enabled_draw is True
    return "igual: perfil [3,4] copiado tal cual; Libre desbloquea"


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
