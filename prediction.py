"""
prediction.py
=============

Motor de prediccion de geometria de recinto a partir del uso previsto.

Idea: el usuario describe QUE necesita (uso, capacidad, restricciones) y el
soft propone dimensiones razonables. Estrategia "ratios + verificacion FEM
ligera":

  1. Para cada ratio clasico (Bolt, Bonello, Louden) se escala a llegar al
     volumen minimo objetivo respetando restricciones de planta/altura.
  2. Se corre un FEM lite (n_per_meter chico, pocos modos) sobre cada
     candidato en paralelo (ThreadPool: scipy/numpy liberan el GIL para
     LAPACK y la factorizacion sparse).
  3. Se scorea cada candidato con un promedio ponderado (RT60 vs objetivo,
     uniformidad modal en bandas bajas, volumen vs minimo, ajuste a
     restricciones).
  4. Se devuelven los 3 resultados ordenados por score para que el panel los
     muestre como cards y el usuario elija cual aplicar.

Diseño v1: presets hardcoded, sin guardado custom (la UI permite editar el
RT60 objetivo y V/persona despues de elegir el uso, lo que cubre el 80% del
valor sin la complejidad de un sistema de presets editables).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Callable
import math
import numpy as np

C0 = 343.0  # velocidad del sonido [m/s]


# ---------------------------------------------------------------------------
# Presets de uso (RT60 objetivo en bandas medias, V/persona tipico)
# ---------------------------------------------------------------------------
# Fuentes: Beranek "Concert Halls and Opera Houses", IEC 60268-16 (STI),
# Long "Architectural Acoustics", ANSI S12.60-2010 (aulas).
# `h_default` (T3, 16 Jun 2026): altura de techo por defecto del uso, en metros.
# Reemplaza al cap duro de 4 m: el usuario puede subirla/bajarla con "Override
# altura". Home theater / aula / estudio = 3 m (pedido del usuario); el resto
# son valores tipicos a ajustar.
USE_PRESETS = {
    "Sala de conferencias": {
        "rt60_500": 0.70,
        "v_per_person": 3.5,
        "h_default": 3.2,
        "programs": ["Voz hablada"],
        "default_program": "Voz hablada",
    },
    "Aula": {
        "rt60_500": 0.80,
        "v_per_person": 5.0,
        "h_default": 3.0,
        "programs": ["Voz hablada", "Voz amplificada"],
        "default_program": "Voz hablada",
    },
    "Estudio de grabacion (control room)": {
        "rt60_500": 0.35,
        "v_per_person": 15.0,
        "h_default": 3.0,
        "programs": ["Musica amplificada"],
        "default_program": "Musica amplificada",
    },
    "Estudio de grabacion (live room)": {
        "rt60_500": 0.55,
        "v_per_person": 20.0,
        "h_default": 3.5,
        "programs": ["Musica acustica", "Musica amplificada"],
        "default_program": "Musica acustica",
    },
    "Home theater": {
        "rt60_500": 0.40,
        "v_per_person": 10.0,
        "h_default": 3.0,
        "programs": ["Cine (PA)", "Musica amplificada"],
        "default_program": "Cine (PA)",
    },
    "Sala de musica de camara": {
        "rt60_500": 1.60,
        "v_per_person": 9.0,
        "h_default": 6.0,
        "programs": ["Musica acustica"],
        "default_program": "Musica acustica",
    },
    "Sala sinfonica": {
        "rt60_500": 2.00,
        "v_per_person": 9.0,
        "h_default": 12.0,
        "programs": ["Musica acustica"],
        "default_program": "Musica acustica",
    },
    "Sala polivalente": {
        "rt60_500": 1.20,
        "v_per_person": 7.0,
        "h_default": 5.0,
        "programs": ["Voz amplificada", "Musica acustica", "Musica amplificada", "Mixto"],
        "default_program": "Mixto",
    },
}

# Altura default si un uso no define h_default (fallback defensivo).
_USE_H_DEFAULT_FALLBACK = 3.0

DEFAULT_USE = "Sala polivalente"


# ---------------------------------------------------------------------------
# Biblioteca de ratios L:W:H (Largo:Ancho:Alto)
# ---------------------------------------------------------------------------
# Cada ratio es (L, W, H) sin unidades; despues se escala uniformemente para
# llegar al volumen objetivo y caer dentro de las restricciones.
# NOTA (16 Jun 2026): hasta v2.12 estos ratios estaban MAL ETIQUETADOS respecto
# de la literatura (Cox & D'Antonio). Correccion aplicada:
#   "Bolt"   (1:1.4:1.9)  era en realidad  Louden
#   "Bonello"(1:1.26:1.59) era en realidad Bolt
#   "Louden" (1:1.6:2.33)  era en realidad Sepmeyer
# + se agrego Cox (1:1.56:1.86). Las predicciones NO se persisten con el nombre
# del ratio, asi que el relabel no rompe `.room` viejos.
RATIO_LIBRARY = [
    {
        "name": "Louden",
        "ratio": (1.90, 1.40, 1.00),       # 1 : 1.40 : 1.90
        "note": "Ratio de Louden (1:1.4:1.9); buena distribucion modal en salas medianas.",
    },
    {
        "name": "Bolt",
        "ratio": (1.59, 1.26, 1.00),       # 1 : 1.26 : 1.59
        "note": "Ratio clasico de Bolt (1:1.26:1.59); proporciones compactas.",
    },
    {
        "name": "Sepmeyer",
        "ratio": (2.33, 1.60, 1.00),       # 1 : 1.60 : 2.33
        "note": "Ratio de Sepmeyer (1:1.6:2.33); sala alargada con buena separacion modal.",
    },
    {
        "name": "Cox",
        "ratio": (1.86, 1.56, 1.00),       # 1 : 1.56 : 1.86
        "note": "Ratio de Cox & D'Antonio (1:1.56:1.86); optimizado para minimizar "
                "coloracion modal en salas chicas/medianas.",
    },
    {
        # A33 (criterios_room_geom_fuente.md): caja BBC/Walker de buena distribucion
        # modal LF -> w/h=1.14+-0.1, l/h=1.4+-0.14. Tomamos el optimo de la caja, que
        # casi coincide con Rindel/Meissner A (1:1.20:1.45). Aporta una sala mas
        # compacta/cuadrada que los otros 4, buena para recintos chicos de reproduccion.
        "name": "BBC/Rindel",
        "ratio": (1.40, 1.14, 1.00),       # 1 : 1.14 : 1.40
        "note": "Ratio BBC/Walker (1:1.14:1.4), optimo de la caja de tolerancia "
                "w/h=1.14, l/h=1.4; ~= Rindel/Meissner A. Buena distribucion modal "
                "LF en salas chicas de reproduccion.",
    },
]


# ---------------------------------------------------------------------------
# Rango constructivo por defecto de la altura de muros.
# ---------------------------------------------------------------------------
# Una jornada tipica de albanileria coloca ~13 hiladas de ladrillo (~10 cm cada
# una) -> 1.3 m/dia. Una pared de 5 m son ~3 jornadas con el riesgo y costo
# que eso implica (apuntalamiento, andamios, complejizacion estructural).
#
# Por eso los candidatos generados por el predictor se confinan a [2.5, 4.0] m
# salvo que el usuario amplie el techo explicitamente desde la UI (campo
# "Altura max"). Si quiere un techo de 10 m, lo tipea en el spinbox.
# El piso (2.5 m) es invariante salvo que el usuario fije un techo aun mas
# bajo (en cuyo caso piso=techo respetando su decision).
_DEFAULT_HEIGHT_MIN = 2.5   # m
_DEFAULT_HEIGHT_MAX = 4.0   # m


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------
@dataclass
class PredictInputs:
    """Entradas del usuario validadas."""
    use: str
    program: str
    priority: float            # 0.0 = inteligibilidad, 1.0 = envoltura
    capacity: int              # personas
    m2_per_person: float       # area por persona
    rt60_target: float         # s @ 500 Hz
    v_per_person: float        # m3/p
    width_max: Optional[float] = None    # m, None = sin limite
    length_max: Optional[float] = None
    height_max: Optional[float] = None
    parallel_walls: str = "permitir"      # "permitir" | "evitar"
    roof_shape: str = "plano"             # "plano" | "inclinado" | "abovedado"
    # Absorcion de las superficies (gate de materiales del panel de Prediccion).
    #   "target"   = usar rt60_target tipeado (el programa elige por uso).
    #   "uniform"  = mismo alpha en las 6 caras (alpha_uniform).
    #   "materials"= materiales reales por superficie (surface_alpha = 3 dicts
    #                {banda: alpha} para piso/paredes/techo, del catalogo).
    # En los modos != "target" el RT60 lo DETERMINAN los materiales, POR
    # candidato (Sabine hacia adelante: cada geometria da su propio RT60).
    alpha_mode: str = "target"
    alpha_uniform: float = 0.31
    surface_alpha: Optional[tuple] = None   # (af, aw, ac) dicts {banda: alpha}

    @property
    def audience_area(self) -> float:
        return self.capacity * self.m2_per_person

    @property
    def v_target(self) -> float:
        """Volumen objetivo: maximo entre V/persona y un piso por audiencia."""
        v_from_pp = self.capacity * self.v_per_person
        # Piso adicional: que la planta cubra al menos la audiencia con 2.5m de altura
        v_from_area = self.audience_area * 2.5
        return max(v_from_pp, v_from_area)


@dataclass
class Candidate:
    """Una alternativa de geometria generada."""
    ratio_name: str
    ratio_note: str
    width: float          # m (X)
    length: float         # m (Y)
    height: float         # m (Z)
    n_walls: int = 4
    taper: float = 0.0
    twist: float = 0.0
    arch_height: float = 0.0
    roof_type: str = "flat"   # "flat" | "arch" | "shed"
    fits_constraints: bool = True
    actual_ratio: tuple = (0.0, 0.0, 0.0)   # (L, W, H) re-normalizado
    # Variante "control negativo": ratio deliberadamente malo para que el
    # usuario vea visualmente por que los buenos ratios son buenos.
    is_negative_control: bool = False

    @property
    def volume(self) -> float:
        # Aprox: prisma rectangular. Para arch/shed le sumamos el bulto del techo
        # (~0.5 * arch_height * area_planta).
        v = self.width * self.length * self.height
        if self.roof_type in ("arch", "shed") and self.arch_height > 0:
            v += 0.5 * self.arch_height * self.width * self.length
        return v


@dataclass
class FemLiteResult:
    """Resultado de la verificacion FEM ligera (rango ~30-125 Hz)."""
    freqs: np.ndarray = field(default_factory=lambda: np.zeros(0))
    n_modes_low: int = 0            # modos en el rango cubierto
    bonello_ok_bands: int = 0       # bandas 1/3 oct con >= 5 modos (referencia)
    total_bands: int = 0
    # A3 (Bonello completo): densidad modal no-decreciente por 1/3-oct hasta 200 Hz.
    bonello_monotonic: bool = False   # True si los conteos por banda no decrecen
    bonello_score: float = 0.0        # % de transiciones no-decrecientes (0-100)
    # A6 (FSI): Frequency Spacing Index psi(25) de Rindel — varianza relativa del
    # espaciado modal. psi=1 ideal, ~1.3 mejor real, >1.6 evitar. nan si < 3 modos.
    fsi: float = float("nan")
    # Bolt-spacing por bins de 5 Hz
    n_spacings: int = 0
    n_good_spacings: int = 0
    n_clumps: int = 0
    n_gaps: int = 0
    rt60_sabine: float = 0.0
    alpha_required: float = 0.0
    # B. Modal Q audibility: cuantos modos serian "audibles individualmente"
    n_audible_modes: int = 0        # modos con Q > 30 (referencia, proxy viejo)
    n_audible_fazenda: int = 0      # C9: audibles por umbral Fazenda ARTIFICIAL (peor caso)
    n_audible_fazenda_music: int = 0  # C9: audibles por umbral Fazenda MUSICA (escucha real)
    n_total_modes_eval: int = 0     # total de modos en 30-125 Hz para %
    # C. Schroeder coverage
    schroeder_freq: float = 0.0     # Hz, calculado con rt60_target
    n_modes_below_schroeder: int = 0
    # F. Distancia critica
    d_crit: float = 0.0             # m, con rt60_target
    d_worst: float = 0.0            # m, sqrt(L^2+W^2)/2
    # G. Bass support proxy
    n_modes_below_80hz: int = 0
    elapsed_s: float = 0.0
    error: Optional[str] = None


@dataclass
class Prediction:
    """Resultado final: candidato + scoring.

    Los 13 sub-scores se agrupan en 5 categorias acusticas + practicas. La
    UI los muestra agrupados; el score_total los combina con pesos
    condicionales por uso (voz / musica / mixto).
    """
    candidate: Candidate
    fem: FemLiteResult
    # --- Grupo MODAL ---
    score_rt60: float = 0.0          # feasibility: alpha en rango razonable
    score_uniformity: float = 0.0    # Bolt-spacing por bins de 5 Hz
    score_modal_q: float = 0.0       # % modos con Q <= 30 (no audibles individualmente)
    score_schroeder: float = 0.0     # cobertura de modos bajo f_Schroeder
    score_fsi: float = 0.0           # A6: Frequency Spacing Index psi(25) de Rindel
    score_bonello: float = 0.0       # A3: densidad modal no-decreciente (Bonello)
    score_robustness: float = 0.0    # margen feasibility (sensibilidad materiales)
    # --- Grupo VOZ (peso 0 para usos de musica) ---
    score_sti: float = 0.0           # STI por Bradley
    score_alcons: float = 0.0        # %Alcons por Peutz
    score_dcrit: float = 0.0         # distancia critica vs receptor tipico
    # --- Grupo MUSICA (peso 0 para usos de voz) ---
    score_bass: float = 0.0          # BR proxy basado en densidad modal baja
    # --- Grupo PRACTICO ---
    score_volume: float = 0.0
    score_aspect: float = 0.0
    score_fits: float = 0.0
    score_planta: float = 0.0        # aprovechamiento de planta
    score_constr: float = 0.0        # constructabilidad
    # --- Score total ---
    score_total: float = 0.0
    # --- Mensajes humano-legibles para la card ---
    feasibility_msg: str = ""        # "α req=0.13 (madera dura)"
    aspect_msg: str = ""             # "L/W=1.6 (ok), H/W=0.5 (ok)"
    sti_msg: str = ""                # "STI=0.67 (bueno) · %Alcons=5.2%"
    dcrit_msg: str = ""              # "d_crit=2.1 m · receptor a 4.8 m → reverberante"
    bass_msg: str = ""               # "8 modos <80Hz · soporte bajo"
    planta_msg: str = ""             # "67% utilizado (24/36 m²)"
    constr_msg: str = ""             # "OK · muros 4.3 m"
    robustness_msg: str = ""         # "margen α=0.07 · sólido"


# ---------------------------------------------------------------------------
# Generacion de candidatos
# ---------------------------------------------------------------------------
def _scale_ratio_to_volume(ratio_LWH: tuple, v_target: float) -> tuple:
    """Escala uniformemente (L, W, H) para que LxWxH == v_target.
    Devuelve (W, L, H) con W=ancho(X), L=largo(Y), H=alto(Z).
    """
    rL, rW, rH = ratio_LWH
    s = (v_target / (rL * rW * rH)) ** (1.0 / 3.0)
    return (rW * s, rL * s, rH * s)


def _apply_constraints(W: float, L: float, H: float,
                       w_max: Optional[float], l_max: Optional[float],
                       h_max: Optional[float]) -> tuple:
    """Aplica caps de planta/altura escalando uniformemente.
    Devuelve (W, L, H, fits) donde fits=True si no hubo que recortar.
    """
    s = 1.0
    fits = True
    if w_max is not None and W > w_max:
        s = min(s, w_max / W)
        fits = False
    if l_max is not None and L > l_max:
        s = min(s, l_max / L)
        fits = False
    if h_max is not None and H > h_max:
        s = min(s, h_max / H)
        fits = False
    return (W * s, L * s, H * s, fits)


def _clamp_height_constructive(W: float, L: float, H: float,
                                v_target: float,
                                user_height_max: Optional[float]) -> tuple:
    """Encajona la altura H en el rango constructivo y reescala W y L
    preservando su proporcion para conservar el volumen objetivo.

    `user_height_max` es el techo EFECTIVO que pasa generate_candidates: el
    override del usuario si lo fijó, o el `h_default` del USO (T3). Puede ser
    mayor a 4 m (p.ej. sinfónica). El piso 2.5 m se mantiene salvo que el techo
    sea aún más bajo (en cuyo caso piso=techo). Si llega None (uso programático
    directo), cae al fallback `_DEFAULT_HEIGHT_MAX`.

    Al recortar H se rompe el ratio textbook L:W:H del candidato; W y L se
    re-escalan ((s = sqrt((v_target / H_clamped) / (W*L)))) para mantener
    W*L*H == v_target y la proporcion W:L original.
    """
    h_max_eff = (user_height_max if user_height_max is not None
                 else _DEFAULT_HEIGHT_MAX)
    h_min_eff = min(_DEFAULT_HEIGHT_MIN, h_max_eff)

    if h_min_eff <= H <= h_max_eff:
        return W, L, H

    H_clamped = max(h_min_eff, min(h_max_eff, H))
    # Reescalar W y L manteniendo W:L para preservar el volumen objetivo.
    wl_target = v_target / max(H_clamped, 1e-6)
    s = (wl_target / max(W * L, 1e-9)) ** 0.5
    return W * s, L * s, H_clamped


def generate_candidates(inputs: PredictInputs) -> list:
    """Genera un candidato por cada ratio de RATIO_LIBRARY (hoy 5:
    Louden/Bolt/Sepmeyer/Cox/BBC-Rindel), escalados al V objetivo y respetando
    las restricciones. `predict()` despues muestra los 3 mejores por score."""
    candidates = []
    v_target = inputs.v_target

    # Modificadores compartidos por "Evitar paredes paralelas" y "Forma de techo"
    taper = 0.15 if inputs.parallel_walls == "evitar" else 0.0
    if inputs.roof_shape == "abovedado":
        roof_type = "arch"
        # arch_height ~ 15% de la altura, capeado en 0.8 m
    elif inputs.roof_shape == "inclinado":
        roof_type = "shed"
    else:
        roof_type = "flat"

    # Techo efectivo (T3): si el usuario fijó height_max, manda; si no, el
    # default del USO (reemplaza el viejo cap duro de 4 m).
    h_eff = inputs.height_max
    if h_eff is None:
        h_eff = USE_PRESETS.get(inputs.use, {}).get(
            "h_default", _USE_H_DEFAULT_FALLBACK)

    for entry in RATIO_LIBRARY:
        rL, rW, rH = entry["ratio"]
        W, L, H = _scale_ratio_to_volume(entry["ratio"], v_target)
        # Encajonar H en el rango constructivo (default 2.5-4 m, salvo que el
        # usuario amplie el techo). Reescala W y L para conservar V_target.
        # Rompe deliberadamente el ratio L:W:H textbook a favor de una sala
        # construible. El nombre del ratio se mantiene como referencia de la
        # proporcion L:W resultante.
        W, L, H = _clamp_height_constructive(W, L, H, v_target, h_eff)
        W, L, H, fits = _apply_constraints(W, L, H,
                                            inputs.width_max,
                                            inputs.length_max,
                                            inputs.height_max)
        # arch_height despues de fijar altura
        arch_h = 0.0
        if roof_type == "arch":
            arch_h = min(0.15 * H, 0.8)
        elif roof_type == "shed":
            arch_h = min(0.20 * H, 1.0)

        cand = Candidate(
            ratio_name=entry["name"],
            ratio_note=entry["note"],
            width=round(W, 2),
            length=round(L, 2),
            height=round(H, 2),
            n_walls=4,
            taper=taper,
            twist=0.0,
            arch_height=arch_h,
            roof_type=roof_type,
            fits_constraints=fits,
            actual_ratio=(rL, rW, rH),
        )
        candidates.append(cand)
    return candidates


# ---------------------------------------------------------------------------
# Verificacion FEM ligera
# ---------------------------------------------------------------------------
# Bandas de 1/3 octava centradas entre 31.5 y 125 Hz. El limite superior
# (125 Hz) viene del alcance valido del FEM lite con n_per_meter=2.0:
# fmax = c / (6*hmax) = 343 / (6*0.5) ~ 114 Hz, redondeado a la banda
# estandar de 125 Hz. Para analisis arriba de esta banda el usuario corre
# el FEM completo en la pestaña Acustica.
_THIRD_OCTAVE_CENTERS = [31.5, 40, 50, 63, 80, 100, 125]


def _build_surface_mesh(cand: Candidate):
    """Construye la malla superficial triangulada del candidato."""
    from geometry import make_room
    v, t, _e, _n = make_room(
        width=cand.width, length=cand.length, height=cand.height,
        n_walls=cand.n_walls, taper=cand.taper, twist=cand.twist,
        arch_height=cand.arch_height, roof_type=cand.roof_type,
        # subdiv_levels=0 para que la malla sea topologicamente consistente
        # con las paredes (sin huecos para gmsh/voxel).
        subdiv_levels=0,
    )
    return v, t


def _shoebox_areas(cand: "Candidate") -> tuple:
    """(S_piso, S_techo, S_paredes, V) para un candidato (caja)."""
    W, L, H = cand.width, cand.length, cand.height
    floor = ceil = W * L
    walls = 2.0 * (W + L) * H
    return floor, ceil, walls, cand.volume


def effective_rt60(inputs: "PredictInputs", cand: "Candidate") -> float:
    """RT60 representativo de ESTE candidato segun la absorcion elegida (opcion
    A: los materiales DETERMINAN el RT60, por candidato).

    - "target":   el rt60_target tipeado (el programa elige por uso).
    - "uniform":  Sabine con alpha uniforme en las 6 caras (alpha_uniform).
    - "materials": Sabine con alpha POR BANDA de los materiales por superficie
      (surface_alpha = (af, aw, ac), cada uno {banda: alpha}); el representativo
      para el scoring = promedio del RT a 500 y 1000 Hz.
    """
    mode = getattr(inputs, "alpha_mode", "target") or "target"
    if mode == "target":
        return inputs.rt60_target
    floor, ceil, walls, V = _shoebox_areas(cand)
    if mode == "uniform":
        a = max(1e-3, float(inputs.alpha_uniform))
        return 0.161 * V / max(a * (2.0 * floor + walls), 1e-6)
    # materials: alpha por banda por superficie -> RT representativo (500/1k)
    af, aw, ac = inputs.surface_alpha or ({}, {}, {})
    rts = []
    for b in (500, 1000):
        A = (af.get(b, 0.03) * floor + ac.get(b, 0.03) * ceil
             + aw.get(b, 0.03) * walls)
        rts.append(0.161 * V / max(A, 1e-6))
    return sum(rts) / len(rts) if rts else inputs.rt60_target


def verify_candidate_fem(cand: Candidate,
                         n_per_meter: float = 2.0,
                         n_modes: int = 40,
                         alpha_default: float = 0.10,
                         rt60_target: float = 1.0,
                         surface=None) -> FemLiteResult:
    """Corre FEM lite sobre un candidato y devuelve el resumen acustico.

    `rt60_target` se usa para calcular alpha_required (feasibility) — la
    absorcion media que el recinto necesitaria para llegar al target.

    `surface` (v, t): si viene, el FEM corre sobre ESA malla (la geometria
    real renderizada — planta custom + cortes laterales) en vez de
    reconstruir una caja con make_room. Es el Camino B de "Evaluar mi diseño"
    para formas irregulares.
    """
    import time as _time
    import acoustic_analysis as aa
    t0 = _time.time()
    result = FemLiteResult()
    try:
        v, t = surface if surface is not None else _build_surface_mesh(cand)
        # FEM con malla gruesa
        sol = aa.run_fem_modal(v, t, n_modes=n_modes,
                                n_per_meter=n_per_meter)
        # Descartar el modo 0 (presion uniforme): solve_modes ya lo recorta,
        # pero por compatibilidad filtramos modos < 5 Hz.
        freqs = np.asarray(sol.freqs, dtype=float)
        freqs = freqs[freqs > 5.0]
        freqs.sort()
        result.freqs = freqs

        # ---- Bandas Bonello (referencia, ya no se usa para score) ----
        n_low = 0
        ok_bands = 0
        total_bands = 0
        counts_by_band = []             # A3: conteo por 1/3-oct hasta 200 Hz
        for fc in _THIRD_OCTAVE_CENTERS:
            lo = fc / (2 ** (1 / 6))
            hi = fc * (2 ** (1 / 6))
            count = int(((freqs >= lo) & (freqs < hi)).sum())
            n_low += count
            total_bands += 1
            if count >= 5:
                ok_bands += 1
            if fc <= 200.0:
                counts_by_band.append(count)
        result.n_modes_low = n_low
        result.bonello_ok_bands = ok_bands
        result.total_bands = total_bands

        # ---- A3: criterio Bonello de densidad NO-DECRECIENTE (hasta 200 Hz) ----
        # Bonello: la cantidad de modos por 1/3-oct debe crecer (u horizontal) al
        # subir de banda. Empezamos en la primera banda CON modos (las vacias de
        # abajo no cuentan: 0->n es trivialmente no-decreciente).
        first = next((i for i, n in enumerate(counts_by_band) if n > 0), None)
        if first is not None and len(counts_by_band) - first >= 2:
            seq = counts_by_band[first:]
            trans = len(seq) - 1
            non_dec = sum(1 for i in range(1, len(seq)) if seq[i] >= seq[i - 1])
            result.bonello_monotonic = (non_dec == trans)
            result.bonello_score = 100.0 * non_dec / max(trans, 1)
        else:
            # < 2 bandas con modos: no evaluable -> neutro.
            result.bonello_monotonic = False
            result.bonello_score = 0.0

        # ---- A6: Frequency Spacing Index psi(25) de Rindel ----
        # Varianza relativa del espaciado de los primeros 25 modos. Mide cuan
        # pareja es la distribucion modal (independiente de V y de la absorcion;
        # discrimina geometria pura). nan si hay < 3 modos.
        import modal_metrics as _mm
        result.fsi = _mm.modal_fsi(freqs, n=25)

        # ---- Bolt-spacing por bins absolutos (mas robusto que ratio) ----
        # Idea: la densidad modal crece con f^2 (formula de Schroeder), asi
        # que un threshold relativo (ratio < 5%) se vuelve TRIVIAL a alta
        # frecuencia (a 125 Hz dos modos a 6 Hz ya son < 5% pero no son grumo
        # perceptual). Usamos bins ABSOLUTOS de 5 Hz entre 30-125 Hz (19 bins):
        #
        #   bin con 0 modos       -> hueco (zona "sorda" sin resonancia)
        #   bin con 1-2 modos     -> bueno (densidad pareja)
        #   bin con >=3 modos     -> grumo (resonancia fuerte localizada)
        #
        # Penalty mayor por grumos que por huecos: el grumo CAUSA coloracion
        # audible; el hueco se cubre con difusion/reflectores.
        if len(freqs) >= 2:
            BIN_W = 5.0
            f_lo, f_hi = 30.0, 125.0
            n_bins = int((f_hi - f_lo) / BIN_W)
            in_range = freqs[(freqs >= f_lo) & (freqs <= f_hi)]
            if len(in_range) >= 2:
                bin_idx = ((in_range - f_lo) / BIN_W).astype(int)
                bin_idx = bin_idx[(bin_idx >= 0) & (bin_idx < n_bins)]
                counts = np.bincount(bin_idx, minlength=n_bins)
                clumps = int((counts >= 3).sum())
                gaps = int((counts == 0).sum())
                good = int(((counts == 1) | (counts == 2)).sum())
                result.n_spacings = n_bins      # total de bins evaluados
                result.n_good_spacings = good
                result.n_clumps = clumps
                result.n_gaps = gaps

        # ---- RT60 y alpha_required ----
        # Sabine: RT60 = 0.161 * V / (alpha * S)
        W, L, H = cand.width, cand.length, cand.height
        S = 2.0 * (W * L + W * H + L * H)
        V = cand.volume
        result.rt60_sabine = 0.161 * V / max(alpha_default * S, 1e-6)
        if rt60_target > 0:
            result.alpha_required = 0.161 * V / (rt60_target * max(S, 1e-6))

        # ---- B. Modal Q audibility ----
        # Q = pi * f * RT60 / 6.9 (-3dB bandwidth de un modo amortiguado)
        # Q > 30 -> resonancia audible individualmente (zumbido)
        # Q < 10 -> bien amortiguado, integra al campo difuso
        # Usamos rt60_target porque ese es el RT60 que la sala VA A TENER cuando
        # se elijan materiales para llegar al target.
        modes_eval = freqs[(freqs >= 20.0) & (freqs <= 200.0)]
        if rt60_target > 0 and len(modes_eval) > 0:
            Q_values = np.pi * modes_eval * rt60_target / 6.9
            result.n_audible_modes = int((Q_values > 30.0).sum())   # referencia (Q>30)
            result.n_total_modes_eval = len(modes_eval)
            # C9: umbral perceptual de Fazenda (2015). Un modo colorea si su
            # decaimiento T60 supera el umbral(f). En el path lite el T60 de cada
            # modo es rt60_target (uniforme), asi que comparamos contra la curva.
            # Exponemos AMBAS curvas: artificial (peor caso) y musica (escucha real).
            import modal_metrics as _mm
            thr_art = _mm.fazenda_modal_threshold(modes_eval, "artificial")
            thr_mus = _mm.fazenda_modal_threshold(modes_eval, "music")
            result.n_audible_fazenda = int((rt60_target > thr_art).sum())
            result.n_audible_fazenda_music = int((rt60_target > thr_mus).sum())

        # ---- C. Schroeder coverage ----
        # f_s = 2000 * sqrt(RT60/V). Cuantos modos hay debajo determina si la
        # sala es "modal" (modos discretos coloreando) o "estadistica" (difusa).
        if rt60_target > 0:
            f_s = 2000.0 * np.sqrt(rt60_target / max(V, 1e-3))
            result.schroeder_freq = float(f_s)
            result.n_modes_below_schroeder = int((freqs <= f_s).sum())

        # ---- F. Distancia critica ----
        # d_crit = 0.057 * sqrt(V * Q / RT60), Q=1 omni.
        # d_worst = sqrt(L^2 + W^2) / 2 (receptor a media diagonal del piso).
        if rt60_target > 0:
            result.d_crit = 0.057 * np.sqrt(V / rt60_target)
            result.d_worst = 0.5 * np.sqrt(W ** 2 + L ** 2)

        # ---- G. Bass support: modos en banda baja ----
        result.n_modes_below_80hz = int((freqs <= 80.0).sum())
    except Exception as e:
        result.error = str(e)
    finally:
        result.elapsed_s = _time.time() - t0
    return result


def verify_candidates_parallel(candidates: list,
                                n_per_meter: float = 2.0,
                                n_modes: int = 40,
                                alpha_default: float = 0.10,
                                rt60_target: float = 1.0,
                                inputs: Optional["PredictInputs"] = None,
                                progress: Optional[Callable[[str], None]] = None
                                ) -> list:
    """Corre FEM lite en paralelo (ThreadPool) sobre los candidatos.

    Si `inputs` viene con alpha_mode != "target", el RT60 de cada candidato lo
    determinan los materiales (Sabine por geometria); si no, usa el escalar
    `rt60_target` (compat con benches/llamadores viejos).

    scipy.sparse.linalg.eigsh y la factorizacion LU liberan el GIL, por lo
    que ThreadPool da ~2-3x speedup en una maquina multi-core sin la
    complejidad de pickle/spawn de ProcessPool en una app PyQt.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if progress:
        progress(f"Verificando {len(candidates)} candidatos con FEM ligero...")

    def _rt_for(c):
        return effective_rt60(inputs, c) if inputs is not None else rt60_target

    results = [None] * len(candidates)
    with ThreadPoolExecutor(max_workers=min(3, len(candidates))) as ex:
        futs = {
            ex.submit(verify_candidate_fem, c, n_per_meter, n_modes,
                      alpha_default, _rt_for(c)): i
            for i, c in enumerate(candidates)
        }
        done = 0
        for fut in as_completed(futs):
            i = futs[fut]
            results[i] = fut.result()
            done += 1
            if progress:
                progress(f"Candidato {done}/{len(candidates)} listo "
                          f"({results[i].elapsed_s:.1f}s)")
    return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _score_volume(cand: Candidate, v_target: float) -> float:
    """Score de volumen: 100 si V en [v_target, 1.5*v_target]; 0 si < 0.8*v_target."""
    V = cand.volume
    if V <= 0:
        return 0.0
    ratio = V / max(v_target, 1e-6)
    if ratio < 0.80:
        return 0.0
    if ratio < 1.0:
        # interp lineal 0.80 -> 60, 1.0 -> 100
        return 60.0 + (ratio - 0.80) / 0.20 * 40.0
    if ratio <= 1.5:
        return 100.0
    # demasiado grande: penalizamos suave
    return max(0.0, 100.0 - (ratio - 1.5) * 40.0)


