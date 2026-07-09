"""
acoustic_mesh.py
================

Mallado volumetrico tetraedrico para un recinto de geometria arbitraria
(la malla de superficie viene de geometry.make_room).

Estrategia
----------
1) Calcular el bounding box (AABB) del recinto.
2) Generar una rejilla estructurada de hexaedros dentro del AABB.
3) Subdividir cada hexaedro en 6 tetraedros conformes (Freudenthal).
4) Filtrar tetraedros cuyo centroide cae FUERA del recinto, usando un
   test point-in-polyhedron por raycast sobre la malla de superficie.

Resultado: malla tetraedrica interior al recinto, con "frontera tipo escalera"
en las zonas no axis-aligned. Para mallas finas (h << lambda_min) el error
de frontera es pequeno; el solver FEM con paredes rigidas (Neumann homogenea
impuesta de forma natural en la forma debil) tolera bien este sesgo.

Ventaja: no requiere bibliotecas externas (TetGen, CGAL); solo numpy.
Limitacion: la frontera no es exacta. Si se necesita mayor fidelidad, se
puede aumentar n_per_meter.

API
---
build_volume_mesh(surface_verts, surface_tris, n_per_meter=3.0)
    -> nodes (Nn,3), tets (Ne,4)

points_inside_surface(points, surface_verts, surface_tris)
    -> bool array (N,) por raycast +z.
"""

from __future__ import annotations

import numpy as np


# Mismo split conforme que usa fem_modal.HEX_TO_TETS (Freudenthal, 6 tets/hex).
HEX_TO_TETS = np.array([
    [0, 1, 3, 7],
    [0, 1, 7, 5],
    [0, 5, 7, 4],
    [0, 3, 2, 7],
    [0, 2, 6, 7],
    [0, 6, 4, 7],
], dtype=int)


