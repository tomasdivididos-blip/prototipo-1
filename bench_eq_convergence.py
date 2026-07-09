# -*- coding: utf-8 -*-
"""Convergencia de malla de eq_correctability (C13/C21, nivel #3).

Corre el FEM de la sala 5x4x3 a n_per_meter = 2/3/4 y verifica:
  P1 (malla): `eq_diagnosis_mesh_ok` marca npm=2 insuficiente, npm>=3 OK.
  P2 (grado): el GRADO continuo de corregibilidad converge con npm>=3 (el flag
              binario viejo era fragil cerca del umbral: 0.147/0.017/0.003).
  Fisica:     cancel_depth y spread convergen (npm3-npm4 << npm2-npm4).
  Escalares:  improvement_flat y fom_espacial estables en las 3 mallas.

Hallazgo del test (documentado): la malla gruesa "redondea" los nodos modales ->
subestima cancel_depth (~1.6 dB en npm=2) -> la sala parece mas corregible de lo
que es. El diagnostico exige npm>=3 (ppw~15, mas que el ppw=6 del solver).
"""
import numpy as np
import modal_metrics as mm
from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import SourceArray, OmniSource

SRC = (0.6, 0.5, 0.5)
FA = np.linspace(20.0, 60.0, 300)        # banda comun valida en npm=2
DAMP = 0.05


def run(npm):
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=npm)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=40)
    info = mesh_info(nodes, tets)
    keep = freqs <= max_solver_frequency(info["h_max"])     # modos validos (estilo panel)
    loc = FieldEvaluator(nodes, tets)
    arr = SourceArray([OmniSource(SRC, sensitivity_dB=90.0)])
    grid = mm.default_receiver_grid(nodes, nx=4, ny=4)
    H_real, H_env = mm.forced_response_with_envelope(
        loc, freqs[keep], phis[:, keep], arr, grid, FA, damping=DAMP)
    res = mm.eq_correctability(H_real, FA, H_env=H_env)
    return {
        "npm": npm, "nodes": len(nodes), "h_max": info["h_max"],
        "mesh_ok": mm.eq_diagnosis_mesh_ok(info["h_max"], float(FA[-1])),
        "frac": res.frac_correctable, "improv": res.improvement_flat,
        "fom_esp": res.fom_espacial, "cancel_mean": float(res.cancel_depth.mean()),
        "grade": res.correctability, "cancel": res.cancel_depth, "spread": res.spread,
    }


def rms(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


if __name__ == "__main__":
    print("== Convergencia de eq_correctability (sala 5x4x3, banda 20-60 Hz) ==\n")
    R = [run(npm) for npm in (2.0, 3.0, 4.0)]
    print(f"{'npm':>4} {'nodos':>7} {'h_max':>7} {'mesh_ok':>8} {'grado_x':>8} "
          f"{'improv':>7} {'fom_esp':>8} {'cancel_x':>9}")
    for r in R:
        print(f"{r['npm']:>4.0f} {r['nodes']:>7} {r['h_max']:>7.3f} {str(r['mesh_ok']):>8} "
              f"{r['frac']:>8.3f} {r['improv']:>7.2f} {r['fom_esp']:>8.2f} {r['cancel_mean']:>9.2f}")

    g34 = rms(R[1]['grade'], R[2]['grade'])
    g24 = rms(R[0]['grade'], R[2]['grade'])
    c34 = rms(R[1]['cancel'], R[2]['cancel'])
    c24 = rms(R[0]['cancel'], R[2]['cancel'])
    print(f"\n  grado correctability  RMS: npm2-npm4={g24:.3f}  npm3-npm4={g34:.3f}")
    print(f"  cancel_depth [dB]     RMS: npm2-npm4={c24:.2f}  npm3-npm4={c34:.2f}")

    # --- P1: el helper distingue malla suficiente de insuficiente ---
    assert R[0]['mesh_ok'] is False, "npm=2 deberia marcarse insuficiente"
    assert R[1]['mesh_ok'] and R[2]['mesh_ok'], "npm>=3 deberia marcarse suficiente"
    # --- P2/fisica: npm3 ya esta cerca de npm4 (converge); npm2 lejos ---
    assert g34 < 0.5 * g24, (g34, g24)          # el grado converge con npm>=3
    assert g34 < 0.1, g34                         # estable en escala 0-1
    assert c34 < c24, (c34, c24)                  # cancel_depth converge
    # --- escalares robustos estables en las 3 mallas ---
    improvs = [r['improv'] for r in R]
    fomesps = [r['fom_esp'] for r in R]
    assert max(improvs) - min(improvs) < 0.5, improvs
    assert max(fomesps) - min(fomesps) < 0.5, fomesps
    print("\nOK: P1 (npm>=3 exigido), P2 (grado converge), escalares estables.")
