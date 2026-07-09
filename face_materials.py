"""face_materials.py
===================

Asignacion de materiales acusticos POR GRUPO DE CARAS (estilo EASE).

A diferencia del esquema clasico piso/techo/paredes, este modulo permite que
el usuario asigne un material distinto a cada region planar del recinto. Esa
region se llama "grupo de caras" y se obtiene automaticamente de la malla
superficial agrupando triangulos por:

  1. Direccion de la normal (clusters con tolerancia angular configurable).
  2. Conectividad: componentes conexas dentro de cada cluster de normal.

Asi un recinto rectangular tiene 6 grupos (piso, techo, 4 paredes).  Un
auditorio importado de CAD genera tantos grupos como caras planares distintas
(escalones, paneles inclinados, plafones, etc.).

API publica
-----------
- FaceGroup                : dataclass con indices de caras, normal dominante,
                              area, etiqueta automatica y firma de geometria.
- group_faces_by_planar_region(verts, tris, normal_tol_deg=15.0)
                              -> List[FaceGroup]
- FaceMaterialMap          : mapeo group_signature -> material_name (persistente).
- compute_sabine_rt60_per_face(V, groups, group_to_material, mat_lib, bands)
                              -> {banda: RT60}
- MaterialsDialog          : QDialog para asignar materiales por grupo, con
                              preview 3D y persistencia entre aperturas.

Persistencia
------------
El mapeo se mantiene en memoria en el panel acustico mientras la app esta
abierta (no se borra al cerrar el dialogo). Se guarda en .room v4 dentro de
`acoustic.face_materials`. La clave es la *firma* del grupo (hash de normal
dominante + area + centroide redondeados), no el indice — asi sobrevive
recompilaciones del agrupador y cambios menores de geometria.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Dataclass de grupo de caras
# ---------------------------------------------------------------------------
@dataclass
class FaceGroup:
    """Un conjunto contiguo de caras coplanares (region planar).

    Atributos:
        face_indices  : np.ndarray (Ng,) indices a `tris` en la malla original.
        normal        : np.ndarray (3,)  normal dominante (promedio ponderado por area).
        area          : float            area total (m^2).
        centroid      : np.ndarray (3,)  centroide ponderado por area (m).
        label         : str              etiqueta auto-generada ("Piso", "Pared N", "Techo 1"...).
        signature     : str              firma estable para persistencia.
        kind          : str              "floor" | "ceiling" | "wall" | "tilted" (categoria heuristica).
    """
    face_indices: np.ndarray
    normal: np.ndarray
    area: float
    centroid: np.ndarray
    label: str
    signature: str
    kind: str = "wall"

    @property
    def n_faces(self) -> int:
        return int(len(self.face_indices))


# ---------------------------------------------------------------------------
# Agrupador
# ---------------------------------------------------------------------------
def _face_normals_and_areas(verts: np.ndarray, tris: np.ndarray
                            ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Devuelve (normals, areas, centroids) por cara.

    normals  : (Nt, 3) unitarias (ceros si la cara es degenerada)
    areas    : (Nt,)
    centroids: (Nt, 3)
    """
    v = verts.astype(float)
    a = v[tris[:, 0]]
    b = v[tris[:, 1]]
    c = v[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    norms = np.linalg.norm(cross, axis=1)
    areas = 0.5 * norms
    safe = np.maximum(norms, 1e-12)
    normals = cross / safe[:, None]
    # Anular normales de caras degeneradas.
    normals[norms < 1e-12] = 0.0
    centroids = (a + b + c) / 3.0
    return normals, areas, centroids


def _build_face_adjacency(tris: np.ndarray) -> List[List[int]]:
    """Adyacencia entre caras: dos caras son adyacentes si comparten una arista.

    Devuelve adj[i] = lista de indices de caras adyacentes a i.
    Vectorizado con np.unique sobre claves enteras (i*N + j).
    """
    Nt = len(tris)
    if Nt == 0:
        return []
    # 3 aristas no orientadas por cara, asociadas al indice de cara.
    e1 = np.sort(tris[:, [0, 1]], axis=1)
    e2 = np.sort(tris[:, [1, 2]], axis=1)
    e3 = np.sort(tris[:, [2, 0]], axis=1)
    edges = np.concatenate([e1, e2, e3], axis=0).astype(np.int64)
    face_of_edge = np.concatenate([
        np.arange(Nt, dtype=np.int64),
        np.arange(Nt, dtype=np.int64),
        np.arange(Nt, dtype=np.int64),
    ])
    # Clave entera por arista no orientada.
    max_v = int(edges.max()) + 1 if len(edges) else 1
    keys = edges[:, 0] * max_v + edges[:, 1]
    # Ordenar por clave para juntar aristas iguales.
    order = np.argsort(keys, kind="stable")
    keys_s = keys[order]
    faces_s = face_of_edge[order]
    # Buscar grupos consecutivos con la misma clave: aristas compartidas.
    adj: List[List[int]] = [[] for _ in range(Nt)]
    i = 0
    n = len(keys_s)
    while i < n:
        j = i + 1
        while j < n and keys_s[j] == keys_s[i]:
            j += 1
        if j - i >= 2:
            # Todas las caras del grupo son mutuamente adyacentes a traves de esta arista.
            group = faces_s[i:j]
            for k_a in range(len(group)):
                fa = int(group[k_a])
                for k_b in range(len(group)):
                    if k_a == k_b:
                        continue
                    adj[fa].append(int(group[k_b]))
        i = j
    return adj


def _connected_components(face_mask: np.ndarray,
                          adj: List[List[int]]) -> List[List[int]]:
    """Componentes conexas dentro del subconjunto `face_mask` (bool, Nt)."""
    Nt = len(face_mask)
    visited = np.zeros(Nt, dtype=bool)
    components: List[List[int]] = []
    for seed in np.where(face_mask)[0]:
        if visited[seed]:
            continue
        # BFS limitado al mask.
        stack = [int(seed)]
        comp: List[int] = []
        visited[seed] = True
        while stack:
            f = stack.pop()
            comp.append(f)
            for nb in adj[f]:
                if not visited[nb] and face_mask[nb]:
                    visited[nb] = True
                    stack.append(nb)
        if comp:
            components.append(comp)
    return components


def _kind_from_normal(n: np.ndarray) -> str:
    """Clasifica la categoria del grupo segun la componente vertical de la normal."""
    nz = float(n[2])
    if nz > 0.85:
        return "ceiling"
    if nz < -0.85:
        return "floor"
    if abs(nz) < 0.15:
        return "wall"
    return "tilted"


def _auto_label(kind: str, normal: np.ndarray, idx_in_kind: int) -> str:
    """Etiqueta legible deterministica."""
    if kind == "floor":
        return "Piso" if idx_in_kind == 0 else f"Piso {idx_in_kind + 1}"
    if kind == "ceiling":
        return "Techo" if idx_in_kind == 0 else f"Techo {idx_in_kind + 1}"
    # Para paredes y caras inclinadas, indicar direccion azimutal aproximada.
    nx, ny = float(normal[0]), float(normal[1])
    az = np.degrees(np.arctan2(ny, nx))  # 0=+X, 90=+Y
    az = (az + 360.0) % 360.0
    # Direccion cardinal aproximada (8 puntos).
    dirs = ["+X (E)", "NE", "+Y (N)", "NW", "-X (W)",
            "SW", "-Y (S)", "SE"]
    sector = int(((az + 22.5) // 45) % 8)
    base = "Pared" if kind == "wall" else "Cara inclinada"
    return f"{base} {idx_in_kind + 1} ({dirs[sector]})"


def _signature(normal: np.ndarray, centroid: np.ndarray, area: float) -> str:
    """Firma estable: normal redondeada a 2 decimales, centroide a 1 cm, area a 0.01 m²."""
    n_round = np.round(normal, 2)
    c_round = np.round(centroid, 2)
    a_round = round(float(area), 2)
    s = f"n={n_round.tolist()}|c={c_round.tolist()}|A={a_round:.2f}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def group_faces_by_planar_region(
    verts: np.ndarray,
    tris: np.ndarray,
    normal_tol_deg: float = 15.0,
    min_area: float = 1e-6,
) -> List[FaceGroup]:
    """Agrupa las caras de la malla en regiones planares contiguas.

    Estrategia:
      1. Calcular normal por cara.
      2. Cluster greedy de normales con tolerancia angular `normal_tol_deg`.
         (cos(ang) >= cos_tol).  Se elige como representante el primer
         triangulo no asignado.
      3. Dentro de cada cluster, hacer componentes conexas (via adyacencia
         por aristas compartidas). Cada componente = un FaceGroup.

    Devuelve los grupos ordenados por categoria (piso, techo, paredes,
    inclinadas) y luego por area descendente.
    """
    verts = np.asarray(verts, dtype=float)
    tris = np.asarray(tris, dtype=int)
    if len(tris) == 0:
        return []

    normals, areas, centroids = _face_normals_and_areas(verts, tris)
    n_valid = np.linalg.norm(normals, axis=1) > 0.5
    cos_tol = float(np.cos(np.radians(normal_tol_deg)))

    # Clustering greedy de normales (acepta cualquier malla, no necesita
    # estimar K de antemano).
    Nt = len(tris)
    cluster_id = np.full(Nt, -1, dtype=int)
    cluster_normals: List[np.ndarray] = []

    # Ordenamos por area descendente para que los clusters representen
    # bien las caras grandes (las paredes principales) antes que las chicas.
    order = np.argsort(-areas)
    for fi in order:
        if not n_valid[fi]:
            continue
        n = normals[fi]
        assigned = False
        for ci, cn in enumerate(cluster_normals):
            if float(np.dot(n, cn)) >= cos_tol:
                cluster_id[fi] = ci
                assigned = True
                break
        if not assigned:
            cluster_normals.append(n.copy())
            cluster_id[fi] = len(cluster_normals) - 1

    # Adyacencia para componentes conexas.
    adj = _build_face_adjacency(tris)

    # Construir grupos: dentro de cada cluster, separar por componentes conexas.
    raw_groups: List[FaceGroup] = []
    for ci in range(len(cluster_normals)):
        mask = (cluster_id == ci)
        if not mask.any():
            continue
        comps = _connected_components(mask, adj)
        for comp in comps:
            comp_arr = np.asarray(comp, dtype=int)
            area_c = float(areas[comp_arr].sum())
            if area_c < min_area:
                continue
            # Normal y centroide ponderados por area.
            w = areas[comp_arr]
            n_mean = (normals[comp_arr] * w[:, None]).sum(axis=0)
            nl = float(np.linalg.norm(n_mean))
            n_mean = n_mean / nl if nl > 1e-12 else cluster_normals[ci]
            c_mean = (centroids[comp_arr] * w[:, None]).sum(axis=0) / max(w.sum(), 1e-12)
            kind = _kind_from_normal(n_mean)
            sig = _signature(n_mean, c_mean, area_c)
            raw_groups.append(FaceGroup(
                face_indices=comp_arr,
                normal=n_mean,
                area=area_c,
                centroid=c_mean,
                label="",      # se asigna abajo
                signature=sig,
                kind=kind,
            ))

    # Ordenar: piso primero, techo, paredes, inclinadas. Dentro de cada
    # categoria, por area descendente.
    kind_order = {"floor": 0, "ceiling": 1, "wall": 2, "tilted": 3}
    raw_groups.sort(key=lambda g: (kind_order[g.kind], -g.area))

    # Etiquetar.
    kind_count: Dict[str, int] = {}
    for g in raw_groups:
        idx_in_kind = kind_count.get(g.kind, 0)
        g.label = _auto_label(g.kind, g.normal, idx_in_kind)
        kind_count[g.kind] = idx_in_kind + 1

    return raw_groups


# ---------------------------------------------------------------------------
# Persistencia del mapeo grupo -> material
# ---------------------------------------------------------------------------
class FaceMaterialMap:
    """Mantiene el mapeo {signature: material_name} entre aperturas del dialogo.

    El mapeo es estable frente a re-agrupaciones porque usa la firma de cada
    grupo (normal+centroide+area redondeados), no el indice. Si un grupo
    desaparece (cambia la geometria), su entrada queda huerfana pero no
    molesta. Cuando un grupo nuevo aparece, no esta en el mapa y toma el
    material default.
    """

    def __init__(self, default_material: str = ""):
        self._map: Dict[str, str] = {}
        self.default = default_material

    def assign(self, signature: str, material_name: str) -> None:
        self._map[signature] = material_name

    def get(self, signature: str) -> str:
        return self._map.get(signature, self.default)

    def to_dict(self) -> Dict[str, str]:
        return dict(self._map)

    def from_dict(self, d: Dict[str, str]) -> None:
        self._map = dict(d or {})

    def __len__(self) -> int:
        return len(self._map)

    def clear(self) -> None:
        self._map.clear()


# ---------------------------------------------------------------------------
# RT60 por banda usando asignacion por grupo
# ---------------------------------------------------------------------------
def _alpha_for(group: FaceGroup,
               group_to_material: Dict[str, "object"],
               f: float,
               default: float = 0.03) -> float:
    mat = group_to_material.get(group.signature)
    if mat is None:
        return default
    return float(mat.alpha(f))


def compute_sabine_rt60_per_face(
    V: float,
    groups: List[FaceGroup],
    group_to_material: Dict[str, "object"],   # signature -> Material
    bands: Optional[List[int]] = None,
) -> Dict[int, float]:
    """RT60 segun **Sabine** (con un material distinto por FaceGroup).

        A(f) = sum_g alpha_g(f) * S_g
        RT60(f) = 0.161 * V / A(f)

    Es la formula clasica. Asume absorcion baja (alpha << 1). Para alpha
    cerca de 1 sobreestima RT60 (no llega a cero en la sala anecoica).
    """
    from material_library import BANDS
    if bands is None:
        bands = BANDS
    rt60: Dict[int, float] = {}
    for f in bands:
        A = sum(_alpha_for(g, group_to_material, f) * g.area for g in groups)
        A = max(A, 1e-6)
        rt60[f] = 0.161 * V / A
    return rt60


def bass_ratio(rt60_bands: Dict[int, float]) -> float:
    """Bass Ratio (BR) de Beranek a partir del RT60 por banda (criterio D5).

        BR = (RT_125 + RT_250) / (RT_500 + RT_1000)

    Mide la **calidez por reverberacion**: cuanto mas largo es el RT en graves
    relativo a los medios. Distinto del soporte/densidad modal (`score_bass` de
    la prediccion mide OTRA cosa). Target tipico (Beranek): ~1.1-1.45 para musica;
    ~1.0-1.1 para palabra. BR<1 = sala "fria"/seca en graves; BR>>1.5 = "boomy".

    Devuelve nan si faltan las bandas necesarias.
    """
    try:
        num = float(rt60_bands[125]) + float(rt60_bands[250])
        den = float(rt60_bands[500]) + float(rt60_bands[1000])
    except (KeyError, TypeError):
        return float("nan")
    if den <= 0:
        return float("nan")
    return num / den


def compute_eyring_rt60_per_face(
    V: float,
    groups: List[FaceGroup],
    group_to_material: Dict[str, "object"],
    bands: Optional[List[int]] = None,
) -> Dict[int, float]:
    """RT60 segun **Norris-Eyring** (estadistica de imagenes).

        alpha_avg(f) = sum_g alpha_g(f) * S_g  /  S_total
        RT60(f) = 0.161 * V / ( -S_total * ln(1 - alpha_avg(f)) )

    Corrige el sesgo de Sabine para absorcion alta: cuando alpha_avg -> 1,
    el termino -ln(1-alpha) tiende a infinito y RT60 -> 0 (sala anecoica),
    que es lo fisicamente correcto. En el limite alpha << 1, -ln(1-alpha) ≈
    alpha y la formula colapsa a Sabine.
    """
    from material_library import BANDS
    if bands is None:
        bands = BANDS
    S_total = sum(g.area for g in groups)
    if S_total <= 0:
        return {f: 0.0 for f in bands}
    rt60: Dict[int, float] = {}
    for f in bands:
        Sa = sum(_alpha_for(g, group_to_material, f) * g.area for g in groups)
        alpha_avg = Sa / S_total
        # Clampear para evitar log(0) si alpha_avg llegara a 1
        alpha_avg = min(max(alpha_avg, 1e-6), 0.999999)
        denom = -S_total * np.log(1.0 - alpha_avg)
        rt60[f] = 0.161 * V / max(denom, 1e-6)
    return rt60


def compute_xi_per_mode_per_face(
    freqs: np.ndarray,
    phis: np.ndarray,
    locator,
    verts: np.ndarray,
    tris: np.ndarray,
    groups: List[FaceGroup],
    group_to_material: Dict[str, "object"],
    V: float,
    default_alpha: float = 0.03,
) -> Optional[np.ndarray]:
    """xi_n por modo PESADO POR LA FORMA MODAL en cada cara (criterio A36).

    A diferencia de `compute_xi_per_mode` (que usa un RT60 GLOBAL por banda,
    igual para todos los modos a una misma frecuencia), aca cada modo ve una
    absorcion efectiva segun **que caras carga su propia forma modal**:

        J_g(n)     = integral_g |phi_n|^2 dA          (presion modal^2 sobre la cara g)
        p_g(n)     = J_g(n) / sum_h J_h(n)            (peso normalizado, sum_g p_g = 1)
        alpha_eff(n) = sum_g alpha_g(f_n) * p_g(n)    (absorcion vista por el modo n)
        T60(n)     = 0.161 * V / (S_total * alpha_eff(n))   (Sabine con alpha del modo)
        xi(n)      = 1.1 / (f_n * T60(n))

    Propiedades:
      - Si los materiales son UNIFORMES (alpha_g = alpha para todas las caras),
        alpha_eff(n) = alpha para todo modo -> se reduce EXACTAMENTE a la Sabine
        global (no regresiona los casos validados con material uniforme).
      - Con tratamiento ASIMETRICO, un modo cuyo antinodo cae sobre una cara
        absorbente se amortigua mas; un modo paralelo a ese tratamiento "suena"
        mas tiempo (xi menor). Es el efecto fisico que B13/A36 piden capturar.

    Nota de alcance: los modos estan M-ortonormalizados (phi^T M phi = 1), por eso
    la energia de volumen es 1 y solo importa la integral de superficie. El peso
    p_g(n) es un COCIENTE de integrales -> robusto a una perdida uniforme de
    evaluacion (puntos fuera de la malla escalonada). NO se modela el efecto de
    "camino libre medio" (axial decae mas que oblicuo con alpha uniforme, H&A fig
    6.38): eso requiere la integral de superficie ABSOLUTA y queda diferido.

    Devuelve xi (Nm,) o None si no hay caras/datos para calcular.
    """
    if phis is None or len(groups) == 0 or locator is None:
        return None
    freqs = np.asarray(freqs, dtype=float)
    Nm = int(phis.shape[1])
    if Nm == 0 or freqs.size < Nm:
        return None

    # Areas y centroides por triangulo (toda la superficie de una vez).
    _, areas_all, centroids_all = _face_normals_and_areas(verts, np.asarray(tris, int))
    Nt = len(areas_all)
    if Nt == 0:
        return None

    # Mapa triangulo -> indice de grupo (-1 si el triangulo no pertenece a ninguno).
    tri_group = np.full(Nt, -1, dtype=int)
    for gi, g in enumerate(groups):
        tri_group[np.asarray(g.face_indices, dtype=int)] = gi
    valid = tri_group >= 0
    if not np.any(valid):
        return None
    cen = centroids_all[valid]
    area_v = areas_all[valid]
    gid = tri_group[valid]
    Ng = len(groups)
    S_total = float(area_v.sum())
    if S_total <= 0 or V <= 0:
        return None

    # J_g(n) = sum_{tri in g} area_tri * |phi_n(centroide_tri)|^2
    J = np.zeros((Nm, Ng), dtype=float)
    for n in range(Nm):
        vals = locator.evaluate_many(phis[:, n], cen)        # complejo (Nt_valid,)
        p2 = np.nan_to_num(np.real(vals)) ** 2 * area_v
        np.add.at(J[n], gid, p2)

    xi = np.empty(Nm, dtype=float)
    for n in range(Nm):
        fn = float(freqs[n])
        Jn = J[n]
        Jtot = float(Jn.sum())
        alpha_g = np.array(
            [_alpha_for(g, group_to_material, fn, default_alpha) for g in groups],
            dtype=float)
        if Jtot > 0:
            alpha_eff = float((alpha_g * (Jn / Jtot)).sum())
        else:
            # Modo sin presion evaluable en frontera: cae a Sabine por area.
            alpha_eff = float((alpha_g * np.array([g.area for g in groups])).sum()
                              / max(sum(g.area for g in groups), 1e-9))
        alpha_eff = max(alpha_eff, 1e-6)
        T60 = 0.161 * V / (S_total * alpha_eff)
        xi[n] = 1.1 / max(fn * T60, 1e-9)
    return xi


# Categorias de la libreria de materiales (material_library / carpeta materials/).
# Porosos/fibrosos operan sobre la VELOCIDAD de particula; perforados/membrana
# sobre la PRESION. Ver criterio B27 de criterios_room_geom_fuente.md.
_POROUS_CATS = {"Porosos", "Alfombras", "Cortinas"}
_RESONANT_CATS = {"Paneles perforados"}


def lf_modal_absorption_hints(
    groups: List[FaceGroup],
    group_to_material: Dict[str, "object"],
    lowest_mode_hz: Optional[float] = None,
    c: float = 343.0,
) -> List[str]:
    """Avisos de colocacion de absorbente para control modal LF (criterio B27).

    El absorbente **poroso/fibroso** (alfombras, lanas, cortinas) opera sobre la
    **velocidad de particula**, que es ~0 SOBRE la pared y en las esquinas -> es
    **ineficaz para graves** montado al ras. Los **paneles perforados/membrana**
    operan sobre la **presion** (maxima en pared/esquina) -> esos si sirven para
    modos. Este chequeo es PURO (sin GUI): devuelve una lista de strings-aviso.

    Dispara UN aviso agregado cuando: hay poroso con alpha bajo en graves cubriendo
    area apreciable Y no hay ningun panel perforado/membrana asignado. No es fisica
    (el solver ya ve alpha(f) ISO 354); es guia para el usuario.
    """
    if not groups:
        return []
    # Gate: solo tiene sentido en regimen modal (modo mas bajo en graves).
    if lowest_mode_hz is not None and lowest_mode_hz > 160.0:
        return []

    f_lf = 80.0 if lowest_mode_hz is None else float(max(lowest_mode_hz, 31.5))
    total_area = sum(g.area for g in groups) or 1.0
    porous_area = 0.0
    resonant_area = 0.0
    worst_alpha = 1.0
    for g in groups:
        mat = group_to_material.get(g.signature)
        if mat is None:
            continue
        cat = getattr(mat, "category", "") or ""
        try:
            a_lf = float(mat.alpha(f_lf))
        except Exception:
            a_lf = 0.0
        if cat in _POROUS_CATS:
            porous_area += g.area
            worst_alpha = min(worst_alpha, a_lf)
        elif cat in _RESONANT_CATS:
            resonant_area += g.area

    hints: List[str] = []
    frac = porous_area / total_area
    if porous_area > 0 and resonant_area == 0 and frac >= 0.15 and worst_alpha < 0.30:
        d_quarter = c / (4.0 * max(f_lf, 1e-3))   # lambda/4 al modo mas bajo
        hints.append(
            f"Control modal de graves: asignaste absorbente poroso/alfombra/cortina "
            f"({porous_area:.0f} m², {frac*100:.0f}% de la superficie) con alpha bajo en "
            f"graves (~{worst_alpha:.2f} @ {f_lf:.0f} Hz). El poroso opera sobre la "
            f"velocidad (≈0 sobre la pared y en esquinas) -> poco efectivo para modos LF. "
            f"Para domar modos usá panel perforado/membrana (resonante, opera sobre presión) "
            f"en las esquinas/máximos de presión, o poroso GRUESO con cámara de aire "
            f"(efectivo a ~λ/4 ≈ {d_quarter:.2f} m respecto de la pared)."
        )
    return hints


def _fitzroy_axis_buckets(groups: List[FaceGroup]) -> Dict[str, List[FaceGroup]]:
    """Asigna cada FaceGroup al eje cardinal segun su componente normal dominante.

    Devuelve {'x': [...], 'y': [...], 'z': [...]} con los grupos en cada bucket.
    Util para Fitzroy, que requiere agrupar paredes por par de paredes opuestas.
    """
    buckets: Dict[str, List[FaceGroup]] = {"x": [], "y": [], "z": []}
    for g in groups:
        nx, ny, nz = abs(g.normal[0]), abs(g.normal[1]), abs(g.normal[2])
        if nz >= nx and nz >= ny:
            buckets["z"].append(g)       # piso + techo
        elif nx >= ny:
            buckets["x"].append(g)       # paredes perpendiculares a X
        else:
            buckets["y"].append(g)       # paredes perpendiculares a Y
    return buckets


def compute_fitzroy_rt60_per_face(
    V: float,
    groups: List[FaceGroup],
    group_to_material: Dict[str, "object"],
    bands: Optional[List[int]] = None,
) -> Dict[int, float]:
    """RT60 segun **Fitzroy** (Knudsen-Harris-Fitzroy, 1959).

    Corrige Eyring cuando la absorcion esta MUY desigualmente distribuida
    (caso tipico: piso o techo muy absorbentes, paredes laterales muy
    reflectivas). Calcula un T60 efectivo por eje cardinal y los combina
    ponderado por el area de los pares de paredes opuestas:

        S_x = area total de las paredes perpendiculares al eje X
        alpha_x(f) = (sum sobre paredes perp. a X) alpha_g(f) * S_g  / S_x
        T_x(f) = 0.161 * V / ( -S_total * ln(1 - alpha_x(f)) )

        idem T_y(f), T_z(f)

        RT60_Fitzroy(f) = (S_x * T_x + S_y * T_y + S_z * T_z) / S_total

    Reduce a Eyring cuando alpha es igual en todas las direcciones.
    """
    from material_library import BANDS
    if bands is None:
        bands = BANDS
    S_total = sum(g.area for g in groups)
    if S_total <= 0:
        return {f: 0.0 for f in bands}
    buckets = _fitzroy_axis_buckets(groups)
    S_axis = {ax: sum(g.area for g in gs) for ax, gs in buckets.items()}

    rt60: Dict[int, float] = {}
    for f in bands:
        # T_axis para cada uno de los 3 ejes cardinales
        T_axis: Dict[str, float] = {}
        for ax in ("x", "y", "z"):
            Sa = sum(_alpha_for(g, group_to_material, f) * g.area
                      for g in buckets[ax])
            S = S_axis[ax]
            if S <= 0:
                T_axis[ax] = 0.0
                continue
            alpha_ax = Sa / S
            alpha_ax = min(max(alpha_ax, 1e-6), 0.999999)
            denom = -S_total * np.log(1.0 - alpha_ax)
            T_axis[ax] = 0.161 * V / max(denom, 1e-6)
        # Combinar ponderado por area de cada par
        rt = sum(S_axis[ax] * T_axis[ax] for ax in ("x", "y", "z")) / S_total
        rt60[f] = rt
    return rt60


# ---------------------------------------------------------------------------
# Conversion RT60 -> RT30 / RT20
# ---------------------------------------------------------------------------
# Para predicciones TEORICAS (Sabine, Eyring, Fitzroy) el decaimiento es
# exponencial puro, asi que T20 = T30 = T60. La diferencia entre T20/T30/T60
# aparece SOLO en mediciones reales de impulsos (Schroeder integration sobre
# un decaimiento no perfectamente exponencial). Por compatibilidad con el
# lenguaje habitual de mediciones, mantenemos los tres "alias" y dejamos al
# usuario decidir como nombrar la curva.

def rt60_to_metric(rt60_bands: Dict[int, float], metric: str = "T60"
                   ) -> Dict[int, float]:
    """Convierte un RT60 teorico al metrico solicitado.

    Como el decaimiento Sabine/Eyring/Fitzroy es exponencial puro, T20 = T30
    = T60 matematicamente. Esta funcion devuelve la copia del dict para que
    el resto del codigo trate los tres casos uniformemente.
    """
    if metric not in ("T20", "T30", "T60"):
        raise ValueError(f"metric debe ser T20/T30/T60, recibido: {metric}")
    return dict(rt60_bands)


# Tabla de metodos disponibles (para construir la UI). El metodo Fitzroy se
# implemento internamente (`compute_fitzroy_rt60_per_face`) pero quedo fuera
# de la UI por pedido del usuario; el codigo se mantiene como referencia,
# se puede re-habilitar agregando una linea aqui.
RT_METHODS = {
    "sabine":  ("Sabine",  compute_sabine_rt60_per_face),
    "eyring":  ("Eyring",  compute_eyring_rt60_per_face),
}

# Unica metrica expuesta. T20 y T30 darian el mismo valor que T60 en una
# prediccion teorica (decaimiento exponencial puro), por lo que el dialogo
# solo muestra T60 para evitar confusion al usuario.
RT_METRICS = ("T60",)


def summarize_zone_areas(groups: List[FaceGroup]) -> Dict[str, float]:
    """Devuelve {kind: area_total} para usar como resumen en el panel."""
    out: Dict[str, float] = {"floor": 0.0, "ceiling": 0.0,
                              "wall": 0.0, "tilted": 0.0}
    for g in groups:
        out[g.kind] = out.get(g.kind, 0.0) + g.area
    return out


# ---------------------------------------------------------------------------
# Dialogo Qt
# ---------------------------------------------------------------------------
try:
    from PyQt5.QtCore import Qt, pyqtSignal, QEvent
    from PyQt5.QtGui import QColor, QBrush
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
        QTableWidget, QTableWidgetItem, QComboBox, QDialogButtonBox,
        QHeaderView, QAbstractItemView, QGroupBox, QFormLayout,
        QDoubleSpinBox, QMessageBox,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


if _HAS_QT:
    # Color deterministico por kind (consistente entre aperturas).
    _KIND_COLORS = {
        "floor":   QColor(120, 200, 130, 220),   # verde
        "ceiling": QColor(140, 170, 230, 220),   # azul
        "wall":    QColor(220, 180, 110, 220),   # ambar
        "tilted":  QColor(200, 130, 200, 220),   # violeta
    }

    class MaterialsDialog(QDialog):
        """Dialogo de asignacion de materiales por grupo de caras.

        Estilo EASE: tabla con una fila por grupo, columnas:
          [color | etiqueta | n caras | area | categoria | material]

        Al cerrar con OK, emite los cambios (lista de (signature, material_name))
        y el panel los aplica al recompute de RT60. Si se cancela, no se
        modifica el FaceMaterialMap del panel.
        """

        applied = pyqtSignal()  # se emite al hacer Apply / OK
        # Hover sobre la fila de un grupo: emite el FaceGroup (o None al salir).
        # El panel lo conecta al resaltado 3D (viewer.set_highlight_faces).
        hovered = pyqtSignal(object)

        def __init__(self,
                     groups: List[FaceGroup],
                     material_library: "MaterialLibrary",
                     face_mat_map: FaceMaterialMap,
                     volume: float = 0.0,
                     parent=None):
            super().__init__(parent)
            self.setWindowTitle("Materiales por cara")
            self.setModal(True)
            self.resize(740, 520)

            self._groups = groups
            self._mat_lib = material_library
            self._map = face_mat_map
            self._volume = float(volume)

            self._build_ui()
            self._populate_table()
            self._refresh_summary()

        # ------------------------------------------------------------------
        # UI
        # ------------------------------------------------------------------
        def _build_ui(self):
            v = QVBoxLayout(self)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(8)

            help_lbl = QLabel(
                "Asigna un material a cada grupo de caras. Los grupos se "
                "detectan automaticamente por orientacion y conectividad. "
                "Las asignaciones se guardan al cerrar el dialogo y se "
                "restauran cuando lo abras de nuevo."
            )
            help_lbl.setWordWrap(True)
            help_lbl.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            v.addWidget(help_lbl)

            # Tabla principal
            self.table = QTableWidget(0, 6, self)
            self.table.setHorizontalHeaderLabels(
                ["", "Grupo", "Caras", "Área (m²)", "Categoría", "Material"]
            )
            self.table.verticalHeader().setVisible(False)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.Fixed)
            hdr.setSectionResizeMode(1, QHeaderView.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(5, QHeaderView.Stretch)
            self.table.setColumnWidth(0, 22)
            # Hover fila -> resaltar el grupo en el render 3D. cellEntered
            # necesita mouse tracking; el filter en el viewport detecta la
            # salida del mouse de la tabla para apagar el resaltado.
            self.table.setMouseTracking(True)
            self.table.cellEntered.connect(self._on_cell_entered)
            self.table.viewport().installEventFilter(self)
            self._hover_row = -1
            v.addWidget(self.table, 1)

            # Resumen
            grp = QGroupBox("Resumen")
            f = QFormLayout(grp)
            self.lbl_zones = QLabel("—")
            self.lbl_zones.setWordWrap(True)
            self.lbl_zones.setStyleSheet("color: #94e2d5; font-size: 9pt;")
            f.addRow("Áreas por categoría:", self.lbl_zones)
            self.lbl_rt = QLabel("—")
            self.lbl_rt.setStyleSheet("color: #94e2d5; font-size: 9pt;")
            f.addRow("RT60 medio (500 Hz):", self.lbl_rt)
            v.addWidget(grp)

            # Acciones rapidas
            qrow = QHBoxLayout()
            self.btn_set_all = QPushButton("Asignar a todos…")
            self.btn_set_all.setToolTip(
                "Asigna el material seleccionado a TODOS los grupos. "
                "Util para empezar de un material base y refinar despues."
            )
            self.btn_set_all.clicked.connect(self._set_all_dialog)
            qrow.addWidget(self.btn_set_all)

            self.btn_zone_preset = QPushButton("Preset piso/techo/paredes…")
            self.btn_zone_preset.setToolTip(
                "Asigna tres materiales (uno para piso, uno para techo, "
                "uno para paredes) replicando el esquema clasico."
            )
            self.btn_zone_preset.clicked.connect(self._zone_preset_dialog)
            qrow.addWidget(self.btn_zone_preset)

            self.btn_named_preset = QPushButton("Preset nombrado…")
            self.btn_named_preset.setToolTip(
                "Aplica un preset CON NOMBRE (Reflectante / Estudio tratado / "
                "Home theatre / Aula / Neutra): asigna piso/paredes/techo con "
                "materiales del catálogo. Mismos presets que el de Predicción."
            )
            self.btn_named_preset.clicked.connect(self._named_preset_dialog)
            qrow.addWidget(self.btn_named_preset)

            self.btn_recompute = QPushButton("Recalcular RT60")
            self.btn_recompute.clicked.connect(self._refresh_summary)
            qrow.addWidget(self.btn_recompute)

            v.addLayout(qrow)

            # OK / Cancel
            bb = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
            )
            bb.accepted.connect(self._on_accept)
            bb.rejected.connect(self.reject)
            bb.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
            v.addWidget(bb)

        # ------------------------------------------------------------------
        # Hover fila -> resaltado 3D
        # ------------------------------------------------------------------
        def _on_cell_entered(self, row, _col):
            if row == self._hover_row:
                return
            self._hover_row = row
            g = self._groups[row] if 0 <= row < len(self._groups) else None
            self.hovered.emit(g)

        def eventFilter(self, obj, ev):
            # El mouse salio de la tabla -> apagar el resaltado.
            if obj is self.table.viewport() and ev.type() == QEvent.Leave:
                self._hover_row = -1
                self.hovered.emit(None)
            return super().eventFilter(obj, ev)

        def done(self, r):
            # Al cerrar (OK/Cancel/X), apagar el resaltado si quedo prendido.
            self._hover_row = -1
            self.hovered.emit(None)
            return super().done(r)

        # ------------------------------------------------------------------
        # Poblar tabla
        # ------------------------------------------------------------------
        def _populate_table(self):
            names = self._mat_lib.names
            self.table.setRowCount(len(self._groups))
            for row, g in enumerate(self._groups):
                # Col 0: chip de color por categoria
                color_item = QTableWidgetItem("")
                color_item.setBackground(QBrush(_KIND_COLORS.get(g.kind,
                                          QColor(180, 180, 180, 220))))
                color_item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(row, 0, color_item)

                # Col 1: etiqueta
                lbl_item = QTableWidgetItem(g.label)
                lbl_item.setToolTip(
                    f"signature: {g.signature}\n"
                    f"normal: ({g.normal[0]:+.2f}, {g.normal[1]:+.2f}, {g.normal[2]:+.2f})\n"
                    f"centroide: ({g.centroid[0]:.2f}, {g.centroid[1]:.2f}, {g.centroid[2]:.2f}) m"
                )
                self.table.setItem(row, 1, lbl_item)

                # Col 2: cantidad de caras
                n_item = QTableWidgetItem(str(g.n_faces))
                n_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 2, n_item)

                # Col 3: area
                a_item = QTableWidgetItem(f"{g.area:.2f}")
                a_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 3, a_item)

                # Col 4: kind humano
                kind_es = {
                    "floor":   "Piso",
                    "ceiling": "Techo",
                    "wall":    "Pared",
                    "tilted":  "Inclinada",
                }.get(g.kind, g.kind)
                k_item = QTableWidgetItem(kind_es)
                k_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 4, k_item)

                # Col 5: combo de material
                combo = QComboBox()
                combo.addItems(names)
                # Restaurar seleccion previa (si la habia en el map)
                prev_name = self._map.get(g.signature) or self._map.default
                idx = combo.findText(prev_name) if prev_name else -1
                combo.setCurrentIndex(max(0, idx))
                # Cambios en combo: aplicar al mapa y refrescar resumen
                combo.currentTextChanged.connect(
                    lambda text, sig=g.signature: self._on_combo_changed(sig, text)
                )
                self.table.setCellWidget(row, 5, combo)

        def _on_combo_changed(self, signature: str, material_name: str):
            self._map.assign(signature, material_name)
            self._refresh_summary()

        # ------------------------------------------------------------------
        # Resumen RT60
        # ------------------------------------------------------------------
        def _refresh_summary(self):
            zones = summarize_zone_areas(self._groups)
            parts = []
            es = {"floor": "Piso", "ceiling": "Techo",
                  "wall": "Paredes", "tilted": "Inclinadas"}
            for k in ("floor", "ceiling", "wall", "tilted"):
                if zones.get(k, 0.0) > 0:
                    parts.append(f"{es[k]}: {zones[k]:.1f} m²")
            self.lbl_zones.setText("   ·   ".join(parts) or "—")

            if self._volume <= 0:
                self.lbl_rt.setText("RT60 — (volumen no calculado)")
                return
            # Materiales por grupo via mat_lib
            try:
                g2m: Dict[str, object] = {}
                names = self._mat_lib.names
                for g in self._groups:
                    name = self._map.get(g.signature) or self._map.default
                    if not name:
                        continue
                    if name in names:
                        g2m[g.signature] = self._mat_lib[names.index(name)]
                rt = compute_sabine_rt60_per_face(self._volume, self._groups, g2m)
                rt500 = rt.get(500, 0.0)
                rt_med = float(np.mean(list(rt.values()))) if rt else 0.0
                self.lbl_rt.setText(
                    f"{rt500:.2f} s @ 500 Hz   ·   "
                    f"medio {rt_med:.2f} s   ·   "
                    f"{len(g2m)}/{len(self._groups)} grupos con material"
                )
            except Exception as e:
                self.lbl_rt.setText(f"(error RT60: {e})")

        # ------------------------------------------------------------------
        # Acciones rapidas
        # ------------------------------------------------------------------
        def _set_all_dialog(self):
            from PyQt5.QtWidgets import QInputDialog
            names = self._mat_lib.names
            cur = self._map.default or (names[0] if names else "")
            name, ok = QInputDialog.getItem(
                self, "Asignar a todos",
                "Material a aplicar a TODOS los grupos:",
                names, names.index(cur) if cur in names else 0, False,
            )
            if not ok:
                return
            for g in self._groups:
                self._map.assign(g.signature, name)
            self._map.default = name
            self._populate_table()
            self._refresh_summary()

        def _zone_preset_dialog(self):
            from PyQt5.QtWidgets import QInputDialog
            names = self._mat_lib.names
            if not names:
                return
            def pick(title: str, prompt: str) -> Optional[str]:
                name, ok = QInputDialog.getItem(
                    self, title, prompt, names, 0, False
                )
                return name if ok else None
            n_floor = pick("Piso", "Material para PISO:")
            if n_floor is None: return
            n_ceil = pick("Techo", "Material para TECHO:")
            if n_ceil is None: return
            n_wall = pick("Paredes", "Material para PAREDES e inclinadas:")
            if n_wall is None: return
            for g in self._groups:
                if g.kind == "floor":
                    self._map.assign(g.signature, n_floor)
                elif g.kind == "ceiling":
                    self._map.assign(g.signature, n_ceil)
                else:
                    self._map.assign(g.signature, n_wall)
            self._populate_table()
            self._refresh_summary()

        def _named_preset_dialog(self):
            """Aplica un preset CON NOMBRE (los mismos de Predicción): resuelve
            sus materiales del catalogo y los asigna por zona (piso/paredes/techo)."""
            import material_library as ml
            from PyQt5.QtWidgets import QInputDialog
            preset_names = ml.preset_names()
            if not preset_names:
                return
            name, ok = QInputDialog.getItem(
                self, "Preset de materiales",
                "Elegí un preset (asigna piso / paredes / techo):",
                preset_names, 0, False)
            if not ok:
                return
            mf, mw, mc = ml.preset_surface_materials(self._mat_lib, name)
            for g in self._groups:
                if g.kind == "floor":
                    self._map.assign(g.signature, mf.name)
                elif g.kind == "ceiling":
                    self._map.assign(g.signature, mc.name)
                else:
                    self._map.assign(g.signature, mw.name)
            self._populate_table()
            self._refresh_summary()

        # ------------------------------------------------------------------
        # Aceptar / aplicar
        # ------------------------------------------------------------------
        def _on_apply(self):
            self.applied.emit()
            self._refresh_summary()

        def _on_accept(self):
            self.applied.emit()
            self.accept()