# Categorias de materiales por rango de alpha (absorcion promedio).
# La fuente es la tabla estandar de Beranek/Long. Cada categoria es lo
# que un acustico veria como "tipica" para ese alpha.
_ALPHA_CATEGORIES = [
    (0.00, 0.05, "hormigón pulido / vidrio pesado"),
    (0.05, 0.10, "yeso pintado / hormigón visto"),
    (0.10, 0.15, "madera dura / panel rigido"),
    (0.15, 0.25, "madera + alfombra parcial"),
    (0.25, 0.40, "panel acústico + cortinas"),
    (0.40, 0.60, "paneles absorbentes en >50% de superficie"),
    (0.60, 1.01, "tratamiento absorbente extremo (cámara anecoica)"),
]


def _alpha_category(alpha: float) -> str:
    for lo, hi, name in _ALPHA_CATEGORIES:
        if lo <= alpha < hi:
            return name
    return "fuera de rango"


def _score_rt60_feasibility(fem: 'FemLiteResult',
                            rt60_target: float) -> tuple:
    """Score: que tan razonable es el alpha que la geometria necesita.

    Diseño:
      - alpha_required en [0.08, 0.30] (cubrible con materiales estandar) -> 100
      - alpha < 0.05  -> sala que NECESITA paredes ULTRA reflectivas (raro,
                         solo cuevas/catedrales) -> score baja
      - alpha > 0.40  -> sala que NECESITA tratamiento absorbente extremo
                         (estudios profesionales) -> score baja
      - alpha 0.05..0.08 -> medio penalizado (hormigon visto sirve)
      - alpha 0.30..0.40 -> medio penalizado (panel acustico)

    Devuelve (score, mensaje).
    """
    if fem.error or rt60_target <= 0:
        return 50.0, "RT60 target invalido"
    a = fem.alpha_required
    cat = _alpha_category(a)
    if 0.08 <= a <= 0.30:
        score = 100.0
    elif a < 0.05:
        # Mas lejos de 0.08 = peor. Lineal de 100 (a=0.05) a 0 (a=0.005).
        score = max(0.0, 100.0 * (a - 0.005) / (0.05 - 0.005))
    elif 0.05 <= a < 0.08:
        score = 70.0 + (a - 0.05) / 0.03 * 30.0
    elif 0.30 < a <= 0.40:
        score = 70.0 + (0.40 - a) / 0.10 * 30.0
    else:  # a > 0.40
        score = max(0.0, 100.0 * (0.60 - a) / 0.20)
    msg = f"α requerido = {a:.2f}  ·  {cat}"
    return score, msg