# ---------------------------------------------------------------------------
# Helper privado: volumen de cada tet, vectorizado.
# ---------------------------------------------------------------------------
# Reutilizado por build_volume_mesh (filtro de slivers) y por mesh_info
# (estadisticos). Identidad usada:
#     V_e = | ((v1-v0) x (v2-v0)) . (v3-v0) | / 6
# ---------------------------------------------------------------------------
def _tet_volumes(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    if len(tets) == 0:
        return np.zeros(0, dtype=float)
    p0 = nodes[tets[:, 0]]
    p1 = nodes[tets[:, 1]]
    p2 = nodes[tets[:, 2]]
    p3 = nodes[tets[:, 3]]
    return np.abs(np.einsum("ij,ij->i",
                            np.cross(p1 - p0, p2 - p0),
                            p3 - p0)) / 6.0


# Umbral relativo para considerar un tet como "sliver" (volumen casi cero).
# Usado en build_volume_mesh para limpieza, y en mesh_info para reporte.
_SLIVER_REL_TOL = 1e-6


# ---------------------------------------------------------------------------
# Test point-in-polyhedron por raycast (Moller-Trumbore) - vectorizado en lote
# ---------------------------------------------------------------------------
# El metodo original evaluaba un punto contra todos los triangulos en numpy,
# pero hacia un bucle Python sobre los puntos. Para 14 400 puntos x 12-500
# triangulos esto dominaba el tiempo de `build_volume_mesh` (>= 95 % del total
# medido en bench_voxel_mesh.py).
#
# Esta version procesa TODOS los puntos contra TODOS los triangulos en una
# sola expresion broadcasted, con chunking para acotar la memoria peak. La
# semantica (direccion del rayo, eps, regla de paridad) es identica.
_CHUNK_PAIRS = 10_000_000   # ~ 250 MB peak temporal (~120 B por par p-t)


def points_inside_surface(points: np.ndarray,
                          surface_verts: np.ndarray,
                          surface_tris: np.ndarray) -> np.ndarray:
    """Test point-in-polyhedron para una nube de puntos.

    Usa un rayo en +z con una pequena inclinacion (para evitar tocar aristas
    exactamente en el mismo plano) y cuenta intersecciones: impar = adentro.

    Vectorizado: procesa todos los puntos contra todos los triangulos en una
    sola expresion broadcasted, en chunks para mantener memoria acotada.
    """
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    Np = pts.shape[0]
    if Np == 0:
        return np.zeros(0, dtype=bool)

    v0 = surface_verts[surface_tris[:, 0]]
    v1 = surface_verts[surface_tris[:, 1]]
    v2 = surface_verts[surface_tris[:, 2]]
    Nt = v0.shape[0]
    if Nt == 0:
        return np.zeros(Np, dtype=bool)

    # Direccion inclinada -> evita coincidencias degeneradas. Misma que la
    # version anterior (preserva igualdad bit-exact de resultados).
    dirn = np.array([1e-4, 2e-4, 1.0])
    dirn = dirn / np.linalg.norm(dirn)
    eps = 1e-9

    # Cantidades que dependen SOLO del triangulo (computadas una vez para todos
    # los puntos del lote).
    e1 = v1 - v0                                    # (Nt, 3)
    e2 = v2 - v0                                    # (Nt, 3)
    h = np.cross(dirn, e2)                          # (Nt, 3)
    a = np.einsum("tj,tj->t", e1, h)                # (Nt,)
    mask_a = np.abs(a) > eps                        # (Nt,)
    f = np.zeros(Nt, dtype=float)
    f[mask_a] = 1.0 / a[mask_a]

    # Chunking por puntos: cap memoria a ~_CHUNK_PAIRS pares (p, t) en flight.
    chunk_size = max(1, _CHUNK_PAIRS // max(Nt, 1))
    counts = np.zeros(Np, dtype=np.int64)

    mask_a_b = mask_a[None, :]                      # (1, Nt) para broadcasting

    for start in range(0, Np, chunk_size):
        end = min(start + chunk_size, Np)
        pts_chunk = pts[start:end]                  # (n, 3)

        # s[p, t] = pts[p] - v0[t]  ->  (n, Nt, 3)
        s = pts_chunk[:, None, :] - v0[None, :, :]

        # u[p, t] = f[t] * (s[p, t] . h[t])
        u = f[None, :] * np.einsum("ptj,tj->pt", s, h)

        # q[p, t] = cross(s[p, t], e1[t])  ->  (n, Nt, 3)
        q = np.cross(s, e1[None, :, :])

        # v_bc[p, t] = f[t] * (dirn . q[p, t])
        v_bc = f[None, :] * np.einsum("j,ptj->pt", dirn, q)

        # t_bc[p, t] = f[t] * (e2[t] . q[p, t])
        t_bc = f[None, :] * np.einsum("tj,ptj->pt", e2, q)

        # Mascaras de hit (Moller-Trumbore)
        mask_u = (u >= 0.0) & (u <= 1.0) & mask_a_b
        mask_v = (v_bc >= 0.0) & (u + v_bc <= 1.0) & mask_u
        hit = mask_v & (t_bc > eps)                 # (n, Nt) bool

        counts[start:end] = hit.sum(axis=1)

    return (counts % 2) == 1


# ---------------------------------------------------------------------------
# Mallado volumetrico
# ---------------------------------------------------------------------------
def build_volume_mesh(surface_verts: np.ndarray,
                      surface_tris: np.ndarray,
                      n_per_meter: float = 3.0,
                      max_nodes: int = 50000):
    """Construye una malla tetraedrica del INTERIOR del recinto.

    Parameters
    ----------
    surface_verts : (Nv, 3)
        Vertices de la malla de superficie (lo que devuelve geometry.make_room).
    surface_tris : (Nt, 3)
        Triangulos de la malla de superficie.
    n_per_meter : float
        Densidad de la rejilla: ~ celdas por metro en cada eje.
    max_nodes : int
        Cap de seguridad: si la rejilla supera este nro de nodos, se
        reduce n_per_meter automaticamente.

    Returns
    -------
    nodes : (Nn, 3) coordenadas de los nodos interiores.
    tets  : (Ne, 4) indices en nodes (re-mapeados, sin huecos).
    """
    surface_verts = np.asarray(surface_verts, dtype=float)
    surface_tris = np.asarray(surface_tris, dtype=int)

    # AABB con un pequeno margen interior negativo -> los nodos exteriores
    # se filtran de todas formas y asi cubrimos toda la geometria.
    xmin, ymin, zmin = surface_verts.min(axis=0)
    xmax, ymax, zmax = surface_verts.max(axis=0)
    Lx = xmax - xmin
    Ly = ymax - ymin
    Lz = zmax - zmin

    nx = max(2, int(round(Lx * n_per_meter)))
    ny = max(2, int(round(Ly * n_per_meter)))
    nz = max(2, int(round(Lz * n_per_meter)))

    # Cap por seguridad de memoria.
    total = (nx + 1) * (ny + 1) * (nz + 1)
    while total > max_nodes and n_per_meter > 0.5:
        n_per_meter *= 0.8
        nx = max(2, int(round(Lx * n_per_meter)))
        ny = max(2, int(round(Ly * n_per_meter)))
        nz = max(2, int(round(Lz * n_per_meter)))
        total = (nx + 1) * (ny + 1) * (nz + 1)

    xs = np.linspace(xmin, xmax, nx + 1)
    ys = np.linspace(ymin, ymax, ny + 1)
    zs = np.linspace(zmin, zmax, nz + 1)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    grid_nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    def gid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    # Tetraedros candidatos (en el bounding box) - vectorizado.
    # meshgrid con indexing="ij" + ravel(C order) preserva el orden del bucle
    # original i-fastest-outer, k-fastest-inner (mismo `cand_tets` que antes).
    ii, jj, kk = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz),
                              indexing="ij")
    ii = ii.ravel(); jj = jj.ravel(); kk = kk.ravel()
    # 8 esquinas de cada hex, mismo orden que la tupla original `v`:
    hex_corners = np.stack([
        gid(ii,     jj,     kk),
        gid(ii + 1, jj,     kk),
        gid(ii,     jj + 1, kk),
        gid(ii + 1, jj + 1, kk),
        gid(ii,     jj,     kk + 1),
        gid(ii + 1, jj,     kk + 1),
        gid(ii,     jj + 1, kk + 1),
        gid(ii + 1, jj + 1, kk + 1),
    ], axis=1)                                   # (n_hex, 8)
    # Indexar HEX_TO_TETS: (n_hex, 6, 4) -> (n_hex*6, 4) preserva orden.
    cand_tets = hex_corners[:, HEX_TO_TETS].reshape(-1, 4)

    # Filtro por centroide: tet queda si su baricentro cae dentro del solido.
    centroids = grid_nodes[cand_tets].mean(axis=1)
    keep = points_inside_surface(centroids, surface_verts, surface_tris)
    kept_tets = cand_tets[keep]

    if kept_tets.size == 0:
        # Fallback: malla degenerada (recinto degenerado o sin volumen).
        return np.zeros((0, 3)), np.zeros((0, 4), dtype=int)

    # Capa 1: filtro de slivers.
    # Los tets degenerados (vertices casi coplanares) aparecen sobre todo en
    # bordes escalonados de paredes oblicuas. Ensucian K y M con entradas
    # mal escaladas (det(V4) casi cero -> gradientes enormes) y son la causa
    # principal de no-convergencia en Lanczos para mallas no axis-aligned.
    # Los descartamos antes de devolver la malla, con umbral relativo al
    # volumen medio de los tets que pasaron el filtro de centroide.
    vols_kept = _tet_volumes(grid_nodes, kept_tets)
    if vols_kept.size > 0 and vols_kept.mean() > 0:
        sliver_mask = vols_kept > (_SLIVER_REL_TOL * vols_kept.mean())
        kept_tets = kept_tets[sliver_mask]

    if kept_tets.size == 0:
        return np.zeros((0, 3)), np.zeros((0, 4), dtype=int)

    # Re-mapear nodos: solo los que aparecen en algun tet.
    used_idx = np.unique(kept_tets)
    new_idx = -np.ones(grid_nodes.shape[0], dtype=int)
    new_idx[used_idx] = np.arange(len(used_idx))
    nodes = grid_nodes[used_idx]
    tets = new_idx[kept_tets]
    return nodes, tets


