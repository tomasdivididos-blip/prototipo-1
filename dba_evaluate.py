"""
dba_evaluate.py
===============

Evaluacion CABS de una configuracion de fuentes REAL del usuario (flujo inverso
al sintetizador de `dba.py`). Responde: "estas fuentes que cargaste, ¿forman una
configuracion valida para CABS?".

Diferencia con `dba.py`: `dba.compute_dba` SINTETIZA el array ideal (grilla de
pistones front/rear) y mide su colapso. Aca se toman las fuentes reales del
usuario (posiciones, Q(f), delay, polaridad, filtros, tipo) y se evalua SU
configuracion, comparandola contra ese ideal como techo alcanzable.

Requisito del usuario: el criterio usa SIEMPRE la respuesta TOTAL = SBIR + modos
(no solo la FRF modal). La respuesta total es el hibrido de `sbir.modal_sbir_
crossfade`: por debajo de f_Schroeder domina la modal (que YA contiene las
reflexiones de frontera como modos: agregar SBIR ahi seria doble conteo), por
encima domina el peine SBIR. Es la MISMA maquina que la pestaña Acustica.

Consistencia de motor: la parte modal usa la base rectangular analitica
`source_coupling.RectModalBasis` (decision S1: no reabrir la integral sobre malla
escalonada), igual que `dba.compute_dba`. El IDEAL de referencia se mide con el
MISMO pipeline que la config real (materializando el array ideal como fuentes y
pasandolo por la misma funcion), asi la comparacion "vos vs ideal" es exacta.

Convencion e^{+i*omega*t} en todo (igual que sources/sbir/dba).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import List, Optional

from sources import OmniSource, SourceArray, RHO0, C0, SUBWOOFER_TYPES
from source_coupling import RectModalBasis
import sbir as _sbir
import dba as _dba


# ---------------------------------------------------------------------------
# Clasificacion de la configuracion (que fuente es que en el esquema CABS)
# ---------------------------------------------------------------------------
@dataclass
class SourceRole:
    """Rol de una fuente en el esquema CABS (resultado de la clasificacion)."""
    index:    int
    label:    str
    type:     str
    pos_box:  tuple          # posicion en coords de caja [0, L]
    is_sub:   bool           # el tipo es sub/woofer (candidato al array)
    role:     str            # "front" | "rear" | "other" (solo subs entran a front/rear)
    src:      object = None  # ref a la OmniSource (para leer delay/polaridad)
    at_front: bool = False   # pegada a la pared minima del eje (CUALQUIER tipo)
    at_rear:  bool = False   # pegada a la pared maxima del eje (CUALQUIER tipo)


def classify_sources(sources, dims, origin, axis: int,
                     wall_tol: float = 0.6) -> List[SourceRole]:
    """Clasifica cada fuente ACTIVA en front / rear / other sobre `axis`.

    - Solo las fuentes cuyo tipo esta en SUBWOOFER_TYPES son candidatas al array
      (is_sub=True). Las demas (fullrange/horn/generic) quedan "other" (igual
      entran en la respuesta total, pero no forman el array CABS).
    - Un sub se asigna a "front" si esta a <= wall_tol de la pared minima del eje
      (coord ~0), "rear" si esta a <= wall_tol de la pared maxima (coord ~L).
    """
    origin = np.asarray(origin, dtype=float)
    L = float(dims[axis])
    roles: List[SourceRole] = []
    for i, s in enumerate(sources):
        if not getattr(s, "active", True):
            continue
        pos_box = tuple(float(p) for p in (np.asarray(s.position, float) - origin))
        stype = getattr(s, "source_type", "generic")
        is_sub = stype in SUBWOOFER_TYPES
        u = pos_box[axis]
        # Membresia de pared para CUALQUIER tipo de fuente (para CABS, donde el
        # frente puede ser Full Range). El rol front/rear se reserva a los SUBS.
        at_front = u <= wall_tol
        at_rear = u >= L - wall_tol
        if is_sub and at_front:
            role = "front"
        elif is_sub and at_rear:
            role = "rear"
        else:
            role = "other"
        roles.append(SourceRole(i, getattr(s, "label", "") or f"S{i+1}",
                                stype, pos_box, is_sub, role, src=s,
                                at_front=at_front, at_rear=at_rear))
    return roles


def best_axis(sources, dims, origin=(0.0, 0.0, 0.0), c: float = C0) -> int:
    """Eje de enfrentamiento mas probable de las fuentes.

    Un array denso de pared deja subs en las esquinas -> parecen enfrentados en
    los TRES ejes (empate por geometria). El desempate real es la COHERENCIA del
    drive: en el eje verdadero el grupo trasero esta retardado ~L/c e invertido de
    forma uniforme; en los otros ejes el drive queda mezclado. Score:
    (drive coherente, min(n_front,n_rear), L_eje)."""
    scored = []
    for ax in range(3):
        roles = classify_sources(sources, dims, origin, ax)
        fronts = [r for r in roles if r.role == "front"]
        rears = [r for r in roles if r.role == "rear"]
        drive_ok, _ = _check_rear_drive(rears, dims[ax] / c)
        coherent = 1 if (fronts and rears and drive_ok) else 0
        scored.append((coherent, min(len(fronts), len(rears)), dims[ax], ax))
    scored.sort(reverse=True)
    return int(scored[0][3])


def cabs_feasibility(sources, dims, origin=(0.0, 0.0, 0.0),
                     axis: Optional[int] = None, c: float = C0,
                     criterion: str = "dba"):
    """Chequeo estructural BARATO (sin computar respuesta) de si la config PUEDE
    satisfacer el criterio elegido. Estas condiciones son INVARIANTES bajo la
    optimizacion (mover fuentes libres dentro de su pared no cambia el tipo ni las
    despega), asi que sirven de PRE-CHEQUEO: si fallan aca, van a seguir fallando
    despues de optimizar. Reglas (spec del usuario):
      dba  -> >=2 subs ADELANTE y >=2 subs ATRAS.
      cabs -> >=2 subs ATRAS + una fuente ADELANTE de cualquier tipo (Full Range OK).
    Devuelve (feasible, reasons, axis)."""
    active = [s for s in sources if getattr(s, "active", True)]
    if axis is None:
        axis = best_axis(active, dims, origin, c) if active else int(np.argmax(dims))
    roles = classify_sources(sources, dims, origin, axis)
    fronts = [r for r in roles if r.role == "front"]
    rears = [r for r in roles if r.role == "rear"]
    n_front_any = sum(1 for r in roles if r.at_front)
    axis_name = ["X (ancho)", "Y (largo)", "Z (alto)"][axis]
    reasons = []
    if criterion == "cabs":
        if len(rears) < 2:
            reasons.append(f"CABS necesita >=2 subs ATRAS en {axis_name} "
                           f"(hay {len(rears)}). Asignales Tipo Sub-Woofer/Woofer.")
        if n_front_any < 1:
            reasons.append(f"CABS necesita una fuente ADELANTE en {axis_name} "
                           "(cualquier tipo, puede ser Full Range).")
    else:
        if len(fronts) < 2 or len(rears) < 2:
            reasons.append(f"DBA necesita >=2 subs ADELANTE y >=2 ATRAS en "
                           f"{axis_name} (hay {len(fronts)}+{len(rears)}). "
                           "Asignales Tipo Sub-Woofer/Woofer a los cuatro.")
    return len(reasons) == 0, reasons, axis


# ---------------------------------------------------------------------------
# Respuesta modal (base rectangular) de fuentes puntuales con Q(f), en grilla
# ---------------------------------------------------------------------------
def _modal_coupling(basis: RectModalBasis, sources_active, origin) -> np.ndarray:
    """kappa[s,n] (Ns, Nm) real: acoplamiento de cada fuente a los modos, via sus
    PUNTOS MONOPOLARES equivalentes (`coupling_points`). Monopolo -> phi_n(x_s);
    dipolo de bafle abierto -> phi_n(x+)-phi_n(x-). Coords caja (resta origin)."""
    origin = np.asarray(origin, dtype=float)
    kappa = np.zeros((len(sources_active), basis.n_modes), dtype=float)
    for i, s in enumerate(sources_active):
        cpts = (s.coupling_points() if hasattr(s, "coupling_points")
                else [(np.asarray(s.position, float), 1.0)])
        for pt, sign in cpts:
            kappa[i] += sign * basis.phi(np.asarray(pt, float) - origin)
    return kappa


def _modal_frf_grid(basis: RectModalBasis, kappa: np.ndarray, Q_spec: np.ndarray,
                    points_box, freq_axis, *, xi: float,
                    rho0: float = RHO0) -> np.ndarray:
    """FRF modal compleja en cada punto -> (N_R, Nf).

    C_n(f) = sum_s Q_s(f) kappa[s,n];  H(x,f)= i w rho0 c^2 sum_n phi_n(x) C_n/denom.
    """
    fa = np.asarray(freq_axis, dtype=float)
    Q = np.asarray(Q_spec, dtype=complex)          # (Nf, Ns)
    C = Q @ np.asarray(kappa, dtype=float)          # (Nf, Nm)
    phi_g = basis.phi_matrix(points_box)           # (N_R, Nm)
    c_sq = basis.c ** 2
    omega = 2.0 * np.pi * fa
    H_grid = np.empty((phi_g.shape[0], fa.shape[0]), dtype=complex)
    for i, w in enumerate(omega):
        denom = (basis.omega_n ** 2 - w ** 2) + 2j * xi * basis.omega_n * w
        denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
        H_grid[:, i] = (1j * w * rho0 * c_sq) * (phi_g @ (C[i] / denom))
    return H_grid


def _total_db_grid(sources_world, walls, points_world, freq_axis,
                   modal_db_grid, f_schroeder, *, c: float, rho0: float):
    """Respuesta TOTAL en dB por punto (SBIR + modal, hibrido en f_S)."""
    fa = np.asarray(freq_axis, dtype=float)
    arr = SourceArray(list(sources_world))
    total_db = np.empty((len(points_world), fa.shape[0]), dtype=float)
    for j, rx in enumerate(points_world):
        if walls:
            res = _sbir.sbir_from_sources(arr, walls, rx, fa, c=c, rho0=rho0)
            sbir_db = res.total_sbir_db
        else:
            sbir_db = np.zeros_like(fa)
        total_db[j] = _sbir.modal_sbir_crossfade(
            fa, sbir_db, modal_db_grid[j], f_schroeder)
    return total_db


# ---------------------------------------------------------------------------
# Metricas de colapso sobre la respuesta total
# ---------------------------------------------------------------------------
def flatness_and_spatial(freq_axis, total_db_grid):
    """(planitud, varianza_espacial) sobre la respuesta total (plan_fuentes §8).

    - planitud = std_f de la media ESPACIAL en energia (FoM_flat):
      L_bar(f)=10log10(mean_r 10^(L/10)); flat = std_f L_bar.
    - varianza_espacial = mean_f de std_r(L) (FoM_espacial): consistencia entre
      asientos.
    """
    L = np.asarray(total_db_grid, dtype=float)            # (N_R, Nf)
    L_bar = 10.0 * np.log10(np.mean(10.0 ** (L / 10.0), axis=0) + 1e-30)
    flat = float(np.std(L_bar))
    spatial = float(np.mean(np.std(L, axis=0)))
    return flat, spatial, L_bar


# ---------------------------------------------------------------------------
# Decay ventaneado (tolera drives no causales como el LS)
# ---------------------------------------------------------------------------
def _windowed_t_decay(t, h, xi, *, level_db=-15.0):
    """T15 (s) sobre una IR VENTANEADA.

    El drive LS-optimo resuelve minimos cuadrados por frecuencia sin restriccion
    de causalidad -> su IFFT tiene una cola acausal (pre-ringing) envuelta al
    FINAL del buffer. La IR fisica del DBA es causal, asi que se ventanea a
    tmax = clamp(6*RT60_est, 0.5, 3.0) s (y lejos del final del buffer) antes de
    medir el decay. RT60_est = 6.91/(2 pi xi f_ref), f_ref=50 Hz.
    """
    rt60 = 6.91 / (2.0 * np.pi * max(xi, 1e-3) * 50.0)
    tmax = float(np.clip(6.0 * rt60, 0.5, 3.0))
    tmax = min(tmax, 0.4 * float(t[-1]))
    m = t <= tmax
    tw, hw = t[m], h[m]
    sch = _dba.schroeder_decay_db(hw)
    return _dba._t_decay(tw, sch, level_db=level_db)


def _decay_of(basis, kappa, arr, receiver_box, *, fmax, xi):
    """T15 (s): IR modal compleja en el receptor via IFFT, ventaneada."""
    def C_of_f(f):
        Q = arr.amplitudes_spectrum(np.array([f]))[0]
        return Q @ np.asarray(kappa, dtype=float)
    t, h = _dba.impulse_response(basis, receiver_box, C_of_f, fmax=fmax, xi=xi)
    return _windowed_t_decay(t, h, xi)


# ---------------------------------------------------------------------------
# Metricas de una config (real o ideal), MISMO pipeline -> comparacion exacta
# ---------------------------------------------------------------------------
def make_basis(dims, fmax, c=C0):
    """Base modal rectangular para dims hasta ~fmax (reusable en el optimizador)."""
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    return RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)


def _config_metrics(sources_world, dims, origin, walls, receiver_world, *,
                    axis, fa, xi, c, f_s, basis=None, with_decay=True,
                    zone_box=None) -> dict:
    """Total (SBIR+modal) + metricas de una lista de fuentes (coords mundo).

    `basis` opcional (la base solo depende de dims, no de las fuentes -> se puede
    pre-construir y reusar en el bucle del optimizador). `with_decay=False` saltea
    el decay (IFFT caro) cuando solo se necesita flat+spatial como costo.
    `zone_box` opcional: grilla de zona en coords caja (el optimizador pasa una
    gruesa para ir rapido; None -> la fina de _zone_grid)."""
    active = [s for s in sources_world if getattr(s, "active", True)]
    origin = np.asarray(origin, dtype=float)
    arr = SourceArray(active)
    Q_spec = arr.amplitudes_spectrum(fa)
    if basis is None:
        basis = make_basis(dims, fa[-1], c)

    receiver_box = tuple(np.asarray(receiver_world, float) - origin)
    grid_box = _dba._zone_grid(dims, axis) if zone_box is None else np.asarray(zone_box, float)
    grid_world = grid_box + origin

    kappa = _modal_coupling(basis, active, origin)      # (Ns, Nm) monopolo/dipolo
    modal_grid = _modal_frf_grid(basis, kappa, Q_spec, grid_box, fa, xi=xi)
    modal_db = 20.0 * np.log10(np.abs(modal_grid) + 1e-30)
    total_db = _total_db_grid(active, walls, list(grid_world), fa, modal_db, f_s,
                              c=c, rho0=RHO0)
    flat, spatial, L_bar = flatness_and_spatial(fa, total_db)
    decay = (_decay_of(basis, kappa, arr, receiver_box, fmax=fa[-1], xi=xi)
             if with_decay else float("nan"))
    return {"flat": flat, "spatial": spatial, "decay": decay, "L_bar": L_bar,
            "n_modes": basis.n_modes}


# ---------------------------------------------------------------------------
# Evaluacion principal
# ---------------------------------------------------------------------------
def evaluate_cabs(sources, dims, receiver, *, origin=(0.0, 0.0, 0.0),
                  walls=None, axis: Optional[int] = None, fmin: float = 20.0,
                  fmax: float = 200.0, xi: float = 0.03, c: float = C0,
                  n_freq: int = 200, ideal_grid=None,
                  f_schroeder: Optional[float] = None,
                  criterion: str = "dba") -> dict:
    """Evalua la configuracion de fuentes real contra el criterio elegido.

    Parameters
    ----------
    sources   : lista de OmniSource (coordenadas MUNDO).
    dims      : (Lx, Ly, Lz) de la caja AABB del recinto.
    receiver  : (3,) receptor principal (coords MUNDO; para el decay).
    origin    : (3,) esquina minima del AABB (mundo -> caja [0,L]).
    walls     : lista de sbir.Wall (mundo) o None. None -> respuesta total = modal
                (sin SBIR), util para el oraculo de que ambas contribuciones entran.
    axis      : eje de enfrentamiento (0/1/2). None -> el mas largo.
    ideal_grid: (n_a, n_b) del array ideal de referencia. None -> se infiere del
                nº de subs front del usuario (grilla ~cuadrada), min 2x2.
    f_schroeder: cruce modal<->SBIR. None -> estimado desde V y xi.
    criterion : "dba" (double bass array: front+rear, trasero con drive CANONICO
                retardo L/c e invertido; el chequeo del drive es CRITICO) o "cabs"
                (controlled acoustic bass: el trasero es MANEJADO/absorbente, su
                drive no tiene por que ser L/c; se juzga por el colapso de la
                respuesta, el drive deja de ser critico). El mismo criterio se pasa
                a `cabs_optimize.optimize_cabs` para que optimizar y evaluar sigan
                UNO SOLO -> concuerdan por construccion (cierra el bug del delay 2x).

    Las metricas (planitud, varianza, decay) se miden sobre la respuesta TOTAL en
    [fmin, fmax] (la banda que le importa al usuario). El f_max=c/d (aliasing del
    array) se reporta aparte en el checklist como techo de validez del CABS.

    Returns
    -------
    dict con roles, axis, metricas real vs ideal, checklist y curvas para graficar.
    """
    dims = tuple(float(x) for x in dims)
    origin = np.asarray(origin, dtype=float)
    if axis is None:
        axis = int(np.argmax(dims))
    L = dims[axis]

    active = [s for s in sources if getattr(s, "active", True)]
    if not active:
        raise ValueError("No hay fuentes activas para evaluar.")
    roles = classify_sources(sources, dims, origin, axis)
    fronts = [r for r in roles if r.role == "front"]
    rears = [r for r in roles if r.role == "rear"]

    fa = np.linspace(fmin, fmax, n_freq)
    f_s = float(f_schroeder) if f_schroeder else _schroeder_guess(dims, xi)
    # walls puede venir como callable(freq)->[Wall] (para que R(f) del material se
    # muestree en NUESTRO eje fa; el panel arma R sobre su propio eje de 2000 pts).
    if callable(walls):
        walls = walls(fa)

    # --- metricas de la config REAL ---
    real = _config_metrics(active, dims, origin, walls, receiver,
                           axis=axis, fa=fa, xi=xi, c=c, f_s=f_s)

    # --- metricas del IDEAL (mismo pipeline; array LS materializado) ---
    n_front = len(fronts)
    if ideal_grid is None:
        na, nb = _grid_shape(max(n_front, 1))
    else:
        na, nb = ideal_grid
    ideal_srcs = _ideal_sources(dims, origin, axis, na, nb, fmin, fmax, xi, c)
    ideal = _config_metrics(ideal_srcs, dims, origin, walls, receiver,
                            axis=axis, fa=fa, xi=xi, c=c, f_s=f_s)

    # --- banda de validez CABS (aliasing del array real) ---
    f_max_alias = _alias_fmax_from_roles(fronts, dims, axis, c)
    band_hi = min(fmax, f_max_alias)

    # --- checklist ---
    checklist = _build_checklist(roles, fronts, rears, dims, axis, L, band_hi,
                                 fmax, c, real, ideal, criterion=criterion)
    passed = all(item["ok"] for item in checklist if item["critical"])

    return {
        "axis": axis, "roles": roles,
        "n_front": n_front, "n_rear": len(rears),
        "f_max": f_max_alias, "band_hi": float(band_hi),
        "n_modes": real["n_modes"], "ideal_grid": (na, nb),
        "flat_real": real["flat"], "spatial_real": real["spatial"],
        "decay_real": real["decay"],
        "flat_ideal": ideal["flat"], "spatial_ideal": ideal["spatial"],
        "decay_ideal": ideal["decay"],
        "checklist": checklist, "passed": bool(passed),
        "freq": fa, "total_db_mean_real": real["L_bar"],
        "total_db_mean_ideal": ideal["L_bar"],
        "f_schroeder": f_s, "criterion": criterion,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _schroeder_guess(dims, xi) -> float:
    """f_Schroeder estimada desde V y un RT60 derivado de xi (f_ref=50 Hz).

    Solo fija el cruce modal<->SBIR de la curva; no entra en la fisica. En la app
    el panel pasa el f_S real (parametro f_schroeder)."""
    V = float(np.prod(dims))
    rt60 = 6.91 / (2.0 * np.pi * max(xi, 1e-3) * 50.0)
    return float(2000.0 * np.sqrt(max(rt60, 1e-3) / max(V, 1e-6)))


def _grid_shape(n: int) -> tuple:
    """Grilla ~cuadrada (na, nb) con na*nb >= n, minimo 2x2."""
    n = max(int(n), 4)
    na = int(np.ceil(np.sqrt(n)))
    nb = int(np.ceil(n / na))
    return max(na, 2), max(nb, 2)


def _ideal_sources(dims, origin, axis, na, nb, fmin, fmax, xi, c) -> list:
    """Materializa el array CABS ideal (LS) como OmniSource en coords MUNDO,
    para medirlo por el MISMO pipeline que la config real."""
    origin = np.asarray(origin, dtype=float)
    specs = _dba.build_dba_sources(dims, axis=axis, n_x=na, n_z=nb, drive="ls",
                                   fmin=fmin, fmax=fmax, xi=xi, c=c)
    out = []
    for sp in specs:
        pos = tuple(np.asarray(sp["pos"], float) + origin)
        out.append(OmniSource(pos, Q=sp["Q"], label=sp["label"],
                              source_type="subwoofer", delay_s=sp["delay_s"],
                              polarity=sp["polarity"], response=sp["response"]))
    return out


def _alias_fmax_from_roles(fronts, dims, axis, c) -> float:
    """f_max = c/d con d el mayor espaciado entre subs front adyacentes."""
    if len(fronts) < 2:
        return float("inf")
    a, b = tuple(x for x in (0, 1, 2) if x != axis)
    ds = []
    for k in (a, b):
        u = np.unique(np.round([r.pos_box[k] for r in fronts], 3))
        if len(u) > 1:
            ds.append(float(np.max(np.diff(np.sort(u)))))
    return float(c / max(ds)) if ds else float("inf")


def _build_checklist(roles, fronts, rears, dims, axis, L, band_hi, fmax, c,
                     real, ideal, criterion: str = "dba") -> list:
    """Lista falsable de condiciones del criterio elegido (por que pasa/falla)."""
    items = []
    axis_name = ["X (ancho)", "Y (largo)", "Z (alto)"][axis]

    # Reglas de array por criterio (spec del usuario, 9 Sep 2026):
    #   DBA  = >=2 subs ADELANTE y >=2 subs ATRAS (minimo 4, 2+2, todos subs).
    #   CABS = >=2 subs ATRAS + una fuente ADELANTE de cualquier tipo (puede ser
    #          Full Range). Asi: FR atras -> ninguno pasa; FR adelante -> solo CABS.
    n_front_subs = len(fronts)
    n_rear_subs = len(rears)
    n_front_any = sum(1 for r in roles if r.at_front)
    if criterion == "cabs":
        ok_arr = n_rear_subs >= 2 and n_front_any >= 1
        arr_txt = (
            f"CABS en {axis_name}: {n_rear_subs} sub(s) atras (min. 2) + "
            f"{n_front_any} fuente(s) adelante (puede ser Full Range)."
            if ok_arr else
            f"CABS necesita >=2 subs ATRAS ({n_rear_subs}) y una fuente ADELANTE "
            f"({n_front_any}, cualquier tipo) en {axis_name}.")
    else:  # dba
        ok_arr = n_front_subs >= 2 and n_rear_subs >= 2
        arr_txt = (
            f"DBA en {axis_name}: {n_front_subs} subs adelante + {n_rear_subs} "
            f"atras (min. 2+2)."
            if ok_arr else
            f"DBA necesita >=2 subs ADELANTE ({n_front_subs}) y >=2 ATRAS "
            f"({n_rear_subs}) en {axis_name}.")
    items.append({"key": "opposing", "ok": bool(ok_arr), "critical": True,
                  "text": arr_txt})

    tau_ideal = L / c
    ok_drive, drive_txt = _check_rear_drive(rears, tau_ideal)
    if criterion == "cabs":
        # CABS: el trasero es MANEJADO (absorbe la onda), su drive no tiene por que
        # ser el DBA canonico L/c. El criterio se juzga por el COLAPSO de la
        # respuesta (planitud/varianza), no por el retardo -> rear_drive informativo.
        items.append({
            "key": "rear_drive", "ok": True, "critical": False,
            "text": "Modo CABS: trasero manejado (se juzga por el colapso de la "
                    "respuesta, no por el retardo L/c). " + drive_txt})
    else:
        items.append({"key": "rear_drive", "ok": ok_drive, "critical": True,
                      "text": drive_txt})

    f_max_alias = _alias_fmax_from_roles(fronts, dims, axis, c)
    ok_alias = (not np.isfinite(f_max_alias)) or f_max_alias >= min(fmax, band_hi) - 1e-6
    if np.isfinite(f_max_alias):
        alias_txt = (f"Espaciado de subs: f_max = c/d ≈ {f_max_alias:.0f} Hz "
                     "(el CABS ecualiza hasta ahi; arriba hay aliasing espacial).")
    else:
        alias_txt = ("Un solo sub por pared: sin grilla transversal "
                     "(no hay control de la onda plana fuera del eje).")
    items.append({"key": "spacing", "ok": bool(ok_alias), "critical": False,
                  "text": alias_txt})

    n_front_fr = sum(1 for r in roles if r.at_front and not r.is_sub)
    ok_count = (len(fronts) + len(rears)) >= 4
    fr_txt = (f" + {n_front_fr} full-range adelante" if n_front_fr else "")
    items.append({
        "key": "count", "ok": ok_count, "critical": False,
        "text": (f"{len(fronts)}+{len(rears)} subs{fr_txt}: "
                 + ("array denso." if ok_count else
                    "un array más denso (≥2 por pared) controla mejor la onda plana.")),
    })

    items.append({
        "key": "metrics", "ok": True, "critical": False,
        "text": (f"Planitud σ|H|: {real['flat']:.1f} dB (ideal "
                 f"{ideal['flat']:.1f}); varianza espacial: "
                 f"{real['spatial']:.1f} dB (ideal {ideal['spatial']:.1f}); "
                 f"decay: {real['decay']*1e3:.0f} ms (ideal "
                 f"{ideal['decay']*1e3:.0f})."),
    })
    return items


def _check_rear_drive(rears, tau_ideal, tol_rel=0.35):
    """¿El array trasero esta retardado ~L/c e invertido respecto del frente?"""
    if not rears:
        return False, "Sin array trasero: no hay drive CABS que evaluar."
    n_baked = sum(1 for r in rears
                  if getattr(r.src, "response", None) is not None)
    if n_baked == len(rears):
        return True, ("Trasero con curva de drive (LS/manejado): "
                      "retardo+inversion horneados en la respuesta.")
    delays = [float(getattr(r.src, "delay_s", 0.0)) for r in rears]
    pols = [int(getattr(r.src, "polarity", 1)) for r in rears]
    d_mean = float(np.mean(delays)) if delays else 0.0
    inverted = all(p < 0 for p in pols)
    delay_ok = abs(d_mean - tau_ideal) <= tol_rel * tau_ideal
    ok = delay_ok and inverted
    txt = (f"Drive trasero: retardo medio {d_mean*1e3:.1f} ms "
           f"(ideal L/c = {tau_ideal*1e3:.1f} ms), "
           f"polaridad {'invertida' if inverted else 'NO invertida'}. "
           + ("OK." if ok else
              "CABS pide retardo ≈ L/c e inversion de polaridad en el trasero."))
    return ok, txt


if __name__ == "__main__":
    dims = (7.8, 4.1, 2.8)
    specs = _dba.build_dba_sources(dims, axis=1, n_x=2, n_z=2, drive="naive",
                                   fmax=120.0)
    srcs = [OmniSource(sp["pos"], Q=sp["Q"], label=sp["label"],
                       source_type="subwoofer", delay_s=sp["delay_s"],
                       polarity=sp["polarity"], response=sp["response"])
            for sp in specs]
    r = evaluate_cabs(srcs, dims, (3.9, 2.05, 1.4), axis=1, fmax=120.0)
    print(f"config DBA valida: passed={r['passed']}  "
          f"flat={r['flat_real']:.2f} (ideal {r['flat_ideal']:.2f})  "
          f"decay={r['decay_real']*1e3:.0f} ms (ideal {r['decay_ideal']*1e3:.0f})")
    for it in r["checklist"]:
        print(f"  [{'x' if it['ok'] else ' '}] {it['text']}")
