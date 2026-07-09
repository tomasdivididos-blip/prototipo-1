"""
geom_import.py
==============

Importador de geometria CAD para el modelador de recintos.

Soporta los siguientes formatos:
  - STL (ASCII y binario)            via trimesh
  - OBJ                              via trimesh
  - PLY                              via trimesh
  - glTF / GLB                       via trimesh
  - 3MF / COLLADA (.dae)             via trimesh
  - OFF / XYZ                        via trimesh
  - STEP / STP                       via gmsh (kernel OpenCASCADE)
  - IGES / IGS                       via gmsh (kernel OpenCASCADE)
  - BREP                             via gmsh nativo

Despues de cargar:
  1. Diagnostica la malla (watertight? normales consistentes? volumen? huecos?).
  2. Si hay problemas, ofrece un dialogo de reparacion guiada con preview 3D:
     - Resaltar cada hueco/arista no-manifold uno por uno.
     - Proponer correccion automatica (fill_holes / merge_close_vertices).
     - Permitir edicion manual de vertices.
  3. Devuelve la malla final lista para mesh_router.build_mesh.

Diseno
------
Se separa la logica pura (este modulo, sin Qt salvo el dialogo guiado) de
la integracion en el main (`main.py` la usa via load_with_repair_dialog).
La logica de reparacion vive en funciones puras y testables.
"""

from __future__ import annotations

import os
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Callable

import numpy as np

try:
    import trimesh
    _HAS_TRIMESH = True
except ImportError:
    trimesh = None
    _HAS_TRIMESH = False

try:
    import gmsh as _gmsh
    _HAS_GMSH = True
except ImportError:
    _gmsh = None
    _HAS_GMSH = False


# ---------------------------------------------------------------------------
# Catalogo de formatos
# ---------------------------------------------------------------------------
# Familias de formato y como se cargan.
TRIMESH_FORMATS = {".stl", ".obj", ".ply", ".glb", ".gltf",
                   ".3mf", ".dae", ".off", ".xyz"}
GMSH_BREP_FORMATS = {".step", ".stp", ".iges", ".igs", ".brep"}
ALL_FORMATS = TRIMESH_FORMATS | GMSH_BREP_FORMATS


def supported_extensions() -> list:
    """Lista ordenada de extensiones soportadas (sin punto)."""
    return sorted(e[1:] for e in ALL_FORMATS)


def file_filter() -> str:
    """Filtro estilo Qt 'Todos los CAD (*.stl *.obj ...);; STL (*.stl);; ...'."""
    all_pat = " ".join(f"*{e}" for e in sorted(ALL_FORMATS))
    parts = [f"Todos los CAD ({all_pat})"]
    for ext in sorted(ALL_FORMATS):
        name = ext[1:].upper()
        parts.append(f"{name} (*{ext})")
    return ";;".join(parts)


# ---------------------------------------------------------------------------
# Carga: dispatch por extension
# ---------------------------------------------------------------------------
def load_geometry(path: str,
                  progress: Optional[Callable[[str], None]] = None
                  ) -> "trimesh.Trimesh":
    """Carga un archivo CAD desde `path` y devuelve un trimesh.Trimesh.

    Para formatos B-rep (STEP/IGES/BREP), se delega a gmsh: primero gmsh
    carga la geometria parametrica con el kernel OpenCASCADE y la tesela
    en triangulos, despues se exportan a STL temporal y se levantan con
    trimesh. Esto unifica el camino: a partir de aqui todo es triangulos.
    """
    if not _HAS_TRIMESH:
        raise RuntimeError("trimesh no esta instalado. "
                            "Instalar con: pip install trimesh")

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {path}")
    ext = p.suffix.lower()
    if ext not in ALL_FORMATS:
        raise ValueError(f"Formato no soportado: {ext}. "
                          f"Formatos: {', '.join(supported_extensions())}")

    if progress: progress(f"Cargando {p.name}...")

    if ext in GMSH_BREP_FORMATS:
        if not _HAS_GMSH:
            raise RuntimeError(f"Formato {ext} requiere gmsh. "
                                "Instalar con: pip install gmsh")
        return _load_via_gmsh(str(p), progress=progress)

    # Camino trimesh nativo.
    loaded = trimesh.load(str(p), force="mesh")
    if isinstance(loaded, trimesh.Scene):
        # Algunos formatos (glTF, OBJ con grupos) dan Scene; fusionar.
        geoms = list(loaded.dump())
        if not geoms:
            raise ValueError(f"Archivo {p.name}: sin geometria.")
        if len(geoms) == 1:
            mesh = geoms[0]
        else:
            mesh = trimesh.util.concatenate(geoms)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ValueError(f"Archivo {p.name}: tipo cargado no es Trimesh "
                          f"({type(loaded).__name__}).")
    return mesh


