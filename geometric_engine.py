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
    return r_total, face_hit


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
        amp0 = source.q / (4.0 * np.pi * r0) * np.exp(-a_air * r0)
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
        r, face_hit = res
        if r < 1e-9:
            continue
        seen.add(key)
        refl = np.ones(nb)
        for fi in face_hit:
            refl = refl * np.sqrt(np.clip(1.0 - scene.alpha[fi], 0.0, 1.0))
        amp = source.q / (4.0 * np.pi * r) * refl * np.exp(-a_air * r)
        e = amp ** 2
        refl_energy = refl_energy + e
        H = H + amp * np.exp(-1j * (2 * np.pi * bands / c) * r)
        paths.append({"order": int(im["order"]), "r": r,
                      "faces": [int(f) for f in face_hit],
                      "energy": e, "refl": refl})

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
                * np.exp(-1j * kf * r0)
        for p in paths:
            # refl(f) interpolado de las bandas (alpha suave en f)
            rf = np.interp(freqs, bands, p["refl"])
            Hf += (source.q / (4 * np.pi * p["r"])) * rf \
                * np.exp(-a_air_f * p["r"]) * np.exp(-1j * kf * p["r"])
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
        e = np.full(n_rays, e0)
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
           "n_rays": int(n_rays)}
    return out


def edge_diffraction(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                     *, order: int = 1):
    """R3: difraccion de bordes BTM (fuentes secundarias coherentes) de 1er
    orden en bordes visibles (2do opcional). Oraculo: cuna exacta de Morse &
    Ingard + casos de Calamia."""
    raise NotImplementedError("R3: edge_diffraction (BTM)")


def hybrid_response(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                    *, fem_frf=None, f_schroeder: float = 0.0):
    """R5: empalme hibrido en f_S (crossover complementario tipo Linkwitz-Riley)
    del FEM (<f_S) con el geometrico (>f_S) -> IR de presion / FRF / metricas de
    banda completa. Oraculo: continuidad de la FRF en f_S + end-to-end vs
    medicion (JND)."""
    raise NotImplementedError("R5: hybrid_response (empalme en f_S)")
