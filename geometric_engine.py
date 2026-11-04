"""
geometric_engine.py
===================

Motor geometrico (acustica de rayos) del simulador, FASE R0 = ANDAMIAJE.
Vale ARRIBA de la frecuencia de Schroeder, donde el campo deja de ser modal; se
empalma con el nucleo modal FEM (que vale abajo) en f_S (ver plan_motor_rayos.md,
Q2). Diseno cerrado por grill (Q1-Q10). Disciplina D0: numpy/scipy desde cero.

R0 (esta entrega, SIN fisica nueva):
  - `boundary_faces(nodes, tets)`: extrae las CARAS LIBRES del tet-mesh (las que
    pertenecen a un solo tetraedro) = la superficie acustica REAL del dominio YA
    TALLADO (paredes + columnas + muebles), triangulada y con normal hacia el
    AIRE. Es la geometria sobre la que corren rayos e imagenes (Q3). Trata shoebox,
    sala en L, CAD y obstaculos tallados de forma uniforme.
  - `face_geometry(nodes, faces)`: centroides, normales unitarias (hacia el aire)
    y areas por cara.
  - Dataclasses del CONTRATO de I/O: `GeoSource`, `GeoReceiver`, `Scene`.
  - Adaptador `specular_oracle_shoebox(...)`: formaliza `reflections_ism` como
    ORACULO ESPECULAR de R1.
  - Stubs de la API que R1-R5 van llenando (levantan NotImplementedError con la
    fase que los implementa).

El resto de las fases (plan_motor_rayos.md):
  R1 imagenes con visibilidad (temprano, coherente)  -> early_reflections
  R2 trazado estocastico de rayos (cola difusa)       -> diffuse_tail
  R3 difraccion de bordes BTM (coherente)             -> edge_diffraction
  R4 fuente/scattering/aire/mixing time (entradas)
  R5 empalme hibrido en f_S + salida                  -> hybrid_response
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Union

import numpy as np
from scipy.special import j1

import acoustic_analysis as _aa
import reflections_ism as _ism

# Las 4 caras de un tetraedro (nodos locales) y el nodo OPUESTO a cada una.
# El nodo opuesto esta en el AIRE (dentro del tet) -> orienta la normal de la
# cara de frontera hacia el dominio.
_TET_FACES = np.array([[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]], dtype=int)
_TET_OPP = np.array([0, 1, 2, 3], dtype=int)


def boundary_faces(nodes: np.ndarray, tets: np.ndarray):
    """Caras libres (de frontera) del tet-mesh: las que aparecen en UN solo
    tetraedro. Devuelve `(faces, tet_of_face)`:
      faces        (K, 3) int: triangulos (indices a `nodes`), orientados con la
                   normal apuntando HACIA EL AIRE (hacia el nodo opuesto del tet).
      tet_of_face  (K,) int: el tetraedro duenho de cada cara.
    La union de estas caras es la superficie cerrada del dominio acustico ya
    tallado (paredes externas + superficie de columnas/muebles)."""
    nodes = np.asarray(nodes, dtype=float)
    tets = np.asarray(tets, dtype=int)
    if tets.size == 0:
        return np.empty((0, 3), int), np.empty((0,), int)

    ne = len(tets)
    # (4*ne, 3) todas las caras + nodo opuesto + tet duenho, en el mismo orden.
    faces = np.concatenate([tets[:, c] for c in _TET_FACES], axis=0)
    opp = np.concatenate([tets[:, o] for o in _TET_OPP])
    tet_of = np.tile(np.arange(ne), len(_TET_FACES))

    # Una cara es de frontera si su conjunto de 3 nodos aparece una sola vez.
    key = np.sort(faces, axis=1)
    _uniq, inv, counts = np.unique(key, axis=0, return_inverse=True,
                                   return_counts=True)
    bmask = counts[inv] == 1
    bf = faces[bmask]
    bopp = opp[bmask]
    btet = tet_of[bmask]

    # Orientar: la normal debe apuntar hacia el nodo opuesto (el aire).
    p0, p1, p2 = nodes[bf[:, 0]], nodes[bf[:, 1]], nodes[bf[:, 2]]
    nrm = np.cross(p1 - p0, p2 - p0)
    cen = (p0 + p1 + p2) / 3.0
    to_air = nodes[bopp] - cen
    flip = np.einsum("ij,ij->i", nrm, to_air) < 0.0
    bf[flip] = bf[flip][:, [0, 2, 1]]     # invierte el giro -> normal al aire
    return bf, btet


def face_geometry(nodes: np.ndarray, faces: np.ndarray):
    """Centroides (K,3), normales UNITARIAS (K,3, hacia el aire si `faces` viene
    de `boundary_faces`) y areas (K,) de cada triangulo."""
    nodes = np.asarray(nodes, dtype=float)
    faces = np.asarray(faces, dtype=int)
    if faces.size == 0:
        return (np.empty((0, 3)), np.empty((0, 3)), np.empty((0,)))
    p0, p1, p2 = nodes[faces[:, 0]], nodes[faces[:, 1]], nodes[faces[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    nrm = np.zeros_like(cross)
    nz = area > 1e-15
    nrm[nz] = cross[nz] / (2.0 * area[nz, None])
    centroid = (p0 + p1 + p2) / 3.0
    return centroid, nrm, area


def _tet_volume(nodes: np.ndarray, tets: np.ndarray) -> float:
    """Volumen total del tet-mesh = suma de |det| / 6 por tetraedro. Es el V del
    dominio acustico YA TALLADO (descuenta columnas/muebles)."""
    nodes = np.asarray(nodes, float)
    tets = np.asarray(tets, int)
    if tets.size == 0:
        return 0.0
    a = nodes[tets[:, 0]]
    e1 = nodes[tets[:, 1]] - a
    e2 = nodes[tets[:, 2]] - a
    e3 = nodes[tets[:, 3]] - a
    det = np.einsum("ij,ij->i", np.cross(e1, e2), e3)
    return float(np.sum(np.abs(det)) / 6.0)


# --------------------------------------------------------------------------
# Contrato de I/O (dataclasses). El motor consume una Scene + fuente(s) +
# receptor(es) y produce (en R5) un IR de presion / FRF / metricas.
# --------------------------------------------------------------------------

AlphaSpec = Union[float, np.ndarray, Callable[[np.ndarray, np.ndarray], np.ndarray]]


@dataclass
class GeoSource:
    """Fuente del motor geometrico. `directivity` es el hueco de R4 (CLF/GLL);
    None = omni (como el nucleo modal)."""
    pos: np.ndarray
    q: float = 1.0
    directivity: Optional[object] = None

    def __post_init__(self):
        self.pos = np.asarray(self.pos, dtype=float).reshape(3)


@dataclass
class GeoReceiver:
    pos: np.ndarray

    def __post_init__(self):
        self.pos = np.asarray(self.pos, dtype=float).reshape(3)


# --------------------------------------------------------------------------
# R4 — Directividad de la fuente geometrica (vale ARRIBA de f_S; abajo la fuente
# es omni, como el nucleo modal). Interfaz comun: `gain(dirs, freqs) -> (M,B)`
# devuelve la ganancia de PRESION lineal RELATIVA al eje (1.0 en eje). El motor
# aplica la ganancia a la amplitud (coherente) y su cuadrado a la energia
# (potencia). `axis` es el eje acustico (apunta "al frente").
# --------------------------------------------------------------------------


def _unit(v):
    v = np.asarray(v, float).reshape(3)
    return v / (np.linalg.norm(v) + 1e-18)


@dataclass
class PistonDirectivity:
    """Directividad ANALITICA de un piston circular en bafle infinito:
        D(theta) = 2 J1(k a sin theta) / (k a sin theta),   0 <= theta <= pi/2
    con theta el angulo al eje acustico, k=2*pi*f/c, a el radio. El bafle no
    radia hacia atras (hemisferio trasero = 0). Resultado EXACTO (integral de
    Rayleigh del disco), sin coeficientes ajustados.

    Ref.: Kinsler, Frey et al., *Fundamentals of Acoustics*, cap. 7 (piston
    circular en bafle); Beranek, *Acustica*. Oraculo del bench: integral de
    Rayleigh numerica sobre el disco (primeros principios)."""
    a: float
    axis: np.ndarray = (1.0, 0.0, 0.0)
    c: float = 343.0

    def __post_init__(self):
        self.axis = _unit(self.axis)

    def gain(self, dirs, freqs):
        dirs = np.atleast_2d(np.asarray(dirs, float))
        dirs = dirs / (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-18)
        freqs = np.atleast_1d(np.asarray(freqs, float))
        cos_t = np.clip(dirs @ self.axis, -1.0, 1.0)              # (M,)
        sin_t = np.sqrt(np.clip(1.0 - cos_t ** 2, 0.0, 1.0))
        k = 2.0 * np.pi * freqs / self.c                           # (B,)
        x = np.outer(sin_t, k * self.a)                            # (M,B) = k a sinθ
        D = np.where(x < 1e-9, 1.0, 2.0 * j1(x) / np.where(x < 1e-9, 1.0, x))
        D = np.where(cos_t[:, None] >= 0.0, D, 0.0)                # bafle: nada atras
        return D


@dataclass
class BalloonDirectivity:
    """Directividad MEDIDA (globo) sobre una grilla esferica, interpolada. Acepta
    cualquier balloon (export CLF/GLL, medicion polar propia, o un muestreo de un
    modelo analitico): `gain_db[i,j,b]` en dB rel. al eje para la direccion
    (theta[i], phi[j]) y la banda freqs[b]. theta = angulo polar al eje (0..pi),
    phi = azimut en el plano (e1,e2) con e1 = proyeccion de `ref` perp. al eje.

    Interpolacion bilineal en (theta, phi) y lineal en log-frecuencia. Es el
    camino para 'tomar en cuenta el balloon' de una caja real sin reversear su
    binario: se le pasa el globo ya decodificado. Override de la analitica."""
    theta: np.ndarray                 # (nt,) rad, creciente
    phi: np.ndarray                   # (nph,) rad, creciente [0, 2pi)
    freqs: np.ndarray                 # (nf,) Hz, creciente
    gain_db: np.ndarray               # (nt, nph, nf) dB rel eje
    axis: np.ndarray = (1.0, 0.0, 0.0)
    ref: np.ndarray = (0.0, 0.0, 1.0)

    def __post_init__(self):
        self.theta = np.asarray(self.theta, float)
        self.phi = np.asarray(self.phi, float)
        self.freqs = np.asarray(self.freqs, float)
        self.gain_db = np.asarray(self.gain_db, float)
        # se interpola en AMPLITUD lineal (no en dB): los nulos (dB -> -inf) son
        # suaves en lineal y es lo correcto para la suma coherente de presion.
        self.gain_lin = 10.0 ** (self.gain_db / 20.0)
        self.axis = _unit(self.axis)
        e1 = np.asarray(self.ref, float) - np.dot(self.ref, self.axis) * self.axis
        self.e1 = _unit(e1)
        self.e2 = np.cross(self.axis, self.e1)

    def gain(self, dirs, freqs):
        dirs = np.atleast_2d(np.asarray(dirs, float))
        dirs = dirs / (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-18)
        freqs = np.atleast_1d(np.asarray(freqs, float))
        cos_t = np.clip(dirs @ self.axis, -1.0, 1.0)
        th = np.arccos(cos_t)                                      # (M,)
        ph = np.mod(np.arctan2(dirs @ self.e2, dirs @ self.e1), 2.0 * np.pi)
        # indices/fracciones para interpolacion bilineal en (theta, phi)
        ti = np.clip(np.searchsorted(self.theta, th) - 1, 0, len(self.theta) - 2)
        fth = (th - self.theta[ti]) / (self.theta[ti + 1] - self.theta[ti] + 1e-18)
        phw = np.concatenate([self.phi, [self.phi[0] + 2.0 * np.pi]])  # cierre ciclico
        pj = np.clip(np.searchsorted(phw, ph) - 1, 0, len(self.phi) - 1)
        pj1 = (pj + 1) % len(self.phi)
        fph = (ph - phw[pj]) / (phw[pj + 1] - phw[pj] + 1e-18)
        logf = np.log(np.clip(freqs, 1e-6, None))
        lgf = np.log(np.clip(self.freqs, 1e-6, None))

        def at(i, j):                                             # (M,B) amplitud lineal
            return np.array([np.interp(logf, lgf, self.gain_lin[i[m], j[m], :])
                             for m in range(len(i))])
        g = ((1 - fth)[:, None] * ((1 - fph)[:, None] * at(ti, pj)
                                   + fph[:, None] * at(ti, pj1))
             + fth[:, None] * ((1 - fph)[:, None] * at(ti + 1, pj)
                               + fph[:, None] * at(ti + 1, pj1)))
        return g


@dataclass
class Scene:
    """Geometria + materiales del recinto para el motor geometrico.

      nodes       (N,3) float: nodos (los del tet-mesh).
      faces       (K,3) int:   caras de frontera (de `boundary_faces`).
      centroid    (K,3), normal (K,3, al aire), area (K,): geometria por cara.
      bands       (B,):        centros de banda (octava por default).
      alpha       (K,B):       coef. de absorcion por cara y banda.
      scatter     (K,B) | None: coef. de scattering s(f) por cara (R2/R5, Q5).
      c, T, RH, P: velocidad del sonido y aire (ISO 9613-1).
      locator     FieldEvaluator | None: para test dentro/fuera (isfinite)."""
    nodes: np.ndarray
    faces: np.ndarray
    centroid: np.ndarray
    normal: np.ndarray
    area: np.ndarray
    bands: np.ndarray
    alpha: np.ndarray
    scatter: Optional[np.ndarray] = None
    c: float = 343.0
    T: float = 20.0
    RH: float = 50.0
    P: float = 101325.0
    locator: Optional[object] = field(default=None, repr=False)
    volume: Optional[float] = None       # V del dominio tallado (para Eyring/4V/S)

    @staticmethod
    def from_tet_mesh(nodes, tets, *, bands=None, alpha=0.1, scatter=None,
                      c=343.0, T=20.0, RH=50.0, P=101325.0, locator=None):
        """Arma una Scene desde el tet-mesh: extrae las caras de frontera y liga
        los materiales. `alpha`/`scatter` escalar, array (K,B) o callable
        (centroides, bands) -> (K,B)."""
        nodes = np.asarray(nodes, dtype=float)
        bands = _ism.octave_bands() if bands is None else np.asarray(bands, float)
        faces, _tet = boundary_faces(nodes, tets)
        centroid, normal, area = face_geometry(nodes, faces)
        a = _resolve_face_spec(alpha, centroid, bands)
        s = None if scatter is None else _resolve_face_spec(scatter, centroid, bands)
        vol = _tet_volume(nodes, tets)
        return Scene(nodes=nodes, faces=faces, centroid=centroid, normal=normal,
                     area=area, bands=bands, alpha=a, scatter=s,
                     c=c, T=T, RH=RH, P=P, locator=locator, volume=vol)

    @property
    def n_faces(self) -> int:
        return len(self.faces)

    def total_area(self) -> float:
        return float(np.sum(self.area))


def _resolve_face_spec(spec: AlphaSpec, centroid: np.ndarray,
                       bands: np.ndarray) -> np.ndarray:
    """Normaliza un alpha/scatter (escalar | (B,) | (K,B) | callable) a (K,B)."""
    k, b = len(centroid), len(bands)
    if callable(spec):
        out = np.asarray(spec(centroid, bands), dtype=float)
    else:
        out = np.asarray(spec, dtype=float)
    if out.ndim == 0:
        out = np.full((k, b), float(out))
    elif out.ndim == 1:
        if len(out) == b:            # por banda, igual en todas las caras
            out = np.tile(out, (k, 1))
        elif len(out) == k:          # por cara, plano en frecuencia
            out = np.tile(out[:, None], (1, b))
        else:
            raise ValueError(f"spec 1D de largo {len(out)} no es K={k} ni B={b}")
    if out.shape != (k, b):
        raise ValueError(f"spec debe resolver a (K={k}, B={b}), dio {out.shape}")
    return np.clip(out, 0.0, 0.999)


# --------------------------------------------------------------------------
# Oraculo especular (R1): reflections_ism, para shoebox.
# --------------------------------------------------------------------------

def specular_oracle_shoebox(source: GeoSource, receiver: GeoReceiver, dims,
                            alpha_by_wall, *, origin=None, bands=None,
                            max_order=3, c=343.0, T=20.0, RH=50.0, P=101325.0,
                            air=True):
    """ORACULO ESPECULAR de R1: energia especular por banda y por pared en un
    SHOEBOX, via el ISM EXACTO ya validado (`reflections_ism`, Allen & Berkley
    1979). Contra esto se contrasta el motor general de imagenes en R1. Devuelve
    el dict de `reflections_ism.wall_reflection_energy`.

    `reflections_ism` asume la caja en [0,dims]; `origin` (el vmin de la malla)
    traslada las posiciones a ese marco local. La energia es invariante al marco
    (depende de distancias y rebotes), pero los puntos de reflexion que devuelve
    quedan en el marco local (sumarles `origin` para el absoluto)."""
    o = np.zeros(3) if origin is None else np.asarray(origin, float)
    return _ism.wall_reflection_energy(
        source.pos - o, receiver.pos - o, dims, alpha_by_wall,
        bands=bands, max_order=max_order, c=c, T=T, RH=RH, P=P, air=air)


# --------------------------------------------------------------------------
# R1: metodo de imagenes con visibilidad (temprano, coherente, con fase).
# --------------------------------------------------------------------------

def _tri_verts(scene: Scene):
    """Vertices de cada cara de frontera: (K,3,3)."""
    f = scene.faces
    n = scene.nodes
    return n[f[:, 0]], n[f[:, 1]], n[f[:, 2]]


def _moller_trumbore(orig, seg, V0, V1, V2, eps=1e-9, tol=1e-7):
    """Interseccion rayo-triangulo Moller & Trumbore 1997 (vectorizada sobre K
    triangulos). `seg` = vector del segmento (b-a), asi t in (0,1) cae sobre el
    segmento. Devuelve (t (K,), hit (K,) bool). Cambio de base: resuelve
    orig + t*seg = (1-u-v)V0 + u V1 + v V2."""
    orig = np.asarray(orig, float)
    seg = np.asarray(seg, float)
    e1 = V1 - V0
    e2 = V2 - V0
    p = np.cross(seg, e2)                     # (K,3)
    det = np.einsum("kj,kj->k", e1, p)
    ok = np.abs(det) > eps
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    tvec = orig - V0                          # (K,3)
    u = np.einsum("kj,kj->k", tvec, p) * inv
    q = np.cross(tvec, e1)
    v = np.einsum("j,kj->k", seg, q) * inv
    t = np.einsum("kj,kj->k", e2, q) * inv
    hit = (ok & (u >= -tol) & (v >= -tol) & (u + v <= 1.0 + tol)
           & (t > eps) & (t < 1.0 - eps))
    return t, hit


def _segment_blocked(scene: Scene, a, b, V, exclude=None, eps=1e-9):
    """True si el segmento a->b es obstruido por alguna cara (fuera de `exclude`,
    mascara bool (K,) de caras a ignorar, p.ej. los reflectores en los extremos)."""
    V0, V1, V2 = V
    _t, hit = _moller_trumbore(a, np.asarray(b, float) - np.asarray(a, float),
                               V0, V1, V2, eps=eps)
    if exclude is not None:
        hit = hit & (~exclude)
    return bool(np.any(hit))


def _in_triangles(X, V0, V1, V2, tol=1e-6):
    """Indice del primer triangulo (entre los dados) que contiene a X (ya en su
    plano), por coordenadas baricentricas; -1 si ninguno."""
    e1 = V1 - V0
    e2 = V2 - V0
    nrm = np.cross(e1, e2)
    nn = np.einsum("kj,kj->k", nrm, nrm)
    w = np.asarray(X, float) - V0
    d00 = np.einsum("kj,kj->k", e1, e1)
    d01 = np.einsum("kj,kj->k", e1, e2)
    d11 = np.einsum("kj,kj->k", e2, e2)
    d20 = np.einsum("kj,kj->k", w, e1)
    d21 = np.einsum("kj,kj->k", w, e2)
    den = d00 * d11 - d01 * d01
    ok = np.abs(den) > 1e-18
    v = np.zeros_like(den)
    wv = np.zeros_like(den)
    v[ok] = (d11[ok] * d20[ok] - d01[ok] * d21[ok]) / den[ok]
    wv[ok] = (d00[ok] * d21[ok] - d01[ok] * d20[ok]) / den[ok]
    u = 1.0 - v - wv
    # coplanaridad + dentro del triangulo
    dist2 = (np.einsum("kj,kj->k", w, nrm) ** 2) / np.where(nn > 0, nn, 1.0)
    inside = ok & (u >= -tol) & (v >= -tol) & (wv >= -tol) & (dist2 < 1e-10)
    idx = np.where(inside)[0]
    return int(idx[0]) if len(idx) else -1


def build_reflectors(scene: Scene, round_n=4, round_d=4):
    """Agrupa las caras de frontera por PLANO (normal + offset) -> reflectores.
    Cada reflector: {"n":(3,), "d":float, "faces":(m,) indices}. En un shoebox
    da exactamente 6 (las 6 paredes). La normal apunta al aire."""
    f = scene.faces
    p0 = scene.nodes[f[:, 0]]
    nrm = scene.normal
    d = np.einsum("kj,kj->k", nrm, p0)        # offset del plano n.x = d
    keys = {}
    for i in range(len(f)):
        key = (tuple(np.round(nrm[i], round_n)), round(float(d[i]), round_d))
        keys.setdefault(key, []).append(i)
    refl = []
    for (nk, dk), idxs in keys.items():
        idxs = np.asarray(idxs, int)
        nn = scene.normal[idxs].mean(0)
        nn = nn / (np.linalg.norm(nn) + 1e-18)
        dd = float(np.einsum("j,j->", nn, scene.nodes[f[idxs[0], 0]]))
        refl.append({"n": nn, "d": dd, "faces": idxs})
    return refl


def _reflect_point(P, n, d):
    """Espejo de P respecto del plano n.x = d (n unitaria)."""
    return P - 2.0 * (float(np.dot(n, P)) - d) * n


def image_sources_general(scene: Scene, source: GeoSource, max_order=3,
                          reflectors=None, dedup=True):
    """Imagenes candidatas hasta `max_order` por reflexion recursiva sobre los
    planos reflectores, con poda 'la imagen debe estar delante del plano' y sin
    volver a reflejar por el plano inmediato. Cada candidata:
    {"pos":(3,), "order":int, "planes":[reflector_idx,...]}.

    `dedup=True` colapsa por (posicion, orden) para listar imagenes distintas
    (sirve para comparar el conjunto). `dedup=False` conserva TODAS las SECUENCIAS
    (ordenaciones de rebotes): una imagen de esquina conmuta en posicion pero solo
    una ordenacion es audible, asi que la audibilidad se decide por secuencia."""
    if reflectors is None:
        reflectors = build_reflectors(scene)
    frontier = [{"pos": source.pos.copy(), "order": 0, "planes": [], "last": -1}]
    out = []
    for order in range(1, int(max_order) + 1):
        nxt = []
        for img in frontier:
            for ri, refl in enumerate(reflectors):
                if ri == img["last"]:
                    continue
                side = float(np.dot(refl["n"], img["pos"])) - refl["d"]
                if side <= 1e-9:              # la imagen debe estar en el aire del plano
                    continue
                newpos = img["pos"] - 2.0 * side * refl["n"]
                cand = {"pos": newpos, "order": order,
                        "planes": img["planes"] + [ri], "last": ri}
                nxt.append(cand)
                out.append(cand)
        frontier = nxt
    if not dedup:
        return out, reflectors
    # dedup por posicion+orden (distintas imagenes).
    seen = set()
    uniq = []
    for im in out:
        key = (im["order"], tuple(np.round(im["pos"], 6)))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(im)
    return uniq, reflectors


def _audible_path(scene, source, receiver, image, reflectors, V):
    """Back-trace de audibilidad de una imagen. Devuelve, si es audible,
    (r_total, [face_idx por reflexion]); si no, None. Chequea que cada punto de
    reflexion caiga en la cara real del reflector y que ningun subsegmento este
    obstruido."""
    planes = image["planes"]
    n = len(planes)
    V0, V1, V2 = V
    # imagenes intermedias I_0=S .. I_n
    imgs = [source.pos.copy()]
    for ri in planes:
        imgs.append(_reflect_point(imgs[-1], reflectors[ri]["n"], reflectors[ri]["d"]))
    # back-trace: X_n .. X_1 (de receptor hacia la fuente)
    target = receiver.pos.copy()
    pts = [None] * n
    face_hit = [-1] * n
    for k in range(n, 0, -1):
        refl = reflectors[planes[k - 1]]
        a = imgs[k]
        dirv = target - a
        denom = float(np.dot(refl["n"], dirv))
        if abs(denom) < 1e-12:
            return None
        t = (refl["d"] - float(np.dot(refl["n"], a))) / denom
        if not (1e-9 < t < 1.0 - 1e-9):
            return None
        X = a + t * dirv
        fidx = refl["faces"]
        loc = _in_triangles(X, V0[fidx], V1[fidx], V2[fidx])
        if loc < 0:
            return None
        pts[k - 1] = X
        face_hit[k - 1] = int(fidx[loc])
        target = X
    # oclusion de cada subsegmento (excluye el/los reflector(es) en los extremos)
    chain = [source.pos] + pts + [receiver.pos]
    for seg_i in range(len(chain) - 1):
        a, b = chain[seg_i], chain[seg_i + 1]
        exclude = np.zeros(len(scene.faces), bool)
        if seg_i >= 1:
            exclude[reflectors[planes[seg_i - 1]]["faces"]] = True
        if seg_i <= n - 1:
            exclude[reflectors[planes[seg_i]]["faces"]] = True
        if _segment_blocked(scene, a, b, V, exclude=exclude):
            return None
    r_total = float(np.linalg.norm(imgs[n] - receiver.pos))
    return r_total, face_hit, pts[0]      # pts[0] = 1er punto de reflexion (emision)


# --------------------------------------------------------------------------
# R4 — scattering s(f) por defecto, densidad de reflexiones y mixing time.
# --------------------------------------------------------------------------


def default_scattering(bands, s_lf: float = 0.1, s_hf: float = 0.4,
                       f_knee: float = 1000.0):
    """Estimado por DEFECTO del coef. de scattering s(f) cuando no hay medicion
    ISO 17497-1. Crece con la frecuencia (las irregularidades de pared son
    grandes respecto a lambda a f alta): interpola de `s_lf` (graves) a `s_hf`
    (agudos) en log-f, con la rodilla en `f_knee`. Es un valor de INGENIERIA
    conservador, no una constante fisica: Vorlander (2011) remarca que los
    defaults de scattering son inciertos, por eso se recomienda override medido
    (ISO 17497-1) y reportar sensibilidad. Devuelve s en [0,1], shape de `bands`."""
    b = np.asarray(bands, float)
    w = np.clip(np.log(np.clip(b, 1e-6, None) / f_knee) / np.log(8.0) + 0.5, 0.0, 1.0)
    return np.clip(s_lf + (s_hf - s_lf) * w, 0.0, 1.0)


def reflection_density(V: float, t, c: float = 343.0):
    """Densidad TEMPORAL de reflexiones recibidas en un punto (Kuttruff, Room
    Acoustics 5a ed, ec. 4.6):
        dN_r/dt = 4 pi c^3 t^2 / V       [reflexiones/s]
    Crece con t^2: la respuesta pasa de reflexiones aisladas (temprano) a una
    maraña densa (cola difusa)."""
    return 4.0 * np.pi * c ** 3 * np.asarray(t, float) ** 2 / float(V)


def mixing_time(V: float, c: float = 343.0, n_crit: float = 1000.0):
    """Tiempo de mezcla (handoff imagenes->rayos): instante en que la densidad
    temporal de reflexiones (Kuttruff ec. 4.6) alcanza `n_crit` reflexiones/s.
    De 4 pi c^3 t^2 / V = n_crit:
        t_mix = sqrt( n_crit * V / (4 pi c^3) )   [s]
    Es la REGLA DE VOLUMEN (t_mix ~ sqrt(V)) derivada de primeros principios, no
    una formula ajustada. `n_crit`=1000/s es el umbral usual de solapamiento de
    reflexiones (convencion); la fisica robusta es el escalado con sqrt(V)."""
    return float(np.sqrt(n_crit * float(V) / (4.0 * np.pi * c ** 3)))


def early_reflections(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                      *, max_order: int = 3, freqs=None, reflectors=None):
    """R1: reflexiones tempranas especulares por metodo de imagenes con test de
    visibilidad sobre geometria ARBITRARIA (las caras de `scene`). Salida de
    PRESION compleja (con fase). Coef. de reflexion R(f)=sqrt(1-alpha(f)) real
    (|R|^2=1-alpha, consistente con el oraculo de energia). Aire por ISO 9613-1.

    Devuelve dict:
      bands (B,), direct {"r", "energy"(B,)}, paths [{order,r,faces,energy(B,),
      refl(B,)}], refl_energy (B,)=suma INCOHERENTE de energias (para el oraculo),
      H (B,) complex = presion total coherente (directo+reflexiones) en bands,
      y si `freqs` dada: freqs (F,), Hf (F,) complex = FRF en esa grilla.
    Allen & Berkley 1979; Vorlander, Auralization (cap. imagenes)."""
    bands = scene.bands
    nb = len(bands)
    c = scene.c
    a_air = _aa.air_absorption_alpha(bands, T=scene.T, RH=scene.RH, P=scene.P)
    V = _tri_verts(scene)
    direc = getattr(source, "directivity", None)

    def _dgain(p_from, p_to, fgrid):
        """Ganancia de presion de la fuente en la direccion de emision p_from->p_to
        evaluada en `fgrid` (1.0 si omni/degenerada)."""
        if direc is None:
            return np.ones(len(np.atleast_1d(fgrid)))
        d = np.asarray(p_to, float) - np.asarray(p_from, float)
        if np.linalg.norm(d) < 1e-12:
            return np.ones(len(np.atleast_1d(fgrid)))
        return direc.gain(d[None, :], fgrid)[0]

    # TODAS las secuencias (ordenaciones): una imagen de esquina solo es audible
    # en una ordenacion; se cuenta la imagen (posicion) UNA vez si alguna lo es.
    imgs, reflectors = image_sources_general(scene, source, max_order,
                                             reflectors, dedup=False)

    # directo
    r0 = float(np.linalg.norm(source.pos - receiver.pos))
    blocked0 = (r0 < 1e-9) or _segment_blocked(scene, source.pos, receiver.pos, V)
    e0 = np.zeros(nb)
    H = np.zeros(nb, complex)
    if not blocked0:
        amp0 = source.q / (4.0 * np.pi * r0) * np.exp(-a_air * r0) \
            * _dgain(source.pos, receiver.pos, bands)
        e0 = amp0 ** 2
        H = H + amp0 * np.exp(-1j * (2 * np.pi * bands / c) * r0)

    paths = []
    refl_energy = np.zeros(nb)
    seen = set()
    for im in imgs:
        key = tuple(np.round(im["pos"], 6))
        if key in seen:
            continue                          # imagen ya contada (otra ordenacion)
        res = _audible_path(scene, source, receiver, im, reflectors, V)
        if res is None:
            continue
        r, face_hit, emit = res
        if r < 1e-9:
            continue
        seen.add(key)
        refl = np.ones(nb)
        for fi in face_hit:
            refl = refl * np.sqrt(np.clip(1.0 - scene.alpha[fi], 0.0, 1.0))
        dgain = _dgain(source.pos, emit, bands)       # directividad en la emision
        amp = source.q / (4.0 * np.pi * r) * refl * np.exp(-a_air * r) * dgain
        e = amp ** 2
        refl_energy = refl_energy + e
        H = H + amp * np.exp(-1j * (2 * np.pi * bands / c) * r)
        paths.append({"order": int(im["order"]), "r": r,
                      "faces": [int(f) for f in face_hit],
                      "energy": e, "refl": refl, "emit": emit})

    out = {"bands": bands, "direct": {"r": r0, "energy": e0},
           "paths": paths, "refl_energy": refl_energy, "H": H,
           "n_paths": len(paths)}

    if freqs is not None:
        freqs = np.asarray(freqs, float)
        Hf = np.zeros(len(freqs), complex)
        a_air_f = _aa.air_absorption_alpha(freqs, T=scene.T, RH=scene.RH, P=scene.P)
        kf = 2 * np.pi * freqs / c
        if not blocked0:
            Hf += (source.q / (4 * np.pi * r0)) * np.exp(-a_air_f * r0) \
                * _dgain(source.pos, receiver.pos, freqs) * np.exp(-1j * kf * r0)
        for p in paths:
            # refl(f) interpolado de las bandas (alpha suave en f)
            rf = np.interp(freqs, bands, p["refl"])
            Hf += (source.q / (4 * np.pi * p["r"])) * rf \
                * np.exp(-a_air_f * p["r"]) \
                * _dgain(source.pos, p["emit"], freqs) * np.exp(-1j * kf * p["r"])
        out["freqs"] = freqs
        out["Hf"] = Hf
    return out


# --------------------------------------------------------------------------
# Contrato de la API (stubs). Cada fase del plan llena el suyo.
# --------------------------------------------------------------------------


def _nearest_face(O, D, V0, V1, V2, eps=1e-7, chunk=256):
    """Para M rayos (O,D unitaria) la cara mas cercana entre K triangulos, via
    Moller-Trumbore con t = distancia a lo largo de D (rayo, no segmento).
    Devuelve (t (M,) dist al choque, inf si ninguno; fidx (M,) indice, -1)."""
    O = np.asarray(O, float); D = np.asarray(D, float)
    M, K = len(O), len(V0)
    e1 = V1 - V0; e2 = V2 - V0                              # (K,3)
    t_out = np.full(M, np.inf); f_out = np.full(M, -1, int)
    for s0 in range(0, M, chunk):
        Oc = O[s0:s0 + chunk]; Dc = D[s0:s0 + chunk]        # (m,3)
        p = np.cross(Dc[:, None, :], e2[None, :, :])        # (m,K,3)
        det = np.einsum("mkj,kj->mk", p, e1)                # (m,K)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tvec = Oc[:, None, :] - V0[None, :, :]              # (m,K,3)
        u = np.einsum("mkj,mkj->mk", tvec, p) * inv
        q = np.cross(tvec, e1[None, :, :])                  # (m,K,3)
        v = np.einsum("mj,mkj->mk", Dc, q) * inv
        t = np.einsum("kj,mkj->mk", e2, q) * inv
        hit = (ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1.0 + 1e-6) & (t > eps))
        tt = np.where(hit, t, np.inf)
        j = np.argmin(tt, axis=1)
        tmin = tt[np.arange(len(j)), j]
        got = np.isfinite(tmin)
        sl = slice(s0, s0 + len(j))
        t_out[sl][got] = tmin[got]
        f_out[sl][got] = j[got]
    return t_out, f_out


def _lambert_dirs(normals, rng):
    """Direcciones difusas por la ley del coseno de Lambert (Kuttruff ec 9.21-9.22):
    cos(theta)=sqrt(z1) alrededor de la normal `n` (al aire), phi=2*pi*z2. Vectorizado."""
    n = np.asarray(normals, float)
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-18)
    m = len(n)
    z1 = rng.random(m); z2 = rng.random(m)
    ct = np.sqrt(z1); st = np.sqrt(np.clip(1.0 - z1, 0.0, 1.0)); ph = 2 * np.pi * z2
    a = np.tile(np.array([1.0, 0.0, 0.0]), (m, 1))
    alt = np.abs(n[:, 0]) > 0.9
    a[alt] = np.array([0.0, 1.0, 0.0])
    t1 = np.cross(a, n); t1 /= (np.linalg.norm(t1, axis=1, keepdims=True) + 1e-18)
    t2 = np.cross(n, t1)
    return (st * np.cos(ph))[:, None] * t1 + (st * np.sin(ph))[:, None] * t2 \
        + ct[:, None] * n


def diffuse_tail(scene: Scene, source: GeoSource, receiver: GeoReceiver = None,
                 *, n_rays: int = 3000, dt: float = 0.005, t_max: float = 1.5,
                 seed: int = 0, max_refl: int = 400, e_min: float = 1e-7,
                 bands=None, chunk: int = 256, air: bool = True):
    """R2: cola difusa por TRAZADO ESTOCASTICO DE RAYOS (Kuttruff, Room Acoustics
    5a ed, Cap. 9.8). N particulas de IGUAL energia emitidas isotropas desde la
    fuente; en cada choque con una cara real del dominio (Moller-Trumbore 1997):

      - reparto especular/difuso por el scattering s(f) (Q5): se sortea z3~U[0,1];
        z3 <= s -> reflexion DIFUSA por Lambert (ec 9.21-9.22), si no ESPECULAR
        (theta_r=theta_i, Fig 9.14). s=None -> todo especular.
      - absorcion de pared: energia *= (1 - alpha(f))  (ec 9.24, rho=1-alpha).
      - aire: energia *= exp(-m*d) por segmento, m = 2*alpha_aire (ISO 9613-1).

    La energia que llega a cada reflexion se histograma por tiempo de vuelo ->
    ENVOLVENTE DE ENERGIA por banda w[b, t] (respuesta impulsiva energetica,
    Fig 9.15). En campo difuso la densidad de energia es uniforme en el espacio
    (Kuttruff 5.1), por eso esta envolvente es la COLA en cualquier receptor; el
    temprano dependiente de posicion lo da R1. `receiver` se acepta por uniformidad
    de API (la cola difusa no depende de su posicion).

    Oraculo (bench_geometric_r2): camino libre medio 4V/S (ec 5.12) + decaimiento
    de Eyring T=-24V*ln10/(c*S*ln(1-alpha)) (ec 5.22/5.23) + conservacion (alpha=0).

    Devuelve dict: t (n_bins,), bands (Bsel,), w (Bsel, n_bins) energia>=0,
    mean_free_path (float, reflexiones>=1), dt, n_rays."""
    V0, V1, V2 = _tri_verts(scene)
    nrm = scene.normal
    allbands = scene.bands
    if bands is None:
        band_idx = np.arange(len(allbands))
    else:
        band_idx = np.array([int(np.argmin(np.abs(allbands - b)))
                             for b in np.atleast_1d(bands)], int)
    c = scene.c
    n_bins = int(np.ceil(t_max / dt))
    tcent = (np.arange(n_bins) + 0.5) * dt
    w = np.zeros((len(band_idx), n_bins))
    seg_all = []
    e0 = float(source.q) / n_rays
    direc = getattr(source, "directivity", None)
    n_spec = 0; n_diff = 0                       # conteo de reflexiones por tipo (Q5)

    for bi, b in enumerate(band_idx):
        rng = np.random.default_rng(int(seed) + 1000 * int(b))
        a_b = scene.alpha[:, b]                               # (K,)
        s_b = None if scene.scatter is None else scene.scatter[:, b]
        m_b = (2.0 * float(_aa.air_absorption_alpha(
            allbands[b], T=scene.T, RH=scene.RH, P=scene.P)) if air else 0.0)
        # emision isotropa desde la fuente (uniforme en la esfera).
        u = rng.random(n_rays); v = rng.random(n_rays)
        ct = 1.0 - 2.0 * u; st = np.sqrt(np.clip(1.0 - ct * ct, 0.0, 1.0))
        ph = 2.0 * np.pi * v
        D = np.column_stack([st * np.cos(ph), st * np.sin(ph), ct])
        O = np.tile(source.pos, (n_rays, 1)).astype(float)
        if direc is None:
            e = np.full(n_rays, e0)
        else:
            # pesar la energia emitida por la POTENCIA direccional D(dir)^2 y
            # renormalizar: conserva la potencia total q, moldeando su reparto.
            Gb = direc.gain(D, [allbands[b]])[:, 0] ** 2
            Gb = Gb * (n_rays / max(float(Gb.sum()), 1e-30))
            e = e0 * Gb
        tof = np.zeros(n_rays)
        alive = np.ones(n_rays, bool)

        for it in range(max_refl):
            if not alive.any():
                break
            idx = np.where(alive)[0]
            tlen, fj = _nearest_face(O[idx], D[idx], V0, V1, V2, chunk=chunk)
            good = fj >= 0
            alive[idx[~good]] = False                        # sin choque (numerico)
            idx = idx[good]; tlen = tlen[good]; fj = fj[good]
            if len(idx) == 0:
                continue
            t1 = tof[idx] + tlen / c
            e_arr = e[idx] * np.exp(-m_b * tlen)             # energia al llegar a la pared
            # histograma de energia por tiempo de llegada (RIR energetica, Fig 9.15)
            bins = (t1 / dt).astype(int)
            okb = bins < n_bins
            np.add.at(w[bi], bins[okb], e_arr[okb])
            if it >= 1:                                      # camino libre pared-pared
                seg_all.append(tlen)
            # punto de choque y reflexion
            P = O[idx] + tlen[:, None] * D[idx]
            nf = nrm[fj]
            z = rng.random(len(idx))
            diffuse = np.zeros(len(idx), bool) if s_b is None else (z < s_b[fj])
            n_diff += int(diffuse.sum()); n_spec += int((~diffuse).sum())
            Dnew = np.empty_like(P)
            sp = ~diffuse
            if sp.any():
                d = D[idx][sp]; nn = nf[sp]
                Dnew[sp] = d - 2.0 * np.einsum("ij,ij->i", d, nn)[:, None] * nn
            if diffuse.any():
                Dnew[diffuse] = _lambert_dirs(nf[diffuse], rng)
            Dnew /= (np.linalg.norm(Dnew, axis=1, keepdims=True) + 1e-18)
            # avanzar el estado de las particulas vivas
            O[idx] = P + 1e-7 * nf                           # despegar de la cara
            D[idx] = Dnew
            e[idx] = e_arr * (1.0 - a_b[fj])
            tof[idx] = t1
            dead = (e[idx] < e_min) | (t1 >= t_max)
            alive[idx[dead]] = False

    out = {"t": tcent, "bands": allbands[band_idx], "w": w, "dt": dt,
           "mean_free_path": (float(np.mean(np.concatenate(seg_all)))
                              if seg_all else float("nan")),
           "n_rays": int(n_rays), "n_spec": n_spec, "n_diff": n_diff,
           "diffuse_frac": (n_diff / max(n_spec + n_diff, 1))}
    return out


# --------------------------------------------------------------------------
# R6: respuesta de ENERGIA compuesta (temprano por imagenes + cola difusa) con
# CONTINUIDAD de densidad de energia en el mixing time (normalizacion del
# detector). Habilita parametros ISO 3382-1 por energia (C80, D50, EDT, Ts).
# --------------------------------------------------------------------------

def _energy_params(g, tc, kd, dt):
    """Parametros ISO 3382-1 desde la ENVOLVENTE DE ENERGIA g(t) (ya en unidades
    de energia recibida por bin), con el directo en el bin kd:
      EDT  tiempo de decaimiento inicial (EDC de Schroeder, 0..-10 dB x6).
      C80  claridad 10 log10( E[0,80ms] / E[80ms,inf] ) desde el directo (ISO 3382-1).
      D50  definicion E[0,50ms]/E[0,inf].
      Ts   tiempo central sum((t-t0) g)/sum(g)."""
    g = np.asarray(g, float)
    n = len(g)
    e_tot = g[kd:].sum()
    if e_tot <= 0:
        return dict(EDT=np.nan, C80=np.nan, D50=np.nan, Ts=np.nan, r2=0.0)
    k80 = kd + int(round(0.080 / dt))
    k50 = kd + int(round(0.050 / dt))
    e_early80 = g[kd:k80].sum(); e_late80 = g[k80:].sum()
    C80 = 10.0 * np.log10(e_early80 / e_late80) if e_late80 > 0 else np.inf
    D50 = float(g[kd:k50].sum() / e_tot)
    t0 = tc[kd]
    Ts = float(((tc[kd:] - t0) * g[kd:]).sum() / e_tot)
    # EDT por EDC de Schroeder (integral hacia atras), pendiente 0..-10 dB
    edc = np.cumsum(g[kd:][::-1])[::-1]
    edc = edc / max(edc[0], 1e-30)
    L = 10.0 * np.log10(np.maximum(edc, 1e-12))
    t = (np.arange(len(L))) * dt
    sel = (L <= 0.0) & (L >= -10.0)
    EDT = r2 = np.nan
    if sel.sum() >= 3:
        A = np.polyfit(t[sel], L[sel], 1)
        EDT = -60.0 / A[0]
        fit = np.polyval(A, t[sel]); ss = np.sum((L[sel] - L[sel].mean()) ** 2)
        r2 = 1.0 - np.sum((L[sel] - fit) ** 2) / max(ss, 1e-30)
    return dict(EDT=float(EDT), C80=float(C80), D50=D50, Ts=Ts, r2=float(r2))


def composed_energy_response(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                             *, fc, n_rays: int = 8000, dt: float = 0.001,
                             t_max: float = None, max_refl: int = 1200,
                             air: bool = True, seed: int = 5, reflectors=None,
                             early_specular: bool = False, max_order: int = 3,
                             tail: dict = None):
    """R6: envolvente de ENERGIA recibida en un receptor = DIRECTO (exacto,
    posicion-dependiente) + COLA DIFUSA (trazado estocastico R2, que ya trae TODA
    la energia reflejada desde el 1er rebote). De aqui salen los parametros ISO
    3382-1 por energia (C80, D50, EDT, Ts).

    ESCALA ABSOLUTA del detector (ANALITICA, no ajustada). El directo esta en
    PRESION^2 en el punto, e_dir=[q/(4pi r)]^2. La cola w(t) es el FLUJO de energia
    en pared (total q/alpha por conservacion exacta); su densidad de energia es
    w_dens=4 w/(c S dt) por la irradiancia difusa I=c w/4 (Kuttruff, Room Acoustics
    5a ed, cap. 9.8), y la presion^2 recibida es p^2=c^2 w_dens (campo difuso).
    Reconciliando la ENERGIA RADIADA de la fuente puntual (q^2/4pi c) con la energia
    q que emite la cola, la cola en unidades de p^2 recibido por bin es

        g_tail[bin] = (q / (pi S)) * w[bin]

    un factor GLOBAL (solo fuente y area S, no el receptor). No hay ajuste ni pin.

    ORACULO de la escala (bench_geometric_r6): con esta normalizacion la DISTANCIA
    CRITICA (directo=reverberante) sale r_c = sqrt(S alpha / 16 pi) = sqrt(A/16pi),
    el radio clasico (Kuttruff ec. 4.9; Kinsler, Fundamentals of Acoustics). q y r
    se cancelan: es una propiedad del recinto, no del ajuste.

    `early_specular=True` ADEMAS inserta las reflexiones tempranas especulares
    (imagenes, R1) hasta t_mix para la estructura posicion-dependiente (coloracion,
    util para el FRF R5); por default False, porque para la ENERGIA la cola ya las
    contiene (sumarlas duplicaria). Vorlander, Auralization (empalme hibrido).
    `tail` reusa una diffuse_tail ya calculada (independiente del receptor) para
    evaluar muchos mics con una sola corrida de la cola.

    Devuelve dict: t (n_bins,), g (energia recibida por bin), g_direct, g_tail,
    scale (q/pi S), t_mix, kd (bin del directo), bi, fc, y C80/D50/EDT/Ts/r2."""
    bands = np.asarray(scene.bands, float)
    bi = int(np.argmin(np.abs(bands - float(fc))))
    c = scene.c; V = float(scene.volume); S = float(scene.total_area())
    t_mix = mixing_time(V, c=c)

    # --- cola (R2): flujo de pared -> p^2 recibido por bin (escala analitica).
    # `tail` reusa una diffuse_tail ya calculada (es INDEPENDIENTE del receptor),
    # util para evaluar muchos mics con una sola corrida de la cola. ---
    if tail is None:
        if t_max is None:
            aw = float(np.clip(np.average(scene.alpha[:, bi], weights=scene.area),
                               1e-3, 0.99))
            rt = 24.0 * np.log(10.0) * V / (c * (-S * np.log(1.0 - aw)))
            t_max = max(1.5 * rt, 4.0 * t_mix)
        tail = diffuse_tail(scene, source, n_rays=n_rays, dt=dt, t_max=t_max,
                            max_refl=max_refl, e_min=1e-12, bands=[float(fc)],
                            air=air, seed=seed)
    dt = float(tail["dt"]); w0 = tail["w"][0]; n_bins = len(w0)
    tc = tail["t"]
    s = float(source.q) / (np.pi * S)             # normalizacion del detector (global)
    g_tail = s * w0

    # --- directo (exacto, posicion-dependiente): e_dir=[q/4pi r]^2 con bloqueo ---
    er = early_reflections(scene, source, receiver,
                           max_order=(max_order if early_specular else 1),
                           reflectors=reflectors)
    g_dir = np.zeros(n_bins)
    r_dir = float(er["direct"]["r"]); e_dir = float(er["direct"]["energy"][bi])
    kd = int((r_dir / c) / dt)
    if 0 <= kd < n_bins:
        g_dir[kd] += e_dir

    g = g_dir + g_tail
    if early_specular:
        # reemplazar la aproximacion difusa del tail en [0, t_mix] por las
        # reflexiones especulares por imagenes (posicion-dependiente), crossfade.
        hi = min(int(t_mix / dt), n_bins)
        g_sp = np.zeros(n_bins)
        for p in er["paths"]:
            k = int((p["r"] / c) / dt)
            if kd < k < hi:
                g_sp[k] += float(p["energy"][bi])
        if hi > kd + 1:
            a = np.linspace(0.0, 1.0, hi - kd - 1)
            g[kd + 1:hi] = (1.0 - a) * g_sp[kd + 1:hi] + a * g_tail[kd + 1:hi]

    par = _energy_params(g, tc, kd, dt)
    out = {"t": tc, "g": g, "g_direct": g_dir, "g_tail": g_tail, "scale": s,
           "t_mix": float(t_mix), "kd": int(kd), "bi": bi, "fc": float(fc),
           "mean_free_path": float(tail["mean_free_path"])}
    out.update(par)
    return out


# --------------------------------------------------------------------------
# R3: difraccion de bordes BTM (Biot-Tolstoy-Medwin), coherente, 1er orden.
# Formulacion de linea-integral de Svensson et al. 1999, segun Calamia &
# Svensson 2007 (ecs. 2-4) y Calamia 2009 tesis (ecs. 3.14, 3.15, 3.16).
# Coords cilindricas al borde: r = distancia perpendicular, theta medido desde
# una cara de la cuna (por el AIRE), z a lo largo del borde. nu = pi/theta_W.
# --------------------------------------------------------------------------

def _btm_beta_sum(nu, thS, thR, eta):
    """Suma de los cuatro beta_i del BTM (Calamia&Svensson 2007 ec. 3):
    beta_i = sin(nu*phi_i)/(cosh(nu*eta) - cos(nu*phi_i)), phi_i = pi +- thS +- thR.
    `eta` escalar o array -> devuelve la suma con la misma forma."""
    che = np.cosh(nu * np.asarray(eta, float))
    out = np.zeros_like(che)
    for s1 in (1.0, -1.0):
        for s2 in (1.0, -1.0):
            phi = np.pi + s1 * thS + s2 * thR
            out = out + np.sin(nu * phi) / (che - np.cos(nu * phi))
    return out


def btm_edge_H_finite(rS, thS, zS, rR, thR, zR, thW, z1, z2, freqs,
                      c=343.0, n_pts=2001):
    """H_diffr(omega) de un borde FINITO por la linea-integral BTM en frecuencia
    (Calamia 2009 ec. 3.14):
        H = -(nu/4pi) sum_i int_{z1}^{z2} exp(-jk(m+l)) beta_i/(m l) dz,
    con m=sqrt(rS^2+(z-zS)^2), l=sqrt(rR^2+(z-zR)^2),
    eta(z)=arccosh{[m l+(z-zS)(z-zR)]/(rS rR)} (ec. 3.10). Convencion e^{-jkr}
    (como R1). Integracion de Simpson sobre una grilla densa en z."""
    freqs = np.atleast_1d(np.asarray(freqs, float))
    k = 2.0 * np.pi * freqs / c
    nu = np.pi / thW
    z = np.linspace(z1, z2, int(n_pts))
    m = np.sqrt(rS * rS + (z - zS) ** 2)
    l = np.sqrt(rR * rR + (z - zR) ** 2)
    arg = (m * l + (z - zS) * (z - zR)) / (rS * rR)
    eta = np.arccosh(np.maximum(arg, 1.0))
    beta = _btm_beta_sum(nu, thS, thR, eta)        # (n_pts,)
    base = beta / (m * l)                           # (n_pts,)
    phase = np.exp(-1j * np.outer(k, (m + l)))      # (nf, n_pts)
    integ = phase * base[None, :]                   # (nf, n_pts)
    from scipy.integrate import simpson
    H = simpson(integ, x=z, axis=1)
    return -(nu / (4.0 * np.pi)) * H


def btm_edge_H_infinite(rS, thS, zS, rR, thR, zR, thW, freqs,
                        c=343.0, eta_max=50.0, n_pts=16001):
    """ORACULO EXACTO: H_diffr de un borde INFINITO por la integral de contorno
    de Bowman & Senior / Pierce (Calamia 2009 ec. 3.15/3.16), derivacion
    INDEPENDIENTE de la linea-integral:
        H_ref = -2(nu/4pi) sum_i int_0^inf exp(-jk R_ref)/R_ref * beta_i d eta,
        R_ref = sqrt(rS^2 + rR^2 + (zR-zS)^2 + 2 rS rR cosh(eta)).
    El integrando decae ~ e^{-nu*eta}/R_ref -> se trunca en eta_max."""
    freqs = np.atleast_1d(np.asarray(freqs, float))
    k = 2.0 * np.pi * freqs / c
    nu = np.pi / thW
    eta = np.linspace(0.0, eta_max, int(n_pts))
    Rref = np.sqrt(rS * rS + rR * rR + (zR - zS) ** 2 + 2.0 * rS * rR * np.cosh(eta))
    beta = _btm_beta_sum(nu, thS, thR, eta)
    base = beta / Rref
    phase = np.exp(-1j * np.outer(k, Rref))
    integ = phase * base[None, :]
    from scipy.integrate import simpson
    H = simpson(integ, x=eta, axis=1)
    return -2.0 * (nu / (4.0 * np.pi)) * H


def _perp(vec, axis):
    """Componente de `vec` perpendicular a `axis` (unitaria), por fila si 2D."""
    axis = np.asarray(axis, float)
    axis = axis / (np.linalg.norm(axis) + 1e-18)
    vec = np.asarray(vec, float)
    return vec - np.dot(vec, axis) * axis


def wedge_coords(edge_A, edge_B, face_a_cen, face_a_nrm, face_b_cen, P):
    """Coords cilindricas (r, theta, z) de un punto P respecto de un borde recto
    A->B, y el angulo de cuna theta_W (del AIRE). La cara A (centroide face_a_cen,
    normal al aire face_a_nrm) fija theta=0; theta crece por el aire hacia la
    cara B. Devuelve (r, theta, z, thW, L) con z,L sobre el eje del borde (z=0 en A)."""
    A = np.asarray(edge_A, float); B = np.asarray(edge_B, float)
    zhat = B - A
    L = float(np.linalg.norm(zhat))
    zhat = zhat / (L + 1e-18)
    # base en el plano perpendicular: e1 = direccion de la cara A (hacia su centro),
    # e2 = normal al aire de la cara A (ambas perp al borde).
    e1 = _perp(np.asarray(face_a_cen, float) - A, zhat)
    e1 = e1 / (np.linalg.norm(e1) + 1e-18)
    e2 = _perp(np.asarray(face_a_nrm, float), zhat)
    e2 = e2 / (np.linalg.norm(e2) + 1e-18)
    # angulo de la cara B (hacia su centro) por el aire -> theta_W
    ub = _perp(np.asarray(face_b_cen, float) - A, zhat)
    ub = ub / (np.linalg.norm(ub) + 1e-18)
    thW = np.arctan2(np.dot(ub, e2), np.dot(ub, e1))
    if thW <= 1e-9:
        thW += 2.0 * np.pi
    # coords de P
    d = np.asarray(P, float) - A
    zc = float(np.dot(d, zhat))
    dp = _perp(d, zhat)
    r = float(np.linalg.norm(dp))
    th = np.arctan2(np.dot(dp, e2), np.dot(dp, e1))
    if th < 0:
        th += 2.0 * np.pi
    return r, th, zc, thW, L


def build_edges(scene: Scene, round_dir=3, round_pos=3, min_len=1e-3):
    """Bordes geometricos del dominio: aristas de la malla compartidas por DOS
    caras de frontera NO coplanares, fusionadas por recta (direccion + punto).
    Cada borde: {"A","B","dir","thW","nu","face_a","face_b"}. thW=pi (caras
    coplanares, pared plana) se descarta (no hay borde). thW=pi/m entero no
    difracta (Bowman); se marca via nu pero se conserva para inspeccion."""
    f = scene.faces
    cen, nrm = scene.centroid, scene.normal
    # mapa arista(nodos ordenados) -> [caras]
    emap = {}
    for fi in range(len(f)):
        a, b, c = f[fi]
        for e in ((a, b), (b, c), (a, c)):
            key = (int(min(e)), int(max(e)))
            emap.setdefault(key, []).append(fi)
    # agrupar aristas colineales (misma recta) con mismo par de caras-tipo
    groups = {}
    for (i, j), fl in emap.items():
        if len(fl) != 2:
            continue
        pA, pB = scene.nodes[i], scene.nodes[j]
        d = pB - pA
        Ld = np.linalg.norm(d)
        if Ld < min_len:
            continue
        d = d / Ld
        # orientacion canonica de la direccion
        if (d[0], d[1], d[2]) < (-d[0], -d[1], -d[2]):
            d = -d
        # ¿coplanares? normales casi paralelas -> no es borde
        na, nb = nrm[fl[0]], nrm[fl[1]]
        if abs(float(np.dot(na, nb))) > 0.9999:
            continue
        # punto de la recta (perp al origen) para la clave
        foot = pA - np.dot(pA, d) * d
        key = (tuple(np.round(d, round_dir)), tuple(np.round(foot, round_pos)))
        groups.setdefault(key, {"pts": [], "faces": fl})
        groups[key]["pts"] += [pA, pB]
        groups[key]["faces"] = fl
    edges = []
    for (dk, _fk), g in groups.items():
        pts = np.array(g["pts"])
        d = np.array(dk, float); d = d / (np.linalg.norm(d) + 1e-18)
        t = pts @ d
        A = pts[np.argmin(t)]; B = pts[np.argmax(t)]
        fa, fb = g["faces"]
        r, th, z, thW, L = wedge_coords(A, B, cen[fa], nrm[fa], cen[fb], A + (B - A))
        if abs(thW - np.pi) < 1e-3:
            continue
        edges.append({"A": A, "B": B, "dir": d, "thW": float(thW),
                      "nu": float(np.pi / thW), "face_a": int(fa), "face_b": int(fb)})
    return edges


def edge_diffraction(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                     *, freqs, order: int = 1, edges=None):
    """R3: difraccion de bordes BTM de 1er orden (coherente, con fase). Suma
    H_diffr(omega) sobre los bordes difractantes del dominio (Svensson et al.
    1999; Calamia 2009 ec. 3.14). `order` reservado (2do orden futuro, Q4).
    Devuelve dict: freqs, H (suma, compleja), per_edge [{thW, H}]."""
    if int(order) != 1:
        raise NotImplementedError("R3: por ahora solo 1er orden (Q4)")
    if edges is None:
        edges = build_edges(scene)
    freqs = np.atleast_1d(np.asarray(freqs, float))
    cen, nrm = scene.centroid, scene.normal
    H = np.zeros(len(freqs), complex)
    per = []
    for ed in edges:
        rS, thS, zS, thW, L = wedge_coords(ed["A"], ed["B"], cen[ed["face_a"]],
                                           nrm[ed["face_a"]], cen[ed["face_b"]],
                                           source.pos)
        rR, thR, zR, _thW, _L = wedge_coords(ed["A"], ed["B"], cen[ed["face_a"]],
                                             nrm[ed["face_a"]], cen[ed["face_b"]],
                                             receiver.pos)
        He = btm_edge_H_finite(rS, thS, zS, rR, thR, zR, thW, 0.0, L, freqs,
                               c=scene.c)
        H = H + He
        per.append({"thW": thW, "H": He})
    return {"freqs": freqs, "H": H, "per_edge": per, "n_edges": len(edges)}


def lr_crossover(freqs, f_cross: float, order: int = 4):
    """Pesos de crossover complementario Linkwitz-Riley en f_cross.

    w_lo(f) = 1 / (1 + (f/f_cross)^order),  w_hi(f) = 1 - w_lo(f).

    Para LR de orden par n (order=n), el modulo del pasa-bajos LR es
    |LP| = 1/(1+u^order) y el del pasa-altos |HP| = u^order/(1+u^order) con
    u=f/f_cross (LR = dos Butterworth de orden n/2 en cascada, |B|=1/sqrt(1+u^n)
    al cuadrado). Por construccion w_lo+w_hi=1 EXACTO (particion de unidad): donde
    FEM y geometrico coinciden, el hibrido los reproduce sin distorsion de modulo
    ni de fase. En f_cross ambos valen 1/2 (-6 dB, cruce LR) y la pendiente
    asintotica es 6*order dB/oct (order=4 -> 24 dB/oct).
    Ref.: Linkwitz, JAES 1976 'Active Crossover Networks for Noncoincident
    Drivers'; D'Appolito, 'Testing Loudspeakers'."""
    freqs = np.atleast_1d(np.asarray(freqs, float))
    if f_cross <= 0:
        return np.ones_like(freqs), np.zeros_like(freqs)
    u = freqs / float(f_cross)
    w_lo = 1.0 / (1.0 + u ** int(order))
    return w_lo, 1.0 - w_lo


def geometric_frf(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                  *, freqs, max_order: int = 3, include_diffraction: bool = False,
                  reflectors=None, edges=None):
    """FRF geometrica COHERENTE (presion compleja, con fase) en `freqs`:
    directo + reflexiones tempranas (R1) [+ difraccion de bordes BTM (R3) si
    include_diffraction]. La cola difusa (R2) es energia con fase aleatoria y NO
    se suma coherentemente aca (se maneja aparte en metricas de energia)."""
    freqs = np.atleast_1d(np.asarray(freqs, float))
    er = early_reflections(scene, source, receiver, max_order=max_order,
                           freqs=freqs, reflectors=reflectors)
    H = er["Hf"].copy()
    if include_diffraction:
        dif = edge_diffraction(scene, source, receiver, freqs=freqs, edges=edges)
        H = H + dif["H"]
    return H, er


def hybrid_response(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                    *, freqs=None, fem_frf=None, f_schroeder: float = 0.0,
                    lr_order: int = 4, max_order: int = 3,
                    include_diffraction: bool = False, h_geo=None):
    """R5: empalme hibrido en f_S del FEM (<f_S) con el geometrico (>f_S) por
    crossover complementario Linkwitz-Riley -> FRF de presion de banda completa.

    H_hib(f) = w_lo(f) * H_FEM(f) + w_hi(f) * H_geo(f),  w_lo+w_hi=1.

    `fem_frf` = FRF modal del nucleo (compleja, alineada a `freqs`); si None, el
    peso bajo es 0 (sale el geometrico puro). `h_geo` permite inyectar una FRF
    geometrica ya calculada (si None se arma con geometric_frf). Oraculo:
    continuidad/transparencia de la FRF en f_S + limites (abajo->FEM, arriba->geo)
    + end-to-end vs medicion (JND; Vorlander 2011, Rindel et al. 1999)."""
    if freqs is None:
        raise ValueError("hybrid_response requiere la grilla `freqs`")
    freqs = np.atleast_1d(np.asarray(freqs, float))
    if h_geo is None:
        h_geo, er = geometric_frf(scene, source, receiver, freqs=freqs,
                                  max_order=max_order,
                                  include_diffraction=include_diffraction)
    else:
        h_geo, er = np.asarray(h_geo, complex), None
    w_lo, w_hi = lr_crossover(freqs, f_schroeder, lr_order)
    if fem_frf is None:
        h_fem = np.zeros(len(freqs), complex)
        w_lo = np.zeros_like(w_lo)
        w_hi = np.ones_like(w_hi)
    else:
        h_fem = np.asarray(fem_frf, complex)
    H = w_lo * h_fem + w_hi * h_geo
    return {"freqs": freqs, "H": H, "H_fem": h_fem, "H_geo": h_geo,
            "w_lo": w_lo, "w_hi": w_hi, "f_schroeder": float(f_schroeder),
            "lr_order": int(lr_order), "early": er}
