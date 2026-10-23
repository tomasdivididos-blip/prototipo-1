"""
bench_reflections_ism.py
========================

Oraculo del ISM especular (item 1 / semilla R1 del motor de ray tracing).
Shoebox: las imagenes y sus energias son ENUMERABLES y EXACTAS, asi que se validan
contra el calculo analitico a mano.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_reflections_ism.py
"""

from __future__ import annotations

import numpy as np

import reflections_ism as ism

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


def test_axis_crossings():
    print("T1  conteo de rebotes por eje = |2n - q| y pared par/impar correcta")
    L = 5.0; s = 1.3
    # x0: n=0,q=1 -> X=-s ; cruce en 0 (par) -> n0=1,nL=0
    n0, nL = ism._axis_crossings(s, -s, L)
    check("imagen x=-s -> 1 rebote en pared 0", (n0, nL) == (1, 0), f"{(n0,nL)}")
    # xL: n=1,q=1 -> X=2L-s ; cruce en L (impar) -> n0=0,nL=1
    n0, nL = ism._axis_crossings(s, 2 * L - s, L)
    check("imagen x=2L-s -> 1 rebote en pared L", (n0, nL) == (0, 1), f"{(n0,nL)}")
    # n=1,q=0 -> X=2L+s ; cruces en L(impar) y 2L(par) -> (1,1), orden 2
    n0, nL = ism._axis_crossings(s, 2 * L + s, L)
    check("imagen x=2L+s -> 2 rebotes (1 y L)", (n0, nL) == (1, 1), f"{(n0,nL)}")


def test_order1_images():
    print("\nT2  orden 1 -> exactamente 6 imagenes (una por pared), posiciones ok")
    dims = (5.0, 4.0, 3.0); s = (1.5, 1.0, 1.2)
    ims = [im for im in ism.image_sources(s, dims, max_order=1)
           if im["order"] == 1]
    check("6 imagenes de orden 1", len(ims) == 6, f"n={len(ims)}")
    pos_by_wall = {}
    for im in ims:
        w = next(wk for wk, n in im["nref"].items() if n)
        pos_by_wall[w] = im["pos"]
    exp = {"x0": (-s[0], s[1], s[2]), "xL": (2 * 5.0 - s[0], s[1], s[2]),
           "y0": (s[0], -s[1], s[2]), "yL": (s[0], 2 * 4.0 - s[1], s[2]),
           "z0": (s[0], s[1], -s[2]), "zL": (s[0], s[1], 2 * 3.0 - s[2])}
    ok = all(w in pos_by_wall and np.allclose(pos_by_wall[w], exp[w])
             for w in exp)
    check("posiciones de las 6 imagenes = reflexion analitica", ok)


def test_order1_energy():
    print("\nT3  energia de orden 1 = (1/(4*pi*d))^2 * (1-alpha) exacta")
    dims = (5.0, 4.0, 3.0); s = (1.5, 2.0, 1.5); rec = (3.5, 2.0, 1.5)
    alpha = {"xL": 0.3}      # solo la pared xL absorbe; resto rigido
    r = ism.wall_reflection_energy(s, rec, dims, alpha, bands=np.array([1000.0]),
                                   max_order=1, air=False)
    # Imagen xL en (2*5-1.5, 2, 1.5) = (8.5,2,1.5); d a rec (3.5,2,1.5) = 5.0
    d = 8.5 - 3.5
    E_exp = (1.0 / (4 * np.pi * d)) ** 2 * (1 - 0.3)
    E_got = float(r["wall_energy"]["xL"][0])
    check("E_xL coincide con la formula", abs(E_got - E_exp) / E_exp < 1e-9,
          f"{E_got:.3e} vs {E_exp:.3e}")
    # Punto de reflexion de orden 1 en xL: el segmento (8.5,2,1.5)->(3.5,2,1.5)
    # cruza x=5 en y=2,z=1.5.
    pts = [p for (w, p, _E) in r["order1_points"] if w == "xL"]
    check("punto de reflexion en xL = (5, 2, 1.5)",
          len(pts) == 1 and np.allclose(pts[0], (5.0, 2.0, 1.5)),
          f"{pts[0] if pts else None}")


def test_monotonic():
    print("\nT4  monotonias: mas absorcion -> menos energia; mas orden -> mas total")
    dims = (6.0, 5.0, 3.0); s = (1.0, 1.0, 1.5); rec = (4.0, 3.0, 1.5)
    b = np.array([500.0])
    e_lo = ism.wall_reflection_energy(s, rec, dims, {w: 0.1 for w in ism.WALLS},
                                      bands=b, max_order=3, air=False)["total"][0]
    e_hi = ism.wall_reflection_energy(s, rec, dims, {w: 0.5 for w in ism.WALLS},
                                      bands=b, max_order=3, air=False)["total"][0]
    check("mas alpha -> menos energia total", e_hi < e_lo,
          f"{e_hi:.3e} < {e_lo:.3e}")
    e_o1 = ism.wall_reflection_energy(s, rec, dims, {w: 0.2 for w in ism.WALLS},
                                      bands=b, max_order=1, air=False)["total"][0]
    e_o3 = ism.wall_reflection_energy(s, rec, dims, {w: 0.2 for w in ism.WALLS},
                                      bands=b, max_order=3, air=False)["total"][0]
    check("orden 3 suma mas energia que orden 1", e_o3 > e_o1,
          f"{e_o3:.3e} > {e_o1:.3e}")


def test_air_band():
    print("\nT5  absorcion del aire: agudos se atenuan mas que graves")
    dims = (8.0, 6.0, 3.0); s = (1.0, 1.0, 1.5); rec = (6.0, 5.0, 1.5)
    bands = np.array([125.0, 8000.0])
    r_air = ism.wall_reflection_energy(s, rec, dims, {w: 0.1 for w in ism.WALLS},
                                       bands=bands, max_order=3, air=True)
    r_no = ism.wall_reflection_energy(s, rec, dims, {w: 0.1 for w in ism.WALLS},
                                      bands=bands, max_order=3, air=False)
    ratio_lo = r_air["total"][0] / r_no["total"][0]
    ratio_hi = r_air["total"][1] / r_no["total"][1]
    check("el aire atenua MAS en 8 kHz que en 125 Hz", ratio_hi < ratio_lo,
          f"125Hz x{ratio_lo:.3f} vs 8kHz x{ratio_hi:.3f}")


def main():
    print("=" * 68)
    print("bench_reflections_ism.py  —  ISM especular shoebox (item 1 / R1)")
    print("=" * 68)
    test_axis_crossings()
    test_order1_images()
    test_order1_energy()
    test_monotonic()
    test_air_band()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