def _score_bolt_spacing(fem: FemLiteResult) -> float:
    """Score basado en distribucion modal por bins de 5 Hz (estilo Bolt).

    Diseño:
      - base = 100 * (bins buenos: 1-2 modos) / total_bins
      - penalty por grumos: -5 puntos por cada bin con >=3 modos (cap 25)
      - los huecos ya se reflejan en menos bins buenos (no double-penalize)

    Penalty mas suave (5 en vez de 8) y cap mas bajo (25 en vez de 40) para
    que la metrica no sature: queremos discriminar candidatos similares.

    Si no hay modos suficientes en rango (sala chica), devuelve 50 (neutro).
    """
    if fem.error:
        return 0.0
    if fem.n_spacings < 3:
        return 50.0
    base = 100.0 * fem.n_good_spacings / max(fem.n_spacings, 1)
    penalty = min(25.0, fem.n_clumps * 5.0)
    return max(0.0, base - penalty)


def _score_aspect(cand: Candidate) -> tuple:
    """Score de razonabilidad de la forma. Devuelve (score, mensaje).

    Rangos comodos (sala "normal" mueblable):
      - L/W   in [1.1, 2.5]  (mas = tunel, menos = casi cuadrada con modos pegados)
      - H/W   in [0.30, 0.70] (mas = sala 'pozo', menos = sala 'pancake')

    Score = avg(score_LW, score_HW) donde cada componente:
      - 100 si dentro del rango
      - cae a 30 en el doble del limite (saturado)
    """
    W, L, H = cand.width, cand.length, cand.height
    if W <= 0 or H <= 0:
        return 0.0, "dimensiones invalidas"
    # Aseguramos L >= W para que el ratio sea siempre >= 1
    lw = max(L / W, W / L)
    hw = H / W

    def _comfort(val, lo, hi):
        if lo <= val <= hi:
            return 100.0
        if val < lo:
            # Por debajo: ratio < lo, lineal hasta 0 en lo/2
            return max(30.0, 100.0 - (lo - val) / max(lo / 2, 0.01) * 70.0)
        # Por encima: hasta 2*hi cae a 30
        return max(30.0, 100.0 - (val - hi) / max(hi, 0.01) * 70.0)

    s_lw = _comfort(lw, 1.1, 2.5)
    s_hw = _comfort(hw, 0.30, 0.70)
    score = (s_lw + s_hw) / 2.0

    # Mensaje
    lw_lbl = "ok" if 1.1 <= lw <= 2.5 else ("túnel" if lw > 2.5 else "casi cuadrada")
    hw_lbl = "ok" if 0.30 <= hw <= 0.70 else ("pozo" if hw > 0.70 else "pancake")
    msg = f"L/W={lw:.1f} ({lw_lbl})  ·  H/W={hw:.2f} ({hw_lbl})"
    return score, msg


