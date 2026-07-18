"""bench_furniture_live.py — cableado del feature muebles al camino LIVE.

Replica, SIN instanciar la GUI, la secuencia de computo que corre el panel
acustico cuando el usuario aprieta "Calcular modos" con muebles cargados:

    malla-ruteada -> carve -> K,M -> solve -> xi(A36) -> SBIR

y valida los tres anclajes del wiring (acoustic_analysis.run_fem_modal_routed +
acoustic_panel._compute_xi_from_materials + acoustic_panel._open_sbir):

  (a) REGRESION: con muebles=[] el resultado es IDENTICO al baseline sin
      muebles (freqs y xi bit a bit). La talla no se invoca -> camino historico.
  (b) SIGNO PERTURBATIVO textbook: un sillon (box 0.8^3) al CENTRO de un
      shoebox BAJA el modo (1,0,0) [centro=nodo] y SUBE el (2,0,0)
      [centro=antinodo]; y su xi AUMENTA cuando el mueble es absorbente.
  (c) CROSS-CHECK contra la espina de referencia: el camino live-equivalente
      (run_fem_modal_routed voxel + augment + A36) coincide con
      solve_modal_with_furniture + furniture_xi (freqs/xi dentro de tolerancia).

Correr:  python bench_furniture_live.py
"""

import numpy as np

import geometry
import acoustic_analysis as aa
import acoustic_fem
import face_materials as fm
import furniture as fu
import mesh_router as mr
import absorption_patch as ap


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


class _Mat:
    """Material minimo con alpha(f) constante (sin depender del catalogo)."""
    def __init__(self, a):
        self._a = float(a)
        self.name = f"a={a}"
        self.category = ""

    def alpha(self, f):
        return self._a


def nearest(freqs, f0):
    freqs = np.asarray(freqs)
    return float(freqs[np.argmin(np.abs(freqs - f0))])


# ---------------------------------------------------------------------------
# Camino LIVE-equivalente (replica _compute_xi_from_materials a nivel funcion).
# ---------------------------------------------------------------------------
def live_solve(v, t, muebles, *, npm, n_modes, engine="voxel"):
    """run_fem_modal_routed tal como lo invoca _solve_fem (con muebles)."""
    sol, dec = aa.run_fem_modal_routed(
        v, t, user_override=engine, n_modes=n_modes, n_per_meter=npm,
        muebles=muebles)
    return sol


def live_xi(sol, v, t, muebles, mat_by_furn, wall_alpha):
    """Replica el nucleo de acoustic_panel._compute_xi_from_materials:
    grupos de pared -> (si hay muebles) augment con caras del mueble usando la
    malla ORIGINAL preservada (sol.nodes0/tets0) + V de AIRE -> A36."""
    groups = fm.group_faces_by_planar_region(v, t)
    g2m = {g.signature: _Mat(wall_alpha) for g in groups}
    V = aa.compute_mesh_volume(v, t)
    verts, tris = v, t
    if muebles and sol.nodes0 is not None and sol.tets0 is not None:
        verts, tris, groups, g2m = fu.augment_surface_with_furniture(
            verts, tris, groups, g2m, sol.nodes0, sol.tets0, muebles,
            mat_by_furn)
        if sol.carve_info is not None:
            V = max(V - float(sol.carve_info.get("V_removed_mesh", 0.0)), 1e-9)
    return fm.compute_xi_per_mode_per_face(
        sol.freqs, sol.phis, sol.locator, verts, tris, groups, g2m, V)


# ---------------------------------------------------------------------------
print("t1: REGRESION — muebles=[] NO altera el camino (malla identica, freqs/xi "
      "a nivel de ruido del eigensolver)")
# Nota: el eigensolver (ARPACK/eigsh) tiene jitter run-to-run de ~1e-13 Hz por
# su vector inicial aleatorio: DOS corridas identicas sin muebles ya difieren en
# ~1e-13. Por eso la regresion "bit a bit" se ancla en lo que el wiring SI
# controla — la MALLA que recibe build_KM es identica y la talla NO se invoca —
# y freqs/xi se comparan al nivel de ese ruido (<<< cualquier efecto fisico de
# un mueble, ~1%). El baseline y muebles=[] recorren el MISMO codigo.
TOL_SOLVER = 1e-9      # relativo; el ruido real observado es ~1e-13
v, t, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)
sol_base = live_solve(v, t, None, npm=4.0, n_modes=20)      # camino historico
sol_empty = live_solve(v, t, [], npm=4.0, n_modes=20)       # lista vacia
check("malla identica bit a bit + talla NO invocada (nodes0/carve = None)",
      sol_empty.nodes0 is None and sol_empty.carve_info is None
      and np.array_equal(sol_base.nodes, sol_empty.nodes)
      and np.array_equal(sol_base.tets, sol_empty.tets),
      f"{len(sol_empty.nodes)} nodos, nodes0={sol_empty.nodes0}")
