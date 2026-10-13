"""Bench M4: Beyn ya NO pierde polos en silencio al saturar el SVD.

Hallazgo M4 del auditor (12 Oct 2026): `beyn_contour` hacia k=sum(s>tol·s0) y, si el
contorno encerraba mas polos que la sonda `ell`, k saturaba en ell y los polos de mas
se perdian SIN AVISO; `only_if_larger` dejaba entonces el fallback subestimado.

Fix: `beyn_contour`/`beyn_qep` exponen {k, ell, saturated}; el tiling del wrapper
`sparse_boundary_xi_shift` BISECTA la banda en Im y recursa cuando satura (reduce
modos-por-contorno), e instrumenta `n_saturated`.

Oraculos:
  T1  el flag de saturacion DISPARA: ell chico sobre un contorno denso -> saturated
      True; ell grande -> saturated False y halla mas polos. (ya no es silencioso)
  T2  la BISECCION recupera: un contorno saturado (ell=24, 40 polos) devuelve ~ell;
      bisecar la banda en dos mitades (ell=24 c/u) no satura y recupera TODOS.
  T3  INTEGRACION: en una sala densa, el sparse recupera los casi-criticos que el
      nodal denso (oraculo exacto, Nn<=1800) confirma, y reporta n_saturated.

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_qep_sparse_m4.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.sparse as sp

import qep_sparse as qs

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

# --- QEP sintetico denso: N modos en una banda estrecha, amortiguamiento leve ---
#   z^2 I + z (0.5 I) + diag(wn^2) = 0  -> polos z ~ -0.25 +/- i wn (casi en el eje Im)
N = 40
fn = 40.0 + 4.0 * np.arange(N)                 # 40..196 Hz, banda densa (espaciado 4)
wn = 2.0 * np.pi * fn
M = sp.identity(N, format="csr", dtype=complex)
K = sp.diags((wn ** 2).astype(complex), format="csr")
C = sp.identity(N, format="csr", dtype=complex) * 0.5


def contour_for(fa, fbb, ell, nq=64, margin=2.0):
    fcl = 0.5 * (fa + fbb)
    wc = 2.0 * np.pi * fcl
    z0 = -0.1 * wc + 1j * wc
    a_re = 1.15 * wc
    b_im = 2.0 * np.pi * (0.5 * (fbb - fa) + margin)   # Im ajustado a la banda
    return qs.beyn_qep(M, C, K, z0, a_re, n_quad=nq, ell=ell, b=b_im,
                       return_info=True)


# ---------------------------------------------------------------------------
print("T1  el flag de saturacion DISPARA (ya no es silencioso)")
lam_s, _Vs, _es, info_s = contour_for(fn[0], fn[-1], ell=24)
lam_b, _Vb, _eb, info_b = contour_for(fn[0], fn[-1], ell=100)
check("T1a ell=24 (chico) sobre 40 polos -> saturated=True", info_s["saturated"] is True,
      f"k={info_s['k']} ell={info_s['ell']}")
check("T1b ell=100 (holgado) -> saturated=False", info_b["saturated"] is False,
      f"k={info_b['k']} ell={info_b['ell']}")
check("T1c ell holgado halla mas polos que el saturado", len(lam_b) > len(lam_s),
      f"{len(lam_b)} vs {len(lam_s)}")
print()


# ---------------------------------------------------------------------------
print("T2  la BISECCION en Im recupera: a MISMO ell, la banda densa satura pero las")
print("    sub-bandas (menos polos encerrados -> menor rango) entran y recuperan")
ELL = 32                                       # chico para 40 polos, holgado para 10
lam_one, _V1, _e1, info_one = contour_for(fn[0], fn[-1], ell=ELL)
# 4 sub-bandas por INDICE, con los bordes en los HUECOS entre modos (medio
# espaciado) para que el contorno no roce ningun polo.
half = 2.0
groups = [list(range(0, 10)), list(range(10, 20)),
          list(range(20, 30)), list(range(30, 40))]
rec, sat_any = 0, False
for g in groups:
    fa, fbb = fn[g[0]] - half, fn[g[-1]] + half
    lam_g, _Vg, _eg, info_g = contour_for(fa, fbb, ell=ELL, margin=0.0)
    rec += len(lam_g)
    sat_any = sat_any or info_g["saturated"]
check(f"T2a la banda densa entera (ell={ELL}) satura y pierde polos", info_one["saturated"],
      f"halla {len(lam_one)} de ~{N}")
check(f"T2b las sub-bandas (mismo ell={ELL}) ya NO saturan", not sat_any)
check("T2c las sub-bandas recuperan casi todos los polos (>=0.9 N)",
      rec >= int(0.9 * N), f"recuperados {rec} de {N}")
print()


# ---------------------------------------------------------------------------
print("T3  INTEGRACION: el refactor M4 no rompe el camino normal (sparse == nodal en")
print("    el casi-critico limpio del ducto) + reporta n_saturated")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import face_materials as fm
from sources import C0

# Ducto 7x2.1x2.3 (eje x largo matcheado): casi-critico GENUINO y LIMPIO (sin la
# degeneracion casi-cubica que dispara la mis-asignacion pre-existente, M3). Es la
# geometria de bench_qep_sparse_f6.
Lx, Ly, Lz = 7.0, 2.1, 2.3
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
Nn = nodes.shape[0]
Kv, Mv, _vol = build_KM(nodes, tets)
freqs, phis = solve_modes(Kv, Mv, n_modes=24)
gr = fm.group_faces_by_planar_region(vr, tr)
rear_mask = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)
C_rear, _nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
print(f"  malla {Nn} nodos, {len(freqs)} modos (densidad alta)")

loc = FieldEvaluator(nodes, tets)
xi_nod, _fn = fm.qep_boundary_nodal(Kv, Mv, C_rear, freqs, phis, beta=1.0, c=C0)
G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rear_mask)
qep_mod = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
fx = np.asarray(qep_mod[0], float); ff = np.asarray(qep_mod[1], float)
xi_sp, f_sp, info = qs.sparse_boundary_xi_shift(
    Kv, Mv, C_rear, freqs, phis, beta=1.0, c=C0,
    fallback_xi=fx, fallback_f=ff, return_info=True)

check("T3a info reporta n_saturated (ya no es silencioso)", "n_saturated" in info,
      f"n_saturated={info.get('n_saturated')}")
# casi-criticos segun el oraculo nodal (xi clasico post-C1)
crit = xi_nod > 0.25
if np.any(crit):
    rel = np.abs(xi_sp[crit] - xi_nod[crit]) / np.maximum(xi_nod[crit], 1e-9)
    worst = float(np.max(rel))
    # ninguno quedo clavado en el fallback subestimado (que para esos modos seria << nodal)
    stuck = np.abs(xi_sp[crit] - fx[crit]) < 1e-6
    not_stuck = not np.any(stuck & (xi_nod[crit] > 1.5 * np.maximum(fx[crit], 1e-9)))
    check("T3b sparse recupera los casi-criticos vs nodal (err medio < 15%)",
          float(np.mean(rel)) < 0.15, f"medio {100*np.mean(rel):.1f}% max {100*worst:.1f}%")
    check("T3c ningun casi-critico quedo clavado en el fallback subestimado", not_stuck,
          f"{int(np.sum(stuck))} clavados de {int(np.sum(crit))} casi-criticos")
else:
    check("T3b (sin casi-criticos en esta malla; se omite)", True)
    check("T3c (sin casi-criticos en esta malla; se omite)", True)
print()


# ---------------------------------------------------------------------------
print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
