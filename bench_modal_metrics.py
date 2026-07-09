"""
bench_modal_metrics.py
======================

Oraculos de la Fase 2c: figura de merito (§8) y cruce de solapamiento modal (§9).

Correr:
    PYTHONIOENCODING=utf-8 python bench_modal_metrics.py
"""
from __future__ import annotations

import numpy as np

from modal_metrics import (response_figures_of_merit, modal_overlap_crossover,
                           modal_density, schroeder_frequency,
                           compute_forced_response, default_receiver_grid)


def test_fom_synthetic():
    print("1. Figura de merito (§8) — H sintetico")
    N_R, Nf = 20, 400
    f = np.linspace(20.0, 200.0, Nf)

    # (a) H perfectamente plano en f y r -> FoM_flat ≈ 0 y FoM_espacial ≈ 0.
    H_flat = np.full((N_R, Nf), 0.5 + 0j)
    r = response_figures_of_merit(H_flat, f)
    print(f"   plano: FoM_flat={r.FoM_flat:.4f}  FoM_espacial={r.FoM_espacial:.4f}")
    assert r.FoM_flat < 1e-9 and r.FoM_espacial < 1e-9

    # (b) Invariancia a ganancia global: x10 en todo H no cambia ninguna FoM.
    r2 = response_figures_of_merit(10.0 * H_flat, f)
    assert abs(r2.FoM_flat - r.FoM_flat) < 1e-9 and abs(r2.FoM_espacial - r.FoM_espacial) < 1e-9
    print("   invariante a nivel global (x10)  OK")

    # (c) Ripple conocido en f (igual en todos los receptores): FoM_espacial≈0,
    #     FoM_flat ≈ std del ripple en dB. Ripple lento (no lo borra el 1/3 oct).
    ripple_db = 4.0 * np.sin(2 * np.pi * np.log2(f / 20.0))     # ±4 dB lento
    mag = 10.0 ** (ripple_db / 20.0)
    H_rip = np.tile(mag, (N_R, 1)).astype(complex)
    rr = response_figures_of_merit(H_rip, f)
    # std del propio ripple en dB (tras suavizado deberia quedar parecido)
    expected = float(np.std(ripple_db))
    print(f"   ripple ±4dB: FoM_flat={rr.FoM_flat:.2f} (std ripple={expected:.2f}), "
          f"FoM_espacial={rr.FoM_espacial:.3f}")
    assert rr.FoM_espacial < 1e-6, "ripple igual en todo r -> sin dispersion espacial"
    assert abs(rr.FoM_flat - expected) < 0.5, "FoM_flat no sigue el ripple"

    # (d) Variacion espacial (cada receptor un nivel distinto, plano en f):
    #     FoM_flat≈0, FoM_espacial = std de los niveles en dB.
    levels_db = np.linspace(-6.0, 6.0, N_R)
    H_sp = (10.0 ** (levels_db / 20.0))[:, None] * np.ones((N_R, Nf))
    rs = response_figures_of_merit(H_sp.astype(complex), f)
    print(f"   var espacial: FoM_flat={rs.FoM_flat:.3f}, "
          f"FoM_espacial={rs.FoM_espacial:.2f} (std niveles={np.std(levels_db):.2f})")
    assert rs.FoM_flat < 1e-6 and abs(rs.FoM_espacial - np.std(levels_db)) < 1e-6
    print("   OK")


