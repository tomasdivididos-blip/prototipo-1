"""smoke_test_undo.py
====================

Smoke test del undo/redo GLOBAL por snapshot (ctrl+z / ctrl+y, limite 10).

Verifica la mecanica nueva de `MainWindow`:
  1. Cambio de geometria -> 1 snapshot; undo vuelve al baseline; redo re-aplica.
  2. El stack se topa en UNDO_LIMIT (10) acciones.
  3. Alta de fuente -> undo la quita; redo la repone (estado acustico completo).
  4. Asignacion de material -> el dirty-check del polling la captura y se deshace.
  5. _maybe_snapshot sin cambios = no-op (no apila basura).

Headless: usa QApplication pero nunca llama .show(). El timer de polling no
corre (no hay event loop); se invoca _maybe_snapshot a mano -> determinista.

Uso: python smoke_test_undo.py
"""

from __future__ import annotations

import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
except Exception as e:
    print(f"FATAL: no se pudo crear QApplication: {e}")
    sys.exit(2)

import main as m


def dims(win):
    p = win.controls.get_params()
    return (round(float(p["width"]), 4),
            round(float(p["length"]), 4),
            round(float(p["height"]), 4))


def set_dim(win, key, value):
    p = dict(win.controls.get_params())
    p[key] = value
    win.controls.set_params(p)
    win._maybe_snapshot(force=True)


TESTS = []
def test(fn):
    TESTS.append(fn); return fn


@test
def t1_geometry_undo_redo():
    win = m.MainWindow()
    assert win._last_state is not None, "no hay baseline"
    base = dims(win)
    assert len(win._undo) == 0

    set_dim(win, "width", float(win.controls.get_params()["width"]) + 1.0)
    assert len(win._undo) == 1, f"esperaba 1 snapshot, hay {len(win._undo)}"
    changed = dims(win)
    assert changed != base

    win.undo()
    assert dims(win) == base, f"undo no restauro: {dims(win)} != {base}"
    assert len(win._redo) == 1

    win.redo()
    assert dims(win) == changed, f"redo no re-aplico: {dims(win)} != {changed}"
    return f"baseline {base} -> {changed} -> undo {base} -> redo {changed}"


@test
def t2_limit_10():
    win = m.MainWindow()
    # 15 cambios REALES (alterno dos alturas distintas para que cada set sea
    # un cambio efectivo, robusto al paso del slider).
    for i in range(15):
        set_dim(win, "height", 3.5 if (i % 2 == 0) else 2.5)
    assert len(win._undo) == m.UNDO_LIMIT, (
        f"el stack no se topo en {m.UNDO_LIMIT}: hay {len(win._undo)}")
    # y siguen siendo deshacibles hasta el limite
    n = len(win._undo)
    for _ in range(n):
        win.undo()
    assert len(win._undo) == 0
    return f"15 cambios reales -> stack topado en {n} (limite {m.UNDO_LIMIT})"


@test
def t3_source_add_undo():
    win = m.MainWindow()
    n0 = len(win.acoustic.sources)
    win.acoustic.add_source_at(1.0, 1.0, 1.2)
    win._maybe_snapshot(force=True)
    n1 = len(win.acoustic.sources)
    assert n1 == n0 + 1, f"no se agrego la fuente: {n0} -> {n1}"

    win.undo()
    assert len(win.acoustic.sources) == n0, (
        f"undo no quito la fuente: {len(win.acoustic.sources)} != {n0}")
    win.redo()
    assert len(win.acoustic.sources) == n1, (
        f"redo no repuso la fuente: {len(win.acoustic.sources)} != {n1}")
    return f"fuentes {n0} -> add {n1} -> undo {n0} -> redo {n1}"


@test
def t4_material_dirty_check():
    """El cambio de material NO pasa por main.py; lo captura el dirty-check."""
    win = m.MainWindow()
    ap = win.acoustic
    fm = getattr(ap, "_face_mat_map", None)
    if fm is None:
        return "SKIP (no hay _face_mat_map en este build)"
    before = win._capture_state()
    # mutar el default del mapa de materiales (cambio de estado acustico real)
    fm.default = "ladrillo" if fm.default != "ladrillo" else "madera"
    after = win._capture_state()
    assert after != before, "el cambio de material no se refleja en el snapshot"
    # simular el poll (force=False, sin actividad reciente -> snapshot)
    win._last_change_t = 0.0
    win._maybe_snapshot(force=False)
    assert len(win._undo) == 1, f"el poll no capturo el material: {len(win._undo)}"
    win.undo()
    assert win.acoustic._face_mat_map.default == before["acoustic"]["face_materials"].get("default", ""), \
        "undo no restauro el material"
    return "cambio de material capturado por dirty-check y deshecho"


@test
def t5_noop_snapshot():
    win = m.MainWindow()
    before = len(win._undo)
    win._maybe_snapshot(force=True)   # sin cambios
    assert len(win._undo) == before, "un snapshot sin cambios apilo basura"
    return "snapshot sin cambios = no-op (OK)"


def run():
    ok = 0
    for fn in TESTS:
        try:
            msg = fn()
            print(f"  [OK]   {fn.__name__}: {msg}")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{ok}/{len(TESTS)} tests OK")
    return ok == len(TESTS)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
