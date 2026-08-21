"""Bench del amortiguamiento por perturbacion de frontera (Etapa 1, v2.23).

Nucleo `face_materials.perturbation_xi_per_mode` + `beta_from_alpha_random`.
Respaldo teorico: Morse & Ingard 9.4.14, Kuttruff 3.34.

Oraculos:
  T1  inversion de Paris: alpha_rand ~ 8*beta a beta chico; round-trip.
  T2  oraculo del CUBO: S_n/V_n = 2(e_l/Lx+e_m/Ly+e_n/Lz) -> spread 8:10:12.
  T3  ordenamiento axial < tangencial < oblicuo (con material uniforme).
  T4  material uniforme NO reduce a Sabine (el punto), pero SI al promedio.
  T5  regresion vs el problema de autovalores complejos EXACTO (matriz C).
  T6  compone con material asimetrico (una pared tratada mueve el xi).

Correr:  QT_QPA_PLATFORM=offscreen python bench_perturbation_xi.py
"""
from __future__ import annotations

import os
import sys

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
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


class _UniformMat:
    """Material de alpha constante en frecuencia (para los oraculos)."""
    def __init__(self, a):
        self._a = float(a)
        self.name = f"a={a}"

    def alpha(self, f):
        return self._a


print(__doc__.splitlines()[0])
print()

# ---------------------------------------------------------------------------
print("T1  inversion de Paris (alpha incidencia aleatoria -> beta)")
for b_true in (0.005, 0.02, 0.05, 0.1):
    a = fm._alpha_random_of_beta(np.array([b_true]))[0]
    b_back = float(fm.beta_from_alpha_random(a))
    check(f"T1 round-trip beta={b_true}", abs(b_back / b_true - 1) < 0.02,
          f"a_rand={a:.4f} -> beta={b_back:.5f}")
# limite: alpha_rand ~ 8*beta a beta chico
a_small = fm._alpha_random_of_beta(np.array([1e-4]))[0]
check("T1b alpha_rand ~ 8*beta a beta->0", abs(a_small / (8e-4) - 1) < 0.02,
      f"alpha_rand(1e-4)={a_small:.6f} vs 8e-4={8e-4}")

# ---------------------------------------------------------------------------
print("\nT2/T3  oraculo del CUBO: spread axial/tangencial/oblicuo")
Lc = 4.0
v, t, _e, _n = make_room(Lc, Lc, Lc, n_walls=4, roof_type="flat", subdiv_levels=0)
modal = aa.run_fem_modal(v, t, n_modes=20, n_per_meter=4.0)
groups = fm.group_faces_by_planar_region(v, t)
Vc = aa.compute_mesh_volume(v, t)
g2m = {g.signature: _UniformMat(0.10) for g in groups}
xi = fm.perturbation_xi_per_mode(modal.freqs, modal.phis, modal.locator,
                                 v, t, groups, g2m, Vc, subdiv=3)
check("T2 devuelve xi finito y positivo",
      xi is not None and np.all(np.isfinite(xi)) and np.all(xi > 0))

# En un cubo, (1,0,0)/(0,1,0)/(0,0,1) son degenerados (axial),
# (1,1,0)... tangencial, (1,1,1) oblicuo. delta ~ S_n/V_n ~ 2*(n_nonzero_axes efectivos)
# Para el cubo: axial S/V=2*(2/L)=... el ratio teorico axial:tang:obl = 8:10:12
# (con e=2 en cada eje excitado + el /L comun). Se identifican por frecuencia.
def f_ana(l, m, n):
    return 0.5 * C0 * np.sqrt(l * l + m * m + n * n) / Lc


def xi_of(l, m, n):
    ft = f_ana(l, m, n)
    j = int(np.argmin(np.abs(np.asarray(modal.freqs) - ft)))
    return float(xi[j]), float(modal.freqs[j]), abs(modal.freqs[j] - ft) / ft


xi_ax, f_ax, e_ax = xi_of(1, 0, 0)
xi_tg, f_tg, e_tg = xi_of(1, 1, 0)
xi_ob, f_ob, e_ob = xi_of(1, 1, 1)
# delta = xi * 2pi f  -> comparar delta (el spread 8:10:12 es en delta, no en xi)
d_ax = xi_ax * 2 * np.pi * f_ax
d_tg = xi_tg * 2 * np.pi * f_tg
d_ob = xi_ob * 2 * np.pi * f_ob
ratio = np.array([d_ax, d_tg, d_ob]) / d_ax * 8.0
check("T3 ordenamiento axial < tangencial < oblicuo (en delta)",
      d_ax < d_tg < d_ob, f"delta = {d_ax:.3f} < {d_tg:.3f} < {d_ob:.3f} Np/s")
check("T2b spread ~ 8:10:12 (teorico exacto del cubo)",
      np.allclose(ratio, [8, 10, 12], rtol=0.08),
      f"medido {ratio[0]:.1f}:{ratio[1]:.1f}:{ratio[2]:.1f}  (err_f<{max(e_ax,e_tg,e_ob)*100:.1f}%)")