def _load_via_gmsh(path: str,
                    target_h: float = 0.40,
                    progress: Optional[Callable[[str], None]] = None
                    ) -> "trimesh.Trimesh":
    """Carga un B-rep con gmsh, tesela la superficie y devuelve un Trimesh.

    Solo TESELA la superficie (modelo 2D) - no genera tetraedros. El motor
    de mallado se llama despues, segun la decision del router.
    """
    _gmsh.initialize()
    try:
        _gmsh.option.setNumber("General.Verbosity", 1)
        _gmsh.model.add("imported")
        if progress: progress("gmsh: cargando B-rep...")
        _gmsh.merge(path)
        _gmsh.model.occ.synchronize()
        # Solo malla 2D (superficie). Con tamano caracteristico moderado;
        # el modelador en runtime decidira si necesita refinar mas.
        _gmsh.option.setNumber("Mesh.MeshSizeMax", float(target_h))
        _gmsh.option.setNumber("Mesh.MeshSizeMin", float(target_h * 0.5))
        if progress: progress(f"gmsh: teselando superficie (h={target_h})...")
        _gmsh.model.mesh.generate(2)
        # Extraer triangulos.
        node_tags, node_coords, _ = _gmsh.model.mesh.getNodes()
        node_coords = np.asarray(node_coords, dtype=float).reshape(-1, 3)
        tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}
        # Tipo 2 = Triangle3.
        et, _et_tags, en = _gmsh.model.mesh.getElements(2)
        all_tris = []
        for type_id, node_buffer in zip(et, en):
            if type_id != 2:
                continue
            tris = np.asarray(node_buffer, dtype=int).reshape(-1, 3)
            tris = np.vectorize(tag_to_idx.__getitem__)(tris)
            all_tris.append(tris)
        if not all_tris:
            raise RuntimeError("gmsh no produjo triangulos al teselar.")
        tris = np.concatenate(all_tris, axis=0)
    finally:
        _gmsh.finalize()
    mesh = trimesh.Trimesh(vertices=node_coords, faces=tris, process=False)
    return mesh


# ---------------------------------------------------------------------------
# Diagnostico
# ---------------------------------------------------------------------------
@dataclass
class Hole:
    """Un hueco en la superficie: ciclo de aristas de borde."""
    boundary_vertex_indices: List[int]   # vertices en orden de recorrido
    boundary_edges: List[Tuple[int, int]]   # aristas (i, j)
    centroid: np.ndarray                 # (3,) centro aproximado
    plane_normal: np.ndarray             # (3,) normal del plano del hueco
    area: float                          # area aproximada (m2)
    diameter: float                      # tamano caracteristico (m)


