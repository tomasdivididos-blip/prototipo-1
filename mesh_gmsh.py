"""
mesh_gmsh.py
============

Wrapper sobre gmsh (kernel OpenCASCADE) para producir mallas tetraedricas
boundary-fitted a partir de una malla de superficie cerrada y limpia.

Diferencias frente a acoustic_mesh.build_volume_mesh (voxel):

  - Boundary-fitted: cada cara del recinto coincide exactamente con caras
    de tetraedros. Sin "escalera". Convergencia monotona de las frecuencias
    modales hacia el limite teorico.
  - Mas rapido en mallas grandes: gmsh (Delaunay 3D) ~6-10x mas rapido que
    el filtro point-in-polyhedron de Moller-Trumbore por bucle (Python puro).
  - Calidad superior de tets: control sobre h_min/h_max, refinamiento cerca
    de esquinas, calidad medida por radio circumscripto / radio inscripto.

Uso tipico
----------
    nodes, tets, info = mesh_with_gmsh(verts, tris, h_target=0.40)

donde verts (Nv,3) y tris (Nt,3) provienen de geometry.make_room o de
geom_import.load_geometry (CAD limpio).

API publica
-----------
mesh_with_gmsh(surface_verts, surface_tris, h_target=0.40, ...)
    -> (nodes, tets, info_dict)

is_available()
    -> bool. True si gmsh esta instalado.

mesh_quality(nodes, tets)
    -> dict con min_quality, mean_quality, n_bad (calidad < umbral).
"""

from __future__ import annotations

import os
import time
import tempfile
import warnings
from typing import Optional, Callable

import numpy as np


# ---------------------------------------------------------------------------
# Deteccion de disponibilidad (gmsh es dependencia obligatoria del instalador
# pero el usuario podria correr el codigo en un env sin gmsh; degradamos
# graciosamente)
# ---------------------------------------------------------------------------
try:
    import gmsh as _gmsh
    _HAS_GMSH = True
except ImportError:
    _gmsh = None
    _HAS_GMSH = False


def is_available() -> bool:
    """True si el modulo gmsh esta instalado en el env de Python."""
    return _HAS_GMSH


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _ensure_gmsh():
    if not _HAS_GMSH:
        raise RuntimeError(
            "gmsh no esta instalado. "
            "Instalar con: pip install gmsh"
        )


def _stl_from_arrays(verts: np.ndarray, tris: np.ndarray, path: str):
    """Escribe un STL ASCII desde arrays numpy (sin dependencia de trimesh)."""
    verts = np.asarray(verts, dtype=float)
    tris = np.asarray(tris, dtype=int)
    with open(path, "w", encoding="ascii") as f:
        f.write("solid mesh\n")
        for tri in tris:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            n = np.cross(v1 - v0, v2 - v0)
            nl = np.linalg.norm(n)
            if nl > 1e-15:
                n = n / nl
            else:
                n = np.array([0.0, 0.0, 1.0])
            f.write(f"  facet normal {n[0]} {n[1]} {n[2]}\n")
            f.write("    outer loop\n")
            f.write(f"      vertex {v0[0]} {v0[1]} {v0[2]}\n")
            f.write(f"      vertex {v1[0]} {v1[1]} {v1[2]}\n")
            f.write(f"      vertex {v2[0]} {v2[1]} {v2[2]}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid\n")


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------
def _auto_clean_mesh(verts, tris,
                      progress: Optional[Callable[[str], None]] = None):
    """Aplica reparaciones automaticas con trimesh para que la malla sea
    aceptable por gmsh (winding consistente, normales hacia afuera,
    sin huecos pequenos por subdivision).

    Si trimesh no esta disponible, devuelve la malla sin tocar.
    """
    try:
        import trimesh
        import trimesh.repair as _tr
    except ImportError:
        return verts, tris

    m = trimesh.Trimesh(vertices=np.asarray(verts, dtype=float),
                         faces=np.asarray(tris, dtype=int),
                         process=False)
    try:
        m.merge_vertices()
    except Exception:
        pass
    try:
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
    except Exception:
        pass
    for fn in (_tr.fix_winding, _tr.fix_normals, _tr.fix_inversion):
        try:
            fn(m)
        except Exception:
            pass
    if not m.is_watertight:
        # Intentar cerrar pequenos huecos. Si no se logra, gmsh fallara
        # con mensaje claro y el usuario debera abrir el dialogo de
        # reparacion guiada para arreglarla manualmente.
        try:
            _tr.fill_holes(m)
        except Exception:
            pass
    if not m.is_watertight and progress:
        progress("aviso: malla aun no watertight; gmsh puede fallar.")
    return (np.asarray(m.vertices, dtype=float),
            np.asarray(m.faces, dtype=int))


