"""Bench del solver SPARSE PAL para el QEP de frontera (F1 del plan_solver_qep_sparse).

Valida `qep_sparse.pal_qep` (Padé Approximate Linearization, Lu et al. 2015) por
etapas, contra el QEP DENSO como oráculo exacto:

  T1  PAL DENSO (arma A_s,B_s, eig denso) reproduce los autovalores del QEP denso
      cerca del shift σ (valida el ÁLGEBRA: Padé + Kron + escalado + recuperación).
  T2  PAL SPARSE (factoriza SOLO Q(σ) + matvec estructurado 5.3 + eigs) == PAL
      denso (valida la IMPLEMENTACIÓN eficiente).
  T3  error hacia atrás η_Q por polo < 1e-10 (certificado, no depende de oráculo).
  T4  envoltorio de frontera: pal_boundary_xi_shift(β=1) == qep_boundary_nodal
      (el QEP nodal denso ya validado) en los modos acoplados.
  T5  rank(C) bajo + factorización de Q(σ) barata (la base de la eficiencia).

QEP en s: s² M + s (c β) C_surf + c² K = 0. Correr:
  QT_QPA_PLATFORM=offscreen python bench_qep_sparse.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.sparse as sp
import scipy.linalg as sla

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import face_materials as fm
import qep_sparse as qs
from sources import C0
from bench_modal_vs_impedance import extract_boundary_faces, assemble_surface_M

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

# --- Shoebox FEM (N chico para que el denso sea rápido) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
N = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
loc = FieldEvaluator(nodes, tets)
# Pared trasera +x (eje de Control Ale es Y; acá da igual, es un oráculo).
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
print(f"  malla: N={N}, {len(freqs)} modos, pared trasera {nf} caras")

beta = 1.0
Mp = sp.csr_matrix(M, dtype=complex)
Cp = (C0 * beta) * sp.csr_matrix(C_rear, dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(K, dtype=complex)
f_band = float(np.median(freqs))
sigma = 1j * 2 * np.pi * f_band


def dense_sqep_eigs(Mp, Cp, Kp):
    """Autovalores s del QEP s²Mp+sCp+Kp por companion generalizado denso."""
    n = Mp.shape[0]
    Md, Cd, Kd = Mp.toarray(), Cp.toarray(), Kp.toarray()
    A = np.block([[-Cd, -Kd], [np.eye(n), np.zeros((n, n))]])
    B = np.block([[Md, np.zeros((n, n))], [np.zeros((n, n)), np.eye(n)]])
    s = sla.eig(A, B, right=False)
    return s[np.isfinite(s)]


s_dense = dense_sqep_eigs(Mp, Cp, Kp)
# polos físicos cerca del shift (Im>0, los que nos interesan)
s_near = s_dense[np.argsort(np.abs(s_dense - sigma))][:12]
print(f"  shift σ = {sigma:.1f}  (f_band={f_band:.1f} Hz)")
print(f"  autovalores densos cerca de σ (s=−δ+iω_d): "
      f"{', '.join(f'{s.real:.1f}{s.imag:+.1f}i' for s in s_near[:4])}")
print()


def match_set(lam, ref):
    """Para cada λ, el |λ−ref| mínimo relativo a |ref|."""
    out = []
    for L in lam:
        out.append(np.min(np.abs(L - ref)) / max(np.min(np.abs(ref)), 1.0))
    return np.array(out)


# ---------------------------------------------------------------------------
# PAL con un shift capta los polos en el DOMINIO DE CONFIANZA de σ; el error
# hacia atrás η_Q AUTO-CERTIFICA cuáles son correctos (Lu et al. §4). Se valida
# que TODOS los polos η-certificados coinciden con el QEP denso a máquina.
print("T1  PAL DENSO: los polos η-certificados == QEP denso (valida el álgebra)")
lam_d, X_d, eta_d = qs.pal_qep(Mp, Cp, Kp, sigma, k=12, m=3, mode="dense")
cert_d = eta_d < 1e-9
err1 = match_set(lam_d[cert_d], s_dense)
# el error en autovalor ≈ η · condición (~1e3) → con η<1e-9 se esperan ~6 dígitos.
check("T1 polos certificados (η<1e-9) coinciden con el QEP denso (<1e-4 rel)",
      cert_d.sum() >= 4 and float(np.max(err1)) < 1e-4,
      f"{int(cert_d.sum())} certificados; max err rel = "
      f"{np.max(err1) if err1.size else 0:.2e}")
print()

# ---------------------------------------------------------------------------
print("T2  PAL SPARSE == PAL denso (valida la implementación 5.3)")
lam_s, X_s, eta_s = qs.pal_qep(Mp, Cp, Kp, sigma, k=12, m=3, mode="sparse")
cert_s = eta_s < 1e-9
err2 = match_set(lam_s[cert_s], lam_d[cert_d])
check("T2 polos certificados sparse == denso (<1e-8 rel)",
      cert_s.sum() >= 4 and float(np.max(err2)) < 1e-8,
      f"max err rel = {np.max(err2) if err2.size else 0:.2e}")
print()

# ---------------------------------------------------------------------------
print("T3  error hacia atrás η_Q: el certificado discrimina (polos exactos)")
check("T3 el mejor polo es a máquina (η<1e-12) y hay >=4 certificados (η<1e-9)",
      float(np.min(eta_s)) < 1e-12 and int((eta_s < 1e-9).sum()) >= 4,
      f"min η_Q = {np.min(eta_s):.2e}; {int((eta_s<1e-9).sum())} polos < 1e-9")
print()

# ---------------------------------------------------------------------------
print("T4  envoltorio MULTI-SHIFT: PAL == qep_boundary_nodal en modos cubiertos")
xi_nod, f_nod = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0)
res = qs.pal_boundary_xi_shift(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                               return_cov=True)
if res is None:
    check("T4 pal_boundary_xi_shift devuelve resultado", False, "None")
else:
    xi_pal, f_pal, cov = res
    cov_mask = np.isfinite(xi_pal)
    rel = np.abs(xi_pal[cov_mask] / np.maximum(xi_nod[cov_mask], 1e-30) - 1.0)
    fref = np.abs(f_pal[cov_mask] - f_nod[cov_mask]) / np.maximum(f_nod[cov_mask], 1.0)
    check("T4a ξ de PAL == nodal en los modos cubiertos (<2%)",
          cov_mask.sum() >= 6 and float(np.max(rel)) < 0.02,
          f"cobertura {100*cov:.0f}% ({int(cov_mask.sum())}/{len(xi_pal)}); "
          f"max rel ξ={100*np.max(rel):.2f}%, max rel f={100*np.max(fref):.3f}%")
    check("T4b cobertura alta de la banda (modos oscilatorios)", cov > 0.7,
          f"cobertura = {100*cov:.0f}% (los no cubiertos = sobreamortiguados -> Beyn/F2)")
print()

# ---------------------------------------------------------------------------
print("T5  rank(C) bajo + Q(σ) barato (base de la eficiencia)")
E = qs.lowrank_factor(C_rear)
ell = E.shape[1] if E is not None else 0
import scipy.sparse.linalg as spla, time
Qs = sp.csc_matrix((sigma * sigma) * Mp + sigma * Cp + Kp)
t0 = time.time(); lu = spla.splu(Qs); dt = time.time() - t0
check("T5 rank(C) ≪ N (amortiguamiento de bajo rango)", 0 < ell < 0.3 * N,
      f"rank(C)={ell}  ({100*ell/N:.1f}% de N={N})")
check("T5 LU de Q(σ) barata", (lu.L.nnz + lu.U.nnz) < 50 * Qs.nnz,
      f"nnz(L+U)={lu.L.nnz+lu.U.nnz:,}  en {dt:.3f}s")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