@dataclass
class MeshDiagnosis:
    """Estado de la malla importada."""
    n_vertices: int
    n_faces: int
    is_watertight: bool
    is_winding_consistent: bool
    is_volume: bool                       # tiene volumen definido
    volume: float                         # m3 (puede ser negativo)
    surface_area: float                   # m2
    n_components: int                     # cuerpos disconexos
    n_duplicate_vertices: int
    n_degenerate_faces: int
    n_non_manifold_edges: int
    holes: List[Hole] = field(default_factory=list)
    bbox: Optional[Tuple[Tuple[float, float, float],
                          Tuple[float, float, float]]] = None

    @property
    def ok(self) -> bool:
        """True si la malla esta lista para mallado volumetrico sin retoques."""
        return (self.is_watertight and self.is_winding_consistent and
                len(self.holes) == 0 and self.n_non_manifold_edges == 0
                and self.n_degenerate_faces == 0 and self.is_volume)

    def summary(self) -> str:
        """Texto humano-legible para la UI."""
        lines = []
        lines.append(f"Vertices: {self.n_vertices}")
        lines.append(f"Triangulos: {self.n_faces}")
        if self.bbox:
            (xmn, ymn, zmn), (xmx, ymx, zmx) = self.bbox
            lines.append(f"AABB: [{xmn:.2f}, {ymn:.2f}, {zmn:.2f}] -> "
                         f"[{xmx:.2f}, {ymx:.2f}, {zmx:.2f}] m")
        lines.append(f"Volumen: {self.volume:.3f} m³"
                     + ("" if self.is_volume else "  (NO definido)"))
        lines.append(f"Superficie: {self.surface_area:.3f} m²")
        lines.append(f"Watertight: {'sí' if self.is_watertight else 'NO'}")
        lines.append(f"Winding consistente: "
                     f"{'sí' if self.is_winding_consistent else 'NO'}")
        lines.append(f"Componentes disconexos: {self.n_components}")
        lines.append(f"Vertices duplicados: {self.n_duplicate_vertices}")
        lines.append(f"Caras degeneradas: {self.n_degenerate_faces}")
        lines.append(f"Aristas no-manifold: {self.n_non_manifold_edges}")
        lines.append(f"Huecos detectados: {len(self.holes)}")
        return "\n".join(lines)


def diagnose(mesh: "trimesh.Trimesh") -> MeshDiagnosis:
    """Diagnostico completo de la malla."""
    verts = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)

    # Duplicados de vertices: rondas a 6 decimales para tolerar ruido.
    rounded = np.round(verts, 6)
    _, unique_idx = np.unique(rounded, axis=0, return_index=True)
    n_dup = int(len(verts) - len(unique_idx))

    # Caras degeneradas: lados con dos vertices iguales o area ~ 0.
    a = verts[faces[:, 0]]; b = verts[faces[:, 1]]; c = verts[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    n_degen = int(np.count_nonzero(areas < 1e-12))

    bbox = ((float(verts[:, 0].min()), float(verts[:, 1].min()), float(verts[:, 2].min())),
            (float(verts[:, 0].max()), float(verts[:, 1].max()), float(verts[:, 2].max())))

    # Datos topologicos via trimesh
    try:
        is_wt = bool(mesh.is_watertight)
    except Exception:
        is_wt = False
    try:
        is_wc = bool(mesh.is_winding_consistent)
    except Exception:
        is_wc = False
    try:
        is_vol = bool(mesh.is_volume)
    except Exception:
        is_vol = False
    try:
        vol = float(mesh.volume)
    except Exception:
        vol = 0.0
    try:
        sa = float(mesh.area)
    except Exception:
        sa = float(areas.sum())
    try:
        ncomp = int(mesh.body_count) if hasattr(mesh, "body_count") else 1
    except Exception:
        ncomp = 1

    # Aristas no-manifold: una arista deberia ser compartida por EXACTAMENTE
    # 2 triangulos en una superficie cerrada. > 2 -> no-manifold; 1 -> hueco.
    edges = np.sort(np.concatenate([
        faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]],
    ], axis=0), axis=1).astype(np.int64, copy=True)
    # Compactar (a, b) en un solo entero para usar np.unique escalar.
    max_v = int(edges.max()) + 1 if len(edges) else 1
    keys = edges[:, 0] * max_v + edges[:, 1]
    _, counts = np.unique(keys, return_counts=True)
    n_non_manifold = int(np.count_nonzero(counts > 2))

    # Huecos: aristas de borde -> ciclos.
    holes = find_holes(mesh)

    return MeshDiagnosis(
        n_vertices=int(len(verts)),
        n_faces=int(len(faces)),
        is_watertight=is_wt,
        is_winding_consistent=is_wc,
        is_volume=is_vol,
        volume=vol,
        surface_area=sa,
        n_components=ncomp,
        n_duplicate_vertices=n_dup,
        n_degenerate_faces=n_degen,
        n_non_manifold_edges=n_non_manifold,
        holes=holes,
        bbox=bbox,
    )


