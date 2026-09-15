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

# pymeshlab: remesh isotropico para destrabar superficies CURVAS / CAD sucio.
# Es dependencia OPCIONAL: si no esta, la rama de remesh se salta y el router
# cae al camino de siempre (reparam -> voxel). Nunca deja al usuario sin malla.
#
# OJO (import PEREZOSO, no eager): pymeshlab EMPAQUETA su PROPIO Qt5 (Qt5Core.dll,
# ..., y un platforms/qwindows.dll). Si se importa ANTES de que el QApplication de
# PyQt5 cree su plugin de plataforma, tapa el "windows" de PyQt5 y la GUI no
# arranca ("Could not load the Qt platform plugin 'windows'"). Por eso NO se
# importa a nivel de modulo: solo dentro de _remesh_isotropic (que corre bien
# despues de que la GUI ya inicializo su plataforma). is_remesh_available() usa
# find_spec para saber si esta SIN importarlo.
import importlib.util as _ilu


def is_available() -> bool:
    """True si el modulo gmsh esta instalado en el env de Python."""
    return _HAS_GMSH


def is_remesh_available() -> bool:
    """True si pymeshlab esta instalado (habilita el remesh isotropico previo
    al mallado discreto, para superficies curvas o CAD con T-junctions).

    Usa find_spec: NO importa pymeshlab (importarlo antes del QApplication
    rompe el plugin de plataforma Qt de PyQt5, ver nota arriba)."""
    try:
        return _ilu.find_spec("pymeshlab") is not None
    except (ImportError, ValueError):
        return False


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
    # Eliminar caras DEGENERADAS (area ~0: vertices colineales/coincidentes). Un
    # solo triangulo de area nula hace que gmsh falle en generate(3) con
    # "Singular matrix 3x3" (no puede parametrizar/mallar ese parche). Aparecen,
    # p.ej., en el abanico de triangulacion de una tapa curva (arco) o columna.
    # OJO: solo se quitan si la malla SIGUE ESTANCA despues (borrarlas puede abrir
    # huecos si la degenerada estaba entre dos parches; una malla no estanca hace
    # fallar a gmsh igual, "overlapping facets"). Si abrir huecos la rompe, se
    # dejan (gmsh caera a voxel via el router, que si las tolera).
    try:
        nd = m.nondegenerate_faces()          # mascara de caras NO degeneradas
        if nd is not None and (~np.asarray(nd)).any():
            n_bad = int((~np.asarray(nd)).sum())
            was_wt = bool(m.is_watertight)
            m2 = m.copy()
            m2.update_faces(nd)
            m2.remove_unreferenced_vertices()
            if (not was_wt) or bool(m2.is_watertight):
                m = m2                        # seguro: no empeora la estanqueidad
                if progress:
                    progress(f"gmsh: quitadas {n_bad} caras degeneradas (area ~0)")
            elif progress:
                progress(f"gmsh: {n_bad} caras degeneradas dejadas (borrarlas "
                         "abriria huecos); probable fallback a voxel")
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


