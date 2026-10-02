"""
bench_front_rear_qep.py
=======================

E3 de `plan_frente_opuesto_admitancia.md` (opcion (b): terminacion de impedancia
MATCHEADA como absorbedor activo real -> los polos modales se MUEVEN, C2). Como
E1c mostro que la admitancia del borde trasero es de orden ~1 (NO perturbativa),
el amortiguamiento modal se calcula por el QEP EXACTO (autovalores complejos con
la BC de admitancia), no por la perturbacion de 1er orden.

QEP (mismo que el oraculo del cono, bench_cone_damping):
    c^2 K  +  i c beta C_bc  w  -  M w^2  = 0
en la base modal ortonormal: M = I, c^2 K = diag(w_n^2), C_bc = Gram de superficie
de los modos sobre la pared trasera, C_bc[n,m] = integral_{pared} phi_n phi_m dS.
Para los modos AXIALES del eje front<->rear (0,j,0) y una pared UNIFORME, C_bc es
RANGO 1: C_bc = (2/Ly) s s^T con s_j = (-1)^j (el valor de cada modo en la pared).
beta = admitancia especifica NORMALIZADA (beta=1 = matcheada = Y0 = absorcion total).

De los autovalores complejos w_n = Re + i Im:  delta_n = Im(w_n) [Np/s],
xi_n = delta_n / Re(w_n),  RT60_n = 6.908 / delta_n.

Checks:
  T1  REGIMEN PERTURBATIVO: para beta<<1 el QEP reproduce la perturbacion de 1er
      orden delta_pert = c Re(beta)/Ly (atadura al modelo YA validado).
  T2  REGIMEN FUERTE (beta=1, matcheada): la perturbacion SUBESTIMA fuerte el
      amortiguamiento -> hay que usar el QEP (justifica (b) por QEP, no perturbacion).
  T3  PAYOFF C2: con la pared trasera matcheada el RT60 de los modos axiales
      COLAPSA vs la pared rigida (los polos se mueven: decaimiento genuino).
  T4  monotonia: delta del 1er axial crece con Re(beta) (mas absorcion -> mas rapido).
"""

from __future__ import annotations

import numpy as np
import scipy.linalg as sla

from sources import C0


def axial_omega(Ly, J, c=C0):
    """w_j de los modos axiales (0,j,0), j=1..J (se excluye el modo DC j=0)."""
    j = np.arange(1, J + 1)
    return c * j * np.pi / Ly, j


def Cbc_axial(Ly, J):
    """C_bc[j,l] = integral_{pared y=Ly} phi_j phi_l dS para los axiales (0,j,0).
    Rango 1: (2/Ly) s s^T con s_j=(-1)^j. Diagonal = 2/Ly (da delta_pert=c Re(b)/Ly)."""
    j = np.arange(1, J + 1)
    s = ((-1.0) ** j) * np.sqrt(2.0 / Ly)
    return np.outer(s, s)


def qep_poles(omega_n, Cbc, beta, c=C0):
    """Resuelve c^2 K + i c beta C_bc w - M w^2 = 0 (M=I, c^2 K=diag(w_n^2)).
    Devuelve los autovalores w con Re(w)>0 ordenados por Re(w)."""
    N = len(omega_n)
    A0 = np.diag(omega_n ** 2).astype(complex)
    A1 = 1j * c * beta * Cbc
    A2 = -np.eye(N, dtype=complex)
    Z, I = np.zeros((N, N), complex), np.eye(N, dtype=complex)
    w = sla.eig(np.block([[A0, A1], [Z, I]]),
                np.block([[Z, -A2], [I, Z]]), right=False)
    w = w[np.isfinite(w)]
    w = w[np.real(w) > 1.0]
    return w[np.argsort(np.real(w))]


def _match_delta(omega_n, w):
    """Para cada w_n, el delta=Im del autovalor con Re mas cercano."""
    out = np.full(len(omega_n), np.nan)
    for i, wn in enumerate(omega_n):
        k = int(np.argmin(np.abs(np.real(w) - wn)))
        out[i] = abs(np.imag(w[k]))
    return out


