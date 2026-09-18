"""
bench_norte_criterios.py
========================

Oraculos de la Fase A del panel unificado "Optimizacion de fuentes" (18 Sep 2026):
el "norte" (criterio) pasa a ser una lista con nortes PUROS (objetivo) ademas de
los esquemas de array CABS/DBA:

  - "flat"    = transferencia compuesta plana (peso 1,0 sobre flat/spatial).
  - "spatial" = uniformidad espacial (peso 0,1).
  - "cabs"/"dba" = esquemas de array (peso 1,1 -> identico al historico).

Falsable, autocontenido, headless. Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_norte_criterios.py
"""

from __future__ import annotations

import numpy as np

import dba_evaluate as dev
import cabs_optimize as copt
from sources import OmniSource
from sbir import Wall


def _box_walls(dims, R=0.7):
    Lx, Ly, Lz = dims
    return [Wall(point=[0, 0, 0], normal=[1, 0, 0], R=R),
            Wall(point=[Lx, 0, 0], normal=[1, 0, 0], R=R),
            Wall(point=[0, 0, 0], normal=[0, 1, 0], R=R),
            Wall(point=[0, Ly, 0], normal=[0, 1, 0], R=R),
            Wall(point=[0, 0, 0], normal=[0, 0, 1], R=R),
            Wall(point=[0, 0, Lz], normal=[0, 0, 1], R=R)]

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


