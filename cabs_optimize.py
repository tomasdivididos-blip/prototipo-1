"""
cabs_optimize.py
================

Discriminacion / optimizacion parcial (item 6 de `plan_modelo_fuente.md`, Opcion C
granular). El usuario marca, POR FUENTE, que variables puede tocar el optimizador
(`OmniSource.free_vars` subset de {"pos","delay","fc","filter"}); las fuentes con
`free_vars` vacio quedan FIJAS. El optimizador mueve solo los grados de libertad
liberados para minimizar el criterio CABS (planitud + varianza espacial de la
respuesta TOTAL = SBIR + modos), usando `dba_evaluate.evaluate_cabs` como funcion
objetivo.

Este primer cut optimiza las variables CONTINUAS (pos, delay, fc) con
`scipy.optimize.differential_evolution` (global, acotado; scipy puro -> respeta D0).
La familia de filtro (discreta) queda para un paso posterior (bucle anidado, ver
mini-spec). Sin fuentes libres -> no hace nada (devuelve la config intacta).

Precedente: MSO (Multi-Sub Optimizer) y Welti & Devantier (JAES 54, 2006).
"""

from __future__ import annotations

import numpy as np
from dataclasses import replace
from typing import List, Optional

from sources import C0
import dba_evaluate as dev
import dba as _dba


# ---------------------------------------------------------------------------
# Grados de libertad (DOF) continuos de las fuentes libres
# ---------------------------------------------------------------------------
def _source_dofs(src, dims, origin, enf_axis):
    """DOF continuos de UNA fuente segun su free_vars: lista de
    (kind, axis_or_None, lo, hi) en coords MUNDO.

    Para "pos" se liberan SOLO los dos ejes TRANSVERSALES al de enfrentamiento
    (`enf_axis`): el sub se mueve EN el plano de su pared, pero NO se despega de
    ella (mantener el sub en la pared es condicion del CABS; liberar el eje de
    enfrentamiento lo sacaria del array). El eje de enfrentamiento queda fijo en
    su valor actual."""
    fv = getattr(src, "free_vars", frozenset()) or frozenset()
    out = []
    if "pos" in fv:
        for k in range(3):
            if k == enf_axis:
                continue                       # se queda en la pared
            out.append(("pos", k, origin[k] + 0.15, origin[k] + dims[k] - 0.15))
    if "delay" in fv:
        out.append(("delay", None, 0.0, 1.5 * max(dims) / C0))
    if "fc" in fv and getattr(src, "filter_type", "none") != "none":
        out.append(("fc", None, 20.0, 300.0))
    if "polarity" in fv:
        out.append(("polarity", None, 0.0, 1.0))    # binaria: 0->+1, 1->-1
    return out


def collect_dofs(sources, dims, origin, enf_axis):
    """Todos los DOF de las fuentes ACTIVAS libres: (src_index, kind, axis, lo, hi)."""
    origin = np.asarray(origin, dtype=float)
    dofs = []
    for i, s in enumerate(sources):
        if not getattr(s, "active", True):
            continue
        for (kind, ax, lo, hi) in _source_dofs(s, dims, origin, enf_axis):
            dofs.append((i, kind, ax, lo, hi))
    return dofs


def apply_vector(sources, dofs, x):
    """Aplica el vector x (un valor por DOF) sobre COPIAS de las fuentes."""
    out = [replace(s) for s in sources]        # copias (response compartida, ok)
    for (i, kind, ax, lo, hi), val in zip(dofs, x):
        s = out[i]
        if kind == "pos":
            p = list(s.position); p[ax] = float(val)
            s.position = (p[0], p[1], p[2])
        elif kind == "delay":
            s.delay_s = float(val)
        elif kind == "fc":
            s.filter_fc = float(val)
        elif kind == "polarity":
            s.polarity = -1 if float(val) >= 0.5 else 1
    return out


# ---------------------------------------------------------------------------
# Optimizacion
# ---------------------------------------------------------------------------
def _cost(x, sources, dofs, dims, origin, walls, receiver, axis, fa, xi, c, f_s,
          basis, zone_box):
    cand = apply_vector(sources, dofs, x)
    m = dev._config_metrics(cand, dims, origin, walls, receiver, axis=axis, fa=fa,
                            xi=xi, c=c, f_s=f_s, basis=basis, with_decay=False,
                            zone_box=zone_box)
    return float(m["flat"] + m["spatial"])


