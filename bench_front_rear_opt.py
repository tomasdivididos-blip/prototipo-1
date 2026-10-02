"""
bench_front_rear_opt.py
=======================

E4a de `plan_frente_opuesto_admitancia.md`: definir y validar (headless, antes de
cablear a la GUI) el NORTE de optimizacion de la interaccion front<->rear.

SUTILEZA (de E3): con fuentes REALES el drive es FEEDFORWARD (trasero proporcional
al frente, no a la p local), que NO mueve los polos modales (es redistribucion de
energia, C1). Por eso el objetivo "maximizar Delta-xi_n" NO aplica a fuentes reales;
el QEP matcheado (E3) es el TECHO ideal (feedback, mueve polos). El objetivo honesto
y alcanzable por fuentes reales es MINIMIZAR LA REFLEXION R de la pared trasera
(= cuanto absorbe el array trasero el frente de onda que impone el frontal). R->0
es el matcheado ideal; menos R = frente de onda mas viajero = campo mas plano.

El norte: coste(config trasero) = R promedio en la banda axial, con R extraido por
la descomposicion viajera de E1b (`bench_front_rear_room.decompose`). Reusa el
nucleo validado (`RectModalBasis`, `dba`), sin tocarlo.

Checks:
  T1  el coste con el array trasero (CABS, retardo L/c + inversion) es MUCHO menor
      que sin trasero (pared rigida, R~1): el norte distingue absorber de no absorber.
  T2  barrido del RETARDO tau: el minimo del coste esta cerca de tau = L/c (el
      transito), que es el drive CABS canonico.
  T3  POLARIDAD: sin inversion (sign=+1) el coste es mucho peor que con inversion.
  T4  una optimizacion chica sobre (tau, nivel) encuentra un coste <= el del CABS
      canonico (el norte es optimizable y el CABS es ~optimo).
"""

from __future__ import annotations

import numpy as np

from source_coupling import RectModalBasis, WallPiston
import dba
from sources import C0
from bench_front_rear_room import _field


def _make_cost(basis, axis, xz, xi=1e-3, frac=(0.25, 0.75), npts=161,
               fs=None):
    """Devuelve cost(tau, sign, level) = R promedio en la banda, con Phi y los
    acoplamientos precalculados (rapido para barridos/optimizacion)."""
    L = basis.dims[axis]
    a, b = tuple(i for i in (0, 1, 2) if i != axis)
    ys = np.linspace(frac[0] * L, frac[1] * L, npts)
    pts = np.zeros((npts, 3)); pts[:, axis] = ys; pts[:, a] = xz[0]; pts[:, b] = xz[1]
    Phi = basis.phi_matrix(pts)
    C_front = basis.wall_piston_coupling(WallPiston(axis=axis, side="min", vn=1.0))
    C_rear1 = basis.wall_piston_coupling(WallPiston(axis=axis, side="max", vn=1.0))
    if fs is None:
        f_ax1 = C0 / (2 * L)
        f_tr = min(C0 / (2 * basis.dims[a]), C0 / (2 * basis.dims[b]))
        fs = np.linspace(0.6 * f_ax1, 0.95 * f_tr, 7)

    def R_at(f, C):
        p = _field(basis, pts, f, C, xi, Phi)
        k = 2.0 * np.pi * f / basis.c
        M = np.column_stack([np.exp(-1j * k * ys), np.exp(+1j * k * ys)])
        coef, *_ = np.linalg.lstsq(M, p, rcond=None)
        return abs(coef[1]) / max(abs(coef[0]), 1e-30)

    def cost(tau, sign=-1.0, level=1.0):
        tot = 0.0
        for f in fs:
            vr = sign * level * np.exp(-1j * 2.0 * np.pi * f * tau)
            C = C_front + vr * C_rear1
            tot += R_at(float(f), C)
        return tot / len(fs)

    return cost, fs, L


def run():
    results = []
    dims = (3.0, 5.0, 2.8); axis = 1; L = dims[axis]
    basis = RectModalBasis(dims, fmax=1200.0, n_max=45, c=C0)
    xz = (dims[0] / 2.0, dims[2] / 2.0)
    cost, fs, _ = _make_cost(basis, axis, xz)

    tau0 = L / C0                      # transito (drive CABS canonico)
    c_rigid = cost(1e9, sign=0.0, level=0.0)       # sin trasero (pared rigida)
    c_cabs = cost(tau0, sign=-1.0, level=1.0)      # CABS: retardo L/c + inversion
    c_nopol = cost(tau0, sign=+1.0, level=1.0)     # sin inversion

    # T1: CABS << rigido.
    t1 = c_cabs < 0.5 * c_rigid and c_rigid > 0.8
    results.append(("T1 el norte distingue absorber (CABS) de no (rigido)",
                    t1, f"R_prom rigido={c_rigid:.3f} -> CABS={c_cabs:.3f}"))

    # T2: barrido del retardo -> minimo cerca de tau = L/c.
    taus = np.linspace(0.2 * tau0, 2.2 * tau0, 41)
    cs = np.array([cost(t, sign=-1.0, level=1.0) for t in taus])
    tau_min = taus[int(np.argmin(cs))]
    t2 = abs(tau_min - tau0) / tau0 < 0.15
    results.append(("T2 el minimo del retardo esta en tau ~ L/c (transito)",
                    t2, f"tau_opt={tau_min*1e3:.2f} ms vs L/c={tau0*1e3:.2f} ms "
                        f"(min R_prom={cs.min():.3f})"))

    # T3: polaridad (sin inversion es mucho peor).
    t3 = c_nopol > 2.0 * c_cabs
    results.append(("T3 polaridad: sin inversion el coste empeora mucho",
                    t3, f"R_prom CABS(inv)={c_cabs:.3f} vs sin-inv={c_nopol:.3f}"))

    # T4: optimizacion chica (tau, nivel) <= CABS canonico.
    levels = np.linspace(0.6, 1.4, 9)
    best = np.inf; best_p = None
    for t in taus:
        for lv in levels:
            cc = cost(t, sign=-1.0, level=lv)
            if cc < best:
                best, best_p = cc, (t, lv)
    t4 = best <= c_cabs + 1e-9
    results.append(("T4 optimizar (tau,nivel) alcanza o mejora el CABS canonico",
                    t4, f"mejor R_prom={best:.3f} (tau={best_p[0]*1e3:.2f} ms, "
                        f"nivel={best_p[1]:.2f}) vs CABS={c_cabs:.3f}"))

    return results


if __name__ == "__main__":
    rs = run()
    npass = sum(1 for _, ok, _ in rs if ok)
    for name, ok, detail in rs:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    print(f"\n{npass}/{len(rs)} checks OK")
    raise SystemExit(0 if npass == len(rs) else 1)
