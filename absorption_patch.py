"""absorption_patch.py
====================

Parches de absorcion SUB-CARA: una region rectangular dentro de una cara con su
propio material (coeficiente de absorcion), distinto del material del resto de la
cara.

Modelo mental
-------------
Un parche NO es fisica nueva: es darle resolucion sub-cara al mecanismo A36
(`face_materials.compute_xi_per_mode_per_face`). Las formas modales phi_n se
calculan con paredes rigidas (Neumann), asi que la absorcion NO entra en el
autoproblema y un parche NO cambia la forma del modo ni el heatmap de |phi_n|.
El alpha del parche entra por dos vias, las dos ya existentes:

  1. RT60 clasico (Sabine/Eyring): A = sum alpha_i * S_i. El parche aporta
     alpha_parche * S_parche y le RESTA area al material anfitrion.
  2. xi_n por modo (A36): alpha efectivo del modo n pesado por la presion modal
     phi_n^2 sobre cada region. Un modo con antinodo sobre el parche se amortigua
     mas; uno con nodo casi no lo ve.

Por que no se usa la malla de render para ubicar el parche
----------------------------------------------------------
La malla de superficie es GROSERA (una pared rectangular son 2 triangulos), asi
que "que triangulos caen dentro del parche" no resuelve un parche mas chico que
la cara. En cambio teselamos la cara FINO nosotros (subdividiendo cada triangulo
de render) y a cada punto de muestra le asignamos alpha_parche si cae dentro del
rectangulo, alpha_anfitrion si no. Integramos alpha*phi^2 y phi^2 sobre esos
puntos:

    alpha_eff(n) = sum_p alpha(p) * phi_n(p)^2 * dA_p  /  sum_p phi_n(p)^2 * dA_p

Propiedades (verificadas en bench_absorption_patch.py):
  - Sin parches y material uniforme, alpha_eff = alpha EXACTO (el alpha factoriza
    del cociente) -> reduce a la Sabine global, no regresiona A36.
  - Un parche que cubre la cara entera con material X == asignar X al grupo.

Alcance v1
----------
Rectangulos sobre caras axis-aligned (paredes/piso/techo). El marco local (u, v)
de la cara son los dos ejes del mundo distintos del eje de la normal dominante.
La extension a poligonos sobre caras arbitrarias (proyeccion al plano local) es
aditiva sobre esta base.

Persistencia
------------
Los parches se guardan en .room v8 dentro de `acoustic.absorption_patches` como
lista de dicts (`AbsorptionPatch.to_dict`). La clave de material del parche es su
`key` estable (hash de la geometria + cara).
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from face_materials import _face_normals_and_areas


# ---------------------------------------------------------------------------
# Marco local de una cara axis-aligned
# ---------------------------------------------------------------------------
def axis_aligned_frame(normal) -> Tuple[int, int, int]:
    """Devuelve (normal_axis, u_axis, v_axis) para una cara axis-aligned.

    El eje de la normal es el de mayor componente absoluta; los otros dos (en
    orden creciente) son los ejes en-plano u y v.

        normal ~ +/-z (2)  ->  (2, 0, 1)   u=X, v=Y   (piso/techo)
        normal ~ +/-x (0)  ->  (0, 1, 2)   u=Y, v=Z   (pared perp. a X)
        normal ~ +/-y (1)  ->  (1, 0, 2)   u=X, v=Z   (pared perp. a Y)
    """
    n = np.abs(np.asarray(normal, dtype=float))
    na = int(np.argmax(n))
    others = [ax for ax in (0, 1, 2) if ax != na]
    return na, others[0], others[1]


# ---------------------------------------------------------------------------
# Geometria de poligonos en el plano local (u, v)
# ---------------------------------------------------------------------------
def poly_area(uv) -> float:
    """Area de un poligono simple por la formula del cordon (shoelace)."""
    p = np.asarray(uv, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def points_in_poly(uv, u, v) -> np.ndarray:
    """Mascara booleana (ray casting) de que puntos (u, v) caen dentro del
    poligono `uv` (K,2). Vectorizado; sirve para convexos y no convexos."""
    p = np.asarray(uv, dtype=float)
    x = np.asarray(u, dtype=float)
    y = np.asarray(v, dtype=float)
    inside = np.zeros(x.shape, dtype=bool)
    K = len(p)
    j = K - 1
    for i in range(K):
        xi, yi = p[i, 0], p[i, 1]
        xj, yj = p[j, 0], p[j, 1]
        dy = yj - yi
        dy = dy if abs(dy) > 1e-30 else 1e-30
        cond = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / dy + xi)
        inside ^= cond
        j = i
    return inside


def _point_in_poly_single(uv, pt, strict: bool = True) -> bool:
    m = points_in_poly(uv, np.array([pt[0]]), np.array([pt[1]]))
    return bool(m[0])


def _seg_cross(a0, a1, b0, b1) -> bool:
    """True si los segmentos a0-a1 y b0-b1 se cruzan PROPIAMENTE (no solo se
    tocan en un extremo / colineales). Test por orientaciones."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = cross(b0, b1, a0)
    d2 = cross(b0, b1, a1)
    d3 = cross(a0, a1, b0)
    d4 = cross(a0, a1, b1)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def polys_overlap(A, B) -> bool:
    """True si dos poligonos simples se solapan en AREA. Permite adyacencia
    (aristas/vertices compartidos sin area en comun).

    Estrategia (barata y robusta para el editor):
      1. Rechazo rapido por bounding box.
      2. Algun vertice o el centroide de uno cae ESTRICTO dentro del otro.
      3. Alguna arista de uno cruza PROPIAMENTE una arista del otro.
    """
    A = np.asarray(A, dtype=float)
    B = np.asarray(B, dtype=float)
    if len(A) < 3 or len(B) < 3:
        return False
    # 1. bbox
    if (A[:, 0].max() <= B[:, 0].min() or B[:, 0].max() <= A[:, 0].min() or
            A[:, 1].max() <= B[:, 1].min() or B[:, 1].max() <= A[:, 1].min()):
        return False
    # 2. vertices y centroides estrictos
    cA = A.mean(axis=0)
    cB = B.mean(axis=0)
    if _point_in_poly_single(B, cA) or _point_in_poly_single(A, cB):
        return True
    if any(_point_in_poly_single(B, p) for p in A):
        return True
    if any(_point_in_poly_single(A, p) for p in B):
        return True
    # 3. cruces propios de aristas
    na, nb = len(A), len(B)
    for i in range(na):
        a0, a1 = A[i], A[(i + 1) % na]
        for j in range(nb):
            b0, b1 = B[j], B[(j + 1) % nb]
            if _seg_cross(a0, a1, b0, b1):
                return True
    return False


