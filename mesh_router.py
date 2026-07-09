"""
mesh_router.py
==============

Router que decide automaticamente que motor de mallado usar (voxel o gmsh)
para una geometria dada, segun dos criterios objetivos:

  1. Rigurosidad cientifica: en geometrias con paredes curvas el voxel
     introduce error de "escalera" que rompe degeneraciones modales.
     -> gmsh boundary-fitted obligatorio.
  2. Tiempo de compilacion: para una caja shoebox axis-aligned el voxel
     es EXACTO (sus celdas coinciden con las paredes) y mas rapido que
     inicializar gmsh.
     -> voxel.

Override del usuario:
  - "auto": el router decide.
  - "voxel": fuerza voxel (badge naranja/amarillo segun el caso).
  - "gmsh":  fuerza gmsh (badge naranja).

Fuente de la decision (en orden de precedencia):
  1. Override por proyecto (campo "mesh_engine" del .room cargado).
  2. Override global (app_settings.default_mesh_engine).
  3. "auto" -> evaluacion segun criterios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable
import numpy as np

import acoustic_mesh
try:
    import mesh_gmsh
    _HAS_GMSH_MODULE = mesh_gmsh.is_available()
except ImportError:
    mesh_gmsh = None
    _HAS_GMSH_MODULE = False


# ---------------------------------------------------------------------------
# Resultado: que motor se uso, por que, y la malla resultante
# ---------------------------------------------------------------------------
@dataclass
class MeshDecision:
    """Razon de la eleccion + datos para el badge UI."""
    engine: str                 # "voxel" | "gmsh"   (motor finalmente usado)
    auto_choice: str            # "voxel" | "gmsh"   (lo que el router HABRIA elegido)
    user_override: str          # "auto" | "voxel" | "gmsh"
    reason: str                 # texto humano-legible
    # Si gmsh fallo y caimos a voxel, aca queda el motivo. None si no hubo fallback.
    fallback_reason: Optional[str] = None

    @property
    def is_forced(self) -> bool:
        return self.user_override != "auto" and self.engine != self.auto_choice

    @property
    def is_lossy(self) -> bool:
        """True si la decision degrada la rigurosidad (voxel sobre curva)."""
        return self.engine == "voxel" and self.auto_choice == "gmsh"

    @property
    def is_fallback(self) -> bool:
        """True si el motor final no es el preferido (cayo por fallo)."""
        return self.fallback_reason is not None


@dataclass
class MeshResult:
    """Salida estandar de cualquier backend: (nodes, tets, info, decision)."""
    nodes: np.ndarray
    tets: np.ndarray
    info: dict
    decision: MeshDecision


# ---------------------------------------------------------------------------
# Auto-density tuner: derivar n_per_meter / h_target de la validez fisica
# ---------------------------------------------------------------------------
# Calibracion empirica (16 hilos, 64 GB RAM):
#   Voxel POST-G (vectorizacion de points_inside_surface + cand_tets):
#       shoebox 6x8x3 npm=2.5: 14400 tets en ~25 ms  -> ~575 000 tets/s mesh-only.
#       Incluyendo ensamblaje K/M + Lanczos: ~150 ms total -> ~95 000 tets/s.
#   Gmsh shoebox h=0.20-0.30:  ~12000 tets/s  (despues de init).
#
# Nota: estos numeros solo afectan los MENSAJES de log del auto-tuner. La
# eleccion de densidad y motor se hace ahora siempre por cobertura completa
# hasta f_Schroeder (`budget=inf` en la llamada desde acoustic_panel), asi
# que el estimador de tiempo es solo informativo, no decisivo.
_C0 = 343.0
_PPW = 6.0                  # puntos por longitud de onda para FEM lineal P1
# Factor de calibracion h_max/h_target para gmsh boundary-fitted.
#   gmsh recibe Mesh.MeshSizeMax = h_target, pero NO lo respeta estrictamente
#   en el peor elemento: el tet mas grande (que define la validez de malla,
#   f_max = c/(ppw*h_max)) sale ~1.5x el target. Medido empiricamente sobre
#   shoebox 5x4x3 y salas 10x15x4 lofteadas, h in [0.20, 0.40]:
#       ratio h_max/h_target = 1.42 .. 1.51  (estable, escala-invariante).
#   Si se asume h_max == h_target (lo que hacia auto_density antes), gmsh
#   sub-entrega validez en ese factor: pediste cobertura hasta f_S y la malla
#   real solo llega a f_S/1.5. Usamos 1.5 (peor caso medido) para que la
#   validez SIEMPRE alcance el objetivo. El voxel NO necesita este factor: su
#   celda es uniforme, h_max == 1/npm exacto.
_GMSH_HMAX_OVER_HTARGET = 1.5
_VOXEL_TETS_PER_M3_PER_NPM3 = 6.0
_GMSH_TETS_PER_M3_PER_INV_H3 = 5.0
# Throughput end-to-end (mesh + K/M + Lanczos) post-vectorizacion.
_VOXEL_THR_TETS_PER_S = 50000.0    # antes 7000 (pre-G). Conservador vs ~95000 medido.
_GMSH_THR_TETS_PER_S = 12000.0     # sin cambio (gmsh no se vectorizo)
_GMSH_INIT_OVERHEAD_S = 1.0
# Margen extra multiplicativo aplicado al tiempo estimado final.
_SAFETY_FACTOR = 1.30


@dataclass
class AutoDensityResult:
    """Salida del auto-tuner de densidad.

    El tuner trabaja en dos modos:
      - 'full': cobertura completa hasta f_target dentro del budget.
      - 'partial': el budget no alcanza para cobertura completa; se devuelve
        la densidad que MAX fmax_achievable cabe en el budget.
    """
    engine: str                 # 'voxel' | 'gmsh' recomendado
    n_per_meter: float          # densidad recomendada para voxel
    h_target: float             # tamano caracteristico para gmsh
    f_target: float             # fmax objetivo (Schroeder)
    f_achievable: float         # fmax que realmente da la densidad recomendada
    estimated_time_s: float     # estimacion de tiempo total FEM
    full_coverage: bool         # True si f_achievable >= f_target
    n_tets_estimated: int
    volume_m3: float
    message: str                # texto para log + tooltip
    # Tabla con los candidatos evaluados (para el dialog over-budget):
    candidates: list = None


def _voxel_n_tets(volume_m3: float, n_per_meter: float) -> int:
    return int(_VOXEL_TETS_PER_M3_PER_NPM3 * volume_m3 * n_per_meter ** 3)


def _gmsh_n_tets(volume_m3: float, h: float) -> int:
    return int(_GMSH_TETS_PER_M3_PER_INV_H3 * volume_m3 / max(h, 1e-3) ** 3)


def _voxel_time_s(volume_m3: float, n_per_meter: float) -> float:
    """Tiempo estimado FEM completo (mesh + assemble + Lanczos) con voxel.

    Incluye factor de seguridad multiplicativo para que la estimacion sea
    conservadora (mejor over-estimate que under-estimate).
    """
    raw = _voxel_n_tets(volume_m3, n_per_meter) / _VOXEL_THR_TETS_PER_S
    return raw * _SAFETY_FACTOR


def _gmsh_time_s(volume_m3: float, h: float) -> float:
    """Tiempo estimado FEM completo con gmsh. Incluye overhead de init."""
    raw = _GMSH_INIT_OVERHEAD_S + _gmsh_n_tets(volume_m3, h) / _GMSH_THR_TETS_PER_S
    return raw * _SAFETY_FACTOR


def _voxel_npm_for_fmax(fmax_hz: float, c: float = _C0) -> float:
    """Voxel cell = 1/npm. fmax = c / (6*h) -> npm = 6*fmax/c."""
    return _PPW * fmax_hz / c


def _gmsh_h_for_fmax(fmax_hz: float, c: float = _C0) -> float:
    """Gmsh h_target para que la VALIDEZ real (definida por el peor tet,
    h_max ~= 1.5*h_target) llegue a fmax.

    Validez = c / (ppw*h_max) = c / (ppw * R * h_target), con R el factor
    h_max/h_target. Despejando: h_target = c / (ppw*fmax) / R. Sin el /R
    (lo que se hacia antes) gmsh sub-entregaba validez en el factor R.
    """
    return c / (_PPW * max(fmax_hz, 1.0)) / _GMSH_HMAX_OVER_HTARGET


def _fmax_from_gmsh_h(h: float, c: float = _C0) -> float:
    """Validez real de una malla gmsh con tamano objetivo h_target=h.

    Usa h_max ~= R*h_target (peor tet), no h_target, para no sobrestimar la
    validez. Inversa exacta de _gmsh_h_for_fmax.
    """
    return c / (_PPW * _GMSH_HMAX_OVER_HTARGET * max(h, 1e-3))


def _fmax_from_voxel_npm(n_per_meter: float, c: float = _C0) -> float:
    return c * n_per_meter / _PPW


def _max_voxel_npm_in_budget(volume_m3: float, budget_s: float) -> float:
    """Maxima densidad voxel que cabe en `budget_s` de tiempo estimado.

    Aplica safety factor inverso (dividimos) para mantener coherencia con
    _voxel_time_s que aplica safety multiplicativo.
    """
    effective_budget = budget_s / _SAFETY_FACTOR
    return (effective_budget * _VOXEL_THR_TETS_PER_S /
            (_VOXEL_TETS_PER_M3_PER_NPM3 * max(volume_m3, 1e-3))) ** (1.0 / 3.0)


def _min_gmsh_h_in_budget(volume_m3: float, budget_s: float) -> float:
    """Minimo h_target gmsh que cabe en `budget_s` de tiempo estimado."""
    effective_budget = budget_s / _SAFETY_FACTOR
    avail = max(effective_budget - _GMSH_INIT_OVERHEAD_S, 0.1)
    return (_GMSH_TETS_PER_M3_PER_INV_H3 * max(volume_m3, 1e-3) /
            (avail * _GMSH_THR_TETS_PER_S)) ** (1.0 / 3.0)


def auto_density(
    volume_m3: float,
    *,
    f_target: float,
    time_budget_s: float,
    prefer_engine: Optional[str] = None,
) -> AutoDensityResult:
    """Recomienda motor + densidad para cubrir f_target dentro del budget.

    Parameters
    ----------
    volume_m3 : float
        Volumen del recinto (calculado de la superficie del recinto).
    f_target : float
        Frecuencia maxima objetivo (Hz). Tipicamente Schroeder.
    time_budget_s : float
        Tiempo maximo aceptable para correr el FEM.
    prefer_engine : 'voxel' | 'gmsh' | None
        Si esta seteado, restringe la decision a ese motor (cuando el usuario
        forzo el motor manualmente). None = elige el mejor.

    Algoritmo:
      1. Compute la densidad teorica que CUBRE f_target en cada motor:
         - voxel: npm_full = 6*f/c
         - gmsh:  h_full   = c/(6*f)
      2. Estima tiempo para cobertura completa en cada motor.
      3. Si alguno entra en el budget con cobertura completa -> 'full'.
         Si los dos entran, prefiere voxel para axis-aligned (caller lo sabe).
      4. Si ninguno entra -> 'partial': calcula densidad maxima que cabe en
         el budget para cada motor y reporta fmax_achievable.
    """
    f = max(float(f_target), 20.0)
    V = max(float(volume_m3), 0.1)

    # ----- Cobertura completa -----
    npm_full = _voxel_npm_for_fmax(f)
    h_full = _gmsh_h_for_fmax(f)
    t_vox_full = _voxel_time_s(V, npm_full)
    t_gmsh_full = _gmsh_time_s(V, h_full)

    # ----- Maxima densidad que cabe en budget (cobertura parcial) -----
    # Con budget infinito (caso de produccion: el panel siempre pasa inf para
    # forzar cobertura completa) la densidad "parcial" tiende a infinito y
    # _voxel_n_tets desborda al castear a int. La cobertura completa siempre
    # entra en budget infinito, asi que el candidato parcial nunca se elige:
    # lo clampamos al valor de cobertura completa para evitar el overflow.
    if np.isfinite(time_budget_s):
        npm_budget = _max_voxel_npm_in_budget(V, time_budget_s)
        h_budget = _min_gmsh_h_in_budget(V, time_budget_s)
    else:
        npm_budget = npm_full
        h_budget = h_full
    f_vox_partial = _fmax_from_voxel_npm(npm_budget)
    f_gmsh_partial = _fmax_from_gmsh_h(h_budget)

    candidates = [
        {"engine": "voxel", "mode": "full",
         "npm": npm_full, "h": float("nan"),
         "fmax": _fmax_from_voxel_npm(npm_full),
         "time_s": t_vox_full,
         "fits_budget": t_vox_full <= time_budget_s,
         "n_tets": _voxel_n_tets(V, npm_full)},
        {"engine": "gmsh", "mode": "full",
         "npm": float("nan"), "h": h_full,
         "fmax": _fmax_from_gmsh_h(h_full),
         "time_s": t_gmsh_full,
         "fits_budget": t_gmsh_full <= time_budget_s,
         "n_tets": _gmsh_n_tets(V, h_full)},
        {"engine": "voxel", "mode": "partial",
         "npm": npm_budget, "h": float("nan"),
         "fmax": f_vox_partial,
         "time_s": time_budget_s,
         "fits_budget": True,
         "n_tets": _voxel_n_tets(V, npm_budget)},
        {"engine": "gmsh", "mode": "partial",
         "npm": float("nan"), "h": h_budget,
         "fmax": f_gmsh_partial,
         "time_s": time_budget_s,
         "fits_budget": True,
         "n_tets": _gmsh_n_tets(V, h_budget)},
    ]

    # Filtrar candidatos por prefer_engine
    eligible = [c for c in candidates if prefer_engine is None or c["engine"] == prefer_engine]

    # Buscar el mejor con cobertura completa que entre en budget
    full_in_budget = [c for c in eligible if c["mode"] == "full" and c["fits_budget"]]
    if full_in_budget:
        # Si hay dos (ambos motores caben), elegimos el de menor tiempo
        chosen = min(full_in_budget, key=lambda c: c["time_s"])
        msg = (f"Cobertura completa hasta {chosen['fmax']:.0f} Hz "
               f"con {chosen['engine']} "
               f"({chosen['n_tets']:,} tets, ~{chosen['time_s']:.1f} s).")
        return AutoDensityResult(
            engine=chosen["engine"],
            n_per_meter=chosen["npm"] if chosen["engine"] == "voxel" else _voxel_npm_for_fmax(f),
            h_target=chosen["h"] if chosen["engine"] == "gmsh" else _gmsh_h_for_fmax(f),
            f_target=f,
            f_achievable=chosen["fmax"],
            estimated_time_s=chosen["time_s"],
            full_coverage=True,
            n_tets_estimated=chosen["n_tets"],
            volume_m3=V,
            message=msg,
            candidates=candidates,
        )

    # Ninguna cobertura completa entra en budget -> elegir partial con mayor fmax
    partial = [c for c in eligible if c["mode"] == "partial"]
    if not partial:   # eligible vacio (shouldn't happen, defensive)
        partial = candidates
    chosen = max(partial, key=lambda c: c["fmax"])
    msg = (f"COBERTURA PARCIAL: {chosen['fmax']:.0f} Hz de {f:.0f} Hz objetivo "
           f"({chosen['engine']}, ~{chosen['time_s']:.1f} s). Para cobertura "
           f"completa se necesitan ~{min(t_vox_full, t_gmsh_full):.1f} s.")
    return AutoDensityResult(
        engine=chosen["engine"],
        n_per_meter=chosen["npm"] if chosen["engine"] == "voxel" else _voxel_npm_for_fmax(f),
        h_target=chosen["h"] if chosen["engine"] == "gmsh" else _gmsh_h_for_fmax(f),
        f_target=f,
        f_achievable=chosen["fmax"],
        estimated_time_s=chosen["time_s"],
        full_coverage=False,
        n_tets_estimated=chosen["n_tets"],
        volume_m3=V,
        message=msg,
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# Detector de geometria axis-aligned
# ---------------------------------------------------------------------------
def is_axis_aligned_box(params: dict, tol_deg: float = 0.05) -> bool:
    """True si la geometria parametrica es un prisma de paredes verticales,
    piso y techo planos, sin twist/taper/pitch/inclinacion ni techo curvo.

    En ese caso el voxel coincide exactamente con las caras del recinto
    -> es boundary-fitted gratis.
    """
    # Si arch_height == 0, el techo es plano de facto, sin importar
    # que roof_type diga "arch" / "gable" / "shed". Solo si hay altura > 0
    # consideramos al techo como curvo.
    if params.get("arch_height", 0.0) > 0.0:
        return False
    if abs(params.get("twist", 0.0)) > tol_deg:
        return False
    if abs(params.get("taper", 0.0)) > 1e-6:
        return False
    for k in ("ceiling_pitch_x", "ceiling_pitch_y",
              "floor_pitch_x",   "floor_pitch_y"):
        if abs(params.get(k, 0.0)) > tol_deg:
            return False
    wi = params.get("wall_inclinations") or []
    if any(abs(w) > tol_deg for w in wi):
        return False

    # Si tiene polygon custom, requerimos que sus aristas sean axis-aligned
    # (paralelas a X o Y). De lo contrario voxel sufrira escalera.
    bp = params.get("base_polygon")
    if bp is not None and len(bp) >= 3:
        return _polygon_is_axis_aligned(bp, tol_deg=tol_deg)

    # Caja regular: n_walls=4 -> 4 paredes axis-aligned por la matematica
    # del prisma regular elipsoidal centrado. Otros n_walls -> no.
    if int(params.get("n_walls", 4)) != 4:
        return False
    return True


def _has_subdivided_curved_roof(params: dict) -> bool:
    """True si el techo es curvo (arco o dos aguas) con arch_height>0.

    En ese caso geometry.make_room subdivide el techo para suavizar la curva
    visualmente, pero las paredes no se subdividen para acompañar. Resultado:
    T-junctions en el borde techo-pared que rompen gmsh con PLC error pero
    son benignos para voxel.

    Techo "shed" (inclinado lineal) NO necesita subdivision -> usa gmsh ok.
    """
    if params.get("arch_height", 0.0) <= 0.0:
        return False
    roof = (params.get("roof_type") or "").lower()
    return roof in ("arch", "gable")


def _polygon_is_axis_aligned(polygon_xy, tol_deg: float = 0.5) -> bool:
    """Una arista es axis-aligned si forma menos de tol_deg con los ejes."""
    pts = np.asarray(polygon_xy, dtype=float)
    n = len(pts)
    if n < 3:
        return False
    edges = pts[(np.arange(n) + 1) % n] - pts
    lens = np.linalg.norm(edges, axis=1)
    lens = np.where(lens < 1e-12, 1.0, lens)
    edges = edges / lens[:, None]
    # Angulo con el eje X y con el eje Y.
    abs_cos_x = np.abs(edges[:, 0])
    abs_cos_y = np.abs(edges[:, 1])
    tol = np.cos(np.deg2rad(tol_deg))
    # Cada arista debe estar pegada a alguno de los dos ejes.
    aligned = (abs_cos_x > tol) | (abs_cos_y > tol)
    return bool(aligned.all())


# ---------------------------------------------------------------------------
# Decision pura (sin mallar todavia)
# ---------------------------------------------------------------------------
def choose_engine(
    params: Optional[dict] = None,
    *,
    is_imported_cad: bool = False,
    user_override: str = "auto",
) -> MeshDecision:
    """Decide que motor usar dado el contexto.

    `params`: dict de geometria parametrica (lo que devuelve ControlPanel.get_params).
              Si la geometria viene de CAD, pasar None y is_imported_cad=True.
    `is_imported_cad`: True si la malla actual proviene de geom_import.
    `user_override`:   "auto" | "voxel" | "gmsh".
    """
    override = (user_override or "auto").lower()

    # Determinacion del "auto choice"
    if is_imported_cad:
        auto = "gmsh"
        auto_reason = "Geometria importada (CAD) -> gmsh boundary-fitted."
    elif params is not None and is_axis_aligned_box(params):
        auto = "voxel"
        auto_reason = ("Recinto axis-aligned (paredes verticales, techo plano): "
                       "el voxel coincide con la frontera (sin escalera) y es mas rapido.")
    elif params is not None and _has_subdivided_curved_roof(params):
        # Geometria parametrica con techo en arco/dos aguas: la malla
        # superficial de visualizacion (subdiv_levels>0) crea T-junctions en
        # el borde techo-pared porque las paredes no se subdividen para
        # acompañar. Gmsh fallaria con PLC error. Voxel no le importa la
        # topologia (usa inside/outside test), asi que es el motor correcto
        # automaticamente. Ahorra 1-2 s de intentar gmsh y caer.
        auto = "voxel"
        auto_reason = ("Techo curvo parametrico: malla de visualizacion tiene "
                       "T-junctions en el borde techo-pared que romperian gmsh. "
                       "Voxel es tolerante a eso (test inside/outside).")
    elif params is not None:
        # Geometria parametrica con otras curvas (n_walls!=4, taper, etc.):
        # intentamos gmsh. Si falla, build_mesh() cae a voxel (fallback).
        auto = "gmsh"
        auto_reason = ("Geometria parametrica con curvas: gmsh boundary-fitted "
                       "(preferencia por rigor cientifico).")
    else:
        auto = "gmsh"
        auto_reason = "Sin params; asumiendo CAD."

    # Aplicar override + validar disponibilidad de gmsh
    if override == "voxel":
        engine = "voxel"
        if auto == "gmsh":
            reason = ("Forzado a voxel sobre geometria curva. "
                      "AVISO: modos pueden tener error >1 Hz y "
                      "perderse degeneraciones rotacionales.")
        else:
            reason = "Forzado a voxel (coincide con la eleccion automatica)."
    elif override == "gmsh":
        if not _HAS_GMSH_MODULE:
            engine = "voxel"
            reason = ("gmsh solicitado pero no esta instalado en este env. "
                      "Cayendo a voxel.")
        else:
            engine = "gmsh"
            if auto == "voxel":
                reason = ("Forzado a gmsh sobre recinto axis-aligned. "
                          "Funciona, pero voxel seria igual de exacto y mas rapido.")
            else:
                reason = "Forzado a gmsh (coincide con la eleccion automatica)."
    else:
        # auto
        if auto == "gmsh" and not _HAS_GMSH_MODULE:
            engine = "voxel"
            reason = ("gmsh no esta instalado y la geometria lo requeria. "
                      "Cayendo a voxel con AVISO de error de escalera.")
        else:
            engine = auto
            reason = auto_reason

    return MeshDecision(
        engine=engine,
        auto_choice=auto,
        user_override=override,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Ejecucion: mallar segun la decision
# ---------------------------------------------------------------------------
def build_mesh(
    surface_verts: np.ndarray,
    surface_tris: np.ndarray,
    *,
    params: Optional[dict] = None,
    is_imported_cad: bool = False,
    user_override: str = "auto",
    h_target: Optional[float] = None,
    n_per_meter: Optional[float] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> MeshResult:
    """Mallador frontal con decision automatica.

    Parameters
    ----------
    surface_verts, surface_tris
        Malla de superficie cerrada (de geometry.py o de un CAD importado).
    params : dict, opcional
        Parametros de la geometria parametrica (necesarios para detectar
        axis-aligned). Si la geometria es CAD, pasar None.
    is_imported_cad : bool
        True si la superficie viene de un archivo CAD.
    user_override : str
        "auto" | "voxel" | "gmsh".
    h_target : float, opcional
        Tamano caracteristico para gmsh (m). Default 0.40.
    n_per_meter : float, opcional
        Densidad para voxel (1/m). Default 2.5.
    progress : callable(str), opcional
        Reporta etapas.

    Returns
    -------
    MeshResult con la malla, info y MeshDecision (badge).
    """
    decision = choose_engine(
        params=params,
        is_imported_cad=is_imported_cad,
        user_override=user_override,
    )

    if progress:
        progress(f"Motor de mallado: {decision.engine} "
                 f"(auto={decision.auto_choice}, override={decision.user_override}).")

    npm = n_per_meter if n_per_meter is not None else 2.5
    h = h_target if h_target is not None else 0.40

    def _build_voxel():
        if progress: progress(f"voxel: mallando (n/m={npm})...")
        nv, nt = acoustic_mesh.build_volume_mesh(
            surface_verts, surface_tris, n_per_meter=npm,
        )
        ni = acoustic_mesh.mesh_info(nv, nt)
        ni["engine"] = "voxel"
        ni["n_per_meter"] = npm
        return nv, nt, ni

    def _build_gmsh():
        return mesh_gmsh.mesh_with_gmsh(
            surface_verts, surface_tris,
            h_target=h, progress=progress,
        )

    if decision.engine == "gmsh":
        if not _HAS_GMSH_MODULE:
            raise RuntimeError("gmsh no disponible en este env de Python.")
        try:
            nodes, tets, info = _build_gmsh()
        except Exception as e:
            # BEST-EFFORT: si gmsh falla (tipico: malla con T-junctions del
            # techo curvo parametrico, o un CAD demasiado complicado), caemos
            # a voxel con un mensaje de fallback explicito. El usuario ve un
            # badge amarillo "voxel · fallback" para entender que paso.
            if decision.user_override == "gmsh":
                # El usuario forzo gmsh: si falla, mejor reportar el error
                # crudo en vez de caer silenciosamente.
                raise
            fallback_msg = str(e).strip().splitlines()[-1][:200]
            if progress:
                progress(f"AVISO: gmsh fallo ({fallback_msg!r}). "
                         "Cayendo a voxel como fallback.")
            nodes, tets, info = _build_voxel()
            decision.engine = "voxel"
            decision.fallback_reason = fallback_msg
            decision.reason = (
                "Gmsh era preferible pero fallo al mallar esta geometria. "
                "Cayendo a voxel con error de escalera. "
                f"Razon de gmsh: {fallback_msg}"
            )
    else:
        nodes, tets, info = _build_voxel()

    return MeshResult(nodes=nodes, tets=tets, info=info, decision=decision)


# ---------------------------------------------------------------------------
# Badge UI: colores y texto para mostrar en el panel acustico
# ---------------------------------------------------------------------------
def badge_for(decision: MeshDecision) -> dict:
    """Devuelve {color, text, tooltip} para el badge en el panel acustico.

    color: 'green' | 'blue' | 'yellow' | 'orange'
    """
    if decision.user_override == "auto":
        if decision.engine == "voxel":
            # Tres casos posibles para voxel automatico:
            # - Shoebox axis-aligned -> voxel "exacto" (verde).
            # - Fallback (gmsh fallo) -> voxel "fallback" (amarillo, con razon).
            # - Geom param curva sin gmsh disponible -> voxel "escalera" (amarillo).
            if decision.is_fallback:
                return {
                    "color": "yellow",
                    "text":  "voxel · fallback",
                    "tooltip": ("Gmsh era preferible pero fallo. Cayendo a "
                                "voxel con error de escalera.\n\n"
                                f"Razon de gmsh: {decision.fallback_reason}"),
                }
            if "axis-aligned" in (decision.reason or "").lower():
                return {
                    "color": "green",
                    "text":  "voxel · exacto",
                    "tooltip": ("Recinto axis-aligned: las celdas voxel "
                                "coinciden con las paredes. Sin error de frontera.\n\n"
                                + decision.reason),
                }
            return {
                "color": "yellow",
                "text":  "voxel · escalera",
                "tooltip": ("Geometria curva: voxel con error de escalera. "
                            "Importa un CAD para boundary-fitted exacto.\n\n"
                            + decision.reason),
            }
        else:
            return {
                "color": "blue",
                "text":  "gmsh · boundary-fitted",
                "tooltip": ("Malla tetraedrica ajustada exactamente a las "
                            "paredes (incluso curvas).\n\n" + decision.reason),
            }

    # Override manual
    if decision.engine == "voxel" and decision.auto_choice == "gmsh":
        return {
            "color": "yellow",
            "text":  "voxel · ESCALERA",
            "tooltip": ("ATENCION: estas forzando voxel sobre una geometria "
                        "que requeria gmsh.\n\n" + decision.reason),
        }
    if decision.engine == "gmsh" and decision.auto_choice == "voxel":
        return {
            "color": "orange",
            "text":  "gmsh · forzado",
            "tooltip": ("Forzaste gmsh donde voxel seria exacto. Sin "
                        "perjuicio, pero algo mas lento.\n\n" + decision.reason),
        }
    # Override coincide con auto
    if decision.engine == "voxel":
        return {"color": "green", "text": "voxel · forzado",
                "tooltip": decision.reason}
    return {"color": "blue", "text": "gmsh · forzado",
            "tooltip": decision.reason}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Caso 1: shoebox 5x4x3 -> voxel auto
    params_box = {
        "width": 5.0, "length": 4.0, "height": 3.0,
        "n_walls": 4, "taper": 0.0, "twist": 0.0,
        "arch_height": 0.0, "roof_type": "flat",
        "ceiling_pitch_x": 0.0, "ceiling_pitch_y": 0.0,
        "floor_pitch_x": 0.0, "floor_pitch_y": 0.0,
        "wall_inclinations": [0, 0, 0, 0],
        "base_polygon": None,
    }
    d = choose_engine(params_box)
    print(f"[caso 1] shoebox       -> {d.engine}  ({d.reason})")
    print(f"          badge = {badge_for(d)['text']}  ({badge_for(d)['color']})")

    # Caso 2: con techo en arco -> gmsh auto
    params_arch = dict(params_box, arch_height=1.2, roof_type="arch", n_walls=5)
    d = choose_engine(params_arch)
    print(f"[caso 2] pentagono+arco -> {d.engine}  ({d.reason})")
    print(f"          badge = {badge_for(d)['text']}  ({badge_for(d)['color']})")

    # Caso 3: CAD importado -> gmsh siempre
    d = choose_engine(None, is_imported_cad=True)
    print(f"[caso 3] CAD importado  -> {d.engine}")
    print(f"          badge = {badge_for(d)['text']}  ({badge_for(d)['color']})")

    # Caso 4: override voxel sobre curva -> badge ESCALERA
    d = choose_engine(params_arch, user_override="voxel")
    print(f"[caso 4] override voxel sobre curva -> {d.engine}")
    print(f"          badge = {badge_for(d)['text']}  ({badge_for(d)['color']})")
    print(f"          razon: {d.reason}")
