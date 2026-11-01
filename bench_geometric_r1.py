"""bench_geometric_r1.py - R1 del motor geometrico: imagenes con visibilidad.

Valida el metodo de imagenes generalizado a geometria arbitraria (presion
compleja) CONTRA el oraculo especular exacto `reflections_ism` en shoebox, mas
el kernel Moller-Trumbore y el test de oclusion con una columna.

Oraculos:
  O1  Moller-Trumbore: un rayo que atraviesa un triangulo da hit + t correcto;
      uno que pasa afuera, no-hit.
  O2  SHOEBOX: el conjunto de imagenes (posicion, orden) coincide EXACTO con
      reflections_ism.image_sources (misma red de espejos).
  O3  SHOEBOX energia: refl_energy por banda == oraculo reflections_ism, para
      alpha escalar, alpha por banda, y alpha DISTINTO por pared (mapeo por cara).
  O4  1er orden analitico: una reflexion de pared sola = (1/4pi d)^2 (1-alpha).
  O5  OCLUSION: segmento por el centro de la columna bloqueado, desviado no; y
      el directo se APAGA cuando la columna se interpone entre fuente y receptor.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_r1.py
"""
import numpy as np

import geometry
import acoustic_mesh
import furniture as fu
import reflections_ism as ism
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# =========================================================================
print("O1: kernel Moller-Trumbore")
V0 = np.array([[0.0, 0.0, 1.0]])
V1 = np.array([[1.0, 0.0, 1.0]])
V2 = np.array([[0.0, 1.0, 1.0]])
t_hit, hit = ge._moller_trumbore(np.array([0.2, 0.2, 0.0]),
                                 np.array([0.0, 0.0, 2.0]), V0, V1, V2)
t_miss, miss = ge._moller_trumbore(np.array([2.0, 2.0, 0.0]),
                                   np.array([0.0, 0.0, 2.0]), V0, V1, V2)
check("O1 rayo atraviesa el triangulo (hit, t=0.5)",
      bool(hit[0]) and abs(t_hit[0] - 0.5) < 1e-9 and not bool(miss[0]),
      f"hit t={t_hit[0]:.4f}, miss hit={bool(miss[0])}")

# =========================================================================
# Shoebox 5x4x3
Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=5.0)
# geometry.make_room centra la caja en x,y (no arranca en el origen); el motor
# trabaja en el marco ABSOLUTO, reflections_ism asume la caja en [0,dims] -> se
# le pasan coords locales (restar vmin). La energia es invariante al marco.
vmin, vmax = nodes.min(0), nodes.max(0)
dims = tuple((vmax - vmin).tolist())
scene = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.2)
refl = ge.build_reflectors(scene)
# fuente/receptor como fracciones de la caja REAL (siempre interiores, sea cual
# sea el marco en que make_room coloque la caja).
src = ge.GeoSource(pos=vmin + np.array([0.22, 0.30, 0.40]) * (vmax - vmin))
rec = ge.GeoReceiver(pos=vmin + np.array([0.72, 0.68, 0.55]) * (vmax - vmin))
MAXO = 2

print("O2: imagenes shoebox vs reflections_ism")
check("O2a build_reflectors da 6 paredes en shoebox", len(refl) == 6,
      f"n_reflectores={len(refl)}")
imgs, _ = ge.image_sources_general(scene, src, MAXO, refl)
set_mine = {(im["order"], tuple(np.round(im["pos"] - vmin, 4))) for im in imgs}
ism_imgs = [im for im in ism.image_sources(src.pos - vmin, dims, MAXO)
            if im["order"] >= 1]
set_ism = {(im["order"], tuple(np.round(im["pos"], 4))) for im in ism_imgs}
check("O2b el conjunto de imagenes (orden,pos) coincide EXACTO",
      set_mine == set_ism,
      f"mias={len(set_mine)}, ism={len(set_ism)}, "
      f"solo_mias={len(set_mine-set_ism)}, solo_ism={len(set_ism-set_mine)}")

# =========================================================================
print("O3: energia por banda vs oraculo (reflections_ism)")


def rel_err(a, b):
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-30)))


# (a) alpha escalar
r1 = ge.early_reflections(scene, src, rec, max_order=MAXO, reflectors=refl)
orc = ism.wall_reflection_energy(src.pos - vmin, rec.pos - vmin, dims,
                                 {w: 0.2 for w in ism.WALLS}, max_order=MAXO)
e_a = rel_err(r1["refl_energy"], orc["total"])
check("O3a alpha escalar: refl_energy == oraculo", e_a < 1e-9,
      f"rel_err={e_a:.2e}, n_paths={r1['n_paths']}")

# (b) alpha por banda (igual en todas las paredes)
bvec = np.linspace(0.05, 0.55, len(ism.octave_bands()))
scene_b = ge.Scene.from_tet_mesh(nodes, tets, alpha=bvec)
r1b = ge.early_reflections(scene_b, src, rec, max_order=MAXO)
orcb = ism.wall_reflection_energy(src.pos - vmin, rec.pos - vmin, dims,
                                  {w: bvec for w in ism.WALLS}, max_order=MAXO)