def _score_fits(cand: Candidate) -> float:
    return 100.0 if cand.fits_constraints else 30.0


# -------------------- Nuevos sub-scores (v3) --------------------
def _fazenda_stimulus_for(program: str) -> str:
    """Elige la curva de umbral de Fazenda segun el PROGRAMA de la sala (C9).

    - Musica / cine -> "music": el propio material musical enmascara el
      decaimiento modal -> umbral de ESCUCHA REAL (mas permisivo).
    - Voz (u otro)  -> "artificial": la voz casi no aporta energia LF que
      enmascare -> umbral ABSOLUTO / PEOR CASO (mas estricto, conservador).
    """
    p = (program or "").lower()
    if "musica" in p or "música" in p or "cine" in p:
        return "music"
    return "artificial"


def _score_modal_q(fem: FemLiteResult, stimulus: str = "artificial") -> float:
    """Score basado en cuantos modos NO colorean (umbral perceptual de Fazenda).

    C9: usa el umbral de decaimiento de Fazenda (2015) en vez del Q>30 fijo, que
    era sistematicamente demasiado laxo. La CURVA la elige el programa de la sala
    (`stimulus`: "artificial"=voz/peor caso, "music"=musica/escucha real). El
    campo `n_audible_modes` (Q>30) se conserva como referencia.

    Sala sin modos que colorean -> 100 (campo modal "suave")
    Sala con todos coloreando   -> 0   (cada modo zumba)
    """
    if fem.error or fem.n_total_modes_eval == 0:
        return 50.0
    n_aud = (fem.n_audible_fazenda_music if stimulus == "music"
             else fem.n_audible_fazenda)
    ok_modes = fem.n_total_modes_eval - n_aud
    return 100.0 * ok_modes / fem.n_total_modes_eval


