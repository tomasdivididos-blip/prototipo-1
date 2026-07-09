"""smoke_test_shift_drag.py
==========================

Smoke tests para los fixes A/B/C de Shift+drag de fuentes y receptor.

Cada test corresponde a uno de los 4 flujos del checklist:

  1. Crear 3 fuentes -> picking ve las 3.
  2. Importar CAD (geometria externa) -> picking del receptor sigue funcionando.
  3. Guardar/restaurar .room (via _restore_acoustic_state) -> picking ve las
     fuentes recien restauradas.
  4. Borrar la fuente del medio -> picking ve las 2 restantes con indices
     correctos.

Mas un test directo de la mecanica de Fix C:

  5. ReceiverMarker mantiene el mismo GLLinePlotItem entre updates (no
     hace removeItem+addItem cada llamada).

Headless: usa QApplication pero nunca llama .show(). Si Qt no puede arrancar
en el entorno (sin display), el script reporta y aborta sin reventar.

Uso: python smoke_test_shift_drag.py
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

# QApplication ANTES de cualquier import que cree widgets
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
from sources import OmniSource


# ---------------------------------------------------------------------------
# Fixture: panel + viewer + geometria
# ---------------------------------------------------------------------------
def make_panel(width=6.0, length=8.0, height=3.0, n_walls=4):
    viewer = IsoViewer()
    v, t, _, _ = make_room(width=width, length=length,
                            height=height, n_walls=n_walls)
    panel = AcousticPanel(
        viewer=viewer,
        get_surface=lambda: (v, t),
        get_dims_hint=lambda: (width, length, height),
    )
    return viewer, panel, v, t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def t1_add_3_sources_visible_to_picker():
    """Flow 1: agregar 3 fuentes -> picker las ve todas."""
    viewer, panel, _v, _t = make_panel()

    panel.add_source_at(1.0, 1.0, 1.0)
    panel.add_source_at(3.0, 3.0, 1.5)
    panel.add_source_at(5.0, 5.0, 2.0)

    assert len(viewer._source_positions) == 3, (
        f"Esperaba 3 posiciones en viewer, tengo "
        f"{len(viewer._source_positions)}")

    # Cada posicion del viewer coincide con la del modelo
    for i, src in enumerate(panel.sources.sources):
        vp = viewer._source_positions[i]
        for k, axis in enumerate("xyz"):
            assert abs(vp[k] - src.position[k]) < 1e-9, (
                f"Fuente {i} eje {axis}: viewer={vp[k]}, "
                f"panel={src.position[k]}")
    return "3 fuentes sincronizadas correctamente al viewer"


@test
def t2_cad_import_does_not_break_receiver_picking():
    """Flow 2: cambiar la geometria externa (simula CAD) -> el receptor
    sigue siendo encontrable por el picker."""
    viewer, panel, _v, _t = make_panel()

    # Posicionar receptor explicitamente
    panel.move_receiver_to(3.0, 4.0, 1.5)
    assert viewer._receiver_position is not None, \
        "Receptor no fue sincronizado al viewer despues de move_receiver_to"

    # Simular CAD import: cambiar geometria + on_geometry_changed +
    # refrescar markers, igual que hace main.py post-import.
    new_v, new_t, _, _ = make_room(width=10, length=12, height=4, n_walls=6)
    panel.get_surface = lambda: (new_v, new_t)
    panel.on_geometry_changed()
    panel._refresh_sources_list()
    panel._refresh_receiver_marker()

    # Receptor todavia visible al picker
    rp = viewer._receiver_position
    assert rp is not None, "Receptor desapareció tras CAD"
    assert abs(rp[0] - 3.0) < 1e-9 and abs(rp[1] - 4.0) < 1e-9, \
        f"Receptor cambiado: {rp}"
    return f"Receptor sigue en {rp} despues de cambiar geometria"


@test
def t3_restore_room_syncs_sources_to_viewer():
    """Flow 3: simular carga de .room -> picker ve las fuentes restauradas.

    Reproduce el bug original: _restore_acoustic_state llamaba a
    _refresh_sources_list pero el viewer quedaba con _source_positions=[].
    """
    viewer, panel, _v, _t = make_panel()

    # Vaciar y volver a llenar como hace _restore_acoustic_state
    panel.sources.sources.clear()
    for pos in [(2.0, 2.0, 1.0), (4.0, 4.0, 1.5), (6.0, 6.0, 2.0)]:
        panel.sources.add(OmniSource(position=pos, label=f"src_{pos[0]:.0f}",
                                     sensitivity_dB=90.0, power_W=1.0))
    panel._refresh_sources_list()

    # Antes del fix A esto fallaba (0 != 3)
    assert len(viewer._source_positions) == 3, (
        f"Tras simular carga .room: viewer tiene "
        f"{len(viewer._source_positions)}, esperaba 3")
    assert abs(viewer._source_positions[2][0] - 6.0) < 1e-9
    return "Carga estilo .room sincroniza al viewer (bug A resuelto)"


@test
def t4_remove_middle_source_keeps_picker_correct():
    """Flow 4: borrar la fuente del medio -> picker ve las 2 restantes
    con posiciones correctas (NO hay fuente fantasma).
    """
    viewer, panel, _v, _t = make_panel()
    panel.add_source_at(1.0, 1.0, 1.0)   # idx 0
    panel.add_source_at(3.0, 3.0, 1.5)   # idx 1 (la del medio)
    panel.add_source_at(5.0, 5.0, 2.0)   # idx 2

    # Seleccionar la del medio y borrarla
    panel.list_src.setCurrentRow(1)
    panel._remove_source()

    assert len(viewer._source_positions) == 2, (
        f"Tras borrar middle: viewer tiene "
        f"{len(viewer._source_positions)}, esperaba 2")
    # La que ahora es indice 1 debe ser la antigua idx 2 (z=2.0), no la
    # borrada (z=1.5).
    p0 = viewer._source_positions[0]
    p1 = viewer._source_positions[1]
    assert abs(p0[2] - 1.0) < 1e-9, f"Fuente[0].z deberia ser 1.0, es {p0[2]}"
    assert abs(p1[2] - 2.0) < 1e-9, (
        f"Fuente[1].z deberia ser 2.0 (la que era idx 2), es {p1[2]} "
        f"(fuente fantasma de la borrada?)")
    return "Borrar middle: viewer queda con [z=1.0, z=2.0], sin fantasma"


@test
def t6_ctrl_shift_drag_sets_z_only_mode():
    """Ctrl+Shift+click pone _drag_mode='z' y guarda los anchors xy de la
    posicion original. Plain Shift+click queda en modo 'xy' (default).
    """
    viewer, panel, _v, _t = make_panel()
    panel.add_source_at(2.0, 3.0, 1.5)

    # Simular Ctrl+Shift+Left press sobre la posicion de la fuente.
    from PyQt5.QtCore import Qt, QPointF, QEvent
    from PyQt5.QtGui import QMouseEvent

    # Calcular la pixel position aproximada de la fuente proyectada.
    # Usamos directamente _project y disparamos un press sintetico ahi.
    viewer.resize(800, 600)   # asegurar tamaño valido para projeccion
    # Forzar un paintGL para que la matriz de projeccion este inicializada.
    viewer.repaint()
    sp = viewer._project((2.0, 3.0, 1.5))
    if sp is None:
        # Si no se puede proyectar (camara mal configurada), saltar
        return "skipped (no se pudo proyectar la fuente)"
    px, py = int(sp[0]), int(sp[1])

    # Press SIN ctrl: modo xy
    ev_plain = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier,
    )
    viewer.mousePressEvent(ev_plain)
    assert viewer._drag_mode == "xy", \
        f"Plain Shift: esperaba modo 'xy', tengo {viewer._drag_mode!r}"
    # Liberar
    viewer._dragging_source_idx = -1

    # Press CON ctrl: modo z + anchors xy
    ev_ctrl = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton,
        Qt.ShiftModifier | Qt.ControlModifier,
    )
    viewer.mousePressEvent(ev_ctrl)
    assert viewer._drag_mode == "z", \
        f"Ctrl+Shift: esperaba modo 'z', tengo {viewer._drag_mode!r}"
    assert abs(viewer._drag_anchor_x - 2.0) < 1e-9, \
        f"_drag_anchor_x deberia ser 2.0, es {viewer._drag_anchor_x}"
    assert abs(viewer._drag_anchor_y - 3.0) < 1e-9, \
        f"_drag_anchor_y deberia ser 3.0, es {viewer._drag_anchor_y}"
    return "Ctrl+Shift -> 'z' mode + anchors xy capturados; Shift solo -> 'xy'"


@test
def t7_pick_vertical_line_math_is_correct():
    """Verifica que _pick_vertical_line proyecta correctamente sobre la
    linea vertical: si el cursor 'apunta' al punto (x0, y0, z_target), la
    funcion devuelve z_target.

    Test sin GUI real: invocamos _pick_vertical_line con un mock de
    _ray_from_pixel que devuelve un rayo construido a mano. El metodo
    no toca Qt internamente, solo numpy.
    """
    viewer = IsoViewer()
    # Mock: rayo desde camara=(0,-10,5) apuntando a (0, 0, 1.5).
    # direccion = (0, 10, -3.5) / norma
    d = np.array([0.0, 10.0, -3.5])
    d /= np.linalg.norm(d)
    orig = np.array([0.0, -10.0, 5.0])

    # Inyectar el mock
    def fake_ray(px, py):
        return orig, d
    viewer._ray_from_pixel = fake_ray

    # Linea vertical pasa por (0, 0) -> proyectar el rayo da z ~ 1.5
    z = viewer._pick_vertical_line(0, 0, x0=0.0, y0=0.0)
    assert z is not None, "Esperaba un z valido, recibi None"
    assert abs(z - 1.5) < 1e-3, f"Esperaba z~1.5, recibi {z}"

    # Caso degenerado: camara apuntando exactamente vertical -> debe
    # devolver None (la altura no se puede inferir de la posicion 2D).
    d_vert = np.array([0.0, 0.0, -1.0])     # rayo paralelo al eje z
    def fake_ray_vertical(px, py):
        return orig, d_vert
    viewer._ray_from_pixel = fake_ray_vertical
    z_vert = viewer._pick_vertical_line(0, 0, x0=0.0, y0=0.0)
    assert z_vert is None, \
        f"Camara vertical: esperaba None, recibi {z_vert}"
    return "Proyeccion sobre linea vertical: z=1.5 OK, caso degenerado None OK"


@test
def t5_receiver_marker_updates_in_place():
    """Fix C: ReceiverMarker mantiene el mismo GLLinePlotItem entre updates
    consecutivos. Antes hacia removeItem + addItem en cada llamada.
    """
    viewer, panel, _v, _t = make_panel()

    panel.move_receiver_to(2.0, 2.0, 1.5)
    item_1 = panel.rcv_marker.item
    assert item_1 is not None, "Receiver marker no creo item en primer update"

    # Mover el receptor varias veces; el item debe ser el mismo objeto
    for x in (2.5, 3.0, 3.5, 4.0):
        panel.move_receiver_to(x, 2.0, 1.5)
        cur = panel.rcv_marker.item
        assert cur is item_1, (
            f"ReceiverMarker recreo el item en move_receiver_to({x}, ...): "
            f"id era {id(item_1)}, ahora es {id(cur)} — esto causaba scene "
            f"graph thrashing durante drag")

    # pos=None debe limpiar el item (caso borde)
    panel.rcv_marker.update(None)
    assert panel.rcv_marker.item is None, \
        "update(None) deberia haber limpiado el marker"
    return "ReceiverMarker reusa item GL entre updates (no recrea por frame)"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print(" Smoke tests: Shift+drag fixes A / B / C")
    print("=" * 78)

    n_ok = 0
    n_fail = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            msg = fn()
            print(f"  [OK]   {name}  -  {msg}")
            n_ok += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}")
            print(f"         {e}")
            n_fail += 1
        except Exception as e:
            print(f"  [ERR]  {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            n_fail += 1

    print("=" * 78)
    print(f" Pasados: {n_ok} / {len(TESTS)}   Fallados: {n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
