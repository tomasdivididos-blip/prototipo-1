"""
bench_driver.py
===============

Oraculos de la Fase S2 (driver fisico Thiele-Small). Ver `plan_modelo_fuente.md`.

Valida contra resultados analiticos:
  T1  caja sellada: |p(fc)|/|p(inf)| = Qtc
  T2  caja sellada: pendiente -12 dB/oct bajo fc, plano arriba
  T3  caja sellada: fase de p en fc = +90° (conv. e^{+iωt})
  T4  fc/Qtc desde TS crudos (Small)
  T5  impedancia de radiacion del piston: limites ka->0 y ka->inf (Kinsler)
  T6  composicion en OmniSource.effective_Q_spectrum reproduce la curva
  T7  reduccion: g(f_ref) = 1 (anclaje relativo)

Correr:  /c/Users/aceve/anaconda3/python.exe bench_driver.py
"""

import numpy as np

import driver as drv
from driver import (DriverModel, sealed_box_params, volume_velocity_transfer,
                    pressure_transfer, piston_radiation_impedance)
from sources import OmniSource

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  OK   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}  {detail}")


# ---------------------------------------------------------------------------
# T1 — |p(fc)|/|p(inf)| = Qtc
# ---------------------------------------------------------------------------
def t1_peak_at_fc():
    for fc, Qtc in [(40.0, 0.707), (30.0, 1.2), (55.0, 0.5)]:
        p_fc = abs(pressure_transfer(fc, fc, Qtc)[0])
        p_hi = abs(pressure_transfer(1e5, fc, Qtc)[0])   # asintota de banda
        ratio = p_fc / p_hi
        check(f"T1 |p(fc)|/|p(inf)|=Qtc (fc={fc}, Qtc={Qtc})",
              np.isclose(ratio, Qtc, rtol=1e-3),
              f"ratio={ratio:.4f} vs Qtc={Qtc}")


# ---------------------------------------------------------------------------
# T2 — pendiente -12 dB/oct bajo fc, plano arriba
# ---------------------------------------------------------------------------
def t2_slopes():
    fc, Qtc = 40.0, 0.707
    # Muy por debajo de fc: p ~ s^2 -> +12 dB/oct subiendo en f (o sea -12 bajando).
    f1, f2 = 2.0, 4.0                      # una octava, f << fc
    p1 = abs(pressure_transfer(f1, fc, Qtc)[0])
    p2 = abs(pressure_transfer(f2, fc, Qtc)[0])
    slope_oct = 20.0 * np.log10(p2 / p1)   # dB por octava
    check("T2 pendiente +12 dB/oct bajo fc",
          np.isclose(slope_oct, 12.0, atol=0.3), f"slope={slope_oct:.2f} dB/oct")
    # Muy por encima de fc: plano.
    f3, f4 = 2000.0, 4000.0
    p3 = abs(pressure_transfer(f3, fc, Qtc)[0])
    p4 = abs(pressure_transfer(f4, fc, Qtc)[0])
    flat = 20.0 * np.log10(p4 / p3)
    check("T2 plano sobre fc", np.isclose(flat, 0.0, atol=0.05),
          f"delta={flat:.3f} dB/oct")


# ---------------------------------------------------------------------------
# T3 — fase de p en fc = +90°
# ---------------------------------------------------------------------------
def t3_phase_at_fc():
    fc, Qtc = 40.0, 0.707
    # H_p(s)=s^2/(s^2+(wc/Qtc)s+wc^2). En s=i*wc -> i*Qtc*wc^2/wc^2... = +90°.
    ph = np.degrees(np.angle(pressure_transfer(fc, fc, Qtc)[0]))
    check("T3 fase p(fc)=+90°", np.isclose(ph, 90.0, atol=1e-6), f"fase={ph:.4f}°")
    # Asintota DC: pasa-altos -> +180°.
    ph_dc = np.degrees(np.angle(pressure_transfer(1e-3, fc, Qtc)[0]))
    check("T3 fase p(DC)->+180°", np.isclose(abs(ph_dc), 180.0, atol=0.1),
          f"fase={ph_dc:.4f}°")


# ---------------------------------------------------------------------------
# T4 — fc/Qtc desde TS crudos (Small)
# ---------------------------------------------------------------------------
def t4_ts_to_box():
    fs, Qts, Vas = 25.0, 0.35, 100.0     # sub tipico
    Vb = 50.0                             # caja = medio Vas -> alpha=2
    fc, Qtc = sealed_box_params(fs, Qts, Vas, Vb)
    scale = np.sqrt(1.0 + Vas / Vb)       # sqrt(3)
    check("T4 fc = fs*sqrt(1+Vas/Vb)", np.isclose(fc, fs * scale, rtol=1e-9),
          f"fc={fc:.3f}")
    check("T4 Qtc = Qts*sqrt(1+Vas/Vb)", np.isclose(Qtc, Qts * scale, rtol=1e-9),
          f"Qtc={Qtc:.3f}")
    # DriverModel resuelve igual por ambos caminos.
    d_ts = DriverModel(fs=fs, Qts=Qts, Vas=Vas, Vb=Vb)
    d_dir = DriverModel(fc=fc, Qtc=Qtc)
    check("T4 DriverModel TS == directo",
          np.isclose(d_ts.fc, d_dir.fc) and np.isclose(d_ts.Qtc, d_dir.Qtc))


