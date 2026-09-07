# -*- coding: utf-8 -*-
"""Test de PODER DISCRIMINANTE de las metricas (responde al hallazgo C1 del auditor).

C1: "M1 y M2 son no discriminantes: una sala equivocada tambien PASA." Con pocos
picos medidos (4-5) contra una densidad alta de modos predichos (22-35 en banda) y
tol 3%, casi cualquier frecuencia aparea. Una metrica valida DEBE empeorar cuando la
geometria es incorrecta.

Se testea directamente:
  Parte 1 (M1): linea base NULA (M1 de salas aleatorias del mismo volumen) + barrido
    de escala uniforme s. Si M1_true no es mejor que la nula, o el minimo no esta en
    s=1, M1 NO discrimina (C1 confirmado).
  Parte 2 (M4, FLAIR): M4 destendenciado vs escala de geometria (via escalado del eje
    de frecuencia del espectro sim). Si M4 se MAXIMIZA en s=1, M4 discrimina y valida
    la geometria verdadera aunque su valor absoluto sea 0.62.
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from validate_meshrir import analytic_modes

# Picos medidos (salida de los runners congelados; se citan, no se re-derivan aca).
MESHRIR = dict(peaks=[22.0, 52.0, 57.1, 68.5, 85.3, 116.8], dims=(7.0, 6.4, 2.7),
               c=347.0, submodal=24.0)     # excluye 22 Hz (< 1er axial 24.8)
FLAIR = dict(peaks=[26.9, 51.7, 71.8, 77.2, 101.4], dims=(4.96, 5.08, 2.72),
             c=344.7, submodal=33.0)       # excluye 26.9 Hz (< 1er axial ~34)
BAND = (25.0, 120.0)


def m1_of(peaks, dims, c, submodal, band=BAND):
    """M1 = mediana |Δf|/f de picos modales -> modo analitico mas cercano."""
    modes = np.array([f for f, _ in analytic_modes(*dims, c, band[1] + 20)])
    modes = modes[(modes >= band[0]) & (modes <= band[1])]
    rels = [min(abs(modes - fm) / fm) for fm in peaks if fm >= submodal]
    return float(np.median(rels)), len(modes)


def null_baseline(peaks, dims, c, submodal, n=4000, seed=0):
    """M1 de salas ALEATORIAS con el mismo volumen (linea base nula)."""
    rng = np.random.default_rng(seed)
    V = np.prod(dims)
    out = []
    for _ in range(n):
        r = rng.uniform(2.5, 8.0, size=3)
        r *= (V / np.prod(r)) ** (1 / 3)          # reescalar a volumen V
        out.append(m1_of(peaks, tuple(r), c, submodal)[0])
    return np.array(out)


def scale_scan(peaks, dims, c, submodal, ss):
    return np.array([m1_of(peaks, tuple(np.array(dims) * s), c, submodal)[0] for s in ss])


def part1():
    print("=" * 74)
    print("PARTE 1 - Poder discriminante de M1 (linea base nula + barrido de escala)")
    print("=" * 74)
    ss = np.linspace(0.80, 1.20, 81)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, (name, d) in zip(axs, [("MeshRIR", MESHRIR), ("FLAIR", FLAIR)]):
        m1_true, nmodes = m1_of(d["peaks"], d["dims"], d["c"], d["submodal"])
        null = null_baseline(d["peaks"], d["dims"], d["c"], d["submodal"])
        pct = float(np.mean(null <= m1_true) * 100)         # percentil de true en la nula
        scan = scale_scan(d["peaks"], d["dims"], d["c"], d["submodal"], ss)
        s_min = ss[np.argmin(scan)]
        print(f"\n[{name}] modos en banda={nmodes} | M1_true={m1_true*100:.2f}%")
        print(f"  nula (salas aleatorias, mismo V): mediana={np.median(null)*100:.2f}% "
              f"| mejor 5%={np.percentile(null,5)*100:.2f}%")
        print(f"  -> M1_true esta en el percentil {pct:.0f} de la nula "
              f"({'NO mejor que el azar' if pct>10 else 'en la cola buena'})")
        print(f"  barrido escala: minimo en s={s_min:.3f} "
              f"({'discrimina (min~1.0)' if abs(s_min-1)<0.03 else 'NO discrimina (min lejos de 1)'})")
        ax.hist(null * 100, bins=40, color="0.7", label="salas aleatorias (nula)")
        ax.axvline(m1_true * 100, color="C3", lw=2, label=f"M1 sala verdadera ({m1_true*100:.2f}%)")
        ax.axvline(3.0, color="k", ls="--", alpha=.5, label="umbral 3%")
        ax.set_title(f"{name}: M1 verdadera vs nula"); ax.set_xlabel("M1 [%]"); ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig("validation_discrimination_m1.png", dpi=110)
    print("\n[out] validation_discrimination_m1.png")


def part2():
    print("\n" + "=" * 74)
    print("PARTE 2 - Poder discriminante de M4 sobre FLAIR (M4 vs escala de geometria)")
    print("=" * 74)
    from validate_flair import (load_flair, measured_spatial, sim_spatial_avg,
                                _detrend_db, corr, N_MODES, NPM, SRC)
    from flair_geometry import reconstruct_room
    from acoustic_mesh import build_volume_mesh
    from acoustic_fem import build_KM, solve_modes, FieldEvaluator
    d = load_flair(); c, fs = d["c"], d["fs"]
    r = reconstruct_room(d["pts"], d["nrm"], d["mic"][67], positions=[d["mic"], d["spk"]],
                         hv=0.04, seal=3)
    mic_al, spk_al = r["positions_aligned"]
    nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=NPM)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=N_MODES, c=c)
    loc = FieldEvaluator(nodes, tets)
    freq, meas_pow, rt = measured_spatial(d["rirs"], fs, SRC)
    delta = 3 * np.log(10) / rt
    sim_pow = sim_spatial_avg(loc, freqs, phis, mic_al, spk_al[SRC], freq, delta, c)
    f_S = 2000 * np.sqrt(rt / r["V_interior"]); band = (45.0, f_S)
    md = _detrend_db(meas_pow, freq)

    # escalar geometria por s <=> evaluar el sim en el eje f*s (modos -> omega/s)
    ss = np.linspace(0.85, 1.15, 61)
    m4s = []
    for s in ss:
        sp_s = np.interp(freq * s, freq, sim_pow, left=sim_pow[0], right=sim_pow[-1])
        m4s.append(corr(md, _detrend_db(sp_s, freq), freq, band))
    m4s = np.array(m4s); s_best = ss[np.argmax(m4s)]
    print(f"[FLAIR] M4 destendenciado, banda [{band[0]:.0f},{band[1]:.0f}]")
    print(f"  M4(s=1.00) = {m4s[np.argmin(abs(ss-1))]:.3f}")
    print(f"  M4 maximo  = {m4s.max():.3f} en s={s_best:.3f}")
    print(f"  -> {'M4 DISCRIMINA (max en s~1)' if abs(s_best-1)<0.03 else 'max corrido de 1'}: "
          f"la geometria verdadera {'maximiza' if abs(s_best-1)<0.03 else 'NO maximiza'} M4")
    plt.figure(figsize=(7, 4.5))
    plt.plot(ss, m4s, "-o", ms=3); plt.axvline(1.0, color="C3", ls="--", label="geometria verdadera")
    plt.axhline(0.7, color="k", ls=":", alpha=.5, label="umbral 0.7")
    plt.xlabel("escala de geometria s"); plt.ylabel("M4 destendenciado")
    plt.title("FLAIR: M4 vs escala de geometria (discriminacion)"); plt.legend(); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig("validation_discrimination_m4.png", dpi=110)
    print("[out] validation_discrimination_m4.png")


if __name__ == "__main__":
    part1()
    part2()
    print("=" * 74)
