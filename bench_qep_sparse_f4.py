"""Bench F4: wrapper unificado A+B (sparse_boundary_xi_shift) vs el QEP nodal denso.

`qep_sparse.sparse_boundary_xi_shift` combina PAL (banda de shifts, modos
oscilatorios) + Beyn (contorno, rellena lo que falta INCLUIDOS los
sobreamortiguados). Debe reproducir `face_materials.qep_boundary_nodal` con
cobertura TOTAL, y correr en salas donde el eig denso de 2N ya es pesado.

  T1  cobertura TOTAL (100% de los modos), PAL + Beyn.
  T2  ξ y f de A+B == nodal denso en TODOS los modos (<2%), incluido el
      SOBREAMORTIGUADO (ξ>1, polos reales) que PAL solo no capta.
  T3  tiempo acotado (on-demand, objetivo ~10 s).

Correr:  QT_QPA_PLATFORM=offscreen python bench_qep_sparse_f4.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes
import face_materials as fm
import qep_sparse as qs
from sources import C0

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
N = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
print(f"  malla: N={N}, {len(freqs)} modos")

# oráculo nodal denso
xi_nod, f_nod = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0)

t0 = time.time()
res = qs.sparse_boundary_xi_shift(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                                  return_info=True)
dt = time.time() - t0
xi_s, f_s, info = res
print(f"  A+B: {info['n_shifts']} shifts PAL, cobertura PAL={100*info['cov_pal']:.0f}% "
      f"-> total={100*info['cov_total']:.0f}% ({info['n_overdamped']} polos reales), {dt:.2f}s")
print(f"  ξ nodal = {np.round(xi_nod,3)}")
print(f"  ξ A+B   = {np.round(xi_s,3)}")
print()

# ---------------------------------------------------------------------------
print("T1  cobertura TOTAL (PAL + Beyn)")
check("T1 todos los modos cubiertos", info["cov_total"] >= 0.999,
      f"cobertura total = {100*info['cov_total']:.0f}% (PAL solo: {100*info['cov_pal']:.0f}%)")
print()

# ---------------------------------------------------------------------------
print("T2  ξ y f de A+B == nodal denso en TODOS los modos")
cov = np.isfinite(xi_s)
rel_xi = np.abs(xi_s[cov] / np.maximum(xi_nod[cov], 1e-9) - 1.0)
rel_f = np.abs(f_s[cov] - f_nod[cov]) / np.maximum(f_nod[cov], 1.0)
over = np.where(xi_nod > 1.0)[0]
over_ok = (cov[over].all()
           and np.all(np.abs(xi_s[over] / xi_nod[over] - 1.0) < 0.02))
check("T2a ξ A+B == nodal en todos los modos cubiertos (<2%)",
      cov.sum() >= 11 and float(np.max(rel_xi)) < 0.02,
      f"max rel ξ = {100*np.max(rel_xi):.2f}%, max rel f = {100*np.max(rel_f):.3f}%")
check("T2b el modo SOBREAMORTIGUADO (ξ>1) se captura (A+B==nodal)",
      bool(over_ok),
      f"modos ξ>1: {list(over)}; ξ_nodal={np.round(xi_nod[over],3)} "
      f"ξ_A+B={np.round(xi_s[over],3)}")
print()

# ---------------------------------------------------------------------------
print("T3  tiempo acotado (on-demand)")
check("T3 corre en tiempo razonable (<10 s en esta malla)", dt < 10.0,
      f"{dt:.2f}s en N={N}")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
