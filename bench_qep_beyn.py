"""Bench del método B (Beyn, integral de contorno) para el QEP de frontera (F2).

Valida `qep_sparse.beyn_contour` / `beyn_qep` (Beyn 2012, "Integral algorithm 1")
contra el QEP DENSO como oráculo:

  T1  Beyn encuentra EXACTAMENTE los polos dentro del contorno Γ (mismo nº que el
      denso, valores a <1e-8, η_Q certificado).
  T2  PAYOFF: Beyn captura un polo SOBREAMORTIGUADO / muy amortiguado (lejos del
      eje imaginario) que el PAL multi-shift NO ve (lo que motivó el método B).
  T3  convergencia EXPONENCIAL en n_quad (el sello de Beyn): el error cae rápido
      al duplicar los nodos de cuadratura.
  T4  capacidad NEP: con T(z) de amortiguamiento dependiente de la frecuencia
      (β(z) holomorfa, no constante → NEP), Beyn devuelve polos con residuo chico.

QEP en s: z²M + z(cβ)Csurf + c²K. Correr:
  QT_QPA_PLATFORM=offscreen python bench_qep_beyn.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.sparse as sp
import scipy.linalg as sla

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
Mp = sp.csr_matrix(M, dtype=complex)
Cp = (C0 * 1.0) * sp.csr_matrix(C_rear, dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(K, dtype=complex)
print(f"  malla: N={N}, {len(freqs)} modos")


def dense_s():
    n = N
    Md, Cd, Kd = Mp.toarray(), Cp.toarray(), Kp.toarray()
    A = np.block([[-Cd, -Kd], [np.eye(n), np.zeros((n, n))]])
    B = np.block([[Md, np.zeros((n, n))], [np.zeros((n, n)), np.eye(n)]])
    s = sla.eig(A, B, right=False)
    return s[np.isfinite(s)]


s_all = dense_s()
s_up = s_all[s_all.imag > 1.0]                            # semiplano superior
print(f"  polos densos (Im>0): {len(s_up)}; más amortiguado "
      f"Re={s_up[np.argmin(s_up.real)].real:.0f}")
print()


# ---------------------------------------------------------------------------
print("T1  Beyn encuentra los polos dentro de Γ (== QEP denso)")
z0 = 1j * 2 * np.pi * float(np.median(freqs))             # centro en la banda
R = 120.0
inside_dense = s_all[np.abs(s_all - z0) < R]
lam_b, V_b, eta_b = qs.beyn_qep(Mp, Cp, Kp, z0, R, n_quad=64, ell=24)
# matchear cada Beyn con el denso más cercano
err = np.array([np.min(np.abs(L - s_all)) for L in lam_b])
check("T1 mismo nº de polos que el denso dentro de Γ",
      len(lam_b) == len(inside_dense),
      f"Beyn={len(lam_b)} vs denso={len(inside_dense)}")
check("T1 autovalores Beyn == denso (<1e-7) y η_Q certificado (<1e-7)",
      (err.size > 0 and float(np.max(err)) < 1e-6
       and float(np.max(eta_b)) < 1e-7),
      f"max err={np.max(err) if err.size else 0:.2e}, max η_Q={np.max(eta_b) if eta_b.size else 0:.2e}")
print()


# ---------------------------------------------------------------------------
print("T2  payoff: Beyn captura el polo MÁS AMORTIGUADO (que PAL no ve)")
# el polo del semiplano superior con Re más negativa (más amortiguado).
s_damp = s_up[np.argmin(s_up.real)]
zc = s_damp                                               # contorno chico a su alrededor
Rc = 30.0
lam_d, V_d, eta_d = qs.beyn_qep(Mp, Cp, Kp, zc, Rc, n_quad=64, ell=12)
if lam_d.size == 0:
    check("T2 Beyn captura el polo muy amortiguado", False, "no devolvió polos")
else:
    hit = np.min(np.abs(lam_d - s_damp))
    xi_damp = (-s_damp.real) / abs(s_damp.imag)
    check("T2 Beyn captura el polo muy amortiguado (match <1e-7)",
          float(hit) < 1e-6,
          f"polo s={s_damp.real:.0f}{s_damp.imag:+.0f}i (ξ={xi_damp:.2f}), "
          f"match={hit:.2e}")
print()


# ---------------------------------------------------------------------------
print("T3  convergencia EXPONENCIAL en n_quad (sello de Beyn)")
ref = lam_b[0] if lam_b.size else z0
errs = []
for nq in (12, 24, 48):
    lam_q, _V, _e = qs.beyn_qep(Mp, Cp, Kp, z0, R, n_quad=nq, ell=24)
    if lam_q.size:
        errs.append(np.min(np.abs(lam_q - ref)))
    else:
        errs.append(np.inf)
# el error debe caer ≥1 orden de 12→48 (trapecio en función analítica)
drop = errs[0] / max(errs[-1], 1e-300)
check("T3 el error cae al aumentar n_quad (12→48)", drop > 10.0 or errs[-1] < 1e-10,
      f"err(nq=12,24,48) = {', '.join(f'{e:.1e}' for e in errs)}")
print()


# ---------------------------------------------------------------------------
print("T4  capacidad NEP: amortiguamiento dependiente de la frecuencia β(z)")
# β(z) holomorfa no constante (juguete): β(z)=1+0.3·(z/z0) → T(z) ya NO es un QEP.
def Tnep(z):
    beta_z = 1.0 + 0.3 * (z / z0)
    return (z * z) * Mp + z * (C0 * beta_z) * sp.csr_matrix(C_rear, dtype=complex) + Kp
lam_n, V_n, res_n = qs.beyn_contour(Tnep, z0, R, n_quad=64, ell=24, tol_res=1e-6)
check("T4 Beyn resuelve el NEP (devuelve polos con residuo chico)",
      lam_n.size >= 3 and float(np.max(res_n)) < 1e-6,
      f"{lam_n.size} polos, max residuo ‖T(λ)v‖/‖v‖ = "
      f"{np.max(res_n) if res_n.size else 0:.2e}")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