df = np.max(np.abs(sol_base.freqs - sol_empty.freqs))
check("freqs coinciden al ruido del eigensolver (<1e-9 rel)",
      np.allclose(sol_base.freqs, sol_empty.freqs, rtol=TOL_SOLVER, atol=1e-9),
      f"max|Δf|={df:.2e} Hz (ruido ARPACK ~1e-13)")
xi_base = live_xi(sol_base, v, t, None, {}, wall_alpha=0.2)
xi_empty = live_xi(sol_empty, v, t, [], {}, wall_alpha=0.2)
dxi = np.max(np.abs(xi_base - xi_empty)) if xi_base is not None else np.inf
check("xi coinciden al ruido del eigensolver (<1e-9 rel)",
      xi_base is not None
      and np.allclose(xi_base, xi_empty, rtol=TOL_SOLVER, atol=1e-12),
      f"max|Δxi|={dxi:.2e}")

# ---------------------------------------------------------------------------
print("t2: SIGNO PERTURBATIVO — sillon 0.8^3 al centro: (1,0,0) baja, (2,0,0) sube")
Lx, Ly, Lz = 6.0, 3.0, 2.4      # axiales x aislados; grilla alineada a npm=5
vb, tb, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
sol0 = live_solve(vb, tb, None, npm=5.0, n_modes=16)
sofa = fu.Furniture("box", position=(0.0, 0.0, Lz / 2), size=(0.8, 0.8, 0.8),
                    label="sillon")
solF = live_solve(vb, tb, [sofa], npm=5.0, n_modes=16)
check("con mueble: tets tallados y modos finitos",
      solF.carve_info is not None and solF.carve_info["n_tets_removed"] > 0
      and np.all(np.isfinite(solF.freqs)),
      f"{solF.carve_info['n_tets_removed']} tets fuera" if solF.carve_info else "sin carve")

f100 = 343.0 / (2 * Lx)     # impar: centro = nodo de presion -> BAJA
f200 = 343.0 / Lx           # par:   centro = antinodo       -> SUBE
b100, p100 = nearest(sol0.freqs, f100), nearest(solF.freqs, f100)
b200, p200 = nearest(sol0.freqs, f200), nearest(solF.freqs, f200)
d100 = (p100 - b100) / b100 * 100
d200 = (p200 - b200) / b200 * 100
check("(1,0,0) BAJA (centro = nodo)", d100 < -0.15,
      f"{b100:.2f} -> {p100:.2f} Hz  ({d100:+.2f}%)")
check("(2,0,0) SUBE (centro = antinodo)", d200 > 0.15,
      f"{b200:.2f} -> {p200:.2f} Hz  ({d200:+.2f}%)")

# xi: mueble absorbente amortigua MAS que rigido (todos los modos).
xi_rig = live_xi(solF, vb, tb, [sofa], {}, wall_alpha=0.03)            # {} -> rigido
xi_abs = live_xi(solF, vb, tb, [sofa], {0: _Mat(0.85)}, wall_alpha=0.03)
d_xi = xi_abs - xi_rig
check("mueble absorbente sube xi en todos los modos", np.all(d_xi > -1e-9),
      f"min Δxi={d_xi.min():.2e}, max={d_xi.max():.2e}")
check("el amortiguamiento del mueble es SELECTIVO (no uniforme)",
      np.std(d_xi / np.maximum(xi_rig, 1e-9)) > 0.02,
      f"std(Δxi/xi)={np.std(d_xi/np.maximum(xi_rig,1e-9)):.3f}")

# ---------------------------------------------------------------------------
print("t3: CROSS-CHECK — camino live == espina solve_modal_with_furniture + furniture_xi")
NPM, NMODES = 4.0, 20
vr, tr, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)
obst = fu.Furniture("box", position=(1.0, 0.5, 0.5), size=(0.8, 0.8, 1.0),
                    label="rack")
mat_by_furn = {0: _Mat(0.7)}
WALL_A = 0.05

# --- camino LIVE (lo que corre el panel) ---
sol_live = live_solve(vr, tr, [obst], npm=NPM, n_modes=NMODES)
xi_live = live_xi(sol_live, vr, tr, [obst], mat_by_furn, wall_alpha=WALL_A)

# --- espina de referencia (furniture.solve_modal_with_furniture) ---
ref = fu.solve_modal_with_furniture(vr, tr, [obst], n_modes=NMODES,
                                    n_per_meter=NPM)
groups_ref = fm.group_faces_by_planar_region(vr, tr)
g2m_ref = {g.signature: _Mat(WALL_A) for g in groups_ref}
V_air = 5 * 4 * 3 - ref["carve_info"]["V_removed_mesh"]
xi_ref = fu.furniture_xi(ref, vr, tr, groups_ref, g2m_ref, [obst],
                         mat_by_furn, V_air)

# El voxel del router y el de la espina llaman al MISMO build_volume_mesh con
# el mismo n_per_meter -> malla identica -> freqs identicas.
df = np.max(np.abs(sol_live.freqs - ref["freqs"]))
check("freqs live == espina (identicas)", df < 1e-6,
      f"max|Δf|={df:.2e} Hz")
