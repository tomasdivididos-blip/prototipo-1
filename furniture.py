"""furniture.py — Mobiliario como obstaculo rigido en la malla modal (Fase A).

Un mueble se modela como un AGUJERO en el dominio de aire: se remueven los
tetraedros cuyo centroide cae adentro del mueble. La superficie del agujero
queda como pared rigida GRATIS (condicion de Neumann homogenea = natural en
la forma debil; misma decision D3 que la frontera escalonada). El solver
(`build_KM`, `solve_modes`) NO se toca: recibe un dominio de aire mas chico
y los modos salen corridos por si solos, exacto (no perturbativo).

v1 (Fase A, decisiones D-a/D-b/D-c/D-d confirmadas):
- Primitivas parametricas (caja, cilindro). Import de malla = fase futura.
- RIGIDO puro: sin absorcion todavia (eso es Fase B via FaceGroups + A36).
- Significancia por dimension: > lambda_max/8 (a f_S=159 Hz ~ 0.27 m).
- Resolucion: la malla global (npm del usuario, D4); se AVISA si no resuelve.

Contrato central:
    carve_mesh(nodes, tets, muebles) -> (nodes2, tets2, info)
opera sobre la salida de `build_volume_mesh`, antes de `build_KM`. Con
`muebles=[]` devuelve la malla intacta (regresion bit a bit).

Smoke test: `python furniture.py` (oraculos completos en bench_furniture.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# Velocidad del sonido (para el criterio de significancia). Se importa de
# sources si esta disponible, con fallback al valor estandar del proyecto.
try:
    from sources import C0
except Exception:
    C0 = 343.0


# ---------------------------------------------------------------------------
# Representacion
# ---------------------------------------------------------------------------
@dataclass
class Furniture:
    """Mueble como primitiva rigida.

    kind        : "box" | "cylinder".
    position    : (3,) centro geometrico [m], en coords de sala.
    size        : (3,) dimensiones COMPLETAS (ancho, largo, alto) [m].
                  Para cylinder: (diametro_x, diametro_y=ignorado, altura);
                  el radio se toma de size[0]/2 (seccion circular, eje vertical).
    orientation : yaw del mueble [deg] alrededor de z (solo box; el cilindro
                  circular es invariante).
    pitch       : inclinacion [deg] del box alrededor de su eje local ey (tras
                  el yaw). AFECTA EL CARVE (no es solo visual): un mueble
                  inclinado talla la region inclinada. pitch=0 reduce exacto al
                  caso solo-yaw. El cilindro lo ignora (se apoya vertical).
    roll        : giro [deg] alrededor del eje local ex (el "frente"), aplicado
                  DESPUES del yaw y el pitch (convencion aviacion z-y'-x''):
                  vuelca el mueble de costado. Tambien afecta el carve.
                  roll=0 reduce EXACTO al caso yaw+pitch (compat total con los
                  .room viejos). El cilindro lo ignora, como el pitch.
    parts       : para kind="compound", lista de sub-Furniture (box/cylinder)
                  definidas en el FRAME LOCAL del compound (su position = offset
                  respecto del centro del compound). El compound aplica su propio
                  yaw/pitch a todo el conjunto. contains = union de las partes;
                  asi un preset (silla, escritorio...) se talla/mueve como UNA
                  pieza. Las patas finas simplemente no resuelven en la malla
                  (correcto). None para box/cylinder.
    mesh_verts  : para kind="mesh" (CAD/OBJ importado), vertices (Nv,3) en el
                  FRAME LOCAL del mueble (centrados: local (0,0,0) = position).
                  El carve usa trimesh.contains sobre la malla local, con los
                  puntos del mundo llevados al local por to_local (yaw/pitch).
    mesh_faces  : para kind="mesh", triangulos (Nf,3) indices a mesh_verts.
    label       : nombre para UI / informe de auditoria.
    provenance  : de donde salieron las dimensiones (medida propia, catalogo,
                  archivo importado + licencia). Trazabilidad (R6.6).
    """
    kind: str = "box"
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: Tuple[float, float, float] = (0.5, 0.5, 0.5)
    orientation: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    label: str = "mueble"
    provenance: str = ""
    parts: Optional[list] = None
    mesh_verts: Optional[np.ndarray] = None
    mesh_faces: Optional[np.ndarray] = None

    # ----- geometria -------------------------------------------------------
    def _as_trimesh(self):
        """Trimesh en el FRAME LOCAL a partir de mesh_verts/mesh_faces, o None.
        trimesh es import perezoso (no es dependencia dura del modulo)."""
        if self.mesh_verts is None or self.mesh_faces is None:
            return None
        import trimesh
        return trimesh.Trimesh(vertices=np.asarray(self.mesh_verts, float),
                               faces=np.asarray(self.mesh_faces, int),
                               process=False)

    def volume(self) -> float:
        """Volumen analitico [m^3]. Compound: suma de partes (aprox, ignora
        solapes; suficiente para el criterio de significancia)."""
        if self.kind == "compound" and self.parts:
            return float(sum(p.volume() for p in self.parts))
        if self.kind == "mesh":
            tm = self._as_trimesh()
            if tm is not None and tm.is_watertight:
                return float(abs(tm.volume))
            lo, hi = self.aabb()               # fallback: bbox (malla abierta)
            return float(np.prod(np.maximum(hi - lo, 0.0)))
        sx, sy, sz = self.size
        if self.kind == "cylinder":
            r = sx / 2.0
            return float(np.pi * r * r * sz)
        return float(sx * sy * sz)

    def max_dim(self) -> float:
        if (self.kind == "compound" and self.parts) or self.kind == "mesh":
            lo, hi = self.aabb()
            return float(max(hi - lo))
        return float(max(self.size))

    def _local_axes(self):
        """Ejes locales (ex', ey', ez') del mueble segun yaw -> pitch -> roll.

        FUENTE UNICA DE VERDAD de la orientacion: la usan contains, aabb, to_local
        y el wireframe del visor -> lo dibujado coincide SIEMPRE con lo tallado
        (no pueden desincronizarse porque no hay una segunda copia de esta cuenta).

        Convencion aviacion (Tait-Bryan intrinseco z-y'-x''):
          1. yaw   (orientation) sobre el eje z del MUNDO,
          2. pitch sobre el ey resultante,
          3. roll  sobre el ex resultante (el "frente").
        roll=0 devuelve exactamente los ejes de yaw+pitch (compat total).
        """
        th = np.radians(float(self.orientation or 0.0))
        ph = np.radians(float(getattr(self, "pitch", 0.0) or 0.0))
        c, s = np.cos(th), np.sin(th)
        cp, sp = np.cos(ph), np.sin(ph)
        ex = np.array([cp * c, cp * s, sp])
        ey = np.array([-s, c, 0.0])
        ez = np.array([-sp * c, -sp * s, cp])
        rl = np.radians(float(getattr(self, "roll", 0.0) or 0.0))
        if rl:                       # roll=0 -> se saltea: reduccion EXACTA
            cr, sr = np.cos(rl), np.sin(rl)
            ey, ez = cr * ey + sr * ez, -sr * ey + cr * ez
        return ex, ey, ez

    def to_local(self, world_pts: np.ndarray) -> np.ndarray:
        """Expresa puntos del mundo en el frame LOCAL del mueble (para compound)."""
        q = np.asarray(world_pts, dtype=float) - np.asarray(self.position, float)
        ex, ey, ez = self._local_axes()
        return np.stack([q @ ex, q @ ey, q @ ez], axis=1)

    def contains(self, points: np.ndarray) -> np.ndarray:
        """Mascara (N,) bool: que puntos caen adentro del mueble.

        points : (N, 3).
        """
        # Compound: union de las partes, evaluadas en el frame local del compound.
        if self.kind == "compound" and self.parts:
            local = self.to_local(points)
            mask = np.zeros(len(local), dtype=bool)
            for part in self.parts:
                mask |= part.contains(local)
            return mask
        # Mesh (CAD/OBJ): puntos del mundo al frame local, test punto-adentro por
        # trimesh (ray-parity / winding). Confiable si la malla es watertight.
        if self.kind == "mesh":
            pts = np.atleast_2d(np.asarray(points, dtype=float))
            tm = self._as_trimesh()
            if tm is None:
                return np.zeros(len(pts), dtype=bool)
            return np.asarray(tm.contains(self.to_local(pts)), dtype=bool)
        p = np.asarray(points, dtype=float) - np.asarray(self.position, float)
        sx, sy, sz = self.size
        if self.kind == "cylinder":
            r = sx / 2.0
            return ((p[:, 0] ** 2 + p[:, 1] ** 2 <= r * r)
                    & (np.abs(p[:, 2]) <= sz / 2.0))
        # box con yaw+pitch+roll: proyectar el punto sobre los ejes locales.
        # Se DELEGA en _local_axes (fuente unica) en vez de repetir la cuenta:
        # asi el tallado no puede divergir del dibujo ni de la colision.
        ex, ey, ez = self._local_axes()
        xl, yl, zl = p @ ex, p @ ey, p @ ez
        return ((np.abs(xl) <= sx / 2.0)
                & (np.abs(yl) <= sy / 2.0)
                & (np.abs(zl) <= sz / 2.0))

    def aabb(self):
        """Bounding box (min, max) en coords MUNDO. Caja/cilindro: envolvente de
        las 8 esquinas rotadas por yaw+pitch. Compound: envolvente de las esquinas
        de todas las partes transformadas por el frame del compound."""
        ex, ey, ez = self._local_axes()
        c0 = np.asarray(self.position, dtype=float)
        pts = []
        if self.kind == "mesh":
            if self.mesh_verts is None:
                return c0.copy(), c0.copy()
            # Directo desde mesh_verts (sin construir trimesh): esto corre por
            # frame en el drag (colision), conviene que sea barato.
            M = np.stack([ex, ey, ez])                 # (3,3): filas ex,ey,ez
            world = c0 + np.asarray(self.mesh_verts, float) @ M   # local -> mundo
            return world.min(axis=0), world.max(axis=0)
        if self.kind == "compound" and self.parts:
            for part in self.parts:
                px, py, pz = part.position
                sx, sy, sz = part.size
                hx = sx / 2.0
                hy = (sx / 2.0 if part.kind == "cylinder" else sy / 2.0)
                hz = sz / 2.0
                for a in (px - hx, px + hx):
                    for b in (py - hy, py + hy):
                        for d in (pz - hz, pz + hz):
                            pts.append(c0 + a * ex + b * ey + d * ez)
        else:
            sx, sy, sz = self.size
            hx = sx / 2.0
            hy = (sx / 2.0 if self.kind == "cylinder" else sy / 2.0)
            hz = sz / 2.0
            for a in (-hx, hx):
                for b in (-hy, hy):
                    for d in (-hz, hz):
                        pts.append(c0 + a * ex + b * ey + d * ez)
        pts = np.asarray(pts)
        return pts.min(axis=0), pts.max(axis=0)

    # ----- persistencia (.room v7) -----------------------------------------
    def to_dict(self) -> dict:
        d = {"kind": self.kind, "position": list(self.position),
             "size": list(self.size), "orientation": self.orientation,
             "pitch": self.pitch, "roll": self.roll,
             "label": self.label, "provenance": self.provenance}
        if self.kind == "compound" and self.parts:
            d["parts"] = [p.to_dict() for p in self.parts]
        if self.kind == "mesh" and self.mesh_verts is not None:
            # Redondeo a 0.1 mm: recorta el JSON sin efecto sobre el carve (la
            # malla FEM es mucho mas gruesa). La decimacion (para escaneos con
            # decenas de miles de caras) la hace el loader, no la persistencia.
            d["mesh_verts"] = np.asarray(self.mesh_verts, float).round(4).tolist()
            d["mesh_faces"] = np.asarray(self.mesh_faces, int).tolist()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Furniture":
        parts = d.get("parts")
        parts = [cls.from_dict(pp) for pp in parts] if parts else None
        mv, mf = d.get("mesh_verts"), d.get("mesh_faces")
        return cls(kind=str(d.get("kind", "box")),
                   position=tuple(d.get("position", (0, 0, 0))),
                   size=tuple(d.get("size", (0.5, 0.5, 0.5))),
                   orientation=float(d.get("orientation", 0.0)),
                   pitch=float(d.get("pitch", 0.0)),
                   roll=float(d.get("roll", 0.0)),   # aditivo: .room viejo -> 0
                   label=str(d.get("label", "mueble")),
                   provenance=str(d.get("provenance", "")),
                   parts=parts,
                   mesh_verts=(np.asarray(mv, float) if mv is not None else None),
                   mesh_faces=(np.asarray(mf, int) if mf is not None else None))


# ---------------------------------------------------------------------------
# Significancia acustica (R1.5 / D-c)
# ---------------------------------------------------------------------------
def significance_threshold(f_valid: float, c: float = C0) -> float:
    """Dimension minima [m] para que un mueble sea acusticamente relevante en
    la banda valida: lambda_max/8 = c/(8 f_valid). A f_S=159 Hz -> ~0.27 m."""
    return c / (8.0 * max(f_valid, 1.0))


def is_significant(furn: Furniture, f_valid: float, c: float = C0) -> bool:
    return furn.max_dim() >= significance_threshold(f_valid, c)


# ---------------------------------------------------------------------------
# Import CAD: OBJ (o cualquier formato que trimesh entienda) -> Furniture mesh
# ---------------------------------------------------------------------------
def load_furniture_mesh(path: str, label: Optional[str] = None,
                        max_faces: Optional[int] = None
                        ) -> Tuple[Furniture, List[str]]:
    """Carga un archivo CAD como mueble kind="mesh".

    Caso de uso (tesis): escanear el estudio con el celular -> SketchUp ->
    exportar cada pieza como OBJ -> importar aca. El carve usa trimesh.contains,
    que es CONFIABLE con malla WATERTIGHT (superficie cerrada). Un escaneo real
    suele venir abierto: se intenta reparar (merge + fill_holes + fix_normals) y
    se AVISA si sigue abierto (contains puede errar en las zonas sin tapar).

    La malla se guarda CENTRADA en el frame local (local (0,0,0) = position del
    mueble), de modo que world = position + R(yaw,pitch) @ local (reconstruccion
    exacta con yaw=pitch=0). `size` se setea al bbox para info/UI.

    Devuelve (Furniture, warnings). max_faces (opcional) decima escaneos pesados.
    """
    import os
    import trimesh
    warnings: List[str] = []
    # process=False: NO weldea vertices al cargar. Un modelo multi-cuerpo (p.ej.
    # una silla = asiento + respaldo + patas que se tocan) queda watertight por
    # cuerpo; weldear las junturas lo volveria non-manifold. La reparacion se
    # aplica SOLO si la malla no es watertight (tipico de un escaneo real).
    tm = trimesh.load(path, force="mesh", process=False)
    if tm is None or len(getattr(tm, "faces", [])) == 0:
        raise ValueError(f"no se pudo leer una malla de {path}")

    if not tm.is_watertight:
        try:
            tm.merge_vertices()                     # une vertices duplicados
        except Exception:
            pass
        if not tm.is_watertight:                    # aun abierta: tapar huecos
            try:
                trimesh.repair.fill_holes(tm)
                trimesh.repair.fix_normals(tm)
            except Exception:
                pass
        if not tm.is_watertight:
            warnings.append(
                "malla no watertight tras reparar: el carve (punto-adentro) "
                "puede fallar en zonas abiertas. Cerra los huecos en el CAD.")

    if max_faces and len(tm.faces) > int(max_faces):
        try:
            tm = tm.simplify_quadric_decimation(int(max_faces))
            warnings.append(f"decimada a ~{len(tm.faces)} caras")
        except Exception:
            warnings.append("no se pudo decimar (sigue con la malla completa)")

    center = tm.bounds.mean(axis=0)                    # centro del bbox
    verts_local = np.asarray(tm.vertices, float) - center
    name = label or os.path.splitext(os.path.basename(path))[0]
    furn = Furniture(
        kind="mesh", position=tuple(float(c) for c in center),
        size=tuple(float(e) for e in tm.extents),
        mesh_verts=verts_local, mesh_faces=np.asarray(tm.faces, int),
        label=name, provenance=f"CAD import: {os.path.basename(path)}")
    return furn, warnings


# ---------------------------------------------------------------------------
# Ocupacion combinada
# ---------------------------------------------------------------------------
def occupancy(points: np.ndarray, muebles: List[Furniture]) -> np.ndarray:
    """Mascara (N,) bool: puntos adentro de ALGUN mueble (union)."""
    points = np.asarray(points, dtype=float)
    occ = np.zeros(len(points), dtype=bool)
    for m in muebles:
        occ |= m.contains(points)
    return occ


# ---------------------------------------------------------------------------
# Volumenes de tetraedros
# ---------------------------------------------------------------------------
def tet_volumes(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """Volumen (Ne,) de cada tet: |det(v1-v0, v2-v0, v3-v0)| / 6."""
    v = nodes[tets]                       # (Ne, 4, 3)
    a = v[:, 1] - v[:, 0]
    b = v[:, 2] - v[:, 0]
    c = v[:, 3] - v[:, 0]
    return np.abs(np.einsum("ei,ei->e", a, np.cross(b, c))) / 6.0


# ---------------------------------------------------------------------------
# Talla de la malla (el corazon de la Fase A)
# ---------------------------------------------------------------------------
def carve_mesh(nodes: np.ndarray, tets: np.ndarray,
               muebles: List[Furniture]
               ) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """Remueve del dominio de aire los tets ocupados por muebles.

    Pasos:
      1. Marca los tets cuyo CENTROIDE cae adentro de algun mueble.
      2. Los quita de la lista (el aire de ahi deja de existir; su frontera
         queda rigida por Neumann natural, sin ensamblar nada).
      3. PODA nodos huerfanos (los que quedan adentro del mueble, sin tet que
         los use) y REINDEXA -> evita filas de ceros en K,M (M singular).

    Devuelve (nodes2, tets2, info). Con muebles=[] devuelve la malla intacta.
    info trae el material de auditoria (R2.2 / R6.7): volumen removido de la
    malla vs volumen geometrico de los muebles, conteos, y advertencias.
    """
    nodes = np.asarray(nodes, dtype=float)
    tets = np.asarray(tets, dtype=int)
    if not muebles or len(tets) == 0:
        return nodes, tets, {
            "n_tets_removed": 0, "n_nodes_pruned": 0,
            "V_removed_mesh": 0.0, "V_furniture_geom": 0.0,
            "V_error_frac": 0.0, "warnings": [],
        }

    centroids = nodes[tets].mean(axis=1)          # (Ne, 3)
    occ = occupancy(centroids, muebles)           # (Ne,)
    vols = tet_volumes(nodes, tets)
    V_removed = float(vols[occ].sum())
    V_geom = float(sum(m.volume() for m in muebles))

    keep = ~occ
    tets_kept = tets[keep]

    # Poda de huerfanos + reindexado.
    used = np.unique(tets_kept)
    remap = -np.ones(len(nodes), dtype=int)
    remap[used] = np.arange(len(used))
    nodes2 = nodes[used]
    tets2 = remap[tets_kept]

    warnings: List[str] = []
    if V_geom > 0:
        err = abs(V_removed - V_geom) / V_geom
        if err > 0.05:
            warnings.append(
                f"volumen mallado difiere {err*100:.0f}% del geometrico "
                f"(malla gruesa para el mueble; subir npm)")
    else:
        err = 0.0
    if V_removed == 0.0:
        warnings.append("ningun tet removido: mueble mas chico que la malla "
                        "(no resuelto) o fuera del dominio")

    info = {
        "n_tets_removed": int(occ.sum()),
        "n_nodes_pruned": int(len(nodes) - len(used)),
        "V_removed_mesh": V_removed,
        "V_furniture_geom": V_geom,
        "V_error_frac": float(err),
        "warnings": warnings,
    }
    return nodes2, tets2, info


# ---------------------------------------------------------------------------
# Fase B: absorcion del mueble (caras del agujero -> FaceGroups -> A36)
# ---------------------------------------------------------------------------
# Caras locales de un tetraedro (indices a sus 4 vertices).
_TET_FACES = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])


def _tri_areas(nodes: np.ndarray, tris: np.ndarray) -> np.ndarray:
    v = nodes[tris]                                    # (Nk, 3, 3)
    return 0.5 * np.linalg.norm(
        np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)


def furniture_boundary_faces(nodes: np.ndarray, tets: np.ndarray,
                             muebles: List[Furniture]
                             ) -> Dict[int, Tuple[np.ndarray, float]]:
    """Triangulos de la interfaz AIRE-MUEBLE (la frontera del agujero).

    La superficie de un mueble = las caras compartidas por un tet REMOVIDO
    (adentro del mueble) y uno CONSERVADO (aire). El fondo apoyado en el piso
    NO cuenta (no hay aire debajo), asi que sale la superficie EXPUESTA real.

    Devuelve {indice_mueble: (tris (Nk,3) indices a `nodes`, area_total)}.
    """
    nodes = np.asarray(nodes, dtype=float)
    tets = np.asarray(tets, dtype=int)
    if not muebles or len(tets) == 0:
        return {}
    centroids = nodes[tets].mean(axis=1)               # (Ne, 3)
    occ = occupancy(centroids, muebles)                # (Ne,) removido
    # A que mueble pertenece cada tet removido (el primero que lo contiene).
    furn_of_tet = np.full(len(tets), -1, dtype=int)
    for fi, m in enumerate(muebles):
        ins = m.contains(centroids)
        furn_of_tet[ins & (furn_of_tet < 0)] = fi

    faces = tets[:, _TET_FACES].reshape(-1, 3)         # (4Ne, 3)
    tet_id = np.repeat(np.arange(len(tets)), 4)
    key = np.sort(faces, axis=1)
    order = np.lexsort(key.T[::-1])
    ks = key[order]; ti = tet_id[order]; fo = faces[order]
    # Caras internas = par consecutivo con la misma clave (malla tet manifold).
    same = np.where(np.all(ks[1:] == ks[:-1], axis=1))[0]
    ta, tb = ti[same], ti[same + 1]
    iface = occ[ta] != occ[tb]                         # kept-vs-removed
    same = same[iface]; ta = ta[iface]; tb = tb[iface]
    removed = np.where(occ[ta], ta, tb)                # el tet removido del par
    fid = furn_of_tet[removed]
    tris_if = fo[same]                                 # (Nk, 3) verts a nodes

    out: Dict[int, Tuple[np.ndarray, float]] = {}
    for fi in np.unique(fid[fid >= 0]):
        tl = tris_if[fid == fi]
        out[int(fi)] = (tl, float(_tri_areas(nodes, tl).sum()))
    return out


def augment_surface_with_furniture(
        verts: np.ndarray, tris: np.ndarray, groups: list, g2m: dict,
        nodes: np.ndarray, tets: np.ndarray, muebles: List[Furniture],
        mat_by_furn: Dict[int, object]):
    """Agrega las caras de los muebles al (verts, tris, groups, g2m) de la sala,
    listos para `face_materials.compute_xi_per_mode_per_face`.

    - verts/tris : malla de SUPERFICIE de la sala (indices de room groups).
    - nodes/tets : malla de VOLUMEN tallada (de donde salen las caras del mueble).
    - mat_by_furn: {indice_mueble: Material | None(rigido)}.

    Las caras del mueble se concatenan; sus FaceGroups apuntan al tris ampliado
    y su material entra al g2m con signature "__furniture_i__". Asi el A36 pesa
    la absorcion del mueble por la presion modal sobre EL, junto a las paredes.
    """
    from face_materials import FaceGroup
    bf = furniture_boundary_faces(nodes, tets, muebles)
    if not bf:
        return verts, tris, list(groups), dict(g2m)

    verts2 = np.vstack([verts, nodes])
    voff = len(verts)
    tris_blocks = [np.asarray(tris, dtype=int)]
    groups2 = list(groups)
    g2m2 = dict(g2m)
    cursor = len(tris)
    for fi, (tl, area) in bf.items():
        tl_g = tl + voff                               # verts -> verts2
        tris_blocks.append(tl_g)
        face_idx = np.arange(cursor, cursor + len(tl_g))
        cursor += len(tl_g)
        m = muebles[fi]
        sig = f"__furniture_{fi}__"
        cen = nodes[tl].reshape(-1, 3).mean(axis=0)
        groups2.append(FaceGroup(
            face_indices=face_idx, normal=np.array([0.0, 0.0, 1.0]),
            area=float(area), centroid=cen, label=m.label,
            signature=sig, kind="furniture"))
        mat = mat_by_furn.get(fi)
        if mat is not None:
            g2m2[sig] = mat
    tris2 = np.vstack(tris_blocks)
    return verts2, tris2, groups2, g2m2


# ---------------------------------------------------------------------------
# Canal SBIR del mueble (reflexion con rolloff de panel finito)
# ---------------------------------------------------------------------------
def furniture_walls(muebles: List[Furniture], mat_by_furn: Dict[int, object],
                    freq: np.ndarray, default_alpha: float = 0.10) -> list:
    """Superficies reflectantes de los muebles para el SBIR, con tamano FINITO.

    Modela la cara SUPERIOR de cada mueble (la que rebota el sonido entre
    parlante y oyente: el sobre del escritorio, el respaldo del sofa) como un
    panel finito: `sbir.Wall(point=tope, normal=+z, R=sqrt(1-alpha), area=huella)`.
    El `area` activa el rolloff de Rindel (reflexion LF atenuada por difraccion).

    freq : (Nf,) eje para muestrear R(f) del material.
    """
    import sbir
    freq = np.asarray(freq, float)
    walls = []
    for fi, m in enumerate(muebles):
        if getattr(m, "kind", "box") in ("compound", "mesh"):
            # tope y huella desde el bounding box (el 'size' del compound/mesh es
            # el default; la cara superior real la da el AABB).
            lo, hi = m.aabb()
            cx, cy = float((lo[0] + hi[0]) / 2.0), float((lo[1] + hi[1]) / 2.0)
            top_z = float(hi[2])
            area = float((hi[0] - lo[0]) * (hi[1] - lo[1]))
        else:
            cx, cy, cz = m.position
            sx, sy, sz = m.size
            top_z = cz + sz / 2.0
            area = (np.pi * (sx / 2.0) ** 2 if m.kind == "cylinder" else sx * sy)
        mat = mat_by_furn.get(fi)
        if mat is not None:
            alpha = np.array([mat.alpha(float(ff)) for ff in freq])
        else:
            alpha = np.full(freq.shape, default_alpha)
        walls.append(sbir.Wall(
            point=[cx, cy, top_z], normal=[0.0, 0.0, 1.0],
            label=f"{m.label} (tope)",
            R=sbir.reflection_from_alpha(alpha), area=float(area)))
    return walls


# ---------------------------------------------------------------------------
# Espina de Fase C: componer malla + talla + solve + absorcion en una llamada
# ---------------------------------------------------------------------------
def solve_modal_with_furniture(surface_verts, surface_tris, muebles, *,
                               n_modes: int = 30, n_per_meter: float = 4.0):
    """Malla -> talla muebles -> K,M -> modos -> locator, en un solo paso.

    Es lo que la UI (Fase C) y `.room` v7 invocan: encapsula que la talla va
    ENTRE build_volume_mesh y build_KM. Guarda la malla ORIGINAL (nodes0/tets0)
    porque la absorcion del mueble la necesita (la frontera se extrae de ahi).

    Devuelve un dict autocontenido (no toca ModalSolution ni la API estable).
    """
    import acoustic_mesh
    import acoustic_fem
    nodes0, tets0 = acoustic_mesh.build_volume_mesh(
        surface_verts, surface_tris, n_per_meter=n_per_meter)
    nodes, tets, carve = carve_mesh(nodes0, tets0, muebles)
    info = acoustic_mesh.mesh_info(nodes, tets)
    K, M, _ = acoustic_fem.build_KM(nodes, tets)
    freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=n_modes)
    loc = acoustic_fem.FieldEvaluator(nodes, tets)
    return {"freqs": freqs, "phis": phis, "nodes": nodes, "tets": tets,
            "nodes0": nodes0, "tets0": tets0, "locator": loc,
            "carve_info": carve, "mesh_info": info}


def furniture_xi(sol: dict, surface_verts, surface_tris, room_groups,
                 g2m_room: dict, muebles: List[Furniture],
                 mat_by_furn: Dict[int, object], V_air: float):
    """xi por modo con la absorcion del mueble incluida (A36).

    `sol` = salida de solve_modal_with_furniture. Compone la ampliacion de la
    superficie con las caras del mueble y llama al mismo A36 de las paredes.
    Devuelve xi (Nm,) o None si no hay datos.
    """
    import face_materials as fm
    va, ta, ga, g2a = augment_surface_with_furniture(
        surface_verts, surface_tris, room_groups, g2m_room,
        sol["nodes0"], sol["tets0"], muebles, mat_by_furn)
    return fm.compute_xi_per_mode_per_face(
        sol["freqs"], sol["phis"], sol["locator"], va, ta, ga, g2a, V_air)


# ---------------------------------------------------------------------------
# Presets de muebles (compound: forma coarse reconocible, tallado por union)
# ---------------------------------------------------------------------------
# Cada parte se define en el FRAME LOCAL del compound: position = offset desde el
# centro del bounding box; z local 0 = centro en altura. El panel ubica el
# compound apoyandolo en el piso (position.z = piso - aabb_local.min_z). Las
# dimensiones siguen la tabla acordada con el usuario. Materiales = sugerencia
# (si el nombre no esta en el catalogo, el mueble queda rigido, fallback seguro).

def _fb(ox, oy, oz, sx, sy, sz):
    return Furniture("box", position=(ox, oy, oz), size=(sx, sy, sz))


def _fc(ox, oy, oz, diam, h):
    return Furniture("cylinder", position=(ox, oy, oz), size=(diam, diam, h))


def _silla():
    p = [_fb(0.0, 0.0, -0.03, 0.45, 0.45, 0.06),      # asiento
         _fb(0.0, -0.20, 0.20, 0.45, 0.05, 0.45)]     # respaldo
    for sx in (-0.19, 0.19):
        for sy in (-0.19, 0.19):
            p.append(_fb(sx, sy, -0.24, 0.04, 0.04, 0.42))   # 4 patas
    return Furniture("compound", parts=p, label="Silla"), "Madera"


def _sillon():
    p = [_fb(0.0, 0.05, -0.12, 0.85, 0.72, 0.42),     # cuerpo/asiento
         _fb(0.0, -0.35, 0.12, 0.85, 0.15, 0.55),     # respaldo
         _fb(-0.35, 0.05, 0.05, 0.15, 0.72, 0.45),    # apoyabrazos izq
         _fb(0.35, 0.05, 0.05, 0.15, 0.72, 0.45)]     # apoyabrazos der
    return Furniture("compound", parts=p, label="Sillón"), "Asientos tapizados"


def _escritorio():
    p = [_fb(0.0, 0.0, 0.345, 1.40, 0.70, 0.05)]      # tapa (refleja, SBIR)
    for sx in (-0.65, 0.65):
        for sy in (-0.30, 0.30):
            p.append(_fb(sx, sy, -0.02, 0.06, 0.06, 0.70))   # 4 patas
    return Furniture("compound", parts=p, label="Escritorio"), "Madera"


def _mesa():
    p = [_fb(0.0, 0.0, 0.345, 1.20, 0.80, 0.05)]      # tapa
    for sx in (-0.55, 0.55):
        for sy in (-0.35, 0.35):
            p.append(_fb(sx, sy, -0.02, 0.06, 0.06, 0.70))
    return Furniture("compound", parts=p, label="Mesa"), "Madera"


def _banqueta():
    p = [_fc(0.0, 0.0, 0.27, 0.35, 0.06)]             # asiento (disco)
    for sx in (-0.13, 0.13):
        for sy in (-0.13, 0.13):
            p.append(_fb(sx, sy, -0.03, 0.03, 0.03, 0.54))
    return Furniture("compound", parts=p, label="Banqueta"), "Madera"


def _velador():
    p = [_fc(0.0, 0.0, -0.72, 0.30, 0.06),            # base
         _fc(0.0, 0.0, 0.0, 0.04, 1.35),              # caño
         _fc(0.0, 0.0, 0.60, 0.30, 0.30)]             # pantalla
    return Furniture("compound", parts=p, label="Velador de piso"), None


def _biblioteca():
    p = [_fb(0.0, -0.13, 0.0, 0.90, 0.04, 1.80),      # panel trasero
         _fb(-0.43, 0.0, 0.0, 0.04, 0.30, 1.80),      # lateral izq
         _fb(0.43, 0.0, 0.0, 0.04, 0.30, 1.80)]       # lateral der
    for z in (-0.89, -0.45, 0.0, 0.45, 0.89):         # estantes
        p.append(_fb(0.0, 0.0, z, 0.86, 0.28, 0.03))
    return Furniture("compound", parts=p, label="Biblioteca"), "Madera"


def _legs(w2, d2, zc, h, t=0.05):
    return [_fb(sx, sy, zc, t, t, h) for sx in (-w2, w2) for sy in (-d2, d2)]


# --- Aula ---
def _pupitre():
    p = [_fb(0, 0, 0.355, 0.60, 0.50, 0.04)] + _legs(0.26, 0.21, -0.02, 0.70, 0.04)
    p.append(_fb(0, 0.0, 0.12, 0.55, 0.45, 0.03))     # bandeja bajo la tapa
    return Furniture("compound", parts=p, label="Pupitre"), "Madera"


def _silla_escolar():
    p = [_fb(0, 0, -0.05, 0.40, 0.42, 0.05),
         _fb(0, -0.18, 0.22, 0.40, 0.04, 0.40)] + _legs(0.17, 0.17, -0.22, 0.40, 0.035)
    return Furniture("compound", parts=p, label="Silla escolar"), "Madera"


def _escritorio_docente():
    p = [_fb(0, 0, 0.345, 1.40, 0.70, 0.05),
         _fb(0, -0.30, 0.0, 1.30, 0.03, 0.55)] + _legs(0.65, 0.30, -0.02, 0.70, 0.06)
    return Furniture("compound", parts=p, label="Escritorio docente"), "Madera"


def _mesa_grupal():
    p = [_fb(0, 0, 0.345, 1.80, 1.20, 0.05)] + _legs(0.85, 0.55, -0.02, 0.70, 0.07)
    return Furniture("compound", parts=p, label="Mesa grupal"), "Madera"


def _pizarron():
    p = [_fb(0, 0, 0.45, 1.80, 0.05, 0.90),           # tablero (refleja)
         _fb(-0.78, 0, -0.35, 0.05, 0.05, 0.70),      # parantes
         _fb(0.78, 0, -0.35, 0.05, 0.05, 0.70),
         _fb(0, 0, -0.87, 1.55, 0.45, 0.05)]          # base con ruedas
    return (Furniture("compound", parts=p, label="Pizarrón"),
            "Panel de contrachapado, 1 cm de espesor")


def _armario():
    p = [_fb(0, 0, 0.03, 0.90, 0.45, 1.75),           # cuerpo cerrado
         _fb(0, 0.235, 0.03, 0.90, 0.02, 1.60),       # frente/puertas
         _fb(0, 0, -0.88, 0.90, 0.45, 0.10)]          # zócalo
    return Furniture("compound", parts=p, label="Armario"), "Madera"


def _estanteria():
    p = [_fb(0.0, -0.13, 0.0, 0.90, 0.04, 1.80),
         _fb(-0.43, 0.0, 0.0, 0.04, 0.30, 1.80),
         _fb(0.43, 0.0, 0.0, 0.04, 0.30, 1.80)]
    for z in (-0.89, -0.45, 0.0, 0.45, 0.89):
        p.append(_fb(0.0, 0.0, z, 0.86, 0.28, 0.03))
    return Furniture("compound", parts=p, label="Estantería abierta"), "Madera"


def _casilleros():
    p = [_fb(0, 0, 0, 1.05, 0.45, 1.80)]              # bloque metálico cerrado
    for x in (-0.35, 0.0, 0.35):                      # divisiones de módulos (frente)
        p.append(_fb(x, 0.23, 0, 0.02, 0.02, 1.75))
    for z in (-0.6, 0.0, 0.6):
        p.append(_fb(0, 0.23, z, 1.0, 0.02, 0.02))
    return Furniture("compound", parts=p, label="Casilleros"), None   # metal = rígido


def _carrito():
    p = [_fb(0, 0, 0.05, 0.70, 0.50, 0.80)]           # cuerpo con bandejas
    for z in (-0.25, 0.05, 0.30):
        p.append(_fb(0, 0.24, z, 0.68, 0.02, 0.02))
    for sx in (-0.30, 0.30):                          # ruedas
        for sy in (-0.20, 0.20):
            p.append(_fc(sx, sy, -0.44, 0.10, 0.06))
    return Furniture("compound", parts=p, label="Carrito de dispositivos"), "Madera"


def _taburete():
    p = [_fc(0.0, 0.0, 0.27, 0.35, 0.06)]
    for sx in (-0.13, 0.13):
        for sy in (-0.13, 0.13):
            p.append(_fb(sx, sy, -0.03, 0.03, 0.03, 0.54))
    return Furniture("compound", parts=p, label="Taburete"), "Madera"


# --- Estudio / tratamiento acústico ---
def _gobo():
    p = [_fb(0, 0, 0.10, 0.70, 0.08, 1.50),           # panel fonoabsorbente
         _fb(0, 0, -0.83, 0.70, 0.40, 0.06)]          # base con ruedas
    for sx in (-0.28, 0.28):
        p.append(_fc(sx, 0.16, -0.89, 0.10, 0.05))
    return (Furniture("compound", parts=p, label="Gobo (panel móvil)"),
            "Panel acústico (espuma + tela)")


def _bass_trap():
    # Columna de esquina. NOTA: absorbente de LF; el modelo usa alpha(f) del
    # material (aprox membrana). Sintonía real no modelada.
    return (Furniture("cylinder", position=(0, 0, 0), size=(0.40, 0.40, 1.80),
                      label="Bass trap (esquina)"),
            "Panel de madera con camara de aire por detras")


def _difusor():
    # Skyline: bloques de distinta altura (COSMÉTICO: la difusión NO se modela).
    p = [_fb(0, 0, -0.06, 0.60, 0.20, 0.10)]          # base
    hs = [0.10, 0.22, 0.14, 0.28, 0.18]
    xs = [-0.22, -0.11, 0.0, 0.11, 0.22]
    for x, h in zip(xs, hs):
        p.append(_fb(x, 0.0, 0.0 + h / 2, 0.10, 0.18, h))
    return Furniture("compound", parts=p, label="Difusor QRD/Skyline"), "Madera"


def _helmholtz():
    # Caja resonante con boca (COSMÉTICO: la sintonía no se modela; se aproxima
    # con un material tipo panel con cámara de aire).
    p = [_fb(0, 0, 0, 0.60, 0.35, 0.70),
         _fb(0, 0.18, 0.0, 0.20, 0.02, 0.10)]         # boca/ranura
    return (Furniture("compound", parts=p, label="Resonador Helmholtz"),
            "Panel de madera con camara de aire por detras")


def _nube():
    # Panel suspendido del techo (placement="ceiling").
    p = [_fb(0, 0, 0, 1.40, 1.20, 0.10)]
    for sx in (-0.6, 0.6):                            # tensores
        for sy in (-0.5, 0.5):
            p.append(_fc(sx, sy, 0.20, 0.02, 0.30))
    return (Furniture("compound", parts=p, label="Nube acústica"),
            "Cielorraso acustico (lana de roca), 20 mm, 100 kg/m3, suspendido a 100 mm")


def _console_desk():
    p = [_fb(0, 0.10, 0.30, 1.60, 0.60, 0.04),        # superficie de control
         _fb(0, -0.30, 0.50, 1.60, 0.10, 0.34),       # puente de monitores
         _fb(-0.78, 0, 0.15, 0.04, 0.80, 0.60),       # laterales
         _fb(0.78, 0, 0.15, 0.04, 0.80, 0.60)]
    return Furniture("compound", parts=p, label="Console desk"), "Madera"


def _soporte_monitor():
    p = [_fb(0, 0, -0.43, 0.35, 0.35, 0.04),          # base pesada (arena)
         _fc(0, 0, 0.0, 0.12, 0.80),                  # columna
         _fb(0, 0, 0.43, 0.30, 0.30, 0.03)]           # plato
    return Furniture("compound", parts=p, label="Soporte de monitor"), None


def _rack():
    p = [_fb(0, 0, 0, 0.55, 0.65, 1.10)]              # frame 19"
    for z in (-0.4, 0.0, 0.4):
        p.append(_fb(0, 0.32, z, 0.50, 0.02, 0.03))   # unidades montadas
    return Furniture("compound", parts=p, label="Rack 19\""), None


def _sofa_control():
    p = [_fb(0.0, 0.05, -0.12, 1.90, 0.75, 0.42),     # cuerpo (absorbente banda ancha)
         _fb(0.0, -0.38, 0.12, 1.90, 0.15, 0.55),
         _fb(-0.88, 0.05, 0.05, 0.14, 0.78, 0.45),
         _fb(0.88, 0.05, 0.05, 0.14, 0.78, 0.45)]
    return Furniture("compound", parts=p, label="Sofá de control"), "Asientos tapizados"


def _silla_mezcla():
    p = [_fb(0, 0, -0.10, 0.50, 0.48, 0.08),          # asiento
         _fb(0, -0.22, 0.25, 0.48, 0.04, 0.45),       # respaldo de malla
         _fc(0, 0, -0.35, 0.08, 0.40),                # columna
         _fc(0, 0, -0.55, 0.60, 0.04)]                # base estrella (disco)
    return Furniture("compound", parts=p, label="Silla de mezcla"), "Asientos tapizados"


# Registro plano (nombre -> factory) + agrupación para el menú + placement.
FURNITURE_PRESETS = {
    "Silla": _silla, "Sillón": _sillon, "Escritorio": _escritorio, "Mesa": _mesa,
    "Banqueta": _banqueta, "Velador de piso": _velador, "Biblioteca": _biblioteca,
    "Pupitre": _pupitre, "Silla escolar": _silla_escolar,
    "Escritorio docente": _escritorio_docente, "Mesa grupal": _mesa_grupal,
    "Pizarrón": _pizarron, "Armario": _armario, "Estantería abierta": _estanteria,
    "Casilleros": _casilleros, "Carrito de dispositivos": _carrito,
    "Taburete": _taburete,
    "Gobo (panel móvil)": _gobo, "Bass trap (esquina)": _bass_trap,
    "Difusor QRD/Skyline": _difusor, "Resonador Helmholtz": _helmholtz,
    "Nube acústica": _nube, "Console desk": _console_desk,
    "Soporte de monitor": _soporte_monitor, "Rack 19\"": _rack,
    "Sofá de control": _sofa_control, "Silla de mezcla": _silla_mezcla,
}

# Menú agrupado (orden de aparición).
FURNITURE_PRESET_GROUPS = {
    "General": ["Silla", "Sillón", "Escritorio", "Mesa", "Banqueta",
                "Velador de piso", "Biblioteca"],
    "Aula": ["Pupitre", "Silla escolar", "Escritorio docente", "Mesa grupal",
             "Pizarrón", "Armario", "Estantería abierta", "Casilleros",
             "Carrito de dispositivos", "Taburete"],
    "Estudio / tratamiento": ["Gobo (panel móvil)", "Bass trap (esquina)",
                              "Difusor QRD/Skyline", "Resonador Helmholtz",
                              "Nube acústica", "Console desk", "Soporte de monitor",
                              "Rack 19\"", "Sofá de control", "Silla de mezcla"],
}

# Colocación al insertar: "floor" (default) o "ceiling" (suspendido del techo).
PRESET_PLACEMENT = {"Nube acústica": "ceiling"}


def make_preset(name: str):
    """Devuelve (Furniture compound, material sugerido) para el preset `name`."""
    return FURNITURE_PRESETS[name]()


def preset_placement(name: str) -> str:
    return PRESET_PLACEMENT.get(name, "floor")


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Malla trivial: cubo 2x2x2 de tets regulares (grid 0..2 paso 0.5).
    import itertools
    xs = np.arange(0, 2.01, 0.5)
    grid = np.array(list(itertools.product(xs, xs, xs)), dtype=float)
    # Tets falsos no hacen falta: probamos contains() y significancia directo.
    sofa = Furniture("box", position=(1, 1, 1), size=(0.8, 0.8, 0.8),
                     label="test")
    inside = sofa.contains(grid)
    assert inside[np.all(np.abs(grid - 1.0) <= 0.4 + 1e-9, axis=1)].all()
    assert abs(sofa.volume() - 0.512) < 1e-9
    print(f"[OK] box: {inside.sum()} nodos adentro, V={sofa.volume():.3f} m3")

    cyl = Furniture("cylinder", position=(1, 1, 1), size=(1.0, 1.0, 1.0))
    assert abs(cyl.volume() - np.pi * 0.25) < 1e-9
    print(f"[OK] cylinder V={cyl.volume():.3f} m3")

    thr = significance_threshold(159.0)
    assert is_significant(sofa, 159.0) and not is_significant(
        Furniture(size=(0.2, 0.2, 0.2)), 159.0)
    print(f"[OK] umbral significancia @159Hz = {thr:.3f} m")
    print("smoke furniture.py OK")