def optimize_cabs(sources, dims, receiver, *, origin=(0.0, 0.0, 0.0), walls=None,
                  axis: Optional[int] = None, fmin: float = 20.0, fmax: float = 200.0,
                  xi: float = 0.03, c: float = C0, f_schroeder: Optional[float] = None,
                  n_freq: int = 70, grid=(3, 2, 3), maxiter: int = 25,
                  popsize: int = 12, seed: int = 0) -> dict:
    """Optimiza las variables liberadas de las fuentes (item 6). Devuelve dict con
    la config optimizada, metricas antes/despues, los DOF y un resumen de cambios.

    Objetivo = flat + spatial de la respuesta TOTAL (evaluate_cabs). Grilla y n_freq
    gruesos para ir rapido (el objetivo se llama cientos de veces); la evaluacion
    'oficial' de alta fidelidad se hace aparte con `evaluate_cabs`.
    """
    from scipy.optimize import differential_evolution
    dims = tuple(float(x) for x in dims)
    origin = np.asarray(origin, dtype=float)
    active = [s for s in sources if getattr(s, "active", True)]
    if axis is None:
        axis = dev.best_axis(active, dims, origin, c)

    fa = np.linspace(fmin, fmax, n_freq)
    if callable(walls):
        walls = walls(fa)
    f_s = float(f_schroeder) if f_schroeder else dev._schroeder_guess(dims, xi)
    basis = dev.make_basis(dims, fmax, c)
    zone_box = _dba._zone_grid(dims, axis, grid[0], grid[1], grid[2])

    def _metrics(src_list):
        return dev._config_metrics(src_list, dims, origin, walls, receiver,
                                   axis=axis, fa=fa, xi=xi, c=c, f_s=f_s,
                                   basis=basis, with_decay=False, zone_box=zone_box)

    before = _metrics(sources)
    dofs = collect_dofs(sources, dims, origin, axis)
    if not dofs:
        return {"optimized": list(sources), "before": before, "after": before,
                "dofs": [], "improved": False, "axis": axis, "changes": [],
                "n_free": 0}

    bounds = [(lo, hi) for (_i, _k, _a, lo, hi) in dofs]
    # La polaridad es entera (binaria): scipy>=1.9 la maneja con integrality.
    # Si la version es vieja (sin integrality), apply_vector igual la umbrala en
    # 0.5, asi que el fallback es correcto (solo un poco menos eficiente).
    integrality = [k == "polarity" for (_i, k, _a, _lo, _hi) in dofs]
    kw = dict(args=(sources, dofs, dims, origin, walls, receiver, axis, fa, xi, c,
                    f_s, basis, zone_box),
              maxiter=maxiter, popsize=popsize, seed=seed, tol=1e-3,
              mutation=(0.5, 1.0), recombination=0.7, polish=True,
              updating="deferred")
    try:
        res = differential_evolution(_cost, bounds, integrality=integrality, **kw)
    except TypeError:                          # scipy viejo: sin integrality
        res = differential_evolution(_cost, bounds, **kw)

    best = apply_vector(sources, dofs, res.x)
    after = _metrics(best)
    improved = (after["flat"] + after["spatial"]
                < before["flat"] + before["spatial"] - 1e-6)
    n_free = len({i for (i, *_r) in dofs})
    return {"optimized": best, "before": before, "after": after, "dofs": dofs,
            "result": res, "improved": improved, "axis": axis, "n_free": n_free,
            "changes": summarize_changes(sources, best, dofs)}


def summarize_changes(before_sources, after_sources, dofs) -> list:
    """Resumen legible de que cambio (por fuente/variable): viejo -> nuevo."""
    out = []
    seen = set()
    for (i, kind, ax, lo, hi) in dofs:
        b, a = before_sources[i], after_sources[i]
        label = getattr(b, "label", "") or f"S{i+1}"
        if kind == "pos":
            key = (i, "pos")
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{label}: posicion {tuple(round(v,2) for v in b.position)} "
                       f"-> {tuple(round(v,2) for v in a.position)}")
        elif kind == "delay":
            out.append(f"{label}: delay {b.delay_s*1e3:.1f} -> {a.delay_s*1e3:.1f} ms")
        elif kind == "fc":
            out.append(f"{label}: corte {b.filter_fc:.0f} -> {a.filter_fc:.0f} Hz")
        elif kind == "polarity":
            _p = lambda s: "invertida" if s.polarity < 0 else "normal"
            if _p(a) != _p(b):
                out.append(f"{label}: polaridad {_p(b)} -> {_p(a)}")
    return out


if __name__ == "__main__":
    # Smoke: una config con 2 subs enfrentados pero DESALINEADOS (delay y posicion
    # subatimos), 2 fuentes libres -> optimizar debe bajar flat+spatial.
    from sources import OmniSource
    dims = (5.0, 6.2, 3.0)
    subs = [
        OmniSource((2.5, 0.1, 1.0), label="F", source_type="subwoofer",
                   free_vars={"pos", "delay"}),
        OmniSource((2.5, 6.1, 1.0), label="R", source_type="subwoofer",
                   polarity=-1, delay_s=0.0, free_vars={"pos", "delay"}),
    ]
    r = optimize_cabs(subs, dims, (2.5, 3.1, 1.2), axis=1, fmax=120.0,
                      maxiter=15)
    print(f"axis={r['axis']} n_free={r['n_free']}")
    print(f"antes:   flat={r['before']['flat']:.2f}  spatial={r['before']['spatial']:.2f}")
    print(f"despues: flat={r['after']['flat']:.2f}  spatial={r['after']['spatial']:.2f}")
    print(f"mejoro={r['improved']}")
    for ch in r["changes"]:
        print("  ", ch)
