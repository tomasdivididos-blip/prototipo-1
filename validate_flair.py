# -*- coding: utf-8 -*-
"""Validacion sobre FLAIR (geometria arbitraria reconstruida) - M1 + M4.

Protocolo: validation_protocol.md. FLAIR es el dataset PRIMARIO para "geometria
arbitraria" y para M4 (posiciones exactas de mic/fuente en el marco de la nube;
sin el placement desconocido que dejo INCONCLUSO a MeshRIR).

Geometria: reconstruida de la nube (flair_geometry.reconstruct_room): alinear yaw
(~8.5 deg) + occupancy + sellar/corregir + marching_cubes. Sala ~4.96x5.08x2.72.

M1 (error de frecuencia modal): pocos picos resolubles (FRF promedio SUAVE por
RT~0.4s + promediado sobre 135 mics). Se reporta lo que hay, con la incertidumbre
de reconstruccion (+-1 voxel ~ +-1.6% en cada dimension).

M4 (correlacion espacial): posiciones exactas -> bien planteado. Se reporta CRUDO y
DESTENDENCIADO (la M4 cruda quedo sub-especificada frente a la coloracion de fuente,
protocolo 10). Amortiguamiento xi_n = delta/omega_n con delta = 3 ln10 / RT60,
RT60 medido de las propias RIRs (INPUT declarado, no prediccion).
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.io import loadmat

import rir
from flair_geometry import reconstruct_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import RHO0

MAT = "datasets/flair/data_FLAIR.mat"
BAND = (25.0, 120.0)          # banda modal de analisis
N_MODES = 60
NPM = 4.0
SRC = 0                        # fuente a usar (0 o 1; dan curvas casi identicas)


def load_flair():
    m = loadmat(MAT, squeeze_me=True)
    return dict(pts=m["boundary_points"].T, nrm=m["boundary_normals"].T,
                mic=m["mic_positions"].T, spk=m["spkr_positions"].T,
                c=float(m["c"]), fs=int(m["fs"]), rirs=m["rirs"])


def measured_spatial(rirs, fs, src):
    """Promedio espacial de |H|^2 sobre los 135 mics + RT60 broadband mediano."""
    psum = None
    rts = []
    for j in range(rirs.shape[1]):
        ir = rirs[:, j, src]
        f, H = rir.rir_to_frf(ir, fs, f_min=10, f_max=200, pad_factor=4)
        if psum is None:
            psum = np.zeros_like(f); freq = f
        psum += np.abs(H) ** 2
        r = rir.rt_from_ir(ir, fs)
        if r.ok:
            rts.append(r.rt60)
    rt60 = float(np.median(rts)) if rts else 0.4
    return freq, psum / rirs.shape[1], rt60


def sim_spatial_avg(loc, freqs, phis, mic_pos, src_pos, freq_axis, delta, c, rho=RHO0):
    Nm = phis.shape[1]
    Phi_r = np.empty((len(mic_pos), Nm))
    for n in range(Nm):
        Phi_r[:, n] = np.nan_to_num(loc.evaluate_many(phis[:, n], mic_pos).real)
    phi_s = np.array([np.nan_to_num(loc.evaluate_many(phis[:, n], src_pos[None])[0].real)
                      for n in range(Nm)])
    omega_n = 2 * np.pi * freqs
    xi = delta / omega_n
    om = 2 * np.pi * np.asarray(freq_axis)
    D = (omega_n[None, :] ** 2 - om[:, None] ** 2) + 2j * xi[None, :] * omega_n[None, :] * om[:, None]
    A = 1j * om[:, None] * rho * c ** 2 * phi_s[None, :] / D
    return np.mean(np.abs(Phi_r @ A.T) ** 2, axis=0)


def _detrend_db(power, freq, frac=0.2):
    y = 10 * np.log10(power + 1e-30)
    lf = np.log(np.maximum(freq, 1e-6))
    base = np.array([y[np.abs(lf - lf[i]) <= frac].mean() for i in range(len(y))])
    return y - base


def corr(a, b, freq, band):
    m = (freq >= band[0]) & (freq <= band[1])
    return float(np.corrcoef(a[m], b[m])[0, 1])


def main():
    d = load_flair()
    c, fs = d["c"], d["fs"]
    print("=" * 74)
    print(f"Validacion FLAIR - M1 + M4 | c={c:.1f} m/s, fs={fs}")
    print("=" * 74)

    # Geometria reconstruida (alineada) + posiciones mapeadas
    print("[geom] reconstruyendo desde la nube...")
    r = reconstruct_room(d["pts"], d["nrm"], d["mic"][len(d["mic"]) // 2],
                         positions=[d["mic"], d["spk"]], hv=0.04, seal="auto")
    assert not r["leaked"], "reconstruccion fugada: revisar la nube"
    mic_al, spk_al = r["positions_aligned"]
    print(f"[geom] yaw {r['theta_deg']:.2f} deg | L={r['Lx']:.2f}x{r['Ly']:.2f}x{r['Lz']:.2f} m "
          f"| V={r['V_interior']:.1f} m3 | seal auto={r['seal_used']} (guard de regimen)")

    # FEM
    nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=NPM)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=N_MODES, c=c)
    info = mesh_info(nodes, tets); f_max = max_solver_frequency(info["h_max"])
    loc = FieldEvaluator(nodes, tets)
    fem_in = freqs[(freqs >= BAND[0]) & (freqs <= BAND[1])]
    print(f"[fem] nodes={len(nodes)} h_max={info['h_max']:.3f} f_max={f_max:.0f} Hz "
          f"| {len(fem_in)} modos en banda")

    # MEDIDO
    print("[medido] promediando 135 mics + RT60...")
    freq, meas_pow, rt60 = measured_spatial(d["rirs"], fs, SRC)
    delta = 3 * np.log(10) / rt60
    mag_db = rir.spectrum_db(np.sqrt(meas_pow))
    peaks = [p[0] for p in rir.find_modal_peaks(freq, mag_db, f_lo=BAND[0], f_hi=BAND[1],
                                                prominence_db=1.5, max_peaks=16)]
    print(f"[medido] RT60~{rt60:.2f}s -> delta={delta:.1f}/s | picos: "
          f"{', '.join(f'{p:.1f}' for p in peaks)} Hz")

    # ---- M1 ----
    print("\n" + "-" * 74)
    print("M1 (error de frecuencia modal) - apareo pico medido -> modo FEM cercano")
    print(f"{'f_med':>8} {'f_FEM':>8} {'drel':>8}")
    rels = []
    for fm in peaks:
        fp = float(fem_in[np.argmin(np.abs(fem_in - fm))])
        rel = abs(fp - fm) / fm
        rels.append(rel)
        print(f"{fm:8.1f} {fp:8.1f} {rel*100:7.2f}%")
    m1 = float(np.median(rels))
    cov = float(np.mean(np.array(rels) <= 0.05))
    print(f"M1 (mediana) = {m1*100:.2f}%  (umbral <=3%) -> {'PASA' if m1 <= 0.03 else 'REVISAR'}")
    print(f"M2 (cobertura tol 5%) = {cov*100:.0f}%")
    print("nota: incertidumbre de reconstruccion ~+-1.6% por dimension (+-1 voxel).")

    # ---- M4 ----
    # Metrica ratificada con el usuario (2026-09-06, protocolo 10): DESTENDENCIADA
    # (saca coloracion de fuente, mide estructura modal), banda [f_piso_fuente, f_S].
    # f_min = 45 Hz = piso util de la RIR (el parlante DS no radia por debajo; protocolo 3).
    # f_S = 2000 sqrt(RT/V) (Schroeder). Ninguno elegido para pasar.
    f_S = 2000.0 * np.sqrt(rt60 / r["V_interior"])
    M4_BAND = (45.0, f_S)
    print("\n" + "-" * 74)
    print(f"M4 (correlacion espacial) - DESTENDENCIADA, banda [{M4_BAND[0]:.0f}, {M4_BAND[1]:.0f}] Hz")
    print(f"  f_S = 2000 sqrt(RT/V) = {f_S:.0f} Hz | f_min = 45 Hz (piso de fuente, protocolo 3)")
    sim_pow = sim_spatial_avg(loc, freqs, phis, mic_al, spk_al[SRC], freq, delta, c)
    md, sd = _detrend_db(meas_pow, freq), _detrend_db(sim_pow, freq)
    m4_det = corr(md, sd, freq, M4_BAND)
    m4_raw = corr(10*np.log10(meas_pow+1e-30), 10*np.log10(sim_pow+1e-30), freq, M4_BAND)
    print(f"M4 destendenciado (fuente {SRC}) = {m4_det:.3f}  (umbral >=0.7) -> "
          f"{'PASA' if m4_det >= 0.7 else 'MISS marginal' if m4_det >= 0.6 else 'FALLA'}")
    print(f"  [secundario] M4 crudo = {m4_raw:.3f}")
    # fuente 1 (secundario)
    freq1, mp1, rt1 = measured_spatial(d["rirs"], fs, 1)
    sp1 = sim_spatial_avg(loc, freqs, phis, mic_al, spk_al[1], freq1, 3*np.log(10)/rt1, c)
    m4_det1 = corr(_detrend_db(mp1, freq1), _detrend_db(sp1, freq1), freq1, M4_BAND)
    print(f"  [secundario] M4 destendenciado (fuente 1) = {m4_det1:.3f}")

    # Figura overlay
    m = (freq >= 20) & (freq <= 150)
    plt.figure(figsize=(9, 4))
    plt.plot(freq[m], 10*np.log10(meas_pow[m]/meas_pow[m].max()+1e-12), label="medido", lw=1.4)
    plt.plot(freq[m], 10*np.log10(sim_pow[m]/sim_pow[m].max()+1e-12),
             label=f"sim (M4 det={m4_det:.2f}, crudo={m4_raw:.2f})", lw=1.4, alpha=.85)
    plt.axvspan(*M4_BAND, color="g", alpha=.08, label=f"banda M4 [{M4_BAND[0]:.0f},{M4_BAND[1]:.0f}]")
    plt.xlabel("f [Hz]"); plt.ylabel("nivel norm. [dB]"); plt.grid(alpha=.3); plt.legend()
    plt.title("FLAIR - promedio espacial de la FRF: medido vs sim")
    plt.tight_layout(); plt.savefig("validation_flair.png", dpi=110)
    print("\n[out] validation_flair.png")
    print("=" * 74)
    return dict(m1=m1, cov=cov, m4_det=m4_det, m4_raw=m4_raw, m4_det1=m4_det1,
                f_S=f_S, peaks=peaks, rels=rels, fem_in=fem_in, geom=r, rt60=rt60)


if __name__ == "__main__":
    main()
