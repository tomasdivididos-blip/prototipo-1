"""
bench_source_model.py
=====================

Oraculos del modelo de fuente exacto (item 5, Fase A): baffle step, guard de
doble conteo, regresion con defaults, round-trip Thiele-Small.

Correr:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_source_model.py
"""

from __future__ import annotations

import numpy as np

import driver as drv
from sources import OmniSource, C0

_n = _ok = 0


def check(name, cond, detail=""):
    global _n, _ok
    _n += 1
    _ok += 1 if cond else 0
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def test_baffle_step():
    """T1: low-shelf de -6 dB referido a la banda: |H(LF)|=-6, |H(HF)|=0, corte
    en f_b=c/(pi*ancho); con bafle enorme (f_b->0) no hay step en banda."""
    print("T1 baffle step (forma del shelf)")
    w = 0.4
    f_b = C0 / (np.pi * w)
    g = drv.baffle_step_gain(np.array([2.0, f_b, 5000.0]), w)
    db = 20 * np.log10(np.abs(g))
    check("LF ~ -6 dB", abs(db[0] - (-6.0)) < 0.3, f"{db[0]:.2f} dB")
    check("HF ~ 0 dB", abs(db[2]) < 0.1, f"{db[2]:.3f} dB")
    check("en f_b esta entre -6 y 0", -6.0 < db[1] < 0.0, f"{db[1]:.2f} dB @ {f_b:.0f} Hz")
    g_big = drv.baffle_step_gain(np.linspace(20, 400, 50), 100.0)
    check("bafle enorme -> sin step en banda (|H|~0 dB)",
          np.max(np.abs(20 * np.log10(np.abs(g_big)))) < 0.3)


def test_guard_no_double_count():
    """T2: el guard evita el doble conteo. Una fuente con respuesta MEDIDA
    (full_system) NO recibe baffle step aunque tenga baffle_size; una 'driver' si."""
    print("T2 guard anti-doble-conteo")
    fa = np.linspace(20, 400, 60)
    base = dict(position=(1, 1, 1), sensitivity_dB=90.0, baffle_size=(0.4, 0.6, 0.4))
    s_none = OmniSource(**base, radiation_baked="none")
    s_full = OmniSource(**base, radiation_baked="full_system")
    s_drv = OmniSource(**base, radiation_baked="driver")
    q_none = s_none.effective_Q_spectrum(fa)
    q_full = s_full.effective_Q_spectrum(fa)
    q_drv = s_drv.effective_Q_spectrum(fa)
    check("full_system NO agrega baffle step (== none)",
          np.allclose(q_full, q_none, rtol=1e-12))
    check("driver SI agrega baffle step (!= none)",
          not np.allclose(q_drv, q_none, rtol=1e-6))
    # el efecto del step: driver atenua el grave respecto de none
    lo = fa < 100
    check("driver atenua el grave (baffle step)",
          np.mean(np.abs(q_drv[lo])) < np.mean(np.abs(q_none[lo])) - 1e-9)


def test_regression_defaults():
    """T3: defaults (box/none, sin curva) -> effective_Q_spectrum == Q constante
    (comportamiento historico, bit a bit)."""
    print("T3 regresion con defaults")
    fa = np.linspace(20, 400, 60)
    s = OmniSource((1, 1, 1), sensitivity_dB=90.0)
    check("radiator_kind default = box", s.radiator_kind == "box")
    check("radiation_baked default = none", s.radiation_baked == "none")
    check("spectrum == Q constante (histórico)",
          np.allclose(s.effective_Q_spectrum(fa), s.effective_Q(), rtol=1e-12))


def test_ts_roundtrip():
    """T4: reconstruir el DriverModel desde los TS persistidos da la MISMA curva
    que construirlo directo (los params crudos alcanzan para releer/editar)."""
    print("T4 round-trip Thiele-Small")
    fs, qts, vas, vb = 30.0, 0.4, 60.0, 40.0
    d_direct = drv.DriverModel(fs=fs, Qts=qts, Vas=vas, Vb=vb)
    s = OmniSource((1, 1, 1), sensitivity_dB=90.0, ts_fs=fs, ts_qts=qts,
                   ts_vas=vas, ts_vb=vb, radiation_baked="driver")
    d_from_src = drv.DriverModel(fs=s.ts_fs, Qts=s.ts_qts, Vas=s.ts_vas, Vb=s.ts_vb)
    fa = np.linspace(20, 400, 40)
    g1 = d_direct.to_response(fa).gain_spectrum(fa)
    g2 = d_from_src.to_response(fa).gain_spectrum(fa)
    check("misma fc/Qtc", abs(d_direct.fc - d_from_src.fc) < 1e-9
          and abs(d_direct.Qtc - d_from_src.Qtc) < 1e-9)
    check("misma curva g(f)", np.allclose(g1, g2, rtol=1e-10))


if __name__ == "__main__":
    print("=" * 60)
    print("bench_source_model.py  —  modelo de fuente exacto (Fase A)")
    print("=" * 60)
    test_baffle_step()
    test_guard_no_double_count()
    test_regression_defaults()
    test_ts_roundtrip()
    print("-" * 60)
    print(f"  {_ok}/{_n} checks OK")
    if _ok != _n:
        raise SystemExit(1)