def _score_fsi(fem: FemLiteResult) -> float:
    """A6: score del Frequency Spacing Index psi(25) de Rindel.

    psi mide la varianza relativa del espaciado modal (independiente de V y de
    la absorcion -> discrimina geometria pura). Mapeo por tramos a 0-100:
        psi <= 1.0  -> 100  (equiespaciado, ideal teorico)
        psi  = 1.3  ->  80  (mejor caso real alcanzable)
        psi  = 1.6  ->  40  (umbral "evitar" de Rindel)
        psi >= 2.0  ->   0  (distribucion muy despareja)
    nan (< 3 modos) -> 50  (no evaluable, neutro).
    """
    psi = fem.fsi
    if not np.isfinite(psi):
        return 50.0
    if psi <= 1.0:
        return 100.0
    if psi <= 1.3:
        return 100.0 - (psi - 1.0) / 0.3 * 20.0
    if psi <= 1.6:
        return 80.0 - (psi - 1.3) / 0.3 * 40.0
    if psi <= 2.0:
        return 40.0 - (psi - 1.6) / 0.4 * 40.0
    return 0.0


def _score_schroeder(fem: FemLiteResult, v_target: float) -> float:
    """Cobertura modal bajo f_Schroeder. Mas modos = menos coloracion.

    Para una sala tipica de 100-500 m³ esperamos ~30-150 modos bajo f_s.
    Score:
      - >=30 modos      -> 100 (campo bien poblado, sin huecos audibles)
      - 15..30          -> linear 50..100
      - <15             -> linear 0..50
    """
    if fem.error or fem.n_modes_below_schroeder == 0:
        return 0.0
    n = fem.n_modes_below_schroeder
    if n >= 30:
        return 100.0
    if n >= 15:
        return 50.0 + (n - 15) / 15.0 * 50.0
    return n / 15.0 * 50.0


def _score_sti(rt60_target: float) -> tuple:
    """STI por formula simplificada Bradley (sin SNR explicito, asume sala silenciosa).

    STI = 0.9482 - 0.1845 * ln(RT60). Clamp [0, 1].
    Score = mapping a bandas calidad:
        STI >= 0.75 -> 100 (excelente, voz nativa)
        STI >= 0.60 -> 80  (bueno, aula)
        STI >= 0.45 -> 50  (regular, sala mixta)
        STI >= 0.30 -> 20  (pobre, demasiado reverberante)
        else        -> 0   (inteligibilidad rota)
    """
    if rt60_target <= 0:
        return 0.0, "STI: target invalido"
    sti = max(0.0, min(1.0, 0.9482 - 0.1845 * np.log(rt60_target)))
    if sti >= 0.75:
        score = 100.0; label = "excelente"
    elif sti >= 0.60:
        score = 80.0 + (sti - 0.60) / 0.15 * 20.0; label = "bueno"
    elif sti >= 0.45:
        score = 50.0 + (sti - 0.45) / 0.15 * 30.0; label = "regular"
    elif sti >= 0.30:
        score = 20.0 + (sti - 0.30) / 0.15 * 30.0; label = "pobre"
    else:
        score = sti / 0.30 * 20.0; label = "no apto para voz"
    return score, f"STI = {sti:.2f} ({label})"


def _score_alcons(fem: FemLiteResult, rt60_target: float) -> tuple:
    """%Alcons por Peutz. Source omni Q=1, receptor en media diagonal.

    %Alcons = 200 * d^2 * RT60^2 / (V * Q),  capeado a 9*RT60 en campo reverberante.
    Score:
      < 3%   -> 100 (excelente)
      3-7%   -> 80
      7-11%  -> 50
      11-15% -> 20
      > 15%  -> 0
    """
    if fem.error or rt60_target <= 0 or fem.d_worst <= 0:
        return 50.0, "%Alcons: sin datos"
    V = fem.freqs.size > 0 and (200.0 * fem.d_worst ** 2 * rt60_target ** 2)
    # Recalculamos V de las dimensiones (esta en fem implícitamente vía d_crit)
    # Mejor: lo calcula prediction.predict() y se lo pasamos. Por ahora,
    # despejamos de d_crit: d_crit = 0.057*sqrt(V/RT60) -> V = (d_crit/0.057)^2 * RT60
    V_calc = (fem.d_crit / 0.057) ** 2 * rt60_target if fem.d_crit > 0 else 100.0
    alcons_peutz = 200.0 * fem.d_worst ** 2 * rt60_target ** 2 / max(V_calc, 1e-3)
    alcons_reverb = 9.0 * rt60_target
    # En campo reverberante (d > 3.16 * d_crit) la formula satura
    if fem.d_worst > 3.16 * fem.d_crit:
        alcons = alcons_reverb
    else:
        alcons = min(alcons_peutz, alcons_reverb)
    alcons = max(0.1, min(60.0, alcons))

    if alcons < 3.0:
        score = 100.0; label = "excelente"
    elif alcons < 7.0:
        score = 80.0 - (alcons - 3.0) / 4.0 * 30.0; label = "bueno"
    elif alcons < 11.0:
        score = 50.0 - (alcons - 7.0) / 4.0 * 30.0; label = "regular"
    elif alcons < 15.0:
        score = 20.0 - (alcons - 11.0) / 4.0 * 20.0; label = "pobre"
    else:
        score = 0.0; label = "ininteligible"
    return score, f"%Alcons = {alcons:.1f}% ({label})"


def _score_dcrit(fem: FemLiteResult, use: str) -> tuple:
    """Distancia critica vs receptor tipico.

    Para voz: queremos d_worst < 3 * d_crit (campo directo/transicion)
    Para musica: queremos d_worst > d_crit (algo de reverb para envolver)

    El parametro `use` controla cual heuristica aplicar (extraido del preset).
    """
    if fem.error or fem.d_crit <= 0 or fem.d_worst <= 0:
        return 50.0, "d_crit: sin datos"
    ratio = fem.d_worst / fem.d_crit
    is_voice = ("conferencia" in use.lower() or "aula" in use.lower())
    is_music = ("musica" in use.lower() or "sinfonica" in use.lower()
                or "camara" in use.lower())

    if is_voice:
        # voz: ratio ideal en [0.5, 3.0], saturado fuera
        if 0.5 <= ratio <= 3.0:
            score = 100.0; verdict = "campo directo OK"
        elif ratio < 0.5:
            score = max(0.0, 100.0 - (0.5 - ratio) / 0.5 * 50.0); verdict = "demasiado seco"
        else:
            score = max(0.0, 100.0 - (ratio - 3.0) / 3.0 * 80.0); verdict = "campo reverberante"
    elif is_music:
        # musica: ratio ideal en [1.5, 5.0]
        if 1.5 <= ratio <= 5.0:
            score = 100.0; verdict = "envolvente OK"
        elif ratio < 1.5:
            score = max(0.0, 100.0 - (1.5 - ratio) / 1.5 * 80.0); verdict = "campo seco (poca reverb)"
        else:
            score = max(0.0, 100.0 - (ratio - 5.0) / 5.0 * 50.0); verdict = "demasiada reverb"
    else:
        # mixto: rango amplio [0.8, 4.0]
        if 0.8 <= ratio <= 4.0:
            score = 100.0; verdict = "balance OK"
        elif ratio < 0.8:
            score = max(0.0, 100.0 - (0.8 - ratio) / 0.8 * 60.0); verdict = "seco"
        else:
            score = max(0.0, 100.0 - (ratio - 4.0) / 4.0 * 60.0); verdict = "reverberante"
    msg = (f"d_crit = {fem.d_crit:.1f} m · receptor ~{fem.d_worst:.1f} m "
           f"(ratio {ratio:.1f}, {verdict})")
    return score, msg


def _score_bass(fem: FemLiteResult, cand: Candidate, use: str) -> tuple:
    """BR proxy: densidad modal bajo 80 Hz por m^3, comparado al target del uso.

    Limitaciones: la BR REAL depende mucho de materiales (alpha por banda).
    Este proxy mide solo la capacidad GEOMETRICA de soportar bajos:
      - sala chica con techo bajo  -> pocos modos bajo 80 Hz -> bass limitado
      - sala grande con techo alto -> muchos modos -> bass abundante (proxy)

    Para usos de musica acustica esperamos densidad alta. Para voz, neutro.
    """
    if fem.error:
        return 50.0, ""
    V = cand.volume
    if V <= 0:
        return 50.0, ""
    is_music = ("musica" in use.lower() or "sinfonica" in use.lower()
                or "camara" in use.lower())
    is_voice = ("conferencia" in use.lower() or "aula" in use.lower())

    # Densidad modal teorica bajo 80 Hz (Schroeder): N = (4pi/3) * V * (f/c)^3
    N_theory = (4.0 * np.pi / 3.0) * V * (80.0 / 343.0) ** 3
    coverage = fem.n_modes_below_80hz / max(N_theory, 1.0)
    # coverage > 0.7 = buen soporte de bajos

    if is_music:
        # queremos coverage alto. score = 100 si coverage >= 0.7
        score = min(100.0, coverage * 140.0)
        label = ("soporte abundante" if score >= 80
                  else "soporte medio" if score >= 50 else "soporte bajo")
    elif is_voice:
        # neutro: la voz no necesita ni evita bass. Score 100 si coverage >= 0.3
        score = 100.0 if coverage >= 0.3 else 70.0 + coverage / 0.3 * 30.0
        label = "neutro (voz)"
    else:
        # mixto: target intermedio
        score = min(100.0, coverage * 110.0)
        label = ("balance OK" if score >= 70 else "soporte limitado")
    msg = f"{fem.n_modes_below_80hz} modos <80Hz · {label}"
    return score, msg


def _score_planta(cand: Candidate, audience_area: float) -> tuple:
    """Aprovechamiento de planta: util = audience / planta_calculada.

    Ideal [0.40, 0.70]. Demasiado bajo = desperdicio. Demasiado alto = apretado.
    """
    planta = cand.width * cand.length
    if planta <= 0 or audience_area <= 0:
        return 50.0, ""
    util = audience_area / planta
    if 0.40 <= util <= 0.70:
        score = 100.0; verdict = "óptimo"
    elif util < 0.40:
        # desperdicio: linear de 100 (util=0.40) a 30 (util=0.10)
        score = max(30.0, 100.0 - (0.40 - util) / 0.30 * 70.0)
        verdict = "espacio sobra"
    elif util <= 0.85:
        score = 80.0; verdict = "cómodo"
    else:
        score = max(0.0, 80.0 - (util - 0.85) / 0.15 * 80.0)
        verdict = "apretado"
    msg = (f"{util*100:.0f}% utilizado ({audience_area:.0f}/{planta:.0f} m², "
           f"{verdict})")
    return score, msg