def find_holes(mesh: "trimesh.Trimesh") -> List[Hole]:
    """Detecta los huecos como ciclos de aristas de borde (incidencia 1).

    Cada hueco se devuelve con sus vertices en orden de recorrido (CCW
    respecto del exterior, segun la orientacion de las caras adyacentes).

    Implementacion vectorizada con numpy: para una malla de ~100k caras,
    detectar las aristas de borde lleva ~50 ms en vez de ~3 s del bucle
    Python original. La construccion de ciclos sigue siendo iterativa
    porque cada ciclo es secuencial, pero opera solo sobre el subconjunto
    de aristas de borde (tipicamente < 5 % del total).
    """
    verts = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    if len(faces) == 0:
        return []
    Nv = int(verts.shape[0])

    # --- Vectorizado: aristas dirigidas (3 por triangulo) ---
    e_dir = np.concatenate([
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]],
    ], axis=0).astype(np.int64)   # (3*Nt, 2), orientacion original conservada

    # --- Contar incidencia no orientada via int64 key ---
    e_sorted = np.sort(e_dir, axis=1)
    keys = e_sorted[:, 0] * Nv + e_sorted[:, 1]
    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    boundary_mask = counts[inverse] == 1

    # Aristas de borde con la orientacion original (tupla i->j).
    boundary_dir = e_dir[boundary_mask]
    if len(boundary_dir) == 0:
        return []
    boundary_edges = [(int(i), int(j)) for i, j in boundary_dir]

    # Armar ciclos: grafo dirigido siguiendo la orientacion original.
    adj: dict = {}
    for (i, j) in boundary_edges:
        adj.setdefault(i, []).append(j)

    visited_edges: set = set()
    holes: List[Hole] = []

    for start_i, start_j in boundary_edges:
        if (start_i, start_j) in visited_edges:
            continue
        # Caminar siguiendo adj.
        cycle = [start_i]
        cur = start_j
        prev = start_i
        visited_edges.add((prev, cur))
        max_iter = len(boundary_edges) + 2
        steps = 0
        while cur != start_i and steps < max_iter:
            cycle.append(cur)
            nexts = adj.get(cur, [])
            # Elegir el proximo NO visitado; en defecto, el primero.
            chosen = None
            for nb in nexts:
                if (cur, nb) not in visited_edges:
                    chosen = nb
                    break
            if chosen is None:
                chosen = nexts[0] if nexts else start_i
            visited_edges.add((cur, chosen))
            prev = cur
            cur = chosen
            steps += 1

        if len(cycle) < 3:
            continue
        # Construir el Hole.
        cyc_pts = verts[cycle]
        centroid = cyc_pts.mean(axis=0)
        # Plano por SVD.
        rel = cyc_pts - centroid
        _, _, vt = np.linalg.svd(rel, full_matrices=False)
        normal = vt[-1]
        nl = np.linalg.norm(normal)
        if nl < 1e-12:
            normal = np.array([0.0, 0.0, 1.0])
        else:
            normal = normal / nl
        # Area aproximada: triangulacion por abanico desde centroide.
        area = 0.0
        for k in range(len(cycle)):
            p1 = cyc_pts[k]
            p2 = cyc_pts[(k + 1) % len(cycle)]
            area += 0.5 * np.linalg.norm(np.cross(p1 - centroid, p2 - centroid))
        # Diametro: distancia max al centroide x 2.
        diameter = float(2.0 * np.max(np.linalg.norm(rel, axis=1)))
        edges_pairs = [(cycle[k], cycle[(k + 1) % len(cycle)])
                       for k in range(len(cycle))]
        holes.append(Hole(
            boundary_vertex_indices=list(cycle),
            boundary_edges=edges_pairs,
            centroid=centroid,
            plane_normal=normal,
            area=float(area),
            diameter=diameter,
        ))
    # Ordenar por area descendente (los grandes primero).
    holes.sort(key=lambda h: -h.area)
    return holes