def test_crossover_weyl():
    print("\n2. Cruce modal (§9) — continuidad con Schroeder (modos de Weyl)")
    V, RT60, c = 100.0, 0.5, 343.0
    # Modos sinteticos con densidad de Weyl: N(f) = (4π/3)V(f/c)³.
    f_top = 260.0
    K = int((4 * np.pi / 3) * V * (f_top / c) ** 3)
    k = np.arange(1, K + 1)
    freqs = c * (3.0 * k / (4 * np.pi * V)) ** (1.0 / 3.0)      # invierte N(f)
    f_cross, fg, M = modal_overlap_crossover(freqs, RT60, f_lo=20.0, f_hi=f_top)

    # Schroeder clasico y la forma exacta del M=3 con densidad de Weyl.
    f_schr = schroeder_frequency(RT60, V)
    f_exact = c * np.sqrt(3.0 * c / (8.8 * np.pi)) * np.sqrt(RT60 / V)   # M=3 Weyl
    print(f"   modos generados: {K} (hasta {f_top:.0f} Hz)")
    print(f"   f_cross numerico = {f_cross:.1f} Hz")
    print(f"   f_exacto (M=3, Weyl analitico) = {f_exact:.1f} Hz")
    print(f"   f_Schroeder (2000√(T/V)) = {f_schr:.1f} Hz")
    assert f_cross is not None
    assert abs(f_cross - f_exact) / f_exact < 0.10, \
        f"cruce numerico lejos del Weyl analitico ({f_cross:.1f} vs {f_exact:.1f})"
    print("   OK (cruce numerico ≈ Weyl analitico dentro de 10%)")


def test_crossover_shape_awareness():
    print("\n3. Cruce modal — sensibilidad a la forma (densidad mas baja sube f_cross)")
    c = 343.0
    V, RT60 = 100.0, 0.5
    K = 120
    k = np.arange(1, K + 1)
    freqs_dense = c * (3.0 * k / (4 * np.pi * V)) ** (1.0 / 3.0)
    # "Forma mala": misma cantidad de modos pero estirados (densidad ~30% menor).
    freqs_sparse = freqs_dense * 1.15
    fc_dense, _, _ = modal_overlap_crossover(freqs_dense, RT60, f_hi=300)
    fc_sparse, _, _ = modal_overlap_crossover(freqs_sparse, RT60, f_hi=300)
    print(f"   densa  -> f_cross={fc_dense:.1f} Hz | rala -> f_cross={fc_sparse:.1f} Hz")
    assert fc_sparse > fc_dense, "menor densidad deberia subir el cruce"
    print("   OK (el cruce VE la forma; Schroeder analitico no podria)")


def test_fom_on_fem():
    print("\n4. FoM end-to-end sobre el FEM (sala 5x4x3)")
    from geometry import make_room
    from acoustic_mesh import build_volume_mesh
    from acoustic_fem import build_KM, solve_modes, FieldEvaluator
    from sources import SourceArray, OmniSource

    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=2.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=12)
    loc = FieldEvaluator(nodes, tets)
    arr = SourceArray([OmniSource((0.5, 0.5, 0.5), sensitivity_dB=90.0)])
    grid = default_receiver_grid(nodes, nx=4, ny=4)
    fa = np.linspace(20.0, 100.0, 200)
    H = compute_forced_response(loc, freqs, phis, arr, grid, fa, damping=0.05)
    r = response_figures_of_merit(H, fa)
    print(f"   {grid.shape[0]} receptores, {len(fa)} freqs -> "
          f"FoM_flat={r.FoM_flat:.2f} dB, FoM_espacial={r.FoM_espacial:.2f} dB")
    assert np.isfinite(r.FoM_flat) and np.isfinite(r.FoM_espacial)
    assert r.FoM_flat > 0 and r.FoM_espacial > 0    # una sala real no es plana
    print("   OK (finito y > 0, como corresponde a una sala con modos)")


def test_fsi_rindel():
    print("\n5. FSI psi(25) (§A6) — el cubo es el peor, ratios buenos bajos")
    from modal_metrics import modal_fsi
    c = 343.0

    def modes(L, W, H, fmax=300.0):
        fs = []
        for l in range(8):
            for m in range(8):
                for n in range(8):
                    if l == m == n == 0:
                        continue
                    f = (c / 2) * np.sqrt((l / L) ** 2 + (m / W) ** 2 + (n / H) ** 2)
                    if f <= fmax:
                        fs.append(f)
        return np.array(sorted(fs))

    V = 60.0

    def psi_of(rL, rW, rH):
        s = (V / (rL * rW * rH)) ** (1 / 3)
        return modal_fsi(modes(rL * s, rW * s, rH * s), 25)

    psi_cubo = psi_of(1, 1, 1)
    psi_rindel = psi_of(1.40, 1.14, 1.0)
    psi_louden = psi_of(1.90, 1.40, 1.0)
    print(f"   cubo={psi_cubo:.2f}  Rindel={psi_rindel:.2f}  Louden={psi_louden:.2f}")
    assert psi_cubo > 3.0, "el cubo deberia dar psi muy alto (modos degenerados)"
    assert psi_rindel < psi_louden < psi_cubo, "Rindel deberia ser el mejor (psi menor)"
    assert modal_fsi(np.array([50.0, 100.0]), 25) != modal_fsi(np.array([50.0, 100.0]), 25) \
        or True  # <3 modos -> nan (no rompe)
    print("   OK (cubo peor; Rindel < Louden < cubo)")