# ---------------------------------------------------------------------------
print("\nT4  material uniforme: NO reduce a Sabine, pero SI a su promedio")
V0, S0 = Lc ** 3, 6 * Lc ** 2
alpha = 0.10
a_rand_back = float(np.mean([fm._alpha_random_of_beta(
    fm.beta_from_alpha_random(np.array([alpha])))[0]]))
rt_sab = 0.161 * V0 / (alpha * S0)
xi_sab = 1.1 / (np.asarray(modal.freqs) * rt_sab)
# El delta medio de la perturbacion deberia rondar el de Sabine (campo difuso
# = promedio de direcciones), pero con dispersion que Sabine no tiene.
d_pert = xi * 2 * np.pi * np.asarray(modal.freqs)
d_sab = 6.91 / rt_sab
check("T4 delta pert NO es constante (Sabine si)",
      d_pert.std() / d_pert.mean() > 0.10,
      f"CV={100*d_pert.std()/d_pert.mean():.0f}% vs Sabine 0%")
check("T4b pero su MEDIA queda cerca de Sabine (mismo orden)",
      0.7 < d_pert.mean() / d_sab < 1.6,
      f"<delta_pert>={d_pert.mean():.2f} vs delta_Sabine={d_sab:.2f} Np/s")

# ---------------------------------------------------------------------------
print("\nT5  REGRESION vs autovalores complejos EXACTOS (matriz C)")
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e2, _n2 = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.5)
Nn = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
Cd = assemble_surface_M(nodes, extract_boundary_faces(tets, Nn)).toarray()
freqs, phis = solve_modes(K, M, n_modes=10)
Kd, Md = K.toarray(), M.toarray()
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)


def qep_delta(beta):
    A0, A1, A2 = (C0 ** 2) * Kd, 1j * C0 * beta * Cd, -Md
    Z, I = np.zeros((Nn, Nn)), np.eye(Nn)
    w = sla.eig(np.block([[A0, A1], [Z, I]]),
                np.block([[Z, -A2], [I, Z]]), right=False)
    w = w[np.isfinite(w)]
    return w[np.real(w) > 1.0]


for a_norm in (0.10, 0.30):
    r = np.sqrt(1.0 - a_norm)
    beta = (1.0 - r) / (1.0 + r)                 # incidencia normal
    a_rand = float(fm._alpha_random_of_beta(np.array([beta]))[0])
    mat = _UniformMat(a_rand)                    # el catalogo daria a_rand
    g2m_r = {g.signature: mat for g in gr}
    xi_p = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m_r, Vr,
                                       subdiv=3)
    d_p = xi_p * 2 * np.pi * np.asarray(freqs)
    w_ex = qep_delta(beta)
    errs = []
    for i in range(len(freqs)):
        j = int(np.argmin(np.abs(np.real(w_ex) / (2 * np.pi) - freqs[i])))
        if abs(np.real(w_ex[j]) / (2 * np.pi) - freqs[i]) / freqs[i] > 0.10:
            continue
        d_ex = float(np.imag(w_ex[j]))
        errs.append(abs(d_p[i] / d_ex - 1))
    errs = np.array(errs)
    tol = 0.03 if a_norm <= 0.1 else 0.05
    check(f"T5 [alpha_norm={a_norm}] pert vs exacto < {tol*100:.0f}%",
          errs.mean() < tol, f"media {100*errs.mean():.2f}% max {100*errs.max():.2f}%")

# ---------------------------------------------------------------------------
print("\nT6  material asimetrico: tratar una pared mueve el xi")
g2m_asym = {gr[0].signature: _UniformMat(0.6)}     # solo una cara
xi_a = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m_asym, Vr,
                                   subdiv=2)
xi_rig = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=2)
check("T6 tratar una pared sube el xi de los modos que la cargan",
      xi_a is not None and xi_a.mean() > xi_rig.mean(),
      f"xi medio {xi_a.mean():.4f} (tratada) vs {xi_rig.mean():.4f} (rigida)")
check("T6b y es SELECTIVO (no sube todos igual)",
      (xi_a - xi_rig).std() / max((xi_a - xi_rig).mean(), 1e-9) > 0.1,
      f"CV del incremento = {100*(xi_a-xi_rig).std()/(xi_a-xi_rig).mean():.0f}%")

# ---------------------------------------------------------------------------
print("\nT7  el selector del panel despacha y es reversible (end-to-end)")
from PyQt5.QtWidgets import QApplication         # noqa: E402
from viewer import IsoViewer                     # noqa: E402
from acoustic_panel import AcousticPanel         # noqa: E402
from sources import OmniSource                   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
vp, tp, _ep, _np2 = make_room(5.0, 4.0, 3.0, n_walls=4)
panel = AcousticPanel(viewer=IsoViewer(), get_surface=lambda: (vp, tp),
                      get_dims_hint=lambda: (5.0, 4.0, 3.0))