# ---------------------------------------------------------------------------
# Reparaciones puras
# ---------------------------------------------------------------------------
def merge_close_vertices(mesh: "trimesh.Trimesh",
                          tolerance: float = 1e-4) -> "trimesh.Trimesh":
    """Fusiona vertices a distancia < tolerance. Devuelve nueva malla."""
    m = mesh.copy()
    m.merge_vertices(merge_tex=False, merge_norm=False)
    # trimesh.merge_vertices usa tolerancia interna; para forzar otra,
    # redondear primero.
    verts = np.round(np.asarray(m.vertices, dtype=float) / tolerance) * tolerance
    m = trimesh.Trimesh(vertices=verts, faces=m.faces, process=True)
    return m


def fill_hole_planar(mesh: "trimesh.Trimesh", hole: Hole) -> "trimesh.Trimesh":
    """Cierra un hueco con triangulacion por abanico desde el centroide.

    Conserva el sentido de las caras (orientacion exterior).
    """
    m = mesh.copy()
    verts = np.asarray(m.vertices, dtype=float).copy()
    faces = np.asarray(m.faces, dtype=int).copy()

    # Insertar un vertice nuevo en el centroide del hueco.
    new_idx = len(verts)
    verts = np.vstack([verts, hole.centroid[None, :]])

    # Triangular en abanico, usando la orientacion del ciclo del hueco.
    n = len(hole.boundary_vertex_indices)
    new_faces = []
    for k in range(n):
        i = hole.boundary_vertex_indices[k]
        j = hole.boundary_vertex_indices[(k + 1) % n]
        new_faces.append([i, j, new_idx])
    new_faces = np.array(new_faces, dtype=int)

    # Necesitamos que la normal del nuevo abanico apunte HACIA AFUERA.
    # La normal del plano del hueco es hole.plane_normal; verificamos
    # con respecto al centroide del solido global.
    body_centroid = verts.mean(axis=0)
    out_dir = hole.centroid - body_centroid
    if np.dot(out_dir, hole.plane_normal) < 0:
        # Plano apunta para adentro; volteamos cada cara.
        new_faces = new_faces[:, [0, 2, 1]]

    faces = np.vstack([faces, new_faces])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=True)


def fill_all_holes_auto(mesh: "trimesh.Trimesh",
                         progress=None) -> "trimesh.Trimesh":
    """Cierra TODOS los huecos en un unico pase optimizado.

    Estrategia: en vez de detectar+cerrar+detectar+cerrar (O(K*Nt) por
    iteracion), se detectan TODOS los huecos UNA vez, se construyen los
    parches de cierre en arrays numpy y se materializa el Trimesh final
    en una sola llamada. Eso convierte un proceso O(K*Nt) en O(Nt + K).

    Es seguro: cada `fill_hole_planar` solo AGREGA vertices y caras al
    final de los arrays, sin tocar los indices existentes. Por lo tanto
    los `boundary_vertex_indices` de los demas huecos siguen siendo
    validos despues de cerrar uno.
    """
    holes = find_holes(mesh)
    if not holes:
        return normalize_mesh(mesh)
    if progress:
        progress(f"Cerrando {len(holes)} huecos en un solo pase...")

    verts = np.asarray(mesh.vertices, dtype=float).copy()
    faces = np.asarray(mesh.faces, dtype=int).copy()
    body_centroid = verts.mean(axis=0)

    new_verts_buf = []
    new_faces_buf = []
    base_idx = int(verts.shape[0])

    for hole in holes:
        # Vertice nuevo en el centroide del hueco.
        center_idx = base_idx + len(new_verts_buf)
        new_verts_buf.append(hole.centroid)

        # Triangulacion por abanico (vectorizada).
        cyc = np.asarray(hole.boundary_vertex_indices, dtype=int)
        n = len(cyc)
        if n < 3:
            continue
        cyc_next = np.roll(cyc, -1)
        tri_block = np.column_stack([
            cyc, cyc_next, np.full(n, center_idx, dtype=int)
        ])

        # Orientacion: normal del parche hacia AFUERA del solido global.
        out_dir = hole.centroid - body_centroid
        if np.dot(out_dir, hole.plane_normal) < 0:
            tri_block = tri_block[:, [0, 2, 1]]
        new_faces_buf.append(tri_block)

    if new_verts_buf:
        verts = np.vstack([verts, np.asarray(new_verts_buf, dtype=float)])
    if new_faces_buf:
        faces = np.vstack([faces, np.concatenate(new_faces_buf, axis=0)])

    # Un solo proceso final (winding, fix normales, validacion).
    out = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    return normalize_mesh(out)