e_b = rel_err(r1b["refl_energy"], orcb["total"])
check("O3b alpha por banda: refl_energy == oraculo", e_b < 1e-9,
      f"rel_err={e_b:.2e}")

# (c) alpha DISTINTO por pared (mapeo por cara centroidal)
awall = {"x0": 0.10, "xL": 0.30, "y0": 0.05, "yL": 0.40, "z0": 0.60, "zL": 0.02}


def alpha_fn(centroids, bands):
    out = np.zeros((len(centroids), len(bands)))
    for i, cxyz in enumerate(centroids):
        if abs(cxyz[0] - vmin[0]) < 1e-6:
            a = awall["x0"]
        elif abs(cxyz[0] - vmax[0]) < 1e-6:
            a = awall["xL"]
        elif abs(cxyz[1] - vmin[1]) < 1e-6:
            a = awall["y0"]
        elif abs(cxyz[1] - vmax[1]) < 1e-6:
            a = awall["yL"]
        elif abs(cxyz[2] - vmin[2]) < 1e-6:
            a = awall["z0"]
        else:
            a = awall["zL"]
        out[i, :] = a
    return out


scene_c = ge.Scene.from_tet_mesh(nodes, tets, alpha=alpha_fn)
r1c = ge.early_reflections(scene_c, src, rec, max_order=MAXO)
orcc = ism.wall_reflection_energy(src.pos - vmin, rec.pos - vmin, dims, awall,
                                  max_order=MAXO)
e_c = rel_err(r1c["refl_energy"], orcc["total"])
check("O3c alpha distinto por pared: refl_energy == oraculo", e_c < 1e-9,
      f"rel_err={e_c:.2e}")

# =========================================================================
print("O4: 1er orden analitico (una reflexion de piso)")
# reflexion en el piso z=0: imagen (sx,sy,-sz); d = |imagen - receptor|.
alpha_floor = awall["z0"]
img = np.array([src.pos[0], src.pos[1], -src.pos[2]])
d_floor = np.linalg.norm(img - rec.pos)
e_expect = (1.0 / (4 * np.pi * d_floor)) ** 2 * (1 - alpha_floor) * \
    np.exp(-2 * ge._aa.air_absorption_alpha(scene_c.bands) * d_floor)
# buscar en r1c el camino de 1er orden que toca el piso (todas sus caras z0)
floor_path = None
for p in r1c["paths"]:
    if p["order"] == 1:
        cen = scene_c.centroid[p["faces"][0]]
        if abs(cen[2] - vmin[2]) < 1e-6:
            floor_path = p
            break
check("O4 reflexion de piso de 1er orden = (1/4pi d)^2 (1-a) exp(...)",
      floor_path is not None and rel_err(floor_path["energy"], e_expect) < 1e-9,
      f"d={d_floor:.3f}, rel_err="
      f"{rel_err(floor_path['energy'], e_expect):.2e}" if floor_path else "no hallado")

# =========================================================================
print("O5: oclusion con columna piso-techo")
D = 0.8
cx, cy = 0.5 * (vmin[0] + vmax[0]), 0.5 * (vmin[1] + vmax[1])
col = fu.make_column("cylinder", diameter=D, position=(cx, cy, 0.0))
fu.sync_column_height(col, v)
nodesC, tetsC, _ = fu.carve_mesh(nodes, tets, [col])
sceneC = ge.Scene.from_tet_mesh(nodesC, tetsC, alpha=0.2)
Vc = ge._tri_verts(sceneC)

# segmento por el centro (a la altura media) vs desviado
zc = 0.5 * (vmin[2] + vmax[2])
A = np.array([cx - 1.5, cy, zc]); B = np.array([cx + 1.5, cy, zc])
blk_center = ge._segment_blocked(sceneC, A, B, Vc)
A2 = np.array([cx - 1.5, cy + 1.6, zc]); B2 = np.array([cx + 1.5, cy + 1.6, zc])
blk_side = ge._segment_blocked(sceneC, A2, B2, Vc)
check("O5a segmento por el centro de la columna BLOQUEADO, desviado NO",
      blk_center and not blk_side,
      f"centro={blk_center}, desviado={blk_side}")

# directo apagado cuando la columna se interpone
srcC = ge.GeoSource(pos=(cx - 1.6, cy, zc))
recC = ge.GeoReceiver(pos=(cx + 1.6, cy, zc))
rC = ge.early_reflections(sceneC, srcC, recC, max_order=1)
# sin columna, misma config
rN = ge.early_reflections(scene, srcC, recC, max_order=1)
check("O5b directo se APAGA con la columna interpuesta (y prende sin ella)",
      float(np.max(rC["direct"]["energy"])) == 0.0
      and float(np.max(rN["direct"]["energy"])) > 0.0,
      f"E_dir(col)={np.max(rC['direct']['energy']):.2e}, "
      f"E_dir(sin)={np.max(rN['direct']['energy']):.2e}")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
