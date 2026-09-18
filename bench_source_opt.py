"""
bench_source_opt.py
===================

Oraculos del cambio de 15-16 Sep 2026 (pedido del profesor Bidondo, via Ale):

  1. CABS/DBA valen sobre CUALQUIER par de paredes OPUESTAS, en CUALQUIER eje, sin
     privilegiar la dimension mas larga ni etiquetar 'frente'/'trasera'. Antes, con
     2 mains adelante + 2 subs atras enfrentados en el eje CORTO, el software elegia
     el eje LARGO y fallaba ('falta full range en el frente'). Ahora `best_axis` es
     criterion-aware y elige el eje del par que cumple el criterio.

  2. El optimizador es CANCELABLE (should_cancel) y reporta progreso (progress_cb),
     para que la GUI no se 'tilde' (corre en un hilo aparte en la UI). polish=off
     -> tiempo predecible + cancel responsivo.

Falsable, autocontenido. Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_source_opt.py
"""

from __future__ import annotations

import numpy as np

import dba_evaluate as dev
import cabs_optimize as copt
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


def _ale_config():
    """Escenario de Ale: sala 6x4x3 (X = eje mas largo). 2 mains full-range
    ADELANTE + 2 subs ATRAS, enfrentados en Y (el eje CORTO)."""
    dims = (6.0, 4.0, 3.0)
    srcs = [
        OmniSource((2.0, 0.1, 1.2), label="MainL", source_type="fullrange"),
        OmniSource((4.0, 0.1, 1.2), label="MainR", source_type="fullrange"),
        OmniSource((2.0, 3.9, 0.5), label="SubL", source_type="subwoofer"),
        OmniSource((4.0, 3.9, 0.5), label="SubR", source_type="subwoofer"),
    ]
    return dims, srcs


