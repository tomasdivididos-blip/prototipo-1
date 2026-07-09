"""bench_voxel_extended.py
==========================

Mide el speedup de la vectorizacion de `points_inside_surface` para los 14
casos del verify (incluye no-convexos, gable, shed, OBJ icosphere).

Side-by-side: corre la implementacion ORIGINAL (inline desde verify) y la
VECTORIZADA (acoustic_mesh actual) sobre los mismos centroides en la misma
invocacion. Reporta speedup por caso.
"""

from __future__ import annotations

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import statistics
import time

import numpy as np

import acoustic_mesh as am
from verify_voxel_equivalence import (
    CASES, _orig_points_inside_surface, make_centroids,
)


N_REPEATS = 3


def time_call(fn, *args, **kwargs):
    t0 = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - t0


def main():
    print("=" * 96)
    print(" Speedup `points_inside_surface`: original vs vectorizado")
    print("=" * 96)
    print(f"{'caso':<38} {'Nt':>5} {'Np':>8} "
          f"{'orig ms':>10} {'vec ms':>10} {'speedup':>9}")
    print("-" * 96)

    rows = []
    for name, builder, npm in CASES:
        try:
            built = builder()
        except Exception as exc:
            print(f"{name:<38} ERROR builder: {exc}")
            continue
        if built is None:
            print(f"{name:<38} SKIPPED")
            continue
        v, t = built

        centroids, _, _, _ = make_centroids(v, npm)
        Nt, Np = len(t), len(centroids)

        # Original: solo si es viable (limitar a Nt*Np < 50M, ya cuesta seg)
        orig_pairs = Nt * Np
        if orig_pairs > 50_000_000:
            print(f"{name:<38} {Nt:>5} {Np:>8} "
                  f"{'skipped':>10} {'(too big)':>10} {'-':>9}")
            continue

        # Warm-up de cache
        am.points_inside_surface(centroids, v, t)

        ts_orig = [time_call(_orig_points_inside_surface, centroids, v, t)
                   for _ in range(N_REPEATS)]
        ts_vec = [time_call(am.points_inside_surface, centroids, v, t)
                  for _ in range(N_REPEATS)]
        t_orig = statistics.median(ts_orig)
        t_vec = statistics.median(ts_vec)
        speedup = t_orig / max(t_vec, 1e-9)

        rows.append((name, Nt, Np, t_orig, t_vec, speedup))
        print(f"{name:<38} {Nt:>5} {Np:>8} "
              f"{t_orig*1000:>9.1f}  {t_vec*1000:>9.2f} "
              f"{speedup:>7.1f}x")

    print("=" * 96)
    if rows:
        speedups = [r[5] for r in rows]
        print(f" Speedup: min {min(speedups):.1f}x | mediana {statistics.median(speedups):.1f}x "
              f"| max {max(speedups):.1f}x | n_casos {len(rows)}")


if __name__ == "__main__":
    main()