def _remesh_isotropic(verts, tris, target_len: float, iterations: int = 6,
                      progress: Optional[Callable[[str], None]] = None):
    """Remesh isotropico con pymeshlab (isotropic explicit remeshing).

    Produce una triangulacion UNIFORME y bien formada, sin T-junctions ni
    slivers, que es lo que el mallador 3D discreto de gmsh (recuperacion de
    frontera / boundary recovery) necesita para NO rechazar la malla con
    "Invalid boundary mesh (overlapping facets)". Es el paso clave para mallar
    superficies curvas importadas (bovedas, arcos) o CAD sucio (EASE).

    Devuelve (verts, tris) remallados y FUSIONADOS (trimesh process=True, para
    soldar los vertices duplicados que pymeshlab deja sueltos -> watertight), o
    None si pymeshlab no esta o el remesh falla (el caller cae al camino previo).

    Ref: Botsch & Kobbelt (2004), "A remeshing approach to multiresolution
    modeling"; implementacion MeshLab (Cignoni et al. 2008).
    """
    verts = np.asarray(verts, dtype=float)
    tris = np.asarray(tris, dtype=np.int32)
    if len(tris) == 0:
        return None
    # Import PEREZOSO (ver nota en la cabecera): pymeshlab trae su propio Qt5 y
    # solo es seguro importarlo despues de que la GUI creo su QApplication.
    # Ademas, al importarse SETEA QT_PLUGIN_PATH a su propia carpeta (con un
    # qwindows.dll ABI-incompatible con PyQt5); lo guardamos y RESTAURAMOS para
    # que no rompa plugins Qt que la GUI cargue on-demand despues (imageformats,
    # styles, etc.).
    _qpp_before = os.environ.get("QT_PLUGIN_PATH")
    try:
        import pymeshlab as _pyml
    except ImportError:
        return None
    finally:
        if _qpp_before is None:
            os.environ.pop("QT_PLUGIN_PATH", None)
        else:
            os.environ["QT_PLUGIN_PATH"] = _qpp_before
    try:
        ms = _pyml.MeshSet()
        ms.add_mesh(_pyml.Mesh(vertex_matrix=verts, face_matrix=tris))
        # OJO: NO limpiar con meshing_remove_duplicate_vertices ANTES del remesh.
        # Verificado empiricamente (determinista, 3 corridas): pre-soldar los
        # vertices hace que el remesher devuelva una superficie que gmsh rechaza
        # con "overlapping facets" (self-intersecta en las aristas vivas). Sin
        # pre-limpieza el remesh sale limpio y gmsh discreto lo malla (19643 tets
        # estables). La fusion de duplicados se hace DESPUES, con trimesh.
        # target_len absoluto en metros. La API cambio de nombre entre versiones
        # (AbsoluteValue -> PureValue en 2023+); probamos ambas.
        try:
            tl = _pyml.PureValue(float(target_len))
        except Exception:
            try:
                tl = _pyml.AbsoluteValue(float(target_len))
            except Exception:
                tl = float(target_len)
        ms.meshing_isotropic_explicit_remeshing(targetlen=tl,
                                                iterations=int(iterations))
        mm = ms.current_mesh()
        rv = np.asarray(mm.vertex_matrix(), dtype=float)
        rf = np.asarray(mm.face_matrix(), dtype=int)
    except Exception as e:
        if progress:
            progress(f"pymeshlab: remesh fallo ({str(e)[:80]}); sin remesh.")
        return None
    if len(rf) == 0:
        return None
    # Fusionar vertices duplicados: pymeshlab devuelve la malla con vertices
    # sin soldar en las costuras -> trimesh(process=False) la ve NO estanca.
    # process=True los suelda y recupera watertight (verificado en el spike).
    try:
        import trimesh
        m = trimesh.Trimesh(vertices=rv, faces=rf, process=True)
        try:
            m.fix_normals()
        except Exception:
            pass
        rv = np.asarray(m.vertices, dtype=float)
        rf = np.asarray(m.faces, dtype=int)
    except ImportError:
        pass
    if progress:
        progress(f"pymeshlab: remesh isotropico -> {len(rf)} tris uniformes "
                 f"(target {target_len:.2f} m)")
    return rv, rf


def _group_surfaces_into_shells(_gmsh, surf_tags):
    """Agrupa las superficies reconstruidas por gmsh en CASCARAS cerradas
    (componentes conexas): dos superficies estan en la misma cascara si comparten
    una curva de borde. Para un recinto+columna devuelve 2 grupos (paredes del
    recinto / paredes de la columna). Devuelve lista de listas de surface tags."""
    curve_to_surfs = {}
    for st in surf_tags:
        try:
            bnd = _gmsh.model.getBoundary([(2, st)], combined=False,
                                          oriented=False, recursive=False)
        except Exception:
            bnd = []
        for (_dim, ctag) in bnd:
            c = abs(int(ctag))
            curve_to_surfs.setdefault(c, []).append(st)
    parent = {st: st for st in surf_tags}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for surfs in curve_to_surfs.values():
        for s in surfs[1:]:
            union(surfs[0], s)
    groups = {}
    for st in surf_tags:
        groups.setdefault(find(st), []).append(st)
    return list(groups.values())


def _shell_bbox(_gmsh, shell):
    """AABB (min, max) de una cascara (union de bboxes de sus superficies)."""
    import numpy as _np
    lo = _np.full(3, _np.inf)
    hi = _np.full(3, -_np.inf)
    for st in shell:
        try:
            b = _gmsh.model.getBoundingBox(2, st)   # (xmin..zmin, xmax..zmax)
        except Exception:
            continue
        lo = _np.minimum(lo, b[:3])
        hi = _np.maximum(hi, b[3:])
    return lo, hi