def main():
    print("=" * 64)
    print("bench_source_opt  (CABS/DBA en cualquier par opuesto + optimizador no-freeze)")
    print("=" * 64)

    dims, srcs = _ale_config()
    print(f"  sala {dims}: eje mas largo = X ({int(np.argmax(dims))}); subs enfrentados en Y")

    # --- 1. best_axis criterion-aware elige el eje CORTO (Y), no el largo (X) ----
    ax_cabs = dev.best_axis(srcs, dims, (0, 0, 0), criterion="cabs")
    check("best_axis(cabs) elige el eje del par opuesto (Y=1), no el mas largo (X=0)",
          ax_cabs == 1, f"eligio {ax_cabs}")

    # --- 2. feasibility Auto (axis=None) reconoce la config de Ale ---------------
    feas, reasons, ax = dev.cabs_feasibility(srcs, dims, axis=None, criterion="cabs")
    check("cabs_feasibility(Auto) reconoce 2 subs atras + mains adelante", feas,
          f"axis={ax} reasons={reasons}")
    check("feasibility Auto usa el eje Y", ax == 1, f"axis={ax}")

    # contraprueba: forzar el eje mas largo (X) DEBE fallar (no hay par ahi)
    feas_x, reasons_x, _ = dev.cabs_feasibility(srcs, dims, axis=0, criterion="cabs")
    check("forzando el eje largo (X) la config NO es factible (contraprueba)",
          not feas_x, f"reasons={reasons_x}")

    # --- 3. evaluate_cabs(Auto) corre en el eje correcto y PASA ------------------
    r = dev.evaluate_cabs(srcs, dims, (3.0, 2.0, 1.2), axis=None,
                          criterion="cabs", fmax=150.0)
    check("evaluate_cabs(Auto) usa eje Y y PASA", r["axis"] == 1 and r["passed"],
          f"axis={r['axis']} passed={r['passed']}")

    # --- 4. DBA con 4 subs enfrentados en el eje corto: best_axis lo elige -------
    dims2 = (6.0, 4.0, 3.0)
    subs4 = [
        OmniSource((2.0, 0.1, 0.5), source_type="subwoofer"),
        OmniSource((4.0, 0.1, 0.5), source_type="subwoofer"),
        OmniSource((2.0, 3.9, 0.5), source_type="subwoofer"),
        OmniSource((4.0, 3.9, 0.5), source_type="subwoofer"),
    ]
    ax_dba = dev.best_axis(subs4, dims2, (0, 0, 0), criterion="dba")
    feas_dba, _, ax_dba2 = dev.cabs_feasibility(subs4, dims2, axis=None, criterion="dba")
    check("DBA: best_axis elige el eje corto (Y) con 4 subs 2+2 enfrentados",
          ax_dba == 1, f"eligio {ax_dba}")
    check("DBA feasibility(Auto) factible en Y", feas_dba and ax_dba2 == 1,
          f"feas={feas_dba} axis={ax_dba2}")

    # --- 4b. ControlAle: monitores a ~0.65 m del muro (NO flush) en el eje corto --
    # Regresion del 17 Sep 2026: con wall_tol fijo=0.6 m los Genelec a 0.65 m no se
    # reconocian como pegados a la pared -> CABS no se detectaba y best_axis caia al
    # eje largo (todo 'otras'). La zona de pared RELATIVA (WALL_FRAC*L) los reconoce.
    dims_ca = (4.8, 3.9, 3.1)
    ctrlale = [
        OmniSource((3.28, 0.65, 1.0), label="Genelec_L", source_type="fullrange"),
        OmniSource((1.29, 0.65, 1.0), label="Genelec_R", source_type="fullrange"),
        OmniSource((3.28, 3.70, 1.1), label="Sub L", source_type="subwoofer",
                   delay_s=0.008, polarity=-1),
        OmniSource((1.29, 3.70, 1.1), label="Sub R", source_type="subwoofer",
                   delay_s=0.008, polarity=-1),
    ]
    ax_ca = dev.best_axis(ctrlale, dims_ca, (0, 0, 0), criterion="cabs")
    feas_ca, why_ca, _ = dev.cabs_feasibility(ctrlale, dims_ca, axis=None,
                                              criterion="cabs")
    check("ControlAle: CABS se detecta en el eje corto Y (monitores a 0.65 m)",
          ax_ca == 1 and feas_ca, f"axis={ax_ca} feas={feas_ca} why={why_ca}")
    r_ca = dev.evaluate_cabs(ctrlale, dims_ca, (2.28, 1.74, 1.15), axis=None,
                             criterion="cabs", fmax=150.0)
    check("ControlAle: evaluate_cabs PASA en Y (par de subs + par de mains enfrente)",
          r_ca["axis"] == 1 and r_ca["passed"],
          f"axis={r_ca['axis']} passed={r_ca['passed']}")

    # --- 5. optimizador CANCELABLE: should_cancel corta y devuelve dict valido ---
    subs_free = [
        OmniSource((2.0, 0.1, 1.2), source_type="fullrange", free_vars={"pos"}),
        OmniSource((4.0, 0.1, 1.2), source_type="fullrange", free_vars={"pos"}),
        OmniSource((2.0, 3.9, 0.5), source_type="subwoofer", free_vars={"pos", "delay"}),
        OmniSource((4.0, 3.9, 0.5), source_type="subwoofer", free_vars={"pos", "delay"}),
    ]
    gens = {"i": 0}
    r_can = copt.optimize_cabs(subs_free, dims, (3.0, 2.0, 1.2), axis=1,
                               fmax=150.0, criterion="cabs", maxiter=30,
                               should_cancel=lambda: gens["i"] >= 2,
                               progress_cb=lambda i, m: gens.__setitem__("i", i))
    check("optimizador cancelable: corta antes del maxiter", gens["i"] < 30,
          f"corto en gen {gens['i']}")
    check("resultado de cancel es un dict valido con 'optimized'",
          isinstance(r_can, dict) and "optimized" in r_can
          and len(r_can["optimized"]) == len(subs_free))

    # --- 6. progress_cb se llama; optimizacion normal mejora --------------------
    prog = []
    r_ok = copt.optimize_cabs(subs_free, dims, (3.0, 2.0, 1.2), axis=1,
                              fmax=150.0, criterion="cabs", maxiter=12,
                              progress_cb=lambda i, m: prog.append(i))
    check("progress_cb se llama una vez por generacion", len(prog) >= 1,
          f"{len(prog)} reportes")
    c0 = r_ok["before"]["flat"] + r_ok["before"]["spatial"]
    c1 = r_ok["after"]["flat"] + r_ok["after"]["spatial"]
    check("la optimizacion (fuentes libres) baja el costo compuesto", c1 <= c0 + 1e-6,
          f"{c0:.2f} -> {c1:.2f}")

    # --- 6b. bounds del optimizador respetan el BAFLE (17 Sep 2026) -------------
    # Regresion: el optimizador usaba un margen de pared FIJO 0.15 m que no sabia del
    # bafle -> dejaba la caja medio afuera. Ahora los bounds de posicion usan el
    # semi-tamano de la caja (bafle) o ~0 (esfera, limite = centro).
    dims_b = (4.0, 5.0, 3.0)
    s_baf = OmniSource((2.0, 0.2, 1.2), baffle_size=(0.3, 0.5, 0.4),
                       orientation=0.0, render_kind="baffle", free_vars={"pos"})
    dofs_b = copt._source_dofs(s_baf, dims_b, np.zeros(3), 1)   # enf en Y
    amin, amax = s_baf.limit_aabb(); p = np.asarray(s_baf.position)
    lo_off, hi_off = p - amin, amax - p
    ok_baf = True
    for _k, ax, lo, hi in dofs_b:
        if (lo - lo_off[ax]) < -1e-9 or (hi + hi_off[ax]) > dims_b[ax] + 1e-9:
            ok_baf = False
    check("bounds(bafle): la caja queda dentro del recinto en los extremos", ok_baf,
          f"dofs={[(ax, round(lo,2), round(hi,2)) for _k,ax,lo,hi in dofs_b]}")
    s_sph = OmniSource((2.0, 0.2, 1.2), baffle_size=(0.3, 0.5, 0.4),
                       render_kind="sphere", free_vars={"pos"})
    dofs_s = copt._source_dofs(s_sph, dims_b, np.zeros(3), 1)
    ok_sph = all(lo < 0.1 and hi > dims_b[ax] - 0.1 for _k, ax, lo, hi in dofs_s)
    check("bounds(esfera): el centro puede llegar a la pared (esfera asoma)", ok_sph,
          f"dofs={[(ax, round(lo,2), round(hi,2)) for _k,ax,lo,hi in dofs_s]}")

    # --- 6c. anti-solape de BAFLES: el optimizador separa cajas superpuestas -----
    def _overlap(s1, s2):
        a, b = s1.render_aabb(); cc, dd = s2.render_aabb()
        return bool(np.all(np.minimum(b, dd) - np.maximum(a, cc) > 0))
    subs_ov = [
        OmniSource((3.0, 0.2, 1.2), baffle_size=(0.5, 0.5, 0.4), orientation=90.0,
                   render_kind="baffle", source_type="subwoofer", free_vars={"pos"}),
        OmniSource((3.2, 0.2, 1.2), baffle_size=(0.5, 0.5, 0.4), orientation=90.0,
                   render_kind="baffle", source_type="subwoofer", free_vars={"pos"}),
        OmniSource((3.0, 3.8, 1.2), source_type="subwoofer"),
        OmniSource((3.2, 3.8, 1.2), source_type="subwoofer")]
    check("dos bafles arrancan SOLAPADOS (test no trivial)",
          _overlap(subs_ov[0], subs_ov[1]))
    r_ov = copt.optimize_cabs(subs_ov, (6.0, 4.0, 3.0), (3.0, 2.0, 1.2), axis=1,
                              fmax=150.0, criterion="cabs", maxiter=40)
    oo = r_ov["optimized"]
    check("el optimizador SEPARA los bafles (no quedan superpuestos)",
          not _overlap(oo[0], oo[1]),
          f"pos {np.round(oo[0].position,2)} / {np.round(oo[1].position,2)}")
    # esferas: exentas del anti-solape (pueden superponerse) -> el optimizador
    # corre igual y NO las obliga a separarse por colision (la exencion se ve
    # tambien en la panel: source_placement_conflict devuelve None para esferas).
    subs_sph = [OmniSource(s.position, baffle_size=(0.5, 0.5, 0.4),
                           render_kind="sphere", source_type="subwoofer",
                           free_vars={"pos"}) for s in subs_ov[:2]] + subs_ov[2:]
    r_sph = copt.optimize_cabs(subs_sph, (6.0, 4.0, 3.0), (3.0, 2.0, 1.2), axis=1,
                               fmax=150.0, criterion="cabs", maxiter=6)
    check("optimizar esferas (exentas del anti-solape) corre y devuelve dict valido",
          isinstance(r_sph, dict) and len(r_sph["optimized"]) == 4
          and all(o.render_kind == "sphere" for o in r_sph["optimized"][:2]))

    # --- 7. CAMPO FEM REAL (FEMModalField): oraculo en una CAJA -----------------
    # En una caja, evaluar sobre el campo FEM real debe dar ~lo mismo que la base
    # analitica rectangular (valida frames box<->mundo + el enmascarado de puntos
    # fuera de malla). Para salas no-caja, el FEM es la geometria correcta.
    try:
        import acoustic_mesh, acoustic_fem, geometry
        bd = (5.0, 4.0, 3.0)
        v, t, _e, _n = geometry.make_room(width=5, length=4, height=3, n_walls=4)
        nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=4.0)[:2]
        K, M, _ = acoustic_fem.build_KM(nodes, tets)
        freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=70)
        loc = acoustic_fem.FieldEvaluator(nodes, tets)
        origin = nodes.min(0)                      # frame real de la malla
        fem = {"locator": loc, "freqs": freqs, "phis": phis, "xi": 0.03}
        xlo, xhi = nodes[:, 0].min() + 0.05, nodes[:, 0].max() - 0.05
        cfg = [
            OmniSource((xlo, -0.5, 1.2), source_type="subwoofer"),
            OmniSource((xhi, -0.5, 1.2), source_type="subwoofer"),
            OmniSource((xlo, 0.5, 1.2), source_type="fullrange"),
            OmniSource((xhi, 0.5, 1.2), source_type="fullrange"),
        ]
        rec = (0.0, 0.0, 1.5)
        kw = dict(origin=origin, axis=0, criterion="cabs", fmax=150.0, walls=None)
        r_an = dev.evaluate_cabs(cfg, bd, rec, **kw)
        r_fe = dev.evaluate_cabs(cfg, bd, rec, fem=fem, **kw)
        check("FEM: usa los modos del recinto real (no la base analitica)",
              r_fe["n_modes"] == len(freqs), f"n_modes={r_fe['n_modes']}")
        check("flag field='fem' cuando corre sobre el campo real",
              r_fe.get("field") == "fem", f"field={r_fe.get('field')}")
        check("flag field='aabb' cuando corre sobre la base analitica",
              r_an.get("field") == "aabb", f"field={r_an.get('field')}")
        check("FEM ~ analitico en una caja: planitud (<1.5 dB)",
              abs(r_fe["flat_real"] - r_an["flat_real"]) < 1.5,
              f"an={r_an['flat_real']:.2f} fem={r_fe['flat_real']:.2f}")
        check("FEM ~ analitico en una caja: varianza espacial (<1.5 dB)",
              abs(r_fe["spatial_real"] - r_an["spatial_real"]) < 1.5,
              f"an={r_an['spatial_real']:.2f} fem={r_fe['spatial_real']:.2f}")
        check("FEM: varianza FINITA (enmascarado de puntos fuera de malla)",
              np.isfinite(r_fe["spatial_real"]) and r_fe["spatial_real"] < 50.0,
              f"spatial={r_fe['spatial_real']:.2f}")
        # optimizar sobre el campo FEM corre y no rompe
        cfg_free = [
            OmniSource((xlo, -0.5, 1.2), source_type="subwoofer", free_vars={"pos"}),
            OmniSource((xhi, -0.5, 1.2), source_type="subwoofer", free_vars={"pos"}),
        ]
        r_opt = copt.optimize_cabs(cfg_free, bd, rec, origin=origin, axis=0,
                                   fmax=150.0, criterion="cabs", maxiter=6, fem=fem)
        check("optimizar sobre el campo FEM devuelve un dict valido",
              isinstance(r_opt, dict) and len(r_opt["optimized"]) == 2)
    except Exception as e:
        check("oraculo FEM corrio sin excepcion", False, str(e)[:80])

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return _N_FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
