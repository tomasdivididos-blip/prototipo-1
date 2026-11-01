"""bench_geometric_engine.py - R0 del motor geometrico (andamiaje).

Valida el EXTRACTOR de caras de frontera y el contrato de I/O (geometria pura,
SIN fisica nueva). La fisica de cada fase (R1-R5) tiene su propio bench.

Oraculos:
  O1  SHOEBOX: las caras de frontera tapizan EXACTO las 6 paredes planas ->
      area total = 2(LxLy + LxLz + LyLz), al cero numerico. Normales axis-aligned.
  O2  MANIFOLD CERRADO: cada arista de la superficie de frontera es compartida por
      EXACTAMENTE 2 caras (superficie cerrada, orientable) - shoebox y columna.
  O3  NORMALES AL AIRE: en el shoebox (convexo) toda normal de cara apunta HACIA
      el centro del recinto (hacia el aire), no hacia afuera.
  O4  COLUMNA TALLADA: la frontera incluye el tunel de la columna -> area extra
      ~ lateral del cilindro 2*pi*R*H (dentro del facetado de la grilla), la
      superficie sigue cerrada, y hay mas caras que el shoebox vacio.
  O5  CONTRATO: Scene.from_tet_mesh liga alpha a (K,B); el oraculo especular
      (reflections_ism) corre y da energia finita con la forma correcta.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_engine.py
"""
import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import furniture as fu
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def _edge_manifold(faces):
    """Devuelve (frac_de_aristas_compartidas_por_2, n_aristas). Una superficie
    triangular cerrada tiene TODAS sus aristas en exactamente 2 caras."""
    e = []
    for tri in faces:
        a, b, c = tri
        e += [tuple(sorted((a, b))), tuple(sorted((b, c))), tuple(sorted((a, c)))]
    e = np.array(e)
    _u, counts = np.unique(e, axis=0, return_counts=True)
    return float(np.mean(counts == 2)), len(_u)


# --- shoebox 5x4x3 ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes0, tets0 = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=5.0)
faces0, tet0 = ge.boundary_faces(nodes0, tets0)
cen0, nrm0, area0 = ge.face_geometry(nodes0, faces0)

print("O1-O3: shoebox %gx%gx%g" % (Lx, Ly, Lz))
area_true = 2.0 * (Lx * Ly + Lx * Lz + Ly * Lz)
A = float(area0.sum())
check("O1 area de la frontera = 2(ab+ac+bc) exacto",
      abs(A - area_true) / area_true < 1e-9,
      f"A={A:.6f} m2 vs {area_true:.6f} (err {abs(A-area_true)/area_true:.2e})")

# normales axis-aligned (una componente ~1, las otras ~0)
maxcomp = np.max(np.abs(nrm0), axis=1)
check("O1b normales axis-aligned (|n_dominante|~1)",
      np.all(maxcomp > 0.999),
      f"min(max|n|)={maxcomp.min():.5f}")

frac2, nedges = _edge_manifold(faces0)
check("O2 superficie cerrada (toda arista en 2 caras)",
      frac2 == 1.0, f"aristas en 2 caras = {frac2*100:.1f}% de {nedges}")

mid = 0.5 * (nodes0.min(0) + nodes0.max(0))
to_center = mid - cen0
dot = np.einsum("ij,ij->i", nrm0, to_center)
check("O3 normales apuntan al aire (hacia el centro, shoebox convexo)",
      np.mean(dot > 0) > 0.999, f"adentro={np.mean(dot>0)*100:.1f}%")

# --- shoebox + columna cilindrica piso-techo ---
print("O4: columna cilindrica Ø0.80 m piso-techo")
D = 0.8
R = D / 2.0
cx, cy = 0.5 * (nodes0[:, 0].min() + nodes0[:, 0].max()), \
         0.5 * (nodes0[:, 1].min() + nodes0[:, 1].max())
