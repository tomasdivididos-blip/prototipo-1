# -*- coding: utf-8 -*-
"""Oraculos de eq_correctability (C13/C21, nivel #1: loop cerrado).

Construye H sinteticos (sin FEM) para validar la matematica pura:
  O1 modo aislado      -> cancel_depth = 0 (|Sigma| = Sigma|.|), corregible.
  O2 cancelacion       -> nulo profundo entre modos -> cancel_depth grande, no corregible.
  O3 posicional        -> notch que se mueve por receptor -> spread alto, no corregible.
  O4 invariancia esp.  -> EQ global (ganancia comun) NO toca la varianza espacial (~0).
  O5 cierre del loop   -> realce consistente -> EQ aplana FoM_flat; FoM_espacial invariante.
  O6 mixto             -> realce corregible + notch posicional -> frac intermedio, bandas OK.
"""
import numpy as np
import modal_metrics as mm

F = np.linspace(20.0, 200.0, 600)


def modal_term(f, fn, r, xi=0.03):
    """Termino modal Lorentziano en f (forma; el prefactor fisico no cambia el test)."""
    return r / (fn ** 2 - f ** 2 + 2j * xi * fn * f)


def test_o1_isolated_mode():
    t = modal_term(F, 55.0, 1.0)
    H = t[None, :]
    Henv = np.abs(t)[None, :]
    res = mm.eq_correctability(H, F, H_env=Henv)
    # un solo termino: |Sigma| == Sigma|.| -> cancelacion identicamente nula.
    assert res.cancel_depth.max() < 1e-9, res.cancel_depth.max()
    print(f"  [O1] modo aislado: max cancel_depth = {res.cancel_depth.max():.2e} dB (=0)")


def test_o2_cancellation():
    # Dos modos de residuo positivo -> antiresonancia profunda entre ellos.
    t1 = modal_term(F, 50.0, 1.0)
    t2 = modal_term(F, 95.0, 1.0)
    H = (t1 + t2)[None, :]
    Henv = (np.abs(t1) + np.abs(t2))[None, :]
    res = mm.eq_correctability(H, F, H_env=Henv)
    fc = F[np.argmax(res.cancel_depth)]
    assert res.cancel_depth.max() > 6.0, res.cancel_depth.max()
    assert 50.0 < fc < 95.0, fc        # el nulo cae entre los dos modos
    # la banda del nulo debe quedar marcada NO corregible (verdict==0)
    band = (F > 60) & (F < 85)
    assert (res.verdict[band] == 0).any()
    print(f"  [O2] cancelacion: max cancel_depth = {res.cancel_depth.max():.1f} dB @ {fc:.0f} Hz "
          f"-> banda no corregible")


def test_o3_positional():
    # Nivel global plano, pero cada receptor con un notch en distinta f (interferencia
    # posicional, tipo SBIR). Sin estructura modal -> H_env=None -> cancel_depth=0.
    centers = [50.0, 75.0, 100.0, 125.0, 150.0]
    H = np.ones((len(centers), F.size), dtype=complex)
    for r, fcr in enumerate(centers):
        H[r] = 1.0 - 0.95 * np.exp(-((F - fcr) / (fcr / 7.0)) ** 2)   # Q cte: sobrevive al 1/3-oct
    res = mm.eq_correctability(H, F, H_env=None)
    assert res.cancel_depth.max() < 1e-9          # no hay senal de cancelacion modal
    assert res.spread.max() > 3.0                  # los notches dispersan los asientos
    assert res.fom_espacial > 1.0                  # varianza espacial irreducible significativa
    assert res.improvement_flat < 1.0             # el EQ global casi no ayuda (es posicional)
    for fcr in centers:                            # cada banda de notch -> grado bajo
        band = np.abs(F - fcr) < fcr / 12.0
        assert res.correctability[band].mean() < 0.5, (fcr, res.correctability[band].mean())
    print(f"  [O3] posicional: max spread = {res.spread.max():.1f} dB, "
          f"FoM_espacial = {res.fom_espacial:.2f} dB, EQ global mejora solo "
          f"{res.improvement_flat:.2f} dB -> bandas de notch no corregibles")