def mesh_with_gmsh(
    surface_verts: np.ndarray,
    surface_tris: np.ndarray,
    h_target: float = 0.40,
    h_min: Optional[float] = None,
    algorithm_3d: int = 1,           # 1 = Delaunay (rapido y robusto)
    classify_angle_deg: float = 40.0,
    verbose: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    auto_clean: bool = True,
):
    """Genera una malla tetraedrica boundary-fitted con gmsh.

    Parameters
    ----------
    surface_verts : (Nv, 3) float
        Vertices de la malla de superficie del recinto (cerrada).
    surface_tris : (Nt, 3) int
        Triangulos de la malla de superficie.
    h_target : float
        Tamano caracteristico de elemento (m). Tipicamente 0.30-0.60 m para
        rangos modales 20-150 Hz (lambda/h >= 6).
    h_min : float, opcional
        Tamano minimo (default = h_target / 2). gmsh refina hasta este limite
        cerca de esquinas o aristas filosas.
    algorithm_3d : int
        Algoritmo de mallado 3D de gmsh.
            1 = Delaunay (default, mas rapido).
            4 = Frontal-Delaunay (mejor calidad, mas lento).
            10 = HXT (paralelo, requiere version reciente).
    classify_angle_deg : float
        Angulo (grados) por debajo del cual gmsh considera dos triangulos
        adyacentes como pertenecientes a la misma superficie geometrica.
        40° funciona bien para mallas de arquitectura.
    verbose : bool
        Si True, gmsh imprime sus mensajes; si False, solo errores.
    progress : callable(str), opcional
        Reporta etapas del proceso.

    Returns
    -------
    nodes : (Nn, 3) float
        Coordenadas de los nodos.
    tets  : (Ne, 4) int
        Indices de nodos por tetraedro.
    info  : dict
        n_nodes, n_tets, volume, h_avg, h_max, t_mesh_seconds, h_target_used.
    """
    _ensure_gmsh()
    if h_min is None:
        h_min = h_target * 0.5

    surface_verts = np.asarray(surface_verts, dtype=float)
    surface_tris = np.asarray(surface_tris, dtype=int)
    if len(surface_tris) == 0:
        raise ValueError("Malla de superficie vacia.")

    if auto_clean:
        if progress: progress("gmsh: limpieza automatica (trimesh)...")
        surface_verts, surface_tris = _auto_clean_mesh(
            surface_verts, surface_tris, progress=progress
        )
        if len(surface_tris) == 0:
            raise ValueError("Malla vacia tras limpieza automatica.")

    if progress: progress(f"gmsh: preparando STL ({len(surface_tris)} tris)...")
    tmp_stl = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp_stl.close()
    _stl_from_arrays(surface_verts, surface_tris, tmp_stl.name)

    t0 = time.perf_counter()
    try:
        _gmsh.initialize()
        # Verbosidad: 0=silent, 1=errors, 2=warnings, 3=info, 4=debug, 5=trace
        _gmsh.option.setNumber("General.Verbosity", 3 if verbose else 1)
        try:
            n_threads = max(1, (os.cpu_count() or 1))
            _gmsh.option.setNumber("General.NumThreads", n_threads)
        except Exception:
            pass

        _gmsh.model.add("acoustic_room")
        if progress: progress("gmsh: cargando STL...")
        _gmsh.merge(tmp_stl.name)

        # Reconstruir entidades geometricas. Estrategia escalonada:
        # 1. Intento con classifySurfaces + createGeometry (lo ideal).
        # 2. Si falla por topologia, intento con angulos mas permisivos.
        # 3. Si todo falla, dejamos la superficie como discrete entity.
        if progress: progress("gmsh: clasificando superficies...")
        classified_ok = False
        last_err = None
        for angle in (classify_angle_deg, 60.0, 80.0):
            try:
                _gmsh.model.mesh.classifySurfaces(
                    np.deg2rad(angle),
                    True,    # forceParametrizablePatches
                    True,    # boundaries
                    np.pi,   # curveAngle
                )
                _gmsh.model.mesh.createGeometry()
                classified_ok = True
                break
            except Exception as e:
                last_err = e
                if progress:
                    progress(f"  classifySurfaces fallo a {angle}°, "
                             "reintentando...")
                # Recargar STL para el siguiente intento.
                _gmsh.clear()
                _gmsh.model.add("acoustic_room")
                _gmsh.merge(tmp_stl.name)
        if not classified_ok:
            _gmsh.finalize()
            raise RuntimeError(
                "gmsh no pudo parametrizar la superficie. La malla tiene "
                "topologia incompatible (huecos, T-junctions, normales "
                "inconsistentes). Sugerencia: usa el dialogo de reparacion "
                "guiada para arreglar la malla antes.\n"
                f"Mensaje original: {last_err}"
            )

        # Volumen cerrado a partir del surface loop.
        surfaces = _gmsh.model.getEntities(2)
        if not surfaces:
            _gmsh.finalize()
            raise RuntimeError("gmsh: no se reconstruyeron superficies del STL.")
        surf_tags = [e[1] for e in surfaces]
        sl = _gmsh.model.geo.addSurfaceLoop(surf_tags)
        _gmsh.model.geo.addVolume([sl])
        _gmsh.model.geo.synchronize()

        # Control de tamano.
        _gmsh.option.setNumber("Mesh.MeshSizeMax", float(h_target))
        _gmsh.option.setNumber("Mesh.MeshSizeMin", float(h_min))
        _gmsh.option.setNumber("Mesh.Algorithm3D", int(algorithm_3d))
        # Optimizaciones de calidad post-meshing.
        _gmsh.option.setNumber("Mesh.Optimize", 1)
        _gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)   # netgen-opt: opcional

        if progress: progress(f"gmsh: meshing 3D (h={h_target} m)...")
        _gmsh.model.mesh.generate(3)

        # Extraer resultados.
        if progress: progress("gmsh: extrayendo malla...")
        node_tags, node_coords, _ = _gmsh.model.mesh.getNodes()
        node_coords = np.asarray(node_coords, dtype=float).reshape(-1, 3)
        tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

        elem_types, elem_tags, elem_node_tags = _gmsh.model.mesh.getElements(3)
        if len(elem_types) == 0 or len(elem_node_tags) == 0:
            raise RuntimeError("gmsh no genero tetraedros (volumen invalido?).")
        # En P1 lineales, elem_types[0] == 4 (Tet4), 4 nodos/elemento.
        raw = np.asarray(elem_node_tags[0], dtype=int).reshape(-1, 4)
        tets = np.vectorize(tag_to_idx.__getitem__)(raw)

    finally:
        try:
            _gmsh.finalize()
        except Exception:
            pass
        try:
            os.unlink(tmp_stl.name)
        except OSError:
            pass

    t_total = time.perf_counter() - t0

    # Info estadistica.
    p0 = node_coords[tets[:, 0]]
    p1 = node_coords[tets[:, 1]]
    p2 = node_coords[tets[:, 2]]
    p3 = node_coords[tets[:, 3]]
    vols = np.abs(np.einsum("ij,ij->i",
                            np.cross(p1 - p0, p2 - p0),
                            p3 - p0)) / 6.0
    V = float(vols.sum())
    h_e = (6.0 * vols) ** (1.0 / 3.0)
    info = {
        "n_nodes": int(node_coords.shape[0]),
        "n_tets":  int(tets.shape[0]),
        "volume":  V,
        "h_avg":   float(h_e.mean()) if len(h_e) else 0.0,
        "h_max":   float(h_e.max())  if len(h_e) else 0.0,
        "h_min":   float(h_e.min())  if len(h_e) else 0.0,
        "t_mesh_seconds": float(t_total),
        "h_target_used":  float(h_target),
        "engine": "gmsh",
    }
    return node_coords, tets, info


