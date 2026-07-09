"""bench_voxel_mesh.py
=====================

Harness de baseline / verificacion para `acoustic_mesh.build_volume_mesh`.

Mide y captura outputs ANTES de cualquier cambio. Despues de modificar
`acoustic_mesh.py`, se vuelve a correr este script y se compara contra el
JSON guardado para verificar:
  - Igualdad bit-exact de tets producidos (mismo set de indices).
  - Igualdad numerica de autovalores FEM (rtol < 1e-10).
  - Speedup real del cuello de botella (`points_inside_surface`).

Uso:
    python bench_voxel_mesh.py             # corre, imprime, guarda baseline_voxel_mesh.json
    python bench_voxel_mesh.py --compare   # corre y compara contra baseline existente

Nota: este script NO modifica ningun archivo del proyecto. Solo lee
`acoustic_mesh.py` y `acoustic_fem.py` via import normal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

# Forzar UTF-8 en stdout (Windows default cp1252 no soporta unicode comun)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import numpy as np

# Imports del proyecto (sin tocar nada)
from geometry import make_room
import acoustic_mesh as am
import acoustic_fem as afem


BASELINE_PATH = Path(__file__).parent / "baseline_voxel_mesh.json"

# Configuracion de casos de test: cubrir shoebox, polygon, curva.
TEST_CASES = [
    {
        "id": "shoebox_4x5x3_npm2.5",
        "params": dict(width=4.0, length=5.0, height=3.0, n_walls=4),
        "n_per_meter": 2.5,
    },
    {
        "id": "shoebox_6x8x3_npm2.5",
        "params": dict(width=6.0, length=8.0, height=3.0, n_walls=4),
        "n_per_meter": 2.5,
    },
    {
        "id": "shoebox_6x8x3_npm3.5",
        "params": dict(width=6.0, length=8.0, height=3.0, n_walls=4),
        "n_per_meter": 3.5,
    },
    {
        "id": "pentagon_8x8x4_npm2.5",
        "params": dict(width=8.0, length=8.0, height=4.0, n_walls=5),
        "n_per_meter": 2.5,
    },
    {
        "id": "hexagon_10x10x4_npm2.5",
        "params": dict(width=10.0, length=10.0, height=4.0, n_walls=6),
        "n_per_meter": 2.5,
    },
    {
        "id": "arch_6x8x3_arch1.0_npm2.5",
        "params": dict(width=6.0, length=8.0, height=3.0, n_walls=4,
                       arch_height=1.0, roof_type="arch"),
        "n_per_meter": 2.5,
    },
]

N_REPEATS = 3       # corridas para mediana
N_MODES = 12        # modos a calcular para verificacion


# ---------------------------------------------------------------------------
# Medicion
# ---------------------------------------------------------------------------
def time_call(fn: Callable, *args, **kwargs):
    """Cronometra una llamada, devuelve (resultado, segundos)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return result, t1 - t0


