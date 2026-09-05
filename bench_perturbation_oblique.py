# -*- coding: utf-8 -*-
"""bench_perturbation_oblique.py -- ORACULO del amortiguamiento/corrimiento en
geometria NO axis-aligned (hallazgo M3 de la auditoria).

La perturbacion de frontera estaba validada contra el QEP exacto solo en shoebox.
En geometria oblicua la frontera voxel es escalonada y la superficie lisa (vr,tr)
!= borde voxel. Este bench separa DOS cosas:

  (A) EXACTITUD DE PRIMER ORDEN en geometria oblicua: la perturbacion sobre el
      MISMO borde voxel que usa el QEP, delta_n = (c/2) beta (phi^T C phi) con phi
      M-ortonormal y C = ∮ Ni Nj dS (assemble_surface_M), vs el QEP complejo exacto
      (sla.eig 2N). Aisla el error del desarrollo de 1er orden (sin mezclar
      superficies). Debe ser chico, como en shoebox.

  (B) HEURISTICA superficie-lisa vs borde-voxel: la perturbacion como la computa la
      APP (fm.perturbation_xi_shift_per_mode sobre vr,tr con re-escala por cobertura)
      vs (A). Cuantifica el sesgo que introduce integrar sobre la superficie lisa en
      vez del borde voxel real (la preocupacion especifica del auditor).

T0 shoebox = sanity (debe reproducir bench_perturbation_complex). T1/T2 oblicuos.
Correr:  QT_QPA_PLATFORM=offscreen python bench_perturbation_oblique.py
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


def build_case(label, **room_kw):
    vr, tr, _e, _n = make_room(subdiv_levels=0, **room_kw)
    nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
    Nn = nodes.shape[0]
    K, M, _v = build_KM(nodes, tets)
    Cd = assemble_surface_M(nodes, extract_boundary_faces(tets, Nn)).toarray()
    Kd, Md = K.toarray(), M.toarray()
    freqs, phis = solve_modes(K, M, n_modes=8)
    loc = FieldEvaluator(nodes, tets)
    gr = fm.group_faces_by_planar_region(vr, tr)
    Vr = aa.compute_mesh_volume(vr, tr)
    # M-ortonormalizar phi (phi^T M phi = 1) para que phi^T C phi = ∮phi^2 dS con ∫phi^2dV=1
    phin = phis.copy()
    for i in range(phin.shape[1]):
        nrm = np.sqrt(abs(phin[:, i] @ (Md @ phin[:, i])))
        if nrm > 0:
            phin[:, i] /= nrm
    return dict(label=label, vr=vr, tr=tr, nodes=nodes, tets=tets, Nn=Nn,
                Kd=Kd, Md=Md, Cd=Cd, freqs=freqs, phis=phis, phin=phin,
                loc=loc, gr=gr, Vr=Vr)


def qep_solve(cs, beta):
    """QEP exacto (c^2 K + i c beta C w - M w^2)=0, beta uniforme. Devuelve (w, P)."""
    Nn = cs["Nn"]
    A0, A1, A2 = (C0 ** 2) * cs["Kd"], 1j * C0 * beta * cs["Cd"], -cs["Md"]
    Z, I = np.zeros((Nn, Nn)), np.eye(Nn)
    w, V = sla.eig(np.block([[A0, A1], [Z, I]]),
                   np.block([[Z, -A2], [I, Z]]), right=True)
    m = np.isfinite(w) & (np.real(w) > 1.0)
    return w[m], V[:Nn][:, m]


def match_overlap(cs, w, P, phi_n):
    Mp = cs["Md"] @ P
    num = np.abs(phi_n.conj() @ Mp)
    den = np.sqrt(np.abs(np.einsum('ik,ik->k', P.conj(), Mp)))
    k = int(np.argmax(num / np.maximum(den, 1e-30)))
    return w[k]


def run_case(cs, beta, tol_first=0.15):
    freqs = cs["freqs"]
    n = len(freqs)
    # (A) primer orden sobre el borde VOXEL: delta = (c/2) beta phi^T C phi
    s_vox = np.array([float(np.real(cs["phin"][:, i] @ (cs["Cd"] @ cs["phin"][:, i])))
                      for i in range(n)])
    delta_first = 0.5 * C0 * beta * s_vox                    # complejo (Np/s)
    xi_first = np.real(delta_first) / (2 * np.pi * freqs)
    fnew_first = freqs - np.imag(delta_first) / (2 * np.pi)
    # QEP exacto (mismo borde voxel)
    w_ex, P_ex = qep_solve(cs, beta)
    d_ex = np.empty(n)
    f_ex = np.empty(n)
    for i in range(n):
        wj = match_overlap(cs, w_ex, P_ex, cs["phis"][:, i])
        d_ex[i] = float(np.imag(wj))
        f_ex[i] = float(np.real(wj) / (2 * np.pi))
    e_d = np.abs(np.real(delta_first) / np.where(np.abs(d_ex) < 1e-9, np.nan, d_ex) - 1)
    e_f = np.abs((fnew_first - freqs) - (f_ex - freqs)) / (np.abs(f_ex - freqs) + 0.05)
    # (B) APP superficie lisa (vr,tr, cobertura)
    prov = lambda groups, fn, b=beta: np.full(len(groups), b, dtype=complex)
    xi_app, fnew_app = fm.perturbation_xi_shift_per_mode(
        cs["freqs"], cs["phis"], cs["loc"], cs["vr"], cs["tr"], cs["gr"], {},
        cs["Vr"], subdiv=3, beta_provider=prov)
    d_app = xi_app * 2 * np.pi * freqs
    e_heur = np.abs(d_app / np.where(np.abs(np.real(delta_first)) < 1e-12, np.nan,
                                     np.real(delta_first)) - 1)
    return dict(e_d=e_d, e_f=e_f, e_heur=e_heur,
                d_first=np.real(delta_first), d_ex=d_ex, d_app=d_app)


def main():
    print(__doc__.splitlines()[0]); print()
    beta = 0.04 + 0.025j                      # regimen de primer orden (|beta|~0.047)

    cases = [
        build_case("T0 shoebox 5x4x3 (sanity)", width=5, length=4, height=3,
                   n_walls=4, roof_type="flat"),
        build_case("T1 paredes en taper 0.35 (trapecio)", width=5, length=4, height=3,
                   n_walls=4, roof_type="flat", taper=0.35),
        build_case("T2 techo inclinado (pitch_x 0.4)", width=5, length=4, height=3,
                   n_walls=4, roof_type="flat", ceiling_pitch_x=0.4),
    ]
    for cs in cases:
        print(f"{cs['label']}: {cs['Nn']} nodos, {len(cs['freqs'])} modos, "
              f"f={np.round(cs['freqs'],1)}")
        r = run_case(cs, beta)
        # area voxel vs lisa (para interpretar B)
        oblique = "shoebox" not in cs["label"]
        check(f"{cs['label'][:34]:34s} (A) 1er orden vs QEP: amort < 15%",
              np.nanmean(r["e_d"]) < 0.15,
              f"amort media {100*np.nanmean(r['e_d']):.1f}% max {100*np.nanmax(r['e_d']):.1f}% "
              f"| corr media {100*np.nanmean(r['e_f']):.1f}%")
        # (B) es DIAGNOSTICO: se reporta el sesgo superficie-lisa vs borde-voxel
        print(f"       (B) heuristica app(superficie lisa) vs borde-voxel: "
              f"sesgo medio {100*np.nanmean(r['e_heur']):.1f}% "
              f"max {100*np.nanmax(r['e_heur']):.1f}%")
    print()
    print("=" * 64)
    print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
    print("=" * 64)
    return len(_FAIL) == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