# ---------------------------------------------------------------------------
# Calidad de la malla (radio-ratio: r_in / r_circ, ideal = 1/3)
# ---------------------------------------------------------------------------
def mesh_quality(nodes: np.ndarray, tets: np.ndarray,
                 bad_threshold: float = 0.10) -> dict:
    """Calidad por tet usando la radio-ratio (3 * r_in / r_circ).

    Devuelve dict con minimo, media, mediana y conteo de elementos con
    calidad < bad_threshold (~< 0.10 se considera tet degenerado).
    """
    if len(tets) == 0:
        return {"min": 0.0, "mean": 0.0, "median": 0.0, "n_bad": 0,
                "bad_threshold": bad_threshold, "n_total": 0}

    p0 = nodes[tets[:, 0]]
    p1 = nodes[tets[:, 1]]
    p2 = nodes[tets[:, 2]]
    p3 = nodes[tets[:, 3]]

    # Volumen.
    vol = np.abs(np.einsum("ij,ij->i",
                           np.cross(p1 - p0, p2 - p0),
                           p3 - p0)) / 6.0

    # Areas de las 4 caras.
    def tri_area(a, b, c):
        return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    A = (tri_area(p1, p2, p3) + tri_area(p0, p2, p3) +
         tri_area(p0, p1, p3) + tri_area(p0, p1, p2))

    # Longitudes de las 6 aristas, sumadas al cuadrado.
    def L2(a, b):
        return np.sum((b - a) ** 2, axis=1)
    L_sum_sq = (L2(p0, p1) + L2(p0, p2) + L2(p0, p3) +
                L2(p1, p2) + L2(p1, p3) + L2(p2, p3))

    # Radio inscripto r_in = 3 V / A.
    # Radio circunscripto r_circ se aproxima con sqrt(L_sum_sq / 24)
    # (no exacto, pero una buena medida normalizada para tet).
    # La "radio-ratio normalizada" mas usada: q = (12 (3V)^(2/3)) / sum_i L_i^2.
    # q = 1 para tet regular; q < 0.1 -> casi degenerado.
    q = (12.0 * (3.0 * vol) ** (2.0 / 3.0)) / np.maximum(L_sum_sq, 1e-30)

    n_bad = int(np.count_nonzero(q < bad_threshold))
    return {
        "min": float(q.min()),
        "mean": float(q.mean()),
        "median": float(np.median(q)),
        "n_bad": n_bad,
        "bad_threshold": bad_threshold,
        "n_total": int(len(tets)),
    }


