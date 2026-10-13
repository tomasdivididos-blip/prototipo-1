"""Bench M3: `only_if_larger` solo PISA con una asignacion polo->modo CONFIABLE.

Hallazgo M3 del auditor (12 Oct 2026): en el relleno Beyn, `_put(only_if_larger)`
escribia si el xi nuevo superaba al que habia, SIN verificar que el polo este bien
asignado al modo -> un polo mal asignado (de un vecino casi-degenerado) podia INFLAR
un modo modesto; F6-T2 (xi_sparse >= xi_fallback) no lo detecta. Era una asimetria
LOGICA (el auditor no pudo falsarla con un caso real).

Fix: el voto guarda tambien el MARGEN del solape sobre el 2do modo, y `_put` en el
pase de relleno solo pisa si solape >= overlap_strong (0.5) Y margen >= overlap_margin
(0.1). El 1er pase PAL (baseline) escribe sin guarda.

Oraculos:
  T1  la guarda esta CABLEADA y controla el overwrite de Beyn: con umbral ESTRICTO
      (0.999/0.9) rechaza la recuperacion del casi-critico que el default SI hace ->
      el xi vuelve al fallback. (prueba que only_if_larger pasa por la guarda)
  T2  el umbral DEFAULT (0.5/0.1) NO rechaza el casi-critico GENUINO (solape alto):
      recupera mode 0 == nodal (la guarda no introduce subestimacion).
  T3  NO-HARM: en una sala near-degenerada el resultado default (guarda ON) es
      IDENTICO a guarda OFF (overlap_strong=0, overlap_margin=0): la guarda no
      perturba los resultados buenos ya existentes.

ALCANCE (declarado): la guarda protege el camino de RELLENO Beyn (only_if_larger).
Las inflaciones OBSERVADAS en salas de degeneracion EXACTA (p.ej. un cubo: un modo
inflado por el 1er pase PAL, o sobre-estimado por el fallback modal) son el RIESGO
RESIDUAL pre-existente que el auditor dejo fuera de alcance (ahi la "verdad" nodal
tambien es ambigua: el autovector del multiplete degenerado es una rotacion
arbitraria). Esta guarda NO las ataca y no pretende hacerlo.

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_qep_sparse_m3.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

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


def setup(Lx, Ly, Lz, n_modes, npm=2.0):
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

    def sparse(**kw):
        return qs.sparse_boundary_xi_shift(K, M, Cr, freqs, phis, beta=1.0, c=C0,
                                           fallback_xi=fx, fallback_f=ff, **kw)[0]
    return freqs, xn, fx, sparse


print(__doc__.splitlines()[0])
print()

# --- Ducto 7x2.1x2.3: casi-critico LIMPIO (mode 0, recuperado por Beyn) ---
print("T1/T2  ducto 7x2.1x2.3 (casi-critico mode 0 recuperado por Beyn)")
freqs, xn, fx, sparse = setup(7.0, 2.1, 2.3, n_modes=12)
deflt = sparse()                                   # guarda default (0.5, 0.1)
strict = sparse(overlap_strong=0.999, overlap_margin=0.9)
# mode 0 = casi-critico; su recuperacion la hace el relleno Beyn (fallback -> nodal).
i0 = int(np.argmax(xn))
print(f"  mode {i0}: nodal={xn[i0]:.3f}  fallback={fx[i0]:.3f}  "
      f"default={deflt[i0]:.3f}  strict={strict[i0]:.3f}")
check("T1 la guarda ESTRICTA rechaza el overwrite de Beyn (xi vuelve al fallback)",
      abs(strict[i0] - fx[i0]) < 0.02 and deflt[i0] > fx[i0] + 0.1,
      f"strict {strict[i0]:.3f} ~ fallback {fx[i0]:.3f} << default {deflt[i0]:.3f}")
check("T2 la guarda DEFAULT NO rechaza el casi-critico genuino (recupera == nodal)",
      abs(deflt[i0] - xn[i0]) / max(xn[i0], 1e-9) < 0.05,
      f"default {deflt[i0]:.3f} vs nodal {xn[i0]:.3f}")
print()

# --- Sala near-degenerada: la guarda no debe perturbar resultados buenos ---
print("T3  no-harm en sala near-degenerada 4.2x4.0x3.8 (guarda ON == OFF)")
_f2, _xn2, _fx2, sparse2 = setup(4.2, 4.0, 3.8, n_modes=24, npm=1.8)
on = sparse2()                                     # guarda default
off = sparse2(overlap_strong=0.0, overlap_margin=0.0)   # guarda desactivada
dmax = float(np.max(np.abs(on - off)))
check("T3 guarda default == guarda OFF (no cambia resultados existentes)", dmax < 1e-9,
      f"max|ON-OFF| = {dmax:.2e}")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
