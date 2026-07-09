"""bench_furniture.py — Oraculos de furniture.py (Fase A).

Valida la talla de mobiliario como obstaculo rigido con casos donde la
respuesta es CONOCIDA analiticamente o por construccion:

  1. Regresion   : muebles=[] -> malla identica bit a bit.
  2. Volumen+solve (R2.3): tallar una caja -> V removido ~ V caja, sin nodos
     huerfanos (K,M ensamblan y eigsh corre = M no singular).
  3. Consistencia (R6.1): tallar una LOSA de una shoebox 5x4x3 -> queda un
     dominio 4x4x3; los modos coinciden con la 4x4x3 ANALITICA y con una
     4x4x3 mallada directo (<3%). Dos formas de armar el mismo dominio.
  4. Signo perturbativo (R6.2): obstaculo en el CENTRO de la sala ->
     el modo axial IMPAR (1,0,0) BAJA (centro = nodo de presion) y el PAR
     (2,0,0) SUBE (centro = antinodo). Los dos sentidos que derivamos.

Correr:  python bench_furniture.py
"""

import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import furniture as fu


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def mesh_room(Lx, Ly, Lz, npm=4.0):
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=npm)
    return nodes, tets


def solve(nodes, tets, n_modes=20):
    K, M, _ = acoustic_fem.build_KM(nodes, tets)
    freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=n_modes)
    return freqs


def nearest(freqs, f0):
    freqs = np.asarray(freqs)
    return float(freqs[np.argmin(np.abs(freqs - f0))])


# ---------------------------------------------------------------------------
print("t1: regresion — muebles=[] deja la malla intacta")
nodes, tets = mesh_room(5, 4, 3, npm=3.0)
n2, t2, info = fu.carve_mesh(nodes, tets, [])
check("nodes/tets identicos", n2.shape == nodes.shape and t2.shape == tets.shape
      and np.array_equal(n2, nodes) and np.array_equal(t2, tets),
      f"{len(nodes)} nodos, {len(tets)} tets")
check("info en cero", info["n_tets_removed"] == 0 and info["n_nodes_pruned"] == 0)

# ---------------------------------------------------------------------------
print("t2: volumen removido, reindex, solubilidad y auditoria del escalonado")
# (a) caja ALINEADA a la grilla (h=0.25 con npm=4; bordes en lineas de grilla
#     x=+-0.5, y=+-0.5, z=0.5/1.5) -> volumen casi exacto.
nodes, tets = mesh_room(5, 4, 3, npm=4.0)
sofa = fu.Furniture("box", position=(0.0, 0.0, 1.0), size=(1.0, 1.0, 1.0),
                    label="sofa")
n2, t2, info = fu.carve_mesh(nodes, tets, [sofa])
check("(a) caja alineada: V removido ~ V geometrico (<5%)",
      info["V_error_frac"] < 0.05,
      f"V_mesh={info['V_removed_mesh']:.3f} vs V_geom={info['V_furniture_geom']:.3f} "
      f"({info['V_error_frac']*100:.1f}%)")
check("(a) indices de tets validos tras reindex",
      t2.min() >= 0 and t2.max() < len(n2))
check("(a) nodos huerfanos podados", info["n_nodes_pruned"] > 0,
      f"{info['n_nodes_pruned']} podados, {info['n_tets_removed']} tets fuera")
try:
    fr = solve(n2, t2, n_modes=15)
    solved = np.all(np.isfinite(fr)) and len(fr) >= 10
except Exception as e:
    solved = False; fr = str(e)
check("(a) K,M ensamblan y eigsh corre (M no singular)", solved,
      (f"{len(fr)} modos" if solved else str(fr)))
# (b) caja NO alineada (0.9 m sobre h=0.25) -> el escalonado se dispara y
#     la advertencia de auditoria (R2.2) DEBE aparecer.
bad = fu.Furniture("box", position=(0.0, 0.0, 0.8), size=(0.9, 0.9, 0.9),
                   label="no-alineada")