def triangulate_uv(uv):
    """Triangula un poligono simple (convexo o no) por ear clipping.

    Devuelve lista de (i, j, k) indices a `uv`. Para el overlay 3D de parches
    no convexos (un fan seria incorrecto). Robusto a orientacion.
    """
    pts = [tuple(map(float, p)) for p in uv]
    n = len(pts)
    if n < 3:
        return []
    idx = list(range(n))
    # Orientacion CCW
    if (0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                  for i in range(n))) < 0:
        idx.reverse()

    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def _in_tri(p, a, b, c):
        d1 = _cross(p, a, b)
        d2 = _cross(p, b, c)
        d3 = _cross(p, c, a)
        neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        found = False
        m = len(idx)
        for a in range(m):
            i0, i1, i2 = idx[(a - 1) % m], idx[a], idx[(a + 1) % m]
            p0, p1, p2 = pts[i0], pts[i1], pts[i2]
            if _cross(p0, p1, p2) <= 0:      # reflex o colineal -> no es oreja
                continue
            ear = True
            for k in idx:
                if k in (i0, i1, i2):
                    continue
                if _in_tri(pts[k], p0, p1, p2):
                    ear = False
                    break
            if ear:
                tris.append((i0, i1, i2))
                del idx[a]
                found = True
                break
        if not found:
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


# ---------------------------------------------------------------------------
# Espesor del tratamiento
# ---------------------------------------------------------------------------
# Espesor por defecto de un parche [m]. 10 cm es el espesor tipico de un panel
# absorbente de banda ancha. Es geometrico (dibujo + lectura de lambda/4); el
# solver sigue usando el alpha(f) del catalogo, que ya incluye el espesor real
# de la construccion medida.
DEFAULT_PATCH_DEPTH = 0.10


# Numeros con unidad de longitud dentro del nombre de un material del catalogo.
_LEN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mm|cm)\b", re.I)

# Contexto (palabras ANTES del numero) que indica geometria EN-PLANO, no
# profundidad: el ancho de las ranuras de un panel estriado y su separacion.
# Sumarlas seria un error (ej.: "franjas de 12 mm a intervalos de 20 mm,
# absorbente de 40 mm, cavidad de 100 mm" -> profundidad = 140, no 172).
_IN_PLANE_WORDS = ("franja", "intervalo", "diametro", "diámetro", "paso",
                   "ancho", "separacion", "separación")
