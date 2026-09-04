"""
crosscheck_santillan_figs.py
============================

Genera las figuras del cross-check contra Santillan (JASA 110(4), 2001):
  - fig7:  E_LS(f) (analogo a su Fig 7) + linea 0.3 + marca c/d.
  - fig6_frf:  FRF en las 4 posiciones de su Fig 6, antes vs despues de ecualizar.
  - fig6_ir:   respuesta impulsiva antes vs despues (colapso a delta retardada).

Correr:  /c/Users/aceve/anaconda3/python.exe crosscheck_santillan_figs.py
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from source_coupling import RectModalBasis, WallPiston
from dba import (piston_wall_grid, coupling_matrix, ls_error_curve,
                 dba_ls_coupling_fn, impulse_response, schroeder_decay_db)

DIMS = (2.7, 5.0, 2.2)
C_SANT = 346.4
XI = 0.03
AXIS = 1
SANT_POS = [(0.3, 0.9, 0.3), (1.0, 1.8, 0.9), (1.7, 3.2, 1.5), (2.4, 4.1, 2.2)]


def listening_zone(n_y=7, n_x=6, n_z=4):
    ys = np.linspace(0.6, 4.4, n_y)
    xs = np.linspace(0.25, DIMS[0] - 0.25, n_x)
    zs = np.linspace(0.25, DIMS[2] - 0.25, n_z)
    return np.array([[x, y, z] for x in xs for y in ys for z in zs])


def two_source_before():
    h = 0.05
    return [WallPiston(axis=AXIS, side="min",
                       span=(0.05 - h, 0.05 + h, 2.00 - h, 2.00 + h), vn=1.0),
            WallPiston(axis=AXIS, side="min",
                       span=(2.65 - h, 2.65 + h, 2.00 - h, 2.00 + h), vn=1.0)]


def main():
    basis = RectModalBasis(DIMS, fmax=620.0, n_max=18, c=C_SANT)
    sensors = listening_zone()
    pistons = (piston_wall_grid(basis, AXIS, "min", 4, 4)
               + piston_wall_grid(basis, AXIS, "max", 4, 4))
    C_before = coupling_matrix(basis, two_source_before()).sum(axis=1)
    C_after = dba_ls_coupling_fn(basis, pistons, sensors, axis=AXIS, xi=XI)

    # ---- Fig 7: E_LS(f) --------------------------------------------------
    fa = np.linspace(40.0, 460.0, 211)
    E = ls_error_curve(basis, pistons, sensors, fa, axis=AXIS, xi=XI)
    dx = (DIMS[0] - 0.10) / 3.0
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(fa, E, "-", color="#1f77b4", lw=1.6, label="E$_{LS}$ (este trabajo)")
    ax.axhline(0.3, color="#d62728", ls="--", lw=1.0, label="límite E=0.3 (Santillán)")
    ax.axvline(C_SANT / dx, color="#2ca02c", ls=":", lw=1.0,
               label=f"c/d = {C_SANT/dx:.0f} Hz")
    ax.set_xlabel("frecuencia [Hz]"); ax.set_ylabel("error de mínimos cuadrados E$_{LS}$")
    ax.set_title("Cross-check Fig 7 de Santillán — error de ecualización (sala 2.7×5.0×2.2 m, 4×4 subs)")
    ax.set_ylim(0, 0.8); ax.set_xlim(40, 460); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig("crosscheck_santillan_fig7.png", dpi=130)
    plt.close(fig)

    # ---- Fig 6: FRF en 4 posiciones -------------------------------------
    fb = np.linspace(40.0, 300.0, 400)
    fig, axs = plt.subplots(2, 2, figsize=(9.5, 6.0), sharex=True)
    for ax, pos in zip(axs.ravel(), SANT_POS):
        Hb = 20 * np.log10(np.abs(basis.frf(np.array(pos), fb, C_before, xi=XI)) + 1e-12)
        Ha = 20 * np.log10(np.abs(basis.frf_dispersive(np.array(pos), fb, C_after, xi=XI)) + 1e-12)
        Hb -= np.mean(Hb); Ha -= np.mean(Ha)
        ax.plot(fb, Hb, "--", color="#888", lw=1.0, label="antes (2 subs)")
        ax.plot(fb, Ha, "-", color="#1f77b4", lw=1.4, label="después (DBA LS)")
        ax.set_title(f"pos {pos} m — σ: {np.std(Hb):.1f}→{np.std(Ha):.1f} dB", fontsize=9)
        ax.grid(alpha=0.3); ax.set_ylim(-25, 15)
    axs[0, 0].legend(fontsize=8, loc="upper right")
    for ax in axs[1, :]:
        ax.set_xlabel("frecuencia [Hz]")
    for ax in axs[:, 0]:
        ax.set_ylabel("nivel relativo [dB]")
    fig.suptitle("Cross-check Fig 6 de Santillán — FRF antes vs después de ecualizar")
    fig.tight_layout(); fig.savefig("crosscheck_santillan_fig6_frf.png", dpi=130)
    plt.close(fig)

    # ---- Fig 6: respuesta impulsiva -------------------------------------
    pos = np.array(SANT_POS[2])
    t, hb = impulse_response(basis, pos, C_before, fmax=300.0, xi=XI)
    _, ha = impulse_response(basis, pos, C_after, fmax=300.0, xi=XI)
    sel = t < 0.35
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.5, 3.6))
    a1.plot(t[sel] * 1e3, hb[sel] / np.max(np.abs(hb[sel])), color="#888", lw=1.0)
    a1.set_title("antes (2 subs): resuena"); a1.set_xlabel("t [ms]"); a1.grid(alpha=0.3)
    a2.plot(t[sel] * 1e3, ha[sel] / np.max(np.abs(ha[sel])), color="#1f77b4", lw=1.0)
    a2.set_title("después (DBA LS): delta retardada"); a2.set_xlabel("t [ms]"); a2.grid(alpha=0.3)
    for a in (a1, a2):
        a.set_ylim(-1.1, 1.1); a.set_ylabel("h(t) norm.")
    fig.suptitle(f"Cross-check Fig 6 de Santillán — respuesta impulsiva en {tuple(pos)} m")
    fig.tight_layout(); fig.savefig("crosscheck_santillan_fig6_ir.png", dpi=130)
    plt.close(fig)

    # resumen numerico
    sb, sa = schroeder_decay_db(hb), schroeder_decay_db(ha)
    def t15(s):
        i = np.argmax(s <= -15.0); return t[i] if s[i] <= -15 else t[-1]
    print("Figuras generadas:")
    print("  crosscheck_santillan_fig7.png       (E_LS vs f)")
    print("  crosscheck_santillan_fig6_frf.png   (FRF 4 posiciones)")
    print("  crosscheck_santillan_fig6_ir.png    (IR antes/despues)")
    # cruce de 0.3 en la banda de diseno (tras el minimo, no la zona <55 Hz)
    band = fa > 150
    cruce = fa[band][np.argmax(E[band] >= 0.3)] if np.any(E[band] >= 0.3) else fa[-1]
    print(f"E_LS cruza 0.3 en ~{cruce:.0f} Hz  (Santillan ~300 Hz, c/d=400 Hz)")
    print(f"IR decay t(-15 dB): antes={t15(sb)*1e3:.0f} ms  despues={t15(sa)*1e3:.0f} ms")


if __name__ == "__main__":
    main()
