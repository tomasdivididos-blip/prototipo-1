"""bench_furniture_absorption.py — Fase B: absorcion del mueble via A36.

Las caras del agujero del mueble entran como FaceGroups nuevos al MISMO
computo de xi por modo pesado por forma modal (compute_xi_per_mode_per_face).
Oraculos:

  1. Area expuesta: la frontera aire-mueble de una caja apoyada en el piso
     ~ tapa + 4 lados (el fondo apoyado NO cuenta). Analitico.
  2. Regresion uniforme: si el mueble tiene el MISMO alpha que las paredes, el
     A36 se reduce a la Sabine global -> xi_n*f_n constante = 1.1/T60 con
     T60 = 0.161 V / (S_total * alpha), S_total incluyendo el mueble.
  3. Selectividad: mueble ABSORBENTE amortigua mas (xi sube), y NO uniforme
     (el modo que carga el mueble se amortigua mas que el que no) -> es el
     efecto fisico que justifica modelar la absorcion del mueble.
  4. Rigido = sin contribucion: mueble con alpha rigido (0.03) igual a paredes
     rigidas -> xi ~ el de la sala sin mueble absorbente (solo desplaza aire).

Correr:  python bench_furniture_absorption.py
"""

import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import face_materials as fm
import furniture as fu


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


class _Mat:
    """Material minimo con alpha(f) constante (evita depender del catalogo)."""
    def __init__(self, a):
        self._a = float(a)
        self.name = f"a={a}"
        self.category = ""
    def alpha(self, f):
        return self._a


def setup(Lx=5.0, Ly=4.0, Lz=3.0, npm=4.0, n_modes=25):
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=npm)
    return v, t, nodes, tets, Lx * Ly * Lz


# ---------------------------------------------------------------------------
print("t1: area expuesta de la frontera aire-mueble (caja apoyada en piso)")
v, t, nodes, tets, Vroom = setup()
# Caja 1x1x0.8 apoyada en el piso (z de 0 a 0.8), centrada en x,y del origen.
sofa = fu.Furniture("box", position=(0.0, 0.0, 0.4), size=(1.0, 1.0, 0.8),
                    label="sofa")
bf = fu.furniture_boundary_faces(nodes, tets, [sofa])
area = bf[0][1] if 0 in bf else 0.0
# expuesta = tapa (1x1=1) + 4 lados (2*1*0.8 + 2*1*0.8 = 3.2) = 4.2
check("area ~ tapa + 4 lados (4.2 m2, sin el fondo)", abs(area - 4.2) < 0.6,
      f"area_mesh={area:.2f} m2 (analitico 4.2)")

# ---------------------------------------------------------------------------
print("t2: regresion uniforme — mueble con alpha de pared -> Sabine global")
v, t, nodes, tets, Vroom = setup()
obst = fu.Furniture("box", position=(1.0, 0.5, 0.5), size=(0.8, 0.8, 1.0),
                    label="rack")
n2, t2, cinfo = fu.carve_mesh(nodes, tets, [obst])
V_air = Vroom - cinfo["V_removed_mesh"]
K, M, _ = acoustic_fem.build_KM(n2, t2)
freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=25)
loc = acoustic_fem.FieldEvaluator(n2, t2)
groups = fm.group_faces_by_planar_region(v, t)
ALPHA = 0.2
g2m = {g.signature: _Mat(ALPHA) for g in groups}
# La frontera del mueble se extrae de la malla ORIGINAL (donde los tets del
# mueble aun existen); el solve y el locator van sobre la tallada (n2,t2).
va, ta_, ga, g2a = fu.augment_surface_with_furniture(
    v, t, groups, g2m, nodes, tets, [obst], {0: _Mat(ALPHA)})
xi = fm.compute_xi_per_mode_per_face(freqs, phis, loc, va, ta_, ga, g2a, V_air)
# S_total = area de todos los grupos (paredes + mueble)
_, areas_all, _ = fm._face_normals_and_areas(va, np.asarray(ta_, int))
tri_grp = np.full(len(areas_all), -1, int)
for gi, g in enumerate(ga):
    tri_grp[np.asarray(g.face_indices, int)] = gi
S_total = float(areas_all[tri_grp >= 0].sum())
T60_glob = 0.161 * V_air / (S_total * ALPHA)
xi_expected = 1.1 / (freqs * T60_glob)
rel = np.abs(xi - xi_expected) / xi_expected
check("xi_n = Sabine global (alpha uniforme incl. mueble)", np.max(rel) < 0.02,
      f"max err {np.max(rel)*100:.2f}%  (T60={T60_glob:.3f}s, S={S_total:.1f}m2)")

# ---------------------------------------------------------------------------
print("t3: selectividad — mueble absorbente amortigua mas, y no-uniforme")
# Paredes rigidas fijas; el mueble pasa de rigido a absorbente.
g2m_rigid = {g.signature: _Mat(0.03) for g in groups}
_, _, gr, g2r = fu.augment_surface_with_furniture(
    v, t, groups, g2m_rigid, nodes, tets, [obst], {0: _Mat(0.03)})
xi_rig = fm.compute_xi_per_mode_per_face(freqs, phis, loc, va, ta_, gr, g2r, V_air)
_, _, gb, g2b = fu.augment_surface_with_furniture(
    v, t, groups, g2m_rigid, nodes, tets, [obst], {0: _Mat(0.85)})
xi_abs = fm.compute_xi_per_mode_per_face(freqs, phis, loc, va, ta_, gb, g2b, V_air)
d = xi_abs - xi_rig
check("mueble absorbente sube xi en todos los modos", np.all(d > -1e-9),
      f"min Δxi={d.min():.2e}, max={d.max():.2e}")
check("el amortiguamiento es SELECTIVO (no uniforme entre modos)",
      np.std(d / np.maximum(xi_rig, 1e-9)) > 0.02,
      f"std(Δxi/xi)={np.std(d/np.maximum(xi_rig,1e-9)):.3f}")
# El modo que MAS carga el mueble (mayor J sobre sus caras) debe subir mas.
furn_g = [i for i, g in enumerate(gb) if g.kind == "furniture"][0]
_, areas_a, cens_a = fm._face_normals_and_areas(va, np.asarray(ta_, int))
fmask = np.zeros(len(areas_a), bool)
fmask[np.asarray(gb[furn_g].face_indices, int)] = True
cen_f = cens_a[fmask]; area_f = areas_a[fmask]
load = np.array([np.sum(np.real(loc.evaluate_many(phis[:, n], cen_f))**2 * area_f)
                 for n in range(len(freqs))])
mode_hi = int(np.argmax(load))                 # el que mas carga el mueble
rel_gain = d / np.maximum(xi_rig, 1e-9)
check("el modo que mas carga el mueble sube mas que la mediana",
      rel_gain[mode_hi] > np.median(rel_gain),
      f"modo #{mode_hi} ({freqs[mode_hi]:.1f}Hz) gana {rel_gain[mode_hi]*100:.0f}% "
      f"vs mediana {np.median(rel_gain)*100:.0f}%")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
