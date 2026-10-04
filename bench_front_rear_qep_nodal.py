"""Bench del QEP de frontera NODAL EXACTO (pendiente opcional de E3).

Valida las piezas nuevas de `face_materials` para el QEP sobre la malla FEM
COMPLETA (no proyectado a los modos), con beta COMPLEJA:
  - `rear_wall_surface_mass(nodes, tets, axis)` -> C de superficie de la pared
    trasera del volumen (caras de frontera con normal exterior ~ +axis).
  - `qep_boundary_nodal(K, M, C, freqs, phis, beta)` -> (xi, f_new) resolviendo
    c^2 K + i c beta C w - M w^2 = 0 (denso exacto; shift-invert sparse si grande).

Es el QEP del que el modal (`qep_boundary_xi_shift`, bench_front_rear_qep_modal)
es la proyeccion de Galerkin. Cierra E3: Re(beta) amortigua (xi), Im(beta) corre
la frecuencia (f_new).

Oraculos:
  T1  C de superficie: `rear_wall_surface_mass` elige la pared correcta y su masa
      == el ensamblado de referencia (assemble_surface_M sobre las mismas caras);
      suma de C == area de la pared.
  T2  ATADURA: para beta<<1 el QEP nodal reproduce la perturbacion de 1er orden
      (delta) en los modos acoplados -> se pega al modelo ya validado.
  T3  BETA COMPLEJA (cierra E3): con Im(beta)!=0 el QEP nodal corre la frecuencia
      (f_new != f) con el MISMO signo que la perturbacion compleja ya validada
      (bench_perturbation_complex), ademas del amortiguamiento por Re(beta).
  T4  PAYOFF (supera al modal): a beta=1 (matcheada) el QEP nodal alcanza mucho
      mas amortiguamiento AGREGADO que el modal truncado (regimen casi-critico que
      la base modal no representa; T4b del bench modal). Metrica agregada, no por
      modo: a beta=1 la identidad modal se degrada y el matcheo por-modo es ambiguo.
  T5  UMBRAL: por encima de max_dense el QEP nodal devuelve None (el caller cae al
      QEP modal, barato y validado); por debajo resuelve. No hay camino sparse (a
      beta~1 no converge de forma fiable; se declara y no se embarca).

Correr:  QT_QPA_PLATFORM=offscreen python bench_front_rear_qep_nodal.py
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
from sources import C0
from bench_modal_vs_impedance import extract_boundary_faces, assemble_surface_M

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

# --- Setup: shoebox 5x4x3, pared trasera = cara +x ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
Nn = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)
rear_mask = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)
print(f"  malla: {Nn} nodos, {len(freqs)} modos")
print(f"  f (rigido): {np.round(freqs, 2)}")
print()


# ---------------------------------------------------------------------------
print("T1  C de superficie de la pared trasera")
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
# referencia: mismas caras por coordenada maxima en x.
bf = extract_boundary_faces(tets, Nn)
cen = nodes[bf].mean(axis=1)
ref_faces = bf[cen[:, 0] > nodes[:, 0].max() - 1e-3]
C_ref = assemble_surface_M(nodes, ref_faces)
diff = np.abs((C_rear - C_ref)).sum()
area_err = abs(float(C_rear.sum()) / (Ly * Lz) - 1.0)
check("T1a rear_wall_surface_mass == ensamblado de referencia (mismas caras)",
      nf == len(ref_faces) and diff < 1e-9,
      f"n_caras {nf} vs {len(ref_faces)}, |dif| suma = {diff:.2e}")
check("T1b suma de C == area de la pared (Ly*Lz)", area_err < 1e-6,
      f"sum(C) = {float(C_rear.sum()):.4f} m^2 vs {Ly*Lz:.1f} (err {area_err:.2e})")
print()


# ---------------------------------------------------------------------------
print("T2  atadura perturbativa: beta<<1 -> QEP nodal ~ perturbacion de 1er orden")
beta2 = 0.05
prov = lambda gs, fn, m=rear_mask, b=beta2: m.astype(float) * b
xi_p, _f = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
d_p = xi_p * 2 * np.pi * freqs
xi_n, f_n = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=beta2, c=C0)
d_n = xi_n * 2 * np.pi * f_n
sig = d_p > 0.05 * np.max(d_p)
rel = np.abs(d_n[sig] / np.maximum(d_p[sig], 1e-30) - 1.0)
check("T2 beta=0.05: QEP nodal reproduce la perturbacion (delta, modos acoplados)",
      float(np.mean(rel)) < 0.08,
      f"media {100*np.mean(rel):.2f}% max {100*np.max(rel):.2f}%")
print()


# ---------------------------------------------------------------------------
print("T3  beta COMPLEJA (cierra E3): Im(beta) corre la frecuencia (f_new)")
beta3 = 0.04 + 0.04j
prov3 = lambda gs, fn, m=rear_mask, b=beta3: m.astype(complex) * b
xi_pc, f_pc = fm.perturbation_xi_shift_per_mode(
    freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov3)
xi_nc, f_nc = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=beta3, c=C0)
df_p = f_pc - freqs                                      # corrimiento perturbacion
df_n = f_nc - freqs                                      # corrimiento nodal
sig3 = (xi_pc * 2 * np.pi * freqs) > 0.05 * np.max(xi_pc * 2 * np.pi * freqs)
same_sign = np.all(np.sign(df_n[sig3]) == np.sign(df_p[sig3]))
seen = np.max(np.abs(df_n[sig3])) > 0.05
check("T3a corrimiento del QEP nodal con el MISMO signo que la perturbacion compleja",
      bool(same_sign), f"df_nodal {np.round(df_n[sig3][:4], 3)} vs "
                       f"df_pert {np.round(df_p[sig3][:4], 3)} Hz")
check("T3b el corrimiento por Im(beta) es observable (|df|>0.05 Hz)", bool(seen),
      f"max |df_nodal| = {np.max(np.abs(df_n[sig3])):.3f} Hz")
print()


# ---------------------------------------------------------------------------
print("T4  payoff: beta=1 (matcheada) -> QEP nodal >> modal truncado (agregado)")
G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rear_mask, subdiv=3)
xi_mod, f_mod = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
xi_nod, f_nod = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0)
# A beta=1 el matcheo por-modo se vuelve ambiguo (muchos modos rigidos mapean al
# mismo polo casi-critico), asi que ni la suma ni el por-modo son limpios. El
# hecho robusto y fisico: el ESPECTRO nodal CONTIENE polos casi-criticos que la
# proyeccion modal truncada no puede alcanzar. Metrica = pico de amortiguamiento.
xi_ratio = float(np.max(xi_nod) / max(np.max(xi_mod), 1e-30))
check("T4a el pico de amortiguamiento nodal supera MUCHO al modal (xi_max ratio > 2)",
      xi_ratio > 2.0, f"xi_max nodal/modal = {xi_ratio:.2f} "
                      f"({np.max(xi_nod):.2f} vs {np.max(xi_mod):.2f})")
check("T4b el QEP nodal alcanza regimen casi-critico (xi_max > 0.5) que el modal no",
      float(np.max(xi_nod)) > 0.5 and float(np.max(xi_mod)) < 0.5,
      f"xi_max nodal = {np.max(xi_nod):.2f} (casi-critico) vs modal = "
      f"{np.max(xi_mod):.2f} (capado por la base)")
print()


# ---------------------------------------------------------------------------
print("T5  umbral max_dense: None arriba del tope (el caller cae al modal)")
res_lo = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                               max_dense=Nn + 1)         # permite resolver
res_hi = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                               max_dense=Nn - 1)         # por encima del tope
check("T5a por debajo del tope resuelve (no None)", res_lo is not None,
      f"Nn={Nn} <= max_dense -> {'(xi,f)' if res_lo is not None else 'None'}")
check("T5b por encima del tope devuelve None (fallback al modal)", res_hi is None,
      f"Nn={Nn} > max_dense -> {'None' if res_hi is None else '(xi,f)'}")
print()


# ---------------------------------------------------------------------------
print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
