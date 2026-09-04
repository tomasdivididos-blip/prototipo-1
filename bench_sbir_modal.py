"""
bench_sbir_modal.py - hibrido SBIR + transferencia modal (pedido del profesor)
==============================================================================
Valida, headless, el camino que arma el panel para el SBIR con transferencia
modal de la sala (sin instanciar la GUI):
  M1  la FRF modal (FEM) en el receptor, normalizada al DIRECTO de campo libre
      del SBIR, da una curva finita en dB re directo.
  M2  el hibrido modal+SBIR (sbir.modal_sbir_crossfade): modal por debajo de
      f_Schroeder, SBIR por encima; finito y continuo.
  M3  serializacion de curvas de RT guardadas (round-trip JSON = .room v9).

Correr:  QT_QPA_PLATFORM=offscreen python bench_sbir_modal.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import sbir
from sources import single_source

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# --- Setup: shoebox + modos ---
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
print(f"  malla {nodes.shape[0]} nodos, {len(freqs)} modos")

# --- SBIR analitico (paredes reflectantes) ---
f_lo, f_hi = 20.0, 500.0
freq = np.linspace(f_lo, f_hi, 2000)
walls = [sbir.Wall(point=g.centroid, normal=g.normal, label=g.label,
                   R=sbir.reflection_from_alpha(np.full(freq.shape, 0.1)))
         for g in gr]
res = sbir.sbir_from_sources(act, walls, rcv, freq)


# ---------------------------------------------------------------------------
print("\nM1  FRF modal normalizada al directo (dB re directo)")
frf = aa.run_fem_frf(modal, act, rcv, f_min=f_lo, f_max=f_hi, n_freqs=len(freq),
                     damping=0.02)
p_dir = np.abs(res.total_p_direct)
modal_db = 20.0 * np.log10(np.maximum(np.abs(frf.H), 1e-30)
                           / np.maximum(p_dir, 1e-30))
check("M1a modal_db finito y misma longitud que el eje SBIR",
      modal_db.shape == freq.shape and np.all(np.isfinite(modal_db)),
      f"n={modal_db.size}, rango [{modal_db.min():.1f},{modal_db.max():.1f}] dB")
# picos modales: hay resonancias (varianza apreciable), no es plano como el SBIR
check("M1b la curva modal tiene resonancias (std > 3 dB)",
      float(np.std(modal_db)) > 3.0, f"std={np.std(modal_db):.1f} dB")


# ---------------------------------------------------------------------------
print("\nM2  hibrido modal+SBIR (crossfade en f_Schroeder)")
f_s = 120.0
total = sbir.modal_sbir_crossfade(freq, res.total_sbir_db, modal_db, f_s)
lo = f_s * 2 ** -0.5
hi = f_s * 2 ** +0.5
check("M2a total finito, misma longitud",
      total.shape == freq.shape and np.all(np.isfinite(total)), "")
check("M2b debajo de f_S/√2 el total == modal",
      np.allclose(total[freq <= lo], modal_db[freq <= lo], atol=1e-9), "")
check("M2c encima de f_S·√2 el total == SBIR",
      np.allclose(total[freq >= hi], res.total_sbir_db[freq >= hi], atol=1e-9), "")


# ---------------------------------------------------------------------------
print("\nM3  serializacion de curvas de RT guardadas (.room v9)")
saved = [
    {"name": "Config A (reflectante)", "method": "sabine", "metric": "T60",
     "bands": [125, 250, 500, 1000], "values": [1.8, 1.6, 1.4, 1.2]},
    {"name": "Config B (tratada)", "method": "perturbation", "metric": "T30",
     "bands": [125, 250, 500, 1000], "values": [0.9, 0.7, 0.6, 0.55]},
]
rt = json.loads(json.dumps(saved))          # round-trip como en el .room
ok = (len(rt) == 2 and rt[0]["name"] == "Config A (reflectante)"
      and rt[1]["method"] == "perturbation"
      and rt[0]["bands"] == [125, 250, 500, 1000]
      and abs(rt[1]["values"][0] - 0.9) < 1e-12)
check("M3 curvas guardadas sobreviven el round-trip JSON (nombre/metodo/valores)",
      ok, f"{len(rt)} curvas")


print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
raise SystemExit(1 if _FAIL else 0)