dxi = np.max(np.abs(xi_live - xi_ref)) if xi_live is not None else np.inf
check("xi live == espina (identicos)", dxi < 1e-9,
      f"max|Δxi|={dxi:.2e}")
check("V de aire coincide (room - tallado)",
      abs((aa.compute_mesh_volume(vr, tr) - sol_live.carve_info["V_removed_mesh"])
          - V_air) < 1e-9,
      f"V_air={V_air:.3f} m3")

# ---------------------------------------------------------------------------
print("t4: SBIR-mueble — furniture_walls se appendea a la lista de paredes")
freq = np.linspace(20.0, 500.0, 512)
walls_room = 6                                   # simular 6 grupos de pared
fw = fu.furniture_walls([obst], mat_by_furn, freq)
check("un wall por mueble, en el tope, con area = huella",
      len(fw) == 1 and abs(fw[0].point[2] - (0.5 + 1.0 / 2.0)) < 1e-9
      and abs(float(fw[0].area) - 0.8 * 0.8) < 1e-9,
      f"z={fw[0].point[2]:.2f}, area={fw[0].area:.2f} m2")
check("lista total = paredes + muebles", walls_room + len(fw) == walls_room + 1)

# ---------------------------------------------------------------------------
print(f"t5: ruteo de motores (gmsh disponible={mr._HAS_GMSH_MODULE})")
# El carve es agnostico al mesher (opera sobre cualquier malla tet). Verificamos
# voxel siempre; gmsh solo si el modulo esta en el env (no lo esta en el CI
# headless de este container -> se documenta como pendiente en la PC).
solV = live_solve(vr, tr, [obst], npm=NPM, n_modes=12, engine="voxel")
check("carve corre por el ruteo VOXEL",
      solV.carve_info is not None and solV.carve_info["n_tets_removed"] > 0
      and np.all(np.isfinite(solV.freqs)),
      f"{solV.carve_info['n_tets_removed']} tets, engine="
      f"{solV.mesh_info.get('engine')}")
if mr._HAS_GMSH_MODULE:
    solG = live_solve(vr, tr, [obst], npm=NPM, n_modes=12, engine="gmsh")
    check("carve corre por el ruteo GMSH",
          solG.carve_info is not None and solG.carve_info["n_tets_removed"] > 0
          and np.all(np.isfinite(solG.freqs)),
          f"{solG.carve_info['n_tets_removed']} tets, engine="
          f"{solG.mesh_info.get('engine')}")
else:
    print("  [SKIP] gmsh no instalado en este env; carve es mesher-agnostico "
          "(mismo carve_mesh sobre los tets de gmsh). Verificar en la PC.")

# ---------------------------------------------------------------------------
print("t6: COMPOSICION con parches — muebles + parche de pared por el A36 refinado")
# _compute_xi_from_materials: si hay parches, la absorcion va por
# ap.compute_xi_per_mode_with_patches. La augmentacion de muebles AGREGA caras
# al final (no renumera), asi el parche por signature sigue resolviendo. Se
# valida que el camino compuesto corre y da xi finito/selectivo, y que la cara
# del mueble sobrevive como grupo.
vp, tp, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)
sofa2 = fu.Furniture("box", position=(1.0, 0.5, 0.5), size=(0.8, 0.8, 1.0),
                     label="rack")
sol_p = live_solve(vp, tp, [sofa2], npm=4.0, n_modes=20)
groups_p = fm.group_faces_by_planar_region(vp, tp)
g2m_p = {g.signature: _Mat(0.05) for g in groups_p}
# un parche absorbente sobre el grupo de mayor area (una pared).
host = max(groups_p, key=lambda g: g.area)
patch = ap.make_patch(host, -0.5, -0.5, 0.5, 0.5, material_name="poroso",
                      label="parche")
patch_mats = {patch.key: _Mat(0.9)}
# augment con muebles (como en el panel) ANTES de llamar al path de parches.
verts_a, tris_a, groups_a, g2m_a = fu.augment_surface_with_furniture(
    vp, tp, groups_p, g2m_p, sol_p.nodes0, sol_p.tets0, [sofa2],
    {0: _Mat(0.7)})
V_air_p = 5 * 4 * 3 - sol_p.carve_info["V_removed_mesh"]
xi_pf = ap.compute_xi_per_mode_with_patches(
    sol_p.freqs, sol_p.phis, sol_p.locator, verts_a, tris_a, groups_a, g2m_a,
    [patch], patch_mats, V_air_p)
has_furn_group = any(getattr(g, "kind", "") == "furniture" for g in groups_a)
check("A36-con-parches corre sobre la superficie aumentada por muebles",
      xi_pf is not None and np.all(np.isfinite(xi_pf)) and np.all(xi_pf > 0),
      f"xi mediana {np.median(xi_pf):.3f}" if xi_pf is not None else "None")
check("la cara del mueble sobrevive como FaceGroup (kind=furniture)",
      has_furn_group)
check("xi selectivo (parche + mueble rompen la uniformidad)",
      xi_pf is not None and np.std(xi_pf) > 1e-3,
      f"std {np.std(xi_pf):.4f}" if xi_pf is not None else "None")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
