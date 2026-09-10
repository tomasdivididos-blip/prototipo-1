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
    if "level" in fv and getattr(src, "sensitivity_dB", None) is not None:
        # Nivel = sensibilidad (dB SPL @1W/1m). Se libera +-12 dB alrededor del
        # valor actual, acotado al rango del spinner [40,130]. El MSO (Welti &
        # Devantier, JAES 54, 2006) optimiza ganancia ademas de delay/pos/pol.
        s0 = float(src.sensitivity_dB)
        out.append(("level", None, max(40.0, s0 - 12.0), min(130.0, s0 + 12.0)))
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
        elif kind == "level":
            from sources import q_from_sensitivity
            s.sensitivity_dB = float(val)
            s.Q = q_from_sensitivity(float(val), s.power_W, s.f_ref)
    return out


# ---------------------------------------------------------------------------
# Criterio DBA: el drive del array lo FIJA el criterio (no lo optimiza)
# ---------------------------------------------------------------------------
def _apply_dba_drive(sources, dims, origin, axis, c):
    """Bajo criterio DBA fija el drive CANONICO en los subs clasificados cuyo drive
    el usuario LIBERO (delay/polarity en free_vars): front -> delay 0, polaridad +1;
    rear -> delay L/c, polaridad -1. Devuelve (sources_mod, excluded) donde
    `excluded` = set de (src_index, kind) a sacar de los DOFs (el criterio los fija,
    el optimizador ya no los busca -> optimizar y evaluar concuerdan).

    Los subs sin free_vars de drive quedan INTACTOS (una fuente fija es fija): el
    criterio solo actua sobre lo que el usuario declaro ajustable. Los 'other' (no
    subs / fuera de pared) no se tocan."""
    roles = dev.classify_sources(sources, dims, origin, axis)
    L = float(dims[axis])
    tau = L / c
    out = [replace(s) for s in sources]
    excluded = set()
    for r in roles:
        if r.role not in ("front", "rear"):
            continue
        fv = getattr(sources[r.index], "free_vars", frozenset()) or frozenset()
        s = out[r.index]
        if "delay" in fv:
            s.delay_s = 0.0 if r.role == "front" else tau
            excluded.add((r.index, "delay"))
        if "polarity" in fv:
            s.polarity = 1 if r.role == "front" else -1
            excluded.add((r.index, "polarity"))
    return out, excluded


# ---------------------------------------------------------------------------
# Optimizacion
# ---------------------------------------------------------------------------
def _cost(x, sources, dofs, dims, origin, walls, receiver, axis, fa, xi, c, f_s,
          basis, zone_box, inside_fn=None):
    cand = apply_vector(sources, dofs, x)
    m = dev._config_metrics(cand, dims, origin, walls, receiver, axis=axis, fa=fa,
                            xi=xi, c=c, f_s=f_s, basis=basis, with_decay=False,
                            zone_box=zone_box)
    pen = 0.0
    # Restriccion dura: ninguna fuente MOVIDA puede quedar fuera del recinto
    # real. Las cotas de caja son el AABB; en un recinto irregular el AABB es mas
    # grande que la planta, asi que un movimiento transversal puede caer dentro
    # del AABB pero fuera del poligono -> se penaliza fuerte (100 dB por fuente
    # afuera, muy por encima de la escala del objetivo ~pocos dB).
    if inside_fn is not None:
        pos_idx = {i for (i, k, *_r) in dofs if k == "pos"}
        for i in pos_idx:
            try:
                if not inside_fn(cand[i].position):
                    pen += 100.0
            except Exception:
                pass
    return float(m["flat"] + m["spatial"] + pen)


def _criterion_drive_changes(orig, base, excluded) -> list:
    """Resumen legible del drive que FIJO el criterio (delay/polaridad canonicos)."""
    out = []
    for (i, kind) in sorted(excluded):
        b, a = orig[i], base[i]
        label = getattr(b, "label", "") or f"S{i+1}"
        if kind == "delay" and abs(a.delay_s - b.delay_s) > 1e-6:
            out.append(f"{label}: delay {b.delay_s*1e3:.1f} -> {a.delay_s*1e3:.1f} "
                       "ms (DBA canonico)")
        elif kind == "polarity" and a.polarity != b.polarity:
            _p = lambda s: "invertida" if s.polarity < 0 else "normal"
            out.append(f"{label}: polaridad {_p(b)} -> {_p(a)} (DBA canonico)")
    return out


