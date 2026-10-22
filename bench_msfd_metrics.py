"""
bench_msfd_metrics.py
=====================

Oráculo del item 4: MSFD = [SD, MD] de Celestinos & Nielsen (JAES 56(11) 2008,
sec. 2.4; Acoustics'08 ec. 1-3) + claridad C30/C50.

Chequeos falsables:
  T1  SD == `spatial` de flatness_and_spatial (atadura de definición).
  T2  MD = mean_r(std_f L) distinto de SD y de `flat`; casos sintéticos con MSFD
      conocido (campo plano en f -> MD=0; campo plano en espacio -> SD=0).
  T3  C_te de un decaimiento exponencial puro vs la fórmula cerrada
      C_te = 10log10(e^{2 δ te} − 1).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_msfd_metrics.py
"""

from __future__ import annotations

import numpy as np

import dba_evaluate as de

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


def test_sd_ties_spatial():
    print("T1  SD == `spatial` (misma definición)")
    rng = np.random.default_rng(0)
    fa = np.linspace(20, 120, 50)
    L = rng.normal(70, 4, size=(12, len(fa)))      # 12 posiciones x 50 freqs
    flat, spatial, _ = de.flatness_and_spatial(fa, L)
    sd, md = de.msfd_metrics(fa, L)
    check("SD == spatial", abs(sd - spatial) < 1e-12, f"{sd:.4f} vs {spatial:.4f}")
    check("MD != SD en campo aleatorio", abs(md - sd) > 1e-3,
          f"MD={md:.3f}, SD={sd:.3f}")


def test_synthetic_msfd():
    print("\nT2  casos sintéticos con MSFD conocido")
    fa = np.linspace(20, 120, 40)
    # (a) Mismo nivel en TODAS las posiciones, pero rugoso en frecuencia:
    #     SD=0 (sin variación espacial), MD>0.
    prof = 5.0 * np.sin(2 * np.pi * fa / 25.0)     # rugosidad espectral comun
    La = np.tile(70.0 + prof, (8, 1))
    sd_a, md_a = de.msfd_metrics(fa, La)
    check("campo igual en todas las posiciones -> SD≈0", sd_a < 1e-9,
          f"SD={sd_a:.2e}")
    check("...pero MD>0 (rugoso en f)", md_a > 1.0, f"MD={md_a:.2f}")
    # (b) Plano en frecuencia, distinto por posición: MD=0, SD>0.
    offs = np.linspace(-6, 6, 8)[:, None]
    Lb = 70.0 + offs + np.zeros((8, len(fa)))
    sd_b, md_b = de.msfd_metrics(fa, Lb)
    check("plano en f -> MD≈0", md_b < 1e-9, f"MD={md_b:.2e}")
    check("...pero SD>0 (varía por posición)", sd_b > 1.0, f"SD={sd_b:.2f}")


def test_clarity_formula():
    print("\nT3  C_te de un decaimiento exponencial vs fórmula cerrada")
    fs = 8000.0
    t = np.arange(0, int(1.0 * fs)) / fs
    for delta, te in ((20.0, 50.0), (40.0, 30.0)):
        ir = np.exp(-delta * t)                    # p(t) ~ e^{-delta t}
        c = de.clarity_db(t, ir, te_ms=te)
        te_s = te * 1e-3
        c_exact = 10.0 * np.log10(np.exp(2 * delta * te_s) - 1.0)
        check(f"C_{int(te)} (δ={delta}) ≈ fórmula", abs(c - c_exact) < 0.2,
              f"{c:.2f} vs {c_exact:.2f} dB")


def main():
    print("=" * 68)
    print("bench_msfd_metrics.py  —  MSFD=[SD,MD] + C30/C50 (item 4)")
    print("=" * 68)
    test_sd_ties_spatial()
    test_synthetic_msfd()
    test_clarity_formula()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
