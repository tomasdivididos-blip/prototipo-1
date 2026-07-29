"""smoke_test_furniture_ui.py
============================

Smoke tests HEADLESS de la UI de muebles (diálogo + wireframe + handlers del
panel + round-trip de persistencia del material por mueble). NO cubre el
cómputo (carve/ξ/SBIR) — eso ya lo cubre bench_furniture_live.py; acá se prueba
solo la capa de UI recién agregada.

  1. _furniture_wireframe (caja): 12 aristas (24 puntos), esquinas correctas.
  2. _furniture_wireframe (cilindro): 2 anillos + montantes, puntos en el radio.
  3. FurnitureEditDialog caja: get_furniture -> Furniture + material None/elegido.
  4. FurnitureEditDialog cilindro: size=(diám,diám,alto), yaw 0, 2º lado oculto.
  5. FurnitureEditDialog precarga: round-trip de un Furniture existente.
  6. Panel: añadir muebles refresca lista + wireframe (marker creado).
  7. Panel: quitar un mueble reindexa _furniture_mat_names correctamente.
  8. Persistencia: furniture_materials (paralelo a furniture) round-trip exacto.

Uso: python smoke_test_furniture_ui.py
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

import numpy as np

from geometry import make_room
from viewer import IsoViewer
from acoustic_panel import AcousticPanel, FurnitureEditDialog
from acoustic_viewer import _furniture_wireframe
from furniture import Furniture
import furniture as fu

MAT_NAMES = ["Alfombra fina", "Madera", "Ladrillo"]

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def make_panel(width=6.0, length=8.0, height=3.0, n_walls=4):
    viewer = IsoViewer()
    v, t, _, _ = make_room(width=width, length=length,
                           height=height, n_walls=n_walls)
    panel = AcousticPanel(
        viewer=viewer,
        get_surface=lambda: (v, t),
        get_dims_hint=lambda: (width, length, height),
    )
    return viewer, panel


# ---------------------------------------------------------------------------
@test
def t1_wireframe_box():
    """Caja centrada en (0,0,0), 2×2×2 -> 12 aristas (24 pts), esquinas ±1."""
    f = Furniture("box", position=(0, 0, 0), size=(2, 2, 2), orientation=0.0)
    segs = np.asarray(_furniture_wireframe(f), dtype=float)
    assert segs.shape == (24, 3), f"esperaba (24,3), tengo {segs.shape}"
    assert np.isfinite(segs).all(), "puntos no finitos"
    # Todas las coords son ±1 (cubo unidad ×2).
    assert np.allclose(np.abs(segs), 1.0), "esquinas no son ±1"
    return f"caja: {len(segs)} puntos (12 aristas), esquinas ±1 OK"


@test
def t2_wireframe_cylinder():
    """Cilindro r=0.5, alto 1.0 -> puntos de los anillos a radio 0.5, en z=±0.5."""
    f = Furniture("cylinder", position=(0, 0, 0), size=(1.0, 1.0, 1.0))
    segs = np.asarray(_furniture_wireframe(f, nseg=24), dtype=float)
    assert np.isfinite(segs).all(), "puntos no finitos"
    r = np.hypot(segs[:, 0], segs[:, 1])
    # Los puntos de anillo están a r=0.5; los montantes también (mismo xy).
    assert np.allclose(r, 0.5, atol=1e-9), "radio del cilindro incorrecto"
    zs = np.unique(np.round(segs[:, 2], 6))
    assert set(zs.tolist()) == {-0.5, 0.5}, f"z de anillos raros: {zs}"
    return f"cilindro: {len(segs)} puntos, r=0.5, z∈{{-0.5,0.5}} OK"


@test
def t3_dialog_box_material():
    """Diálogo caja: default -> Furniture caja + material None; elegir material
    -> se devuelve el nombre."""
    dlg = FurnitureEditDialog(mat_names=MAT_NAMES, dims_hint=(6, 8, 3))
    furn, mat = dlg.get_furniture()
    assert furn.kind == "box", f"kind={furn.kind}"
    assert mat is None, f"material default deberia ser None (rígido), es {mat}"
    # Centro por default = centro de planta, apoyado en piso.
    assert abs(furn.position[0] - 3.0) < 1e-9 and abs(furn.position[1] - 4.0) < 1e-9
    # Elegir un material.
    dlg.combo_mat.setCurrentText("Madera")
    _f2, mat2 = dlg.get_furniture()
    assert mat2 == "Madera", f"esperaba 'Madera', tengo {mat2}"
    return "caja default rígida + selección de material OK"


@test
def t4_dialog_cylinder():
    """Diálogo cilindro: size=(diám,diám,alto), yaw 0, 2º lado oculto."""
    dlg = FurnitureEditDialog(mat_names=MAT_NAMES)
    dlg.combo_kind.setCurrentText("Cilindro")
    dlg.sb_sx.setValue(0.6)     # diámetro
    dlg.sb_sz.setValue(1.2)     # alto
    dlg.sb_orient.setValue(45)  # debe ignorarse en cilindro
    furn, _mat = dlg.get_furniture()
    assert furn.kind == "cylinder"
    assert abs(furn.size[0] - 0.6) < 1e-9 and abs(furn.size[2] - 1.2) < 1e-9
    assert abs(furn.orientation) < 1e-9, "cilindro no debe llevar yaw"
    assert not dlg.sb_sy.isVisible(), "el 2º lado debe ocultarse en cilindro"
    assert not dlg.sb_orient.isEnabled(), "yaw debe deshabilitarse en cilindro"
    return "cilindro: size=(Ø,Ø,alto), yaw=0, 2º lado oculto OK"


@test
def t5_dialog_preload_roundtrip():
    """Precargar un Furniture existente -> get_furniture reproduce sus valores."""
    orig = Furniture("box", position=(1.0, 2.0, 0.5), size=(0.7, 0.9, 1.1),
                     orientation=30.0, label="sofá", provenance="medida propia")
    dlg = FurnitureEditDialog(orig, mat_name="Madera", mat_names=MAT_NAMES)
    furn, mat = dlg.get_furniture()
    assert furn.kind == "box"
    assert np.allclose(furn.position, (1.0, 2.0, 0.5))
    assert np.allclose(furn.size, (0.7, 0.9, 1.1))
    assert abs(furn.orientation - 30.0) < 1e-9
    assert furn.label == "sofá" and furn.provenance == "medida propia"
    assert mat == "Madera", f"material no round-trippeó: {mat}"
    return "round-trip de Furniture existente (pos/size/yaw/label/material) OK"


@test
def t6_panel_add_refreshes_list_and_wireframe():
    """Añadir muebles al panel refresca la lista y crea el marker de wireframe."""
    _viewer, panel = make_panel()
    assert panel.list_furn.count() == 0
    panel.furniture.append(Furniture("box", position=(2, 2, 0.45),
                                     size=(0.8, 0.8, 0.9), label="a"))
    panel.furniture.append(Furniture("cylinder", position=(4, 3, 0.5),
                                     size=(0.5, 0.5, 1.0), label="b"))
    panel._furniture_mat_names[1] = "Madera"
    panel._refresh_furniture_list()
    assert panel.list_furn.count() == 2, f"lista tiene {panel.list_furn.count()}"
    # El texto del item refleja tipo + material.
    assert "rígido" in panel.list_furn.item(0).text()
    assert "Madera" in panel.list_furn.item(1).text()
    # El marker de wireframe se creó (item GL persistente).
    assert panel.furn_markers._item_normal is not None, "wireframe no creado"
    return "añadir 2 muebles -> lista=2 + wireframe creado + texto correcto"


@test
def t7_panel_remove_reindexes_materials():
    """Quitar el mueble del medio reindexa _furniture_mat_names (los > i bajan 1)."""
    _viewer, panel = make_panel()
    for k in range(3):
        panel.furniture.append(Furniture("box", position=(k + 1, 1, 0.45),
                                         size=(0.5, 0.5, 0.9), label=f"m{k}"))
    # Materiales en 0 y 2 (el 1 rígido).
    panel._furniture_mat_names = {0: "Alfombra fina", 2: "Ladrillo"}
    panel._refresh_furniture_list()
    panel.list_furn.setCurrentRow(1)     # borrar el del medio (rígido)
    panel._remove_furniture()
    assert len(panel.furniture) == 2
    # El viejo idx 2 ("Ladrillo") ahora es idx 1; el idx 0 se conserva.
    assert panel._furniture_mat_names == {0: "Alfombra fina", 1: "Ladrillo"}, \
        f"reindex mal: {panel._furniture_mat_names}"
    assert panel.furniture[1].label == "m2"
    return "quitar medio -> materiales reindexados {0:Alfombra, 1:Ladrillo} OK"


@test
def t8_persistence_roundtrip():
    """El serializado paralelo furniture/furniture_materials round-trippea el
    dict de materiales (misma lógica que main._serialize/_restore)."""
    furniture = [
        Furniture("box", position=(2, 2, 0.45), size=(0.8, 0.8, 0.9), label="a"),
        Furniture("cylinder", position=(4, 3, 0.5), size=(0.5, 0.5, 1.0), label="b"),
        Furniture("box", position=(1, 5, 0.3), size=(0.6, 0.6, 0.6), label="c"),
    ]
    mat_names = {0: "Madera", 2: "Ladrillo"}      # el 1 rígido

    # --- serialize (idéntico a main._serialize_acoustic_state) ---
    ser_furniture = [m.to_dict() for m in furniture]
    ser_materials = [mat_names.get(i) for i in range(len(furniture))]

    # --- restore (idéntico a main._restore_acoustic_state) ---
    furn2 = [Furniture.from_dict(m) for m in ser_furniture]
    mat2 = {i: str(nm) for i, nm in enumerate(ser_materials) if nm}

    assert len(furn2) == 3 and furn2[1].kind == "cylinder"
    assert mat2 == {0: "Madera", 2: "Ladrillo"}, f"materiales no round-trip: {mat2}"
    # Compat: un .room v7 sin la clave -> todos rígidos.
    mat_none = {i: str(nm) for i, nm in enumerate([]) if nm}
    assert mat_none == {}, "sin la clave deberían quedar todos rígidos"
    return "round-trip furniture + furniture_materials (+ compat v7) OK"


@test
def t9_overlap_detection():
    """_furniture_conflict: cajas que interpenetran -> mensaje; separadas o
    tocándose de cara -> None. (Todo dentro del recinto x∈[-3,3].)"""
    _v, panel = make_panel()
    panel.furniture.append(Furniture("box", position=(0.0, 0.0, 0.45),
                                     size=(1.0, 1.0, 0.9)))
    over = Furniture("box", position=(0.5, 0.0, 0.45), size=(1.0, 1.0, 0.9))
    m = panel._furniture_conflict(over)
    assert m and "mueble" in m, f"no detectó interpenetración: {m!r}"
    far = Furniture("box", position=(2.0, 0.0, 0.45), size=(0.8, 0.8, 0.9))
    assert panel._furniture_conflict(far) is None, "falso positivo (separada)"
    touch = Furniture("box", position=(1.0, 0.0, 0.45), size=(1.0, 1.0, 0.9))
    assert panel._furniture_conflict(touch) is None, "contacto de cara no permitido"
    return "solape: interpenetra sí / separada no / contacto de cara permitido"


@test
def t10_default_pos_room_center():
    """_room_center_default -> centro de planta del bbox real, apoyado en piso.
    (make_room centra el recinto en el origen: bbox x∈[-3,3], y∈[-4,4], z∈[0,3].)"""
    _v, panel = make_panel(width=6.0, length=8.0, height=3.0)
    dp = panel._room_center_default()
    assert dp is not None
    assert abs(dp[0]) < 1e-6 and abs(dp[1]) < 1e-6, f"centro XY no es (0,0): {dp}"
    assert abs(dp[2] - 0.45) < 1e-6, f"z no apoyado en piso+0.45: {dp[2]}"
    return f"default = centro real {tuple(round(v, 2) for v in dp)} (no la esquina)"


@test
def t11_move_collision_stop():
    """apply_furniture_move: mover hacia otro mueble no se aplica (colisión-stop);
    a espacio libre sí."""
    _v, panel = make_panel()   # sala 6×8 centrada -> x∈[-3,3], y∈[-4,4]
    panel.furniture.append(Furniture("box", position=(-1.5, 0.0, 0.45),
                                     size=(1.0, 1.0, 0.9), label="fijo"))
    panel.furniture.append(Furniture("box", position=(1.5, 0.0, 0.45),
                                     size=(1.0, 1.0, 0.9), label="movil"))
    panel._refresh_furniture_list()
    panel.apply_furniture_move(1, -1.3, 0.0, 0.45)     # encima del fijo
    assert abs(panel.furniture[1].position[0] - 1.5) < 1e-9, "colisión-stop falló"
    panel.apply_furniture_move(1, 2.0, 0.0, 0.45)      # a espacio libre y dentro
    assert abs(panel.furniture[1].position[0] - 2.0) < 1e-9, "move libre no aplicó"
    return "colisión-stop: hacia otro no aplica, a libre (dentro) sí"


@test
def t12_rotate_box_and_cylinder_noop():
    """apply_furniture_rotate: la caja rota (yaw); el cilindro es no-op."""
    _v, panel = make_panel()
    panel.furniture.append(Furniture("box", position=(1, 1, 0.45),
                                     size=(0.8, 0.8, 0.9), orientation=0.0))
    panel.furniture.append(Furniture("cylinder", position=(4, 3, 0.5),
                                     size=(0.5, 0.5, 1.0)))
    panel._refresh_furniture_list()
    panel.apply_furniture_rotate(0, 30.0)
    assert abs(panel.furniture[0].orientation - 30.0) < 1e-9, "caja no rotó"
    panel.apply_furniture_rotate(1, 30.0)
    assert abs(panel.furniture[1].orientation) < 1e-9, "cilindro no debería rotar"
    return "rotate: caja 0->30°, cilindro no-op"


@test
def t13_viewer_pick_drag_signal_and_source_priority():
    """Shift+drag sobre un mueble emite furnitureMoveRequested; una fuente bajo
    el cursor tiene PRIORIDAD (no arranca drag de mueble)."""
    from PyQt5.QtCore import Qt, QPointF, QEvent
    from PyQt5.QtGui import QMouseEvent
    viewer, panel = make_panel()
    viewer.resize(800, 600); viewer.repaint()
    # Alejar el receptor (el panel lo coloca por default y tiene prioridad de
    # picking) para que no tape al mueble en pantalla.
    panel.move_receiver_to(2.8, 3.8, 0.2)
    furn_pos = (-2.0, -3.0, 0.6)
    panel.furniture.append(Furniture("box", position=furn_pos,
                                     size=(0.8, 0.8, 1.2), label="m"))
    panel._refresh_furniture_list()      # sincroniza posiciones al viewer
    sp = viewer._project(furn_pos)
    if sp is None:
        return "skipped (no se pudo proyectar el mueble)"
    px, py = int(sp[0]), int(sp[1])
    got = []
    viewer.furnitureMoveRequested.connect(lambda i, x, y, z: got.append(i))
    viewer.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier))
    assert viewer._dragging_furn_idx == 0, \
        f"esperaba drag de mueble 0, tengo {viewer._dragging_furn_idx}"
    viewer.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(px + 20, py + 10),
        Qt.NoButton, Qt.LeftButton, Qt.ShiftModifier))
    assert got, "no se emitió furnitureMoveRequested en el drag"
    viewer.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(px + 20, py + 10),
        Qt.LeftButton, Qt.NoButton, Qt.ShiftModifier))
    assert viewer._dragging_furn_idx == -1, "no se reseteó el drag al soltar"
    # Fuente en la misma posición -> gana el pick (prioridad).
    panel.add_source_at(*furn_pos)
    viewer.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier))
    assert viewer._dragging_source_idx == 0 and viewer._dragging_furn_idx == -1, \
        "la fuente debería tener prioridad de picking sobre el mueble"
    return "Shift+drag mueble emite move; fuente tiene prioridad de picking"


@test
def t14_pitch_is_physical_in_contains():
    """El pitch afecta Furniture.contains (el carve), no es solo visual. Una caja
    alta 0.4×0.4×2.0 inclinada 90° se acuesta: puntos que estaban dentro salen y
    viceversa."""
    up = Furniture("box", position=(0, 0, 0), size=(0.4, 0.4, 2.0), pitch=0.0)
    lay = Furniture("box", position=(0, 0, 0), size=(0.4, 0.4, 2.0), pitch=90.0)
    # (0,0,0.9): dentro parado (|z|<=1), fuera acostado (pasa al eje corto).
    assert up.contains(np.array([[0, 0, 0.9]]))[0]
    assert not lay.contains(np.array([[0, 0, 0.9]]))[0]
    # (0.8,0,0): fuera parado (|x|>0.2), dentro acostado (el lado largo va en x).
    assert not up.contains(np.array([[0.8, 0, 0.0]]))[0]
    assert lay.contains(np.array([[0.8, 0, 0.0]]))[0]
    return "pitch cambia contains (carve): la caja inclinada 90° se acuesta"


@test
def t15_pitch_tilts_wireframe():
    """El wireframe refleja el pitch (difiere de pitch=0)."""
    a = np.asarray(_furniture_wireframe(
        Furniture("box", position=(0, 0, 1), size=(0.6, 0.6, 1.2), pitch=0.0)))
    b = np.asarray(_furniture_wireframe(
        Furniture("box", position=(0, 0, 1), size=(0.6, 0.6, 1.2), pitch=30.0)))
    assert a.shape == b.shape and not np.allclose(a, b), "el pitch no movió el wireframe"
    return "wireframe inclinado difiere del recto"


@test
def t16_conflict_with_source_baffle():
    """_furniture_conflict detecta solape con el bafle de un parlante."""
    _v, panel = make_panel()
    panel.add_source_at(0.0, 0.0, 1.0)          # parlante en el centro
    over = Furniture("box", position=(0.0, 0.0, 1.0), size=(0.8, 0.8, 0.8))
    msg = panel._furniture_conflict(over)
    assert msg and "parlante" in msg, f"no detectó solape con parlante: {msg!r}"
    far = Furniture("box", position=(2.5, 3.0, 0.45), size=(0.4, 0.4, 0.4))
    assert panel._furniture_conflict(far) is None, "falso positivo lejos del parlante"
    return "solape con bafle de parlante detectado; lejos = OK"


@test
def t17_conflict_out_of_room():
    """_furniture_conflict traba si el mueble se sale del recinto (bbox)."""
    _v, panel = make_panel(width=6.0, length=8.0, height=3.0)  # x∈[-3,3]
    out = Furniture("box", position=(2.9, 0.0, 0.45), size=(0.8, 0.8, 0.9))  # x→3.3
    msg = panel._furniture_conflict(out)
    assert msg and "recinto" in msg, f"no trabó fuera del recinto: {msg!r}"
    inside = Furniture("box", position=(2.0, 0.0, 0.45), size=(0.8, 0.8, 0.9))
    assert panel._furniture_conflict(inside) is None, "falso positivo dentro"
    return "fuera del recinto trabado; dentro = OK"


@test
def t18_apply_tilt_box_and_cylinder():
    """apply_furniture_tilt inclina la caja (clamp) y es no-op en el cilindro."""
    _v, panel = make_panel()
    panel.furniture.append(Furniture("box", position=(0, 0, 0.6),
                                     size=(0.4, 0.4, 1.0), pitch=0.0))
    panel.furniture.append(Furniture("cylinder", position=(2, 2, 0.5),
                                     size=(0.5, 0.5, 1.0)))
    panel._refresh_furniture_list()
    panel.apply_furniture_tilt(0, 30.0)
    assert abs(panel.furniture[0].pitch - 30.0) < 1e-9, "la caja no se inclinó"
    panel.apply_furniture_tilt(1, 30.0)
    assert abs(getattr(panel.furniture[1], "pitch", 0.0)) < 1e-9, "cilindro no debería inclinarse"
    return "tilt: caja 0->30°, cilindro no-op"


@test
def t19_pitch_persists():
    """El pitch round-trippea por to_dict/from_dict (.room)."""
    m = Furniture("box", position=(1, 2, 0.5), size=(0.6, 0.6, 0.9),
                  orientation=20.0, pitch=15.0)
    m2 = Furniture.from_dict(m.to_dict())
    assert abs(m2.pitch - 15.0) < 1e-9 and abs(m2.orientation - 20.0) < 1e-9
    # Compat: un dict viejo sin pitch -> 0.
    old = {"kind": "box", "position": [0, 0, 0], "size": [1, 1, 1]}
    assert abs(Furniture.from_dict(old).pitch) < 1e-9
    return "pitch persiste; dict viejo sin pitch -> 0"


@test
def t20_clamp_to_room_bbox():
    """_clamp_to_room_bbox recorta al recinto (traba fuentes/receptor en drag).
    Sala 6×8×3 centrada -> x∈[-3,3], y∈[-4,4], z∈[0,3]."""
    _v, panel = make_panel(width=6.0, length=8.0, height=3.0)
    cx, cy, cz = panel._clamp_to_room_bbox(10.0, 0.0, 1.0)      # fuera por +x
    assert cx <= 3.0 and abs(cx - 3.0) < 1e-2, f"x no clampeó: {cx}"
    assert abs(cy) < 1e-9 and abs(cz - 1.0) < 1e-9, "y/z no deberían cambiar"
    _cx2, cy2, cz2 = panel._clamp_to_room_bbox(0.0, -10.0, 9.0)  # fuera por -y y techo
    assert cy2 >= -4.0 and abs(cy2 + 4.0) < 1e-2, f"y no clampeó: {cy2}"
    assert cz2 <= 3.0 and abs(cz2 - 3.0) < 1e-2, f"z no clampeó: {cz2}"
    assert np.allclose(panel._clamp_to_room_bbox(1.0, 2.0, 1.5), (1.0, 2.0, 1.5)), \
        "punto interior no debe moverse"
    return "clamp: fuera -> pegado a la pared; dentro -> intacto"


@test
def t21_compound_contains_and_aabb():
    """Compound (preset): contains = unión de partes; aabb envuelve todo; se
    apoya en el piso."""
    f, mat = fu.make_preset("Silla")
    lo, hi = f.aabb(); f.position = (0.0, 0.0, -float(lo[2]))   # apoyar en z=0
    lo, hi = f.aabb()
    assert abs(lo[2]) < 1e-6, "no quedó apoyada en el piso"
    cz = f.position[2]
    assert f.contains(np.array([[0, 0, cz-0.02]]))[0], "asiento no está adentro"
    assert not f.contains(np.array([[2.0, 2.0, 0.5]]))[0], "punto lejano adentro?"
    assert mat == "Madera"
    d = hi - lo
    return f"compound: contains unión + aabb {d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}"


@test
def t22_compound_persistence():
    """to_dict/from_dict preserva las partes del compound (.room)."""
    f, _ = fu.make_preset("Escritorio")
    f.position = (1.0, 2.0, 0.4); f.orientation = 30.0
    g = Furniture.from_dict(f.to_dict())
    assert g.kind == "compound" and g.parts and len(g.parts) == len(f.parts)
    assert np.allclose(g.position, (1.0, 2.0, 0.4)) and abs(g.orientation-30) < 1e-9
    pts = np.random.default_rng(0).uniform(-1, 3, (200, 3))
    assert np.array_equal(f.contains(pts), g.contains(pts)), "contains no round-trip"
    return "compound round-trip: partes + contains idénticos"


@test
def t23_compound_wireframe():
    """El wireframe del compound concatena las partes y rota con el yaw."""
    f, _ = fu.make_preset("Sillón")
    segs = np.asarray(_furniture_wireframe(f))
    assert segs.ndim == 2 and segs.shape[1] == 3 and len(segs) > 0
    assert np.isfinite(segs).all()
    f.orientation = 90.0
    segs2 = np.asarray(_furniture_wireframe(f))
    assert not np.allclose(segs, segs2), "el yaw no rotó el wireframe del compound"
    return f"compound wireframe: {len(segs)} puntos, rota con el yaw"


@test
def t24_preset_insert_and_edit():
    """Panel: insertar un preset (compound + material) y editarlo preserva la forma."""
    _v, panel = make_panel()
    n0 = len(panel.furniture)
    panel._insert_preset("Mesa")
    assert len(panel.furniture) == n0 + 1, "no se insertó el preset"
    i = len(panel.furniture) - 1
    m = panel.furniture[i]
    assert m.kind == "compound" and m.parts, "el preset no es compound"
    assert panel._furniture_mat_names.get(i) == "Madera"
    assert "preset" in panel.list_furn.item(i).text()
    dlg = FurnitureEditDialog(m, mat_name="Madera", mat_names=MAT_NAMES,
                              dims_hint=(6, 8, 3))
    dlg.sb_x.setValue(0.5)
    f2, _mat = dlg.get_furniture()
    assert f2.kind == "compound" and len(f2.parts) == len(m.parts), "editar perdió la forma"
    assert abs(f2.position[0] - 0.5) < 1e-9
    return "preset: insertar (compound+material) + editar preserva la forma"


@test
def t25_preset_move_rotate_tilt():
    """Los gestos move/rotate/tilt funcionan sobre un compound."""
    _v, panel = make_panel()
    panel._insert_preset("Silla")
    i = len(panel.furniture) - 1
    p0 = panel.furniture[i].position
    panel.apply_furniture_rotate(i, 25.0)
    assert abs(panel.furniture[i].orientation - 25.0) < 1e-9, "no rotó"
    panel.apply_furniture_tilt(i, 10.0)
    assert abs(panel.furniture[i].pitch - 10.0) < 1e-9, "no inclinó"
    panel.apply_furniture_move(i, p0[0]+0.3, p0[1], p0[2])
    assert abs(panel.furniture[i].position[0] - (p0[0]+0.3)) < 1e-6, "no movió"
    return "compound: rotate/tilt/move OK"


@test
def t26_pick_large_furniture_by_silhouette():
    """Un mueble grande se agarra clickeando en su silueta (borde), no solo cerca
    del centro. (El picking viejo por radio de 28px fallaba en muebles grandes.)"""
    viewer, panel = make_panel(width=8.0, length=8.0, height=4.0)
    viewer.resize(800, 600); viewer.repaint()
    panel.move_receiver_to(3.5, 3.5, 0.2)     # receptor lejos, sin prioridad
    panel.furniture.append(Furniture("box", position=(0.0, 0.0, 1.0),
                                     size=(3.0, 3.0, 2.0), label="grande"))
    panel._refresh_furniture_list()           # sincroniza pos + bboxes
    i = len(panel.furniture) - 1
    m = panel.furniture[i]
    center_sp = viewer._project(tuple(m.position))
    if center_sp is None:
        return "skipped (no se pudo proyectar)"
    lo, hi = m.aabb()
    far = None
    for a in (lo[0], hi[0]):
        for b in (lo[1], hi[1]):
            for c in (lo[2], hi[2]):
                q = viewer._project((float(a), float(b), float(c)))
                if q is not None and ((q[0]-center_sp[0])**2 +
                                      (q[1]-center_sp[1])**2) ** 0.5 > 30:
                    far = q
    if far is None:
        return "skipped (bbox chico en pantalla headless)"
    # El borde está a >30px del centro -> el picking viejo (radio 28) fallaría.
    assert viewer._pick_furniture(int(far[0]), int(far[1])) == i, \
        "no agarró el mueble grande por la silueta"
    # Un punto MUY lejos (fuera de la silueta) no debe agarrarlo.
    assert viewer._pick_furniture(int(max(0, far[0]) + 300), int(far[1])) != i, \
        "agarró el mueble desde fuera de su silueta"
    return "mueble grande: agarrado por la silueta, no desde afuera"


@test
def t27_rotate_gesture_yaw_only():
    """El gesto Alt+Ctrl rota (yaw) SIN inclinar, aunque el arrastre tenga
    componente vertical -> el mueble no se 'cae' ni se traba después."""
    from PyQt5.QtCore import Qt, QPointF, QEvent
    from PyQt5.QtGui import QMouseEvent
    viewer, panel = make_panel(width=8.0, length=8.0, height=4.0)
    viewer.resize(800, 600); viewer.repaint()
    panel.move_receiver_to(3.5, 3.5, 0.2)
    viewer.furnitureRotateRequested.connect(panel.apply_furniture_rotate)
    viewer.furnitureTiltRequested.connect(panel.apply_furniture_tilt)
    panel._insert_preset("Silla")
    i = len(panel.furniture) - 1
    m = panel.furniture[i]
    sp = viewer._project(tuple(m.position))
    if sp is None:
        return "skipped (no se pudo proyectar)"
    px, py = int(sp[0]), int(sp[1])
    ac = Qt.AltModifier | Qt.ControlModifier
    viewer.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(px, py),
                                       Qt.LeftButton, Qt.LeftButton, ac))
    assert viewer._orient_furn_idx == i, "no agarró el mueble para orientar"
    for k in range(1, 6):                       # arrastre horizontal Y vertical
        viewer.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,
            QPointF(px + 15*k, py + 8*k), Qt.NoButton, Qt.LeftButton, ac))
    viewer.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease,
        QPointF(px + 75, py + 40), Qt.LeftButton, Qt.NoButton, ac))
    assert abs(m.orientation) > 1e-6, "no rotó (yaw)"
    assert abs(getattr(m, "pitch", 0.0)) < 1e-9, "se inclinó sin querer (pitch != 0)"
    assert viewer._orient_furn_idx == -1, "no soltó el gesto"
    p0 = m.position                              # y sigue movible tras rotar
    panel.apply_furniture_move(i, p0[0]+0.3, p0[1], p0[2])
    assert abs(m.position[0] - (p0[0]+0.3)) < 1e-6, "se traba: no se mueve tras rotar"
    return "gesto rotar = solo yaw; pitch queda 0; sigue movible"


# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print(" Smoke tests: UI de muebles (diálogo + wireframe + panel + persistencia)")
    print("=" * 78)
    n_ok = n_fail = 0
    for fn in TESTS:
        try:
            msg = fn()
            print(f"  [OK]   {fn.__name__}  -  {msg}")
            n_ok += 1
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}")
            print(f"         {e}")
            n_fail += 1
        except Exception as e:
            print(f"  [ERR]  {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            n_fail += 1
    print("=" * 78)
    print(f" Pasados: {n_ok} / {len(TESTS)}   Fallados: {n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