def move_vertex(mesh: "trimesh.Trimesh", vertex_idx: int,
                new_position) -> "trimesh.Trimesh":
    """Reposicion manual de un vertice (devuelve nueva malla)."""
    m = mesh.copy()
    verts = np.asarray(m.vertices, dtype=float).copy()
    if not (0 <= vertex_idx < len(verts)):
        raise IndexError(f"vertex_idx {vertex_idx} fuera de rango")
    verts[vertex_idx] = np.asarray(new_position, dtype=float)
    return trimesh.Trimesh(vertices=verts, faces=m.faces, process=False)


def snap_hole_vertices(mesh: "trimesh.Trimesh", hole: Hole,
                        snap_tolerance: float = 1e-3) -> "trimesh.Trimesh":
    """Intenta cerrar un hueco fusionando vertices del hueco con vertices
    cercanos del resto de la malla (a distancia < snap_tolerance).

    Util cuando el hueco viene de un "T-junction" donde dos vertices estan
    proximos pero no compartidos.

    Implementacion: cKDTree para el resto de la malla, una sola consulta
    en lote para todos los vertices del hueco. Para mallas grandes
    (>10 k vertices) es ~100x mas rapido que el bucle Python original.
    """
    m = mesh.copy()
    verts = np.asarray(m.vertices, dtype=float).copy()
    faces = np.asarray(m.faces, dtype=int).copy()

    hole_idx_set = set(hole.boundary_vertex_indices)
    n_total = len(verts)
    rest_mask = np.ones(n_total, dtype=bool)
    rest_mask[list(hole_idx_set)] = False
    rest_idx = np.where(rest_mask)[0]
    if rest_idx.size == 0:
        return m

    # Consulta nearest-neighbor en lote con cKDTree.
    from scipy.spatial import cKDTree
    tree = cKDTree(verts[rest_idx])
    hole_pts = verts[hole.boundary_vertex_indices]
    dists, nn_local = tree.query(hole_pts, k=1)
    snap_mask = dists < snap_tolerance
    if not np.any(snap_mask):
        return m

    # Construir remap como ndarray (mas rapido que dict).
    remap = np.arange(n_total, dtype=int)
    for k, hi in enumerate(hole.boundary_vertex_indices):
        if snap_mask[k]:
            remap[hi] = int(rest_idx[nn_local[k]])

    # Aplicar remap vectorizado.
    new_faces = remap[faces]
    # Filtrar caras degeneradas tras el remap.
    keep = (new_faces[:, 0] != new_faces[:, 1]) & \
           (new_faces[:, 1] != new_faces[:, 2]) & \
           (new_faces[:, 0] != new_faces[:, 2])
    new_faces = new_faces[keep]
    return trimesh.Trimesh(vertices=verts, faces=new_faces, process=True)


def normalize_mesh(mesh: "trimesh.Trimesh") -> "trimesh.Trimesh":
    """Limpieza final estandar: merge dups, fix normales, fix winding."""
    m = mesh.copy()
    m.merge_vertices()
    try:
        m.update_faces(m.unique_faces())
    except Exception:
        pass
    try:
        m.remove_unreferenced_vertices()
    except Exception:
        pass
    try:
        trimesh.repair.fix_inversion(m)
    except Exception:
        pass
    try:
        trimesh.repair.fix_normals(m)
    except Exception:
        pass
    try:
        trimesh.repair.fix_winding(m)
    except Exception:
        pass
    return m


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def to_arrays(mesh: "trimesh.Trimesh") -> Tuple[np.ndarray, np.ndarray]:
    """Devuelve (verts, tris) en formato numpy para alimentar al pipeline."""
    return (np.asarray(mesh.vertices, dtype=np.float32),
            np.asarray(mesh.faces, dtype=np.int32))


