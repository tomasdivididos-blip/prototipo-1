"""
bench_cone_damping.py
=====================

Oraculos de C2 (punto 3 riguroso del profesor): el cono del sub como PARCHE DE
IMPEDANCIA de frontera que agrega amortiguamiento modal Delta xi_n.

C2a (este archivo, HECHO): beta_cono(f) = rho0 c S_d / Z_mech(f) desde Thiele-Small
(driver.py). Absorbedor resonante: pico en f_c, beta_max = rho0 c S_d Q_tc/(M_ms w_c),
ancho -3dB = f_c/Q_tc, resistivo puro en f_c, masa-dominado (Im beta<0) arriba.
Ref: Small, JAES 20 (1972); Beranek & Mellow, Sound Fields and Transducers, cap. 6.

C2b (PENDIENTE, requiere decidir): alimentar beta_cono como parche a la suma de
perturbacion (face_materials, Morse & Ingard 9.4.14) -> Delta xi_n, validado contra
el autovalor complejo EXACTO con la BC del cono (mismo oraculo que bench_perturbation_xi).

Correr:
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 \
    /c/Users/aceve/anaconda3/python.exe bench_cone_damping.py
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.linalg as sla

import driver
import face_materials as fm
from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import RHO0, C0

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def main():
    # Sub 12": fs=25 Hz, Qts=0.40, Vas=120 L, Sd=0.055 m2, caja sellada Vb=80 L.
    fs, Qts, Vas, Sd, Vb = 25.0, 0.40, 0.120, 0.055, 0.080
    fc, Qtc = driver.sealed_box_params(fs, Qts, Vas, Vb)
    Mms = driver.moving_mass_from_ts(fs, Vas, Sd)

    # M_ms consistente con C_ms = Vas/(rho0 c^2 Sd^2) y fs.
    Cms = Vas / (RHO0 * C0 ** 2 * Sd ** 2)
    Mms_teo = 1.0 / ((2 * np.pi * fs) ** 2 * Cms)
    check("M_ms desde TS (fs, Vas, Sd)", abs(Mms - Mms_teo) < 1e-9,
          f"Mms={Mms:.4f} kg")

    f = np.geomspace(5.0, 200.0, 6000)
    b = driver.cone_specific_admittance(f, fc, Qtc, Sd, Mms)

    # 1) pico de |beta| en f_c.
    i = int(np.argmax(np.abs(b)))
    check("beta_cono: pico en f_c", abs(f[i] - fc) / fc < 0.01,
          f"pico={f[i]:.1f} Hz  fc={fc:.1f} Hz")

    # 2) beta_max = rho0 c Sd Qtc/(Mms w_c).
    bmax_teo = RHO0 * C0 * Sd * Qtc / (Mms * 2 * np.pi * fc)
    check("beta_max = rho0 c Sd Qtc/(Mms w_c)",
          abs(np.abs(b[i]) - bmax_teo) / bmax_teo < 1e-3,
          f"medido={np.abs(b[i]):.4f} teo={bmax_teo:.4f}")

    # 3) ancho -3dB (potencia) = f_c/Q_tc.
    mag2 = np.abs(b) ** 2
    half = mag2[i] / 2.0
    lo = f[:i][np.where(mag2[:i] <= half)[0][-1]]
    hi = f[i:][np.where(mag2[i:] <= half)[0][0]]
    check("ancho -3dB de |beta|^2 = f_c/Q_tc",
          abs((hi - lo) - fc / Qtc) / (fc / Qtc) < 0.03,
          f"medido={hi-lo:.1f} Hz  fc/Qtc={fc/Qtc:.1f} Hz")

    # 4) en f_c beta es resistivo puro (Im ~ 0, Re > 0 -> disipa).
    bc = complex(driver.cone_specific_admittance(fc, fc, Qtc, Sd, Mms))
    check("en f_c: beta resistivo puro (Im~0, Re>0)",
          abs(bc.imag) < 1e-6 * abs(bc.real) and bc.real > 0,
          f"Im/Re={bc.imag/bc.real:.1e}")

    # 5) arriba de f_c: masa-dominado -> Im(beta) < 0 (e^{-iwt}); debajo: rigidez -> >0.
    bhi = complex(driver.cone_specific_admittance(4 * fc, fc, Qtc, Sd, Mms))
    blo = complex(driver.cone_specific_admittance(fc / 4, fc, Qtc, Sd, Mms))
    check("arriba de f_c masa-dominado (Im<0), debajo rigidez (Im>0)",
          bhi.imag < 0 and blo.imag > 0,
          f"Im(4fc)={bhi.imag:.3f}  Im(fc/4)={blo.imag:.3f}")

    # 6) MAGNITUD FISICA: el cono en f_c es un absorbedor NO despreciable
    #    (beta ~ 0.4 -> alpha_random equivalente alto). Confirma la intuicion del
    #    profesor de que el sub "modifica el decaimiento".
    check("beta_cono en f_c es significativo (> 0.1)", np.abs(b[i]) > 0.1,
          f"|beta|max={np.abs(b[i]):.3f}")

    # -----------------------------------------------------------------------
    # C3: ESTADO ELECTRICO DE LOS BORNES (driver.box_terminal_Q).
    # El amplificador cambia el Q de la caja via su impedancia de salida R_g
    # (factor de amortiguamiento DF = R_E/R_g). Tres estados fisicos:
    #   open  (bornes abiertos) -> solo Q_mc, absorbedor mas AGUDO y ALTO en f_c
    #   amp   (ampli real, DF)  -> intermedio
    #   short (bornes en corto) -> Q_tc historico (max amortiguamiento del cono)
    # Ref: Small JAES 20 (1972); Beranek & Mellow cap. 6 (R_g sobre Q_es).
    # -----------------------------------------------------------------------
    print("\n  --- C3: estado electrico de los bornes ---")
    Qms, Qes = driver.qms_qes_from_qts(Qts, Qms=3.0)
    # 7) qms_qes_from_qts respeta 1/Q_ts = 1/Q_ms + 1/Q_es.
    check("qms_qes_from_qts cumple 1/Qts = 1/Qms + 1/Qes",
          abs(1.0 / Qts - (1.0 / Qms + 1.0 / Qes)) < 1e-9,
          f"Qms={Qms:.3f} Qes={Qes:.3f}")
    # 8) sin Q_ms ni Q_es NO se puede separar -> ValueError (norte: no inventar).
    try:
        driver.qms_qes_from_qts(Qts)
        raised = False
    except ValueError:
        raised = True
    check("sin Qms/Qes lanza ValueError (no inventa amortiguamiento)", raised)

    Q_short = driver.box_terminal_Q(fc, fs, Qms, Qes, state="short")
    Q_open = driver.box_terminal_Q(fc, fs, Qms, Qes, state="open")
    Q_amp = driver.box_terminal_Q(fc, fs, Qms, Qes, state="amp", DF=50.0)
    # 9) "short" reproduce EXACTO el Q_tc historico de sealed_box_params.
    check("estado 'short' == Q_tc historico (sin regresion)",
          abs(Q_short - Qtc) < 1e-9, f"short={Q_short:.4f} Qtc={Qtc:.4f}")
    # 10) "open" = Q_mc = Q_ms f_c/f_s y es el mayor (menos freno del cono).
    check("estado 'open' = Q_mc = Qms fc/fs y open > short",
          abs(Q_open - Qms * fc / fs) < 1e-9 and Q_open > Q_short,
          f"open={Q_open:.3f} short={Q_short:.3f}")
    # 11) "amp" (DF finito) queda estrictamente entre short y open.
    check("estado 'amp' (DF=50) entre short y open",
          Q_short < Q_amp < Q_open, f"short={Q_short:.3f} amp={Q_amp:.3f} open={Q_open:.3f}")
    # 12) limites y monotonia en DF: DF->inf ~ short, DF->0 ~ open, decreciente.
    DFs = np.array([1e-4, 0.1, 1.0, 10.0, 100.0, 1e6])
    Qdf = np.array([driver.box_terminal_Q(fc, fs, Qms, Qes, state="amp", DF=d) for d in DFs])
    mono = np.all(np.diff(Qdf) < 0)                        # Q decrece al subir DF
    lim_hi = abs(Qdf[-1] - Q_short) / Q_short < 1e-3
    lim_lo = abs(Qdf[0] - Q_open) / Q_open < 1e-3
    check("DF: Q monotono decreciente, DF->inf=short, DF->0=open",
          mono and lim_hi and lim_lo,
          f"Q(DF=1e6)={Qdf[-1]:.3f} Q(DF=1e-4)={Qdf[0]:.3f}")
    # 13) KNOB FISICO: en f_c, Re(beta) open > amp > short (abiertos absorben mas
    #     en la resonancia; el ampli conectado ensancha y aplana el pico).
    re_at_fc = lambda Q: float(np.real(
        driver.cone_specific_admittance(fc, fc, Q, Sd, Mms)))
    r_short, r_amp, r_open = re_at_fc(Q_short), re_at_fc(Q_amp), re_at_fc(Q_open)
    check("en f_c: Re(beta) open > amp > short (knob del ampli)",
          r_open > r_amp > r_short,
          f"open={r_open:.3f} amp={r_amp:.3f} short={r_short:.3f}")

    # -----------------------------------------------------------------------
    # C2b: Delta xi_n de perturbacion (cono interior) vs QEP complejo EXACTO.
    # El cono en un nodo x_j es un absorbedor interior; el termino exacto de
    # amortiguamiento es C_cone = S_d e_j e_j^T (rango 1). El QEP
    #   c^2 K + i c beta C_cone w - M w^2 = 0
    # da delta_n = Im(w_n); la perturbacion da (c/2) Re(beta) S_d phi_n^2(x_j).
    # -----------------------------------------------------------------------
    print("\n  --- C2b: perturbacion (cono) vs autovalor complejo EXACTO ---")
    Lx, Ly, Lz = 5.0, 4.0, 3.0
    vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat",
                               subdiv_levels=0)
    nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.5)
    Nn = nodes.shape[0]
    K, M, _v = build_KM(nodes, tets)
    Kd, Md = K.toarray(), M.toarray()
    freqs, phis = solve_modes(K, M, n_modes=10)
    loc = FieldEvaluator(nodes, tets)

    # Nodo interior "antinodo-ish" (lejos del centro, no en una pared).
    j = int(np.argmin(np.linalg.norm(
        nodes - np.array([Lx * 0.5, Ly * 0.5, Lz * 0.72]), axis=1)))
    x_j = nodes[j]
    Sd = 0.05

    def qep_delta_cone(beta_val):
        Ccone = np.zeros((Nn, Nn))
        Ccone[j, j] = Sd                                  # C_cone = Sd e_j e_j^T
        A0, A1, A2 = (C0 ** 2) * Kd, 1j * C0 * beta_val * Ccone, -Md
        Z, I = np.zeros((Nn, Nn)), np.eye(Nn)
        w = sla.eig(np.block([[A0, A1], [Z, I]]),
                    np.block([[Z, -A2], [I, Z]]), right=False)
        w = w[np.isfinite(w)]
        return w[np.real(w) > 1.0]

    for beta_val in (0.05, 0.15):
        cones = [{"pos": x_j, "Sd": Sd, "beta": (lambda f, b=beta_val: b)}]
        dxi = fm.cone_xi_shift_per_mode(freqs, phis, loc, cones, c=C0)
        d_p = dxi * 2 * np.pi * np.asarray(freqs)          # delta perturbacion
        w_ex = qep_delta_cone(beta_val)
        errs = []
        for i in range(len(freqs)):
            k = int(np.argmin(np.abs(np.real(w_ex) / (2 * np.pi) - freqs[i])))
            if abs(np.real(w_ex[k]) / (2 * np.pi) - freqs[i]) / freqs[i] > 0.10:
                continue
            d_ex = float(np.imag(w_ex[k]))
            if d_ex < 1e-6 or d_p[i] < 1e-9:
                continue
            errs.append(abs(d_p[i] / d_ex - 1))
        errs = np.array(errs)
        tol = 0.05 if beta_val <= 0.05 else 0.10
        check(f"C2b [beta={beta_val}] Delta-xi pert vs exacto < {tol*100:.0f}%",
              len(errs) >= 3 and errs.mean() < tol,
              f"n={len(errs)} media {100*errs.mean():.2f}% max {100*errs.max():.2f}%")

    # aditividad: xi(pared) + Delta xi(cono) (a 1er orden los polos se suman)
    check("C2b: Delta xi del cono es >= 0 y finito",
          np.all(np.isfinite(fm.cone_xi_shift_per_mode(
              freqs, phis, loc,
              [{"pos": x_j, "Sd": Sd, "beta": (lambda f: 0.1)}], c=C0)) )
          and np.all(fm.cone_xi_shift_per_mode(
              freqs, phis, loc,
              [{"pos": x_j, "Sd": Sd, "beta": (lambda f: 0.1)}], c=C0) >= 0))

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK  (C2a + C3 bornes + C2b)")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