def test_o4_spatial_invariance():
    # Cualquier H multi-receptor: el EQ global del metodo es ganancia comun ->
    # la varianza espacial (sin suavizar) debe ser invariante a precision maquina.
    rng = np.random.default_rng(0)
    H = (rng.standard_normal((6, F.size)) + 1j * rng.standard_normal((6, F.size)))
    res = mm.eq_correctability(H, F, H_env=None)
    assert res.espacial_invariant_err < 1e-9, res.espacial_invariant_err
    print(f"  [O4] invariancia espacial del EQ global: err = {res.espacial_invariant_err:.2e} dB (=0)")


def test_o5_loop_closed():
    # Realce de banda consistente en todos los asientos (corregible por EQ global).
    boost = np.where((F >= 70) & (F <= 95), 10.0 ** (6.0 / 20.0), 1.0)
    H = np.tile(boost, (5, 1)).astype(complex)
    res = mm.eq_correctability(H, F, H_env=None)
    assert res.improvement_flat > 0.5, res.improvement_flat     # el EQ aplana la media
    assert res.fom_flat_after < res.fom_flat_before
    assert res.fom_espacial < 1e-6, res.fom_espacial            # todos iguales -> sin varianza
    assert res.frac_correctable > 0.95                          # realce, no nulo -> corregible
    print(f"  [O5] loop cerrado: FoM_flat {res.fom_flat_before:.2f} -> {res.fom_flat_after:.2f} dB "
          f"(mejora {res.improvement_flat:.2f}); FoM_espacial = {res.fom_espacial:.2e} dB")


def test_o6_mixed():
    # Realce consistente (corregible) + notch posicional (no). frac intermedio.
    N_R = 5
    boost = np.where((F >= 70) & (F <= 95), 10.0 ** (6.0 / 20.0), 1.0)
    H = np.tile(boost, (N_R, 1)).astype(complex)
    for r in range(N_R):
        fcr = 120.0 + 15.0 * r
        H[r] *= (1.0 - 0.95 * np.exp(-((F - fcr) / (fcr / 7.0)) ** 2))   # Q cte
    res = mm.eq_correctability(H, F, H_env=None)
    # la zona del realce (70-95) debe quedar mayormente corregible (grado alto)
    band_boost = (F >= 72) & (F <= 93)
    assert res.correctability[band_boost].mean() > 0.8
    # la zona de notches posicionales (120-185) grado bajo
    band_notch = (F >= 118) & (F <= 188)
    assert res.correctability[band_notch].mean() < 0.5
    print(f"  [O6] mixto: grado@realce = {res.correctability[band_boost].mean():.2f}, "
          f"grado@notch = {res.correctability[band_notch].mean():.2f}")


def test_o7_end_to_end_fem():
    # Sobre el FEM real: H_real de forced_response_with_envelope debe coincidir con
    # compute_forced_response (regresion del refactor _modal_terms), y la envolvente
    # debe acotar por arriba a |H_real| (desigualdad triangular |Sigma| <= Sigma|.|).
    from geometry import make_room
    from acoustic_mesh import build_volume_mesh
    from acoustic_fem import build_KM, solve_modes, FieldEvaluator
    from sources import SourceArray, OmniSource
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=2.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=12)
    loc = FieldEvaluator(nodes, tets)
    arr = SourceArray([OmniSource((0.6, 0.5, 0.5), sensitivity_dB=90.0)])
    grid = mm.default_receiver_grid(nodes, nx=4, ny=4)
    fa = np.linspace(20.0, 100.0, 200)
    H_ref = mm.compute_forced_response(loc, freqs, phis, arr, grid, fa, damping=0.05)
    H_real, H_env = mm.forced_response_with_envelope(loc, freqs, phis, arr, grid, fa, damping=0.05)
    assert np.allclose(H_real, H_ref, rtol=1e-12, atol=0), \
        np.abs(H_real - H_ref).max()                       # refactor no cambio nada
    assert (H_env + 1e-9 >= np.abs(H_real)).all()          # desigualdad triangular
    res = mm.eq_correctability(H_real, fa, H_env=H_env)
    assert 0.0 <= res.frac_correctable <= 1.0
    assert res.espacial_invariant_err < 1e-6               # invariancia tambien sobre FEM real
    print(f"  [O7] FEM 5x4x3: H_real==ref (refactor OK), H_env>=|H_real| (triangular OK); "
          f"frac corregible={res.frac_correctable:.2f}, EQ mejora {res.improvement_flat:.2f} dB, "
          f"FoM_espacial(irreducible)={res.fom_espacial:.2f} dB")


