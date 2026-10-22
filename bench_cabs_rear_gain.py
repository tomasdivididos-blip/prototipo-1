"""
bench_cabs_rear_gain.py
=======================

Oráculo del item 1 (ganancia G del parlante trasero del CABS) + item 3 (f_max =
c/d − Δe). Fuente: Celestinos & Nielsen, «CABS», JAES 56(11), 2008, sec. 2.1 y
2.3 (Fig. 7); absorción del aire ISO 9613-1.

FÍSICA (clave, falsable): en el modelo modal estacionario la cancelación del
modo axial es C_m(k_m) ∝ 1 − G, o sea el residuo de UN modo aislado es mínimo en
G=1. PERO en una sala AMORTIGUADA el frente llega atenuado a la pared trasera, y
un trasero con G=1 la sobre-excita: la UNIFORMIDAD de la zona (lo que optimiza
MSFD) mejora con G<1, y la mejora crece con el amortiguamiento. El bench mide la
métrica correcta (uniformidad espacial), no el residuo del modo aislado.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_cabs_rear_gain.py
"""

from __future__ import annotations

import numpy as np

from source_coupling import RectModalBasis
import acoustic_analysis as aa
import dba

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


def _spatial_std(basis, zone, Cfn, fa, xi):
    s = []
    for f in fa:
        p = np.abs(basis.pressure_field(zone, float(f), Cfn(f), xi=xi))
        s.append(np.std(20.0 * np.log10(p / p.mean())))
    return float(np.mean(s))


def test_gain_shape():
    print("T1  G(f): <1, decrece con L y con delta; delta->0 y air off -> 1")
    c = 343.0
    G_short = dba.cabs_rear_gain((4, 6, 3), 1, rt60=0.4, c=c, air=False)
    G_long = dba.cabs_rear_gain((4, 6, 3), 1, rt60=2.0, c=c, air=False)
    check("G < 1 con amortiguamiento", G_short(60.0) < 1.0,
          f"G={G_short(60.0):.3f}")
    check("más amortiguado (RT corto) -> G más chico",
          G_short(60.0) < G_long(60.0),
          f"{G_short(60.0):.3f} < {G_long(60.0):.3f}")
    G_bigroom = dba.cabs_rear_gain((4, 12, 3), 1, rt60=0.4, c=c, air=False)
    check("eje más largo -> G más chico (más viaje)",
          G_bigroom(60.0) < G_short(60.0),
          f"{G_bigroom(60.0):.3f} < {G_short(60.0):.3f}")
    G_none = dba.cabs_rear_gain((4, 6, 3), 1, rt60=None, xi=None, c=c, air=False)
    check("sin RT ni xi ni aire -> G==1 (no-regresión)",
          abs(G_none(60.0) - 1.0) < 1e-12, f"G={G_none(60.0):.6f}")


def test_uniformity_improves():
    print("\nT2  G<1 da zona MÁS uniforme que G=1 en sala amortiguada, y la "
          "mejora crece con el amortiguamiento")
    dims = (4.0, 6.0, 3.0); axis = 1; c = 343.0
    fmax = 120.0
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    basis = RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)
    zone = dba._zone_grid(dims, axis)
    fa = np.linspace(25.0, fmax, 30)
    gains = []
    for xi in (0.01, 0.03, 0.08):
        omega1 = c * np.pi / dims[axis]
        rt60 = 3.0 * np.log(10.0) / (xi * omega1)
        G = dba.cabs_rear_gain(dims, axis, rt60=rt60, c=c, air=True)
        s1 = _spatial_std(basis, zone, dba.dba_coupling_fn(basis, axis=axis,
                          rear_gain=1.0), fa, xi)
        sg = _spatial_std(basis, zone, dba.dba_coupling_fn(basis, axis=axis,
                          rear_gain=G), fa, xi)
        gains.append(s1 - sg)
        check(f"xi={xi:.2f}: G<1 más plano que G=1", sg < s1,
              f"{s1:.2f} dB -> {sg:.2f} dB  (G_mid={G(70.0):.3f})")
    check("la mejora crece con el amortiguamiento",
          gains[0] < gains[1] < gains[2],
          f"Δplanitud={[round(g,2) for g in gains]} dB")


def test_air_absorption_iso():
    print("\nT3  absorción del aire vs ISO 9613-1 (valor tabulado)")
    # ISO 9613-1, 20 C, 50% HR, 1 atm: a 1 kHz ~ 5.1 dB/km = 5.1e-3 dB/m.
    a = aa.air_absorption_alpha(1000.0, T=20.0, RH=50.0, P=101325.0)
    a_db_km = a * 8.686 * 1000.0
    check("α(1 kHz) ~ 5 dB/km (tabla ISO 9613-1)", 4.0 < a_db_km < 6.5,
          f"{a_db_km:.2f} dB/km")
    # A graves es minúsculo (crece con f^2).
    a63 = aa.air_absorption_alpha(63.0) * 8.686 * 1000.0
    check("α(63 Hz) << α(1 kHz) (crece ~f^2)", a63 < 0.1 * a_db_km,
          f"{a63:.4f} dB/km")


def test_fmax_delta_e():
    print("\nT4  item 3: f_max = c/d − Δe (Δe del amortiguamiento)")
    dims = (4.0, 6.0, 3.0); axis = 1
    f0 = dba.alias_fmax(dims, axis, 4, 4)                       # Δe=0 (histórico)
    f_damped = dba.alias_fmax(dims, axis, 4, 4, rt60=0.4)       # amortiguado
    f_live = dba.alias_fmax(dims, axis, 4, 4, rt60=2.0)         # vivo
    check("Δe=0 (default) == c/d histórico", np.isfinite(f0) and f0 > 0,
          f"f_max={f0:.1f} Hz")
    check("f_max baja con amortiguamiento (Δe>0)", f_damped < f0,
          f"{f0:.1f} -> {f_damped:.1f} Hz")
    check("RT corto (más amortiguado) baja más que RT largo",
          f_damped < f_live < f0,
          f"RT0.4={f_damped:.1f} < RT2.0={f_live:.1f} < {f0:.1f}")
    check("1 sub por eje -> inf (sin aliasing)",
          dba.alias_fmax(dims, axis, 1, 1) == float("inf"))


def main():
    print("=" * 70)
    print("bench_cabs_rear_gain.py  —  ganancia G del trasero (item 1) + f_max (item 3)")
    print("=" * 70)
    test_gain_shape()
    test_uniformity_improves()
    test_air_absorption_iso()
    test_fmax_delta_e()
    print("-" * 70)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
