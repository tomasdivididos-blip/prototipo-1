# -*- coding: utf-8 -*-
"""Sensibilidad del diagnostico de corregibilidad EQ al damping xi (C13/C21, nivel #4).

El veredicto depende de xi_n (Q de los modos -> profundidad/ancho de los nulos).
Sin Z(omega) medida (D5b), xi tiene incertidumbre irreducible (RT60 estimado,
alpha de catalogo). Este bench mide si las metricas ESCALARES robustas
(improvement_flat, fom_espacial) aguantan esa incertidumbre.

Tres ejes:
  - NIVEL: barrer xi x {0.7, 1.0, 1.5} (~ +-40% en RT60, la incertidumbre D5b).
  - FORMA: xi uniforme (escalar) vs xi Sabine per-modo (f-dependiente: graves mas
    amortiguados). A36 (per-cara) se enchufa igual como array xi (mismo shape).
"""
import numpy as np
import modal_metrics as mm
from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import SourceArray, OmniSource

SRC = (0.6, 0.5, 0.5)
RT60 = 0.4          # s, sala chica de escucha


def setup():
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=3.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=40)
    info = mesh_info(nodes, tets)
    keep = freqs <= max_solver_frequency(info["h_max"])
    loc = FieldEvaluator(nodes, tets)
    arr = SourceArray([OmniSource(SRC, sensitivity_dB=90.0)])
    grid = mm.default_receiver_grid(nodes, nx=5, ny=5)
    fa = np.linspace(20.0, 110.0, 400)
    return loc, freqs[keep], phis[:, keep], arr, grid, fa


def diag(loc, fr, ph, arr, grid, fa, xi):
    H_real, H_env = mm.forced_response_with_envelope(loc, fr, ph, arr, grid, fa, damping=xi)
    return mm.eq_correctability(H_real, fa, H_env=H_env)


if __name__ == "__main__":
    print("== Sensibilidad de eq_correctability al damping xi (sala 5x4x3, npm=3) ==\n")
    loc, fr, ph, arr, grid, fa = setup()
    xi_sabine = 1.1 / (fr * RT60)                  # per-modo Sabine (f-dependiente)
    xi_unif = float(xi_sabine.mean())              # escalar equivalente

    print(f"{'caso':>26} {'improv':>8} {'fom_esp':>8} {'grado_x':>8}")
    rows = {}
    # forma: uniforme vs per-modo (a nivel base)
    for lbl, xi in [("xi uniforme (escalar)", xi_unif),
                    ("xi Sabine per-modo", xi_sabine)]:
        r = diag(loc, fr, ph, arr, grid, fa, xi)
        rows[lbl] = r
        print(f"{lbl:>26} {r.improvement_flat:>8.2f} {r.fom_espacial:>8.2f} {r.frac_correctable:>8.3f}")
    # nivel: barrer xi per-modo x factor (incertidumbre D5b)
    print()
    sweep = {}
    for k in (0.7, 1.0, 1.5):
        r = diag(loc, fr, ph, arr, grid, fa, xi_sabine * k)
        sweep[k] = r
        print(f"{'xi x ' + str(k) + ' (RT60 ' + ('+' if k<1 else '') + str(round((1/k-1)*100)) + '%)':>26} "
              f"{r.improvement_flat:>8.2f} {r.fom_espacial:>8.2f} {r.frac_correctable:>8.3f}")

    # --- analisis de robustez ---
    impr = [sweep[k].improvement_flat for k in (0.7, 1.0, 1.5)]
    fesp = [sweep[k].fom_espacial for k in (0.7, 1.0, 1.5)]
    print(f"\n  improvement_flat: rango {min(impr):.2f}-{max(impr):.2f} dB "
          f"(span {max(impr)-min(impr):.2f} dB sobre +-40% de xi)")
    print(f"  fom_espacial:     rango {min(fesp):.2f}-{max(fesp):.2f} dB "
          f"(span {max(fesp)-min(fesp):.2f} dB)")
    d_forma = abs(rows["xi uniforme (escalar)"].fom_espacial
                  - rows["xi Sabine per-modo"].fom_espacial)
    print(f"  forma (unif vs per-modo): dif fom_espacial = {d_forma:.2f} dB")

    # robusto si el span de las escalares bajo +-40% de xi es chico (< ~1.5 dB)
    assert max(impr) - min(impr) < 1.5, impr
    assert max(fesp) - min(fesp) < 1.5, fesp
    print("\nOK: las escalares robustas aguantan la incertidumbre D5b de xi (span < 1.5 dB).")
    print("    (A36 per-cara se enchufa como array xi; efecto de FORMA acotado arriba.)")