_n, _t, info_b = fu.carve_mesh(nodes, tets, [bad])
check("(b) auditoria detecta el escalonado (warning presente)",
      info_b["V_error_frac"] > 0.05 and len(info_b["warnings"]) > 0,
      f"error {info_b['V_error_frac']*100:.0f}% -> {info_b['warnings']}")

# ---------------------------------------------------------------------------
print("t3: consistencia — losa tallada de 5x4x3 == dominio 4x4x3")
# Sala 5x4x3 centrada en origen: x in [-2.5, 2.5]. Tallar x in [1.5, 2.5]
# (losa full y,z) deja x in [-2.5, 1.5] = ancho 4 -> 4x4x3.
nodes, tets = mesh_room(5, 4, 3, npm=4.0)
slab = fu.Furniture("box", position=(2.0, 0.0, 1.5), size=(1.0, 100.0, 100.0),
                    label="losa")
n2, t2, info = fu.carve_mesh(nodes, tets, [slab])
f_carved = solve(n2, t2, n_modes=12)
f_direct = solve(*mesh_room(4, 4, 3, npm=4.0), n_modes=12)


def analytic_shoebox(Lx, Ly, Lz, fmax=120, c=343.0):
    out = []
    for nx in range(4):
        for ny in range(4):
            for nz in range(3):
                if nx == ny == nz == 0:
                    continue
                f = c/2*np.sqrt((nx/Lx)**2 + (ny/Ly)**2 + (nz/Lz)**2)
                if f <= fmax:
                    out.append(f)
    return np.array(sorted(out))


f_an = analytic_shoebox(4, 4, 3)
# Comparar los primeros 3 modos axiales conocidos de la 4x4x3:
#   f100=42.9  f001=57.2  f200=85.8
for f0, tag in [(42.875, "100"), (57.17, "001"), (85.75, "200")]:
    fc = nearest(f_carved, f0)
    fd = nearest(f_direct, f0)
    e_ca = abs(fc - f0) / f0 * 100
    e_cd = abs(fc - fd) / fd * 100
    check(f"modo {tag}: tallado vs analitico {e_ca:.1f}% / vs directo {e_cd:.1f}%",
          e_ca < 4.0 and e_cd < 4.0,
          f"tallado={fc:.1f} analitico={f0:.1f} directo={fd:.1f}")

# ---------------------------------------------------------------------------
print("t4: signo perturbativo — obstaculo en el centro: (1,0,0) baja, (2,0,0) sube")
# Sala 7x3x2.5 (axiales x aislados). Obstaculo cubo en el centro (0,0,H/2).
Lx, Ly, Lz = 7.0, 3.0, 2.5
nodes, tets = mesh_room(Lx, Ly, Lz, npm=4.0)
f_base = solve(nodes, tets, n_modes=16)
# cubo 1 m centrado (bordes en lineas de grilla: x,y=+-0.5, z=0.75/1.75)
obst = fu.Furniture("box", position=(0.0, 0.0, Lz/2), size=(1.0, 1.0, 1.0),
                    label="obstaculo")
n2, t2, info = fu.carve_mesh(nodes, tets, [obst])
f_pert = solve(n2, t2, n_modes=16)

f100 = 343/(2*Lx)      # 24.5  (impar: centro = nodo -> baja)
f200 = 343/Lx          # 49.0  (par:   centro = antinodo -> sube)
b100, p100 = nearest(f_base, f100), nearest(f_pert, f100)
b200, p200 = nearest(f_base, f200), nearest(f_pert, f200)
d100 = (p100 - b100) / b100 * 100
d200 = (p200 - b200) / b200 * 100
check("(1,0,0) BAJA (centro = nodo de presion)", d100 < -0.15,
      f"{b100:.2f} -> {p100:.2f} Hz  ({d100:+.2f}%)")
check("(2,0,0) SUBE (centro = antinodo de presion)", d200 > 0.15,
      f"{b200:.2f} -> {p200:.2f} Hz  ({d200:+.2f}%)")
check("V del obstaculo desplazado (alineado, <8%)", info["V_error_frac"] < 0.08,
      f"V_mesh={info['V_removed_mesh']:.3f} vs {info['V_furniture_geom']:.3f} m3")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