# ---------------------------------------------------------------------------
# T5 — impedancia de radiacion del piston (limites)
# ---------------------------------------------------------------------------
def t5_radiation_impedance():
    # ka -> 0: R1 ~ (ka)^2/2, X1 ~ 8*ka/(3*pi).
    ka = 1e-3
    Z = piston_radiation_impedance(ka)[0]
    check("T5 R1(ka->0) ~ (ka)^2/2",
          np.isclose(Z.real, ka**2 / 2.0, rtol=2e-2),
          f"R1={Z.real:.3e} vs {ka**2/2:.3e}")
    check("T5 X1(ka->0) ~ 8ka/(3pi)",
          np.isclose(Z.imag, 8.0 * ka / (3.0 * np.pi), rtol=2e-2),
          f"X1={Z.imag:.3e} vs {8*ka/(3*np.pi):.3e}")
    # ka -> inf: R1 -> 1, X1 -> 0.
    Zhi = piston_radiation_impedance(50.0)[0]
    check("T5 R1(ka->inf)->1", np.isclose(Zhi.real, 1.0, atol=5e-2),
          f"R1={Zhi.real:.4f}")
    check("T5 X1(ka->inf)->0", abs(Zhi.imag) < 5e-2, f"X1={Zhi.imag:.4f}")


# ---------------------------------------------------------------------------
# T6 — composicion en OmniSource.effective_Q_spectrum
# ---------------------------------------------------------------------------
def t6_composition():
    d = DriverModel(fc=40.0, Qtc=0.707)
    resp = d.to_response(f_ref=200.0)
    src = OmniSource((1.0, 1.0, 1.0), sensitivity_dB=90.0, response=resp)
    fa = np.array([20.0, 40.0, 80.0, 160.0, 200.0])
    q = src.effective_Q_spectrum(fa)
    q0 = src.effective_Q()
    g = resp.gain_spectrum(fa)
    # effective_Q_spectrum = effective_Q() * g(f)  (sin delay/filtro/polaridad)
    check("T6 effective_Q_spectrum = Q0*g(f)",
          np.allclose(q, q0 * g, rtol=1e-9),
          f"max err={np.max(np.abs(q - q0*g)):.2e}")


# ---------------------------------------------------------------------------
# T7 — anclaje relativo + observable PRESION (p ∝ omega*Q ∝ f*g, Q0 constante)
# ---------------------------------------------------------------------------
def t7_relative_anchor_and_pressure():
    fc, Qtc = 40.0, 0.707
    d = DriverModel(fc=fc, Qtc=Qtc)
    resp = d.to_response(f_ref=200.0)
    # (a) anclaje: |g(f_ref)| = 1
    check("T7 |g(f_ref)|=1", np.isclose(abs(resp.gain_spectrum(200.0)[0]), 1.0,
          rtol=1e-6), f"|g(200)|={abs(resp.gain_spectrum(200.0)[0]):.6f}")
    # (b) regresion: g(f) == U(f)/U(f_ref) exacto
    fa = np.array([12.0, 40.0, 90.0, 200.0, 380.0])
    g = resp.gain_spectrum(fa)
    U = volume_velocity_transfer(fa, fc, Qtc)
    Uref = volume_velocity_transfer(200.0, fc, Qtc)[0]
    # rtol laxo: la SourceResponse interpola linealmente una curva de 2000 pts,
    # el residuo ~1e-4 es error de interpolacion, no del modelo.
    check("T7 g(f)=U(f)/U(f_ref)", np.allclose(g, U / Uref, rtol=3e-3, atol=1e-4),
          f"max err={np.max(np.abs(g - U/Uref)):.2e}")
    # (c) observable PRESION: p(f) ∝ f*|g(f)| (Q baseline constante). Normalizada
    #     a f_ref (banda), debe reproducir el pasa-altos de 2º orden.
    def pnorm(f):
        return float(f * abs(resp.gain_spectrum(np.atleast_1d(float(f)))[0]))
    p_ref = pnorm(200.0)
    check("T7 presion plana en banda", np.isclose(pnorm(400.0) / p_ref, 1.0,
          atol=0.05), f"p(400)/p_ref={pnorm(400.0)/p_ref:.3f}")
    check("T7 presion cae bajo fc (~(f/fc)^2)", pnorm(10.0) / p_ref < 0.15,
          f"p(10)/p_ref={pnorm(10.0)/p_ref:.3f}")
    check("T7 presion en fc = Qtc", np.isclose(pnorm(fc) / p_ref, Qtc, rtol=2e-2),
          f"p(fc)/p_ref={pnorm(fc)/p_ref:.3f} vs Qtc={Qtc}")


if __name__ == "__main__":
    print("bench_driver.py — oraculos Fase S2 (driver fisico TS)\n")
    t1_peak_at_fc()
    t2_slopes()
    t3_phase_at_fc()
    t4_ts_to_box()
    t5_radiation_impedance()
    t6_composition()
    t7_relative_anchor_and_pressure()
    print(f"\n  {_PASS} OK, {_FAIL} FAIL")
    raise SystemExit(1 if _FAIL else 0)