col = fu.make_column("cylinder", diameter=D, position=(cx, cy, 0.0))
fu.sync_column_height(col, v)
nodesC, tetsC, _info = fu.carve_mesh(nodes0, tets0, [col])
facesC, tetC = ge.boundary_faces(nodesC, tetsC)
cenC, nrmC, areaC = ge.face_geometry(nodesC, facesC)

# Area de la COLUMNA sola = caras que NO estan sobre ninguna de las 6 paredes
# planas (las de la columna estan en el interior). Oraculo limpio (sin mezclar
# la remocion del disco en piso/techo). Un cilindro piso-techo no tiene tapas:
# su area de frontera = lateral. Staircase de la grilla -> area >= lisa.
vmin, vmax = nodesC.min(0), nodesC.max(0)
eps = 1e-6
on_wall = ((np.abs(cenC[:, 0] - vmin[0]) < eps) | (np.abs(cenC[:, 0] - vmax[0]) < eps) |
           (np.abs(cenC[:, 1] - vmin[1]) < eps) | (np.abs(cenC[:, 1] - vmax[1]) < eps) |
           (np.abs(cenC[:, 2] - vmin[2]) < eps) | (np.abs(cenC[:, 2] - vmax[2]) < eps))
col_area = float(areaC[~on_wall].sum())
lateral = 2.0 * np.pi * R * Lz               # lateral liso del cilindro
check("O4a el area de la columna ~ lateral del cilindro (staircase >= liso)",
      0.9 * lateral < col_area < 2.2 * lateral,
      f"col_area={col_area:.3f} m2 vs liso 2piRH={lateral:.3f} (ratio {col_area/lateral:.2f})")

frac2c, nedgesc = _edge_manifold(facesC)
check("O4b la frontera con columna sigue cerrada",
      frac2c == 1.0, f"aristas en 2 caras = {frac2c*100:.1f}%")

check("O4c hay mas caras que el shoebox vacio",
      len(facesC) > len(faces0),
      f"{len(facesC)} caras vs {len(faces0)}")

# caras cerca del canto del cilindro, normal ~ radial (no axis-aligned pura)
rr = np.hypot(cenC[:, 0] - cx, cenC[:, 1] - cy)
near = (rr > R - 0.25) & (rr < R + 0.25) & (cenC[:, 2] > 0.3) & (cenC[:, 2] < Lz - 0.3)
check("O4d existen caras laterales de la columna (canto)",
      np.count_nonzero(near) > 20, f"n_canto={int(np.count_nonzero(near))}")

# --- O5: contrato Scene + oraculo ---
print("O5: contrato Scene.from_tet_mesh + oraculo especular")
sc = ge.Scene.from_tet_mesh(nodes0, tets0, alpha=0.1)
okshape = sc.alpha.shape == (sc.n_faces, len(sc.bands))
# alpha por banda (B,) debe difundirse a (K,B)
bvec = np.linspace(0.05, 0.6, len(ge._ism.octave_bands()))
sc2 = ge.Scene.from_tet_mesh(nodes0, tets0, alpha=bvec)
okbroad = np.allclose(sc2.alpha[0], bvec) and sc2.alpha.shape == (sc2.n_faces, len(bvec))
check("O5a Scene liga alpha a (K,B) (escalar y por banda)",
      okshape and okbroad,
      f"alpha {sc.alpha.shape}, broadcast banda OK={okbroad}")

src = ge.GeoSource(pos=(0.6, 0.6, 1.2))
rec = ge.GeoReceiver(pos=(3.5, 2.5, 1.2))
awall = {w: 0.1 for w in ge._ism.WALLS}
res = ge.specular_oracle_shoebox(src, rec, (Lx, Ly, Lz), awall, max_order=3)
tot = res["total"]
check("O5b oraculo especular corre y da energia finita (B,)",
      tot.shape == ge._ism.octave_bands().shape and np.all(np.isfinite(tot))
      and np.all(tot > 0),
      f"total {tot.shape}, min={tot.min():.2e}, max={tot.max():.2e}")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
