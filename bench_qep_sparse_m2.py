"""Bench M2: el gate de Beyn ya no depende de una cota NO probada.

Hallazgo M2 del auditor (12 Oct 2026): el gate `xi_est > xi_gate=0.15` decidia Beyn
con xi_est = perturbacion de 1er orden, que NO es una cota inferior DEMOSTRADA del ξ
real; un casi-critico con xi_est apenas < 0.15 (y fallback subestimado) se escapaba.

Fix (empiricamente calibrado + redes extra, NO un certificado exacto porque no existe
uno barato — ver T3): (1) xi_gate bajado a 0.08 (< 0.40·xi_crit medido en el audit);
(2) red de SOSPECHA: si el fallback modal da MENOS amortiguamiento que la perturbacion
diagonal (fallback < xi_est, con xi_est no despreciable) ⇒ probable subestimacion por
truncamiento ⇒ se flaggea para Beyn.

Oraculos:
  T1  AUDIT del margen: sobre una familia de shoeboxes, el ratio xi_est/xi_nodal de
      los casi-criticos (xi_nodal>xi_crit) tiene un MINIMO; el xi_gate DEFAULT del
      codigo debe ser < min_ratio·xi_crit (asi ningun casi-critico escapa al gate de
      xi_est). Reporta el margen medido.
  T2  RECUPERACION end-to-end: en el ducto, el sparse (gate+sospecha+Beyn) recupera
      TODOS los modos con xi_nodal>0.1 vs el nodal, incluido un modo SUBESTIMADO por
      el fallback (xi_nodal~0.19 con fallback~0.004) que la red de sospecha atrapa.
  T3  por que NO un certificado η: el η del polo de fallback con la forma RIGIDA φ_n
      NO separa (mide cuan autovector es φ_n, no el error del ξ): el casi-critico (el
      PEOR subestimado) NO tiene el η mayor ⇒ η no sirve de gate.

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_qep_sparse_m2.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect
import numpy as np
import scipy.sparse as sp

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


def build(Lx, Ly, Lz, n_modes, npm=2.0):
    vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
    nodes, tets = build_volume_mesh(vr, tr, n_per_meter=npm)
    K, M, _v = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=n_modes)
    gr = fm.group_faces_by_planar_region(vr, tr)
    rm = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)
    Cr, _nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
    loc = FieldEvaluator(nodes, tets)
    xn, _f = fm.qep_boundary_nodal(K, M, Cr, freqs, phis, beta=1.0, c=C0)
    G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rm)
    qm = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
    fx, ff = np.asarray(qm[0], float), np.asarray(qm[1], float)
    diagG = np.array([np.real(phis[:, n] @ (Cr @ phis[:, n])) for n in range(len(freqs))])
    xi_est = (C0 / 2.0) * diagG / np.maximum(2 * np.pi * freqs, 1e-9)
    return dict(K=K, M=M, Cr=Cr, freqs=freqs, phis=phis, xn=xn, fx=fx, ff=ff, xi_est=xi_est)


XI_CRIT = 0.35
XI_GATE = inspect.signature(qs.sparse_boundary_xi_shift).parameters["xi_gate"].default
print(__doc__.splitlines()[0])
print(f"(xi_gate default del codigo = {XI_GATE})\n")


# ---------------------------------------------------------------------------
print("T1  AUDIT del margen xi_est/xi_nodal de los casi-criticos")
rooms = [(7.0, 2.1, 2.3), (6.0, 4.0, 2.8), (8.0, 3.0, 2.5), (4.5, 3.5, 3.0)]
ratios, min_xiest_crit, n_crit = [], np.inf, 0
for (Lx, Ly, Lz) in rooms:
    d = build(Lx, Ly, Lz, n_modes=12)
    crit = d["xn"] > XI_CRIT
    for n in np.where(crit)[0]:
        n_crit += 1
        ratios.append(d["xi_est"][n] / max(d["xn"][n], 1e-9))
        min_xiest_crit = min(min_xiest_crit, d["xi_est"][n])
min_ratio = float(np.min(ratios))
print(f"  casi-criticos: {n_crit}, ratio xi_est/xi_nodal min={min_ratio:.3f} "
      f"mediana={np.median(ratios):.3f}, xi_est min de un casi-critico={min_xiest_crit:.3f}")
check("T1a xi_gate default < min_ratio*xi_crit (ningun casi-critico escapa al gate xi_est)",
      XI_GATE < min_ratio * XI_CRIT,
      f"{XI_GATE} < {min_ratio * XI_CRIT:.3f}")
check("T1b todo casi-critico observado tiene xi_est > xi_gate (margen real)",
      min_xiest_crit > XI_GATE, f"min xi_est casi-critico {min_xiest_crit:.3f} > {XI_GATE}")
print()


# ---------------------------------------------------------------------------
print("T2  RECUPERACION end-to-end (ducto): sparse recupera los subestimados por el fallback")
d = build(7.0, 2.1, 2.3, n_modes=12)
sp_xi = qs.sparse_boundary_xi_shift(d["K"], d["M"], d["Cr"], d["freqs"], d["phis"],
                                    beta=1.0, c=C0, fallback_xi=d["fx"],
                                    fallback_f=d["ff"])[0]
sig = d["xn"] > 0.1                                   # modos con amortiguamiento real
rel = np.abs(sp_xi[sig] - d["xn"][sig]) / np.maximum(d["xn"][sig], 1e-9)
# el modo SUBESTIMADO por el fallback que la sospecha debe rescatar
under = np.where((d["xn"] > 0.1) & (d["fx"] < 0.5 * d["xn"]))[0]
rescued = all(abs(sp_xi[n] - d["xn"][n]) / max(d["xn"][n], 1e-9) < 0.2 for n in under)
print(f"  modos xi_nodal>0.1: err medio {100*np.mean(rel):.1f}% max {100*np.max(rel):.1f}%")
print(f"  subestimados por fallback (fb<0.5·nodal): modos {list(under)} -> "
      f"sparse {np.round(sp_xi[under],3)} vs nodal {np.round(d['xn'][under],3)} "
      f"(fallback {np.round(d['fx'][under],3)})")
check("T2a sparse recupera todos los modos con xi_nodal>0.1 (err medio < 12%)",
      float(np.mean(rel)) < 0.12, f"medio {100*np.mean(rel):.1f}%")
check("T2b los subestimados por el fallback quedan recuperados (no clavados en fb)",
      rescued and len(under) > 0, f"{len(under)} modos rescatados")
print()


# ---------------------------------------------------------------------------
print("T3  por que NO un certificado η (no separa el error del ξ)")
Mp = sp.csr_matrix(d["M"], dtype=complex)
Cp = C0 * sp.csr_matrix(d["Cr"], dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(d["K"], dtype=complex)
nM, nC, nK = qs._qep_norms(Mp, Cp, Kp)
eta = np.empty(len(d["freqs"]))
for n in range(len(d["freqs"])):
    wnat = 2 * np.pi * d["ff"][n]; xi = d["fx"][n]
    s = -xi * wnat + 1j * wnat * np.sqrt(max(1 - xi * xi, 0.0))
    eta[n] = qs._backward_error(Mp, Cp, Kp, s, d["phis"][:, n].astype(complex), nM, nC, nK)
i_crit = int(np.argmax(d["xn"]))                      # el casi-critico (peor subestimado)
i_eta = int(np.argmax(eta))
print(f"  casi-critico = modo {i_crit} (xi_nodal={d['xn'][i_crit]:.3f}, "
      f"eta={eta[i_crit]:.2e});  eta maximo = modo {i_eta} (eta={eta[i_eta]:.2e}, "
      f"xi_nodal={d['xn'][i_eta]:.3f})")
check("T3 el η NO separa: el casi-critico NO es el de η maximo (η no sirve de gate)",
      i_eta != i_crit and eta[i_crit] < np.median(eta),
      f"eta[casi-critico]={eta[i_crit]:.2e} < mediana {np.median(eta):.2e}")
print()


print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
