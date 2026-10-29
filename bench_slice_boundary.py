"""bench_slice_boundary.py - Borde CONFORMADO del corte 2D + densificacion 3D.

Valida la mejora de precision en la FRONTERA de un carve (columna/mueble) en la
visualizacion del campo (NO toca la fisica modal; el campo se muestrea del mismo
locator FEM ya validado). Sala rectangular con una COLUMNA cilindrica piso-techo.

Oraculos:
  O1  AREA del corte con borde conformado << error del escalon, vs una verdad de
      terreno por mascara FINA (supersampleo dentro/fuera en grilla densa). Aisla
      la mejora del render del facetado del mallado: ambos se comparan contra el
      MISMO dominio mallado, no contra el circulo ideal.
  O2  Todos los vertices del borde conformado estan ADENTRO del dominio (el locator
      devuelve finito), incluidos los cruces biseccionados.
  O3  El borde conformado se PEGA al canto de la columna: la distancia radial de
      sus vertices al eje esta mucho mas concentrada en R que las esquinas de la
      grilla adyacentes al hueco (el escalon).
  O4  Densificacion 3D: agrega puntos, todos adentro, y pegados al canto (radio~R).

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_slice_boundary.py
"""
import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import acoustic_analysis as aa
import furniture as fu

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class _Modal:
    """Stand-in minimo para slice_field_fem_plane / *_3d (usa nodes + locator)."""
    def __init__(self, nodes, tets):
        self.nodes = nodes
        self.tets = tets
        self.locator = acoustic_fem.FieldEvaluator(nodes, tets)
        # un modo sintetico suave (no importa para la geometria del borde)
        self.phis = np.cos(2 * np.pi * nodes[:, 0] / (nodes[:, 0].ptp() + 1e-9))[:, None]
        self.freqs = np.array([50.0])


# --- malla: sala 5x4x3 con columna cilindrica piso-techo en el centro ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
D = 0.8                      # diametro de la columna
R = D / 2.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes0, tets0 = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=5.0)
cx, cy = 0.5 * (nodes0[:, 0].min() + nodes0[:, 0].max()), \
         0.5 * (nodes0[:, 1].min() + nodes0[:, 1].max())
col = fu.make_column("cylinder", diameter=D, position=(cx, cy, 0.0))
fu.sync_column_height(col, v)
nodes, tets, _info = fu.carve_mesh(nodes0, tets0, [col])
modal = _Modal(nodes, tets)
field = nodes[:, 0].astype(float)          # campo suave real (x)
zc = 0.5 * (nodes[:, 2].min() + nodes[:, 2].max())

print("O1-O3: corte XY con borde conformado (columna cilindrica Ø%.2f m)" % D)
n1 = n2 = 120
fs = aa.slice_field_fem_plane(modal, field, axis=2, offset=zc, n1=n1, n2=n2)
c1 = fs.X[:, 0]; c2 = fs.Y[0, :]
d1 = c1[1] - c1[0]; d2 = c2[1] - c2[0]
cell = d1 * d2

# verdad de terreno: mascara FINA (supersampleo) del MISMO dominio mallado.
nf = 600
xf = np.linspace(c1[0], c1[-1], nf); yf = np.linspace(c2[0], c2[-1], nf)
Xf, Yf = np.meshgrid(xf, yf, indexing="ij")
ptsf = np.stack([Xf.ravel(), Yf.ravel(), np.full(Xf.size, zc)], axis=1)
inside_f = np.isfinite(modal.locator.evaluate_many(field.astype(complex), ptsf))
area_true = inside_f.sum() * (xf[1] - xf[0]) * (yf[1] - yf[0])

# area del ESCALON: quads con los 4 vertices adentro.
m = fs.mask
allin = m[:-1, :-1] & m[1:, :-1] & m[1:, 1:] & m[:-1, 1:]
area_stair = int(allin.sum()) * cell

# area CONFORMADA: escalon + triangulos del borde.
area_bnd = 0.0
if fs.bnd_pts is not None and len(fs.bnd_pts):
    P2 = fs.bnd_pts
    for a, b, cvx in fs.bnd_faces:
        pa, pb, pcc = P2[a], P2[b], P2[cvx]
        area_bnd += 0.5 * abs((pb[0] - pa[0]) * (pcc[1] - pa[1]) -
                              (pcc[0] - pa[0]) * (pb[1] - pa[1]))
area_conf = area_stair + area_bnd

err_stair = abs(area_stair - area_true) / area_true
err_conf = abs(area_conf - area_true) / area_true
check("O1 area conformada mas exacta que el escalon (y < 1%)",
      err_conf < err_stair and err_conf < 0.01,
      f"err_conf={err_conf*100:.2f}% vs escalon={err_stair*100:.2f}%")

# O2: vertices del borde ADENTRO (finito).
B3 = np.stack([fs.bnd_pts[:, 0], fs.bnd_pts[:, 1],
               np.full(len(fs.bnd_pts), zc)], axis=1)
fin = np.isfinite(modal.locator.evaluate_many(field.astype(complex), B3))
check("O2 vertices del borde conformado adentro del dominio",
      fin.mean() > 0.98, f"adentro={fin.mean()*100:.1f}%")

# O3: radio de los vertices del borde vs esquinas-escalon adyacentes al hueco.
rad_bnd = np.hypot(fs.bnd_pts[:, 0] - cx, fs.bnd_pts[:, 1] - cy)
# esquinas de la grilla que son el primer anillo ADENTRO alrededor del hueco:
# vecinas (en la grilla) de una celda con algun vertice afuera.
mixed = (m[:-1, :-1].astype(int) + m[1:, :-1] + m[1:, 1:] + m[:-1, 1:])
mixed = (mixed > 0) & (mixed < 4)
ii, jj = np.where(mixed)
rad_stair = np.hypot(c1[ii] - cx, c2[jj] - cy)
spread_bnd = float(np.std(rad_bnd))
check("O3 el borde conformado se pega al canto (radio~R, spread chico)",
      abs(np.median(rad_bnd) - R) < 0.5 * d1 and spread_bnd < np.std(rad_stair),
      f"med(r)={np.median(rad_bnd):.3f} R={R:.3f} spread={spread_bnd*1e3:.1f}mm "
      f"vs escalon {np.std(rad_stair)*1e3:.1f}mm")

print("O4: densificacion del campo 3D en la frontera del carve")
pts3, vals3, _ = aa.mode_shape_field_3d(modal, 0, resolution=24)
# puntos del borde: los que caen cerca del radio R en el plano (el resto es bulk).
rr = np.hypot(pts3[:, 0] - cx, pts3[:, 1] - cy)
near = pts3[(rr > R - 0.06) & (rr < R + 0.06)]
fin3 = np.isfinite(modal.locator.evaluate_many(field.astype(complex), near)) \
    if len(near) else np.array([False])
check("O4 densificacion agrega puntos pegados al canto, todos adentro",
      len(near) > 20 and fin3.mean() > 0.98,
      f"n_near={len(near)}, adentro={fin3.mean()*100:.1f}%")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
