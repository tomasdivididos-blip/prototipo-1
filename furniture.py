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
    label       : nombre para UI / informe de auditoria.
    provenance  : de donde salieron las dimensiones (medida propia, catalogo,
                  archivo importado + licencia). Trazabilidad (R6.6).
    """
    kind: str = "box"
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: Tuple[float, float, float] = (0.5, 0.5, 0.5)
    orientation: float = 0.0
    pitch: float = 0.0
    label: str = "mueble"
    provenance: str = ""

    # ----- geometria -------------------------------------------------------
    def volume(self) -> float:
        """Volumen analitico [m^3]."""
        sx, sy, sz = self.size
        if self.kind == "cylinder":
            r = sx / 2.0
            return float(np.pi * r * r * sz)
        return float(sx * sy * sz)

    def max_dim(self) -> float:
        return float(max(self.size))

    def contains(self, points: np.ndarray) -> np.ndarray:
        """Mascara (N,) bool: que puntos caen adentro del mueble.

        points : (N, 3).
        """
        p = np.asarray(points, dtype=float) - np.asarray(self.position, float)
        sx, sy, sz = self.size
        if self.kind == "cylinder":
            r = sx / 2.0
            return ((p[:, 0] ** 2 + p[:, 1] ** 2 <= r * r)
                    & (np.abs(p[:, 2]) <= sz / 2.0))
        # box con yaw (+pitch): proyectar el punto sobre los ejes locales.
        # ejes: yaw th sobre z -> ex=(c,s,0), ey=(-s,c,0), ez=(0,0,1);
        # luego pitch ph sobre ey -> ex'=cp*ex+sp*ez, ez'=-sp*ex+cp*ez, ey'=ey.
        # pitch=0 reduce EXACTO al caso solo-yaw (cp=1, sp=0).
        th = np.radians(self.orientation)
        ph = np.radians(float(getattr(self, "pitch", 0.0) or 0.0))
        c, s = np.cos(th), np.sin(th)
        cp, sp = np.cos(ph), np.sin(ph)
        xl = (cp * c) * p[:, 0] + (cp * s) * p[:, 1] + sp * p[:, 2]   # . ex'
        yl = (-s) * p[:, 0] + c * p[:, 1]                            # . ey'
        zl = (-sp * c) * p[:, 0] + (-sp * s) * p[:, 1] + cp * p[:, 2]  # . ez'
        return ((np.abs(xl) <= sx / 2.0)
                & (np.abs(yl) <= sy / 2.0)
                & (np.abs(zl) <= sz / 2.0))

    # ----- persistencia (.room v7) -----------------------------------------
    def to_dict(self) -> dict:
        return {"kind": self.kind, "position": list(self.position),
                "size": list(self.size), "orientation": self.orientation,
                "pitch": self.pitch,
                "label": self.label, "provenance": self.provenance}

    @classmethod
    def from_dict(cls, d: dict) -> "Furniture":
        return cls(kind=str(d.get("kind", "box")),
                   position=tuple(d.get("position", (0, 0, 0))),
                   size=tuple(d.get("size", (0.5, 0.5, 0.5))),
                   orientation=float(d.get("orientation", 0.0)),
                   pitch=float(d.get("pitch", 0.0)),
                   label=str(d.get("label", "mueble")),
                   provenance=str(d.get("provenance", "")))


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
