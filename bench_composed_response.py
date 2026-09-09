"""
bench_composed_response.py - núcleo canónico modal + SBIR en SPL absoluto (grupo A)
===================================================================================
Valida, headless, la función `composed_response.composed_response` (Fase 1 del
plan_respuesta_compuesta.md):

  C1  REDUCCIÓN modal: sin paredes (walls=None) la compuesta ES la FRF modal, en
      dBSPL absoluto = 20log10(|H|/20µPa), bit a bit con `run_fem_frf`.
  C2  REDUCCIÓN SBIR: sin modos (modal_result=None) la compuesta ES el SBIR
      absoluto = 20log10(|total_p_total|/20µPa).
  C3  CROSSFADE: con modal Y SBIR, debajo de f_S/√2 la compuesta == modal, encima
      de f_S·√2 == SBIR, y es finita/continua en el medio.
  C4  ESCALA ABSOLUTA física: el directo de campo libre del SBIR coincide con el
      monopolo analítico |p| = ω·ρ0·|Q|/(4π r) -> dBSPL correcto (no un ratio).
  C5  f_schroeder faltante con modal+SBIR -> error explícito (no compone en silencio).

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_composed_response.py
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
import sbir
from sources import single_source, RHO0
import composed_response as cr
from composed_response import P_REF

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# --- Setup: shoebox 5x4x3 + modos (idiom de bench_sbir_modal) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.6)
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
_lo, _hi = nodes.min(axis=0), nodes.max(axis=0)


def _inside(fr):
    return tuple(_lo + np.asarray(fr) * (_hi - _lo))


class _Modal:
    def __init__(self):
        self.locator, self.freqs, self.phis = loc, freqs, phis


modal = _Modal()
act = single_source(_inside((0.30, 0.30, 0.5)))
rcv = _inside((0.72, 0.65, 0.55))
f_lo, f_hi = 20.0, 500.0
freq = np.linspace(f_lo, f_hi, 2000)
walls = [sbir.Wall(point=g.centroid, normal=g.normal, label=g.label,
                   R=sbir.reflection_from_alpha(np.full(freq.shape, 0.1)))
         for g in gr]
damping = 0.02
print(f"  malla {nodes.shape[0]} nodos, {len(freqs)} modos, {len(walls)} paredes")


# ---------------------------------------------------------------------------
print("\nC1  reducción modal (walls=None -> FRF modal en dBSPL)")
c1 = cr.composed_response(act, rcv, freq, modal_result=modal, walls=None,
                          damping=damping)
frf = aa.run_fem_frf(modal, act, rcv, f_min=f_lo, f_max=f_hi, n_freqs=len(freq),
                     damping=damping)
frf_spl = 20.0 * np.log10(np.maximum(np.abs(frf.H), 1e-30) / P_REF)
check("C1a compuesta == FRF modal en dBSPL (bit a bit)",
      np.allclose(c1.composed_spl, frf_spl, atol=1e-9),
      f"max|dif|={np.max(np.abs(c1.composed_spl - frf_spl)):.2e} dB")
check("C1b sin SBIR (has_sbir False, sbir_spl None)",
      (not c1.has_sbir) and c1.sbir_spl is None and c1.has_modal, "")
check("C1c la curva modal tiene resonancias (std > 3 dB)",
      float(np.std(c1.composed_spl)) > 3.0, f"std={np.std(c1.composed_spl):.1f} dB")


# ---------------------------------------------------------------------------
print("\nC2  reducción SBIR (modal_result=None -> SBIR absoluto en dBSPL)")
c2 = cr.composed_response(act, rcv, freq, modal_result=None, walls=walls)
res = sbir.sbir_from_sources(act, walls, rcv, freq)
sbir_spl = 20.0 * np.log10(np.maximum(np.abs(res.total_p_total), 1e-30) / P_REF)
check("C2a compuesta == SBIR absoluto (bit a bit)",
      np.allclose(c2.composed_spl, sbir_spl, atol=1e-9),
      f"max|dif|={np.max(np.abs(c2.composed_spl - sbir_spl)):.2e} dB")
check("C2b sin modal (has_modal False, modal_spl None)",
      (not c2.has_modal) and c2.modal_spl is None and c2.has_sbir, "")


# ---------------------------------------------------------------------------
print("\nC3  crossfade modal+SBIR en f_Schroeder")
f_s = 120.0
c3 = cr.composed_response(act, rcv, freq, modal_result=modal, walls=walls,
                          f_schroeder=f_s, damping=damping)
lo = f_s * 2 ** -0.5
hi = f_s * 2 ** +0.5
check("C3a finita y misma longitud",
      c3.composed_spl.shape == freq.shape and np.all(np.isfinite(c3.composed_spl)), "")
check("C3b debajo de f_S/√2 la compuesta == modal_spl",
      np.allclose(c3.composed_spl[freq <= lo], c3.modal_spl[freq <= lo], atol=1e-9), "")
check("C3c encima de f_S·√2 la compuesta == sbir_spl",
      np.allclose(c3.composed_spl[freq >= hi], c3.sbir_spl[freq >= hi], atol=1e-9), "")
# continuidad: sin saltos espurios (paso a paso acotado por el rango de las curvas)
step = np.max(np.abs(np.diff(c3.composed_spl)))
span = float(np.max(c3.composed_spl) - np.min(c3.composed_spl))
check("C3d continua (max salto entre muestras << rango de la curva)",
      step < 0.5 * span, f"salto={step:.2f} dB, rango={span:.1f} dB")


# ---------------------------------------------------------------------------
print("\nC4  escala absoluta física (directo de campo libre = monopolo analítico)")
# Fuente única Q=1: |p_dir(f)| = omega*rho0*|Q|/(4*pi*r). Comparo el directo del
# SBIR (res.total_p_direct, = ese monopolo) contra el analítico, en dBSPL.
xs = np.asarray(act.positions(), dtype=float).reshape(-1, 3)[0]
r = float(np.linalg.norm(np.asarray(rcv, float) - xs))
i0 = 1000
f0 = float(freq[i0])
p_dir_analytic = (2.0 * np.pi * f0) * RHO0 * 1.0 / (4.0 * np.pi * r)  # |Q|=1
spl_analytic = 20.0 * np.log10(p_dir_analytic / P_REF)
spl_sbir_dir = 20.0 * np.log10(np.abs(res.total_p_direct[i0]) / P_REF)
check("C4a directo del SBIR == monopolo analítico en dBSPL",
      abs(spl_sbir_dir - spl_analytic) < 1e-6,
      f"sbir={spl_sbir_dir:.4f} vs analitico={spl_analytic:.4f} dBSPL (f={f0:.0f} Hz, r={r:.2f} m)")


# ---------------------------------------------------------------------------
print("\nC5  guard: modal+SBIR sin f_schroeder -> error explícito")
try:
    cr.composed_response(act, rcv, freq, modal_result=modal, walls=walls)
    check("C5 lanza ValueError si falta f_schroeder", False, "no lanzó")
except ValueError:
    check("C5 lanza ValueError si falta f_schroeder", True, "")


print()
print("=" * 68)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 68)
raise SystemExit(1 if _FAIL else 0)
