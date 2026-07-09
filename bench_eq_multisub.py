# -*- coding: utf-8 -*-
"""Validacion externa contra Welti & Devantier (2003) (C13/C21, nivel #6a).

Welti: multiples subwoofers en el PUNTO MEDIO de las paredes (midwall) reducen la
varianza espacial asiento-a-asiento (MSV) frente a 1 sub. Si nuestro `fom_espacial`
(la cota irreducible por EQ global) REPRODUCE esa tendencia, el diagnostico esta
validado contra un resultado publicado conocido -- sin necesitar mediciones propias.

NO es validacion cuantitativa contra medicion real (eso queda bloqueado por datos,
como D5b/C9); es validacion de CONSISTENCIA con la literatura.
"""
import numpy as np
import modal_metrics as mm
from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import SourceArray, OmniSource

DAMP = 0.04
# make_room centra en origen: x in [-2.5,2.5], y in [-2,2], z in [0,3].
SUB1_CORNER = [(-2.3, -1.8, 0.3)]                                   # 1 sub en esquina
SUB2_MID = [(-2.3, 0.0, 0.3), (2.3, 0.0, 0.3)]                      # 2 midwall (x)
SUB4_MID = SUB2_MID + [(0.0, -1.8, 0.3), (0.0, 1.8, 0.3)]          # 4 midwall


def setup():
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=3.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=40)
    info = mesh_info(nodes, tets)
    keep = freqs <= max_solver_frequency(info["h_max"])
    loc = FieldEvaluator(nodes, tets)
    grid = mm.default_receiver_grid(nodes, nx=5, ny=5)
    fa = np.linspace(20.0, 100.0, 400)
    return loc, freqs[keep], phis[:, keep], grid, fa


def fom_esp(loc, fr, ph, positions, grid, fa):
    arr = SourceArray([OmniSource(p, sensitivity_dB=90.0) for p in positions])
    H, He = mm.forced_response_with_envelope(loc, fr, ph, arr, grid, fa, damping=DAMP)
    return mm.eq_correctability(H, fa, H_env=He).fom_espacial


if __name__ == "__main__":
    print("== Validacion externa vs Welti 2003 (multi-sub baja varianza espacial) ==\n")
    loc, fr, ph, grid, fa = setup()
    f1 = fom_esp(loc, fr, ph, SUB1_CORNER, grid, fa)
    f2 = fom_esp(loc, fr, ph, SUB2_MID, grid, fa)
    f4 = fom_esp(loc, fr, ph, SUB4_MID, grid, fa)
    print(f"  1 sub  (esquina)      : fom_espacial = {f1:.2f} dB")
    print(f"  2 subs (midwall x)    : fom_espacial = {f2:.2f} dB")
    print(f"  4 subs (midwall x+y)  : fom_espacial = {f4:.2f} dB")
    print(f"\n  reduccion 1->2 subs: {f1 - f2:+.2f} dB | 1->4 subs: {f1 - f4:+.2f} dB")

    # Welti: multi-sub midwall reduce la varianza espacial frente a 1 sub.
    assert f2 < f1, (f1, f2)
    assert f4 < f1, (f1, f4)
    print("\nOK: el diagnostico REPRODUCE Welti (multi-sub midwall < 1 sub). [validacion externa]")
