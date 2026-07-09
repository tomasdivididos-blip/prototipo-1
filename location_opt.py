"""
location_opt.py
===============

T8 — Optimizador de UBICACION de fuentes (eje de prediccion separado del de
geometria). Dado un recinto FIJO (sus modos FEM + paredes + materiales),
busca donde poner las fuentes para optimizar una funcion objetivo combinada:

  - FoM_flat     (modal_metrics §8): planitud de la respuesta media        [dB, menor mejor]
  - FoM_espacial (modal_metrics §8): consistencia asiento-a-asiento          [dB, menor mejor]
  - SBIR         (sbir, T6): realce/atenuacion del peine fuente-frontera     [dB, menor mejor]
  - suavidad modal (Bolt-spacing): es propiedad del RECINTO, constante entre
    layouts del mismo recinto (discrimina en modo geometria/combinado, no en
    ubicacion-sola).

Cada metrica -> sub-score 0..100; combinadas con pesos (por uso + ajustables)
-> score de ubicacion 0..100, consistente con el scorer de geometria.

Espacio de busqueda COMPLETO (item 8.1): numero de fuentes, posiciones,
delays/polaridad, montadas-o-no en pared (flush/soffit), dimensiones del bafle.
Metodo: semillas heuristicas (estereo simetrico, subs a 1/4, esquina, flush) ->
refinamiento local (grilla chica + barrido de delay) -> top-N.

Constraint flush/soffit: distancia fuente-pared <= menor dimension del bafle
(empuja el primer notch SBIR fuera de banda; ata T4 + T6).

Cómputo puro (numpy + modal_metrics + sbir + sources). Sin Qt.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import modal_metrics as mm
import sbir
from sources import OmniSource, SourceArray, SourceResponse, RHO0, C0


# ---------------------------------------------------------------------------
# Pesos por uso (default) — ajustables por el usuario (decision 18 Jun 2026)
# ---------------------------------------------------------------------------
def default_location_weights(use: str) -> dict:
    """Pesos default del objetivo de ubicacion segun el uso.

    Claves: flat, espacial, sbir, smoothness. La UI los puede mover; aca solo
    se da un punto de partida razonable por uso (analogo a _category_weights
    del scorer de geometria).
    """
    u = (use or "").lower()
    is_voice = ("conferencia" in u or "aula" in u or "voz" in u)
    is_music = ("musica" in u or "sinfonica" in u or "camara" in u)
    if is_voice:
        # Voz: prioriza timbre plano e inteligibilidad por sobre envoltura.
        return {"flat": 0.40, "espacial": 0.20, "sbir": 0.30, "smoothness": 0.10}
    if is_music:
        # Musica: prioriza consistencia espacial (Welti) y control del comb.
        return {"flat": 0.25, "espacial": 0.35, "sbir": 0.30, "smoothness": 0.10}
    # Mixto / theater / estudio / polivalente.
    return {"flat": 0.30, "espacial": 0.30, "sbir": 0.30, "smoothness": 0.10}


# ---------------------------------------------------------------------------
# Parametrizacion de un layout de fuentes (espacio de busqueda completo)
# ---------------------------------------------------------------------------
def _delay_polarity_response(tau_s: float, inverted: bool,
                             phi0_rad: float = 0.0,
                             f_max: float = 600.0,
                             n: int = 2000) -> Optional[SourceResponse]:
    """g(f) = e^{i(phi0 + pi*inv)} * e^{-i2pi f tau}  (gain plano, solo fase).

    None si no hay delay/polaridad/offset (para no tocar el Q baseline)."""
    if tau_s == 0.0 and not inverted and phi0_rad == 0.0:
        return None
    f = np.linspace(1.0, f_max, n)
    gdb = np.zeros_like(f)
    ph = phi0_rad + (np.pi if inverted else 0.0) - 2.0 * np.pi * f * tau_s
    return SourceResponse(f, gdb, ph, name="layout")


@dataclass
class SourceLayout:
    """Una configuracion candidata de fuentes en un recinto fijo."""
    positions: np.ndarray                       # (Ns, 3)
    delays_s:  Optional[np.ndarray] = None      # (Ns,) retardos [s]
    inverted:  Optional[np.ndarray] = None      # (Ns,) polaridad invertida
    mounted:   Optional[np.ndarray] = None      # (Ns,) montada en pared (flush)
    baffle:    Tuple[float, float, float] = (0.30, 0.50, 0.40)   # (an, al, prof)
    label:     str = ""

    def __post_init__(self):
        self.positions = np.atleast_2d(np.asarray(self.positions, dtype=float))
        ns = self.positions.shape[0]
        self.delays_s = (np.zeros(ns) if self.delays_s is None
                         else np.asarray(self.delays_s, dtype=float))
        self.inverted = (np.zeros(ns, dtype=bool) if self.inverted is None
                         else np.asarray(self.inverted, dtype=bool))
        self.mounted = (np.zeros(ns, dtype=bool) if self.mounted is None
                        else np.asarray(self.mounted, dtype=bool))
        self.baffle = tuple(float(x) for x in self.baffle)

    @property
    def n_sources(self) -> int:
        return self.positions.shape[0]

    def to_source_array(self) -> SourceArray:
        """Construye la SourceArray (delay/polaridad -> response, bafle -> dims)."""
        arr = SourceArray()
        for i in range(self.n_sources):
            resp = _delay_polarity_response(float(self.delays_s[i]),
                                            bool(self.inverted[i]))
            arr.add(OmniSource(
                tuple(self.positions[i]), Q=1.0 + 0.0j,
                label=f"{self.label or 'L'}{i+1}",
                response=resp, baffle_size=self.baffle,
            ))
        return arr


# ---------------------------------------------------------------------------
# Suavidad modal (propiedad del recinto)
# ---------------------------------------------------------------------------
def modal_smoothness_score(freqs: np.ndarray, f_lo: float = 20.0,
                           f_hi: float = 125.0, bin_w: float = 5.0) -> float:
    """Score 0..100 de uniformidad modal por bins absolutos (estilo Bolt).

    Bin con 1-2 modos = bueno; >=3 = grumo (coloracion); 0 = hueco. Penaliza el
    grumo mas que el hueco. Es propiedad del recinto, no del layout.
    """
    fr = np.asarray(freqs, dtype=float)
    fr = fr[(fr >= f_lo) & (fr <= f_hi)]
    if fr.size < 2:
        return 50.0
    n_bins = max(1, int(round((f_hi - f_lo) / bin_w)))
    idx = ((fr - f_lo) / bin_w).astype(int)
    idx = idx[(idx >= 0) & (idx < n_bins)]
    counts = np.bincount(idx, minlength=n_bins)
    good = int(((counts == 1) | (counts == 2)).sum())
    clumps = int((counts >= 3).sum())
    gaps = int((counts == 0).sum())
    raw = (good - 1.0 * clumps - 0.5 * gaps) / n_bins
    return float(np.clip(50.0 + 50.0 * raw, 0.0, 100.0))


# ---------------------------------------------------------------------------
# Contexto del recinto (precomputa lo que NO depende del layout)
# ---------------------------------------------------------------------------
@dataclass
class LocationContext:
    """Todo lo fijo del recinto para evaluar layouts rapido."""
    locator: object                 # acoustic_fem.FieldEvaluator
    freqs:   np.ndarray             # (Nm,) frecuencias modales
    phis:    np.ndarray             # (Nn, Nm)
    nodes:   np.ndarray             # (Nn, 3)
    walls:   List[sbir.Wall]
    receivers: np.ndarray           # (N_R, 3) grilla de escucha (FoM)
    receiver_center: np.ndarray     # (3,) punto de escucha (SBIR)
    fa_fom:  np.ndarray             # eje de freq para FoM (banda valida)
    fa_sbir: np.ndarray             # eje de freq para SBIR (20-500)
    damping: object = 0.03          # xi escalar o (Nm,)
    use:     str = ""
    smoothness: float = 50.0        # score de suavidad modal (room-fijo)
    # Test de pertenencia al recinto REAL: callable (N,3)->bool array, o None.
    # Sin el, el espacio de busqueda es el AABB de los nodos: para una forma
    # irregular (pared inclinada, planta no rectangular) el AABB incluye zonas
    # FUERA de la sala y el optimizador podia recomendar fuentes ahi.
    inside_fn: object = None

    @classmethod
    def from_modal(cls, modal_result, walls, *, use: str = "",
                   damping=0.03, receivers=None,
                   fa_fom=None, fa_sbir=None,
                   f_max_valid: Optional[float] = None,
                   inside_fn=None) -> "LocationContext":
        nodes = np.asarray(modal_result.nodes, dtype=float)
        freqs = np.asarray(modal_result.freqs, dtype=float)
        if receivers is None:
            receivers = mm.default_receiver_grid(nodes)
        receivers = np.atleast_2d(np.asarray(receivers, dtype=float))
        center = receivers.mean(axis=0)
        if fa_fom is None:
            f_hi = float(f_max_valid) if f_max_valid else float(freqs[-1])
            fa_fom = np.linspace(20.0, max(40.0, f_hi), 200)
        if fa_sbir is None:
            fa_sbir = np.linspace(20.0, 500.0, 1200)
        smooth = modal_smoothness_score(freqs)
        return cls(
            locator=modal_result.locator, freqs=freqs, phis=modal_result.phis,
            nodes=nodes, walls=list(walls), receivers=receivers,
            receiver_center=center, fa_fom=np.asarray(fa_fom, float),
            fa_sbir=np.asarray(fa_sbir, float), damping=damping, use=use,
            smoothness=smooth, inside_fn=inside_fn,
        )

    def layout_inside(self, layout) -> bool:
        """True si TODAS las fuentes del layout caen dentro del recinto real.
        Sin inside_fn (recinto caja: bbox == sala) acepta todo. Tolerante a
        fallas del test (acepta, no rompe la optimizacion)."""
        if self.inside_fn is None:
            return True
        try:
            pos = np.atleast_2d(np.asarray(layout.positions, dtype=float))
            return bool(np.all(self.inside_fn(pos)))
        except Exception:
            return True

    def repair_layout(self, layout):
        """Trae al interior las fuentes de un layout que caen FUERA de la sala
        real (biseccion hacia un ancla interior), preservando la estrategia de
        la semilla (mono/estereo/esquina/...). Con una planta muy no-rectangular
        puede pasar que TODAS las semillas del AABB caigan fuera; descartarlas
        dejaria al optimizador sin espacio de busqueda.

        Devuelve el layout (intacto si ya estaba dentro), o None si no se pudo
        reparar. Las fuentes movidas pierden el flag `mounted` (ya no estan
        contra la pared) y el label gana '≈'."""
        if self.inside_fn is None:
            return layout
        try:
            pos = np.atleast_2d(np.asarray(layout.positions, dtype=float)).copy()
            ins = np.asarray(self.inside_fn(pos), dtype=bool)
            if ins.all():
                return layout
            # Ancla interior: el nodo de la malla volumetrica mas cercano al
            # centroide de nodos (un nodo real siempre esta en el volumen).
            c = self.nodes.mean(axis=0)
            anchor = self.nodes[int(np.argmin(np.sum((self.nodes - c) ** 2,
                                                     axis=1)))]
            if not bool(np.asarray(self.inside_fn(np.atleast_2d(anchor)),
                                   dtype=bool)[0]):
                return None
            mounted = np.asarray(layout.mounted, dtype=bool).copy()
            for i in np.where(~ins)[0]:
                p = pos[i].copy()
                t_lo, t_hi = 0.0, 1.0          # p(t) = p + t*(anchor-p)
                for _ in range(24):
                    mid = 0.5 * (t_lo + t_hi)
                    q = p + mid * (anchor - p)
                    if bool(np.asarray(self.inside_fn(np.atleast_2d(q)),
                                       dtype=bool)[0]):
                        t_hi = mid
                    else:
                        t_lo = mid
                # t_hi = primer t adentro; 2% extra de margen interior.
                pos[i] = p + min(1.0, t_hi + 0.02) * (anchor - p)
                mounted[i] = False
            if not bool(np.all(np.asarray(self.inside_fn(pos), dtype=bool))):
                return None
            return SourceLayout(pos, delays_s=layout.delays_s,
                                inverted=layout.inverted, mounted=mounted,
                                baffle=layout.baffle,
                                label=(layout.label or "") + "≈")
        except Exception:
            return None

    def room_bbox(self):
        return self.nodes.min(axis=0), self.nodes.max(axis=0)


# ---------------------------------------------------------------------------
# Evaluacion de un layout
# ---------------------------------------------------------------------------
@dataclass
class LayoutScore:
    layout: SourceLayout
    score_total: float
    FoM_flat: float
    FoM_espacial: float
    sbir_realce: float
    sbir_aten: float
    smoothness: float
    sub_scores: dict = field(default_factory=dict)


def _lin_score(value: float, best: float, worst: float) -> float:
    """value=best -> 100, value=worst -> 0, recortado a [0,100]."""
    if worst == best:
        return 100.0
    return float(np.clip(100.0 * (worst - value) / (worst - best), 0.0, 100.0))


def evaluate_layout(ctx: LocationContext, layout: SourceLayout,
                    weights: Optional[dict] = None) -> LayoutScore:
    """Evalua un layout: FoM + SBIR + suavidad -> sub-scores -> score combinado."""
    if weights is None:
        weights = default_location_weights(ctx.use)
    arr = layout.to_source_array()

    # FoM (respuesta forzada sobre la grilla, banda valida).
    H = mm.compute_forced_response(ctx.locator, ctx.freqs, ctx.phis,
                                   arr, ctx.receivers, ctx.fa_fom,
                                   damping=ctx.damping)
    fom = mm.response_figures_of_merit(H, ctx.fa_fom)

    # SBIR en el punto de escucha. El objetivo evalua el peine en la banda de
    # GRAVES/MODAL (20-200 Hz): es donde el SBIR colorea y donde la regla
    # flush/soffit (d <= bafle) empuja el notch fuera de banda. El diálogo T6
    # sigue mostrando 20-500 al usuario.
    sb = sbir.sbir_from_sources(arr, ctx.walls, ctx.receiver_center, ctx.fa_sbir)
    f_pk, realce, f_dip, aten = sb.band_extremes(20.0, 200.0)
    span = float(realce - aten)          # peine pico-a-valle [dB]

    # Sub-scores 0..100 (umbrales calibrables — plan §8.4).
    s_flat = _lin_score(fom.FoM_flat, 2.0, 12.0)
    s_esp = _lin_score(fom.FoM_espacial, 2.0, 12.0)
    s_sbir = _lin_score(span, 2.0, 24.0)
    s_smooth = ctx.smoothness

    sub = {"flat": s_flat, "espacial": s_esp, "sbir": s_sbir,
           "smoothness": s_smooth}
    wsum = sum(weights.values()) or 1.0
    total = sum(weights.get(k, 0.0) * sub[k] for k in sub) / wsum

    return LayoutScore(
        layout=layout, score_total=float(total),
        FoM_flat=fom.FoM_flat, FoM_espacial=fom.FoM_espacial,
        sbir_realce=float(realce), sbir_aten=float(aten),
        smoothness=s_smooth, sub_scores=sub,
    )


# ---------------------------------------------------------------------------
# Semillas heuristicas
# ---------------------------------------------------------------------------
def seed_layouts(bbox_min, bbox_max,
                 baffle: Tuple[float, float, float] = (0.30, 0.50, 0.40),
                 z_ear: float = 1.2) -> List[SourceLayout]:
    """Genera layouts semilla cubriendo las dimensiones del espacio de busqueda.

    Convencion: la pared frontal es y=ymin; las fuentes miran al interior (+y);
    el oyente cae hacia el centro. El piso es z=zmin.
    """
    mn = np.asarray(bbox_min, float)
    mx = np.asarray(bbox_max, float)
    xmin, ymin, zmin = mn
    xmax, ymax, zmax = mx
    W = xmax - xmin
    xc = 0.5 * (xmin + xmax)
    bd = baffle[2]
    bmin = min(baffle)
    z = float(np.clip(z_ear, zmin + 0.1, zmax - 0.1))
    y_front = ymin + 0.6                 # 0.6 m de la pared frontal
    y_flush = ymin + min(bd * 0.5, bmin) # montada (flush/soffit)
    z_sub = zmin + 0.3
    seeds: List[SourceLayout] = []

    # 1) Mono al frente-centro.
    seeds.append(SourceLayout([[xc, y_front, z]], baffle=baffle, label="mono"))
    # 2) Estereo simetrico (separacion ~0.5 W).
    seeds.append(SourceLayout(
        [[xc - 0.25 * W, y_front, z], [xc + 0.25 * W, y_front, z]],
        baffle=baffle, label="estereo"))
    # 3) Estereo ancho (~0.7 W).
    seeds.append(SourceLayout(
        [[xc - 0.35 * W, y_front, z], [xc + 0.35 * W, y_front, z]],
        baffle=baffle, label="estereo_ancho"))
    # 4) Subs a 1/4 y 3/4 del ancho, bajos, contra el frente.
    seeds.append(SourceLayout(
        [[xmin + 0.25 * W, y_front, z_sub], [xmin + 0.75 * W, y_front, z_sub]],
        baffle=baffle, label="subs_1/4"))
    # 5) Esquina (peor-caso de excitacion modal, util de baseline/semilla).
    seeds.append(SourceLayout(
        [[xmin + 0.4, ymin + 0.4, zmin + 0.4]], baffle=baffle, label="esquina"))
    # 6) Estereo FLUSH (montadas en la pared frontal, d<=min bafle -> notch
    #    SBIR fuera de banda).
    seeds.append(SourceLayout(
        [[xc - 0.25 * W, y_flush, z], [xc + 0.25 * W, y_flush, z]],
        mounted=[True, True], baffle=baffle, label="flush_estereo"))
    return seeds


def random_baseline(bbox_min, bbox_max, n_sources: int = 2,
                    rng: Optional[np.random.Generator] = None,
                    margin: float = 0.3) -> SourceLayout:
    """Layout baseline: fuentes en posiciones aleatorias (para el oraculo)."""
    rng = rng or np.random.default_rng(0)
    mn = np.asarray(bbox_min, float) + margin
    mx = np.asarray(bbox_max, float) - margin
    pos = rng.uniform(mn, mx, size=(n_sources, 3))
    return SourceLayout(pos, label="random")


# ---------------------------------------------------------------------------
# Optimizacion: semillas -> refinamiento local -> top-N
# ---------------------------------------------------------------------------
def _clamp_positions(pos: np.ndarray, mn, mx, margin: float = 0.2) -> np.ndarray:
    lo = np.asarray(mn, float) + margin
    hi = np.asarray(mx, float) - margin
    return np.clip(pos, lo, hi)


def _refine_trials(best: SourceLayout, mn, mx, rng,
                   refine_steps: int, pos_step: float,
                   delay_grid_ms: Sequence[float]) -> List[SourceLayout]:
    """Genera perturbaciones locales de un layout (posicion + delay + polaridad)."""
    ns = best.n_sources
    trials: List[SourceLayout] = []
    # (a) perturbaciones de posicion alrededor de la semilla.
    for _ in range(refine_steps):
        dp = rng.uniform(-pos_step, pos_step, size=(ns, 3))
        dp[:, 2] *= 0.3                       # menos juego en z
        pos = _clamp_positions(best.positions + dp, mn, mx)
        trials.append(SourceLayout(pos, delays_s=best.delays_s.copy(),
                                   inverted=best.inverted.copy(),
                                   mounted=best.mounted.copy(),
                                   baffle=best.baffle, label=best.label + "*"))
    if ns >= 2:
        # (b) barrido de delay relativo: alinear la 2da fuente.
        for d_ms in delay_grid_ms:
            dl = best.delays_s.copy(); dl[1] = d_ms * 1e-3
            trials.append(SourceLayout(best.positions.copy(), delays_s=dl,
                                       inverted=best.inverted.copy(),
                                       mounted=best.mounted.copy(),
                                       baffle=best.baffle,
                                       label=best.label + f"+d{d_ms:g}ms"))
        # (c) polaridad invertida de la 2da.
        inv = best.inverted.copy(); inv[1] = True
        trials.append(SourceLayout(best.positions.copy(),
                                   delays_s=best.delays_s.copy(), inverted=inv,
                                   mounted=best.mounted.copy(),
                                   baffle=best.baffle, label=best.label + "+inv"))
    return trials


def _seed_family(label: str) -> str:
    """Familia de semilla a partir de la etiqueta (quita sufijos de refinamiento
    '*', '+d..ms', '+inv'). Asi 'esquina', 'esquina*', 'esquina+inv' colapsan."""
    return (label or "").split("*")[0].split("+")[0]


def _layout_signature(r: LayoutScore) -> str:
    """Firma de 'estrategia' para dedup con diversidad: la familia de semilla
    (mono / estereo / subs / esquina / flush...). Un representante por familia."""
    return _seed_family(r.layout.label)


def optimize_layout(ctx: LocationContext,
                    weights: Optional[dict] = None,
                    z_ear: float = 1.2,
                    refine: bool = True,
                    n_refine_seeds: int = 3,
                    refine_steps: int = 14,
                    pos_step: float = 0.4,
                    delay_grid_ms: Sequence[float] = (0.0, 0.5, 1.0, 2.0),
                    top_n: int = 3,
                    rng: Optional[np.random.Generator] = None) -> List[LayoutScore]:
    """Busca los mejores layouts: evalua semillas, refina las top-K, y devuelve
    top-N con DIVERSIDAD de estrategia (no 3 jitters del mismo layout).

    Espacio completo: posiciones (grilla local), delays relativos (alineacion
    temporal), polaridad, montaje flush, nro de fuentes (via semillas).
    """
    if weights is None:
        weights = default_location_weights(ctx.use)
    rng = rng or np.random.default_rng(12345)
    mn, mx = ctx.room_bbox()

    # Las semillas viven en el AABB; con forma irregular pueden caer FUERA de
    # la sala real -> repararlas (traer las fuentes al interior preservando la
    # estrategia). NO descartar-y-caer a las crudas: con una planta bien
    # no-rectangular TODAS las semillas caen fuera y el fallback devolveria
    # exactamente lo que se quiere evitar. Ultimo recurso (repair imposible):
    # las crudas, mejor una sugerencia imperfecta que ninguna.
    seeds = seed_layouts(mn, mx, z_ear=z_ear)
    seeds_ok = [r for r in (ctx.repair_layout(s) for s in seeds)
                if r is not None]
    scored: List[LayoutScore] = [evaluate_layout(ctx, s, weights)
                                 for s in (seeds_ok or seeds)]
    scored.sort(key=lambda r: r.score_total, reverse=True)

    if refine and scored:
        # Refinar las top-K semillas (no solo la mejor) -> diversidad.
        for base in scored[:n_refine_seeds]:
            trials = _refine_trials(base.layout, mn, mx, rng,
                                    refine_steps, pos_step, delay_grid_ms)
            scored.extend(evaluate_layout(ctx, t, weights)
                          for t in trials if ctx.layout_inside(t))
        scored.sort(key=lambda r: r.score_total, reverse=True)

    # Seleccion con diversidad: a lo sumo un representante (el mejor) por
    # 'estrategia' (nro de fuentes + montaje + celda de centroide).
    out: List[LayoutScore] = []
    seen = set()
    for r in scored:
        sig = _layout_signature(r)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
        if len(out) >= top_n:
            break
    # Si la diversidad dejo menos de top_n (recinto chico), completar con los
    # siguientes mejores aunque repitan estrategia.
    if len(out) < top_n:
        for r in scored:
            if r in out:
                continue
            out.append(r)
            if len(out) >= top_n:
                break
    return out


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("location_opt.py — smoke (requiere geometry/acoustic_analysis)")
    import geometry, acoustic_analysis as aa
    import face_materials as fm
    Lx, Ly, Lz = 6.0, 4.0, 3.0
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    mr = aa.run_fem_modal(v, t, n_modes=40, n_per_meter=2.0)
    # Paredes desde los face groups (centroide+normal en el frame REAL del
    # recinto, como hace el panel). make_room centra el recinto en el origen.
    R = sbir.reflection_from_alpha(0.08)
    walls = [sbir.Wall(g.centroid, g.normal, g.label, R)
             for g in fm.group_faces_by_planar_region(v, t)]
    ctx = LocationContext.from_modal(mr, walls, use="estudio", f_max_valid=114.0)
    tops = optimize_layout(ctx, top_n=3)
    print(f"suavidad modal del recinto: {ctx.smoothness:.1f}")
    for i, r in enumerate(tops, 1):
        print(f"  #{i} {r.layout.label:16s} score={r.score_total:5.1f}  "
              f"flat={r.FoM_flat:.2f} esp={r.FoM_espacial:.2f} "
              f"sbir[realce={r.sbir_realce:+.1f} aten={r.sbir_aten:+.1f}]  "
              f"ns={r.layout.n_sources}")
