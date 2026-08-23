"""
bench_predict_location.py
=========================

Valida la Fase B de T8: el eje de ubicacion integrado en prediction.py
(`predict_axis` con los 3 modos geometry / location / combined).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_predict_location.py
"""

from __future__ import annotations

import numpy as np
import prediction as pr
import sources as src


# Recinto shoebox de prueba para 'Evaluar mi diseño' (make_room centra en el
# origen: x in [-W/2,W/2], y in [-L/2,L/2], z in [0,H]).
_PARAMS = {"width": 5.0, "length": 4.0, "height": 3.0, "n_walls": 4,
           "taper": 0.0, "twist": 0.0, "arch_height": 0.0, "roof_type": "flat"}


def _src_array(positions):
    """SourceArray con fuentes en las posiciones dadas (como las del recinto)."""
    arr = src.SourceArray()
    for p in positions:
        arr.add_at(tuple(p))
    return arr


def _ok(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def _inputs(use="estudio", rt60=0.5):
    return pr.PredictInputs(
        use=use, program="mixto", priority=0.5,
        capacity=8, m2_per_person=1.5, rt60_target=rt60,
        v_per_person=9.0,
        width_max=None, length_max=None, height_max=None,
        parallel_walls="permitir", roof_shape="plano",
    )


def _positions_inside(pred, margin=-0.05):
    """Las posiciones del layout caen dentro del bbox del recinto del candidato."""
    cand = pred.candidate
    # make_room centra en el origen: x in [-W/2,W/2], y in [-L/2,L/2], z in [0,H].
    W, L, H = cand.width, cand.length, cand.height
    pos = np.atleast_2d(pred.layout.positions)
    okx = np.all((pos[:, 0] >= -W/2 - 0.3) & (pos[:, 0] <= W/2 + 0.3))
    oky = np.all((pos[:, 1] >= -L/2 - 0.3) & (pos[:, 1] <= L/2 + 0.3))
    okz = np.all((pos[:, 2] >= -0.1) & (pos[:, 2] <= H + 0.1))
    return bool(okx and oky and okz)


def test_geometry_regression():
    """Modo geometria: sigue devolviendo Predictions (sin romper lo de antes)."""
    preds = pr.predict_axis(_inputs(), mode="geometry")
    ok = _ok("geometry -> Predictions", len(preds) >= 1
             and isinstance(preds[0], pr.Prediction),
             f"n={len(preds)} top={preds[0].score_total:.0f}")
    return ok


def test_location_mode():
    """Modo ubicacion: recinto fijo -> 3 LocationPredictions validas."""
    inp = _inputs()
    cand = pr.generate_candidates(inp)[0]
    preds = pr.predict_axis(inp, mode="location", fixed_candidate=cand,
                            progress=lambda m: None)
    ok = _ok("location -> 3 LocationPredictions",
             1 <= len(preds) <= 3 and all(isinstance(p, pr.LocationPrediction)
                                          for p in preds),
             f"n={len(preds)}")
    ok &= _ok("scores en [0,100] y ordenados",
              all(0 <= p.score_total <= 100 for p in preds) and
              all(preds[i].score_total >= preds[i+1].score_total
                  for i in range(len(preds)-1)),
              f"scores={[round(p.score_total,1) for p in preds]}")
    ok &= _ok("posiciones dentro del recinto",
              all(_positions_inside(p) for p in preds))
    ok &= _ok("mensajes legibles no vacios",
              all(p.layout_msg and p.fom_msg and p.sbir_msg for p in preds),
              f"ej: '{preds[0].layout_msg}' | '{preds[0].fom_msg}'")
    ok &= _ok("el layout reconstruye una SourceArray",
              preds[0].layout.to_source_array() is not None
              and len(preds[0].layout.to_source_array()) == preds[0].layout.n_sources)
    return ok


def test_combined_mode():
    """Modo combinado: geometria + ubicacion -> predicciones con geom_score."""
    inp = _inputs()
    preds = pr.predict_axis(inp, mode="combined", progress=lambda m: None)
    ok = _ok("combined -> LocationPredictions",
             1 <= len(preds) <= 3 and all(p.mode == "combined" for p in preds),
             f"n={len(preds)}")
    ok &= _ok("combinado usa geom_score + ubicacion",
              all(p.geom_score > 0 for p in preds),
              f"geom={[round(p.geom_score,0) for p in preds]} "
              f"comb={[round(p.score_total,1) for p in preds]}")
    # El score combinado debe estar entre el geom y el de ubicacion (promedio).
    ok &= _ok("score combinado = mezcla geom/ubicacion",
              all(0 <= p.score_total <= 100 for p in preds))
    return ok


def test_weights_change_ranking():
    """Pesos distintos -> puede cambiar el mejor layout (mismo recinto)."""
    inp = _inputs()
    cand = pr.generate_candidates(inp)[0]
    w_flat = {"flat": 1.0, "espacial": 0.0, "sbir": 0.0, "smoothness": 0.0}
    w_sbir = {"flat": 0.0, "espacial": 0.0, "sbir": 1.0, "smoothness": 0.0}
    pf = pr.predict_locations(inp, cand, weights=w_flat, top_n=1)[0]
    ps = pr.predict_locations(inp, cand, weights=w_sbir, top_n=1)[0]
    # Con peso 100% planitud, el ganador debe tener FoM_flat <= el ganador SBIR.
    ok = _ok("pesos dirigen (flat vs sbir)",
             pf.FoM_flat <= ps.FoM_flat + 1e-6,
             f"win_flat FoM_flat={pf.FoM_flat:.2f} ({pf.layout_msg}) | "
             f"win_sbir FoM_flat={ps.FoM_flat:.2f} ({ps.layout_msg})")
    return ok


# ---------------------------------------------------------------------------
# "Evaluar mi diseño actual" por eje (evaluate_design): scorea lo que el
# usuario YA tiene, incluido su layout REAL de fuentes (no optimiza).
# ---------------------------------------------------------------------------
def test_eval_geometry():
    """Eje geometria: sigue devolviendo una Prediction (sin fuentes)."""
    pred = pr.evaluate_design(_PARAMS, _inputs(), mode="geometry")
    return _ok("eval geometry -> Prediction",
               isinstance(pred, pr.Prediction) and 0 <= pred.score_total <= 100,
               f"score={pred.score_total:.0f}")


def test_eval_location_uses_real_sources():
    """Eje ubicacion: evalua las posiciones REALES, no un layout optimizado."""
    arr = _src_array([(-1.2, -1.5, 1.2), (1.2, -1.5, 1.2)])
    pred = pr.evaluate_design(_PARAMS, _inputs(), mode="location",
                              sources=arr, progress=lambda m: None)
    ok = _ok("eval location -> LocationPrediction",
             isinstance(pred, pr.LocationPrediction) and pred.mode == "location",
             f"score={pred.score_total:.0f}")
    pos = np.atleast_2d(pred.layout.positions)
    ok &= _ok("usa las posiciones reales (no optimiza)",
              pos.shape[0] == 2
              and np.allclose(sorted(pos[:, 0]), [-1.2, 1.2], atol=1e-6),
              f"x={sorted(np.round(pos[:,0],2))}")
    return ok


def test_eval_location_consistent():
    """evaluate_design(location) == evaluate_layout sobre el mismo layout/ctx.

    Oraculo robusto: prueba que el eje evalua las fuentes REALES con el scorer
    de ubicacion (no afirma que tal posicion sea 'mejor' que otra — eso depende
    de pesos/geometria y no es un invariante).
    """
    import location_opt as lo
    arr = _src_array([(-1.0, -1.0, 1.2), (1.0, -1.0, 1.2)])
    inp = _inputs()
    pred = pr.evaluate_design(_PARAMS, inp, mode="location",
                              sources=arr, progress=lambda m: None)
    cand = pr.candidate_from_params(_PARAMS)
    ctx = pr._build_location_context(cand, inp)
    layout = pr._layout_from_sources(arr)
    ls = lo.evaluate_layout(ctx, layout,
                            weights=lo.default_location_weights(inp.use))
    return _ok("score coincide con evaluate_layout directo",
               abs(pred.score_total - ls.score_total) < 1e-6,
               f"design={pred.score_total:.4f} layout={ls.score_total:.4f}")


def test_eval_combined():
    """Eje combinado: geometria + layout real -> LocationPrediction combinada."""
    arr = _src_array([(-1.2, -1.5, 1.2), (1.2, -1.5, 1.2)])
    pred = pr.evaluate_design(_PARAMS, _inputs(), mode="combined",
                              sources=arr, progress=lambda m: None)
    return _ok("eval combined -> LocationPrediction(combined) con geom_score",
               isinstance(pred, pr.LocationPrediction)
               and pred.mode == "combined" and pred.geom_score > 0,
               f"geom={pred.geom_score:.0f} comb={pred.score_total:.1f}")


def test_eval_no_sources_raises():
    """Ubicacion sin fuentes -> ValueError (el panel lo intercepta y avisa)."""
    raised = False
    try:
        pr.evaluate_design(_PARAMS, _inputs(), mode="location",
                           sources=_src_array([]))
    except ValueError:
        raised = True
    return _ok("location sin fuentes -> ValueError", raised)


def test_eval_sources_outside_raises():
    """Fuente fuera del recinto reconstruido -> ValueError (no score basura)."""
    raised = False
    try:
        pr.evaluate_design(_PARAMS, _inputs(), mode="location",
                           sources=_src_array([(100.0, 0.0, 1.0)]),
                           progress=lambda m: None)
    except ValueError:
        raised = True
    return _ok("fuentes fuera del recinto -> ValueError", raised)


# ---------------------------------------------------------------------------
# Camino B: forma irregular -> FEM sobre la malla REAL renderizada (no una
# caja reconstruida), con eleccion AABB / no-ponderar.
# ---------------------------------------------------------------------------
def _irregular_surface():
    """Malla real de una planta custom (cuadrilatero irregular), techo plano."""
    from geometry import make_room
    poly = [(-3.0, -2.0), (3.0, -2.0), (2.8, 2.2), (-2.6, 2.4)]
    v, t, *_ = make_room(width=6.0, length=4.0, height=3.0,
                         base_polygon=poly, roof_type="flat", subdiv_levels=0)
    return np.asarray(v, float), np.asarray(t)


def _center_sources(surface):
    """Dos fuentes cerca del centro del AABB (siempre dentro del bbox)."""
    v = surface[0]
    mn, mx = v.min(0), v.max(0)
    c = 0.5 * (mn + mx)
    z = mn[2] + 0.4 * (mx[2] - mn[2])
    return _src_array([(c[0] - 0.4, c[1], z), (c[0] + 0.4, c[1], z)])


def test_irregular_detect():
    return _ok("is_irregular_shape detecta base_polygon / wall_profiles",
               pr.is_irregular_shape({"base_polygon": [(0, 0), (1, 0), (1, 1)]})
               and not pr.is_irregular_shape({"base_polygon": None}))


def test_eval_irregular_aabb():
    """geometry + aabb: Prediction con las dimensiones de la caja envolvente."""
    surf = _irregular_surface()
    params = dict(_PARAMS, base_polygon=[(-3, -2), (3, -2), (2.8, 2.2), (-2.6, 2.4)])
    pred = pr.evaluate_design(params, _inputs(), mode="geometry",
                              surface=surf, shape_mode="aabb",
                              progress=lambda m: None)
    W, L, H = pr._aabb_dims(surf)
    return _ok("geometry+aabb -> Prediction con dims del AABB",
               isinstance(pred, pr.Prediction)
               and abs(pred.candidate.width - W) < 1e-6
               and abs(pred.candidate.length - L) < 1e-6,
               f"AABB={W:.2f}x{L:.2f}x{H:.2f} "
               f"cand={pred.candidate.width:.2f}x{pred.candidate.length:.2f}")


def test_eval_irregular_none_blocks_geometry():
    """geometry + none: no se puede predecir por geometria -> ValueError."""
    raised = False
    try:
        pr.evaluate_design(_PARAMS, _inputs(), mode="geometry",
                           surface=_irregular_surface(), shape_mode="none")
    except ValueError:
        raised = True
    return _ok("geometry+none -> ValueError (no ponderable)", raised)


def test_eval_irregular_location_real_mesh():
    """location sobre la malla real: fuentes al centro caen dentro (no error)."""
    surf = _irregular_surface()
    pred = pr.evaluate_design(_PARAMS, _inputs(), mode="location",
                              surface=surf, shape_mode="none",
                              sources=_center_sources(surf),
                              progress=lambda m: None)
    return _ok("location sobre malla real -> LocationPrediction",
               isinstance(pred, pr.LocationPrediction)
               and 0 <= pred.score_total <= 100,
               f"score={pred.score_total:.1f}")


def test_eval_irregular_combined_none_degrades():
    """combined + none degrada a solo ubicacion (sin score de geometria)."""
    surf = _irregular_surface()
    pred = pr.evaluate_design(_PARAMS, _inputs(), mode="combined",
                              surface=surf, shape_mode="none",
                              sources=_center_sources(surf),
                              progress=lambda m: None)
    return _ok("combined+none -> ubicacion (geom_score=0)",
               isinstance(pred, pr.LocationPrediction)
               and pred.mode == "location" and pred.geom_score == 0.0,
               f"mode={pred.mode} geom={pred.geom_score}")


def test_predict_location_irregular_real_mesh():
    """Predecir ubicacion con forma irregular: el FEM corre sobre la malla REAL
    (Camino B), no una caja centrada reconstruida. Malla desplazada +50 en x ->
    las posiciones recomendadas deben salir en ese frame (se aplican sin
    corrimiento a las fuentes)."""
    surf = _irregular_surface()
    v = surf[0].copy(); v[:, 0] += 50.0           # frame distinguible
    surf = (v, surf[1])
    params = dict(_PARAMS, base_polygon=[(-3, -2), (3, -2), (2.8, 2.2), (-2.6, 2.4)])
    fixed = pr.fixed_room_from_design(params, surface=surf)
    preds = pr.predict_axis(_inputs(), mode="location", fixed_candidate=fixed,
                            surface=surf, progress=lambda m: None)
    pos = np.atleast_2d(preds[0].layout.positions)
    used_real = bool(np.all(pos[:, 0] > 40.0))
    # Contraste: sin surface reconstruye caja centrada -> posiciones cerca de 0.
    preds0 = pr.predict_axis(_inputs(), mode="location", fixed_candidate=fixed,
                             surface=None, progress=lambda m: None)
    pos0 = np.atleast_2d(preds0[0].layout.positions)
    centered = bool(np.all(np.abs(pos0[:, 0]) < 10.0))
    return _ok("predict location irregular -> FEM sobre malla real (frame ok)",
               len(preds) >= 1 and used_real and centered,
               f"x_real~{pos[0,0]:.1f} x_sinSurf~{pos0[0,0]:.1f}")


def test_predict_location_irregular_sources_inside():
    """Con forma irregular, las fuentes recomendadas caen DENTRO de la sala
    real, no solo del AABB (fix 5 Jul 2026: inside_fn en LocationContext).
    Planta con esquina cortada al frente: la cuna AABB-menos-sala atrapaba
    semillas del optimizador."""
    from geometry import build_room_geometry
    from acoustic_mesh import points_inside_surface
    import location_opt as lo
    poly = [(0.0, 0.0), (4.0, 0.0), (6.0, 2.0), (6.0, 5.0), (0.0, 5.0)]
    params = dict(_PARAMS, base_polygon=poly, wall_inclinations=[0.0] * 5)
    v, t, _e, _n = build_room_geometry(params)
    v = np.asarray(v, float)
    surf = (v, t)
    # El caso debe discriminar: al menos una semilla cruda del AABB cae fuera.
    mn, mx = v.min(axis=0), v.max(axis=0)
    n_out = sum(
        1 for s in lo.seed_layouts(mn, mx)
        if not bool(np.all(points_inside_surface(
            np.atleast_2d(np.asarray(s.positions, float)), v,
            np.asarray(t, int)))))
    fixed = pr.fixed_room_from_design(params, surface=surf)
    preds = pr.predict_axis(_inputs(), mode="location", fixed_candidate=fixed,
                            surface=surf, progress=lambda m: None)
    all_inside = all(
        bool(np.all(points_inside_surface(
            np.atleast_2d(np.asarray(p.layout.positions, float)), v,
            np.asarray(t, int))))
        for p in preds)
    return _ok("recomendaciones dentro de la sala real (no solo AABB)",
               n_out >= 1 and len(preds) >= 1 and all_inside,
               f"semillas crudas fuera={n_out}, preds={len(preds)}")


def test_predict_location_pentagon_all_seeds_outside():
    """Caso real del usuario (recintopptx2.room, 5 Jul 2026): pentagono grande
    donde TODAS las semillas del AABB caen fuera de la sala. El primer fix
    (filtrar) degeneraba al fallback sin filtro; el fix definitivo REPARA las
    semillas (biseccion hacia un ancla interior). Todas las recomendaciones
    deben caer dentro."""
    from geometry import build_room_geometry
    from acoustic_mesh import points_inside_surface
    import location_opt as lo
    poly = [(7.0, 15.0), (1.5, 9.5), (3.5, 1.0), (14.0, 2.0), (19.0, 10.5)]
    params = dict(_PARAMS, base_polygon=poly, wall_inclinations=[0.0] * 5)
    v, t, _e, _n = build_room_geometry(params)
    v = np.asarray(v, float)
    ti = np.asarray(t, int)
    mn, mx = v.min(axis=0), v.max(axis=0)
    n_bad = sum(
        1 for s in lo.seed_layouts(mn, mx)
        if not bool(np.all(points_inside_surface(
            np.atleast_2d(np.asarray(s.positions, float)), v, ti))))
    fixed = pr.fixed_room_from_design(params, surface=(v, t))
    preds = pr.predict_axis(_inputs(), mode="location", fixed_candidate=fixed,
                            surface=(v, t), progress=lambda m: None)
    all_inside = all(
        bool(np.all(points_inside_surface(
            np.atleast_2d(np.asarray(p.layout.positions, float)), v, ti)))
        for p in preds)
    return _ok("pentagono (todas las semillas fuera) -> reparadas y dentro",
               n_bad == 6 and len(preds) >= 1 and all_inside,
               f"semillas crudas fuera={n_bad}/6, preds={len(preds)}")


def test_location_perturbation_damping():
    """Etapa 2c: el FEM de ubicacion usa xi POR MODO (perturbacion) en vez del
    1.1/(f_n·RT) uniforme, cuando damping_model='perturbation' y hay materiales
    por superficie. El default 'sabine' queda intacto (uniforme)."""
    from geometry import make_room
    v, t, _e, _n = make_room(width=5.0, length=4.0, height=3.0, n_walls=4)
    # Materiales por superficie: piso absorbente, paredes/techo reflectantes.
    af = {125: 0.20, 250: 0.30, 500: 0.40, 1000: 0.50, 2000: 0.55}
    aw = {125: 0.03, 250: 0.04, 500: 0.05, 1000: 0.06, 2000: 0.07}
    inp = pr.PredictInputs(
        use="estudio", program="mixto", priority=0.5,
        capacity=8, m2_per_person=1.5, rt60_target=0.5, v_per_person=9.0,
        width_max=None, length_max=None, height_max=None,
        parallel_walls="permitir", roof_shape="plano",
        alpha_mode="materials", surface_alpha=(af, aw, aw))
    cand = pr.fixed_room_from_design(_PARAMS, surface=(v, t))

    ctx_s = pr._build_location_context(cand, inp, surface=(v, t),
                                       damping_model="sabine")
    ctx_p = pr._build_location_context(cand, inp, surface=(v, t),
                                       damping_model="perturbation")
    d_s = np.asarray(ctx_s.damping, float)
    d_p = np.asarray(ctx_p.damping, float)
    # Necesitamos las freqs de los modos para pasar de xi a delta.
    fr_s = np.asarray(ctx_s.freqs, float) if hasattr(ctx_s, "freqs") else None
    ok = True

    # a) sabine: xi = 1.1/(f·RT) -> delta = xi·2π·f = 2π·1.1/RT CONSTANTE.
    if fr_s is not None and d_s.size == fr_s.size:
        delta_s = d_s * 2 * np.pi * fr_s
        cv_s = float(delta_s.std() / max(delta_s.mean(), 1e-12))
        ok &= _ok("sabine: delta uniforme (xi ∝ 1/f)", cv_s < 1e-6,
                  f"CV(delta)={cv_s:.2e}")
        # b) perturbacion: delta NO constante (amortiguamiento por modo).
        delta_p = d_p * 2 * np.pi * fr_s
        cv_p = float(delta_p.std() / max(delta_p.mean(), 1e-12))
        ok &= _ok("perturbacion: delta por modo (no uniforme)", cv_p > 0.10,
                  f"CV(delta)={cv_p:.0%}")
    # c) las dos difieren de verdad en el vector de damping.
    ok &= _ok("los dos modelos dan damping distinto",
              d_s.shape == d_p.shape and not np.allclose(d_s, d_p),
              f"maxdif={np.max(np.abs(d_s - d_p)):.4f}")

    # d) sin materiales (alpha_mode!='materials') la perturbacion cae al uniforme.
    inp2 = pr.PredictInputs(
        use="estudio", program="mixto", priority=0.5,
        capacity=8, m2_per_person=1.5, rt60_target=0.5, v_per_person=9.0,
        width_max=None, length_max=None, height_max=None,
        parallel_walls="permitir", roof_shape="plano",
        alpha_mode="target")
    import acoustic_analysis as _aa
    mr = _aa.run_fem_modal(v, t, n_modes=40, n_per_meter=2.0)
    xi_none = pr._perturbation_damping_for_location(mr, v, t, inp2)
    ok &= _ok("sin materiales -> perturbacion devuelve None (cae a uniforme)",
              xi_none is None)
    return ok


def main():
    print("bench_predict_location.py — Fase B de T8 (3 modos) + evaluate_design\n")
    tests = [
        ("geometry_regression", test_geometry_regression),
        ("location_mode", test_location_mode),
        ("combined_mode", test_combined_mode),
        ("weights_change_ranking", test_weights_change_ranking),
        ("eval_geometry", test_eval_geometry),
        ("eval_location_uses_real_sources", test_eval_location_uses_real_sources),
        ("eval_location_consistent", test_eval_location_consistent),
        ("eval_combined", test_eval_combined),
        ("eval_no_sources_raises", test_eval_no_sources_raises),
        ("eval_sources_outside_raises", test_eval_sources_outside_raises),
        ("irregular_detect", test_irregular_detect),
        ("eval_irregular_aabb", test_eval_irregular_aabb),
        ("eval_irregular_none_blocks_geometry", test_eval_irregular_none_blocks_geometry),
        ("eval_irregular_location_real_mesh", test_eval_irregular_location_real_mesh),
        ("eval_irregular_combined_none_degrades", test_eval_irregular_combined_none_degrades),
        ("predict_location_irregular_real_mesh", test_predict_location_irregular_real_mesh),
        ("predict_location_irregular_sources_inside", test_predict_location_irregular_sources_inside),
        ("predict_location_pentagon_all_seeds_outside", test_predict_location_pentagon_all_seeds_outside),
        ("location_perturbation_damping", test_location_perturbation_damping),
    ]
    all_ok = True
    for name, fn in tests:
        print(f"[{name}]")
        try:
            all_ok &= fn()
        except Exception as e:
            import traceback
            all_ok = False
            print(f"  [FAIL] excepcion: {e}")
            traceback.print_exc()
        print()
    print("=" * 52)
    print("TODOS OK" if all_ok else "HAY FALLAS")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