def _modal_H(freqs, xi, r, fa):
    """H y H_env (1 receptor) de la superposicion modal, en el eje fa."""
    w = 2 * np.pi * np.asarray(fa)
    wn = 2 * np.pi * np.asarray(freqs, float)
    r = np.asarray(r, float)
    den = wn[:, None] ** 2 - w[None, :] ** 2 + 2j * xi * wn[:, None] * w[None, :]
    terms = r[:, None] / den                       # (Nm, Nf)
    return terms.sum(0)[None, :], np.abs(terms).sum(0)[None, :]


def test_o8_proxy_overmarks_minphase():
    # 2 modos mismo signo: antiresonancia PROFUNDA (proxy la marca) pero MIN-PHASE
    # (corregible). El exacto (#2b) lo distingue -> el proxy cancel_depth sobre-marca.
    freqs, xi, r = [50.0, 90.0], 0.03, [1.0, 1.0]
    fa = np.linspace(20.0, 140.0, 700)
    H, Henv = _modal_H(freqs, xi, r, fa)
    res = mm.eq_correctability(H, fa, H_env=Henv)
    _z, n_rhp, ism = mm.modal_minphase_zeros(freqs, xi, r)
    assert res.cancel_depth.max() > 6.0, res.cancel_depth.max()   # proxy "ve cancelacion"
    assert ism and n_rhp == 0                                     # exacto: es min-phase
    print(f"  [O8] proxy SOBRE-marca: cancel_depth={res.cancel_depth.max():.1f} dB (marca nulo) "
          f"pero exacto n_rhp={n_rhp} -> MIN-PHASE (corregible)")


def test_o9_nonminphase_exact():
    # 5 modos alternados -> no-minima (ceros en RHP).
    _z, n_rhp, ism = mm.modal_minphase_zeros([40, 55, 70, 85, 100], 0.03,
                                             [1, -1, 1, -1, 1])
    assert (not ism) and n_rhp >= 1, n_rhp
    print(f"  [O9] 5 modos alternados: n_rhp={n_rhp} -> NO-minima (exige acustica)")


def test_o11_driving_point_minphase():
    # Driving point (fuente=receptor): residuos = phi_s² >= 0 -> SIEMPRE min-phase
    # (teorema de pasividad). Robustez de la factorizacion con muchos modos.
    rng = np.random.default_rng(7)
    for _ in range(5):
        f = np.sort(rng.uniform(30.0, 130.0, 9))
        r = rng.uniform(0.1, 2.0, 9) ** 2          # >= 0
        _z, n_rhp, ism = mm.modal_minphase_zeros(f, 0.03, r)
        assert ism and n_rhp == 0, n_rhp
    print("  [O11] driving-point (residuos >=0): min-phase en 5/5 (pasividad, np.roots estable)")


if __name__ == "__main__":
    print("== eq_correctability (C13/C21, niveles #1-#3 + #2b) ==")
    test_o1_isolated_mode()
    test_o2_cancellation()
    test_o3_positional()
    test_o4_spatial_invariance()
    test_o5_loop_closed()
    test_o6_mixed()
    test_o7_end_to_end_fem()
    test_o8_proxy_overmarks_minphase()
    test_o9_nonminphase_exact()
    test_o11_driving_point_minphase()
    print("\nTODOS OK")
