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
        return Scene(nodes=nodes, faces=faces, centroid=centroid, normal=normal,
                     area=area, bands=bands, alpha=a, scatter=s,
                     c=c, T=T, RH=RH, P=P, locator=locator)

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
                            alpha_by_wall, *, bands=None, max_order=3,
                            c=343.0, T=20.0, RH=50.0, P=101325.0, air=True):
    """ORACULO ESPECULAR de R1: energia especular por banda y por pared en un
    SHOEBOX, via el ISM EXACTO ya validado (`reflections_ism`, Allen & Berkley
    1979). Contra esto se contrasta el motor general de imagenes en R1. Devuelve
    el dict de `reflections_ism.wall_reflection_energy`."""
    return _ism.wall_reflection_energy(
        source.pos, receiver.pos, dims, alpha_by_wall,
        bands=bands, max_order=max_order, c=c, T=T, RH=RH, P=P, air=air)


# --------------------------------------------------------------------------
# Contrato de la API (stubs). Cada fase del plan llena el suyo.
# --------------------------------------------------------------------------

def early_reflections(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                      *, max_order: int = 3):
    """R1: reflexiones tempranas especulares (metodo de imagenes con test de
    visibilidad sobre geometria arbitraria). IR de presion COMPLEJO (con fase).
    Oraculo: `specular_oracle_shoebox` en shoebox (EXACTO) + continuidad."""
    raise NotImplementedError("R1: early_reflections (imagenes con visibilidad)")


def diffuse_tail(scene: Scene, source: GeoSource, receiver: GeoReceiver,
                 *, n_rays: int = 20000):
    """R2: cola difusa (trazado estocastico de rayos Moller-Trumbore, histograma
    de energia; scattering ISO 17497 reparte especular/difuso, Lambert).
    Oraculo: radiosidad (Nosal) + Sabine/Eyring + conservacion de energia."""
    raise NotImplementedError("R2: diffuse_tail (trazado de rayos)")


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