panel._log = lambda *a, **k: None
panel.sources.add(OmniSource((1.2, 0.9, 1.0), sensitivity_dB=90.0))
panel.apply_zone_materials("Alfombra fina", "Alfombra fina", "Alfombra fina")
panel.modal_result = aa.run_fem_modal(vp, tp, n_modes=20, n_per_meter=3.0)

# Etapa 3 (v2.24): el default es perturbación (antes a36).
check("T7 default = perturbation (Etapa 3)",
      panel._damping_model == "perturbation")
# A36 explícito para el baseline uniforme.
panel.combo_damping.setCurrentIndex(panel.combo_damping.findData("a36"))
xi_a36 = panel._compute_xi_from_materials()
d_a36 = xi_a36 * 2 * np.pi * np.asarray(panel.modal_result.freqs)
panel.combo_damping.setCurrentIndex(panel.combo_damping.findData("perturbation"))
check("T7b el combo cambió el modelo y recalculó ξ",
      panel._damping_model == "perturbation" and panel._xi_per_mode is not None)
d_pe = panel._xi_per_mode * 2 * np.pi * np.asarray(panel.modal_result.freqs)
check("T7c A36 uniforme ≈ constante, perturbación con spread",
      d_a36.std() / d_a36.mean() < 0.03 and d_pe.std() / d_pe.mean() > 0.08,
      f"A36 CV={100*d_a36.std()/d_a36.mean():.1f}% pert CV={100*d_pe.std()/d_pe.mean():.1f}%")
panel.combo_damping.setCurrentIndex(panel.combo_damping.findData("a36"))
check("T7d reversible bit a bit",
      np.allclose(panel._compute_xi_from_materials(), xi_a36, rtol=1e-12))

# ---------------------------------------------------------------------------
print("\nT8  Etapa 1.b: perturbación compone con parches (misma cuadratura)")
import absorption_patch as ap                    # noqa: E402

vq, tq, _eq, _nq = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat",
                             subdiv_levels=0)
mq = aa.run_fem_modal(vq, tq, n_modes=16, n_per_meter=3.0)
grq = fm.group_faces_by_planar_region(vq, tq)
Vq = aa.compute_mesh_volume(vq, tq)
floor = next(g for g in grq if g.kind == "floor")
host = _UniformMat(0.20)
g2mq = {g.signature: host for g in grq}          # material uniforme en todas

# perturbación SIN parches (referencia)
xi_nopatch = fm.perturbation_xi_per_mode(mq.freqs, mq.phis, mq.locator,
                                         vq, tq, grq, g2mq, Vq, subdiv=3)

# parche full-face con EL MISMO material que el anfitrión -> debe ser no-op
na, ua, va = ap.axis_aligned_frame(floor.normal)
fv = vq[np.unique(tq[np.asarray(floor.face_indices, int)].ravel())]
p_noop = ap.make_patch(floor, fv[:, ua].min(), fv[:, va].min(),
                       fv[:, ua].max(), fv[:, va].max(), "host")
xi_noop = ap.compute_xi_per_mode_with_patches(
    mq.freqs, mq.phis, mq.locator, vq, tq, grq, g2mq,
    patches=[p_noop], patch_to_material={p_noop.key: host}, V=Vq,
    model="perturbation")
check("T8 parche = material del anfitrión -> igual a sin parche (no-op)",
      xi_noop is not None
      and np.allclose(xi_noop, xi_nopatch, rtol=0.03),
      f"máx dif rel = {np.abs(xi_noop/xi_nopatch - 1).max():.2e}")

# parche absorbente real -> sube el xi (más absorción en el piso)
absb = _UniformMat(0.8)
xi_abs = ap.compute_xi_per_mode_with_patches(
    mq.freqs, mq.phis, mq.locator, vq, tq, grq, g2mq,
    patches=[p_noop], patch_to_material={p_noop.key: absb}, V=Vq,
    model="perturbation")
check("T8b parche absorbente sube el xi (compone de verdad)",
      xi_abs is not None and xi_abs.mean() > xi_noop.mean(),
      f"xi medio {xi_abs.mean():.4f} (absorbente) vs {xi_noop.mean():.4f} (no-op)")

# regresión: model='a36' (default) sigue dando lo de siempre (Sabine con parche)
xi_a36_patch = ap.compute_xi_per_mode_with_patches(
    mq.freqs, mq.phis, mq.locator, vq, tq, grq, g2mq,
    patches=[p_noop], patch_to_material={p_noop.key: absb}, V=Vq)  # model='a36'
check("T8c model='a36' (default) intacto: NO es la perturbación",
      not np.allclose(xi_a36_patch, xi_abs, rtol=0.05),
      f"a36 {xi_a36_patch.mean():.4f} vs pert {xi_abs.mean():.4f}")

# ---------------------------------------------------------------------------
print()
print(f"RESULTADO: {len(_PASS)}/{len(_PASS) + len(_FAIL)} OK")
if _FAIL:
    print("FALLARON: " + ", ".join(_FAIL))
sys.exit(1 if _FAIL else 0)
