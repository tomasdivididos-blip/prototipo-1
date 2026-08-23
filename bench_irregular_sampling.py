"""Bench de muestreo en plantas IRREGULARES (auditoría 18 Ago 2026, v2.23).

Los benches previos usan todos shoebox, que es exactamente por que estos dos
bugs vivieron sin que nadie los viera: en una caja el bounding box ES el
recinto y no se pierde ni un punto.

Cubre:
  A1  receptores de `default_receiver_grid` que caen FUERA del recinto. Entraban
      con phi=0 -> -600 dB -> `FoM_espacial` de ~5 dB pasaba a ~90 dB.
  A2  centroides de cara fuera de la malla en A36. Pesaban CERO en el alpha_eff
      del modo -> la absorcion de las paredes oblicuas se subestimaba.

Correr:  QT_QPA_PLATFORM=offscreen python bench_irregular_sampling.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from geometry import make_room
import acoustic_analysis as aa
import modal_metrics as mm
import face_materials as fm
from sources import OmniSource, SourceArray

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


_L_POLY = np.array([[0, 0], [6, 0], [6, 3], [3, 3], [3, 6], [0, 6]], dtype=float)

ROOMS = {
    "shoebox":   dict(width=5.0, length=4.0, height=3.0, n_walls=4),
    "pentagono": dict(width=5.0, length=4.0, height=3.0, n_walls=5),
    "hex_taper": dict(width=6.0, length=5.0, height=3.0, n_walls=6, taper=0.45),
    "planta_L":  dict(width=6.0, length=6.0, height=3.0, base_polygon=_L_POLY),
}


def solve(kw, npm=3.0, n_modes=25):
    v, t, _e, _n = make_room(**kw)
    return v, t, aa.run_fem_modal(v, t, n_modes=n_modes, n_per_meter=npm)


print(__doc__.splitlines()[0])
print()

# ---------------------------------------------------------------------------
print("A1  grilla de receptores en plantas irregulares")
solved = {}
for name, kw in ROOMS.items():
    v, t, modal = solve(kw)
    solved[name] = (v, t, modal)

    cruda = mm.default_receiver_grid(modal.nodes)
    ok_cruda = mm.receivers_inside(modal.locator, modal.phis, cruda)
    filtrada = mm.default_receiver_grid(modal.nodes, locator=modal.locator,
                                        phis=modal.phis)
    ok_filt = mm.receivers_inside(modal.locator, modal.phis, filtrada)

    check(f"A1 [{name}] la grilla filtrada NO tiene puntos fuera",
          bool(ok_filt.all()),
          f"cruda {int((~ok_cruda).sum())}/{len(cruda)} afuera → "
          f"filtrada {int((~ok_filt).sum())}/{len(filtrada)}")
    check(f"A1b [{name}] conserva una muestra útil (≥ 60 % de 25)",
          len(filtrada) >= 15, f"{len(filtrada)} receptores")

# El shoebox NO debe cambiar (regresión: la grilla filtrada == la cruda).
_v, _t, m_box = solved["shoebox"]
check("A1c shoebox: la grilla no cambia (regresión exacta)",
      np.array_equal(mm.default_receiver_grid(m_box.nodes),
                     mm.default_receiver_grid(m_box.nodes,
                                              locator=m_box.locator,
                                              phis=m_box.phis)))

# ---------------------------------------------------------------------------
print("\nA1d  el FoM espacial deja de explotar")
for name in ("pentagono", "hex_taper", "planta_L"):
    _v, _t, modal = solved[name]
    arr = SourceArray()
    arr.add(OmniSource(tuple(modal.nodes.mean(axis=0) * 0.5 + 0.2),
                       sensitivity_dB=90.0))
    fa = np.linspace(20.0, 120.0, 200)
    grid = mm.default_receiver_grid(modal.nodes, locator=modal.locator,
                                    phis=modal.phis)
    H = mm.compute_forced_response(modal.locator, modal.freqs, modal.phis,
                                   arr, grid, fa, damping=0.05)
    fom = mm.response_figures_of_merit(H, fa)
    check(f"A1d [{name}] FoM_espacial en rango físico (< 20 dB)",
          np.isfinite(fom.FoM_espacial) and fom.FoM_espacial < 20.0,
          f"{fom.FoM_espacial:.2f} dB (antes ~70-98 dB)")

# ---------------------------------------------------------------------------
print("\nA1e  _modal_terms ya no miente: falla fuerte con receptores inválidos")
_v, _t, modal = solved["pentagono"]
cruda = mm.default_receiver_grid(modal.nodes)
mala = cruda[~mm.receivers_inside(modal.locator, modal.phis, cruda)]
arr = SourceArray()
arr.add(OmniSource(tuple(modal.nodes.mean(axis=0) * 0.5 + 0.2), sensitivity_dB=90.0))
try:
    mm.compute_forced_response(modal.locator, modal.freqs, modal.phis, arr,
                               mala, np.linspace(20.0, 120.0, 50), damping=0.05)
    _raised = False
except ValueError as e:
    _raised = "FUERA" in str(e)
check("A1e receptores fuera → ValueError explícito (antes: 0 en silencio)",
      _raised)

# ---------------------------------------------------------------------------
print("\nA2  A36 no pierde área de pared en geometría oblicua")
for name in ("shoebox", "pentagono"):
    v, t, modal = solved[name]
    groups = fm.group_faces_by_planar_region(v, t)
    cen = v[t].mean(axis=1)
    bad = ~np.isfinite(np.real(modal.locator.evaluate_many(modal.phis[:, 0], cen)))
    V = aa.compute_mesh_volume(v, t)
    xi = fm.compute_xi_per_mode_per_face(
        modal.freqs, modal.phis, modal.locator, v, t, groups, {}, V)
    check(f"A2 [{name}] xi finito y positivo con {int(bad.sum())} centroides perdidos",
          xi is not None and np.all(np.isfinite(xi)) and np.all(xi > 0),
          f"xi medio {xi.mean():.4f}" if xi is not None else "None")

# Regresión dura: material UNIFORME debe reducir EXACTO a la Sabine global,
# incluso con centroides perdidos (el re-escalado por cobertura lo garantiza).
v, t, modal = solved["pentagono"]
groups = fm.group_faces_by_planar_region(v, t)
V = aa.compute_mesh_volume(v, t)


class _Mat:
    name = "uniforme"
    def alpha(self, f):        # noqa: E301
        return 0.25


g2m = {g.signature: _Mat() for g in groups}
xi_u = fm.compute_xi_per_mode_per_face(modal.freqs, modal.phis, modal.locator,
                                       v, t, groups, g2m, V)
S_tot = sum(g.area for g in groups)
T60_sab = 0.161 * V / (S_tot * 0.25)
xi_sab = 1.1 / (np.asarray(modal.freqs, dtype=float) * T60_sab)
check("A2b material uniforme ≡ Sabine global EXACTO (pese a los perdidos)",
      np.allclose(xi_u, xi_sab, rtol=1e-9),
      f"máx dif rel = {np.abs(xi_u/xi_sab - 1).max():.2e}")

# Y la absorción de una pared oblicua tiene que MOVER el xi (antes, con el
# área perdida, su peso quedaba subestimado).
g_obl = [g for g in groups if "Pared" in g.label]
g2m_asim = {g.signature: (_Mat() if g is g_obl[0] else None) for g in groups}
g2m_asim = {k: v2 for k, v2 in g2m_asim.items() if v2 is not None}
xi_asim = fm.compute_xi_per_mode_per_face(modal.freqs, modal.phis, modal.locator,
                                          v, t, groups, g2m_asim, V)
check("A2c tratar UNA pared oblicua cambia el xi (su área ya no se pierde)",
      xi_asim is not None and not np.allclose(xi_asim, xi_u),
      f"xi medio {xi_asim.mean():.4f} vs uniforme {xi_u.mean():.4f}")

# ---------------------------------------------------------------------------
print()
print(f"RESULTADO: {len(_PASS)}/{len(_PASS) + len(_FAIL)} OK")
if _FAIL:
    print("FALLARON: " + ", ".join(_FAIL))
sys.exit(1 if _FAIL else 0)