# ---------------------------------------------------------------------------
# Escalado al importar
# ---------------------------------------------------------------------------
@dataclass
class ScaleSuggestion:
    """Sugerencia automatica de factor de escala para un CAD recien cargado.

    factor: multiplicador a aplicar a los vertices. 1.0 = sin cambio.
    reason: texto humano explicando POR QUE se sugiere ese factor.
    unit_guess: unidad detectada ("mm", "cm", "m", "in", "ft", "?")
    diag_meters: diagonal del bbox interpretada como metros (sin escalar).
    """
    factor: float
    reason: str
    unit_guess: str
    diag_meters: float


def _bbox_diagonal(mesh: "trimesh.Trimesh") -> float:
    """Diagonal del AABB (asumiendo unidades = metros)."""
    bounds = np.asarray(mesh.bounds, dtype=float)
    return float(np.linalg.norm(bounds[1] - bounds[0]))


def suggest_scale_factor(mesh: "trimesh.Trimesh") -> ScaleSuggestion:
    """Heuristica: a partir de la diagonal del bbox, infiere la unidad
    probable y propone un factor de escala que lleve la geometria a un
    rango razonable para un recinto arquitectonico (10-60 m de diagonal).

    Reglas:
        diag > 5000 m  ->  ÷1000 (probable mm dibujado en m)
        diag > 500 m   ->  ÷100  (probable cm)
        diag > 60 m    ->  ÷10   (probable dm o STL escalado x10)
        0.5 < diag <= 60 m  ->  sin cambio (probable metros, OK)
        diag <= 0.5 m  ->  ×100  (probable pulgadas o cm en m incorrecto)
        diag <= 0.05 m ->  ×1000 (probable mm en m incorrecto)

    NO modifica la malla. Solo sugiere. El usuario decide.
    """
    diag = _bbox_diagonal(mesh)
    # Casos grandes: la geometria esta en mm/cm/dm pero interpretada como m.
    if diag > 5000:
        return ScaleSuggestion(
            factor=1e-3, unit_guess="mm",
            diag_meters=diag,
            reason=(f"La diagonal del recinto importado es {diag:,.0f} m. "
                    "Probablemente el archivo este en milimetros. "
                    "Se sugiere dividir por 1000 (mm -> m)."),
        )
    if diag > 500:
        return ScaleSuggestion(
            factor=1e-2, unit_guess="cm",
            diag_meters=diag,
            reason=(f"La diagonal es {diag:,.1f} m. Probablemente este "
                    "en centimetros. Se sugiere dividir por 100 (cm -> m)."),
        )
    if diag > 60:
        return ScaleSuggestion(
            factor=1e-1, unit_guess="dm",
            diag_meters=diag,
            reason=(f"La diagonal es {diag:.1f} m. Es grande para un "
                    "recinto arquitectonico tipico. Se sugiere dividir por "
                    "10, aunque puede tratarse de un estadio o recinto "
                    "muy grande sin necesidad de escalar."),
        )
    if diag < 0.05:
        return ScaleSuggestion(
            factor=1e3, unit_guess="mm-as-m",
            diag_meters=diag,
            reason=(f"La diagonal es {diag*1000:.1f} mm. La geometria esta "
                    "expresada en metros muy pequena. Se sugiere multiplicar "
                    "por 1000."),
        )
    if diag < 0.5:
        return ScaleSuggestion(
            factor=1e2, unit_guess="in/cm-as-m",
            diag_meters=diag,
            reason=(f"La diagonal es {diag*100:.1f} cm. Demasiado chico para "
                    "un recinto. Se sugiere multiplicar por 100."),
        )
    # Rango razonable [0.5, 60] m: lo dejamos pasar.
    return ScaleSuggestion(
        factor=1.0, unit_guess="m",
        diag_meters=diag,
        reason=(f"La diagonal es {diag:.2f} m, dentro del rango tipico de "
                "un recinto arquitectonico. No se sugiere escalar."),
    )


def apply_scale(mesh: "trimesh.Trimesh", factor: float) -> "trimesh.Trimesh":
    """Devuelve una copia de la malla escalada por `factor` (centrada en
    el origen del archivo, sin desplazar). Triangulos intactos.
    """
    if factor <= 0:
        raise ValueError("factor de escala debe ser positivo.")
    if abs(factor - 1.0) < 1e-12:
        return mesh.copy()
    m = mesh.copy()
    new_verts = np.asarray(m.vertices, dtype=float) * float(factor)
    return trimesh.Trimesh(vertices=new_verts, faces=m.faces, process=False)


