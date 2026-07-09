"""
bench_origin_mode.py
====================

Oraculos de la convencion de origen (0,0,0) configurable (auto/center/corner)
en build_room_geometry / origin_offset / anchor_vertices.

Correr:  PYTHONIOENCODING=utf-8 python bench_origin_mode.py
"""

import sys
import numpy as np

from geometry import build_room_geometry, origin_offset, anchor_vertices

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK' if cond else 'FALLA'}] {name}" + (f"  ({detail})" if detail else ""))


def bbox(v):
    v = np.asarray(v, float)
    return v.min(axis=0), v.max(axis=0)


BASE = {
    "width": 6.0, "length": 8.0, "height": 3.0,
    "n_walls": 4, "taper": 0.0, "twist": 0.0,
    "arch_height": 0.0, "ridge_offset": 0.0, "roof_type": "flat",
    "ceiling_pitch_x": 0.0, "ceiling_pitch_y": 0.0,
    "floor_pitch_x": 0.0, "floor_pitch_y": 0.0,
    "wall_inclinations": [0.0] * 4,
    "base_polygon": None, "wall_profiles": None,
}

# ---------------------------------------------------------------- parametrico
print("--- parametrico (caja 6x8x3) ---")
for mode, exp_min, exp_max in (
        ("auto",   (-3.0, -4.0, 0.0), (3.0, 4.0, 3.0)),   # legado: centrado
        ("center", (-3.0, -4.0, 0.0), (3.0, 4.0, 3.0)),
        ("corner", (0.0, 0.0, 0.0),   (6.0, 8.0, 3.0))):
    p = dict(BASE, origin_mode=mode)
    v, t, e, n = build_room_geometry(p)
    mn, mx = bbox(v)
    ok = np.allclose(mn, exp_min, atol=1e-5) and np.allclose(mx, exp_max, atol=1e-5)
    check(f"{mode}: bbox esperado", ok,
          f"min={np.round(mn, 3)} max={np.round(mx, 3)}")

# sin la clave (params viejos) == auto
v0 = build_room_geometry(dict(BASE))[0]
va = build_room_geometry(dict(BASE, origin_mode="auto"))[0]
check("sin clave == auto (compat .room viejos)", np.allclose(v0, va))

# ------------------------------------------------------------ planta dibujada
print("--- planta dibujada (cuadrante positivo, esquina en (0,0)) ---")
poly = [(0.0, 0.0), (6.0, 0.0), (5.6, 4.4), (0.4, 5.0)]
for mode, exp_min_xy in (("auto", (0.0, 0.0)),      # como se dibujo
                         ("corner", (0.0, 0.0)),    # ya esta anclada -> no-op
                         ("center", (-3.0, -2.5))):
    p = dict(BASE, base_polygon=poly, origin_mode=mode)
    v, *_ = build_room_geometry(p)
    mn, mx = bbox(v)
    ok = np.allclose(mn[:2], exp_min_xy, atol=1e-5)
    check(f"{mode}: xy_min esperado", ok, f"xy_min={np.round(mn[:2], 3)}")
    check(f"{mode}: piso sigue en z=0", abs(mn[2]) < 1e-6)

# planta dibujada LEJOS del origen: corner la normaliza, auto la respeta
poly_far = [(10.0, 20.0), (16.0, 20.0), (16.0, 25.0), (10.0, 25.0)]
p = dict(BASE, base_polygon=poly_far, origin_mode="corner")
v, *_ = build_room_geometry(p)
check("corner normaliza planta lejana", np.allclose(bbox(v)[0][:2], (0, 0), atol=1e-5))
p = dict(BASE, base_polygon=poly_far, origin_mode="auto")
v, *_ = build_room_geometry(p)
check("auto respeta planta lejana", np.allclose(bbox(v)[0][:2], (10, 20), atol=1e-5))

# ------------------------------------------------------------------- lofteada
print("--- lofteada (planta + perfiles de tope) ---")
profs = [[(0.0, 3.0), (1.0, 3.5)], [(0.0, 3.5), (1.0, 3.5)],
         [(0.0, 3.5), (1.0, 3.0)], [(0.0, 3.0), (1.0, 3.0)]]
p = dict(BASE, base_polygon=poly, wall_profiles=profs, origin_mode="center")
v, *_ = build_room_geometry(p)
mn, mx = bbox(v)
ok = (np.allclose((mn[:2] + mx[:2]) / 2.0, (0, 0), atol=1e-5)
      and abs(mn[2]) < 1e-6 and abs(mx[2] - 3.5) < 1e-6)
check("center en lofteada (centro xy=0, z intacto)", ok,
      f"min={np.round(mn, 3)} max={np.round(mx, 3)}")

# ------------------------------------------------- traslacion pura (invariante)
print("--- la forma no cambia, solo se traslada ---")
p_auto = dict(BASE, base_polygon=poly, origin_mode="auto")
p_cent = dict(BASE, base_polygon=poly, origin_mode="center")
v1, t1, *_ = build_room_geometry(p_auto)
v2, t2, *_ = build_room_geometry(p_cent)
d = np.asarray(v2, float) - np.asarray(v1, float)
check("traslacion pura (delta constante)", float(np.ptp(d, axis=0).max()) < 1e-5,
      f"delta={np.round(d[0], 3)}")
check("misma topologia", np.array_equal(t1, t2))

# ------------------------------------------------------------------- helpers
print("--- helpers ---")
try:
    origin_offset(np.zeros((4, 3)), "diagonal")
    check("modo invalido -> ValueError", False)
except ValueError:
    check("modo invalido -> ValueError", True)
check("offset auto == 0", np.allclose(origin_offset(np.random.rand(9, 3), "auto"), 0))
va = anchor_vertices(np.array([[2.0, 3.0, 0.0], [4.0, 7.0, 2.0]]), "corner")
check("anchor_vertices corner", np.allclose(va, [[0, 0, 0], [2, 4, 2]]))

n_ok = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 52)
print(f"{'TODOS OK' if n_ok == len(results) else 'HAY FALLAS'} ({n_ok}/{len(results)})")
sys.exit(0 if n_ok == len(results) else 1)
