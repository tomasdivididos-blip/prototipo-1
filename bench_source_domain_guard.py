"""
bench_source_domain_guard.py
============================

Oraculos del fix A1+A3 (22 Sep 2026, bug del profesor via 'Control Ale.room').

SINTOMA: tras optimizar las fuentes en un recinto con techo a dos aguas (gable, NO
convexo), aplicar y recalcular la FRF daba una RECTA PLANA a ~-506 dB (y el SBIR lo
mismo). CAUSA RAIZ: el dominio 'adentro' usado por el optimizador era
`points_inside_surface` (paridad de rayo, 1 direccion), que en un techo no-convexo da
FALSOS 'adentro' en una cascara sobre el cielorraso inclinado. Ahi el campo modal FEM
esta indefinido y el acople fuente-modo es 0 exacto
(acoustic_fem._source_modal_coupling). El optimizador podia parkear un sub z-libre en
esa cascara sin penalizacion -> run_fem_frf devolvia H=0 -> `20 log10(0/20e-6) ~ -506`.

A1: el `inside_fn` del optimizador usa el DOMINIO FEM real (los tets: campo != NaN),
    el MISMO que evalua run_fem_frf. Asi optimizar y evaluar comparten un dominio y la
    cascara de falso-positivo queda CERRADA.
A3: `AcousticPanel._decoupled_active_sources` detecta fuentes con acople ~0 para AVISAR
    en vez de dibujar la recta enganosa (la logica de guarda vive en _compute_frf /
    _open_sbir; aca se testea el detector, que es su nucleo).

Falsable, autocontenido. Correr:
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 \
    /c/Users/aceve/anaconda3/python.exe bench_source_domain_guard.py
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PROTO1_WATCHDOG", "0")

import numpy as np

import geometry
import acoustic_analysis as aa
import acoustic_fem
import cabs_optimize as copt
from acoustic_mesh import points_inside_surface
from sources import OmniSource

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


def _gable_room():
    """Recinto 4.8x3.9x3.1 con techo a dos aguas (como 'Control Ale.room'): NO convexo,
    AABB en z hasta el pico (~4.3). Devuelve (verts, tris, modal)."""
    v, t, _e, _n = geometry.make_room(
        4.8, 3.9, 3.1, n_walls=4, roof_type="gable",
        arch_height=1.2, ridge_offset=-0.04, subdiv_levels=0)
    v = np.asarray(v, dtype=float)
    # anclar a esquina (como el .room con origin_mode='corner')
    v = v - np.array([v[:, 0].min(), v[:, 1].min(), 0.0])
    ti = np.asarray(t, dtype=int)
    mr = aa.run_fem_modal(v, ti, n_modes=20, n_per_meter=4.0)
    return v, ti, mr


def _tet_inside_fn(mr):
    """Reproduce el inside_fn de A1 (dominio FEM = campo definido en los tets)."""
    ones = np.ones(np.asarray(mr.phis).shape[0], dtype=complex)

    def _fn(p, _loc=mr.locator, _ones=ones):
        pt = np.asarray(p, dtype=float).reshape(1, 3)
        return bool(np.isfinite(np.real(np.asarray(_loc.evaluate_many(_ones, pt))[0])))
    return _fn


def _kappa_norm(mr, pos):
    s = OmniSource(tuple(float(x) for x in pos), source_type="subwoofer", label="p")
    k = acoustic_fem._source_modal_coupling(mr.locator, mr.phis, [s])
    return float(np.linalg.norm(np.asarray(k[0], dtype=float)))


def main():
    v, ti, mr = _gable_room()
    inside_fem = _tet_inside_fn(mr)

    # --- 0) el escenario tiene la patologia: existe la cascara de falso-positivo ---
    mn, mx = v.min(0), v.max(0)
    rng = np.random.default_rng(0)
    P = rng.uniform(mn, mx, size=(4000, 3))
    ray = points_inside_surface(P, v, ti)
    ones = np.ones(mr.phis.shape[0], dtype=complex)
    fld = mr.locator.evaluate_many(ones, P)
    in_tet = np.isfinite(np.real(np.asarray(fld)))
    false_pos = ray & (~in_tet)
    check("el gable tiene cascara de falso-positivo (rayo si, tet no)",
          false_pos.sum() > 0, f"{int(false_pos.sum())} pts, todos en el techo")
    if false_pos.sum():
        zmin_fp = float(P[false_pos][:, 2].min())
        check("la cascara esta ARRIBA (sobre el cielorraso inclinado)",
              zmin_fp > 0.6 * mx[2], f"z_min falso-positivo={zmin_fp:.2f} > {0.6*mx[2]:.2f}")

    # --- 1) A1: el dominio tet RECHAZA la cascara; el rayo la ACEPTA (el bug) ---
    shell = P[false_pos][:6]
    n_ray_yes = sum(bool(points_inside_surface(np.asarray(q).reshape(1, 3), v, ti)[0])
                    for q in shell)
    n_tet_no = sum(0 if inside_fem(q) else 1 for q in shell)
    check("A1: inside_fn(tet) rechaza TODA la cascara que el rayo aceptaba",
          n_ray_yes == len(shell) and n_tet_no == len(shell),
          f"rayo-si={n_ray_yes}/{len(shell)}, tet-no={n_tet_no}/{len(shell)}")
    for q in shell[:3]:
        check(f"  acople 0 en la cascara {tuple(round(x,2) for x in q)}",
              _kappa_norm(mr, q) < 1e-12)

    # --- 2) A1: el optimizador (flat) YA NO expulsa los subs con inside_fn=tet ---
    subs = [OmniSource((4.4, 3.4, 1.6), source_type="subwoofer", label="Sub L",
                       free_vars=frozenset({"pos", "delay", "polarity"})),
            OmniSource((0.4, 3.4, 0.4), source_type="subwoofer", label="Sub R",
                       free_vars=frozenset({"pos", "delay", "polarity"}))]
    fem = {"locator": mr.locator, "freqs": mr.freqs, "phis": mr.phis, "xi": 0.03}
    origin = tuple(v.min(0).tolist())
    dims = tuple((v.max(0) - v.min(0)).tolist())
    rec = (2.28, 1.74, 1.15)
    res = copt.optimize_cabs(
        subs, dims, tuple((np.asarray(rec) - v.min(0)).tolist()), origin=origin,
        criterion="flat", maxiter=25, popsize=12, inside_fn=inside_fem, seed=7, fem=fem)
    ks = [_kappa_norm(mr, s.position) for s in res["optimized"]]
    check("A1: tras optimizar (flat), TODOS los subs siguen acoplados (k>0)",
          all(k > 1e-6 for k in ks), f"||k||={[round(k,3) for k in ks]}")
    check("A1: ninguna posicion optimizada cae fuera del dominio FEM",
          all(inside_fem(s.position) for s in res["optimized"]))

    # --- 3) A1 (control): con el inside_fn VIEJO (rayo) el bug era POSIBLE ---
    # (no re-optimizamos por costo; basta mostrar que el rayo NO lo hubiera frenado)
    q0 = shell[0]
    check("A1 (control): el rayo viejo NO habria penalizado la cascara",
          bool(points_inside_surface(np.asarray(q0).reshape(1, 3), v, ti)[0]) is True)

    # --- 4) A3: el detector encuentra las desacopladas y respeta las interiores ---
    #   (probamos la logica de _decoupled_active_sources con un panel minimo)
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from viewer import IsoViewer
    import acoustic_panel as ap
    panel = ap.AcousticPanel(viewer=IsoViewer(), get_surface=lambda: (v, ti),
                             get_dims_hint=lambda: (4.8, 3.9, 3.1))
    panel.modal_result = mr
    bad = [OmniSource(tuple(shell[0]), source_type="subwoofer", label="BAD1"),
           OmniSource(tuple(shell[1]), source_type="subwoofer", label="BAD2")]
    good = [OmniSource((2.28, 1.74, 1.0), source_type="subwoofer", label="GOOD")]
    dec_bad = panel._decoupled_active_sources(bad)
    dec_good = panel._decoupled_active_sources(good)
    check("A3: detecta AMBAS fuentes de la cascara como desacopladas",
          len(dec_bad) == 2, f"detectadas={[s.label for s in dec_bad]}")
    check("A3: NO marca una fuente interior valida",
          len(dec_good) == 0, f"detectadas={[s.label for s in dec_good]}")
    dec_mix = panel._decoupled_active_sources(bad + good)
    check("A3: en config mixta separa desacopladas de acopladas (2 de 3)",
          len(dec_mix) == 2 and all(s.label.startswith("BAD") for s in dec_mix))
    check("A3: sin modos -> [] (no puede juzgar)",
          ap.AcousticPanel._decoupled_active_sources.__get__(
              type("P", (), {"modal_result": None})())(bad) == [])

    # --- 5) A2: _snap_source_into_domain proyecta al interior lo que cae afuera ---
    # 5a) un punto de la cascara (fuera de los tets) se reubica y queda acoplado
    p_out = tuple(shell[0])
    snapped_pos, moved = panel._snap_source_into_domain(p_out)
    check("A2: un punto de la cascara se marca como movido", moved is True)
    check("A2: la posicion reubicada cae DENTRO del dominio FEM",
          inside_fem(snapped_pos), f"{tuple(round(x,2) for x in snapped_pos)}")
    check("A2: la fuente reubicada YA acopla (k>0)",
          _kappa_norm(mr, snapped_pos) > 1e-6,
          f"||k||={_kappa_norm(mr, snapped_pos):.3e}")
    # 5b) un punto interior NO se toca
    p_in = (2.28, 1.74, 1.0)
    same_pos, moved2 = panel._snap_source_into_domain(p_in)
    check("A2: un punto interior NO se mueve",
          (moved2 is False) and np.allclose(same_pos, p_in))
    # 5c) el falso-positivo de z MAS ALTO (garantizado sobre las aguas, fuera de los
    #     tets) se rescata al interior: es el peor caso del clamp al AABB del render.
    fp_pts = P[false_pos]
    peak = tuple(fp_pts[int(np.argmax(fp_pts[:, 2]))])
    rescued, mv = panel._snap_source_into_domain(peak)
    check("A2: el falso-positivo mas alto (sobre las aguas) se rescata al interior",
          (not inside_fem(peak)) and mv and inside_fem(rescued),
          f"peak z={peak[2]:.2f} -> rescatado z={rescued[2]:.2f}")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