def optimize_cabs(sources, dims, receiver, *, origin=(0.0, 0.0, 0.0), walls=None,
                  axis: Optional[int] = None, fmin: float = 20.0, fmax: float = 200.0,
                  xi: float = 0.03, c: float = C0, f_schroeder: Optional[float] = None,
                  n_freq: int = 70, grid=(3, 2, 3), maxiter: int = 25,
                  popsize: int = 12, seed: int = 0, criterion: str = "dba",
                  inside_fn=None) -> dict:
    """Optimiza las variables liberadas de las fuentes (item 6). Devuelve dict con
    la config optimizada, metricas antes/despues, los DOF y un resumen de cambios.

    Objetivo = flat + spatial de la respuesta TOTAL (evaluate_cabs). Grilla y n_freq
    gruesos para ir rapido (el objetivo se llama cientos de veces); la evaluacion
    'oficial' de alta fidelidad se hace aparte con `evaluate_cabs`.

    `criterion` ("dba" | "cabs") es EL MISMO que se le pasa a `evaluate_cabs`, para
    que optimizar y evaluar sigan UN SOLO criterio (cierra el bug del delay 2x):
      - "dba": el drive del array lo FIJA el criterio (front 0/+1, rear L/c/-1) y
        sale de los DOFs -> el optimizador solo mueve posicion/fc dentro de esa
        forma. El resultado satisface el chequeo DBA de evaluate por construccion.
      - "cabs": el drive del trasero queda LIBRE (manejado); el optimizador lo busca
        para aplanar y evaluate lo juzga por el colapso, no por L/c.
    """
    from scipy.optimize import differential_evolution
    dims = tuple(float(x) for x in dims)
    origin = np.asarray(origin, dtype=float)
    active = [s for s in sources if getattr(s, "active", True)]
    if axis is None:
        axis = dev.best_axis(active, dims, origin, c)

    # Criterio: bajo DBA el drive del array lo fija el criterio y sale de los DOFs;
    # bajo CABS el drive queda libre (el optimizador lo busca).
    if criterion == "dba":
        base, excluded = _apply_dba_drive(sources, dims, origin, axis, c)
    else:
        base, excluded = [replace(s) for s in sources], set()

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
    dofs = [d for d in collect_dofs(base, dims, origin, axis)
            if (d[0], d[1]) not in excluded]
    crit_changes = _criterion_drive_changes(sources, base, excluded)

    if not dofs:
        # Sin DOFs continuos: o no hay nada libre (config intacta), o el criterio ya
        # fijo el drive (DBA) y no queda mas que optimizar.
        after = _metrics(base) if excluded else before
        improved = (after["flat"] + after["spatial"]
                    < before["flat"] + before["spatial"] - 1e-6)
        return {"optimized": base, "before": before, "after": after, "dofs": [],
                "result": None, "improved": bool(improved), "axis": axis,
                "n_free": 0, "changes": crit_changes, "criterion": criterion}

    bounds = [(lo, hi) for (_i, _k, _a, lo, hi) in dofs]
    # La polaridad es entera (binaria): scipy>=1.9 la maneja con integrality.
    # Si la version es vieja (sin integrality), apply_vector igual la umbrala en
    # 0.5, asi que el fallback es correcto (solo un poco menos eficiente).
    integrality = [k == "polarity" for (_i, k, _a, _lo, _hi) in dofs]
    kw = dict(args=(base, dofs, dims, origin, walls, receiver, axis, fa, xi, c,
                    f_s, basis, zone_box, inside_fn),
              maxiter=maxiter, popsize=popsize, seed=seed, tol=1e-3,
              mutation=(0.5, 1.0), recombination=0.7, polish=True,
              updating="deferred")
    try:
        res = differential_evolution(_cost, bounds, integrality=integrality, **kw)
    except TypeError:                          # scipy viejo: sin integrality
        res = differential_evolution(_cost, bounds, **kw)

    best = apply_vector(base, dofs, res.x)
    after = _metrics(best)
    improved = (after["flat"] + after["spatial"]
                < before["flat"] + before["spatial"] - 1e-6)
    n_free = len({i for (i, *_r) in dofs})
    return {"optimized": best, "before": before, "after": after, "dofs": dofs,
            "result": res, "improved": improved, "axis": axis, "n_free": n_free,
            "changes": crit_changes + summarize_changes(sources, best, dofs),
            "criterion": criterion}


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
        elif kind == "level":
            b0 = b.sensitivity_dB if b.sensitivity_dB is not None else 0.0
            a0 = a.sensitivity_dB if a.sensitivity_dB is not None else 0.0
            if abs(a0 - b0) > 1e-3:
                out.append(f"{label}: nivel {b0:.1f} -> {a0:.1f} dB SPL")
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
