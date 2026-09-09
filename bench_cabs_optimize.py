"""
bench_cabs_optimize.py
======================

Oraculos de `cabs_optimize.optimize_cabs` (discriminacion/optimizacion parcial,
item 6). Asserts falsables, cada uno con su racional.

Los tests que liberan delay/polaridad usan `criterion="cabs"` (modo MANEJADO: el
drive del trasero es libre, es lo que estos tests ejercitan). La consistencia
optimizar<->evaluar bajo `criterion="dba"` (el drive lo fija el criterio) vive en
`bench_cabs_criterion.py`.

Correr:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_cabs_optimize.py
"""

from __future__ import annotations

import numpy as np

import cabs_optimize as opt
from sources import OmniSource

DIMS = (5.0, 6.2, 3.0)
AXIS = 1
RX = (2.5, 3.1, 1.2)
FMAX = 120.0
_n = _ok = 0


def check(name, cond, detail=""):
    global _n, _ok
    _n += 1
    _ok += 1 if cond else 0
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def _subs(free_f, free_r):
    return [
        OmniSource((2.5, 0.1, 1.0), label="F", source_type="subwoofer",
                   free_vars=free_f),
        OmniSource((2.5, 6.1, 1.0), label="R", source_type="subwoofer",
                   polarity=-1, delay_s=0.0, free_vars=free_r),
    ]


def test_no_free_no_change():
    """T1: sin variables libres, el optimizador NO toca nada (config intacta)."""
    print("T1 sin free_vars -> no cambia")
    subs = _subs(frozenset(), frozenset())
    r = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=10)
    check("no hay DOF", len(r["dofs"]) == 0)
    check("improved=False", r["improved"] is False)
    check("posiciones intactas",
          r["optimized"][0].position == subs[0].position
          and r["optimized"][1].position == subs[1].position)


def test_improves():
    """T2: con 2 subs desalineados y {pos,delay} libres, baja el costo flat+spatial."""
    print("T2 optimiza -> baja el costo")
    subs = _subs({"pos", "delay"}, {"pos", "delay"})
    r = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=18,
                          criterion="cabs")
    c0 = r["before"]["flat"] + r["before"]["spatial"]
    c1 = r["after"]["flat"] + r["after"]["spatial"]
    check("costo despues < antes", c1 < c0, f"{c0:.2f} -> {c1:.2f}")
    check("improved=True", r["improved"] is True)


def test_wall_constraint():
    """T3: al liberar pos de un sub de pared, su coordenada en el EJE de
    enfrentamiento NO cambia (se queda en la pared); las transversales si."""
    print("T3 el sub no se despega de la pared")
    subs = _subs({"pos"}, {"pos"})
    r = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=12)
    f0, f1 = subs[0], r["optimized"][0]
    check("coordenada del eje (Y) intacta en el front",
          abs(f1.position[AXIS] - f0.position[AXIS]) < 1e-9,
          f"y {f0.position[AXIS]} -> {f1.position[AXIS]}")
    moved_transverse = (abs(f1.position[0] - f0.position[0]) > 1e-3
                        or abs(f1.position[2] - f0.position[2]) > 1e-3)
    check("se movio en el plano de la pared (X/Z)", moved_transverse)


def test_fixed_untouched():
    """T4: con una fuente libre y otra FIJA, la fija queda iduntica."""
    print("T4 la fuente fija no se toca")
    subs = _subs({"pos", "delay"}, frozenset())   # solo el front es libre
    r = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=12,
                          criterion="cabs")
    rear0, rear1 = subs[1], r["optimized"][1]
    check("rear (fija): posicion intacta", rear1.position == rear0.position)
    check("rear (fija): delay intacto", rear1.delay_s == rear0.delay_s)
    check("solo 1 fuente libre", r["n_free"] == 1)


def _cost_at_polarity(pol, tau, L):
    """flat+spatial con el trasero a polaridad `pol` (para saber cual es mejor)."""
    import numpy as np
    import dba_evaluate as dev
    subs = [OmniSource((2.5, 0.1, 1.0), label="F", source_type="subwoofer"),
            OmniSource((2.5, L - 0.1, 1.0), label="R", source_type="subwoofer",
                       delay_s=tau, polarity=pol)]
    fa = np.linspace(20.0, FMAX, 70)
    m = dev._config_metrics(subs, DIMS, (0, 0, 0), None, RX, axis=AXIS, fa=fa,
                            xi=0.03, c=343.0, f_s=180.0, with_decay=False)
    return m["flat"] + m["spatial"]


def test_polarity_flip():
    """T5 (mecanismo): el optimizador EXPLORA la polaridad y elige la mejor. Se
    determina cual polaridad da menor costo, se ARRANCA en la peor liberando solo
    'polarity', y se verifica que el optimizador termina en la mejor y mejora.
    (Para subs PUNTUALES la inversion no siempre ayuda: la cancelacion polo-cero
    del DBA es de pistones de pared, no de monopolos; por eso el test no asume el
    signo, solo que el optimizador encuentra el optimo binario.)"""
    print("T5 el optimizador elige la mejor polaridad")
    L = DIMS[AXIS]
    tau = L / 343.0
    c_plus, c_minus = _cost_at_polarity(1, tau, L), _cost_at_polarity(-1, tau, L)
    better = 1 if c_plus < c_minus else -1
    worse = -better
    subs = [
        OmniSource((2.5, 0.1, 1.0), label="F", source_type="subwoofer"),
        OmniSource((2.5, L - 0.1, 1.0), label="R", source_type="subwoofer",
                   delay_s=tau, polarity=worse, free_vars={"polarity"}),
    ]
    r = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=10,
                          criterion="cabs")
    rear = r["optimized"][1]
    c0 = r["before"]["flat"] + r["before"]["spatial"]
    c1 = r["after"]["flat"] + r["after"]["spatial"]
    check("el optimizador eligio la MEJOR polaridad", rear.polarity == better,
          f"arranco {worse}, termino {rear.polarity}, mejor={better}")
    check("mejoro el criterio", c1 < c0 - 1e-6, f"{c0:.2f} -> {c1:.2f}")


if __name__ == "__main__":
    print("=" * 60)
    print("bench_cabs_optimize.py  —  optimizacion parcial CABS")
    print("=" * 60)
    test_no_free_no_change()
    test_improves()
    test_wall_constraint()
    test_fixed_untouched()
    test_polarity_flip()
    print("-" * 60)
    print(f"  {_ok}/{_n} checks OK")
    if _ok != _n:
        raise SystemExit(1)
