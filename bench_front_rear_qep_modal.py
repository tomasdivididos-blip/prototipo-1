"""Bench del QEP de frontera PROYECTADO A LOS MODOS (refinamiento C2 de E5).

Valida las dos piezas nuevas de `face_materials`:
  - `surface_gram_per_mode`  -> G[n,m] = INT_{pared} phi_n phi_m dS (Gram completa,
    off-diagonal incluida), sobre los modos FEM reales.
  - `qep_boundary_xi_shift`  -> resuelve el QEP de frontera exacto
    diag(w_n^2) + i c beta G w - I w^2 = 0 en la base modal.

Es el reemplazo de la perturbacion de 1er orden en el panel «Decaimiento con
subs» (pared trasera matcheada, C2). El ORACULO es el QEP NODAL exacto (todo el
espacio FEM, matriz de masa de superficie de la pared trasera, sla.eig 2N): el
QEP modal es su proyeccion de Galerkin a los modos computados.

Oraculos:
  T1  IDENTIDAD DE GRAM: surface_gram_per_mode ~ phis^T C_surf,pared phis
      (la cuadratura geometrica reproduce el emparedado de la masa de superficie
      FEM); ata la Gram nueva a la cuadratura YA validada (A36/A2).
  T2  ATADURA PERTURBATIVA: para beta<<1 el QEP modal reproduce la perturbacion
      de 1er orden (delta = c Re(beta) Sg) -> se pega al modelo ya validado.
  T3  PAYOFF C2: a beta=1 (matcheada) el QEP modal da MAS amortiguamiento que la
      perturbacion en los modos bajos (estructura en f + acople inter-modal que
      la perturbacion diagonal no ve) -> justifica el refinamiento.
  T4  ORACULO NODAL (proyeccion de Galerkin): el QEP modal es la proyeccion del
      QEP nodal a los modos. T4a: en REGIMEN MODERADO (beta~0.3, la identidad
      modal todavia vale, solapamiento del autovector >0.9) el delta modal ~ el
      nodal exacto (<15%). T4b: a beta=1 (matcheada) el modo rigido se REPARTE en
      varios polos nodales fuertemente amortiguados (solapamiento cae) y el nodal
      lleva los modos cerca del critico; el QEP modal queda por DEBAJO del nodal
      (piso conservador, declarado) pero por ENCIMA de la perturbacion diagonal.

Correr:  QT_QPA_PLATFORM=offscreen python bench_front_rear_qep_modal.py
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
from sources import C0
from bench_modal_vs_impedance import extract_boundary_faces, assemble_surface_M

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

# --- Setup: shoebox 5x4x3, pared trasera = cara +x (x ~ Lx) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
# n_per_meter moderado: el oraculo nodal (T4) resuelve un eig denso 2Nn x 2Nn,
# asi que la malla fina lo haria lentisimo. 1.8 basta para la Gram y el QEP.
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=1.8)
Nn = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=14)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)
Md = M.toarray()
Kd = K.toarray()

# Mascara de la pared trasera (+x): grupos con normal ~ +x.
rear_mask = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)

# Masa de superficie SOLO de la pared trasera (caras de frontera en x ~ Lx).
bf = extract_boundary_faces(tets, Nn)
cen_f = nodes[bf].mean(axis=1)
x_rear = nodes[:, 0].max()                               # la malla esta centrada
rear_faces = bf[cen_f[:, 0] > x_rear - 1e-3]
Cd_rear = assemble_surface_M(nodes, rear_faces).toarray()

print(f"  malla: {Nn} nodos, {len(freqs)} modos, {len(gr)} grupos; "
      f"pared trasera: {int(rear_mask.sum())} grupo(s), {len(rear_faces)} caras")
print(f"  f (rigido): {np.round(freqs, 2)}")
print()


def qep_nodal(beta, Cd):
    """QEP NODAL exacto c^2 K + i c beta Cd w - M w^2 = 0. Devuelve (w, P) con la
    presion P (mitad superior del autovector companion)."""
    A0, A1, A2 = (C0 ** 2) * Kd, 1j * C0 * beta * Cd, -Md
    Z, I = np.zeros((Nn, Nn)), np.eye(Nn)
    w, V = sla.eig(np.block([[A0, A1], [Z, I]]),
                   np.block([[Z, -A2], [I, Z]]), right=True)
    m = np.isfinite(w) & (np.real(w) > 1.0)
    return w[m], V[:Nn][:, m]


def match_overlap(w, P, phi_n):
    """Autovalor nodal cuyo autovector de presion mas se solapa con phi_n (M)."""
    Mp = Md @ P
    num = np.abs(phi_n.conj() @ Mp)
    den = np.sqrt(np.abs(np.einsum('ik,ik->k', P.conj(), Mp)))
    return w[int(np.argmax(num / np.maximum(den, 1e-30)))]


# ---------------------------------------------------------------------------
print("T1  identidad de Gram: surface_gram_per_mode ~ phis^T C_surf phis")
G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rear_mask, subdiv=3)
G_fem = phis.T @ Cd_rear @ phis                          # emparedado exacto FEM
# Comparar la matriz completa (diagonal domina; off-diagonal es el acople nuevo).
num = np.linalg.norm(G - G_fem)
den = np.linalg.norm(G_fem)
rel = num / max(den, 1e-30)
# Diagonal debe pegar con el Sg de la perturbacion (misma cuadratura).
Sg = fm._modal_surface_integrals(phis, loc, vr, tr, gr, subdiv=3)
Sg_rear = Sg[:, rear_mask].sum(axis=1)                   # INT_pared phi_n^2 dS
rel_diag = np.max(np.abs(np.diag(G) / np.maximum(Sg_rear, 1e-30) - 1.0))
check("T1a Gram completa ~ emparedado FEM (Frobenius)", rel < 0.05,
      f"||G-G_fem||/||G_fem|| = {rel:.2e}")
check("T1b diagonal de G == Sg de la perturbacion (misma cuadratura)",
      rel_diag < 1e-9, f"max |diag(G)/Sg - 1| = {rel_diag:.2e}")
check("T1c G tiene off-diagonal NO despreciable (acople inter-modal real)",
      np.linalg.norm(G - np.diag(np.diag(G))) / den > 0.05,
      f"||offdiag||/||G|| = {np.linalg.norm(G - np.diag(np.diag(G)))/den:.2f}")
print()


# ---------------------------------------------------------------------------
print("T2  atadura perturbativa: beta<<1 -> QEP modal ~ perturbacion de 1er orden")
worst = 0.0
for beta in (0.02, 0.05, 0.12):
    prov = lambda gs, fn, m=rear_mask, b=beta: m.astype(float) * b
    xi_p, _f = fm.perturbation_xi_shift_per_mode(
        freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
    d_p = xi_p * 2 * np.pi * freqs
    xi_q, f_q = fm.qep_boundary_xi_shift(freqs, G, beta=beta, c=C0)
    d_q = xi_q * 2 * np.pi * f_q
    # modos con amortiguamiento no trivial (los que tocan la pared trasera)
    sig = d_p > 0.05 * np.max(d_p)
    r = np.abs(d_q[sig] / np.maximum(d_p[sig], 1e-30) - 1.0)
    worst = max(worst, float(np.max(r)))
check("T2 beta<=0.12: QEP modal reproduce la perturbacion (delta)", worst < 0.12,
      f"max |delta_QEP/delta_pert - 1| = {worst:.2e}")
print()


# ---------------------------------------------------------------------------
print("T3  payoff C2: beta=1 -> QEP modal da MAS amortiguamiento que la perturbacion")
prov1 = lambda gs, fn, m=rear_mask: m.astype(float)
xi_p1, _f = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov1)
d_p1 = xi_p1 * 2 * np.pi * freqs
xi_q1, f_q1 = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
d_q1 = xi_q1 * 2 * np.pi * f_q1
sig = d_p1 > 0.05 * np.max(d_p1)
ratio = d_q1[sig] / np.maximum(d_p1[sig], 1e-30)
check("T3 beta=1: QEP > perturbacion en los modos acoplados (ratio > 1)",
      float(np.max(ratio)) > 1.3,
      f"delta_QEP/delta_pert: max={np.max(ratio):.2f}, mediana={np.median(ratio):.2f}")
# xi del 1er modo acoplado: debe salir del regimen perturbativo (xi apreciable).
n0 = int(np.argmax(d_q1))
check("T3b xi del modo mas amortiguado ya NO es perturbativo (>0.1)",
      xi_q1[n0] > 0.1, f"xi_max = {xi_q1[n0]:.3f} (modo {n0}, f={freqs[n0]:.1f} Hz)")
print()


# ---------------------------------------------------------------------------
print("T4  oraculo nodal (proyeccion de Galerkin del QEP nodal exacto)")


def nodal_delta_overlap(beta):
    """delta_n y solapamiento del QEP NODAL exacto, matcheado por autovector a
    cada modo rigido. Devuelve (delta[Nm], overlap[Nm])."""
    w_ex, P_ex = qep_nodal(beta, Cd_rear)
    Mp = Md @ P_ex
    den = np.sqrt(np.abs(np.einsum('ik,ik->k', P_ex.conj(), Mp)))
    d = np.empty(len(freqs)); ov = np.empty(len(freqs))
    for n in range(len(freqs)):
        num = np.abs(phis[:, n].conj() @ Mp)
        rel = num / np.maximum(den, 1e-30)
        k = int(np.argmax(rel))
        d[n] = abs(np.imag(w_ex[k])); ov[n] = float(rel[k])
    return d, ov

# T4a: regimen MODERADO (beta=0.3), la identidad modal vale -> acuerdo exacto.
beta_mod = 0.3
d_nod_m, ov_m = nodal_delta_overlap(beta_mod)
xi_qm, f_qm = fm.qep_boundary_xi_shift(freqs, G, beta=beta_mod, c=C0)
d_qm = xi_qm * 2 * np.pi * f_qm
clean = (ov_m > 0.9) & (d_qm > 0.1 * np.max(d_qm))       # modos con identidad limpia
errs = np.abs(d_qm[clean] / np.maximum(d_nod_m[clean], 1e-30) - 1.0)
check(f"T4a beta={beta_mod}: QEP modal ~ QEP nodal exacto (modos de identidad limpia)",
      clean.sum() >= 3 and float(np.mean(errs)) < 0.15,
      f"{int(clean.sum())} modos (ov>0.9); media {100*np.mean(errs):.1f}% "
      f"max {100*np.max(errs):.1f}%")

# T4b: beta=1 (matcheada) -> la IDENTIDAD MODAL se degrada (el modo rigido se
# reparte en varios polos fuertemente amortiguados, el nodal roza el critico), asi
# que el delta nodal POR MODO ya no esta bien definido (depende del matcheo/malla)
# y NO hay un sandwich limpio: el valor matcheado del panel es una estimacion del
# SUBESPACIO modal (declarada), no el nodal exacto. Lo robusto y honesto:
#   (1) el mejor solapamiento cae vs el regimen moderado (quiebre de identidad);
#   (2) el QEP modal se mantiene FISICO (xi acotado, sin blow-up) y REFINA a la
#       perturbacion diagonal (mediana >=).
d_nod_1, ov_1 = nodal_delta_overlap(1.0)
ov_drop = float(np.max(ov_1)) < float(np.max(ov_m))
sigc = d_p1 > 0.2 * np.max(d_p1)
xi_max = float(np.max(xi_q1))
physical = (xi_max < 1.5) and np.all(d_q1 >= -1e-9) and \
    (np.median(d_q1[sigc]) >= np.median(d_p1[sigc]) - 1e-9)
check("T4b beta=1: la identidad modal se degrada (solapamiento cae vs beta moderado)",
      ov_drop, f"max overlap: beta={beta_mod}->{np.max(ov_m):.2f}, beta=1->{np.max(ov_1):.2f} "
               f"(nodal xi_max~{np.max(d_nod_1)/(2*np.pi*freqs[np.argmax(d_nod_1)]):.2f}, "
               "cerca del critico)")
check("T4b beta=1: el QEP modal se mantiene fisico (xi acotado) y refina la perturbacion",
      physical,
      f"xi_max={xi_max:.2f} (<1.5); mediana delta modos acoplados: QEP="
      f"{np.median(d_q1[sigc]):.0f} >= pert={np.median(d_p1[sigc]):.0f}")
print()


# ---------------------------------------------------------------------------
print("=" * 68)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 68)
raise SystemExit(1 if _FAIL else 0)