def run():
    results = []
    Ly = 5.0
    J = 20
    omega_n, _j = axial_omega(Ly, J)
    Cbc = Cbc_axial(Ly, J)

    def delta_pert(beta):
        return C0 * np.real(beta) / Ly       # perturbacion 1er orden (constante en j)

    # --- T1: regimen perturbativo (QEP ~ perturbacion) ---
    worst = 0.0
    for beta in (0.02, 0.05, 0.15):
        w = qep_poles(omega_n, Cbc, beta)
        d_qep = _match_delta(omega_n, w)
        dp = delta_pert(beta)
        # comparar en los primeros modos (los mejor resueltos por la base axial)
        rel = np.abs(d_qep[:10] / dp - 1.0)
        worst = max(worst, float(np.nanmax(rel)))
    t1 = worst < 0.12
    results.append(("T1 beta<<1: QEP reproduce la perturbacion c*Re(b)/Ly",
                    t1, f"max |delta_QEP/delta_pert - 1| (beta<=0.15) = {worst:.2e}"))

    # --- T2: regimen fuerte (beta=1): el QEP tiene estructura en FRECUENCIA que
    # la perturbacion (constante c Re(b)/Ly) NO captura. En los modos bajos
    # (sin sesgo de truncamiento) delta_QEP/delta_pert llega a ~2x, y xi se hace
    # grande (modo 1 xi~0.35, fuertemente amortiguado) -> la perturbacion de 1er
    # orden describe un promedio, el QEP da el amortiguamiento modal real.
    w1 = qep_poles(omega_n, Cbc, 1.0)
    d_qep1 = _match_delta(omega_n, w1)
    dp1 = delta_pert(1.0)
    ratio_lo = d_qep1[:6] / dp1
    xi_1 = float(d_qep1[0] / omega_n[0])
    t2 = float(np.max(ratio_lo)) > 1.5 and xi_1 > 0.2
    results.append(("T2 beta=1: QEP da estructura en f que la perturbacion no ve",
                    t2, f"delta_QEP/delta_pert (modos 1-6) max={np.max(ratio_lo):.2f}, "
                        f"min={np.min(ratio_lo):.2f} (pert.=const); xi_1={xi_1:.2f} "
                        f"(fuertemente amortiguado)"))

    # --- T3: PAYOFF C2: RT60 de los axiales colapsa (rigido -> matcheado) ---
    # rigido ~ beta pequeno (pared casi rigida); matcheado beta=1.
    d_rig = _match_delta(omega_n, qep_poles(omega_n, Cbc, 1e-3))
    rt_rig = 6.908 / d_rig
    rt_mat = 6.908 / d_qep1
    rt_rig1, rt_mat1 = float(rt_rig[0]), float(rt_mat[0])
    collapse = rt_rig1 / rt_mat1
    t3 = collapse > 20.0 and rt_mat1 < 0.3
    results.append(("T3 payoff C2: RT60 del 1er axial colapsa (rigido->matcheado)",
                    t3, f"RT60_1 rigido={rt_rig1:.2f}s -> matcheado={rt_mat1:.3f}s "
                        f"(x{collapse:.0f} mas rapido)"))

    # --- T4: monotonia: delta_1 crece con Re(beta) ---
    betas = np.array([0.01, 0.05, 0.15, 0.5, 1.0])
    d1 = np.array([_match_delta(omega_n, qep_poles(omega_n, Cbc, b))[0] for b in betas])
    t4 = bool(np.all(np.diff(d1) > 0))
    results.append(("T4 delta_1 crece monotono con Re(beta)",
                    t4, "delta_1(beta): " + ", ".join(
                        f"{b:.2f}->{d:.1f}" for b, d in zip(betas, d1))))

    return results


if __name__ == "__main__":
    rs = run()
    npass = sum(1 for _, ok, _ in rs if ok)
    for name, ok, detail in rs:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    print(f"\n{npass}/{len(rs)} checks OK")
    raise SystemExit(0 if npass == len(rs) else 1)
