"""bench_cad.py -- oraculos del import CAD (kind="mesh") en furniture.py.

Valida que un mueble importado de un OBJ:
  1. carga watertight y con volumen correcto (silla_test.obj);
  2. contains() acierta puntos adentro/afuera conocidos;
  3. una CAJA exportada como OBJ y cargada como mesh da el MISMO contains que
     el kind="box" analitico (incluye yaw+pitch) -> el path mesh no regresiona;
  4. carve_mesh sobre una sala da el MISMO conjunto de tets removidos con la
     caja analitica y con su OBJ (equivalencia end-to-end);
  5. round-trip .room (to_dict/from_dict) preserva la malla y el contains;
  6. aabb() coincide con el bounding box de la malla.

Correr: PYTHONIOENCODING=utf-8 python bench_cad.py
"""
import os
import tempfile

import numpy as np
import trimesh

import furniture as F

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIR = os.path.join(HERE, "silla_test.obj")

_fails = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fails.append(name)


def _box_obj(extents, path):
    """Escribe una caja centrada en el origen como OBJ y devuelve el path."""
    b = trimesh.creation.box(extents=extents)
    b.export(path)
    return path


# --- 1. carga de la silla fixture ------------------------------------------
furn, warns = F.load_furniture_mesh(CHAIR, label="Silla CAD")
check("1a silla carga como mesh", furn.kind == "mesh")
check("1b silla watertight (sin warnings)", not warns, detail=str(warns))
check("1c volumen ~0.023 m3", abs(furn.volume() - 0.023002) < 1e-4,
      detail=f"V={furn.volume():.5f}")

# --- 2. contains adentro/afuera --------------------------------------------
# La silla se guarda centrada en su bbox; position = centro del bbox. En coords
# de MUNDO (yaw=0) reproduce el OBJ original (asiento z~0.45, respaldo y=-0.20).
inside = np.array([[0.0, 0.0, 0.45],       # centro del asiento
                   [0.0, -0.20, 0.70]])    # respaldo
outside = np.array([[1.0, 1.0, 1.0],       # lejos
                    [0.0, 0.0, 2.0]])       # arriba de todo
check("2a puntos interiores -> True", furn.contains(inside).all())
check("2b puntos exteriores -> False", (~furn.contains(outside)).all())

# --- 3. regresion caja analitica vs caja-OBJ (yaw+pitch) -------------------
tmpdir = tempfile.mkdtemp()
ext = (0.6, 0.4, 0.5)
obj_box = _box_obj(ext, os.path.join(tmpdir, "caja.obj"))
mfurn, _ = F.load_furniture_mesh(obj_box)
# Colocar ambas en la misma pose.
P, YAW, PITCH = (1.2, 0.7, 0.9), 35.0, 18.0
bbox = F.Furniture("box", position=P, size=ext, orientation=YAW, pitch=PITCH)
mfurn.position, mfurn.orientation, mfurn.pitch = P, YAW, PITCH
rng = np.random.default_rng(0)
cloud = rng.uniform(-1, 3, size=(4000, 3))
ca, cm = bbox.contains(cloud), mfurn.contains(cloud)
agree = (ca == cm).mean()
check("3 caja analitica == caja-OBJ (yaw+pitch)", agree > 0.999,
      detail=f"acuerdo={agree*100:.2f}% ({(ca != cm).sum()} de {len(cloud)})")

# --- 4. carve end-to-end: caja analitica vs OBJ ----------------------------
try:
    import acoustic_mesh
    import geometry
    # Shoebox 3x2.5x2.4 centrada en el origen (como el recinto vivo).
    rverts, rtris = geometry.make_room(3.0, 2.5, 2.4)[:2]
    nodes0, tets0 = acoustic_mesh.build_volume_mesh(
        rverts, rtris, n_per_meter=4.0)
    obj2 = _box_obj((0.8, 0.6, 0.7), os.path.join(tmpdir, "obst.obj"))
    m2, _ = F.load_furniture_mesh(obj2)
    Pc = (0.4, -0.3, -0.2)   # dentro de la sala (centrada en 0)
    m2.position = Pc
    b2 = F.Furniture("box", position=Pc, size=(0.8, 0.6, 0.7))
    _, tb, ib = F.carve_mesh(nodes0, tets0, [b2])
    _, tm2, im = F.carve_mesh(nodes0, tets0, [m2])
    check("4 carve caja == carve OBJ (mismos tets)",
          ib["n_tets_removed"] == im["n_tets_removed"],
          detail=f"box={ib['n_tets_removed']} obj={im['n_tets_removed']}")
except Exception as e:
    check("4 carve caja == carve OBJ", False, detail=f"excepcion: {e}")

# --- 5. round-trip .room ----------------------------------------------------
d = furn.to_dict()
furn2 = F.Furniture.from_dict(d)
check("5a from_dict reconstruye mesh", furn2.kind == "mesh"
      and furn2.mesh_verts is not None
      and len(furn2.mesh_faces) == len(furn.mesh_faces))
check("5b contains identico tras round-trip",
      np.array_equal(furn.contains(inside), furn2.contains(inside))
      and np.array_equal(furn.contains(outside), furn2.contains(outside)))

# --- 6. aabb coincide con el bbox de la malla ------------------------------
lo, hi = furn.aabb()
tm = furn._as_trimesh()
world_lo = furn.position + tm.bounds[0]     # yaw=0 -> traslacion pura
world_hi = furn.position + tm.bounds[1]
check("6 aabb == bbox de la malla (yaw=0)",
      np.allclose(lo, world_lo, atol=1e-9) and np.allclose(hi, world_hi, atol=1e-9),
      detail=f"lo={lo.round(3)} hi={hi.round(3)}")

print()
if _fails:
    print(f"FALLARON {len(_fails)}: {_fails}")
    raise SystemExit(1)
print("bench_cad.py OK")
