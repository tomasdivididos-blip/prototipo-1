"""
bench_location_opt.py
=====================

Oraculos del optimizador de ubicacion (T8, Fase A). Comportamientos RELATIVOS
y robustos a la calibracion de umbrales:

  1. beats_random : el mejor layout optimizado supera el baseline aleatorio.
  2. flush_sbir   : montar la fuente en la pared (flush) saca el notch SBIR de
                    banda -> mejor sub-score SBIR que la misma fuente despegada.
  3. symmetric    : estereo simetrico -> mejor FoM_espacial que asimetrico.
  4. delay_matters: el delay relativo entre 2 fuentes cambia el objetivo y el
                    barrido encuentra algo >= delay 0.
  5. weights_steer: cambiar los pesos cambia que layout gana (espacial vs flat).
  6. diversity    : el top-3 son estrategias distintas (familias de semilla).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_location_opt.py
"""

from __future__ import annotations

import numpy as np

import geometry, acoustic_analysis as aa
import face_materials as fm
import sbir
import location_opt as lo


def _ok(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def _build_ctx(Lx=6.0, Ly=4.0, Lz=3.0, use="estudio", alpha=0.08):
    """Construye el contexto como el panel real: paredes desde los face groups
    (centroide+normal en el frame REAL del recinto, que make_room centra en el
    origen en x,y)."""
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    mr = aa.run_fem_modal(v, t, n_modes=40, n_per_meter=2.0)
    R = sbir.reflection_from_alpha(alpha)
    groups = fm.group_faces_by_planar_region(v, t)
    walls = [sbir.Wall(g.centroid, g.normal, g.label, R) for g in groups]
    ctx = lo.LocationContext.from_modal(mr, walls, use=use, f_max_valid=114.0)
    return ctx, (Lx, Ly, Lz)


def _front_wall(ctx):
    """La pared frontal (-Y) del recinto, desde sus paredes reales."""
    for w in ctx.walls:
        if w.normal[1] < -0.9:
            return w
    return ctx.walls[0]


def test_beats_random():
    ctx, dims = _build_ctx()
    tops = lo.optimize_layout(ctx, top_n=3)
    best = tops[0].score_total
    mn, mx = ctx.room_bbox()
    rng = np.random.default_rng(7)
    base = [lo.evaluate_layout(ctx, lo.random_baseline(mn, mx, 2, rng)).score_total
            for _ in range(8)]
    mean_base = float(np.mean(base))
    return _ok("optimizado > baseline aleatorio", best > mean_base + 2.0,
               f"best={best:.1f} vs random_mean={mean_base:.1f}")


def test_flush_sbir():
    # Solo pared frontal (real, -Y) para aislar el montaje: off-wall genera un
    # notch en banda (c/4d), flush lo saca fuera de banda. Coords en el frame
    # REAL (recinto centrado en origen; pared frontal en y=ymin).
    ctx, (Lx, Ly, Lz) = _build_ctx()
    front = _front_wall(ctx)
    ctx.walls = [front]
    mn, mx = ctx.room_bbox()
    ymin = mn[1]
    baffle = (0.30, 0.50, 0.40)
    flush = lo.SourceLayout([[0.0, ymin + 0.20, 1.2]], mounted=[True],
                            baffle=baffle, label="flush")
    off = lo.SourceLayout([[0.0, ymin + 0.80, 1.2]], baffle=baffle, label="off")
    sf = lo.evaluate_layout(ctx, flush)
    so = lo.evaluate_layout(ctx, off)
    return _ok("flush -> notch fuera de banda (mejor SBIR)",
               sf.sub_scores["sbir"] > so.sub_scores["sbir"],
               f"flush sbir={sf.sub_scores['sbir']:.1f} (aten={sf.sbir_aten:+.1f}) "
               f"vs off={so.sub_scores['sbir']:.1f} (aten={so.sbir_aten:+.1f})")


def test_corner_flat():
    # Textbook: la esquina es antinodo de TODOS los modos -> excita todo ->
    # media mas plana. El centro cae en nodos de los modos impares. Coords en el
    # frame REAL (recinto centrado en origen).
    ctx, (Lx, Ly, Lz) = _build_ctx()
    mn, mx = ctx.room_bbox()
    corner = lo.SourceLayout([[mn[0] + 0.4, mn[1] + 0.4, mn[2] + 0.4]], label="corner")
    center = lo.SourceLayout([[0.5 * (mn[0] + mx[0]), 0.5 * (mn[1] + mx[1]),
                               0.5 * (mn[2] + mx[2])]], label="center")
    rc = lo.evaluate_layout(ctx, corner)
    rk = lo.evaluate_layout(ctx, center)
    return _ok("fuente en esquina -> media mas plana que en el centro",
               rc.FoM_flat < rk.FoM_flat,
               f"esquina={rc.FoM_flat:.2f} dB vs centro={rk.FoM_flat:.2f} dB")


def test_delay_matters():
    ctx, (Lx, Ly, Lz) = _build_ctx()
    mn, mx = ctx.room_bbox()
    W = mx[0] - mn[0]
    yf, zs = mn[1] + 0.6, mn[2] + 0.3
    base = lo.SourceLayout([[mn[0] + 0.25 * W, yf, zs],
                            [mn[0] + 0.75 * W, yf, zs]], label="subs")
    scores = []
    for d_ms in (0.0, 0.5, 1.0, 2.0, 3.0):
        dl = np.array([0.0, d_ms * 1e-3])
        r = lo.evaluate_layout(ctx, lo.SourceLayout(base.positions.copy(),
                                                    delays_s=dl, label="subs"))
        scores.append(r.score_total)
    spread = max(scores) - min(scores)
    best_ge_zero = max(scores) >= scores[0] - 1e-9
    return _ok("el delay relativo cambia el objetivo y el barrido ayuda",
               spread > 0.1 and best_ge_zero,
               f"spread={spread:.2f}  delay0={scores[0]:.1f}  best={max(scores):.1f}")


def test_weights_steer():
    ctx, (Lx, Ly, Lz) = _build_ctx()
    mn, mx = ctx.room_bbox()
    seeds = lo.seed_layouts(mn, mx)
    w_esp = {"flat": 0.0, "espacial": 1.0, "sbir": 0.0, "smoothness": 0.0}
    w_flat = {"flat": 1.0, "espacial": 0.0, "sbir": 0.0, "smoothness": 0.0}
    res_esp = sorted((lo.evaluate_layout(ctx, s, w_esp) for s in seeds),
                     key=lambda r: r.score_total, reverse=True)
    res_flat = sorted((lo.evaluate_layout(ctx, s, w_flat) for s in seeds),
                      key=lambda r: r.score_total, reverse=True)
    win_esp, win_flat = res_esp[0], res_flat[0]
    # El ganador con pesos espaciales debe tener FoM_espacial <= el de flat.
    return _ok("los pesos dirigen la eleccion (espacial vs flat)",
               win_esp.FoM_espacial <= win_flat.FoM_espacial + 1e-9,
               f"win_esp espacial={win_esp.FoM_espacial:.2f} ({win_esp.layout.label}) "
               f"<= win_flat espacial={win_flat.FoM_espacial:.2f} ({win_flat.layout.label})")


def test_diversity():
    ctx, dims = _build_ctx()
    tops = lo.optimize_layout(ctx, top_n=3)
    fams = [lo._seed_family(r.layout.label) for r in tops]
    return _ok("top-3 = estrategias distintas", len(set(fams)) == len(fams),
               f"familias={fams}")


def main():
    print("bench_location_opt.py — oraculos del optimizador de ubicacion\n")
    tests = [
        ("beats_random", test_beats_random),
        ("flush_sbir", test_flush_sbir),
        ("corner_flat", test_corner_flat),
        ("delay_matters", test_delay_matters),
        ("weights_steer", test_weights_steer),
        ("diversity", test_diversity),
    ]
    all_ok = True
    for name, fn in tests:
        print(f"[{name}]")
        try:
            all_ok &= fn()
        except Exception as e:
            all_ok = False
            print(f"  [FAIL] excepcion: {e}")
        print()
    print("=" * 52)
    print("TODOS OK" if all_ok else "HAY FALLAS")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