def measure_case(case: dict) -> dict:
    """Mide un caso N_REPEATS veces y agrega los resultados."""
    print(f"\n[{case['id']}]")
    print(f"  params: {case['params']}  npm={case['n_per_meter']}")

    # Build superficie (1 vez, no se cronometra)
    v, t, _e, _n = make_room(**case["params"])
    print(f"  surface: {len(v)} verts, {len(t)} tris")

    # Mediciones: build_volume_mesh + points_inside_surface aislado
    t_total_list = []
    t_inside_list = []
    nodes_ref, tets_ref = None, None

    for rep in range(N_REPEATS):
        # build_volume_mesh completo
        (nodes, tets), dt_total = time_call(
            am.build_volume_mesh, v, t, n_per_meter=case["n_per_meter"])
        t_total_list.append(dt_total)

        # Aislar points_inside_surface sobre los mismos centroides que usa
        # build_volume_mesh internamente. Esto mide SOLO el cuello.
        # Reproducimos la generacion de centroides:
        xmin, ymin, zmin = v.min(axis=0)
        xmax, ymax, zmax = v.max(axis=0)
        Lx, Ly, Lz = xmax - xmin, ymax - ymin, zmax - zmin
        npm = case["n_per_meter"]
        nx = max(2, int(round(Lx * npm)))
        ny = max(2, int(round(Ly * npm)))
        nz = max(2, int(round(Lz * npm)))
        # Cap matching el de am.build_volume_mesh
        total = (nx + 1) * (ny + 1) * (nz + 1)
        while total > 50000 and npm > 0.5:
            npm *= 0.8
            nx = max(2, int(round(Lx * npm)))
            ny = max(2, int(round(Ly * npm)))
            nz = max(2, int(round(Lz * npm)))
            total = (nx + 1) * (ny + 1) * (nz + 1)
        xs = np.linspace(xmin, xmax, nx + 1)
        ys = np.linspace(ymin, ymax, ny + 1)
        zs = np.linspace(zmin, zmax, nz + 1)
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        grid_nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

        # Reconstruir cand_tets como hace build_volume_mesh
        def gid(i, j, k):
            return (i * (ny + 1) + j) * (nz + 1) + k

        cand_tets = np.empty((nx * ny * nz * 6, 4), dtype=int)
        e = 0
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    vs = (
                        gid(i,     j,     k),
                        gid(i + 1, j,     k),
                        gid(i,     j + 1, k),
                        gid(i + 1, j + 1, k),
                        gid(i,     j,     k + 1),
                        gid(i + 1, j,     k + 1),
                        gid(i,     j + 1, k + 1),
                        gid(i + 1, j + 1, k + 1),
                    )
                    for tet in am.HEX_TO_TETS:
                        cand_tets[e] = (vs[tet[0]], vs[tet[1]],
                                        vs[tet[2]], vs[tet[3]])
                        e += 1
        centroids = grid_nodes[cand_tets].mean(axis=1)

        # Medir SOLO points_inside_surface
        _, dt_inside = time_call(
            am.points_inside_surface, centroids, v, t)
        t_inside_list.append(dt_inside)

        # Capturar mesh de la primera corrida (las siguientes deben ser identicas
        # porque el algoritmo es deterministico)
        if rep == 0:
            nodes_ref, tets_ref = nodes, tets

    # Calcular FEM modal sobre la malla de referencia (1 vez, no cronometrar)
    K, M, _ = afem.build_KM(nodes_ref, tets_ref)
    freqs, _ = afem.solve_modes(K, M, n_modes=N_MODES)

    # Resumen
    t_total_med = statistics.median(t_total_list)
    t_inside_med = statistics.median(t_inside_list)
    pct_inside = 100.0 * t_inside_med / t_total_med if t_total_med > 0 else 0.0

    print(f"  mesh:    {len(nodes_ref)} nodos, {len(tets_ref)} tets, "
          f"V_aabb*npm^3~={len(centroids)} centroides evaluados")
    print(f"  total:   {t_total_med*1000:7.1f} ms (med 3 corridas, "
          f"min={min(t_total_list)*1000:.1f} max={max(t_total_list)*1000:.1f})")
    print(f"  inside:  {t_inside_med*1000:7.1f} ms ({pct_inside:.0f}% del total)")
    print(f"  freqs (Hz): {', '.join(f'{f:.2f}' for f in freqs[:6])}...")

    # Capturar para JSON: hash canonico de tets (order-independent, deterministico
    # entre corridas via hashlib en vez de hash() builtin que usa PYTHONHASHSEED).
    canon = np.sort(np.asarray(tets_ref, dtype=np.int64), axis=1)
    order = np.lexsort(canon.T[::-1])
    canon = np.ascontiguousarray(canon[order])
    tets_hash_str = hashlib.md5(canon.tobytes()).hexdigest()

    return {
        "id": case["id"],
        "params": case["params"],
        "n_per_meter": case["n_per_meter"],
        "n_nodes": int(len(nodes_ref)),
        "n_tets": int(len(tets_ref)),
        "n_centroids_evaluated": int(len(centroids)),
        "t_total_ms_med": t_total_med * 1000,
        "t_total_ms_min": min(t_total_list) * 1000,
        "t_total_ms_max": max(t_total_list) * 1000,
        "t_inside_ms_med": t_inside_med * 1000,
        "t_inside_ms_min": min(t_inside_list) * 1000,
        "t_inside_ms_max": max(t_inside_list) * 1000,
        "pct_inside": pct_inside,
        "freqs_hz": [float(f) for f in freqs],
        # Hash canonico md5 (determinista entre corridas)
        "tets_hash": tets_hash_str,
    }