# ("abierto" NO va aca: el "20% abierto" de los perforados no lleva unidad de
#  longitud, asi que nunca matchea, y en cambio ensuciaba el contexto del
#  numero siguiente -> "20% abierto, absorbente de 40 mm" perdia los 40 mm.)

# Ventana de texto previo que se mira para clasificar cada numero.
_CTX_CHARS = 26


def thickness_from_material_name(name: str) -> Optional[float]:
    """Profundidad [m] que ocupa la construccion, leida del NOMBRE del material.

    El catalogo describe la construccion completa en el nombre
    ("Lana de vidrio 100 mm, 25 kg/m3", "Cielorraso ... 20 mm ... suspendido a
    100 mm"). Esta funcion suma los espesores que aportan PROFUNDIDAD (la capa
    absorbente, la cavidad, la camara de aire, el descuelgue) y descarta los que
    son geometria en-plano (ancho de franjas, intervalos, diametro de
    perforaciones).

    Devuelve None si el nombre no declara espesor (no se puede inferir).

    OJO: es lectura de texto libre, o sea heuristica. Se usa solo para
    PRE-CARGAR el espesor del dibujo y para avisar de inconsistencias; NUNCA
    entra al solver, donde manda alpha(f) del catalogo. Un parseo equivocado es
    un error de dibujo, no de fisica.
    """
    if not name:
        return None
    total_mm = 0.0
    found = False
    for m in _LEN_RE.finditer(name):
        ctx = name[max(0, m.start() - _CTX_CHARS):m.start()].lower()
        if any(w in ctx for w in _IN_PLANE_WORDS):
            continue                       # ancho/separacion: no es profundidad
        val = float(m.group(1).replace(",", "."))
        if m.group(2).lower() == "cm":
            val *= 10.0
        total_mm += val
        found = True
    if not found or total_mm <= 0.0:
        return None
    return total_mm / 1000.0


def quarter_wave_limit(depth: float, c: float = 343.0) -> float:
    """Frecuencia [Hz] a partir de la cual un absorbente POROSO de `depth` metros
    montado al ras empieza a trabajar: f = c / (4 d).

    Regla de lambda/4: el poroso actua sobre la VELOCIDAD de particula, que es
    nula sobre la pared rigida y maxima a un cuarto de onda de ella. Por debajo
    de esta frecuencia el panel es casi transparente.

    Numero que importa en este software: 10 cm -> ~860 Hz, MUY por encima de la
    banda modal que resuelve el FEM. Es decir, un poroso de 10 cm al ras casi no
    toca los modos; para graves hacen falta espesores mucho mayores, montaje
    despegado de la pared, o dispositivos de presion (membrana/perforado), que es
    lo que ya avisa el criterio B27 (`face_materials.lf_modal_absorption_hints`).
    """
    d = float(depth)
    if d <= 0.0:
        return float("inf")
    return float(c / (4.0 * d))