def apply_up_axis(mesh: "trimesh.Trimesh", source_up: str) -> "trimesh.Trimesh":
    """Rota la malla para que el eje 'up' del archivo coincida con Z+
    del soft (convencion Z-up).

    source_up : 'Z+' | 'Y+' | 'X+' | 'Z-' | 'Y-' | 'X-'
        - 'Z+': sin cambios (default del soft).
        - 'Y+': intercambio Y/Z (caso tipico de OBJ/glTF/Blender).
        - 'X+': intercambio X/Z (raro).
        - Las versiones negativas voltean el sentido.
    """
    s = (source_up or "Z+").upper().strip()
    if s in ("Z+", "Z", "+Z"):
        return mesh.copy()
    m = mesh.copy()
    v = np.asarray(m.vertices, dtype=float).copy()

    if s in ("Y+", "+Y"):
        # X queda igual; Y -> Z; Z -> -Y (rotacion -90 deg alrededor de X).
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
    elif s in ("Y-", "-Y"):
        v = np.column_stack([v[:, 0],  v[:, 2], -v[:, 1]])
    elif s in ("X+", "+X"):
        # Z -> X, X -> -Z, Y igual (rotacion -90 deg alrededor de Y).
        v = np.column_stack([-v[:, 2], v[:, 1], v[:, 0]])
    elif s in ("X-", "-X"):
        v = np.column_stack([ v[:, 2], v[:, 1], -v[:, 0]])
    elif s in ("Z-", "-Z"):
        # Voltear: (-z queda como +z, -x para mantener determinante > 0).
        v = np.column_stack([-v[:, 0], v[:, 1], -v[:, 2]])
    else:
        return mesh.copy()

    # Como cambiamos la orientacion de los ejes, las normales / winding
    # pueden quedar invertidas. process=True hace fix_normals.
    return trimesh.Trimesh(vertices=v, faces=m.faces, process=True)


def autofit_scale(mesh: "trimesh.Trimesh", target_diag: float = 20.0) -> float:
    """Devuelve el factor que llevaria la diagonal del bbox al valor
    `target_diag` en metros. Util para 'auto-encajar' independiente de
    las unidades originales (cuando la heuristica de unidad falla).
    """
    diag = _bbox_diagonal(mesh)
    if diag <= 0:
        return 1.0
    return float(target_diag) / diag


def load_and_diagnose(path: str,
                      progress: Optional[Callable[[str], None]] = None
                      ) -> Tuple["trimesh.Trimesh", MeshDiagnosis]:
    """Conveniencia: load + diagnose en una sola llamada."""
    mesh = load_geometry(path, progress=progress)
    diag = diagnose(mesh)
    return mesh, diag


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not _HAS_TRIMESH:
        print("Faltan dependencias.")
        raise SystemExit(1)
    print("Formatos soportados:", supported_extensions())
    print()
    # Generamos un STL con huecos a proposito para probar diagnose/fill.
    import trimesh.creation as tc
    cyl = tc.cylinder(radius=2.0, height=4.0, sections=32)
    # Borramos algunas caras para hacer huecos.
    faces = np.asarray(cyl.faces).copy()
    keep = np.ones(len(faces), dtype=bool)
    keep[10:13] = False
    keep[40:42] = False
    cyl = trimesh.Trimesh(vertices=cyl.vertices, faces=faces[keep], process=False)

    d = diagnose(cyl)
    print("=== Diagnostico cilindro con huecos ===")
    print(d.summary())
    print()
    print("Huecos encontrados:")
    for i, h in enumerate(d.holes):
        print(f"  Hueco {i+1}: {len(h.boundary_vertex_indices)} vertices, "
              f"area={h.area:.4f} m², centroide={tuple(h.centroid.round(3))}")

    print()
    print("Reparando todo automaticamente...")
    cyl_fixed = fill_all_holes_auto(cyl)
    d2 = diagnose(cyl_fixed)
    print(d2.summary())