def _score_constr(cand: Candidate) -> tuple:
    """Constructabilidad heuristica.

    Penaliza:
      - muros > 12 m sin soporte intermedio (-30)
      - planta > 800 m² (-20, requiere vigas grandes)
      - L/W > 5 (-20, span largo dificil)
    """
    score = 100.0
    notes = []
    if cand.height > 12.0:
        score -= 30.0
        notes.append(f"muros {cand.height:.1f}m altos")
    if cand.height > 6.0:
        notes.append(f"muros {cand.height:.1f}m")
    planta = cand.width * cand.length
    if planta > 800.0:
        score -= 20.0
        notes.append(f"planta {planta:.0f}m² grande")
    lw = max(cand.length / max(cand.width, 1e-3),
              cand.width / max(cand.length, 1e-3))
    if lw > 5.0:
        score -= 20.0
        notes.append(f"L/W={lw:.1f} (span largo)")
    score = max(0.0, score)
    if not notes:
        notes.append("OK estándar")
    msg = " · ".join(notes)
    return score, msg


def _score_robustness(fem: FemLiteResult) -> tuple:
    """Sensibilidad a materiales: que tan cerca esta alpha_required del borde
    de la zona feasible [0.08, 0.30].

    Margen = min(alpha - 0.08, 0.30 - alpha). Si margen > 0.10 -> 100.
    Si negativo (fuera de zona) -> ya lo penaliza score_rt60; aca damos 30.
    """
    if fem.error or fem.alpha_required <= 0:
        return 50.0, ""
    a = fem.alpha_required
    margin = min(a - 0.08, 0.30 - a)
    if margin < 0:
        return 30.0, f"margen α=0 (en borde de feasible)"
    if margin >= 0.10:
        return 100.0, f"margen α={margin:.2f} · sólido"
    score = 30.0 + margin / 0.10 * 70.0
    label = "sólido" if margin > 0.06 else ("ajustado" if margin > 0.03 else "frágil")
    return score, f"margen α={margin:.2f} · {label}"


# -------------------- Pesos condicionales por uso --------------------
def _category_weights(use: str) -> dict:
    """Pesos por GRUPO de sub-scores segun el uso."""
    is_voice = ("conferencia" in use.lower() or "aula" in use.lower())
    is_music = ("musica" in use.lower() or "sinfonica" in use.lower()
                or "camara" in use.lower())
    if is_voice:
        # Voz: prioridad inteligibilidad + base modal correcta
        return {"modal": 0.40, "voz": 0.30, "musica": 0.00,
                "practico": 0.25, "robustez": 0.05}
    if is_music:
        # Musica: prioridad modal + envoltura
        return {"modal": 0.45, "voz": 0.00, "musica": 0.20,
                "practico": 0.25, "robustez": 0.10}
    # Mixto/polivalente/theater/estudio
    return {"modal": 0.40, "voz": 0.15, "musica": 0.10,
            "practico": 0.25, "robustez": 0.10}


def score_prediction(cand: Candidate, fem: FemLiteResult,
                     inputs: PredictInputs) -> Prediction:
    """Combina los 13 sub-scores en un score total por grupos.

    Grupos:
      MODAL    = avg(Bolt-spacing, FSI, Bonello, Modal Q, RT60_feas, Schroeder)
      VOZ      = avg(STI, %Alcons, d_crit)
      MUSICA   = avg(Bass proxy, d_crit)    # d_crit aparece en los 2
      PRACTICO = avg(Vol, Aspect, Fit, Planta, Constr)
      ROBUSTEZ = Robustness

    Los pesos de cada GRUPO son condicionales por uso (voz / musica / mixto).
    """
    # RT60 efectivo de ESTE candidato: si el usuario eligio materiales, lo
    # determina la absorcion (Sabine por geometria); si no, el rt60_target.
    rt = effective_rt60(inputs, cand)
    # Sub-scores individuales
    s_rt, feas_msg = _score_rt60_feasibility(fem, rt)
    s_un = _score_bolt_spacing(fem)
    s_mq = _score_modal_q(fem, _fazenda_stimulus_for(inputs.program))
    s_sch = _score_schroeder(fem, inputs.v_target)
    s_fsi = _score_fsi(fem)                 # A6: FSI psi(25) de Rindel
    s_bon = fem.bonello_score               # A3: ya 0-100 (% transiciones no-decr.)
    s_sti, sti_msg = _score_sti(rt)
    s_alcons, alcons_msg = _score_alcons(fem, rt)
    sti_msg = f"{sti_msg}  ·  {alcons_msg}"
    s_dc, dc_msg = _score_dcrit(fem, inputs.use)
    s_bass, bass_msg = _score_bass(fem, cand, inputs.use)
    s_vol = _score_volume(cand, inputs.v_target)
    s_asp, asp_msg = _score_aspect(cand)
    s_fi = _score_fits(cand)
    s_plt, plt_msg = _score_planta(cand, inputs.audience_area)
    s_cns, cns_msg = _score_constr(cand)
    s_rob, rob_msg = _score_robustness(fem)

    # Promedios PONDERADOS por grupo. Las metricas que mas discriminan entre
    # candidatos (Bolt-spacing en modal, Aspect en practico) tienen mas peso
    # para que el ranking refleje las diferencias geometricas reales.
    # Las metricas dominadas por V o RT60 (que son inputs constantes) tienen
    # peso menor — son informativas pero no discriminadoras.
    # Bolt-spacing, FSI (A6) y Bonello (A3) son tres lentes del MISMO fenomeno
    # (lo pareja que es la distribucion modal). Por eso entran con presupuesto
    # combinado 0.45 (Bolt 0.25 + FSI 0.15 + Bonello 0.05), no inflado por
    # contar tres veces lo mismo. FSI pesa mas que Bonello: discrimina geometria
    # pura (independiente de V y absorcion); Bonello es casi binario.
    modal_avg = (0.25 * s_un + 0.15 * s_fsi + 0.05 * s_bon +
                 0.20 * s_mq + 0.20 * s_rt + 0.15 * s_sch)
    voz_avg = (s_sti + s_alcons + s_dc) / 3.0
    musica_avg = (s_bass + s_dc) / 2.0
    practico_avg = (0.20 * s_vol + 0.25 * s_asp + 0.15 * s_fi +
                    0.25 * s_plt + 0.15 * s_cns)

    # Pesos por uso
    w = _category_weights(inputs.use)
    total = (w["modal"] * modal_avg + w["voz"] * voz_avg +
              w["musica"] * musica_avg + w["practico"] * practico_avg +
              w["robustez"] * s_rob)

    return Prediction(
        candidate=cand, fem=fem,
        score_rt60=s_rt, score_uniformity=s_un,
        score_modal_q=s_mq, score_schroeder=s_sch,
        score_fsi=s_fsi, score_bonello=s_bon,
        score_robustness=s_rob,
        score_sti=s_sti, score_alcons=s_alcons, score_dcrit=s_dc,
        score_bass=s_bass,
        score_volume=s_vol, score_aspect=s_asp, score_fits=s_fi,
        score_planta=s_plt, score_constr=s_cns,
        score_total=total,
        feasibility_msg=feas_msg, aspect_msg=asp_msg,
        sti_msg=sti_msg, dcrit_msg=dc_msg,
        bass_msg=bass_msg, planta_msg=plt_msg,
        constr_msg=cns_msg, robustness_msg=rob_msg,
    )


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def predict(inputs: PredictInputs,
            progress: Optional[Callable[[str], None]] = None) -> list:
    """Devuelve una lista de Prediction ordenada por score descendente.

    Si los 3 candidatos clasicos salen con scores dentro de ±5 puntos, agrega
    una 4ta card 'Control negativo' (cubo 1:1:1) para que el usuario vea
    visualmente lo que NO funciona. Esa card aparece con border rojo y
    boton Aplicar deshabilitado.
    """
    if progress: progress("Generando candidatos...")
    candidates = generate_candidates(inputs)
    fem_results = verify_candidates_parallel(
        candidates,
        rt60_target=inputs.rt60_target,
        inputs=inputs,
        progress=progress,
    )
    preds = [score_prediction(c, f, inputs)
             for c, f in zip(candidates, fem_results)]
    preds.sort(key=lambda p: p.score_total, reverse=True)
    # La libreria de ratios puede tener > 3 entradas (Louden/Bolt/Sepmeyer/Cox):
    # se evaluan todas y se muestran los 3 mejores por score.
    preds = preds[:3]

    # Control negativo: si los 3 candidatos son muy parecidos en score,
    # generamos una variante deliberadamente mala como referencia visual.
    if len(preds) >= 3:
        score_range = preds[0].score_total - preds[2].score_total
        if score_range < 5.0:
            neg = _generate_negative_control(inputs)
            if neg is not None:
                if progress: progress("Generando control negativo...")
                neg_fem = verify_candidate_fem(
                    neg, rt60_target=effective_rt60(inputs, neg),
                )
                neg_pred = score_prediction(neg, neg_fem, inputs)
                preds.append(neg_pred)
    return preds


def _generate_negative_control(inputs: PredictInputs) -> Optional[Candidate]:
    """Genera una sala deliberadamente mala (cubo 1:1:1) escalada al V target.

    El cubo tiene modos triplemente degenerados (3 axiales en la misma
    frecuencia para cualquier tripla l=m=n) -> resonancias super fuertes
    aisladas. Visualmente debe sacar Bolt-spacing bajo y aspecto malo.
    """
    v_target = inputs.v_target
    s = v_target ** (1.0 / 3.0)
    W, L, H = s, s, s
    W, L, H, fits = _apply_constraints(W, L, H,
                                        inputs.width_max,
                                        inputs.length_max,
                                        inputs.height_max)
    return Candidate(
        ratio_name="Cubo 1:1:1",
        ratio_note="CONTROL NEGATIVO: cubo perfecto. Modos triplemente degenerados "
                    "causan resonancias fuertes aisladas. NO usar — se muestra "
                    "como referencia de lo que NO funciona.",
        width=round(W, 2), length=round(L, 2), height=round(H, 2),
        n_walls=4, taper=0.0, twist=0.0,
        arch_height=0.0, roof_type="flat",
        fits_constraints=fits,
        actual_ratio=(1.0, 1.0, 1.0),
        is_negative_control=True,
    )