def _build_volumes_with_voids(_gmsh, surf_tags, progress=None):
    """Define el/los volumen(es) a mallar. Con una sola cascara -> un volumen
    simple. Con varias -> la cascara exterior (mayor AABB) es la frontera y las
    interiores CONTENIDAS en ella son huecos: addVolume([ext, hueco1, ...]).
    Una cascara no contenida (dos recintos separados) recibe su propio volumen."""
    import numpy as _np
    shells = _group_surfaces_into_shells(_gmsh, surf_tags)
    if len(shells) <= 1:
        sl = _gmsh.model.geo.addSurfaceLoop(surf_tags)
        _gmsh.model.geo.addVolume([sl])
        return
    boxes = [_shell_bbox(_gmsh, s) for s in shells]
    # Exterior = mayor volumen de AABB.
    vols = [float(_np.prod(_np.maximum(hi - lo, 0.0))) for (lo, hi) in boxes]
    outer = int(_np.argmax(vols))
    lo_o, hi_o = boxes[outer]

    def _contained(lo_i, hi_i):
        eps = 1e-6
        return bool(_np.all(lo_i >= lo_o - eps) and _np.all(hi_i <= hi_o + eps))

    loops = [_gmsh.model.geo.addSurfaceLoop(s) for s in shells]
    holes, standalone = [], []
    for i, (lo_i, hi_i) in enumerate(boxes):
        if i == outer:
            continue
        (holes if _contained(lo_i, hi_i) else standalone).append(i)
    if progress:
        progress(f"gmsh: {len(shells)} cascaras -> 1 recinto con "
                 f"{len(holes)} hueco(s) interior(es)"
                 + (f" + {len(standalone)} cuerpo(s) aparte" if standalone else ""))
    _gmsh.model.geo.addVolume([loops[outer]] + [loops[i] for i in holes])
    for i in standalone:                 # recintos separados: su propio volumen
        _gmsh.model.geo.addVolume([loops[i]])


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
    remesh_target_len: Optional[float] = None,
    remesh_iterations: int = 6,
):
    """Genera una malla tetraedrica boundary-fitted con gmsh.

    Dos caminos de reconstruccion de la geometria desde la malla de superficie:

      - REPARAMETRIZACION (default, remesh_target_len=None): classifySurfaces +
        createGeometry. Rearma parches parametricos B-spline. Ideal para mallas
        limpias (geometria parametrica de la app). Falla ("overlapping facets" /
        "Singular matrix") sobre superficies curvas importadas o CAD con
        T-junctions, porque dos parches se solapan al aplanarlos al plano
        parametrico.

      - REMESH + DISCRETO (remesh_target_len set y pymeshlab disponible): remesh
        isotropico de la superficie (pymeshlab) -> triangulacion uniforme sin
        T-junctions -> gmsh malla el VOLUMEN con esa superficie como frontera
        DISCRETA fija (createTopology, sin reparametrizar). Es el camino para
        superficies CURVAS importadas (bovedas, arcos). Boundary-fitted a la
        superficie remallada.

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

    # Camino discreto: remesh isotropico previo (pymeshlab). Si se pidio pero
    # pymeshlab no esta o el remesh falla, use_discrete queda False y seguimos
    # por reparametrizacion (el caller ya intento eso; el router decide la cadena).
    use_discrete = False
    if remesh_target_len is not None:
        remeshed = _remesh_isotropic(surface_verts, surface_tris,
                                     float(remesh_target_len),
                                     iterations=remesh_iterations,
                                     progress=progress)
        if remeshed is not None:
            surface_verts, surface_tris = remeshed
            use_discrete = True
        elif progress:
            progress("gmsh: remesh no disponible; se usa reparametrizacion.")

    if auto_clean and not use_discrete:
        # El remesh ya deja la malla uniforme y estanca; auto_clean (que quita
        # degeneradas condicionalmente) solo aplica al camino de reparametrizacion.
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

        if use_discrete:
            # Camino DISCRETO: la superficie remallada (uniforme, sin T-junctions)
            # se toma como frontera FIJA. createTopology deriva las curvas/puntos
            # de los angulos de la malla y deja las superficies como entidades
            # geo, sin reparametrizarlas (sin aplanar al plano parametrico -> sin
            # "overlapping facets"). El volumen se define con esas superficies y
            # gmsh solo llena el interior con tets (boundary recovery).
            if progress: progress("gmsh: topologia discreta (sin reparametrizar)...")
            _gmsh.model.mesh.createTopology()
        else:
            # Camino REPARAMETRIZACION. Estrategia escalonada:
            # 1. classifySurfaces + createGeometry (lo ideal para malla limpia).
            # 2. Si falla por topologia, angulos mas permisivos.
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

        # Volumen a partir de los surface loops. Un CAD con HUECO INTERIOR (p.ej.
        # una columna piso-techo) tiene VARIAS cascaras cerradas: la exterior
        # (paredes del recinto) + una interior por cada hueco. gmsh malla el
        # recinto MENOS los huecos si el volumen se define como
        # addVolume([loop_exterior, loop_hueco1, ...]) (primer loop = frontera,
        # los siguientes = huecos). Un unico surface loop con TODAS las
        # superficies fallaba ("Invalid boundary mesh / overlapping facets").
        surfaces = _gmsh.model.getEntities(2)
        if not surfaces:
            _gmsh.finalize()
            raise RuntimeError("gmsh: no se reconstruyeron superficies del STL.")
        surf_tags = [e[1] for e in surfaces]
        _build_volumes_with_voids(_gmsh, surf_tags, progress=progress)
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
        "reconstruction": "discrete_remesh" if use_discrete else "reparam",
        "remeshed": bool(use_discrete),
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
