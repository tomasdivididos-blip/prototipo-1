"""bench_geometric_r3.py - R3 del motor geometrico: difraccion de bordes BTM.

Valida la linea-integral BTM en frecuencia (`geometric_engine.btm_edge_H_finite`,
Calamia 2009 ec. 3.14) contra la solucion EXACTA del borde infinito (integral de
contorno de Bowman & Senior / Pierce, ec. 3.15/3.16), derivacion INDEPENDIENTE,
mas propiedades exactas del campo difractado.

Oraculos:
  O1  CONVERGENCIA AL BORDE INFINITO EXACTO: el borde finito (ec. 3.14) converge
      a la referencia exacta (ec. 3.15) al crecer la longitud -> error ~100 dB
      abajo a 200 m (reproduce Fig 3.5 de la tesis), con la geometria de Fig 3.4.
  O2  RECIPROCIDAD: intercambiar fuente y receptor da el MISMO H_diffr (ec. 3.14).
  O3  CUNA NO DIFRACTANTE: theta_W=pi (cara plana, sin borde) -> H_diffr = 0.
  O4  EXTRACCION DE BORDES: build_edges sobre un shoebox halla las 12 aristas
      reales con theta_W~90 (esquina concava, nu=2, no difracta); y wedge_coords
      da theta_W~270 en un borde convexo recto (nu=2/3, difracta).
  O5  APICE Y FRONTERA: el punto de apice (min m+l) cae DENTRO del borde, y la
      difraccion se concentra cerca de la frontera de sombra (|H| mayor ahi).

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_r3.py
"""
import numpy as np

import geometry
import acoustic_mesh
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


D2R = np.pi / 180.0
# geometria de Fig 3.4 (Calamia 2009): cuna rigida theta_W=315, fuente y receptor.
thW = 315.0 * D2R
rS, thS, zS = 2.0, 45.0 * D2R, 0.0
rR, thR, zR = 5.0, 270.0 * D2R, 0.0
freqs = np.array([100.0, 250.0, 500.0])


def relerr(a, b):
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-30)))


print("O1: borde finito (ec. 3.14) -> borde infinito exacto (ec. 3.15)")
Href = ge.btm_edge_H_infinite(rS, thS, zS, rR, thR, zR, thW, freqs)
errs = {}
for L in (12.5, 50.0, 200.0):
    Hfin = ge.btm_edge_H_finite(rS, thS, zS, rR, thR, zR, thW,
                                -L / 2.0, L / 2.0, freqs, n_pts=40001)
    errs[L] = relerr(Hfin, Href)
mono = errs[12.5] > errs[50.0] > errs[200.0]
check("O1 convergencia a la referencia exacta (err<1e-4 a 200 m, decrece con L)",
      errs[200.0] < 1e-4 and mono,
      f"err(L=12.5)={errs[12.5]:.2e}, err(50)={errs[50.0]:.2e}, "
      f"err(200)={errs[200.0]:.2e}; |Href|={np.abs(Href)}")

print("O2: reciprocidad fuente<->receptor (ec. 3.14)")
L = 10.0
H_sr = ge.btm_edge_H_finite(rS, thS, 1.0, rR, thR, -2.0, thW, 0.0, L, freqs, n_pts=20001)
H_rs = ge.btm_edge_H_finite(rR, thR, -2.0, rS, thS, 1.0, thW, 0.0, L, freqs, n_pts=20001)
check("O2 H(S,R) == H(R,S)", relerr(H_sr, H_rs) < 1e-9,
      f"rel_err={relerr(H_sr, H_rs):.2e}")

print("O3: cuna plana theta_W=pi (sin borde) -> no difracta")
H_flat = ge.btm_edge_H_finite(rS, thS, 0.0, rR, thR, 0.0, np.pi, -50.0, 50.0,
                              freqs, n_pts=40001)
check("O3 |H_diffr| ~ 0 para theta_W=pi",
      float(np.max(np.abs(H_flat))) < 1e-9,
      f"max|H_flat|={np.max(np.abs(H_flat)):.2e}, |Href(315)|~{np.abs(Href[0]):.2e}")

print("O4: extraccion de bordes (build_edges) + theta_W")
v, t, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
scene = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1)
edges = ge.build_edges(scene)
thWs = np.array([e["thW"] for e in edges]) / D2R
n90 = int(np.sum(np.abs(thWs - 90.0) < 5.0))
check("O4a shoebox: ~12 aristas, todas esquina concava theta_W~90 (nu=2)",
      len(edges) == 12 and n90 == len(edges),
      f"n_edges={len(edges)}, con thW~90={n90}, thW(deg)={np.round(np.sort(thWs),1)}")

# borde convexo recto a 270 (dos caras a 90 grados, aire del lado reflex)
A = np.array([0.0, 0.0, 0.0]); B = np.array([0.0, 0.0, 1.0])
# cara A en el plano y=0 (se extiende a x>0), normal al aire -y (aire en y<0 lado reflex)
faceA_cen = np.array([0.5, 0.0, 0.5]); faceA_nrm = np.array([0.0, -1.0, 0.0])
# cara B en el plano x=0 (se extiende a y>0), normal al aire -x
faceB_cen = np.array([0.0, 0.5, 0.5])
_r, _th, _z, thW270, _L = ge.wedge_coords(A, B, faceA_cen, faceA_nrm, faceB_cen,
                                          np.array([1.0, 1.0, 0.5]))
check("O4b borde convexo recto -> theta_W~270 (nu=2/3)",
      abs(thW270 / D2R - 270.0) < 1.0,
      f"thW={thW270/D2R:.2f} deg, nu={np.pi/thW270:.3f}")

print("O5: apice dentro del borde + concentracion en la frontera de sombra")
# apice = argmin(m+l) sobre el borde, geometria Fig 3.4 centrada
Lz = 6.0
z = np.linspace(-Lz / 2, Lz / 2, 4001)
m = np.sqrt(rS**2 + (z - zS)**2); l = np.sqrt(rR**2 + (z - zR)**2)
z_apex = z[np.argmin(m + l)]
apex_in = (-Lz / 2 < z_apex < Lz / 2)
# frontera de sombra en theta_R = pi + theta_S; difraccion mas fuerte cerca
thR_bnd = np.pi + thS
H_near = ge.btm_edge_H_infinite(rS, thS, zS, rR, thR_bnd + 0.3 * D2R, zR, thW, freqs)
H_far = ge.btm_edge_H_infinite(rS, thS, zS, rR, 270.0 * D2R, zR, thW, freqs)
concentra = np.abs(H_near[0]) > np.abs(H_far[0])
check("O5 apice interior al borde y difraccion concentrada en la sombra",
      apex_in and concentra,
      f"z_apex={z_apex:.3f} (borde [{-Lz/2},{Lz/2}]); "
      f"|H| sombra={np.abs(H_near[0]):.2e} > lejos={np.abs(H_far[0]):.2e}")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