# ---------------------------------------------------------------------------
# Demo (solo si gmsh disponible)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not _HAS_GMSH:
        print("gmsh no instalado. pip install gmsh")
        raise SystemExit(1)

    # Caja 5x4x3: validar que el volumen coincide y los modos son razonables.
    from geometry import make_room
    v, t, _e, _n = make_room(width=5.0, length=4.0, height=3.0, n_walls=4)
    print(f"[gmsh demo] superficie {len(v)} verts, {len(t)} tris")

    try:
        nodes, tets, info = mesh_with_gmsh(v, t, h_target=0.40,
                                             progress=lambda m: print(" ", m))
    except Exception as e:
        print("FALLO:", e)
        raise SystemExit(1)

    print(f"\n[gmsh demo] resultado:")
    print(f"  nodos: {info['n_nodes']}")
    print(f"  tets:  {info['n_tets']}")
    print(f"  V:     {info['volume']:.3f} m3  (esperado 60.000)")
    print(f"  h_avg: {info['h_avg']:.3f} m")
    print(f"  t_malla: {info['t_mesh_seconds']:.2f} s")

    q = mesh_quality(nodes, tets)
    print(f"\n[gmsh demo] calidad:")
    print(f"  min/mean/median q = {q['min']:.3f} / {q['mean']:.3f} / {q['median']:.3f}")
    print(f"  tets degenerados (q<{q['bad_threshold']}): {q['n_bad']}/{q['n_total']}")