# ---------------------------------------------------------------------------
# Comparacion
# ---------------------------------------------------------------------------
def compare_against_baseline(current: list, baseline_path: Path):
    """Compara resultados actuales contra baseline guardada."""
    if not baseline_path.exists():
        print(f"\nNo existe baseline en {baseline_path}.")
        print("Corre primero sin --compare para generarla.")
        return False

    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    base_cases = {c["id"]: c for c in base["cases"]}

    print("\n" + "=" * 78)
    print(" COMPARACION vs baseline")
    print("=" * 78)
    print(f"{'caso':<32} {'tets_ok':>8} {'freqs_ok':>9} "
          f"{'t_total':>15} {'t_inside':>15}")
    print("-" * 78)

    all_ok = True
    for cur in current:
        bid = cur["id"]
        if bid not in base_cases:
            print(f"  {bid}: NO esta en baseline (caso nuevo)")
            continue
        b = base_cases[bid]

        tets_ok = (cur["n_tets"] == b["n_tets"]
                   and cur["tets_hash"] == b["tets_hash"])
        freqs_diff = np.array(cur["freqs_hz"]) - np.array(b["freqs_hz"])
        freqs_rtol = np.max(np.abs(freqs_diff) /
                            np.maximum(np.abs(b["freqs_hz"]), 1e-9))
        freqs_ok = freqs_rtol < 1e-10

        t_total_speedup = b["t_total_ms_med"] / max(cur["t_total_ms_med"], 1e-6)
        t_inside_speedup = b["t_inside_ms_med"] / max(cur["t_inside_ms_med"], 1e-6)

        status_tets = "OK" if tets_ok else "DIFF"
        status_freqs = "OK" if freqs_ok else f"rtol={freqs_rtol:.1e}"

        print(f"{bid:<32} {status_tets:>8} {status_freqs:>9} "
              f"{cur['t_total_ms_med']:>7.1f}ms ({t_total_speedup:4.1f}x) "
              f"{cur['t_inside_ms_med']:>7.1f}ms ({t_inside_speedup:4.1f}x)")

        if not (tets_ok and freqs_ok):
            all_ok = False

    print("=" * 78)
    if all_ok:
        print(" Todos los casos preservan igualdad de output (tets + freqs).")
    else:
        print(" HAY DIFERENCIAS — revisar antes de aceptar el cambio.")
    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", action="store_true",
                        help="Compara contra baseline guardada en lugar de sobrescribirla.")
    parser.add_argument("--out", default=str(BASELINE_PATH),
                        help="Path del JSON de salida.")
    args = parser.parse_args()

    print("=" * 78)
    print(" Benchmark: acoustic_mesh.build_volume_mesh")
    print("=" * 78)
    print(f" Casos: {len(TEST_CASES)} | Corridas por caso: {N_REPEATS}")
    print(f" Output: {args.out}")
    print(f" Modo: {'COMPARAR' if args.compare else 'GENERAR baseline'}")

    results = []
    for case in TEST_CASES:
        try:
            results.append(measure_case(case))
        except Exception as exc:
            print(f"  ERROR en {case['id']}: {exc}")
            import traceback
            traceback.print_exc()

    payload = {
        "version": "1.0",
        "n_repeats": N_REPEATS,
        "n_modes": N_MODES,
        "python": sys.version,
        "cases": results,
    }

    if args.compare:
        ok = compare_against_baseline(results, BASELINE_PATH)
        sys.exit(0 if ok else 1)
    else:
        Path(args.out).write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nBaseline guardada en: {args.out}")
        print("Para comparar despues de modificar acoustic_mesh.py:")
        print(f"    python bench_voxel_mesh.py --compare")


if __name__ == "__main__":
    main()