def subdivide_surface(verts: np.ndarray, tris: np.ndarray,
                      levels: int = 0):
    """Subdivide cada triangulo de superficie en 4 sub-triangulos (midpoint).

    levels=0: sin cambio.
    levels=1: 4x triangulos.
    levels=2: 16x triangulos.
    levels=3: 64x triangulos.
    Util para refinar la discretizacion de la superficie.
    """
    if levels <= 0:
        return np.asarray(verts, dtype=float), np.asarray(tris, dtype=int)
    v = np.asarray(verts, dtype=float).tolist()
    t = np.asarray(tris, dtype=int)
    for _ in range(levels):
        edge_mid = {}
        new_t = []
        for tri in t:
            a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
            for i, j in ((a, b), (b, c), (c, a)):
                key = (min(i, j), max(i, j))
                if key not in edge_mid:
                    edge_mid[key] = len(v)
                    v.append([(v[i][k] + v[j][k]) * 0.5 for k in range(3)])
            ab = edge_mid[(min(a, b), max(a, b))]
            bc = edge_mid[(min(b, c), max(b, c))]
            ca = edge_mid[(min(c, a), max(c, a))]
            new_t += [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]
        t = np.array(new_t, dtype=int)
    return np.array(v, dtype=float), t


def mesh_info(nodes: np.ndarray, tets: np.ndarray) -> dict:
    """Estadisticos basicos y de CALIDAD de una malla tet.

    Claves devueltas:
      - n_nodes, n_tets, volume : cuenta y volumen total.
      - h_avg, h_max, h_min     : tamano caracteristico (V_e^(1/3) * factor).
      - h_ratio                 : h_max / h_min. Indica heterogeneidad de
                                  la malla. Valores > 50 sugieren tets muy
                                  alargados (slivers / aspect ratio alto).
      - n_slivers               : cantidad de tets con volumen < 1e-4 del
                                  promedio. Con el filtro de Capa 1 activo
                                  este valor deberia ser 0 en mallas sanas.
                                  Si > 0, la malla puede inducir no-
                                  convergencia en Lanczos.
    """
    if len(tets) == 0:
        return {"n_nodes": 0, "n_tets": 0, "volume": 0.0,
                "h_avg": 0.0, "h_max": 0.0, "h_min": 0.0,
                "h_ratio": 0.0, "n_slivers": 0}

    # Volumen total y tamano caracteristico de elemento.
    vols = _tet_volumes(nodes, tets)
    V = float(vols.sum())
    # h_e: lado caracteristico ~ V_e^(1/3) * factor.
    h_e = (6.0 * vols) ** (1.0 / 3.0)
    h_min = float(h_e.min())
    h_max = float(h_e.max())

    # Capa 4: diagnostico de calidad.
    # Reporte de slivers usando el mismo umbral relativo que el filtro de
    # Capa 1. Si hay slivers despues del mallado, algo no esta funcionando
    # (puede aparecer si el usuario llama build_KM con una malla externa
    # no filtrada).
    mean_vol = float(vols.mean()) if vols.size > 0 else 0.0
    if mean_vol > 0:
        n_slivers = int(np.sum(vols < _SLIVER_REL_TOL * 100 * mean_vol))
    else:
        n_slivers = 0

    return {
        "n_nodes":   int(nodes.shape[0]),
        "n_tets":    int(tets.shape[0]),
        "volume":    V,
        "h_avg":     float(h_e.mean()),
        "h_max":     h_max,
        "h_min":     h_min,
        "h_ratio":   h_max / max(h_min, 1e-30),
        "n_slivers": n_slivers,
    }


def max_solver_frequency(h_max: float, c: float = 343.0,
                          ppw: float = 6.0) -> float:
    """Maxima f admisible para una malla con tamano max h_max.

    Regla practica: lambda / h >= ppw  =>  f_max = c / (ppw * h_max).
    """
    if h_max <= 0:
        return 0.0
    return c / (ppw * h_max)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Caja 5x4x3: verificamos que la malla queda con todos los puntos adentro.
    from geometry import make_room
    v, t, _e, _n = make_room(width=5.0, length=4.0, height=3.0, n_walls=4)
    nodes, tets = build_volume_mesh(v, t, n_per_meter=2.0)
    info = mesh_info(nodes, tets)
    print(f"[mesh] nodos={info['n_nodes']}, tets={info['n_tets']}, "
          f"V={info['volume']:.3f} m^3 (esperado 60), h_avg={info['h_avg']:.3f} m")
    print(f"[mesh] f_max (ppw=6) = {max_solver_frequency(info['h_max']):.1f} Hz")
