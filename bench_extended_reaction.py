"""Bench de la reaccion EXTENDIDA (Capa 0, Etapa 2b).

Valida:
  T1  estimador de angulo de incidencia por modo (_modal_incidence_angles) vs el
      angulo ANALITICO del shoebox arccos(|k_normal|/|k|) del modo (l,m,n).
  T2  puente: perturbation_xi_shift_extended con una superficie LOCAL (rigido /
      resistivo) coincide con la version por incidencia normal.
  T3  una superficie de reaccion EXTENDIDA (poroso+camara via TMM oblicuo) da un
      xi distinto al de asumir incidencia normal (el angulo por modo importa).

Correr:  QT_QPA_PLATFORM=offscreen python bench_extended_reaction.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import impedance as imp

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


C0 = 343.0
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.5)
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=10)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)
print(f"  malla {nodes.shape[0]} nodos, {len(freqs)} modos, {len(gr)} paredes")

# Eje dominante de cada grupo (0=x,1=y,2=z) desde su normal.
grp_axis = [int(np.argmax(np.abs(g.normal))) for g in gr]

# Tabla analitica de modos (l,m,n) para matchear las frecuencias FEM.
L = np.array([Lx, Ly, Lz])
lmn = [(l, m, n) for l in range(4) for m in range(4) for n in range(4)
       if (l, m, n) != (0, 0, 0)]
f_lmn = np.array([0.5 * C0 * np.sqrt((l/Lx)**2 + (m/Ly)**2 + (n/Lz)**2)
                  for (l, m, n) in lmn])


def analytic_angles(f_fem):
    """(l,m,n) mas cercano en frecuencia + angulo por eje arccos(|k_ax|/|k|)."""
    j = int(np.argmin(np.abs(f_lmn - f_fem)))
    if abs(f_lmn[j] - f_fem) / f_fem > 0.03:
        return None, None
    k = np.pi * np.array(lmn[j]) / L
    kmag = np.linalg.norm(k)
    th = np.arccos(np.clip(np.abs(k) / kmag, 0, 1))    # por eje (x,y,z)
    return lmn[j], th


# ---------------------------------------------------------------------------
print("\nT1  estimador de angulo vs analitico del shoebox")
ang = fm._modal_incidence_angles(freqs, phis, loc, vr, tr, gr, subdiv=3)
errs = []
for i in range(len(freqs)):
    idx, th_ax = analytic_angles(freqs[i])
    if idx is None:
        continue
    for gi in range(len(gr)):
        th_est = np.degrees(ang[i, gi])
        th_true = np.degrees(th_ax[grp_axis[gi]])
        # el clamp del estimador es 88 deg; el analitico rasante es 90 -> acotar
        if th_true > 88.0:
            th_true = 88.0
        errs.append(abs(th_est - th_true))
errs = np.array(errs)
check("T1 error medio del angulo estimado < 10 deg",
      errs.mean() < 10.0, f"media {errs.mean():.1f} deg, max {errs.max():.1f} deg")
check("T1b error mediano < 6 deg",
      float(np.median(errs)) < 6.0, f"mediana {np.median(errs):.1f} deg")


# ---------------------------------------------------------------------------
print("\nT2  puente: superficie LOCAL == incidencia normal")
# (a) rigido -> xi ~ 0
xr = fm.perturbation_xi_shift_extended(freqs, phis, loc, vr, tr, gr, {}, Vr,
                                       default_surf=imp.rigid(), subdiv=3)
check("T2a rigido: xi ~ 0", xr is not None and np.all(np.abs(xr[0]) < 1e-6),
      f"max xi {np.max(np.abs(xr[0])):.2e}")
# (b) resistivo local: extendida == provider uniforme beta_real
beta_r = 0.08
surf_r = imp.resistive(beta_r)
xe, fe = fm.perturbation_xi_shift_extended(
    freqs, phis, loc, vr, tr, gr, {s.signature: surf_r for s in gr}, Vr, subdiv=3)
prov = lambda groups, fn: np.full(len(groups), beta_r, dtype=complex)
xn, fnn = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
check("T2b resistivo local: extendida == normal (xi)",
      np.allclose(xe, xn, rtol=1e-9, atol=1e-12),
      f"max dif {np.max(np.abs(xe - xn)):.2e}")
check("T2c resistivo local: corrimiento ~ 0 (beta real)",
      np.allclose(fe, freqs, atol=1e-9), f"max {np.max(np.abs(fe-freqs)):.2e}")


# ---------------------------------------------------------------------------
print("\nT3  reaccion extendida: el angulo por modo cambia el resultado")
surf_e = imp.porous(15000.0, 0.05, "miki", air_gap=0.10)   # extendida
xe2, fe2 = fm.perturbation_xi_shift_extended(
    freqs, phis, loc, vr, tr, gr, {s.signature: surf_e for s in gr}, Vr, subdiv=3)
# comparacion: la MISMA superficie pero evaluada a incidencia normal (theta=0)
prov0 = lambda groups, fn: np.array(
    [np.conj(imp.Z0 / complex(surf_e.Z(fn, 0.0)[0]))] * len(groups), dtype=complex)
xn0, fn0 = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov0)
dxi = np.abs(xe2 - xn0) / np.maximum(np.abs(xn0), 1e-12)
check("T3a extendida != normal en xi (el angulo importa)",
      float(dxi.mean()) > 0.02, f"dif media {100*dxi.mean():.1f}%")
check("T3b xi extendido fisico (>0 y finito)",
      np.all(np.isfinite(xe2)) and np.all(xe2 >= -1e-9),
      f"min {xe2.min():.4f} max {xe2.max():.4f}")


print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
raise SystemExit(1 if _FAIL else 0)
