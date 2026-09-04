"""
bench_sbir.py
=============

Oraculos analiticos para sbir.py (T6). Cada test tiene comportamiento conocido
de cerrado, asi sirve de regresion permanente.

  1. notch_c_4d   : 1 pared, R=1, receptor lejano -> 1er nulo en c/(4d).
  2. flush_mount  : fuente sobre la pared (d->0) -> sin notch en banda, +6 dB.
  3. boundary_lift: |1+R| en LF -> +20log10(1+R) dB.
  4. material_R   : pared absorbente (alpha alto) -> notch menos profundo que R=1.
  5. shoebox6     : 6 paredes, fuente en esquina -> notches en los c/(4d) por cara.
  6. stereo_sum   : 2 fuentes -> la curva total = suma compleja de p_tot, no el
                    promedio de las curvas dB.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_sbir.py
"""

from __future__ import annotations

import numpy as np

from sbir import (Wall, sbir_response, reflection_from_alpha, C0,
                  modal_sbir_crossfade)


def _ok(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def test_notch_c_4d():
    """1 pared en x=0, fuente a d, receptor lejano: 1er nulo en c/(4d)."""
    f = np.linspace(20.0, 500.0, 4000)
    all_ok = True
    for d in (0.3, 0.5, 0.8):
        wall = Wall([0, 0, 0], [1, 0, 0], "pared", R=1.0)
        Q = np.ones((len(f), 1), dtype=complex)
        res = sbir_response([[d, 0, 0]], Q, [wall], [60.0, 0, 0], f)
        _, _, f_valle, aten = res.band_extremes(20, 500)
        f_teor = C0 / (4 * d)
        rel = abs(f_valle - f_teor) / f_teor
        all_ok &= _ok(f"notch c/(4d) d={d}m",
                      rel < 0.03 and aten < -15.0,
                      f"teor={f_teor:.1f} medido={f_valle:.1f} ({aten:.1f} dB)")
        # El notch teorico declarado debe coincidir con c/(4d).
        nt = res.first_notches(20, 500)
        all_ok &= _ok(f"notch declarado d={d}m",
                      len(nt) >= 1 and abs(nt[0].f_notch - f_teor) < 1e-6,
                      f"declarado={nt[0].f_notch:.1f}" if nt else "sin notch")
    return all_ok


def test_flush_mount():
    """d -> 0: la imagen coincide con la fuente, sin notch en banda, +6 dB."""
    f = np.linspace(20.0, 500.0, 1000)
    wall = Wall([0, 0, 0], [1, 0, 0], "pared", R=1.0)
    Q = np.ones((len(f), 1), dtype=complex)
    res = sbir_response([[1e-5, 0, 0]], Q, [wall], [50.0, 0, 0], f)
    spread = float(res.total_sbir_db.max() - res.total_sbir_db.min())
    lift = float(res.total_sbir_db.mean())
    return (_ok("flush sin notch en banda", spread < 0.5,
                f"spread={spread:.3f} dB")
            and _ok("flush +6 dB", abs(lift - 6.02) < 0.2, f"lift={lift:.2f} dB"))


def test_boundary_lift():
    """LF: |p_tot/p_dir| -> |1+R| -> +20log10(1+R) dB para varias R."""
    f = np.linspace(20.0, 500.0, 500)
    all_ok = True
    for R in (1.0, 0.7, 0.5):
        wall = Wall([0, 0, 0], [1, 0, 0], "pared", R=R)
        Q = np.ones((len(f), 1), dtype=complex)
        # d chico -> la imagen llega casi en fase en toda la banda.
        res = sbir_response([[1e-4, 0, 0]], Q, [wall], [50.0, 0, 0], f)
        expected = 20.0 * np.log10(1.0 + R)
        all_ok &= _ok(f"boundary lift R={R}",
                      abs(res.total_sbir_db[0] - expected) < 0.1,
                      f"medido={res.total_sbir_db[0]:.2f} esperado={expected:.2f}")
    return all_ok


def test_material_R():
    """Pared absorbente: el notch es menos profundo que con R=1."""
    f = np.linspace(20.0, 500.0, 4000)
    d = 0.5
    rcv = [60.0, 0, 0]
    Q = np.ones((len(f), 1), dtype=complex)
    res_rig = sbir_response([[d, 0, 0]],
                            Q, [Wall([0, 0, 0], [1, 0, 0], "rig", R=1.0)], rcv, f)
    R_abs = reflection_from_alpha(0.6)   # alpha=0.6 -> R~0.63
    res_abs = sbir_response([[d, 0, 0]],
                            Q, [Wall([0, 0, 0], [1, 0, 0], "abs", R=R_abs)], rcv, f)
    _, _, _, aten_rig = res_rig.band_extremes(20, 500)
    _, _, _, aten_abs = res_abs.band_extremes(20, 500)
    return _ok("absorbente => notch menos profundo", aten_abs > aten_rig + 5.0,
               f"R=1:{aten_rig:.1f} dB  alpha=0.6:{aten_abs:.1f} dB")


def _shoebox_walls(Lx, Ly, Lz, R=1.0):
    """6 paredes de una caja Lx x Ly x Lz (planos con normal hacia adentro)."""
    return [
        Wall([0, 0, 0],   [1, 0, 0], "x-",   R),
        Wall([Lx, 0, 0],  [-1, 0, 0], "x+",  R),
        Wall([0, 0, 0],   [0, 1, 0], "y-",   R),
        Wall([0, Ly, 0],  [0, -1, 0], "y+",  R),
        Wall([0, 0, 0],   [0, 0, 1], "piso", R),
        Wall([0, 0, Lz],  [0, 0, -1], "techo", R),
    ]


def test_shoebox6():
    """6 paredes, fuente cerca de una esquina: los notches declarados coinciden
    con c/(4d) de las 3 distancias chicas (x, y, z a las caras cercanas)."""
    Lx, Ly, Lz = 5.0, 4.0, 3.0
    f = np.linspace(20.0, 500.0, 2000)
    src = [0.4, 0.5, 0.6]    # cerca de la esquina (x-,y-,piso)
    walls = _shoebox_walls(Lx, Ly, Lz, R=1.0)
    Q = np.ones((len(f), 1), dtype=complex)
    res = sbir_response([src], Q, walls, [Lx/2, Ly/2, 1.2], f)
    # Debe haber 6 notches declarados (uno por cara).
    ok = _ok("shoebox: 6 notches", len(res.notches) == 6, f"n={len(res.notches)}")
    # Las 3 caras cercanas dan c/(4d) con d = 0.4, 0.5, 0.6.
    by_wall = {n.wall_label: n for n in res.notches}
    for lbl, d in (("x-", 0.4), ("y-", 0.5), ("piso", 0.6)):
        f_teor = C0 / (4 * d)
        ok &= _ok(f"shoebox notch {lbl}",
                  abs(by_wall[lbl].f_notch - f_teor) < 1e-6,
                  f"{by_wall[lbl].f_notch:.1f} Hz (d={d})")
    return ok


def test_stereo_sum():
    """2 fuentes: la curva total usa la suma compleja de presiones (no el
    promedio de las curvas dB individuales)."""
    f = np.linspace(20.0, 500.0, 1000)
    wall = Wall([0, 0, 0], [1, 0, 0], "pared", R=1.0)
    Q = np.ones((len(f), 2), dtype=complex)
    pos = [[0.5, -1.0, 0], [0.5, 1.0, 0]]   # par simetrico
    res = sbir_response(pos, Q, [wall], [50.0, 0, 0], f)
    # total_p_direct = suma de los p_direct de cada fuente.
    sum_dir = res.per_source[0].p_direct + res.per_source[1].p_direct
    ok = _ok("total = suma compleja de p_dir",
             np.allclose(res.total_p_direct, sum_dir, rtol=1e-9),
             "")
    # Y hay una curva por fuente + el total.
    ok &= _ok("2 curvas por fuente", len(res.per_source) == 2)
    return ok


def test_modal_crossfade():
    """El hibrido modal+SBIR: modal en graves, SBIR en agudos, crossfade en f_S."""
    f = np.geomspace(20.0, 500.0, 1000)
    fs = 120.0
    # curvas sinteticas bien distintas para ver de cual sale cada tramo
    modal = np.full_like(f, -8.0)       # "modal" = -8 dB en todos lados
    sbir = np.full_like(f, +4.0)        # "sbir"  = +4 dB en todos lados
    tot = modal_sbir_crossfade(f, sbir, modal, fs, transition_oct=0.5)
    lo = fs * 2 ** -0.5
    hi = fs * 2 ** +0.5
    ok = _ok("debajo del crossfade -> modal (-8 dB)",
             np.allclose(tot[f <= lo], -8.0, atol=1e-9),
             f"max {np.max(np.abs(tot[f<=lo]+8)):.1e}")
    ok &= _ok("encima del crossfade -> SBIR (+4 dB)",
              np.allclose(tot[f >= hi], 4.0, atol=1e-9),
              f"max {np.max(np.abs(tot[f>=hi]-4)):.1e}")
    # en f_S el peso es 0.5 -> promedio de ambos
    i_fs = int(np.argmin(np.abs(f - fs)))
    ok &= _ok("en f_S -> promedio (w=0.5)",
              abs(tot[i_fs] - (-8.0 + 4.0) / 2.0) < 0.1,
              f"tot(f_S)={tot[i_fs]:.2f}")
    # monotona en la transicion (de -8 a +4 al subir f)
    trans = (f > lo) & (f < hi)
    ok &= _ok("transicion monotona (modal->sbir)",
              bool(np.all(np.diff(tot[trans]) >= -1e-9)),
              "")
    # continuidad en los bordes (sin salto)
    ok &= _ok("continua en los bordes del crossfade",
              abs(tot[f <= lo][-1] - tot[trans][0]) < 0.2
              and abs(tot[trans][-1] - tot[f >= hi][0]) < 0.2, "")
    return ok


def main():
    print("bench_sbir.py — oraculos analiticos de SBIR\n")
    tests = [
        ("notch c/(4d)",      test_notch_c_4d),
        ("flush mount",       test_flush_mount),
        ("boundary lift",     test_boundary_lift),
        ("material R",         test_material_R),
        ("shoebox 6 paredes", test_shoebox6),
        ("stereo suma",        test_stereo_sum),
        ("hibrido modal+SBIR", test_modal_crossfade),
    ]
    all_ok = True
    for name, fn in tests:
        print(f"[{name}]")
        all_ok &= fn()
        print()
    print("=" * 50)
    print("TODOS OK" if all_ok else "HAY FALLAS")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
