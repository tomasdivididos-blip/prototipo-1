# -*- coding: utf-8 -*-
"""Separar fuente de sala + peor caso L+R (C13/C21, nivel #5).

Demuestra:
  (1) El diagnostico de SALA (flat_source=True, Q plano) es INVARIANTE a la fase
      de fuente (delay/polaridad). La sala es la sala: un delay/polaridad de fuente
      es all-pass de la FUENTE, corregible desde el drive, no un problema de sala.
  (2) La interferencia L+R (one-toothed comb de Toole) SI cambia la respuesta
      con-fuente. Con R en contrafase, L+R cancela en el centro -> peor que L o R
      solos. Es un problema de SETUP (fase relativa de canales), distinguible de la
      no-corregibilidad de SALA.
  (3) El peor caso sobre {L, R, L+R} lo da L+R cuando hay cancelacion entre canales.
"""
import numpy as np
import modal_metrics as mm
from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import SourceArray, OmniSource, synth_response

# make_room centra en el origen: x in [-2.5,2.5], y in [-2,2], z in [0,3].
L_POS = (-1.0, -0.8, 1.2)
R_POS = (-1.0, +0.8, 1.2)
DAMP = 0.04


def setup():
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=3.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=40)
    info = mesh_info(nodes, tets)
    keep = freqs <= max_solver_frequency(info["h_max"])
    loc = FieldEvaluator(nodes, tets)
    grid = mm.default_receiver_grid(nodes, nx=5, ny=5)
    fa = np.linspace(20.0, 110.0, 400)
    return loc, freqs[keep], phis[:, keep], grid, fa


def diag(loc, fr, ph, arr, grid, fa, flat):
    H, He = mm.forced_response_with_envelope(loc, fr, ph, arr, grid, fa,
                                             damping=DAMP, flat_source=flat)
    return mm.eq_correctability(H, fa, H_env=He)


if __name__ == "__main__":
    print("== Separar fuente/sala + peor caso L+R (sala 5x4x3, npm=3) ==\n")
    loc, fr, ph, grid, fa = setup()
    fpts = np.linspace(1.0, 300.0, 1200)

    L = OmniSource(L_POS, sensitivity_dB=90.0, label="L")
    R = OmniSource(R_POS, sensitivity_dB=90.0, label="R")
    R_inv = OmniSource(R_POS, sensitivity_dB=90.0, label="R-inv",
                       response=synth_response("polarity", fpts))

    arr_A = SourceArray([L, R])            # L+R en fase
    arr_B = SourceArray([L, R_inv])        # L+R en contrafase (one-toothed comb)
    arr_L = SourceArray([L])
    arr_R = SourceArray([R])

    # (1) SALA SOLA (flat): invariante a la fase de fuente
    sa = diag(loc, fr, ph, arr_A, grid, fa, flat=True)
    sb = diag(loc, fr, ph, arr_B, grid, fa, flat=True)
    print("(1) SALA SOLA (flat_source=True) -- debe ser invariante a polaridad:")
    print(f"    A (L+R fase)     : improv={sa.improvement_flat:.2f}  fom_esp={sa.fom_espacial:.2f}  grado={sa.frac_correctable:.3f}")
    print(f"    B (L+R contrafase): improv={sb.improvement_flat:.2f}  fom_esp={sb.fom_espacial:.2f}  grado={sb.frac_correctable:.3f}")
    assert abs(sa.improvement_flat - sb.improvement_flat) < 1e-9
    assert abs(sa.fom_espacial - sb.fom_espacial) < 1e-9
    print("    -> identicas: la SALA no cambia con la fase de fuente. [OK]\n")

    # (2) CON FUENTE: la interferencia L+R cambia con la polaridad
    ca = diag(loc, fr, ph, arr_A, grid, fa, flat=False)
    cb = diag(loc, fr, ph, arr_B, grid, fa, flat=False)
    print("(2) CON FUENTE (flat_source=False) -- la interferencia L+R si cambia:")
    print(f"    A (L+R fase)     : improv={ca.improvement_flat:.2f}  fom_esp={ca.fom_espacial:.2f}  grado={ca.frac_correctable:.3f}")
    print(f"    B (L+R contrafase): improv={cb.improvement_flat:.2f}  fom_esp={cb.fom_espacial:.2f}  grado={cb.frac_correctable:.3f}")
    assert cb.fom_espacial > ca.fom_espacial + 0.2     # la contrafase empeora el campo
    print("    -> B (contrafase) peor: es un problema de SETUP de fuente, no de sala. [OK]\n")

    # (3) Peor caso sobre {L, R, L+R} para el caso B
    cl = diag(loc, fr, ph, arr_L, grid, fa, flat=False)
    cr = diag(loc, fr, ph, arr_R, grid, fa, flat=False)
    print("(3) Peor caso sobre subconjuntos (caso B, contrafase):")
    print(f"    L solo : fom_esp={cl.fom_espacial:.2f}  grado={cl.frac_correctable:.3f}")
    print(f"    R solo : fom_esp={cr.fom_espacial:.2f}  grado={cr.frac_correctable:.3f}")
    print(f"    L+R    : fom_esp={cb.fom_espacial:.2f}  grado={cb.frac_correctable:.3f}")
    worst = max([cl.fom_espacial, cr.fom_espacial, cb.fom_espacial])
    assert worst == cb.fom_espacial                    # L+R contrafase es el peor caso
    print("    -> peor caso = L+R contrafase (one-toothed comb). [OK]")

    print("\nTODOS OK")
