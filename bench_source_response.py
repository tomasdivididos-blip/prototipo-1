"""
bench_source_response.py
========================

Smoke tests / oraculos de la Fase 0 del plan de fuentes (Q(f) + fase).

Decision de diseño (opcion 1): la respuesta de fuente es una ganancia compleja
g(f) RELATIVA al Q baseline.  Consecuencia clave usada aca:

    Para UNA sola fuente,  H_resp(f) = g(f) * H_base(f)  EXACTO,

porque la curva factoriza fuera de la suma modal:
    coupling[i,n] = Q(f_i)·phi_s[n] = q0·g(f_i)·phi_s[n] = g(f_i)·coupling_base[i,n].

Eso convierte las 5 curvas oraculo en un unico assert fuerte (allclose contra
g·H_base). Aparte se testea la cancelacion multi-fuente (§13.3 del doc tecnico).

Correr:
    PYTHONIOENCODING=utf-8 python bench_source_response.py
"""

from __future__ import annotations

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info
from acoustic_fem import build_KM, solve_modes, FieldEvaluator, frequency_response
from sources import SourceArray, OmniSource, synth_response


def _build_case():
    Lx, Ly, Lz = 5.0, 4.0, 3.0
    sv, st, _e, _n = make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=2.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=8)
    locator = FieldEvaluator(nodes, tets)
    info = mesh_info(nodes, tets)
    return nodes, tets, freqs, phis, locator, info


