"""Bench de la perturbacion COMPLEJA (Capa 0, Etapa 1c).

Valida `face_materials.perturbation_xi_shift_per_mode` (beta compleja ->
amortiguamiento xi por Re(beta) Y corrimiento de frecuencia por Im(beta))
contra el problema de autovalores complejos EXACTO (QEP con matriz C de
impedancia, sla.eig de tamano 2N).

Oraculos:
  T1  puente: beta_provider=None reduce EXACTO a perturbation_xi_per_mode
      (xi identico, corrimiento ~ 0).
  T2  beta compleja uniforme sintetica: xi (amortiguamiento) Y f_new
      (corrimiento) coinciden con el QEP exacto < few%.
  T3  puente con impedance.py (poroso + camara): con conj(beta) [convencion
      e^{+iwt} del solver] la perturbacion coincide con el QEP, y la reactancia
      produce un corrimiento observable.

Correr:  QT_QPA_PLATFORM=offscreen python bench_perturbation_complex.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.linalg as sla

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import impedance as imp
from sources import C0
from bench_modal_vs_impedance import extract_boundary_faces, assemble_surface_M

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class _UniformMat:
    def __init__(self, a):
        self._a = float(a)
        self.name = f"a={a}"

    def alpha(self, f):
        return self._a


print(__doc__.splitlines()[0])
print()

# --- Setup comun: shoebox 5x4x3 ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e2, _n2 = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat",
                             subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
Nn = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
Cd = assemble_surface_M(nodes, extract_boundary_faces(tets, Nn)).toarray()
Kd, Md = K.toarray(), M.toarray()
freqs, phis = solve_modes(K, M, n_modes=8)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)
print(f"  malla: {Nn} nodos, {len(freqs)} modos, {len(gr)} grupos de cara")
print(f"  f (rigido): {np.round(freqs, 2)}")
print()


def qep_solve(beta):
    """QEP (c^2 K + i c beta C w - M w^2) = 0 con beta uniforme. Devuelve
    (w, P): autovalores complejos w (rad/s, rama Re(w)>1) y sus autovectores de
    PRESION P (columnas, Nn). El companion [[A0,A1],[0,I]]v=w[[0,-A2],[I,0]]v da
    v=[p; w p] -> la presion es la mitad superior."""
    A0, A1, A2 = (C0 ** 2) * Kd, 1j * C0 * beta * Cd, -Md
    Z, I = np.zeros((Nn, Nn)), np.eye(Nn)
    w, V = sla.eig(np.block([[A0, A1], [Z, I]]),
                   np.block([[Z, -A2], [I, Z]]), right=True)
    m = np.isfinite(w) & (np.real(w) > 1.0)
    return w[m], V[:Nn][:, m]


def match_overlap(w, P, phi_n):
    """Autovalor del QEP cuyo autovector de presion MAS se solapa con phi_n
    (producto interno con M). Robusto ante corrimientos y casi-degeneracion, a
    diferencia de matchear por frecuencia."""
    Mp = Md @ P                                        # (Nn, k)
    num = np.abs(phi_n.conj() @ Mp)                    # |phi^H M p_k|
    den = np.sqrt(np.abs(np.einsum('ik,ik->k', P.conj(), Mp)))  # sqrt(p^H M p)
    k = int(np.argmax(num / np.maximum(den, 1e-30)))
    return w[k]


# ---------------------------------------------------------------------------
print("T1  puente: beta_provider=None reduce EXACTO a la perturbacion real")
mat = _UniformMat(0.30)
g2m = {g.signature: mat for g in gr}
xi_real = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m, Vr,
                                      subdiv=3)
xi_c, f_new = fm.perturbation_xi_shift_per_mode(freqs, phis, loc, vr, tr, gr,
                                                g2m, Vr, subdiv=3)
check("T1a xi complejo (beta real) == xi real, bit a bit",
      np.allclose(xi_c, xi_real, rtol=1e-12, atol=1e-15),
      f"max dif {np.max(np.abs(xi_c - xi_real)):.2e}")
check("T1b corrimiento ~ 0 con beta real",
      np.allclose(f_new, freqs, atol=1e-9),
      f"max |f_new-f| {np.max(np.abs(f_new - freqs)):.2e} Hz")


# ---------------------------------------------------------------------------
print("\nT2  beta compleja uniforme sintetica vs QEP exacto (xi Y corrimiento)")
# beta en el regimen de primer orden (|beta| ~ el maximo que valido el bench
# real, alpha_norm<=0.3 -> beta<=0.089). Matching por autovector.
for beta in (0.03 + 0.02j, 0.05 - 0.03j):
    prov = lambda groups, fn, b=beta: np.full(len(groups), b, dtype=complex)
    xi_p, f_p = fm.perturbation_xi_shift_per_mode(
        freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
    d_p = xi_p * 2 * np.pi * np.asarray(freqs)          # delta predicho
    w_ex, P_ex = qep_solve(beta)
    e_d, e_f = [], []
    for i in range(len(freqs)):
        wj = match_overlap(w_ex, P_ex, phis[:, i])
        d_ex = float(np.imag(wj))                       # amortiguamiento exacto
        f_ex = float(np.real(wj) / (2 * np.pi))         # frecuencia corrida exacta
        e_d.append(abs(d_p[i] / d_ex - 1))
        Df_ex = f_ex - freqs[i]
        Df_p = f_p[i] - freqs[i]
        e_f.append(abs(Df_p - Df_ex) / (abs(Df_ex) + 0.05))
    e_d, e_f = np.array(e_d), np.array(e_f)
    check(f"T2 beta={beta}: amortiguamiento < 8%",
          e_d.mean() < 0.08, f"media {100*e_d.mean():.2f}% max {100*e_d.max():.2f}%")
    check(f"T2 beta={beta}: corrimiento de f < 12%",
          e_f.mean() < 0.12, f"media {100*e_f.mean():.2f}% max {100*e_f.max():.2f}%")


# ---------------------------------------------------------------------------
print("\nT3  puente con impedance.py (poroso 50mm + camara 100mm) vs QEP")
s = imp.porous(sigma=15000.0, thickness=0.05, air_gap=0.10, model="miki")
# Convencion: solver e^{+iwt}, impedance.py e^{-iwt} -> conj(beta).
prov_imp = lambda groups, fn: np.full(len(groups), np.conj(s.beta(fn)[0]),
                                      dtype=complex)
xi_i, f_i = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov_imp)

# Validar por-modo contra un QEP con beta constante = conj(beta_imp(f_n)).
n_ok = 0
shift_seen = False
for i in range(min(4, len(freqs))):                    # 4 modos (QEP por modo)
    beta_n = np.conj(complex(s.beta(freqs[i])[0]))
    w_ex, P_ex = qep_solve(beta_n)
    wj = match_overlap(w_ex, P_ex, phis[:, i])
    d_ex = float(np.imag(wj))
    f_ex = float(np.real(wj) / (2 * np.pi))
    d_p = xi_i[i] * 2 * np.pi * freqs[i]
    Df_ex, Df_p = f_ex - freqs[i], f_i[i] - freqs[i]
    ok_d = abs(d_p / d_ex - 1) < 0.10
    ok_f = abs(Df_p - Df_ex) / (abs(Df_ex) + 0.05) < 0.15
    if abs(Df_ex) > 0.05:
        shift_seen = True
    check(f"T3 modo {i} f={freqs[i]:.1f}Hz: xi y corrimiento vs QEP",
          ok_d and ok_f,
          f"delta {d_p:.3f}/{d_ex:.3f}, Df {Df_p:+.3f}/{Df_ex:+.3f} Hz "
          f"|beta|={abs(beta_n):.3f}")
    n_ok += 1
check("T3b la reactancia produce corrimiento observable (Im(beta)!=0)",
      shift_seen and n_ok > 0, "corrimiento no despreciable en >=1 modo")


# ---------------------------------------------------------------------------
print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
raise SystemExit(1 if _FAIL else 0)