# ---------------------------------------------------------------------------
# Dataclass del parche
# ---------------------------------------------------------------------------
@dataclass
class AbsorptionPatch:
    """Un rectangulo de material sobre una cara axis-aligned.

    Atributos geometricos (todos en coordenadas del MUNDO, metros):
        face_signature : firma del FaceGroup anfitrion (estable, ver face_materials).
        normal_axis    : 0/1/2, eje de la normal de la cara.
        plane_coord    : coordenada constante de la cara a lo largo de la normal.
        u_axis, v_axis : ejes en-plano (los dos que no son normal_axis).
        u0, u1         : rango del rectangulo sobre u_axis (u0 <= u1).
        v0, v1         : rango del rectangulo sobre v_axis (v0 <= v1).
        material_name  : nombre del material del catalogo aplicado en el parche.
        label          : etiqueta legible opcional.
        depth          : espesor del tratamiento [m], hacia el INTERIOR de la sala
                         (default 0.10 = 10 cm, el espesor tipico de un panel
                         absorbente). Es GEOMETRICO/DOCUMENTAL: dibuja el parche
                         como prisma en vez de plano y permite leer cuanto invade
                         el recinto y hasta donde llega su lambda/4. NO entra al
                         solver: el alpha(f) del catalogo YA esta medido CON el
                         espesor de esa construccion (ISO 354), asi que sumarlo
                         como obstaculo seria contarlo dos veces. Ver la nota de
                         `quarter_wave_limit`.
    """
    face_signature: str
    normal_axis: int
    plane_coord: float
    u_axis: int
    v_axis: int
    u0: float
    u1: float
    v0: float
    v1: float
    material_name: str = ""
    label: str = ""
    # Poligono en local (u, v). None -> el parche ES el rectangulo [u0,u1]x[v0,v1]
    # (retrocompatible con .room v8 previo). Cuando esta seteado, u0..v1 son su
    # bounding box (se mantienen para rechazo rapido y display).
    poly: Optional[List[Tuple[float, float]]] = None
    depth: float = DEFAULT_PATCH_DEPTH

    def polygon_uv(self) -> List[Tuple[float, float]]:
        """Vertices efectivos del parche en (u, v): el poligono si lo tiene,
        o las 4 esquinas del rectangulo."""
        if self.poly:
            return [(float(a), float(b)) for (a, b) in self.poly]
        return [(self.u0, self.v0), (self.u1, self.v0),
                (self.u1, self.v1), (self.u0, self.v1)]

    @property
    def area(self) -> float:
        if self.poly:
            return poly_area(self.poly)
        return float(max(0.0, self.u1 - self.u0) * max(0.0, self.v1 - self.v0))

    @property
    def volume(self) -> float:
        """Volumen que ocupa el prisma [m^3] = area x espesor. Informativo (cuanto
        invade el recinto); NO se descuenta del volumen de aire del solver."""
        return float(self.area * max(0.0, self.depth))

    @property
    def quarter_wave_hz(self) -> float:
        """f = c/(4d) del espesor de este parche (ver `quarter_wave_limit`)."""
        return quarter_wave_limit(self.depth)

    @property
    def key(self) -> str:
        """Clave estable (hash de cara + geometria EN-PLANO). Sirve de id para el
        mapa parche->Material y para persistencia.

        OJO: el espesor NO entra al hash a proposito. Si entrara, cambiar el
        espesor generaria una clave nueva y el parche perderia su material
        asignado."""
        if self.poly:
            geo = "poly=" + ";".join(f"{a:.3f},{b:.3f}" for (a, b) in self.poly)
        else:
            geo = f"u=[{self.u0:.3f},{self.u1:.3f}]|v=[{self.v0:.3f},{self.v1:.3f}]"
        s = f"{self.face_signature}|n={self.normal_axis}|p={self.plane_coord:.3f}|{geo}"
        return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

    def contains(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Mascara booleana: que puntos (u, v) caen dentro del parche."""
        if self.poly:
            return points_in_poly(self.poly, u, v)
        return (u >= self.u0) & (u <= self.u1) & (v >= self.v0) & (v <= self.v1)

    def translate(self, delta) -> None:
        """Traslada el parche por `delta` (3,) en coords MUNDO, in-place.

        Se usa al cambiar la convencion de origen (`origin_mode`): el recinto se
        mueve y todo lo anclado a el tiene que moverse CON el, si no el parche
        queda flotando fuera de su cara. Como la geometria del parche vive en el
        marco (normal, u, v) de la cara, cada componente del delta va al eje que
        le corresponde.
        """
        d = np.asarray(delta, dtype=float)
        self.plane_coord = float(self.plane_coord + d[self.normal_axis])
        du, dv = float(d[self.u_axis]), float(d[self.v_axis])
        self.u0 += du; self.u1 += du
        self.v0 += dv; self.v1 += dv
        if self.poly:
            self.poly = [(float(a + du), float(b + dv)) for (a, b) in self.poly]

    def to_dict(self) -> dict:
        d = {
            "face_signature": self.face_signature,
            "normal_axis": int(self.normal_axis),
            "plane_coord": float(self.plane_coord),
            "u_axis": int(self.u_axis),
            "v_axis": int(self.v_axis),
            "u0": float(self.u0), "u1": float(self.u1),
            "v0": float(self.v0), "v1": float(self.v1),
            "material_name": self.material_name,
            "label": self.label,
            "depth": float(self.depth),
        }
        if self.poly:
            d["poly"] = [[float(a), float(b)] for (a, b) in self.poly]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AbsorptionPatch":
        poly = d.get("poly")
        poly = [(float(a), float(b)) for (a, b) in poly] if poly else None
        return cls(
            face_signature=str(d["face_signature"]),
            normal_axis=int(d["normal_axis"]),
            plane_coord=float(d["plane_coord"]),
            u_axis=int(d["u_axis"]),
            v_axis=int(d["v_axis"]),
            u0=float(d["u0"]), u1=float(d["u1"]),
            v0=float(d["v0"]), v1=float(d["v1"]),
            material_name=str(d.get("material_name", "")),
            label=str(d.get("label", "")),
            poly=poly,
            # .room v8 previo (sin "depth") -> espesor por defecto: los parches
            # viejos pasan a dibujarse como prisma, que es el comportamiento
            # pedido. Como el espesor no toca el solver, la acustica del archivo
            # cargado no cambia ni un digito.
            depth=float(d.get("depth", DEFAULT_PATCH_DEPTH)),
        )


def make_patch(group, u0: float, v0: float, u1: float, v1: float,
               material_name: str = "", label: str = "",
               depth: float = DEFAULT_PATCH_DEPTH) -> AbsorptionPatch:
    """Crea un parche a partir de un FaceGroup y un rectangulo en local (u, v).

    El marco local se deriva de la normal del grupo (cara axis-aligned). La
    coordenada del plano se toma del centroide del grupo.
    """
    na, ua, va = axis_aligned_frame(group.normal)
    plane = float(group.centroid[na])
    return AbsorptionPatch(
        face_signature=group.signature,
        normal_axis=na, plane_coord=plane, u_axis=ua, v_axis=va,
        u0=float(min(u0, u1)), u1=float(max(u0, u1)),
        v0=float(min(v0, v1)), v1=float(max(v0, v1)),
        material_name=material_name, label=label, depth=float(depth),
    )


def make_polygon_patch(group, uv_points, material_name: str = "",
                       label: str = "",
                       depth: float = DEFAULT_PATCH_DEPTH) -> AbsorptionPatch:
    """Crea un parche POLIGONAL a partir de un FaceGroup y una lista de vertices
    en local (u, v). El rectangulo u0..v1 se fija como bounding box del poligono."""
    na, ua, va = axis_aligned_frame(group.normal)
    plane = float(group.centroid[na])
    p = np.asarray(uv_points, dtype=float)
    return AbsorptionPatch(
        face_signature=group.signature,
        normal_axis=na, plane_coord=plane, u_axis=ua, v_axis=va,
        u0=float(p[:, 0].min()), u1=float(p[:, 0].max()),
        v0=float(p[:, 1].min()), v1=float(p[:, 1].max()),
        material_name=material_name, label=label, depth=float(depth),
        poly=[(float(a), float(b)) for (a, b) in p],
    )


# ---------------------------------------------------------------------------
# Teselado fino de una cara (para integrar phi^2 con resolucion sub-cara)
# ---------------------------------------------------------------------------
def _subdivide_tri(a: np.ndarray, b: np.ndarray, c: np.ndarray, k: int
                   ) -> np.ndarray:
    """Centroides de las k^2 sub-triangulos congruentes de un triangulo.

    Grilla baricentrica P(i, j) = a + (i/k)(b-a) + (j/k)(c-a), i+j <= k.
    Sub-triangulos "hacia arriba" (k(k+1)/2) y "hacia abajo" (k(k-1)/2);
    en total k^2, cada uno de area = area_tri / k^2.

    Devuelve centroids (k^2, 3).
    """
    ab = (b - a) / k
    ac = (c - a) / k
    cents = []
    for i in range(k):
        for j in range(k - i):
            # sub-triangulo hacia arriba: P(i,j), P(i+1,j), P(i,j+1)
            p0 = a + i * ab + j * ac
            p1 = a + (i + 1) * ab + j * ac
            p2 = a + i * ab + (j + 1) * ac
            cents.append((p0 + p1 + p2) / 3.0)
            # sub-triangulo hacia abajo: P(i+1,j), P(i,j+1), P(i+1,j+1)
            if i + j < k - 1:
                q = a + (i + 1) * ab + (j + 1) * ac
                cents.append((p1 + p2 + q) / 3.0)
    return np.asarray(cents, dtype=float)


def tessellate_group(verts: np.ndarray, tris: np.ndarray, group,
                     h_target: float = 0.2, kmax: int = 8
                     ) -> Tuple[np.ndarray, np.ndarray]:
    """Teselado fino de un FaceGroup: puntos de muestra + area de cada uno.

    Cada triangulo de render se subdivide en k^2 sub-triangulos con
    k = clamp(ceil(sqrt(area)/h_target), 1, kmax). El area total se conserva
    (sum de areas == area del grupo).

    Devuelve (points (Np, 3), areas (Np,)).
    """
    verts = np.asarray(verts, dtype=float)
    tris = np.asarray(tris, dtype=int)
    fidx = np.asarray(group.face_indices, dtype=int)
    pts_blocks: List[np.ndarray] = []
    area_blocks: List[np.ndarray] = []
    for ti in fidx:
        tri = tris[ti]
        a, b, c = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        area = 0.5 * float(np.linalg.norm(np.cross(b - a, c - a)))
        if area <= 1e-12:
            continue
        k = int(min(max(1, int(np.ceil(np.sqrt(area) / max(h_target, 1e-6)))), kmax))
        cents = _subdivide_tri(a, b, c, k)
        pts_blocks.append(cents)
        area_blocks.append(np.full(len(cents), area / float(len(cents))))
    if not pts_blocks:
        return np.empty((0, 3)), np.empty((0,))
    return np.vstack(pts_blocks), np.concatenate(area_blocks)


# ---------------------------------------------------------------------------
# xi_n por modo con parches (A36 con resolucion sub-cara)
# ---------------------------------------------------------------------------
def _alpha_of(mat, f: float, default_alpha: float) -> float:
    if mat is None:
        return default_alpha
    return float(mat.alpha(f))


def sabine_rt60_with_patches(
    V: float,
    groups: List,
    group_to_material: Dict[str, "object"],
    patches: List[AbsorptionPatch],
    patch_to_material: Dict[str, "object"],
    bands: Optional[List[int]] = None,
    default_alpha: float = 0.03,
) -> Dict[int, float]:
    """RT60 de Sabine con parches: cada parche le RESTA area a su cara anfitriona
    y aporta su propio alpha sobre esa area.

        A(f) = sum_g alpha_g(f) (S_g - S_parches_g) + sum_p alpha_p(f) S_p
        RT60(f) = 0.161 V / A(f)

    Reduce EXACTO a `face_materials.compute_sabine_rt60_per_face` cuando no hay
    parches (S_parches_g = 0). Es puramente geometrico (areas nominales); no
    resuelve solapes entre parches de la misma cara (caso de borde).
    """
    from material_library import BANDS
    if bands is None:
        bands = BANDS
    by_face: Dict[str, List[AbsorptionPatch]] = defaultdict(list)
    for p in patches or []:
        by_face[p.face_signature].append(p)

    rt60: Dict[int, float] = {}
    for f in bands:
        A = 0.0
        for g in groups:
            host = group_to_material.get(g.signature)
            a_host = _alpha_of(host, f, default_alpha)
            pg = by_face.get(g.signature, [])
            patch_area = sum(p.area for p in pg)
            host_area = max(g.area - patch_area, 0.0)
            A += a_host * host_area
            for p in pg:
                a_p = _alpha_of(patch_to_material.get(p.key), f, default_alpha)
                A += a_p * p.area
        A = max(A, 1e-6)
        rt60[f] = 0.161 * V / A
    return rt60


def compute_xi_per_mode_with_patches(
    freqs: np.ndarray,
    phis: np.ndarray,
    locator,
    verts: np.ndarray,
    tris: np.ndarray,
    groups: List,
    group_to_material: Dict[str, "object"],
    patches: List[AbsorptionPatch],
    patch_to_material: Dict[str, "object"],
    V: float,
    default_alpha: float = 0.03,
    h_target: float = 0.2,
    kmax: int = 8,
    model: str = "a36",
    c: float = 343.0,
) -> Optional[np.ndarray]:
    """xi_n por modo con parches de absorcion sub-cara (cuadratura FINA).

    Cada cara se integra sobre un teselado fino y cada punto usa el alpha del
    parche que lo cubre (o el del material anfitrion de la cara si ninguno lo
    cubre). Los puntos se agrupan por "slot" (cada material distinto = un slot).

    Dos modelos de amortiguamiento (Etapa 1.b, v2.23) sobre la MISMA maquinaria
    de teselado + slots; solo cambia como se convierte la absorcion en xi:

      model="a36" (default): Sabine por modo, via el COCIENTE de integrales
        alpha_eff(n) = sum_s alpha_s(f_n) Ws / sum_s Ws
        T60(n) = 0.161 V / (S_total alpha_eff(n)) ;  xi = 1.1/(f T60)

      model="perturbation": perturbacion de frontera de 1er orden, via la
        integral de superficie ABSOLUTA por slot (Ws ya lo es):
        delta(n) = (c/2) sum_s beta_s(f_n) Ws   [Np/s] ;  xi = delta/omega_n
        con beta_s = inversion de Paris del alpha_s (ver face_materials).
        La teselacion fina de los parches es JUSTO la cuadratura que la
        perturbacion necesita para la integral absoluta -> aca es natural.

    - `group_to_material`: signature de FaceGroup -> Material (anfitrion de la cara).
    - `patch_to_material`: patch.key -> Material (material del parche).

    Devuelve xi (Nm,) o None si no hay datos.
    """
    if phis is None or not groups or locator is None:
        return None
    freqs = np.asarray(freqs, dtype=float)
    Nm = int(phis.shape[1])
    if Nm == 0 or freqs.size < Nm:
        return None

    S_total = float(sum(g.area for g in groups))
    if S_total <= 0 or V <= 0:
        return None

    by_face: Dict[str, List[AbsorptionPatch]] = defaultdict(list)
    for p in patches or []:
        by_face[p.face_signature].append(p)

    # Slots de material: cada material distinto (anfitriones + parches) recibe un
    # indice. Cada punto de muestra apunta a un slot. Asi evaluamos phi_n una sola
    # vez sobre TODOS los puntos por modo y hacemos bincount por slot.
    slot_mats: List[object] = []          # Material o None (-> default_alpha)
    slot_of: Dict[int, int] = {}

    def _slot_for(mat) -> int:
        key = id(mat) if mat is not None else 0
        if key not in slot_of:
            slot_of[key] = len(slot_mats)
            slot_mats.append(mat)
        return slot_of[key]

    pts_all: List[np.ndarray] = []
    area_all: List[np.ndarray] = []
    slot_all: List[np.ndarray] = []

    for g in groups:
        pts, ars = tessellate_group(verts, tris, g, h_target, kmax)
        if len(pts) == 0:
            continue
        host = group_to_material.get(g.signature)
        host_slot = _slot_for(host)
        slots = np.full(len(pts), host_slot, dtype=int)
        pg = by_face.get(g.signature, [])
        if pg:
            u = pts[:, pg[0].u_axis]
            v = pts[:, pg[0].v_axis]
            for p in pg:
                inside = p.contains(u, v)
                if np.any(inside):
                    slots[inside] = _slot_for(patch_to_material.get(p.key))
        pts_all.append(pts)
        area_all.append(ars)
        slot_all.append(slots)

    if not pts_all:
        return None
    PTS = np.vstack(pts_all)
    AREA = np.concatenate(area_all)
    SLOT = np.concatenate(slot_all)
    n_slots = len(slot_mats)

    # Mismo criterio que A36 (face_materials, v2.23): los puntos de cuadratura
    # que el locator NO ubica se DESCARTAN y cada slot se re-escala por su
    # cobertura de area, en vez de entrar con phi=0 (que los hacia pesar cero
    # en silencio y subestimaba la absorcion de las caras oblicuas).
    VALID = np.isfinite(np.real(locator.evaluate_many(phis[:, 0], PTS)))
    area_tot_s = np.bincount(SLOT, weights=AREA, minlength=n_slots)
    area_ok_s = np.bincount(SLOT[VALID], weights=AREA[VALID], minlength=n_slots)
    cover_s = np.where(area_ok_s > 0,
                       area_tot_s / np.maximum(area_ok_s, 1e-12), 0.0)

    is_pert = (str(model).lower() == "perturbation")
    if is_pert:
        from face_materials import beta_from_alpha_random

    xi = np.empty(Nm, dtype=float)
    for n in range(Nm):
        fn = float(freqs[n])
        vals = locator.evaluate_many(phis[:, n], PTS)      # complejo (Np,)
        w = np.where(VALID, np.nan_to_num(np.real(vals)) ** 2, 0.0) * AREA
        J = float(w.sum())
        if J <= 0:
            # Modo sin presion evaluable en frontera: fallback por area/slot.
            Ws = np.bincount(SLOT, weights=AREA, minlength=n_slots)
            J = float(Ws.sum())
        else:
            # Ws[s] = INT_slot phi_n^2 dS  (ABSOLUTO, re-escalado por cobertura).
            Ws = np.bincount(SLOT, weights=w, minlength=n_slots) * cover_s
            J = float(Ws.sum())      # J coherente con los pesos re-escalados
        alpha_s = np.array([_alpha_of(slot_mats[s], fn, default_alpha)
                            for s in range(n_slots)], dtype=float)
        if is_pert:
            # perturbacion: la integral ABSOLUTA por slot (Ws) x beta, sin RT60.
            beta_s = beta_from_alpha_random(alpha_s)
            delta = 0.5 * c * float((beta_s * Ws).sum())       # Np/s
            xi[n] = delta / max(2.0 * np.pi * fn, 1e-9)
        else:
            alpha_eff = max(float((alpha_s * Ws).sum() / max(J, 1e-30)), 1e-6)
            T60 = 0.161 * V / (S_total * alpha_eff)
            xi[n] = 1.1 / max(fn * T60, 1e-9)
    return xi


def compute_xi_shift_with_impedance(
    freqs: np.ndarray,
    phis: np.ndarray,
    locator,
    verts: np.ndarray,
    tris: np.ndarray,
    groups: List,
    surf_by_group: Dict[str, "object"],     # signature -> SurfaceImpedance
    patches: List[AbsorptionPatch],
    surf_by_patch: Dict[str, "object"],      # patch.key -> SurfaceImpedance
    V: float,
    default_surf=None,
    h_target: float = 0.2,
    kmax: int = 8,
    c: float = 343.0,
) -> Optional[tuple]:
    """Perturbacion de frontera COMPLEJA (Capa 0, Etapa 5c) sobre la MISMA
    maquinaria de teselado fino que los parches: cada superficie (cara, parche o
    mueble) tiene una `SurfaceImpedance`, y se computa el amortiguamiento MAS el
    corrimiento de las frecuencias modales en una sola pasada.

        delta_c(n) = (c/2) sum_slot beta_slot(f_n) Ws        (complejo)
        xi[n]     = Re(delta_c)/omega_n                       (amortiguamiento)
        f_new[n]  = f_n - Im(delta_c)/(2 pi)                  (corrimiento reactivo)

    con beta_slot = conj(rho0*c / Z_slot(f_n)) [convencion e^{-iwt} de impedance.py
    -> e^{+iwt} del solver]. Incidencia NORMAL (reaccion local) en este camino
    unificado; la reaccion extendida por angulo (perturbation_xi_shift_extended)
    queda para el caso de solo-paredes. Devuelve (xi, f_new) o None.

    - `surf_by_group`: signature de FaceGroup (incluye muebles __furniture_i__) ->
      SurfaceImpedance. Cara sin entrada -> `default_surf` (o rigido).
    - `surf_by_patch`: patch.key -> SurfaceImpedance del parche.
    """
    if phis is None or not groups or locator is None:
        return None
    freqs = np.asarray(freqs, dtype=float)
    Nm = int(phis.shape[1])
    if Nm == 0 or freqs.size < Nm or V <= 0:
        return None
    Z0 = 1.21 * c

    by_face: Dict[str, List[AbsorptionPatch]] = defaultdict(list)
    for p in patches or []:
        by_face[p.face_signature].append(p)

    slot_surf: List[object] = []
    slot_of: Dict[int, int] = {}

    def _slot_for(surf) -> int:
        key = id(surf) if surf is not None else 0
        if key not in slot_of:
            slot_of[key] = len(slot_surf)
            slot_surf.append(surf)
        return slot_of[key]

    pts_all, area_all, slot_all = [], [], []
    for g in groups:
        pts, ars = tessellate_group(verts, tris, g, h_target, kmax)
        if len(pts) == 0:
            continue
        host_surf = surf_by_group.get(g.signature, default_surf)
        slots = np.full(len(pts), _slot_for(host_surf), dtype=int)
        pg = by_face.get(g.signature, [])
        if pg:
            u = pts[:, pg[0].u_axis]
            v = pts[:, pg[0].v_axis]
            for p in pg:
                inside = p.contains(u, v)
                if np.any(inside):
                    ps = surf_by_patch.get(p.key, host_surf)
                    slots[inside] = _slot_for(ps)
        pts_all.append(pts); area_all.append(ars); slot_all.append(slots)

    if not pts_all:
        return None
    PTS = np.vstack(pts_all)
    AREA = np.concatenate(area_all)
    SLOT = np.concatenate(slot_all)
    n_slots = len(slot_surf)

    VALID = np.isfinite(np.real(locator.evaluate_many(phis[:, 0], PTS)))
    area_tot_s = np.bincount(SLOT, weights=AREA, minlength=n_slots)
    area_ok_s = np.bincount(SLOT[VALID], weights=AREA[VALID], minlength=n_slots)
    cover_s = np.where(area_ok_s > 0,
                       area_tot_s / np.maximum(area_ok_s, 1e-12), 0.0)

    xi = np.empty(Nm, dtype=float)
    f_new = np.empty(Nm, dtype=float)
    for n in range(Nm):
        fn = float(freqs[n])
        vals = locator.evaluate_many(phis[:, n], PTS)
        w = np.where(VALID, np.nan_to_num(np.real(vals)) ** 2, 0.0) * AREA
        Ws = np.bincount(SLOT, weights=w, minlength=n_slots) * cover_s
        beta_s = np.empty(n_slots, dtype=complex)
        for s in range(n_slots):
            surf = slot_surf[s]
            if surf is None:
                beta_s[s] = 0.0
            else:
                beta_s[s] = np.conj(Z0 / complex(surf.Z(fn)[0]))
        cdelta = 0.5 * c * complex((beta_s * Ws).sum())
        xi[n] = cdelta.real / max(2.0 * np.pi * fn, 1e-9)
        f_new[n] = fn - cdelta.imag / (2.0 * np.pi)
    return xi, f_new