def main():
    print("[bench_source_response] caja 5x4x3, npm=2.0, 8 modos")
    nodes, tets, freqs, phis, locator, info = _build_case()
    print(f"  malla: {info['n_nodes']} nodos, {info['n_tets']} tets; "
          f"modos: {', '.join(f'{f:.1f}' for f in freqs)} Hz")

    receiver = (2.5, 2.0, 1.5)
    freq_axis = np.linspace(20.0, 120.0, 201)

    # --- Baseline: una fuente, sin curva (comportamiento historico) ---------
    src0 = OmniSource((0.5, 0.5, 0.5), sensitivity_dB=90.0, label="s0")
    arr = SourceArray([src0])
    H_base = frequency_response(locator, freqs, phis, arr, receiver, freq_axis)

    # ------------------------------------------------------------------------
    # 1-5. Para una sola fuente, H_resp == g(f) * H_base  (oraculo exacto)
    # ------------------------------------------------------------------------
    oracles = {
        "flat":     dict(),
        "delay":    dict(tau=2.0e-3),
        "polarity": dict(),
        "highpass": dict(fc=45.0),
        "peak":     dict(peak_freq=57.0, peak_db=6.0, peak_bw=6.0),
    }
    print("\n  Oraculo H_resp == g(f)*H_base (una fuente):")
    for kind, kw in oracles.items():
        resp = synth_response(kind, freq_pts=np.linspace(1.0, 200.0, 800), **kw)
        src0.response = resp
        H = frequency_response(locator, freqs, phis, arr, receiver, freq_axis)
        g = resp.gain_spectrum(freq_axis)
        expected = g * H_base
        ok = np.allclose(H, expected, rtol=1e-10, atol=1e-30)
        max_rel = np.max(np.abs(H - expected) / np.maximum(np.abs(expected), 1e-30))
        print(f"    {kind:9s}: allclose={ok}  max_rel={max_rel:.2e}")
        assert ok, f"[FALLA] oraculo {kind}: H_resp != g*H_base (max_rel={max_rel:.2e})"
    src0.response = None

    # 1b. Regresion explicita: 'flat' reproduce EXACTO la baseline.
    src0.response = synth_response("flat")
    H_flat = frequency_response(locator, freqs, phis, arr, receiver, freq_axis)
    assert np.allclose(H_flat, H_base, rtol=1e-10, atol=1e-30), \
        "[FALLA] regresion: flat no reproduce la FRF baseline"
    print("\n  Regresion: flat -> FRF identica a baseline (rtol<1e-10)  OK")
    src0.response = None

    # 2b. Delay: |H| invariante, pendiente de fase = -2πτ exacta.
    tau = 2.0e-3
    src0.response = synth_response("delay", tau=tau)
    H_d = frequency_response(locator, freqs, phis, arr, receiver, freq_axis)
    assert np.allclose(np.abs(H_d), np.abs(H_base), rtol=1e-10), \
        "[FALLA] delay altera |H|"
    # pendiente de la fase relativa via mejor recta (evita saltos de wrap)
    rel = np.unwrap(np.angle(H_d) - np.angle(H_base))
    slope = np.polyfit(freq_axis, rel, 1)[0]
    expected_slope = -2.0 * np.pi * tau
    print(f"  Delay tau={tau*1e3:.1f} ms: pendiente fase={slope:.5e} "
          f"rad/Hz, esperada={expected_slope:.5e}")
    assert abs(slope - expected_slope) < 1e-6, "[FALLA] pendiente de fase del delay"
    src0.response = None

    # ------------------------------------------------------------------------
    # 6. Cancelacion multi-fuente (§13.3): dos fuentes COINCIDENTES,
    #    flat+flat suma; flat+polaridad cancela exacto.
    # ------------------------------------------------------------------------
    pos = (1.0, 1.0, 1.0)
    a = OmniSource(pos, sensitivity_dB=90.0, label="a")
    b = OmniSource(pos, sensitivity_dB=90.0, label="b")
    arr2 = SourceArray([a, b])
    H_sum = frequency_response(locator, freqs, phis, arr2, receiver, freq_axis)
    H_one = frequency_response(locator, freqs, phis,
                               SourceArray([OmniSource(pos, sensitivity_dB=90.0)]),
                               receiver, freq_axis)
    assert np.allclose(H_sum, 2.0 * H_one, rtol=1e-10), \
        "[FALLA] dos fuentes en fase no suman x2"
    b.response = synth_response("polarity")          # invierte b
    H_cancel = frequency_response(locator, freqs, phis, arr2, receiver, freq_axis)
    max_resid = np.max(np.abs(H_cancel))
    ref = np.max(np.abs(H_one))
    print(f"\n  Multi-fuente coincidente: flat+flat = 2x una fuente  OK")
    print(f"    flat+polaridad: max|H|={max_resid:.2e} (ref una fuente "
          f"{ref:.2e}) -> cancelacion {20*np.log10(max(max_resid,1e-30)/ref):.0f} dB")
    assert max_resid < 1e-10 * ref, "[FALLA] polaridad opuesta no cancela"

    # ------------------------------------------------------------------------
    # 7. Pasa-altos: modos por debajo de fc mas atenuados que los de arriba.
    # ------------------------------------------------------------------------
    fc = 45.0
    g_hp = synth_response("highpass", fc=fc).gain_spectrum(freqs)
    atten_db = 20.0 * np.log10(np.abs(g_hp))
    print(f"\n  Pasa-altos fc={fc} Hz: atenuacion por modo [dB]:")
    for f, a_db in zip(freqs, atten_db):
        print(f"    {f:6.1f} Hz -> {a_db:+5.1f} dB")
    # El modo mas bajo debe estar mas atenuado que el mas alto.
    assert atten_db[0] < atten_db[-1], "[FALLA] highpass no atenua mas a baja f"

    # ------------------------------------------------------------------------
    # 8. v2.25: delay/fase como CAMPOS de la fuente (no horneados en la curva).
    #    Se componen en effective_Q_spectrum; delay=0,fase=0 -> historico exacto.
    # ------------------------------------------------------------------------
    fa8 = np.array([50.0, 100.0, 200.0])
    s_base = OmniSource((1, 1, 1), sensitivity_dB=90.0)
    q_hist = s_base.effective_Q_spectrum(fa8)
    s_zero = OmniSource((1, 1, 1), sensitivity_dB=90.0, delay_s=0.0, phase_deg=0.0)
    assert np.array_equal(q_hist, s_zero.effective_Q_spectrum(fa8)), \
        "[FALLA] delay/fase = 0 no reduce EXACTO al historico"
    tau = 0.003
    s_d = OmniSource((1, 1, 1), sensitivity_dB=90.0, delay_s=tau, polarity=-1)
    fac = s_d.effective_Q_spectrum(fa8) / (q_hist * -1.0)     # aisla el factor
    assert np.allclose(np.abs(fac), 1.0), "[FALLA] el delay cambio la magnitud"
    assert np.allclose(np.angle(fac * np.exp(1j * 2 * np.pi * fa8 * tau)), 0.0,
                       atol=1e-9), "[FALLA] delay no da fase lineal -2pi f tau"
    print(f"\n  Delay/fase como campos: delay=0 identico al historico; "
          f"delay {tau*1e3:.0f} ms = fase lineal, |factor|=1, compone con "
          f"polaridad  OK")

    print("\n  TODOS LOS ORACULOS OK.")


if __name__ == "__main__":
    main()
