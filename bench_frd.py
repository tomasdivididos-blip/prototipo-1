"""
bench_frd.py
============

Smoke tests de la Fase 1 del plan de fuentes: parser FRD, anclaje de nivel
(absoluto / relativo), round-trip de persistencia (.room v5) y fase minima.

La integracion FEM de Q(f) ya esta cubierta por bench_source_response.py
(una curva FRD es solo otro g(f); la factorizacion H=g·H_base es agnostica
al origen de la curva). Aca se testea la capa FRD->g(f) y el I/O.

Correr:
    PYTHONIOENCODING=utf-8 python bench_frd.py
"""
from __future__ import annotations

import os
import tempfile
import numpy as np

from frd import load_frd, minimum_phase
from sources import (SourceResponse, OmniSource, q_from_sensitivity,
                     synth_response, RHO0)


def _write(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".frd")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_parser():
    print("1. Parser tolerante")
    # comentarios (*, #, ;), separador mixto coma/espacio/tab, 3 columnas.
    txt = (
        "* VituixCAD export\n"
        "# header de texto\n"
        "freq spl phase\n"            # se ignora (no parsea a float)
        "20.0, 78.3, -145.2\n"
        "40.0\t81.0\t-120.0\n"
        "80.0  84.5  -95.0\n"
        ";comentario\n"
        "160.0 86.0 -60.0\n"
    )
    p = _write(txt)
    f, spl, ph = load_frd(p)
    os.unlink(p)
    assert list(f) == [20, 40, 80, 160], f
    assert ph is not None and len(ph) == 4
    print(f"   3 cols: f={list(f)}  spl={list(spl)}  phase={list(ph)}  OK")

    # 2 columnas -> phase None; orden y dedup.
    p2 = _write("100 90\n50 85\n50 99\n200 92\n")
    f2, spl2, ph2 = load_frd(p2)
    os.unlink(p2)
    assert list(f2) == [50, 100, 200] and ph2 is None
    assert spl2[0] == 85.0          # se quedo con la primera de las f=50 dup
    print(f"   2 cols + dedup + orden: f={list(f2)}  phase={ph2}  OK")


def test_anchoring():
    print("\n2. Anclaje de nivel (absoluto vs relativo)")
    f_ref = 1000.0
    S = 90.0
    q_base = q_from_sensitivity(S, f_ref=f_ref).real
    fa = np.array([28.0, 50.0, 100.0, f_ref])

    # --- FRD plano EXACTAMENTE a la sensibilidad S ---
    f = np.linspace(10.0, 1000.0, 400)
    spl_flat = np.full_like(f, S)
    r_abs = SourceResponse.from_frd(f, spl_flat, anchor="absolute",
                                    q_base=q_base, f_ref=f_ref)
    src = OmniSource((1, 1, 1), sensitivity_dB=S, f_ref=f_ref)
    src.response = r_abs
    Qf = src.effective_Q_spectrum(fa)
    # §3.1: |Q(f)| debe ser q_base*(f_ref/f) para SPL plano (flat SPL -> Q∝1/f)
    expected = q_base * (f_ref / fa)
    assert np.allclose(np.abs(Qf), expected, rtol=1e-3), \
        f"absoluto flat: {np.abs(Qf)} != {expected}"
    # en f_ref el nivel coincide con la sensibilidad
    assert abs(abs(src.effective_Q_spectrum(np.array([f_ref]))[0]) - q_base) < 1e-9 * q_base
    print(f"   absoluto, SPL plano @ {S} dB: |Q(f)| = q_base·(f_ref/f)  OK")
    print(f"     |Q| en {list(fa.astype(int))} = "
          f"{[f'{x:.3e}' for x in np.abs(Qf)]}")

    # --- FRD plano 10 dB MAS CALIENTE que la sensibilidad ---
    spl_hot = np.full_like(f, S + 10.0)
    r_abs_hot = SourceResponse.from_frd(f, spl_hot, anchor="absolute",
                                        q_base=q_base, f_ref=f_ref)
    r_rel_hot = SourceResponse.from_frd(f, spl_hot, anchor="relative",
                                        q_base=q_base, f_ref=f_ref)
    src.response = r_abs_hot
    q_abs_ref = abs(src.effective_Q_spectrum(np.array([f_ref]))[0])
    src.response = r_rel_hot
    q_rel_ref = abs(src.effective_Q_spectrum(np.array([f_ref]))[0])
    # Absoluto refleja los +10 dB; relativo los IGNORA (ancla a sensibilidad).
    assert abs(20*np.log10(q_abs_ref / q_base) - 10.0) < 1e-6, "absoluto no refleja +10 dB"
    assert abs(q_rel_ref - q_base) < 1e-9 * q_base, "relativo no ancla a la sensibilidad"
    print(f"   FRD +10 dB:  absoluto @f_ref = +{20*np.log10(q_abs_ref/q_base):.1f} dB  |  "
          f"relativo @f_ref = {20*np.log10(q_rel_ref/q_base):+.2f} dB (anclado)  OK")


def test_roundtrip():
    print("\n3. Round-trip .room v5 (to_dict / from_dict)")
    f = np.linspace(20.0, 200.0, 120)
    spl = 85.0 + 6.0 * np.exp(-((f - 60.0) / 12.0) ** 2)      # bump
    ph_deg = -90.0 * np.tanh((f - 80.0) / 40.0)
    r = SourceResponse.from_frd(f, spl, np.deg2rad(ph_deg),
                                anchor="absolute", q_base=1.0e-3, f_ref=1000.0)
    d = r.to_dict()
    r2 = SourceResponse.from_dict(d)
    fa = np.linspace(25.0, 190.0, 50)
    assert np.allclose(r.gain_spectrum(fa), r2.gain_spectrum(fa), rtol=1e-12, atol=1e-30)
    assert r2.anchor == "absolute" and r2.name == r.name
    print(f"   dict keys={sorted(d.keys())}; g(f) reconstruida identica  OK")


def test_minimum_phase():
    print("\n4. Fase minima (oraculo: pasa-altos de 1 polo)")
    fc = 50.0
    f = np.linspace(10.0, 1000.0, 600)
    mag = f / np.sqrt(f**2 + fc**2)                  # |HP 1 polo|
    spl = 20.0 * np.log10(mag)
    ph_min = minimum_phase(f, spl)
    ph_true = np.arctan2(fc, f)                      # fase analitica = arctan(fc/f)
    # Comparar en banda media (el Hilbert es malo en los bordes).
    mid = (f > 30.0) & (f < 400.0)
    err = np.abs(ph_min[mid] - ph_true[mid])
    print(f"   error medio mid-band = {np.degrees(err.mean()):.2f}°, "
          f"max = {np.degrees(err.max()):.2f}°")
    # Tolerante: el metodo es aproximado. Verificamos signo y tendencia.
    assert err.mean() < np.radians(8.0), "fase minima fuera de tolerancia (signo?)"
    print("   OK (signo y tendencia correctos)")


if __name__ == "__main__":
    test_parser()
    test_anchoring()
    test_roundtrip()
    test_minimum_phase()
    print("\nTODOS LOS TESTS DE FASE 1 OK.")