def main():
    print("=" * 64)
    print("bench_norte_criterios  (Fase A: nortes puros flat/spatial + cabs/dba)")
    print("=" * 64)

    # --- 1. taxonomia + pesos ---------------------------------------------------
    check("is_array_criterion: cabs/dba SI, flat/spatial NO",
          dev.is_array_criterion("cabs") and dev.is_array_criterion("dba")
          and not dev.is_array_criterion("flat")
          and not dev.is_array_criterion("spatial"))
    check("objective_weights flat=(1,0)", dev.objective_weights("flat") == (1.0, 0.0))
    check("objective_weights spatial=(0,1)", dev.objective_weights("spatial") == (0.0, 1.0))
    check("objective_weights cabs/dba=(1,1) (historico intacto)",
          dev.objective_weights("cabs") == (1.0, 1.0)
          and dev.objective_weights("dba") == (1.0, 1.0))

    # --- 2. feasibility de nortes puros: SIEMPRE factible, sin razones ----------
    dims = (5.0, 4.0, 3.0)
    srcs = [OmniSource((1.0, 1.0, 1.2), source_type="fullrange"),
            OmniSource((4.0, 1.0, 1.2), source_type="fullrange")]
    for crit in ("flat", "spatial"):
        feas, reasons, ax = dev.cabs_feasibility(srcs, dims, axis=None, criterion=crit)
        check(f"cabs_feasibility('{crit}') = factible, sin razones",
              feas and reasons == [], f"feas={feas} reasons={reasons} axis={ax}")

    # --- 3. evaluate_cabs con norte puro: PASA + checklist informativo unico ----
    for crit in ("flat", "spatial"):
        r = dev.evaluate_cabs(srcs, dims, (2.5, 2.0, 1.2), axis=None,
                              criterion=crit, fmax=150.0)
        check(f"evaluate_cabs('{crit}') PASA y trae criterion en el dict",
              r["passed"] and r["criterion"] == crit)
        keys = [it["key"] for it in r["checklist"]]
        check(f"evaluate_cabs('{crit}') checklist = 1 item 'objective' (sin esquema)",
              keys == ["objective"], f"keys={keys}")
        check(f"evaluate_cabs('{crit}') metrica FINITA",
              np.isfinite(r["flat_real"]) and np.isfinite(r["spatial_real"]))

    # --- 4. optimizar con norte 'flat' baja la PLANITUD (el objetivo elegido) ---
    free = [OmniSource((1.0, 1.0, 1.2), source_type="subwoofer", free_vars={"pos"}),
            OmniSource((4.0, 1.0, 1.2), source_type="subwoofer", free_vars={"pos"})]
    r_flat = copt.optimize_cabs(free, dims, (2.5, 2.0, 1.2), axis=1,
                                criterion="flat", fmax=150.0, maxiter=15)
    check("optimize('flat') baja la planitud (flat_after <= flat_before)",
          r_flat["after"]["flat"] <= r_flat["before"]["flat"] + 1e-6,
          f"flat {r_flat['before']['flat']:.2f} -> {r_flat['after']['flat']:.2f}")

    # --- 5. el costo interno usa los pesos del norte ----------------------------
    # (chequeo directo del objetivo ponderado sobre metricas de juguete)
    m = {"flat": 8.0, "spatial": 4.0}
    of = dev.objective_weights("flat")
    osp = dev.objective_weights("spatial")
    check("objetivo 'flat' = solo planitud (8.0)",
          of[0] * m["flat"] + of[1] * m["spatial"] == 8.0)
    check("objetivo 'spatial' = solo varianza (4.0)",
          osp[0] * m["flat"] + osp[1] * m["spatial"] == 4.0)

    # --- 6. Fase B: norte SBIR (peine de bordes) --------------------------------
    check("wants_sbir: solo 'sbir'",
          dev.wants_sbir("sbir") and not dev.wants_sbir("flat")
          and not dev.wants_sbir("cabs"))
    check("composite_cost('sbir') = el peine (sbir_span)",
          dev.composite_cost({"flat": 9.0, "spatial": 9.0, "sbir_span": 5.5}, "sbir") == 5.5)
    check("composite_cost('flat') = planitud; cabs = flat+spatial",
          dev.composite_cost(m, "flat") == 8.0
          and dev.composite_cost(m, "cabs") == 12.0)

    walls = _box_walls(dims)
    src_sb = [OmniSource((1.0, 0.5, 1.2), source_type="subwoofer"),
              OmniSource((4.0, 0.5, 1.2), source_type="subwoofer")]
    r_sb = dev.evaluate_cabs(src_sb, dims, (2.5, 2.0, 1.2), walls=walls,
                             criterion="sbir", fmax=200.0)
    check("evaluate_cabs('sbir') con paredes -> sbir_real FINITO y >= 0",
          np.isfinite(r_sb["sbir_real"]) and r_sb["sbir_real"] >= 0.0,
          f"sbir_real={r_sb['sbir_real']:.2f}")
    check("evaluate_cabs('sbir') checklist menciona el peine SBIR",
          any("SBIR" in it["text"] for it in r_sb["checklist"]))
    check("smoothness (Bolt) presente y FINITO (informativo)",
          np.isfinite(r_sb["smoothness"]) and 0.0 <= r_sb["smoothness"] <= 100.0,
          f"smoothness={r_sb['smoothness']:.0f}")
    # el peine RESPONDE a la posicion (metrica no trivial)
    r_sb2 = dev.evaluate_cabs(
        [OmniSource((0.15, 0.15, 0.3), source_type="subwoofer")],
        dims, (2.5, 2.0, 1.2), walls=walls, criterion="sbir", fmax=200.0)
    check("el peine SBIR responde a la posicion (esquina != centro)",
          abs(r_sb["sbir_real"] - r_sb2["sbir_real"]) > 1e-3,
          f"{r_sb['sbir_real']:.2f} vs esquina {r_sb2['sbir_real']:.2f}")
    # optimizar por SBIR corre y no empeora el peine
    free_sb = [OmniSource((1.0, 0.5, 1.2), source_type="subwoofer", free_vars={"pos"}),
               OmniSource((4.0, 0.5, 1.2), source_type="subwoofer", free_vars={"pos"})]
    r_opt = copt.optimize_cabs(free_sb, dims, (2.5, 2.0, 1.2), walls=walls, axis=1,
                               criterion="sbir", fmax=200.0, maxiter=12)
    check("optimize('sbir') corre y no empeora el peine",
          r_opt["after"]["sbir_span"] <= r_opt["before"]["sbir_span"] + 1e-6,
          f"sbir {r_opt['before']['sbir_span']:.2f} -> {r_opt['after']['sbir_span']:.2f}")

    # --- 7. Fase B: norte COMBINADO (por caso de uso) ---------------------------
    check("combined es objetivo (no array) y usa SBIR",
          "combined" in dev.OBJECTIVE_CRITERIA and not dev.is_array_criterion("combined")
          and dev.wants_sbir("combined"))
    import location_opt as _lo
    mm2 = {"flat": 4.0, "spatial": 4.0, "sbir_span": 6.0,
           "freqs": np.array([40., 55., 70., 90., 110.])}
    sc = dev.combined_score(mm2, _lo.default_location_weights("musica"))
    check("combined_score en rango 0..100", 0.0 <= sc <= 100.0, f"score={sc:.1f}")
    check("composite_cost('combined') = 100 - score",
          abs(dev.composite_cost(mm2, "combined", _lo.default_location_weights("musica"))
              - (100.0 - sc)) < 1e-9)
    # los pesos por caso de uso CAMBIAN el score (musica != voz cuando difieren
    # los sub-scores)
    mm3 = {"flat": 2.0, "spatial": 11.0, "sbir_span": 6.0,   # planitud buena, espacial mala
           "freqs": mm2["freqs"]}
    s_mus = dev.combined_score(mm3, _lo.default_location_weights("musica"))
    s_voz = dev.combined_score(mm3, _lo.default_location_weights("voz"))
    check("los pesos por uso cambian el score (voz prioriza planitud > espacial)",
          abs(s_mus - s_voz) > 1e-6 and s_voz > s_mus,
          f"musica={s_mus:.1f} voz={s_voz:.1f}")
    # evaluate + optimize con weights
    r_cb = dev.evaluate_cabs(src_sb, dims, (2.5, 2.0, 1.2), walls=walls,
                             criterion="combined", fmax=200.0,
                             weights=_lo.default_location_weights("mixto"))
    check("evaluate_cabs('combined') -> combined_real FINITO 0..100",
          np.isfinite(r_cb["combined_real"]) and 0.0 <= r_cb["combined_real"] <= 100.0,
          f"combined_real={r_cb['combined_real']:.0f}")
    r_ocb = copt.optimize_cabs(free_sb, dims, (2.5, 2.0, 1.2), walls=walls, axis=1,
                               criterion="combined", fmax=200.0, maxiter=12,
                               weights=_lo.default_location_weights("mixto"))
    j0 = dev.composite_cost(r_ocb["before"], "combined", _lo.default_location_weights("mixto"))
    j1 = dev.composite_cost(r_ocb["after"], "combined", _lo.default_location_weights("mixto"))
    check("optimize('combined') no empeora el objetivo (100-score)", j1 <= j0 + 1e-6,
          f"{j0:.2f} -> {j1:.2f}")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return _N_FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
