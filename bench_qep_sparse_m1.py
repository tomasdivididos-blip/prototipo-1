"""Bench M1 (win-native): el sparse A+B == nodal exacto, y RECUPERA el casi-critico a
escala (regimen sparse Nn>1800) tras el fix del contorno de Beyn.

Historia: el oraculo SLEPc (bench_qep_slepc_scale) expuso que el sparse A+B PERDIA el
casi-critico fuertemente matcheado a Nn>1800 (su polo, con δ grande y fₙ corrida hacia
arriba, quedaba fuera del contorno de Beyn). ARREGLADO en `_beyn_band` (ensanche en Re:
a=1.5wc, z0=-0.35wc). Validado sparse==nodal a 0.0000 a Nn=2660 (WSL/SLEPc). Este bench
lo chequea SIN WSL:

  T1  self-consistencia couple_thr: exacto-en-banda (0) == default (0.6) en los
      casi-criticos (el atajo de velocidad no cambia la fisica).
  T2  sparse == nodal EXACTO + convergencia, en mallas <= 1800 (donde corre el nodal).
  T3  a Nn>1800 (regimen sparse) el sparse RECUPERA el casi-critico fundamental (NO
      colapsa al fallback subestimado): es el fix del contorno. Y el tope de uso quedo
      restaurado (SPARSE_NN_MAX > tope nodal: el sparse SI se usa a escala).

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_qep_sparse_m1.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import face_materials as fm
import qep_sparse as qs
from sources import C0

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def build(Lx, Ly, Lz, npm, n_modes=12):
    vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
    nodes, tets = build_volume_mesh(vr, tr, n_per_meter=npm)
    Nn = nodes.shape[0]
    K, M, _v = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=n_modes)
    gr = fm.group_faces_by_planar_region(vr, tr)
    rm = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)
    Cr, _nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
    loc = FieldEvaluator(nodes, tets)
    G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rm)
    qm = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
    fx, ff = np.asarray(qm[0], float), np.asarray(qm[1], float)

    def sparse(**kw):
        return qs.sparse_boundary_xi_shift(K, M, Cr, freqs, phis, beta=1.0, c=C0,
                                           fallback_xi=fx, fallback_f=ff, **kw)[0]
    nod = fm.qep_boundary_nodal(K, M, Cr, freqs, phis, beta=1.0, c=C0)  # None si Nn>1800
    xn = np.asarray(nod[0], float) if nod is not None else None
    return dict(Nn=Nn, freqs=freqs, sparse=sparse, xn=xn, fx=fx)


print(__doc__.splitlines()[0]); print()
CAP = qs.SPARSE_NN_MAX
NODAL_CAP = inspect.signature(fm.qep_boundary_nodal).parameters["max_dense"].default

# ---------------------------------------------------------------------------
print("T1  self-consistencia couple_thr: exacto-en-banda (0) == default (0.6)")
d = build(7.0, 2.1, 2.3, npm=2.6)
xi0 = d["sparse"](couple_thr=0.0)
xid = d["sparse"](couple_thr=0.6)
crit = xi0 > 0.15
dcrit = float(np.max(np.abs(xi0[crit] - xid[crit]))) if np.any(crit) else 0.0
print(f"  Nn={d['Nn']}, casi-criticos (ξ>0.15): {int(np.sum(crit))}, max|Δξ|={dcrit:.4f}")
check("T1 couple_thr=0 == 0.6 en los casi-criticos (|Δξ| < 0.01)", dcrit < 0.01,
      f"max|Δξ|_crit = {dcrit:.4f}")
print()

# ---------------------------------------------------------------------------
print(f"T2  sparse == nodal EXACTO + convergencia, en el rango usado (Nn <= {CAP})")
res = []
for npm in (2.0, 3.0, 3.4):
    d = build(7.0, 2.1, 2.3, npm=npm)
    assert d["Nn"] <= CAP, "mesh fuera del rango validado"
    xs = d["sparse"]()
    i0 = int(np.argmax(d["xn"]))               # casi-critico fundamental (por el nodal)
    err = abs(xs[i0] - d["xn"][i0]) / max(d["xn"][i0], 1e-9)
    res.append((d["Nn"], float(xs[i0]), float(d["xn"][i0]), err))
    print(f"  Nn={d['Nn']:5d}  sparse={xs[i0]:.4f}  nodal={d['xn'][i0]:.4f}  err={100*err:.1f}%")
max_err = max(r[3] for r in res)
d1 = abs(res[1][1] - res[0][1]); d2 = abs(res[2][1] - res[1][1])
check("T2a el sparse == el nodal exacto en cada malla del rango usado (err < 5%)",
      max_err < 0.05, f"err max = {100*max_err:.1f}%")
check("T2b el ξ del casi-critico converge (diferencias sucesivas decrecen)",
      d2 < d1 + 1e-9, f"|Δ1|={d1:.4f} -> |Δ2|={d2:.4f}")
print()

# ---------------------------------------------------------------------------
print("T3  a Nn>1800 (regimen sparse) el fundamental SE RECUPERA (fix del contorno)")
d = build(7.0, 2.1, 2.3, npm=4.0)                 # Nn~2610, regimen sparse (sin nodal)
xs = d["sparse"]()
i0 = int(np.argmax(xs))
fb0 = float(d["fx"][i0])
# el convergido (de T2) ronda ~0.82; antes del fix el sparse caia al fallback (~0.34)
print(f"  Nn={d['Nn']}  sparse fundamental = {xs[i0]:.3f}  fallback = {fb0:.3f}  "
      f"(convergido ~0.82; pre-fix caia al fallback)")
check("T3a a Nn>1800 el sparse recupera el casi-critico (> 0.6, NO colapsa al fallback)",
      d["Nn"] > 1800 and xs[i0] > 0.6 and xs[i0] > fb0 + 0.3,
      f"Nn={d['Nn']}, ξ_fundamental={xs[i0]:.3f} vs fallback {fb0:.3f}")
check("T3b el tope de uso habilita el sparse a escala (SPARSE_NN_MAX > tope nodal)",
      CAP > NODAL_CAP, f"SPARSE_NN_MAX={CAP} > max_dense_nodal={NODAL_CAP}")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
