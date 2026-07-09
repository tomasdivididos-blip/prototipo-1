"""verify_voxel_equivalence.py
==============================

Verifica que la version vectorizada de `acoustic_mesh.points_inside_surface` y
del bucle de `cand_tets` produce EXACTAMENTE los mismos resultados que la
implementacion original (inlineada abajo como `_orig_*`).

No depende del baseline JSON: corre las dos implementaciones lado a lado y
compara bit-a-bit.

Uso: python verify_voxel_equivalence.py
"""

from __future__ import annotations

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import numpy as np

from geometry import make_room
import acoustic_mesh as am


# ---------------------------------------------------------------------------
# Implementaciones ORIGINALES, copia exacta del codigo previo a vectorizar.
# Sirven solo para esta verificacion - no son llamadas desde el resto del soft.
# ---------------------------------------------------------------------------
def _orig_ray_triangles_intersect_count(orig, dirn, v0, v1, v2):
    eps = 1e-9
    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(dirn, e2)
    a = np.einsum("ij,ij->i", e1, h)
    mask_a = np.abs(a) > eps
    if not np.any(mask_a):
        return 0
    f = np.zeros_like(a)
    f[mask_a] = 1.0 / a[mask_a]
    s = orig - v0
    u = f * np.einsum("ij,ij->i", s, h)
    mask_u = (u >= 0.0) & (u <= 1.0) & mask_a
    q = np.cross(s, e1)
    v = f * np.einsum("j,ij->i", dirn, q)
    mask_v = (v >= 0.0) & (u + v <= 1.0) & mask_u
    t = f * np.einsum("ij,ij->i", e2, q)
    hit = mask_v & (t > eps)
    return int(np.count_nonzero(hit))


def _orig_points_inside_surface(points, surface_verts, surface_tris):
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    v0 = surface_verts[surface_tris[:, 0]]
    v1 = surface_verts[surface_tris[:, 1]]
    v2 = surface_verts[surface_tris[:, 2]]
    dirn = np.array([1e-4, 2e-4, 1.0])
    dirn /= np.linalg.norm(dirn)
    inside = np.zeros(len(pts), dtype=bool)
    for i, p in enumerate(pts):
        count = _orig_ray_triangles_intersect_count(p, dirn, v0, v1, v2)
        inside[i] = (count % 2) == 1
    return inside


def _orig_cand_tets(nx, ny, nz):
    """Reproduce el bucle triple original que genera cand_tets."""
    def gid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    cand_tets = np.empty((nx * ny * nz * 6, 4), dtype=int)
    e = 0
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                v = (
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
                    cand_tets[e] = (v[tet[0]], v[tet[1]], v[tet[2]], v[tet[3]])
                    e += 1
    return cand_tets


def _new_cand_tets(nx, ny, nz):
    """Replica el bloque vectorizado actual de build_volume_mesh."""
    def gid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    ii, jj, kk = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz),
                              indexing="ij")
    ii = ii.ravel(); jj = jj.ravel(); kk = kk.ravel()
    hex_corners = np.stack([
        gid(ii,     jj,     kk),
        gid(ii + 1, jj,     kk),
        gid(ii,     jj + 1, kk),
        gid(ii + 1, jj + 1, kk),
        gid(ii,     jj,     kk + 1),
        gid(ii + 1, jj,     kk + 1),
        gid(ii,     jj + 1, kk + 1),
        gid(ii + 1, jj + 1, kk + 1),
    ], axis=1)
    return hex_corners[:, am.HEX_TO_TETS].reshape(-1, 4)


# ---------------------------------------------------------------------------
# Builders de geometria: cada uno devuelve (v, t)
# ---------------------------------------------------------------------------
def build_from_params(**params):
    """Constructor que delega en make_room (geometria parametrica)."""
    def _builder():
        v, t, _, _ = make_room(**params)
        return v, t
    return _builder