# ---------------------------------------------------------------------------
# Helper para construir el params dict que ControlPanel.set_params espera
# ---------------------------------------------------------------------------
def _aabb_dims(surface):
    """(W, L, H) de la caja envolvente (AABB) de la malla real (v, t)."""
    v = np.asarray(surface[0], dtype=float)
    d = v.max(axis=0) - v.min(axis=0)
    return float(d[0]), float(d[1]), float(d[2])


def is_irregular_shape(params: dict) -> bool:
    """True si el diseño NO es un prisma regular: tiene planta dibujada
    (`base_polygon`) o cortes laterales (`wall_profiles`). En esos casos el
    score de geometria de CAJA (Bolt, ratios) no aplica directo -> el panel
    pregunta si aproximar por caja envolvente o no ponderar la forma."""
    return bool(params.get("base_polygon") or params.get("wall_profiles"))


def candidate_from_params(params: dict, name: str = "Tu diseño actual",
                           note: str = "", aabb=None) -> Candidate:
    """Crea un Candidate a partir de los params actuales de ControlPanel.

    Util para 'Evaluar mi diseño actual': el usuario disena en la pestaña
    Geometria, va a Predicción y ve su diseño scorado contra los presets.

    `aabb` (W, L, H): si viene, sobreescribe las dimensiones con la caja
    envolvente del recinto real y fuerza caja (n_walls=4, sin taper/arch). Se
    usa para aproximar el score de geometria de una forma irregular por su AABB.
    """
    if aabb is not None:
        W, L, H = float(aabb[0]), float(aabb[1]), float(aabb[2])
        n_walls, taper, twist = 4, 0.0, 0.0
        arch_height, roof_type = 0.0, "flat"
    else:
        W = float(params.get("width", 6.0))
        L = float(params.get("length", 8.0))
        H = float(params.get("height", 3.0))
        n_walls = int(params.get("n_walls", 4))
        taper = float(params.get("taper", 0.0))
        twist = float(params.get("twist", 0.0))
        arch_height = float(params.get("arch_height", 0.0))
        roof_type = str(params.get("roof_type", "flat"))
    return Candidate(
        ratio_name=name,
        ratio_note=note or "Geometría tomada de la pestaña Geometría tal como esta diseñada actualmente.",
        width=W, length=L, height=H,
        n_walls=n_walls, taper=taper, twist=twist,
        arch_height=arch_height, roof_type=roof_type,
        fits_constraints=True,    # por definicion el diseno actual "cabe"
        actual_ratio=(1.0, 1.0, 1.0),
        is_negative_control=False,
    )


def fixed_room_from_design(params: dict, surface=None) -> Candidate:
    """Candidate del recinto ACTUAL para el eje de UBICACION (recinto fijo).

    Si la forma es irregular (planta dibujada / cortes laterales) y tenemos la
    malla real renderizada (`surface` = (v, t)), reconstruye la CAJA ENVOLVENTE
    (AABB) de esa malla en vez de tomar las dimensiones crudas de los sliders:
    asi el FEM de ubicacion corre sobre una caja que ENVUELVE al recinto real
    (mismas extensiones en planta y alto) y las posiciones de fuente generadas
    caen dentro de ese volumen. Si la forma es regular —o no hay malla— usa los
    params tal cual.

    Es el analogo, para el flujo "Predecir ubicacion", del shape_mode="aabb" de
    evaluate_design ("Evaluar mi diseño"): el score de ubicacion no depende del
    detalle fino de la forma (Bolt/ratios), pero SI del volumen y las paredes,
    que la caja envolvente aproxima."""
    if is_irregular_shape(params) and surface is not None:
        return candidate_from_params(params, name="Recinto (caja env.)",
                                     aabb=_aabb_dims(surface))
    return candidate_from_params(params)


def candidate_to_params(cand: Candidate) -> dict:
    """Convierte un Candidate al dict que ControlPanel.set_params espera.
    Incluye TODOS los campos para que el panel no levante KeyError.
    """
    return {
        "width": float(cand.width),
        "length": float(cand.length),
        "height": float(cand.height),
        "n_walls": int(cand.n_walls),
        "taper": float(cand.taper),
        "twist": float(cand.twist),
        "arch_height": float(cand.arch_height),
        "ridge_offset": 0.0,
        "roof_type": str(cand.roof_type),
        "ceiling_pitch_x": 0.0,
        "ceiling_pitch_y": 0.0,
        "floor_pitch_x": 0.0,
        "floor_pitch_y": 0.0,
        "wall_inclinations": [0.0] * int(cand.n_walls),
        "base_polygon": None,
    }


# ===========================================================================
# T8 — Eje de UBICACION de fuentes (Fase B: integracion en Prediccion)
# ===========================================================================
# Tres modos de salida (decision del usuario 18 Jun 2026):
#   - "geometry"  : recomendar la forma del recinto (predict(), sin cambios).
#   - "location"  : recinto FIJO -> recomendar donde poner las fuentes.
#   - "combined"  : optimizar geometria Y ubicacion -> 3 predicciones.
# Reusa location_opt (FoM + SBIR + suavidad modal) sobre el FEM completo del
# recinto (con locator), no el FEM-lite (que descarta el locator).

# Reflexion de referencia para SBIR en Prediccion (no hay materiales por cara
# todavia): alpha uniforme = alpha_default del FEM-lite -> R = sqrt(1-alpha).
_LOC_ALPHA_REF = 0.10
# Peso geometria vs ubicacion en el modo combinado (calibrable).
_COMBINED_W_GEOM = 0.5


@dataclass
class LocationPrediction:
    """Una recomendacion del eje de ubicacion: recinto + layout de fuentes."""
    candidate: Candidate                 # recinto (fijo en 'location', optimizado en 'combined')
    layout: "object"                     # location_opt.SourceLayout
    score_total: float                   # score de ubicacion (o combinado)
    mode: str = "location"               # "location" | "combined"
    geom_score: float = 0.0              # score de geometria (solo combinado)
    FoM_flat: float = 0.0
    FoM_espacial: float = 0.0
    sbir_realce: float = 0.0
    sbir_aten: float = 0.0
    smoothness: float = 0.0
    sub_scores: dict = field(default_factory=dict)
    layout_msg: str = ""                 # "2 fuentes · estereo · delay 2.0 ms"
    fom_msg: str = ""                    # "planitud 2.8 dB · espacial 5.0 dB"
    sbir_msg: str = ""                   # "realce +12 dB · aten +8 dB (20-200 Hz)"
    positions_msg: str = ""              # "(-1.5, -1.4, 1.2) · (1.5, -1.4, 1.2) m"


def _describe_layout(layout) -> str:
    fam = (layout.label or "").split("*")[0].split("+")[0]
    ns = layout.n_sources
    parts = [f"{ns} fuente{'s' if ns != 1 else ''}"]
    if fam:
        parts.append(fam)
    if np.any(np.asarray(layout.delays_s) != 0.0):
        dmax = float(np.max(np.abs(layout.delays_s))) * 1e3
        parts.append(f"delay {dmax:.1f} ms")
    if np.any(np.asarray(layout.inverted)):
        parts.append("polaridad inv")
    if np.any(np.asarray(layout.mounted)):
        parts.append("flush")
    return " · ".join(parts)


def _location_prediction(cand: Candidate, ls, mode: str = "location",
                         geom_score: float = 0.0,
                         score_total: Optional[float] = None) -> LocationPrediction:
    """Arma una LocationPrediction (mensajes legibles) desde un LayoutScore."""
    pos = np.atleast_2d(ls.layout.positions)
    pos_txt = " · ".join("(" + ", ".join(f"{c:.1f}" for c in p) + ")" for p in pos)
    return LocationPrediction(
        candidate=cand, layout=ls.layout,
        score_total=float(score_total if score_total is not None else ls.score_total),
        mode=mode, geom_score=float(geom_score),
        FoM_flat=ls.FoM_flat, FoM_espacial=ls.FoM_espacial,
        sbir_realce=ls.sbir_realce, sbir_aten=ls.sbir_aten,
        smoothness=ls.smoothness, sub_scores=dict(ls.sub_scores),
        layout_msg=_describe_layout(ls.layout),
        fom_msg=f"planitud {ls.FoM_flat:.1f} dB · espacial {ls.FoM_espacial:.1f} dB",
        sbir_msg=(f"realce {ls.sbir_realce:+.0f} dB · aten {ls.sbir_aten:+.0f} dB "
                  f"(20–200 Hz)"),
        positions_msg=pos_txt + " m",
    )


def _build_location_context(cand: Candidate, inputs: PredictInputs,
                            n_per_meter: float = 2.0, n_modes: int = 40,
                            surface=None):
    """FEM completo del recinto (con locator) + paredes + grilla -> LocationContext.

    `surface` (v, t): si viene, usa esa malla real (forma irregular renderizada)
    en vez de reconstruir una caja. Garantiza ademas que las fuentes reales
    caigan dentro del recinto evaluado (mismo sistema de coords)."""
    import acoustic_analysis as aa
    import face_materials as fm
    import sbir
    import location_opt as lo

    v, t = surface if surface is not None else _build_surface_mesh(cand)
    mr = aa.run_fem_modal(v, t, n_modes=n_modes, n_per_meter=n_per_meter)
    R = sbir.reflection_from_alpha(_LOC_ALPHA_REF)
    walls = [sbir.Wall(g.centroid, g.normal, g.label, R)
             for g in fm.group_faces_by_planar_region(v, t)]
    h_max = mr.mesh_info.get("h_max", 0.0)
    f_max = (C0 / (6.0 * h_max)) if h_max > 0 else None
    # Damping desde el RT60 objetivo (el RT que la sala VA A tener): xi_n =
    # 1.1/(f_n·RT60_target). Constante en banda (RT objetivo es un solo numero).
    rt = max(float(effective_rt60(inputs, cand)), 1e-3)
    damping = 1.1 / (np.maximum(np.asarray(mr.freqs, float), 1e-6) * rt)
    # Forma irregular: el AABB incluye zonas fuera de la sala (pared inclinada,
    # planta no rectangular). inside_fn testea contra la superficie REAL para
    # que el optimizador no recomiende fuentes fuera del recinto.
    inside_fn = None
    if surface is not None:
        from acoustic_mesh import points_inside_surface
        sv = np.asarray(v, dtype=float)
        st = np.asarray(t, dtype=int)
        inside_fn = lambda pts: points_inside_surface(
            np.asarray(pts, dtype=float), sv, st)
    return lo.LocationContext.from_modal(mr, walls, use=inputs.use,
                                         damping=damping, f_max_valid=f_max,
                                         inside_fn=inside_fn)


