# -*- coding: utf-8 -*-
"""Validacion M4 (correlacion espacial de la FRF) sobre MeshRIR + barrido.

Protocolo: validation_protocol.md, metrica M4 (correlacion del promedio espacial
de la FRF, sim vs medida) >= 0.7.

PROBLEMA DE DATO (hallazgo 2026-09-05): MeshRIR fija el origen en el CENTRO DE LA
REGION de medicion y NO publica donde esta esa region dentro del cuarto (ni el
paper, ni el repo, ni la pagina). M4 depende de la ubicacion del rig respecto de
las paredes (los phi_n estan anclados a las paredes). El protocolo 1 prohibe
inventar posiciones, asi que:

  - Se BARRE la ubicacion P (centro de la region) sobre todo el rango plausible
    (rig adentro del cuarto, con margen de pared). Si M4 >= 0.7 en TODO el rango,
    el dato faltante NO cambia el veredicto. Si M4 oscila, M4 sobre MeshRIR queda
    INCONCLUSO y lo carga FLAIR (geometria + posiciones exactas).

Amortiguamiento: xi_n = delta / omega_n con delta = 3 ln(10) / T60 y T60 = 0.38 s
(medido, Kuttruff Room Acoustics ec. de la constante de decaimiento). Es un INPUT
declarado (fija el ancho/altura de los picos), NO una prediccion de RT. Se testea
la sensibilidad de M4 a xi (x0.5, x2) para mostrar que no manda.
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from validate_meshrir import (LX, LY, LZ, C_SOUND, DATA_DIR,
                              measured_spatial_spectrum, load_positions, fem_solve)
from sources import RHO0

RT60 = 0.38                       # s, medido (Table 1 del paper MeshRIR)
DELTA = 3.0 * np.log(10.0) / RT60  # constante de decaimiento [1/s] (Kuttruff)
M4_BAND = (26.0, 120.0)           # arranca sobre el 1er modo (24.8) para evitar el pico sub-modal
N_MODES = 60


def sim_spatial_avg(loc, freqs, phis, P, mic_local, src_local, freq_axis,
                    xi_scale=1.0, c=C_SOUND, rho=RHO0):
    """Promedio espacial de |H(f)|^2 sobre los mics, para la ubicacion P."""
    mic_room = P[None, :] + mic_local           # (Nrec, 3)
    src_room = P + src_local                     # (3,)
    Nm = phis.shape[1]
    Phi_r = np.empty((len(mic_room), Nm))
    for n in range(Nm):
        Phi_r[:, n] = np.nan_to_num(loc.evaluate_many(phis[:, n], mic_room).real)
    phi_s = np.array([np.nan_to_num(loc.evaluate_many(phis[:, n], src_room[None])[0].real)
                      for n in range(Nm)])

    omega_n = 2.0 * np.pi * freqs                # (Nm,)
    xi = xi_scale * DELTA / omega_n              # (Nm,) xi_n = delta/omega_n
    om = 2.0 * np.pi * np.asarray(freq_axis)     # (Nf,)
    D = ((omega_n[None, :] ** 2 - om[:, None] ** 2)
         + 2j * xi[None, :] * omega_n[None, :] * om[:, None])       # (Nf, Nm)
    A = 1j * om[:, None] * rho * c ** 2 * phi_s[None, :] / D         # (Nf, Nm)
    H_all = Phi_r @ A.T                           # (Nrec, Nf)
    return np.mean(np.abs(H_all) ** 2, axis=0)    # (Nf,)


def m4_corr(meas_pow, sim_pow, freq, band):
    m = (freq >= band[0]) & (freq <= band[1])
    a = 10.0 * np.log10(meas_pow[m] + 1e-30)
    b = 10.0 * np.log10(sim_pow[m] + 1e-30)
    return float(np.corrcoef(a, b)[0, 1])


def main():
    print("=" * 74)
    print("Validacion M4 - MeshRIR (correlacion espacial de la FRF) + barrido")
    print(f"  Caja {LX}x{LY}x{LZ} | c={C_SOUND:.1f} m/s | T60={RT60}s -> delta={DELTA:.1f}/s")
    print("=" * 74)

    # Lado MEDIDO (promedio espacial, una sola pasada)
    print("[medido] promediando espectro sobre el grid...")
    freq, meas_pow, used, _ir_len, _fs = measured_spatial_spectrum(DATA_DIR)
    mic_local, src_local, _fs2, _npts = load_positions(DATA_DIR)
    print(f"[medido] {used} mics, {len(mic_local)} posiciones locales")

    # Sim: solve modal una vez
    print("[sim] resolviendo modos...")
    loc, freqs, phis, f_max, info = fem_solve(LX, LY, LZ, C_SOUND, 4.0, N_MODES)
    print(f"[sim] h_max={info['h_max']:.3f} m, f_max={f_max:.0f} Hz, "
          f"{int(np.sum((freqs>=M4_BAND[0])&(freqs<=M4_BAND[1])))} modos en banda")

    # Rango plausible de P (centro de region) con margen de 0.3 m a paredes.
    # make_room: x in [-Lx/2,Lx/2], y in [-Ly/2,Ly/2], z in [0,Lz].
    # Extension del rig: mics +-0.5 (xy), +-0.2 (z); fuente en P+(2.0,1.5,0).
    margin = 0.3
    px_lo = -LX / 2 + 0.5 + margin;  px_hi = LX / 2 - 2.0 - margin
    py_lo = -LY / 2 + 0.5 + margin;  py_hi = LY / 2 - 1.5 - margin
    z_lo, z_hi = 0.6, 1.3            # altura de medicion plausible (fuente de piso)
    Pxs = np.linspace(px_lo, px_hi, 3)
    Pys = np.linspace(py_lo, py_hi, 3)
    Pzs = np.array([z_lo, 0.5 * (z_lo + z_hi), z_hi])

    print(f"\n[barrido] Px in [{px_lo:.2f},{px_hi:.2f}], Py in [{py_lo:.2f},{py_hi:.2f}], "
          f"z0 in [{z_lo},{z_hi}] -> {len(Pxs)*len(Pys)*len(Pzs)} ubicaciones")
    m4s = []
    for pz in Pzs:
        for px in Pxs:
            for py in Pys:
                P = np.array([px, py, pz])
                sp = sim_spatial_avg(loc, freqs, phis, P, mic_local, src_local, freq)
                m4s.append((m4_corr(meas_pow, sp, freq, M4_BAND), (px, py, pz)))
    vals = np.array([v for v, _ in m4s])
    frac_pass = float(np.mean(vals >= 0.7))
    print(f"[barrido] M4: min {vals.min():.3f} | mediana {np.median(vals):.3f} | "
          f"max {vals.max():.3f}")
    print(f"[barrido] fraccion con M4>=0.7: {frac_pass*100:.0f}%  "
          f"({int(np.sum(vals>=0.7))}/{len(vals)})")

    # Nominal: region al centro del cuarto (xy), z0 medio
    P_nom = np.array([0.0, 0.0, 0.5 * (z_lo + z_hi)])
    sp_nom = sim_spatial_avg(loc, freqs, phis, P_nom, mic_local, src_local, freq)
    m4_nom = m4_corr(meas_pow, sp_nom, freq, M4_BAND)
    print(f"\n[nominal] region al centro xy, z0={P_nom[2]:.2f}: M4 = {m4_nom:.3f}")

    # Sensibilidad al amortiguamiento (nominal)
    print("[damping] sensibilidad de M4 a xi (nominal):")
    for sc in (0.5, 1.0, 2.0):
        spx = sim_spatial_avg(loc, freqs, phis, P_nom, mic_local, src_local, freq, xi_scale=sc)
        print(f"    xi x{sc:>3}: M4 = {m4_corr(meas_pow, spx, freq, M4_BAND):.3f}")

    # Figura overlay (nominal)
    m = (freq >= 20) & (freq <= 130)
    plt.figure(figsize=(9, 4))
    plt.plot(freq[m], 10 * np.log10(meas_pow[m] / np.max(meas_pow[m]) + 1e-12),
             label="medido (promedio espacial)", lw=1.4)
    plt.plot(freq[m], 10 * np.log10(sp_nom[m] / np.max(sp_nom[m]) + 1e-12),
             label=f"sim (nominal, M4={m4_nom:.2f})", lw=1.4, alpha=0.85)
    plt.axvspan(M4_BAND[0], M4_BAND[1], color="k", alpha=0.05)
    plt.xlabel("f [Hz]"); plt.ylabel("nivel norm. [dB]")
    plt.title("MeshRIR - promedio espacial de la FRF: medido vs sim")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig("validation_meshrir_m4.png", dpi=110)
    print("\n[out] validation_meshrir_m4.png")

    verdict = ("ROBUSTO (M4>=0.7 en todo el rango)" if frac_pass == 1.0
               else "PARCIAL (M4>=0.7 en parte del rango)" if frac_pass > 0
               else "INCONCLUSO (M4<0.7 en todo el rango)")
    print("=" * 74)
    print(f"M4 sobre MeshRIR: {verdict}")
    print(f"  -> el M4 autoritativo lo carga FLAIR (geometria + posiciones exactas).")
    print("=" * 74)
    return freq, meas_pow, sp_nom, vals, m4_nom, frac_pass


if __name__ == "__main__":
    main()