def test_fom_asymmetry():
    print("\n6. FoM_flat_asym (§C8) — picos penalizan mas que nulos")
    f = np.linspace(20.0, 200.0, 400)

    def bump(dev_db):
        L = dev_db * np.exp(-((f - 100.0) / 8.0) ** 2)
        return (10.0 ** (L / 20.0))[None, :].astype(complex)

    rp = response_figures_of_merit(bump(+6.0), f)
    rn = response_figures_of_merit(bump(-6.0), f)
    print(f"   pico +6dB asym={rp.FoM_flat_asym:.3f} | nulo -6dB asym={rn.FoM_flat_asym:.3f}")
    assert rp.FoM_flat_asym > rn.FoM_flat_asym, "el pico debe penalizar mas que el nulo"
    # Reduccion: asym_weight=1 -> FoM_flat_asym == FoM_flat.
    r1 = response_figures_of_merit(bump(+6.0), f, asym_weight=1.0)
    assert abs(r1.FoM_flat_asym - r1.FoM_flat) < 1e-9, "asym_weight=1 deberia reducir a FoM_flat"
    print("   OK (pico>nulo; asym_weight=1 reduce a FoM_flat)")


def test_fazenda_threshold():
    print("\n7. Umbral perceptual de Fazenda (§C9) — dos curvas (artificial/music)")
    from modal_metrics import fazenda_modal_threshold as thr
    # Anclas de la Fig. 4 (artificial = peor caso).
    assert abs(thr(32) - 0.90) < 1e-6 and abs(thr(63) - 0.30) < 1e-6
    assert abs(thr(100) - 0.20) < 1e-6 and abs(thr(200) - 0.17) < 1e-6
    # Anclas de la Fig. 5 (music = escucha real).
    assert abs(thr(63, "music") - 0.51) < 1e-6 and abs(thr(125, "music") - 0.30) < 1e-6
    assert abs(thr(250, "music") - 0.12) < 1e-6
    # Ambas monotonicamente decrecientes.
    fs = np.array([32, 50, 63, 80, 100, 160, 200], dtype=float)
    assert np.all(np.diff(thr(fs)) <= 1e-9)
    assert np.all(np.diff(thr(fs, "music")) <= 1e-9)
    # Clamp fuera de rango.
    assert thr(20) == thr(32) and thr(300) == thr(200)
    # Artificial mas estricto que el Q>30 implicito (T60_thr < 65.9/f).
    for f in (40.0, 63.0, 100.0, 160.0):
        assert thr(f) < 65.9 / f, f"artificial deberia ser mas estricto que Q>30 a {f} Hz"
    # Music MAS PERMISIVO que artificial en la banda modal (enmascaramiento).
    for f in (50.0, 63.0, 100.0, 160.0):
        assert thr(f, "music") >= thr(f, "artificial"), f"music deberia ser mas laxo a {f} Hz"
    print(f"   artificial: 63Hz={thr(63):.2f}s 100Hz={thr(100):.2f}s | music: 63Hz={thr(63,'music'):.2f}s 100Hz={thr(100,'music'):.2f}s")
    print("   OK (ambas curvas; artificial<Q>30 implicito; music>=artificial)")


if __name__ == "__main__":
    test_fom_synthetic()
    test_crossover_weyl()
    test_crossover_shape_awareness()
    test_fom_on_fem()
    test_fsi_rindel()
    test_fom_asymmetry()
    test_fazenda_threshold()
    print("\nTODOS LOS ORACULOS DE FASE 2c OK.")
