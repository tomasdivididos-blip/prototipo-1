"""
acoustic_analysis.py
====================

Orquestador de alto nivel para el modulo acustico. Coordina:

    geometry -> superficie -> malla volumetrica -> solver modal FEM
                                                          |
                                                          v
                                       resultados de modos, FRFs, campos

Resultados se devuelven empaquetados en dataclasses (ModalSolution,
FRFResult, FieldSlice) listos para usar en la UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
import numpy as np

from sources import SourceArray, OmniSource, RHO0, C0
import acoustic_mesh
import acoustic_fem


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------
@dataclass
class ModalSolution:
    """Solucion modal FEM."""
    method: str                 # "fem"
    freqs: np.ndarray           # (Nm,) frecuencias modales en Hz
    phis: np.ndarray            # (Nn, Nm) modos M-ortonormalizados
    nodes: np.ndarray           # (Nn, 3)   malla del DOMINIO DE AIRE (tallada si hay muebles)
    tets: np.ndarray            # (Ne, 4)
    mesh_info: dict
    locator: acoustic_fem.FieldEvaluator = field(repr=False, default=None)
    # --- Mobiliario (Fase C, aditivo) --------------------------------------
    # Cuando hay muebles, la malla se TALLA (carve) entre build_volume_mesh y
    # build_KM: `nodes`/`tets` arriba son ya la malla del aire (con el agujero).
    # La malla ORIGINAL (sin tallar) se preserva aca porque el canal de
    # absorcion (A36) extrae de ella la frontera aire-mueble por posicion
    # mundial (gotcha de furniture.furniture_boundary_faces). Sin muebles estos
    # campos quedan None -> regresion bit a bit (consumidores previos no los ven).
    nodes0: Optional[np.ndarray] = field(repr=False, default=None)  # malla sin tallar
    tets0: Optional[np.ndarray] = field(repr=False, default=None)
    carve_info: Optional[dict] = None      # auditoria de la talla (furniture.carve_mesh)


@dataclass
class FRFResult:
    method: str
    freq_axis: np.ndarray
    H: np.ndarray
    receiver: tuple


@dataclass
class FieldSlice:
    """Slice 2D de un campo sobre un plano axis-alineado.

    axis=2 → plano XY (z=cte)  X=coord_x, Y=coord_y     [default, original]
    axis=1 → plano XZ (y=cte)  X=coord_x, Y=coord_z
    axis=0 → plano YZ (x=cte)  X=coord_y, Y=coord_z
    z      → posicion del plano en el eje fijo (independiente del nombre)
    """
    z: float                                   # offset en el eje fijo
    X: np.ndarray                              # (N1, N2) primera coord de barrido
    Y: np.ndarray                              # (N1, N2) segunda coord de barrido
    P: np.ndarray                              # (N1, N2) magnitud
    P_complex: Optional[np.ndarray] = None
    mask: Optional[np.ndarray] = None         # True = dentro del recinto
    axis: int = 2                             # eje fijo (0=x, 1=y, 2=z)


# ---------------------------------------------------------------------------
# FEM modal: pipeline completo
# ---------------------------------------------------------------------------
def run_fem_modal(
    surface_verts: np.ndarray,
    surface_tris: np.ndarray,
    n_modes: int = 12,
    n_per_meter: float = 3.0,
    c: float = C0,
    muebles: Optional[list] = None,
    progress=None,
) -> ModalSolution:
    """Pipeline FEM: malla -> K,M -> autovalores -> modos M-ortonormales.

    `progress`: callable opcional(str) para reportar etapas.
    `muebles`: lista de furniture.Furniture, opcional (talla la malla; ver
    run_fem_modal_routed). Con None/[] el resultado es identico al historico.
    """
    if progress: progress("Mallando volumen...")
    nodes, tets = acoustic_mesh.build_volume_mesh(
        surface_verts, surface_tris, n_per_meter=n_per_meter
    )
    if len(tets) == 0:
        raise RuntimeError("Mallado volumetrico vacio (geometria degenerada?).")

    # Talla de mobiliario (ver run_fem_modal_routed) preservando la malla original.
    nodes0 = tets0 = None
    carve_info = None
    if muebles:
        import furniture as fu
        nodes0, tets0 = nodes, tets
        nodes, tets, carve_info = fu.carve_mesh(nodes0, tets0, muebles)
        if len(tets) == 0:
            raise RuntimeError("La talla de muebles vacio el dominio de aire.")
    info = acoustic_mesh.mesh_info(nodes, tets)

    if progress: progress(f"Ensamblando K, M ({info['n_nodes']} nodos)...")
    K, M, _ = acoustic_fem.build_KM(nodes, tets)

    if progress: progress(f"Resolviendo {n_modes} modos (Lanczos)...")
    freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=n_modes, c=c)

    locator = acoustic_fem.FieldEvaluator(nodes, tets)
    return ModalSolution(
        method="fem",
        freqs=freqs, phis=phis,
        nodes=nodes, tets=tets,
        mesh_info=info, locator=locator,
        nodes0=nodes0, tets0=tets0, carve_info=carve_info,
    )


def run_fem_modal_routed(
    surface_verts: np.ndarray,
    surface_tris: np.ndarray,
    *,
    params: Optional[dict] = None,
    is_imported_cad: bool = False,
    user_override: str = "auto",
    n_modes: int = 12,
    n_per_meter: float = 2.5,
    h_target: float = 0.40,
    c: float = C0,
    muebles: Optional[list] = None,
    progress=None,
):
    """Pipeline FEM con seleccion automatica de motor (voxel/gmsh).

    Devuelve (ModalSolution, MeshDecision). El segundo elemento contiene
    la informacion para el badge UI (color, texto, tooltip).

    `muebles`: lista de furniture.Furniture, opcional. Si no es vacia, la malla
    del router se TALLA (carve) antes de ensamblar K,M — los muebles quedan como
    agujeros rigidos en el aire (Neumann natural). La malla ORIGINAL se preserva
    en sol.nodes0/tets0 para el canal de absorcion. Con muebles=None/[] el
    resultado es identico al historico (regresion bit a bit).
    """
    import mesh_router

    result = mesh_router.build_mesh(
        surface_verts, surface_tris,
        params=params,
        is_imported_cad=is_imported_cad,
        user_override=user_override,
        h_target=h_target,
        n_per_meter=n_per_meter,
        progress=progress,
    )
    if len(result.tets) == 0:
        raise RuntimeError("Mallado volumetrico vacio (geometria degenerada?).")

    # ----- Talla de mobiliario (Fase C): ENTRE build_mesh y build_KM --------
    nodes, tets, info = result.nodes, result.tets, result.info
    nodes0 = tets0 = None
    carve_info = None
    if muebles:
        import furniture as fu
        nodes0, tets0 = result.nodes, result.tets      # malla ORIGINAL preservada
        nodes, tets, carve_info = fu.carve_mesh(nodes0, tets0, muebles)
        if len(tets) == 0:
            raise RuntimeError("La talla de muebles vacio el dominio de aire "
                               "(mueble mas grande que el recinto?).")
        # mesh_info recomputado sobre la malla TALLADA (h_max/n_nodes reales),
        # preservando las claves-meta del router (engine, n_per_meter, t_mesh).
        info = {**result.info, **acoustic_mesh.mesh_info(nodes, tets)}
        if progress:
            progress(f"Muebles: {carve_info['n_tets_removed']} tets tallados, "
                     f"{carve_info['n_nodes_pruned']} nodos podados "
                     f"(V_aire -{carve_info['V_removed_mesh']:.2f} m3).")

    if progress: progress(f"Ensamblando K, M ({info['n_nodes']} nodos)...")
    K, M, _ = acoustic_fem.build_KM(nodes, tets)

    if progress: progress(f"Resolviendo {n_modes} modos (Lanczos)...")
    freqs, phis = acoustic_fem.solve_modes(K, M, n_modes=n_modes, c=c)

    locator = acoustic_fem.FieldEvaluator(nodes, tets)
    sol = ModalSolution(
        method="fem",
        freqs=freqs, phis=phis,
        nodes=nodes, tets=tets,
        mesh_info=info, locator=locator,
        nodes0=nodes0, tets0=tets0, carve_info=carve_info,
    )
    return sol, result.decision


# ---------------------------------------------------------------------------
# FRF (frequency response function) - FEM
# ---------------------------------------------------------------------------
def run_fem_frf(
    modal: ModalSolution,
    sources: SourceArray,
    receiver: tuple,
    f_min: float = 20.0,
    f_max: float = 200.0,
    n_freqs: int = 200,
    damping: float = 0.03,
    modal_freqs=None,
) -> FRFResult:
    """`modal_freqs` (opcional, Nm,): frecuencias de RESONANCIA a usar en la suma
    modal, en vez de las rigidas `modal.freqs`. Es el corrimiento reactivo de la
    Capa 0 (Im(beta) -> fₙ corrida); la FORMA modal `modal.phis` sigue rigida
    (perturbacion de 1er orden, D3). Sin construcciones se pasa None y coincide
    bit a bit con el camino previo."""
    fa = np.linspace(f_min, f_max, n_freqs)
    freqs = modal.freqs if modal_freqs is None else np.asarray(modal_freqs, float)
    H = acoustic_fem.frequency_response(
        modal.locator, freqs, modal.phis, sources, receiver,
        freq_axis=fa, damping=damping,
    )
    return FRFResult(method="fem", freq_axis=fa, H=H, receiver=tuple(receiver))


# ---------------------------------------------------------------------------
# Slices del campo para visualizar
# ---------------------------------------------------------------------------
def slice_field_fem(
    modal: ModalSolution,
    nodal_field: np.ndarray,
    z: float,
    nx: int = 50,
    ny: int = 50,
    surface_verts: Optional[np.ndarray] = None,
    surface_tris: Optional[np.ndarray] = None,
) -> FieldSlice:
    """Evalua `nodal_field` (Nn,) sobre un plano horizontal z=cte.

    Devuelve magnitud (|.| si es complejo). Los puntos fuera del recinto
    quedan enmascarados (NaN, mask=False) para que la visualizacion los
    omita.
    """
    # AABB de la malla.
    nodes = modal.nodes
    xmin, ymin, zmin = nodes.min(axis=0)
    xmax, ymax, zmax = nodes.max(axis=0)
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pts = np.stack([X.ravel(), Y.ravel(), np.full(X.size, float(z))], axis=1)

    is_complex = np.iscomplexobj(nodal_field)
    if is_complex:
        Pc = modal.locator.evaluate_many(nodal_field, pts).reshape(X.shape)
        P = np.abs(Pc)
    else:
        Pc = None
        Pf = modal.locator.evaluate_many(nodal_field.astype(complex), pts)
        P = Pf.real.reshape(X.shape)

    # Mascara: NaN -> fuera. Aprovechamos el resultado del locator
    # (evaluate_many devuelve NaN si el punto no esta en ningun tet).
    raw = Pc if is_complex else Pf.reshape(X.shape)
    mask = np.isfinite(raw if is_complex else raw)
    return FieldSlice(z=z, X=X, Y=Y, P=P, P_complex=Pc, mask=mask)


def slice_pressure_field(
    modal: ModalSolution,
    sources: SourceArray,
    f: float,
    z: float,
    nx: int = 50,
    ny: int = 50,
    damping: float = 0.03,
) -> FieldSlice:
    """Slice del campo de presion complejo (FEM modal superposition) a freq f."""
    p_nodes = acoustic_fem.modal_pressure_field(
        modal.locator, modal.freqs, modal.phis, sources, f, damping=damping
    )
    return slice_field_fem(modal, p_nodes, z=z, nx=nx, ny=ny)


def slice_mode_shape(
    modal: ModalSolution,
    mode_idx: int,
    z: float,
    nx: int = 50,
    ny: int = 50,
) -> FieldSlice:
    """Slice del modo normalizado (campo real)."""
    phi = acoustic_fem.mode_shape_field(modal.phis, mode_idx)
    return slice_field_fem(modal, phi, z=z, nx=nx, ny=ny)


# ---------------------------------------------------------------------------
# Slices en plano arbitrario (XY, XZ, YZ)
# ---------------------------------------------------------------------------
def slice_field_fem_plane(
    modal: ModalSolution,
    nodal_field: np.ndarray,
    axis: int,
    offset: float,
    n1: int = 50,
    n2: int = 50,
) -> FieldSlice:
    """Evalua nodal_field sobre un plano axis-alineado.

    axis=2 → plano XY (z=offset):  barre x, y
    axis=1 → plano XZ (y=offset):  barre x, z
    axis=0 → plano YZ (x=offset):  barre y, z
    """
    nodes = modal.nodes
    mn = nodes.min(axis=0)
    mx = nodes.max(axis=0)

    # Los dos ejes de barrido son los que NO son el fijo
    ax1, ax2 = [a for a in (0, 1, 2) if a != axis]

    c1 = np.linspace(mn[ax1], mx[ax1], n1)
    c2 = np.linspace(mn[ax2], mx[ax2], n2)
    C1, C2 = np.meshgrid(c1, c2, indexing="ij")

    # Construir puntos 3D
    pts = np.zeros((C1.size, 3))
    pts[:, axis] = float(offset)
    pts[:, ax1]  = C1.ravel()
    pts[:, ax2]  = C2.ravel()

    is_complex = np.iscomplexobj(nodal_field)
    if is_complex:
        Pc  = modal.locator.evaluate_many(nodal_field, pts).reshape(C1.shape)
        P   = np.abs(Pc)
    else:
        Pc  = None
        Pf  = modal.locator.evaluate_many(nodal_field.astype(complex), pts)
        P   = Pf.real.reshape(C1.shape)

    raw  = Pc if is_complex else Pf.reshape(C1.shape)
    mask = np.isfinite(raw if is_complex else raw)
    return FieldSlice(z=float(offset), X=C1, Y=C2, P=P,
                      P_complex=Pc, mask=mask, axis=axis)


def slice_mode_shape_plane(
    modal: ModalSolution,
    mode_idx: int,
    axis: int,
    offset: float,
    n1: int = 50,
    n2: int = 50,
) -> FieldSlice:
    """Slice de la forma modal en un plano axis-alineado."""
    phi = acoustic_fem.mode_shape_field(modal.phis, mode_idx)
    return slice_field_fem_plane(modal, phi, axis=axis, offset=offset,
                                  n1=n1, n2=n2)


def slice_pressure_field_plane(
    modal: ModalSolution,
    sources: "SourceArray",
    f: float,
    axis: int,
    offset: float,
    n1: int = 50,
    n2: int = 50,
    damping=0.03,
) -> FieldSlice:
    """Slice del campo de presion |p| en un plano axis-alineado."""
    p_nodes = acoustic_fem.modal_pressure_field(
        modal.locator, modal.freqs, modal.phis, sources, f, damping=damping
    )
    return slice_field_fem_plane(modal, p_nodes, axis=axis, offset=offset,
                                  n1=n1, n2=n2)


# ---------------------------------------------------------------------------
# Frecuencia de Schroeder (frontera modal / estadistica)
# ---------------------------------------------------------------------------

def compute_mesh_volume(surface_verts: np.ndarray,
                        surface_tris: np.ndarray) -> float:
    """Volumen del recinto via teorema de la divergencia sobre la malla triangular."""
    v = surface_verts.astype(float)
    a = v[surface_tris[:, 0]]
    b = v[surface_tris[:, 1]]
    c = v[surface_tris[:, 2]]
    cross = np.cross(b - a, c - a)
    return float(abs(np.einsum('ij,ij->i', a, cross).sum()) / 6.0)


def compute_mesh_surface_area(surface_verts: np.ndarray,
                               surface_tris: np.ndarray) -> float:
    """Area total de la superficie triangulada."""
    v = surface_verts.astype(float)
    a = v[surface_tris[:, 0]]
    b = v[surface_tris[:, 1]]
    c = v[surface_tris[:, 2]]
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def schroeder_frequency(volume: float, surface_area: float,
                        alpha: float = 0.05, c: float = C0) -> float:
    """Frecuencia de Schroeder: por debajo el campo es modal (modos discretos),
    por encima el campo es estadistico (difuso).

    Sabine: RT60 = 0.161 * V / (alpha * S)
    Schroeder: f_s = 2000 * sqrt(RT60 / V)

    Ejemplo: cuarto 6x8x3 m, alpha=0.05 -> RT60~1.3 s -> f_s~120 Hz.
    """
    RT60 = 0.161 * volume / max(alpha * surface_area, 1e-9)
    return 2000.0 * float(np.sqrt(max(RT60 / max(volume, 1e-9), 0)))


def pressure_field_3d(modal: ModalSolution, sources: SourceArray,
                      f: float, resolution: int = 20,
                      damping: float = 0.03) -> tuple:
    """Evalua el campo de presion en una rejilla 3D interior al recinto.

    Devuelve (points, pressure_abs, pressure_complex):
        points: (N,3) puntos dentro del recinto
        pressure_abs: (N,) amplitud de presion en cada punto
        pressure_complex: (N,) presion compleja
    """
    nodes = modal.nodes
    mn = nodes.min(axis=0)
    mx = nodes.max(axis=0)
    xs = np.linspace(mn[0], mx[0], resolution)
    ys = np.linspace(mn[1], mx[1], resolution)
    zs = np.linspace(mn[2], mx[2], max(resolution // 2, 4))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    p_nodes = acoustic_fem.modal_pressure_field(
        modal.locator, modal.freqs, modal.phis, sources, f, damping=damping
    )
    p_pts = modal.locator.evaluate_many(p_nodes, pts)
    # Filtrar solo puntos dentro del recinto (evaluate_many devuelve NaN afuera)
    mask = np.isfinite(p_pts)
    return pts[mask], np.abs(p_pts[mask]), p_pts[mask]


def mode_shape_field_3d(modal: ModalSolution, mode_idx: int,
                        resolution: int = 20) -> tuple:
    """Evalua la forma modal (real, con signo) del modo mode_idx en una rejilla 3D.

    Devuelve (points, values_signed, None):
      points:        (N,3)  puntos dentro del recinto
      values_signed: (N,)   valores reales normalizados a [-1, 1]
    """
    nodes = modal.nodes
    mn = nodes.min(axis=0)
    mx = nodes.max(axis=0)
    xs = np.linspace(mn[0], mx[0], resolution)
    ys = np.linspace(mn[1], mx[1], resolution)
    zs = np.linspace(mn[2], mx[2], max(resolution // 2, 4))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    phi = acoustic_fem.mode_shape_field(modal.phis, mode_idx)
    vals = modal.locator.evaluate_many(phi.astype(complex), pts)
    vals_real = vals.real
    mask = np.isfinite(vals_real)
    return pts[mask], vals_real[mask], None


def pressure_gradient_3d(modal: ModalSolution, sources: SourceArray,
                         f: float, resolution: int = 8,
                         damping: float = 0.03) -> tuple:
    """Calcula el gradiente del campo de presion en una rejilla esparsa.

    Devuelve (origins, gradients):
        origins: (N,3) origenes de las flechas
        gradients: (N,3) vectores gradiente (Re o modulo)
    """
    nodes = modal.nodes
    mn = nodes.min(axis=0)
    mx = nodes.max(axis=0)
    res = resolution
    xs = np.linspace(mn[0], mx[0], res)
    ys = np.linspace(mn[1], mx[1], res)
    zs = np.linspace(mn[2], mx[2], max(res // 2, 3))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    pts_all = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    p_nodes = acoustic_fem.modal_pressure_field(
        modal.locator, modal.freqs, modal.phis, sources, f, damping=damping
    )

    # Diferencias finitas: dx, dy, dz = spacing
    dx = (mx[0] - mn[0]) / max(res - 1, 1)
    dy = (mx[1] - mn[1]) / max(res - 1, 1)
    dz = (mx[2] - mn[2]) / max(res // 2 - 1, 1)
    eps = min(dx, dy, dz) * 0.4

    def eval_pts(plist):
        return modal.locator.evaluate_many(p_nodes, plist)

    gx = (np.abs(eval_pts(pts_all + [eps, 0, 0])) -
          np.abs(eval_pts(pts_all - [eps, 0, 0]))) / (2 * eps)
    gy = (np.abs(eval_pts(pts_all + [0, eps, 0])) -
          np.abs(eval_pts(pts_all - [0, eps, 0]))) / (2 * eps)
    gz = (np.abs(eval_pts(pts_all + [0, 0, eps])) -
          np.abs(eval_pts(pts_all - [0, 0, eps]))) / (2 * eps)

    grads = np.stack([gx, gy, gz], axis=1)
    p_center = eval_pts(pts_all)
    mask = np.isfinite(p_center) & np.all(np.isfinite(grads), axis=1)
    return pts_all[mask], grads[mask]