def build_obj_icosphere():
    """OBJ roundtrip: icosphere via trimesh -> export OBJ -> reload -> (v, t).

    Testea el path real de importacion CAD para una malla curva no-trivial
    (~2500 triangulos) escalada a tamano de recinto.
    """
    import os
    import tempfile
    try:
        import trimesh
    except ImportError:
        return None  # se marca como skipped en runtime
    m = trimesh.creation.icosphere(subdivisions=3)   # 2562 vertices, 5120 faces
    m.apply_scale(3.0)
    m.apply_translation([3.0, 3.0, 3.0])             # centrar en (3,3,3)
    tmp_path = tempfile.NamedTemporaryFile(
        suffix=".obj", delete=False).name
    try:
        m.export(tmp_path)
        m_loaded = trimesh.load(tmp_path, force="mesh")
        v = np.asarray(m_loaded.vertices, dtype=float)
        t = np.asarray(m_loaded.faces, dtype=int)
        return v, t
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Casos de test: (id, builder, n_per_meter)
# ---------------------------------------------------------------------------
CASES = [
    # ----- baseline parametrico (mismos casos que el primer bench) -----
    ("shoebox_4x5x3 npm=2.5",
     build_from_params(width=4.0, length=5.0, height=3.0, n_walls=4), 2.5),
    ("shoebox_6x8x3 npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4), 2.5),
    ("shoebox_6x8x3 npm=3.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4), 3.5),
    ("pentagon_8x8x4 npm=2.5",
     build_from_params(width=8.0, length=8.0, height=4.0, n_walls=5), 2.5),
    ("hexagon_10x10x4 npm=2.5",
     build_from_params(width=10.0, length=10.0, height=4.0, n_walls=6), 2.5),
    ("arch_6x8x3 arch=1.0 npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4,
                        arch_height=1.0, roof_type="arch"), 2.5),

    # ----- plantas no convexas (base_polygon custom) -----
    ("L-shape 6x7x3 npm=2.5",
     build_from_params(
        width=6.0, length=7.0, height=3.0, n_walls=4,
        base_polygon=[(0, 0), (6, 0), (6, 4), (4, 4), (4, 7), (0, 7)],
        roof_type="flat"),
     2.5),
    ("U-shape 8x6x3 npm=2.5",
     build_from_params(
        width=8.0, length=6.0, height=3.0, n_walls=4,
        base_polygon=[(0, 0), (8, 0), (8, 6), (5, 6),
                       (5, 3), (3, 3), (3, 6), (0, 6)],
        roof_type="flat"),
     2.5),
    ("Plus-shape 6x6x3 npm=2.5",
     build_from_params(
        width=6.0, length=6.0, height=3.0, n_walls=4,
        base_polygon=[(2, 0), (4, 0), (4, 2), (6, 2), (6, 4), (4, 4),
                       (4, 6), (2, 6), (2, 4), (0, 4), (0, 2), (2, 2)],
        roof_type="flat"),
     2.5),

    # ----- techos especiales -----
    ("gable_6x8x3 arch=1.5 npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4,
                        arch_height=1.5, roof_type="gable",
                        ridge_offset=0.0), 2.5),
    ("gable_6x8x3 ridge=0.4 npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4,
                        arch_height=1.5, roof_type="gable",
                        ridge_offset=0.4), 2.5),
    ("shed_6x8x3 arch=1.5 npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=4,
                        arch_height=1.5, roof_type="shed"), 2.5),

    # ----- paredes inclinadas + taper + twist (combo complejo) -----
    ("tapered+twisted hexagon npm=2.5",
     build_from_params(width=6.0, length=8.0, height=3.0, n_walls=6,
                        taper=0.3, twist=15.0,
                        wall_inclinations=[10.0, -5.0, 8.0,
                                            -3.0, 6.0, -2.0]), 2.5),

    # ----- import OBJ real (trimesh roundtrip) -----
    ("OBJ_icosphere_r3 npm=2.0", build_obj_icosphere, 2.0),
]


def make_centroids(v, n_per_meter):
    """Reproduce la generacion de centroides de build_volume_mesh."""
    xmin, ymin, zmin = v.min(axis=0)
    xmax, ymax, zmax = v.max(axis=0)
    Lx, Ly, Lz = xmax - xmin, ymax - ymin, zmax - zmin
    npm = n_per_meter
    nx = max(2, int(round(Lx * npm)))
    ny = max(2, int(round(Ly * npm)))
    nz = max(2, int(round(Lz * npm)))
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

    cand_tets = _new_cand_tets(nx, ny, nz)
    centroids = grid_nodes[cand_tets].mean(axis=1)
    return centroids, nx, ny, nz


def main():
    print("=" * 88)
    print(" Verificacion: vectorizado vs original (bit-exact)")
    print("=" * 88)

    all_ok = True
    n_skipped = 0
    print(f"\n{'caso':<38} {'cand_tets':>10} {'inside':>11} "
          f"{'Nt':>5} {'centroides':>12}")
    print("-" * 88)
    for name, builder, npm in CASES:
        try:
            built = builder()
        except Exception as exc:
            print(f"{name:<38} ERROR builder: {exc}")
            all_ok = False
            continue
        if built is None:
            print(f"{name:<38} SKIPPED (builder devolvio None)")
            n_skipped += 1
            continue
        v, t = built

        centroids, nx, ny, nz = make_centroids(v, npm)

        # cand_tets: original vs vectorizado
        ct_orig = _orig_cand_tets(nx, ny, nz)
        ct_new = _new_cand_tets(nx, ny, nz)
        ct_ok = np.array_equal(ct_orig, ct_new)

        # points_inside_surface: original vs vectorizado actual
        inside_orig = _orig_points_inside_surface(centroids, v, t)
        inside_new = am.points_inside_surface(centroids, v, t)
        n_diff = int(np.count_nonzero(inside_orig != inside_new))
        in_ok = (n_diff == 0)

        status_ct = "OK" if ct_ok else "DIFF"
        status_in = "OK" if in_ok else f"{n_diff} dif."
        print(f"{name:<38} {status_ct:>10} {status_in:>11} "
              f"{len(t):>5} {len(centroids):>12}")

        if not (ct_ok and in_ok):
            all_ok = False

    print("=" * 88)
    if all_ok:
        n_run = len(CASES) - n_skipped
        print(f" Bit-exact en los {n_run} casos: cand_tets y mascara `inside` IDENTICAS.")
        if n_skipped:
            print(f" ({n_skipped} caso(s) saltado(s) por dependencia faltante)")
        print(" La vectorizacion preserva el output exactamente.")
        return 0
    else:
        print(" HAY DIFERENCIAS BIT-A-BIT. Revisar antes de aceptar.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