def predict_locations(inputs: PredictInputs, cand: Candidate,
                      weights: Optional[dict] = None,
                      n_per_meter: float = 2.0, n_modes: int = 40,
                      top_n: int = 3,
                      progress: Optional[Callable[[str], None]] = None,
                      surface=None) -> list:
    """Modo UBICACION: recinto fijo `cand` -> top-N layouts de fuentes.

    `surface` (v, t): si el recinto es de forma irregular, la malla REAL
    renderizada. El FEM de ubicacion corre sobre ella (Camino B, mismos modos y
    mismo sistema de coordenadas que la pestaña Geometria) en vez de reconstruir
    una caja centrada -> las posiciones recomendadas caen en el frame del recinto
    real. `cand` sigue aportando el volumen/areas para el RT60 (su AABB)."""
    import location_opt as lo
    if progress:
        # El texto distingue el camino: "malla real" = Camino B (forma
        # irregular dibujada); sin surface = caja reconstruida del candidato.
        progress("FEM del recinto fijo (malla real de la forma dibujada)..."
                 if surface is not None else
                 "FEM del recinto fijo (para ubicacion)...")
    ctx = _build_location_context(cand, inputs, n_per_meter, n_modes,
                                  surface=surface)
    if weights is None:
        weights = lo.default_location_weights(inputs.use)
    if progress:
        progress("Optimizando ubicacion de fuentes...")
    tops = lo.optimize_layout(ctx, weights=weights, top_n=top_n)
    return [_location_prediction(cand, ls, mode="location") for ls in tops]


def predict_combined(inputs: PredictInputs,
                     weights: Optional[dict] = None,
                     geom_top_k: int = 3, top_n: int = 3,
                     n_per_meter: float = 2.0, n_modes: int = 40,
                     progress: Optional[Callable[[str], None]] = None
                     ) -> list:
    """Modo COMBINADO: optimiza geometria Y ubicacion. Para las top-K geometrias,
    busca su mejor layout y combina ambos scores -> top-N predicciones."""
    import location_opt as lo
    if progress:
        progress("Generando y verificando geometrias...")
    geom_preds = predict(inputs, progress=progress)
    geom_preds = [p for p in geom_preds
                  if not p.candidate.is_negative_control][:geom_top_k]
    out = []
    for i, gp in enumerate(geom_preds, 1):
        if progress:
            progress(f"Ubicacion para geometria {i}/{len(geom_preds)} "
                     f"({gp.candidate.ratio_name})...")
        ctx = _build_location_context(gp.candidate, inputs, n_per_meter, n_modes)
        w = weights or lo.default_location_weights(inputs.use)
        tops = lo.optimize_layout(ctx, weights=w, top_n=1)
        if not tops:
            continue
        ls = tops[0]
        combined = (_COMBINED_W_GEOM * gp.score_total +
                    (1.0 - _COMBINED_W_GEOM) * ls.score_total)
        out.append(_location_prediction(gp.candidate, ls, mode="combined",
                                        geom_score=gp.score_total,
                                        score_total=combined))
    out.sort(key=lambda p: p.score_total, reverse=True)
    return out[:top_n]


def predict_axis(inputs: PredictInputs, mode: str = "geometry",
                 fixed_candidate: Optional[Candidate] = None,
                 weights: Optional[dict] = None,
                 progress: Optional[Callable[[str], None]] = None,
                 surface=None) -> list:
    """Dispatcher de los 3 ejes de prediccion.

      mode="geometry" -> list[Prediction]          (forma del recinto)
      mode="location" -> list[LocationPrediction]  (recinto fijo `fixed_candidate`)
      mode="combined" -> list[LocationPrediction]  (geometria + ubicacion)

    `surface` (v, t): solo modo "location" -> malla real del recinto fijo cuando
    su forma es irregular (ver predict_locations). En "combined" no aplica: ese
    modo GENERA geometrias nuevas, no usa la forma actual.
    """
    m = (mode or "geometry").lower()
    if m == "geometry":
        return predict(inputs, progress=progress)
    if m == "location":
        cand = fixed_candidate
        if cand is None:
            # Fallback: si no hay diseno fijo, usar el mejor candidato generado.
            cand = generate_candidates(inputs)[0]
        return predict_locations(inputs, cand, weights=weights,
                                 progress=progress, surface=surface)
    if m == "combined":
        return predict_combined(inputs, weights=weights, progress=progress)
    raise ValueError(f"modo desconocido: {mode!r} (geometry|location|combined)")


# ---------------------------------------------------------------------------
# "Evaluar mi diseño actual" respetando el eje elegido (geometry/location/
# combined). A diferencia de predict_axis (que GENERA candidatos), esto scorea
# lo que el usuario YA tiene: su geometria y, en location/combined, su layout
# REAL de fuentes (no optimiza — evalua lo que pusiste).
# ---------------------------------------------------------------------------
def _layout_from_sources(sources, label: str = "actual"):
    """SourceLayout con las posiciones REALES de las fuentes del recinto.

    v1 evalua UBICACION: usa posiciones + bafle (el de la primera fuente, que
    es el unico que SourceLayout soporta de forma global). Delay/polaridad de
    cada fuente quedan en 0 — afectan el peine SBIR fino pero no el 'donde
    estan ubicadas', que es lo que este eje juzga.
    """
    import location_opt as lo
    positions = [np.asarray(s.position, float) for s in sources]
    if not positions:
        raise ValueError("No hay fuentes para evaluar la ubicacion.")
    first = next(iter(sources))
    baffle = tuple(float(x) for x in getattr(first, "baffle_size",
                                             (0.30, 0.50, 0.40)))
    return lo.SourceLayout(np.array(positions), baffle=baffle, label=label)


def _assert_sources_inside(ctx, layout):
    """Las fuentes reales viven en coords del recinto de Acustica; el ctx se
    re-malla con make_room (centrado en origen). Si no coinciden (CAD con
    offset, o sliders movidos tras colocar las fuentes) avisamos en vez de
    scorear basura."""
    mn, mx = ctx.room_bbox()
    pos = np.atleast_2d(layout.positions)
    inside = np.all((pos >= mn - 0.10) & (pos <= mx + 0.10), axis=1)
    if not bool(inside.all()):
        raise ValueError(
            "Las fuentes no caen dentro del recinto reconstruido para la "
            "evaluacion. Suele pasar si importaste un CAD o moviste la "
            "geometria despues de colocar las fuentes. Re-ubica las fuentes "
            "dentro de la geometria de la pestana Geometria y reintenta.")


def evaluate_design(params: dict, inputs: PredictInputs,
                    mode: str = "geometry", sources=None,
                    weights: Optional[dict] = None,
                    surface=None, shape_mode: str = "exact",
                    n_per_meter: float = 2.0, n_modes: int = 40,
                    progress: Optional[Callable[[str], None]] = None):
    """Scorea el diseño ACTUAL segun el eje elegido.

      mode="geometry" -> Prediction          (solo la forma)
      mode="location" -> LocationPrediction  (tu layout real en tu recinto)
      mode="combined" -> LocationPrediction  (geometria + tu layout real)

    `surface` (v, t): malla REAL renderizada (forma irregular: planta custom +
        cortes). Si viene, el FEM corre sobre ella (Camino B) y las fuentes
        reales caen dentro del recinto evaluado.
    `shape_mode`: "exact" (forma regular), "aabb" (forma irregular -> el score
        de geometria se aproxima por la caja envolvente del recinto), "none"
        (forma irregular -> NO se pondera la geometria; en 'geometry' es error,
        en 'combined' degrada a solo ubicacion).

    En location/combined `sources` debe traer >=1 fuente (el caller valida y
    avisa antes; aca levantamos ValueError por las dudas).
    """
    import location_opt as lo
    m = (mode or "geometry").lower()

    # Candidate: caja envolvente (AABB) si la forma es irregular y se eligio
    # aproximar; si no, las dimensiones de los sliders.
    if shape_mode == "aabb" and surface is not None:
        cand = candidate_from_params(params, name="Tu diseño actual (caja env.)",
                                     aabb=_aabb_dims(surface))
    else:
        cand = candidate_from_params(params)
    geom_ponderable = (shape_mode != "none")

    if m == "geometry":
        if not geom_ponderable:
            raise ValueError(
                "La forma es irregular y elegiste NO ponderarla: no se puede "
                "predecir por geometria. Elegi el enfoque Ubicacion o "
                "Combinado, o volve a evaluar aproximando con la caja "
                "envolvente.")
        if progress: progress("Evaluando geometria...")
        fem = verify_candidate_fem(cand, rt60_target=inputs.rt60_target,
                                   surface=surface)
        return score_prediction(cand, fem, inputs)

    if m not in ("location", "combined"):
        raise ValueError(
            f"modo desconocido: {mode!r} (geometry|location|combined)")

    layout = _layout_from_sources(sources)
    if weights is None:
        weights = lo.default_location_weights(inputs.use)

    geom_pred = None
    if m == "combined" and geom_ponderable:
        if progress: progress("Evaluando geometria...")
        fem = verify_candidate_fem(cand, rt60_target=inputs.rt60_target,
                                   surface=surface)
        geom_pred = score_prediction(cand, fem, inputs)

    if progress: progress("FEM del recinto actual (ubicacion)...")
    ctx = _build_location_context(cand, inputs, n_per_meter, n_modes,
                                  surface=surface)
    _assert_sources_inside(ctx, layout)
    if progress: progress("Evaluando tu ubicacion de fuentes...")
    ls = lo.evaluate_layout(ctx, layout, weights=weights)

    if m == "location" or geom_pred is None:
        # location, o combined sin geometria ponderable -> solo ubicacion.
        return _location_prediction(cand, ls, mode="location")
    combined = (_COMBINED_W_GEOM * geom_pred.score_total +
                (1.0 - _COMBINED_W_GEOM) * ls.score_total)
    return _location_prediction(cand, ls, mode="combined",
                                geom_score=geom_pred.score_total,
                                score_total=combined)
