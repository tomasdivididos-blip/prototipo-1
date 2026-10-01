"""
impedance_defaults.py - modelo de impedancia por DEFAULT de un material
========================================================================
Dado un material de catalogo (nombre + categoria + descripcion + alpha por
banda), propone un `spec` de impedancia (para `impedance.build_surface`) SOLO si
el nombre/descripcion tiene palabras clave que indican un tipo constructivo
claro. Los materiales INESPECIFICOS (cargados por el usuario, alpha plano /
porcentaje fijo, o sin palabra clave) quedan SIN modelo, y el panel «Impedancias»
avisa que hay que elegirlo a mano.

Criterio (decision del usuario, plan_impedancias_default.md, 30 Sep 2026):
  - modelo SOLO con evidencia textual de un tipo constructivo -> se estima
    "con derecho"; parametros no especificados se estiman;
  - inespecificos -> sin modelo + aviso;
  - Re(beta)=alpha SIEMPRE exacto (eso lo da el camino de material, sin modelo);
    este modulo SOLO agrega la REACTANCIA cuando hay evidencia -> NO reintroduce
    el sesgo M1 (que era alpha-shape -> Miki extrapolado ciego).

NUCLEO numpy PURO (D0). Sin PyQt. Reusa `impedance.sigma_from_alpha`.

Referencias (en referencias/):
  - Cox & D'Antonio, "Acoustic Absorbers and Diffusers": inversion alpha->sigma
    (cap. 5-6), TMM, perforados (cap. 7), membranas (cap. 6), Helmholtz (cap. 8).
  - Bies & Hansen, "Engineering Noise Control": resistividad al flujo sigma vs
    densidad de porosos fibrosos.
  - Maa 1998 (JASA 104, 2861): panel (micro)perforado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple

import numpy as np

import impedance as imp
import face_materials as _fm


# ---------------------------------------------------------------------------
# Normalizacion de texto (sin acentos, minusculas) para el match de keywords.
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


# Palabras clave por tipo. El orden lo fija `classify_material` (los asientos,
# vidrios y placas se resuelven antes que los buckets genericos de _match_kind).
_KW_PERFORATED = ("microperforado", "micro perforado", "micro-perforado", "mpp",
                  "perforado", "perforada", "perforated")
# Membranas / placas. "estriado" NO va aca (es poroso, correccion del usuario).
_KW_MEMBRANE = ("membrana", "membrane", "placa de yeso", "panel de yeso",
                "roca de yeso", "drywall", "pladur", "durlock", "diafragmatic",
                "diafragmatico", "masa-resorte", "masa resorte", "yeso laminado")
_KW_CORK = ("corcho", "cork")
_KW_CURTAIN = ("cortina", "cortinado", "drapeado", "terciopelo", "velvet",
               "colgadura")
_KW_CARPET = ("alfombra", "moqueta", "carpet", "tapete", "alfombrado")
# Porosos. Incluye "estriado" (panel estriado = poroso, con o sin camara) y
# "ranurado"/"slotted" (rejilla sobre absorbente). "lana de vidrio" es POROSO.
_KW_POROUS = ("lana de vidrio", "lana de roca", "lana mineral", "lana",
              "fibra", "fibrous", "fieltro", "espuma", "foam", "poliuretano",
              "melamina", "poroso", "porosa", "rockwool", "glasswool",
              "absorbente acustico", "panel acustico", "acoustic foam",
              "basotect", "estriado", "estriada", "ranurado", "ranurada",
              "slotted")
# Duro (beta real, sin reactancia). SIN "vidrio"/"cristal" (ahora son membranas).
_KW_HARD = ("hormigon", "concreto", "cemento", "ladrillo", "mamposteria",
            "baldosa", "ceramica", "ceramico", "marmol", "granito", "piedra",
            "yeso pintado", "yeso liso", "revoque", "pintura", "pintado",
            "metal", "acero", "aluminio", "chapa", "madera", "parquet",
            "piso", "suelo", "agua")
# Audiencia/publico = beta real (personas, no una construccion de pared).
_KW_AUDIENCE = ("audiencia", "publico", "espectador", "persona")
# Asientos tapizados / sillas tapizadas = POROSOS (con o sin gente). Se tratan
# como duro solo si son de madera/plastico/metal (ver _seat_kind).
_KW_SEAT_UPHOLSTERED = ("tapizado", "tapizada", "asiento", "butaca", "silla",
                        "poltrona", "sofa", "sillon")
_KW_SEAT_HARDMAT = ("madera", "plastico", "metal", "acero", "polipropileno")
# Vidrio en placa (no "lana de vidrio"/"fibra de vidrio"/"velo").
_KW_GLASS = ("vidrio", "cristal", "espejo", "acristalamiento")
_KW_GLASS_NOT = ("lana", "fibra", "velo", "fibra de vidrio")
_KW_DOUBLE = ("doble vidrio", "vidrio doble", "doble acristalamiento",
              "doble vidriado", "dvh")

# Densidades tipicas [kg/m^3] para estimar la masa superficial de una membrana
# desde su espesor. Cox & D'Antonio cap. 6; valores de manual.
_RHO_BY_KW = (
    (("yeso", "placa", "pladur", "durlock", "drywall"), 800.0),
    (("madera", "mdf", "contrachapado", "terciada", "aglomerado"), 650.0),
    (("vidrio", "cristal"), 2500.0),
    (("acero", "chapa", "metal", "hierro"), 7800.0),
    (("aluminio",), 2700.0),
    (("policarbonato", "acrilico", "plastico"), 1200.0),
)


@dataclass
class MaterialImpedance:
    """Resultado de clasificar un material.
      - `spec`: dict para impedance.build_surface, o None (sin modelo).
      - `has_model`: True si hay spec (aporta reactancia).
      - `nonspecific`: True si el material es inespecifico y hay que elegir a mano
        (el panel avisa). Un material DURO tiene has_model=False pero
        nonspecific=False (beta real es lo correcto, sin aviso).
      - `kind`: etiqueta del tipo detectado.
      - `reason`: texto corto legible.
      - `confidence`: "alta" | "media" | "baja" (de la estimacion de params).
    """
    spec: Optional[dict] = None
    has_model: bool = False
    nonspecific: bool = False
    kind: str = "unknown"
    reason: str = ""
    confidence: str = ""
    justification: str = ""      # POR QUE se eligio (keyword + criterio fisico)


# ---------------------------------------------------------------------------
# Parsers de parametros constructivos desde el texto.
# ---------------------------------------------------------------------------
def parse_thickness(text: str) -> Optional[float]:
    """Primer espesor "NN mm" o "NN cm" del texto, en METROS. None si no hay."""
    t = _norm(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm", t)
    if m:
        return float(m.group(1).replace(",", ".")) * 1e-3
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*cm", t)
    if m:
        return float(m.group(1).replace(",", ".")) * 1e-2
    return None


def parse_density(text: str) -> Optional[float]:
    """Densidad "NN kg" (se asume kg/m^3) del texto. None si no hay."""
    t = _norm(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", t)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def parse_air_gap(text: str) -> Optional[float]:
    """Camara de aire en METROS desde "camara/cavidad/aire/plenum/suspendido a
    ... NN mm". Cubre "cavidad de 100 mm", "suspendido a 200 mm", "camara de aire
    de 10 mm". El ancla puede estar antes (hasta ~14 chars) del numero."""
    t = _norm(text)
    m = re.search(
        r"(?:camara|cavidad|plenum|suspendido|suspension|gap)[^0-9]{0,14}"
        r"(\d+(?:[.,]\d+)?)\s*(mm|cm)", t)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val * (1e-3 if m.group(2) == "mm" else 1e-2)
    return None


def parse_absorber_thickness(text: str) -> Optional[float]:
    """Espesor del ABSORBENTE en METROS desde "absorbente de NN mm" (nombres tipo
    'Panel estriado, ..., absorbente de 40 mm a 81 kg/m3'). Evita agarrar la
    geometria de las franjas."""
    t = _norm(text)
    m = re.search(r"absorbente[^0-9]{0,8}(\d+(?:[.,]\d+)?)\s*(mm|cm)", t)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val * (1e-3 if m.group(2) == "mm" else 1e-2)
    return None


def parse_porous_fill(text: str) -> Optional[float]:
    """Espesor del relleno poroso (lana) en METROS, para una placa/membrana con
    lana detras: "NN mm de lana ..." o "lana ... NN mm"."""
    t = _norm(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(mm|cm)\s+de\s+(?:lana|fibra|espuma)", t)
    if not m:
        m = re.search(r"(?:lana|fibra|espuma)[^0-9]{0,18}(\d+(?:[.,]\d+)?)\s*(mm|cm)", t)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val * (1e-3 if m.group(2) == "mm" else 1e-2)
    return None


def _density_for(text: str) -> Optional[float]:
    t = _norm(text)
    for kws, rho in _RHO_BY_KW:
        if any(k in t for k in kws):
            return rho
    return None


def _first_match(text: str, kws) -> Optional[str]:
    """Primera keyword que aparece en `text` como PALABRA (con plural opcional
    …s/…es). Devuelve la keyword (para justificar) o None. El limite de palabra
    evita que 'lana' caiga dentro de 'plana' o 'aire' dentro de 'aireado'."""
    for k in kws:
        if re.search(r"\b" + re.escape(k) + r"(?:e?s)?\b", text):
            return k
    return None


def _contains_any(text: str, kws) -> bool:
    return _first_match(text, kws) is not None


def _match_kind(text: str) -> Tuple[Optional[str], Optional[str]]:
    """(tipo, keyword) por palabra clave, con prioridad. (None, None) sin match.
    Los asientos y vidrios se resuelven ANTES en `classify_material`."""
    for kind, kws in (("perforated", _KW_PERFORATED), ("membrane", _KW_MEMBRANE),
                      ("cork", _KW_CORK), ("curtain", _KW_CURTAIN),
                      ("carpet", _KW_CARPET), ("porous", _KW_POROUS),
                      ("hard", _KW_HARD)):
        kw = _first_match(text, kws)
        if kw is not None:
            return kind, kw
    return None, None


def _seat_kind(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Clasificacion de asientos/audiencia (correccion del usuario):
      - audiencia/publico/persona -> ('audience', kw): beta real (son personas).
      - asiento/silla/butaca TAPIZADO -> ('upholstered', kw): POROSO sin camara
        (con o sin gente); salvo que sean de madera/plastico/metal -> ('hard', kw).
    (None, None) si no hay asientos."""
    kw = _first_match(text, _KW_AUDIENCE)
    if kw is not None:
        return "audience", kw
    kw = _first_match(text, _KW_SEAT_UPHOLSTERED)
    if kw is not None:
        hardmat = _first_match(text, _KW_SEAT_HARDMAT)
        if hardmat is not None:
            return "hard", hardmat        # sillas de madera/plastico -> duro
        return "upholstered", kw
    return None, None


def _is_double_glazing(text: str) -> Optional[str]:
    return _first_match(text, _KW_DOUBLE)


def _is_glass_pane(text: str) -> Optional[str]:
    """Vidrio en placa (membrana), excluyendo 'lana de vidrio'/'fibra de vidrio'/
    'velo de fibra de vidrio' (esos son porosos)."""
    if _contains_any(text, _KW_GLASS_NOT):
        return None
    return _first_match(text, _KW_GLASS)


# ---------------------------------------------------------------------------
# Estimacion de sigma (poroso) desde el alpha, con fallback por tipo.
# ---------------------------------------------------------------------------
_SIGMA_FALLBACK = {          # [Pa*s/m^2] tipicos (Bies & Hansen / Mechel)
    "porous": 15000.0, "cork": 30000.0, "carpet": 50000.0, "curtain": 5000.0,
    "upholstered": 8000.0,
}


def _alpha_arrays(mat) -> Tuple[np.ndarray, np.ndarray]:
    bands = mat.alpha_bands()
    fb = np.array(sorted(bands), dtype=float)
    ab = np.array([float(bands[int(f)]) for f in fb], dtype=float)
    return fb, ab


def _estimate_sigma(mat, kind: str) -> Tuple[float, str]:
    """(sigma, confianza). Ajusta sigma al alpha (Miki); si el alpha no es
    poroso-compatible cae al tipico por tipo (confianza baja)."""
    fb, ab = _alpha_arrays(mat)
    sigma, _resid, ok = imp.sigma_from_alpha(ab, fb)
    if ok and sigma is not None:
        return float(sigma), "alta"
    return _SIGMA_FALLBACK.get(kind, 15000.0), "baja"


# ---------------------------------------------------------------------------
# Clasificador principal
# ---------------------------------------------------------------------------
def _is_flat_alpha(mat, cv_thresh: float = 0.12) -> bool:
    """True si el alpha es casi plano (coef. de variacion bajo) -> tipicamente un
    'porcentaje fijo de absorcion', inespecifico."""
    _fb, ab = _alpha_arrays(mat)
    mean = float(np.mean(ab))
    if mean <= 1e-9:
        return True
    return float(np.std(ab) / mean) < cv_thresh


def _is_user_material(mat) -> bool:
    cat = _norm(getattr(mat, "category", ""))
    return cat in ("personalizado", "custom", "propio", "usuario", "default")


# ---------------------------------------------------------------------------
# Ajuste de params del modelo al alpha de catalogo (feature 1-2, etapa 2)
# ---------------------------------------------------------------------------
# Decision del usuario (1 Oct 2026): "elegir que modelo le toca a cada alpha",
# o sea el modelo propuesto debe REPRODUCIR el alpha medido. El keyword fija el
# TIPO (prior); los PARAMS se AJUSTAN para que el amortiguamiento del modelo
# coincida con el del catalogo. Objetivo del ajuste = Re(beta) a incidencia
# NORMAL (theta=0), que es LO QUE USA el kernel de perturbacion
# (absorption_patch.compute_xi_shift_with_impedance) y lo que fija el RT/f_S. El
# blanco es beta_from_alpha_random(alpha_cat), identico a lo que usa el camino de
# material (face_materials). Si NINGUN ajuste reproduce ese amortiguamiento
# (residuo alto), se cae a beta REAL (alpha exacto, sin reactancia): no se falsea
# la absorcion por meter un modelo que no corresponde. Esto frena el f_S falso que
# aparecia al aplicar sugerencias con modelos mal ajustados (membrana con Re(beta)
# ~0 -> paredes casi rigidas -> RT explota). Ref: Cox & D'Antonio cap. 5-7
# (inversion de params), Bies & Hansen (sigma). Fit = minimos cuadrados (scipy).

_FIT_FB = np.array([63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0])  # bandas de ajuste
_FIT_CACHE: Dict[tuple, "MaterialImpedance"] = {}


def _beta_re_target(mat, fb: np.ndarray) -> np.ndarray:
    """Re(beta) objetivo = inversion de Paris del alpha de catalogo, igual que el
    camino de material (face_materials.beta_from_alpha_random). Es el
    amortiguamiento 'correcto' que el modelo debe reproducir."""
    ab = np.array([float(mat.alpha(float(f))) for f in fb], dtype=float)
    return np.asarray(_fm.beta_from_alpha_random(ab), dtype=float)


def _model_beta_re(spec: dict, fb: np.ndarray) -> np.ndarray:
    """Re(beta(theta=0)) del modelo por banda (lo que consume el kernel)."""
    s = imp.build_surface(spec)
    return np.array([(imp.Z0 / complex(np.atleast_1d(s.Z(float(f), 0.0))[0])).real
                     for f in fb], dtype=float)


# Layout de ajuste por tipo de spec: (claves, lo, hi, grilla de arranques).
_FIT_LAYOUT = {
    "porous": (["sigma", "thickness", "air_gap"],
               [1e3, 0.005, 0.0], [5e5, 0.3, 0.3],
               [[s, d, g] for s in (2e4, 8e4) for d in (0.02, 0.08)
                for g in (0.0, 0.1)]),
    "membrane": (["mass_per_area", "cavity_depth", "damping"],
                 [0.5, 0.01, 0.01], [60.0, 0.4, 0.6],
                 [[m, D, 0.15] for m in (3, 10, 25) for D in (0.05, 0.15)]),
    "perforated": (["thickness", "hole_diam", "ratio", "cavity_depth"],
                   [5e-4, 3e-4, 5e-3, 0.01], [0.02, 0.02, 0.4, 0.3],
                   [[0.003, dd, r, c] for dd in (0.001, 0.008)
                    for r in (0.03, 0.15) for c in (0.05, 0.10)]),
}


def _fit_spec_to_alpha(mat, spec: dict) -> Tuple[Optional[dict], Optional[float]]:
    """Ajusta los params del `spec` (segun su type) para que Re(beta(theta=0))
    reproduzca beta_from_alpha_random(alpha_cat). Devuelve (spec_ajustado,
    residuo_rms) o (spec, None) si el tipo no se ajusta (helmholtz/multilayer/
    duro). El ajuste pesa mas las bandas graves (donde vive el f_S)."""
    t = str(spec.get("type", "")).lower()
    layout = _FIT_LAYOUT.get(t)
    if layout is None:
        return spec, None
    from scipy.optimize import least_squares
    keys, lo, hi, grid = layout
    fb = _FIT_FB
    bt = _beta_re_target(mat, fb)
    w = np.sqrt(fb[0] / fb)                     # enfasis en graves (sub-Schroeder)

    def mk(p):
        s = dict(spec)                          # preserva extras (p.ej. porous_fill, model)
        for k, val in zip(keys, p):
            s[k] = float(val)
        return s

    def resid(p):
        try:
            return w * (_model_beta_re(mk(p), fb) - bt)
        except Exception:
            return np.full(fb.size, 1e3)

    best = None
    for g0 in grid:
        try:
            r = least_squares(resid, g0, bounds=(lo, hi), max_nfev=60)
            c = float(np.sqrt(np.mean(r.fun ** 2)))
            if best is None or c < best[0]:
                best = (c, mk(r.x))
        except Exception:
            continue
    if best is None:
        return spec, None
    return best[1], best[0]


def _fit_is_acceptable(mat, resid: Optional[float]) -> bool:
    """El modelo ajustado se acepta solo si su amortiguamiento (Re beta)
    reproduce el del catalogo dentro de una tolerancia RELATIVA a la escala de
    beta. Si no, se usa beta real (alpha exacto). Umbral calibrado con los
    materiales reales del profesor (Techo membrana residuo 0.016 pasa; Emplacado
    plano residuo 0.019 no pasa y cae a beta real)."""
    if resid is None:
        return False
    bt = _beta_re_target(mat, _FIT_FB)
    scale = max(float(np.sqrt(np.mean(bt ** 2))), 5e-3)
    return resid <= 0.40 * scale


def _betareal_result(kind: str, base: "MaterialImpedance") -> "MaterialImpedance":
    """Resultado 'beta real' (alpha exacto, sin reactancia) para cuando el modelo
    no reproduce el amortiguamiento. has_model=False, nonspecific=False (beta real
    es fisicamente correcto: no falta un modelo, el modelo candidato no servia)."""
    head = (base.reason.split(":")[0] if base.reason else kind)
    return MaterialImpedance(
        has_model=False, nonspecific=False, kind=kind,
        reason=f"{head}: el modelo no reproduce α → β real (α exacto)",
        justification=(base.justification + " Sin embargo, con params ajustados el "
                       "modelo NO reproduce el amortiguamiento del α de catálogo "
                       "(Re β, residuo alto): se usa α→β real (absorción EXACTA, sin "
                       "reactancia) para no falsear la física. Elegí un modelo a mano "
                       "si querés su corrimiento de fₙ."))


def _material_fit_key(mat):
    try:
        bands = mat.alpha_bands()
        at = tuple(round(float(bands[b]), 4) for b in sorted(bands))
    except Exception:
        at = None
    return (str(getattr(mat, "name", "")), str(getattr(mat, "category", "")), at)


def _alpha_shape(mat) -> str:
    """Forma del α de catálogo (feature 1-2 etapa 2): decide el TIPO de modelo.
      - 'flat'     : α casi plano (cv bajo) -> β real (resistivo, sin reactancia).
      - 'low_peak' : pico en graves que cae -> resonante (membrana/panel).
      - 'mid_peak' : pico en medios -> perforado/membrana.
      - 'rising'   : sube con f -> poroso.
      - 'other'    : indefinido -> se confía en el keyword.
    """
    fb = _FIT_FB
    ab = np.array([float(mat.alpha(float(f))) for f in fb])
    mean = float(np.mean(ab))
    if mean <= 1e-9:
        return "flat"
    cv = float(np.std(ab) / mean)
    pk = int(np.argmax(ab))
    if cv < 0.30:
        return "flat"
    if fb[pk] <= 125.0 and ab[-1] < 0.6 * ab[pk]:
        return "low_peak"
    if ab[-1] > 1.3 * ab[0] and pk >= fb.size - 2:
        return "rising"
    if ab[pk] > 1.3 * ab[0] and ab[pk] > 1.3 * ab[-1]:
        return "mid_peak"
    return "other"


_SHAPE_TYPES = {
    "low_peak": ["membrane"],
    "mid_peak": ["perforated", "membrane"],
    "rising": ["porous"],
    "other": [],
}


def _base_spec_for(t: str, kw_spec: Optional[dict]) -> dict:
    """Spec base de un tipo para el ajuste. Si el keyword dio ESE mismo tipo, se
    reusa (preserva extras como porous_fill/model); si no, genérico (el multi-start
    del fit mueve los params)."""
    if kw_spec is not None and str(kw_spec.get("type", "")).lower() == t:
        return dict(kw_spec)
    return {
        "porous": {"type": "porous", "sigma": 15000.0, "thickness": 0.05,
                   "model": "miki", "air_gap": 0.0},
        "membrane": {"type": "membrane", "mass_per_area": 5.0,
                     "cavity_depth": 0.1, "damping": 0.1},
        "perforated": {"type": "perforated", "thickness": 0.005,
                       "hole_diam": 0.008, "ratio": 0.10, "cavity_depth": 0.05},
    }[t]


def classify_material(mat) -> MaterialImpedance:
    """Clasifica un material y propone (o no) un spec de impedancia por default,
    eligiendo el TIPO por la FORMA del α y AJUSTANDO los params para reproducir el
    α de catálogo (feature 1-2 etapa 2, decisión del usuario 1 Oct 2026).

    Flujo: el keyword/categoría resuelve primero los casos sin modelo (usuario,
    audiencia, duro) e inespecíficos. Para el resto, la FORMA del α (`_alpha_shape`)
    + el keyword fijan los TIPOS candidatos; cada uno se AJUSTA (`_fit_spec_to_alpha`,
    Re β a θ=0 ↔ α de catálogo) y se elige el de menor residuo que PASA la
    tolerancia. Si ninguno reproduce el amortiguamiento, o el α es plano, cae a β
    real (α exacto). Cacheado por (nombre, categoría, α)."""
    key = _material_fit_key(mat)
    if key[2] is not None and key in _FIT_CACHE:
        return _FIT_CACHE[key]
    mi = _classify_impl(mat)

    def _cache(m):
        if key[2] is not None:
            _FIT_CACHE[key] = m
        return m

    # Sin modelo del keyword (usuario/audiencia/duro/inespecífico): no se toca.
    if not (mi.has_model and mi.spec):
        return _cache(mi)
    # Helmholtz/multilayer explícitos: params con dimensiones, no se re-elige tipo.
    kw_type = str(mi.spec.get("type", "")).lower()
    if kw_type not in ("porous", "membrane", "perforated"):
        return _cache(mi)

    shape = _alpha_shape(mat)
    # α plano -> β real (resistivo): la reactancia de un modelo no está justificada
    # y un resonante metería un pico espurio (caso Emplacado: sándwich amortiguado).
    if shape == "flat":
        return _cache(_betareal_result(mi.kind, mi))

    # Tipos candidatos: los que sugiere la FORMA + el del keyword (como alternativa).
    cand_types = list(_SHAPE_TYPES.get(shape, []))
    if kw_type not in cand_types:
        cand_types.append(kw_type)

    bt_scale = max(float(np.sqrt(np.mean(_beta_re_target(mat, _FIT_FB) ** 2))), 5e-3)
    strong = 0.15 * bt_scale        # ajuste "muy bueno": corta la búsqueda
    best = None            # (resid, spec, type)
    for t in cand_types:
        spec0 = _base_spec_for(t, mi.spec)
        spec_fit, resid = _fit_spec_to_alpha(mat, spec0)
        if resid is None or not _fit_is_acceptable(mat, resid):
            continue
        if best is None or resid < best[0]:
            best = (resid, spec_fit, t)
        if resid <= strong:
            break

    if best is None:
        # ningún modelo reproduce el amortiguamiento -> β real (α exacto)
        return _cache(_betareal_result(mi.kind, mi))

    resid, spec_fit, t = best
    mi.spec = spec_fit
    # Conserva la etiqueta fina (cork/carpet/curtain/upholstered/vidrio/…) si el
    # tipo no cambió respecto del keyword; si la FORMA forzó otro tipo, usa ese y
    # actualiza el `reason` (si no, quedaría el texto del tipo viejo, p.ej. poroso).
    if t != kw_type:
        mi.kind = t
        try:
            mi.reason = f"{t} (tipo por forma del α, ajustado): {imp.spec_label(spec_fit)}"
        except Exception:
            mi.reason = f"{t} (tipo por forma del α, ajustado al α de catálogo)"
    mi.confidence = "ajustada al α (forma + β-match)"
    mi.justification += (
        f" Tipo elegido por la forma del α ({shape}); params AJUSTADOS por mínimos "
        f"cuadrados para que Re(β) reproduzca el α de catálogo (modelo «{t}», "
        f"residuo β={resid:.3f}; Cox & D'Antonio cap. 5-7).")
    return _cache(mi)


def _classify_impl(mat) -> MaterialImpedance:
    """Clasifica un material y propone (o no) un spec de impedancia por default.

    Ver el criterio en la cabecera del modulo. NUNCA inventa reactancia sin
    evidencia textual: si el material no cae claramente en un tipo, queda sin
    modelo (nonspecific=True) para que el usuario elija a mano."""
    text = _norm(f"{getattr(mat, 'name', '')} {getattr(mat, 'description', '')}")

    # (1) Material del usuario -> inespecifico por regla (aunque el nombre tenga
    #     keyword: el usuario dijo que sus materiales cargados no llevan modelo).
    if _is_user_material(mat):
        return MaterialImpedance(
            nonspecific=True, kind="usuario",
            reason="material propio/cargado por el usuario (sin modelo automatico)",
            justification=(f"Categoría «{getattr(mat, 'category', '')}» → material "
                           "propio del usuario. Regla del criterio: los materiales "
                           "cargados por el usuario no reciben modelo automático "
                           "(su reactancia no se infiere sin dato), se elige a mano."))

    # (2) Asientos / audiencia (correccion del usuario). Se resuelve ANTES que los
    #     buckets genericos: audiencia = beta real; asiento/silla tapizado = poroso
    #     sin camara (con o sin gente); de madera/plastico = duro.
    seat, seat_kw = _seat_kind(text)
    if seat == "audience":
        return MaterialImpedance(
            has_model=False, nonspecific=False, kind="audiencia",
            reason="audiencia/público: β real (personas, sin construcción)",
            justification=(f"El nombre contiene «{seat_kw}» → audiencia/público "
                           "(personas), no una construcción de pared con reactancia "
                           "definida. Se usa α→β real (amortiguamiento exacto); no "
                           "necesita modelo ni aviso."))

    # (3) Vidrios (correccion del usuario). "Lana de vidrio" es POROSO (cae abajo,
    #     se excluye aca). "Vidrio" solo = membrana rígida (masa alta). "Doble
    #     vidrio" = dos membranas con cámara: el vidrio interior resuena contra la
    #     cámara de aire y el exterior hace de cierre (≈ rígido) -> membrana+cámara.
    dbl = _is_double_glazing(text)
    if dbl is not None:
        t = parse_thickness(text) or 0.003
        m = t * 2500.0
        cav = parse_air_gap(text) or 0.012
        spec = {"type": "membrane", "mass_per_area": round(m, 3),
                "cavity_depth": round(cav, 4), "damping": 0.02}
        return MaterialImpedance(
            spec=spec, has_model=True, kind="doble_vidrio", confidence="media",
            reason=(f"doble vidrio: membrana (vidrio {t*1e3:.0f} mm, m≈{m:.1f} "
                    f"kg/m²) + cámara {cav*1e3:.0f} mm"),
            justification=(f"El nombre contiene «{dbl}» → dos vidrios (membranas) con "
                           f"una cámara de aire. Visto desde la sala, el vidrio "
                           f"interior (masa m≈{m:.1f} kg/m², de {t*1e3:.0f} mm × 2500 "
                           f"kg/m³) resuena contra la cámara de {cav*1e3:.0f} mm, con "
                           f"el vidrio exterior como cierre ≈ rígido → resonador "
                           f"masa-resorte (membrana + cámara, Cox & D'Antonio cap. 6)."))
    glass = _is_glass_pane(text)
    if glass is not None:
        t = parse_thickness(text) or 0.006
        m = t * 2500.0
        cav = parse_air_gap(text) or 0.05
        spec = {"type": "membrane", "mass_per_area": round(m, 3),
                "cavity_depth": round(cav, 4), "damping": 0.02}
        return MaterialImpedance(
            spec=spec, has_model=True, kind="vidrio", confidence="baja",
            reason=(f"vidrio: membrana rígida (masa m≈{m:.1f} kg/m², "
                    f"{t*1e3:.0f} mm)"),
            justification=(f"El nombre contiene «{glass}» (y no «lana/fibra/velo de "
                           f"vidrio», que serían porosos) → panel de vidrio = membrana "
                           f"rígida de masa alta (m≈{m:.1f} kg/m², {t*1e3:.0f} mm × 2500 "
                           f"kg/m³): reflectante, dominada por la masa. Modelada como "
                           f"membrana (Cox & D'Antonio cap. 6)."))

    kind, kw = _match_kind(text)
    if seat == "upholstered":        # asiento/silla tapizado -> poroso sin camara
        kind, kw = "upholstered", seat_kw
    elif seat == "hard":             # silla de madera/plastico -> duro
        kind, kw = "hard", seat_kw

    # (4) Poroso (lana/espuma/poroso/estriado/asiento tapizado) -> poroso Miki.
    #     sigma del alpha; espesor del campo "absorbente de …" (estriado) o del
    #     nombre; camara de "cavidad/suspendido a …". TMM via impedance.porous.
    if kind in ("porous", "cork", "carpet", "curtain", "upholstered"):
        sigma, conf = _estimate_sigma(mat, kind)
        default_t = {"porous": 0.05, "cork": 0.03, "carpet": 0.01,
                     "curtain": 0.005, "upholstered": 0.05}[kind]
        t_abs = parse_absorber_thickness(text)
        t_parsed = parse_thickness(text)
        if t_abs is None and "franja" in text:
            t_parsed = None          # "franjas de 12 mm" es geometría, no espesor
        t = t_abs or t_parsed or default_t
        gap = parse_air_gap(text)
        gap_note = "leída del nombre" if gap else ""
        if kind == "curtain":
            if _contains_any(text, ("contacto", "contra la pared", "al ras",
                                    "pegada", "pegado", "adosada", "adosado")):
                gap = 0.0
                gap_note = "en contacto con la pared → sin cámara"
            elif gap is None:
                gap = 0.05
                gap_note = "default (cuelga con aire detrás)"
        spec = {"type": "porous", "sigma": round(sigma, 1),
                "thickness": round(t, 4), "model": "miki",
                "air_gap": round(gap or 0.0, 4)}
        nice = {"porous": "poroso", "cork": "corcho", "carpet": "alfombra",
                "curtain": "cortina", "upholstered": "asiento tapizado"}[kind]
        s_src = ("ajustada al α de catálogo por mínimos cuadrados (Miki, inversión "
                 "ISO 9053 equiv., Cox & D'Antonio cap. 5-6)" if conf == "alta"
                 else "típica del tipo (el α no es poroso-compatible: no se pudo "
                      "ajustar σ; Bies & Hansen)")
        t_src = (f'espesor {t*1e3:.0f} mm del campo "absorbente de …"' if t_abs
                 else (f"espesor {t*1e3:.0f} mm leído del nombre" if t_parsed
                       else f"espesor {t*1e3:.0f} mm por default ({nice})"))
        gap_src = "" if not gap else f"; cámara {gap*1e3:.0f} mm ({gap_note})"
        why = ("asiento/silla tapizado → relleno poroso (con o sin gente)"
               if kind == "upholstered"
               else "material poroso fibroso/absorbente")
        return MaterialImpedance(
            spec=spec, has_model=True, kind=kind, confidence=conf,
            reason=(f"{nice}: poroso Miki σ≈{sigma:.0f} Pa·s/m², "
                    f"{t*1e3:.0f} mm" + (f" + cámara {gap*1e3:.0f} mm" if gap else "")),
            justification=(f"El nombre/descr. contiene «{kw}» → {why}. Modelo poroso "
                           f"de Miki sobre backing rígido (TMM). σ {s_src}; {t_src}"
                           f"{gap_src}."))

    # (3) Perforado / microperforado -> Maa. Params muy subdeterminados por el
    #     alpha: se estiman con tipicos y se marca confianza baja (editable).
    if kind == "perforated":
        micro = _contains_any(text, ("microperforado", "micro perforado",
                                     "micro-perforado", "mpp"))
        gap_raw = parse_air_gap(text)
        t_parsed = parse_thickness(text)
        t = t_parsed
        if t is not None and gap_raw is not None and abs(t - gap_raw) < 1e-9:
            t = None                 # el unico "NN mm" era el de la camara
        t = t or (0.001 if micro else 0.005)
        cav = gap_raw or 0.05
        d = 0.0005 if micro else 0.008
        spec = {"type": "perforated", "thickness": round(t, 4),
                "hole_diam": d, "ratio": 0.02 if micro else 0.10,
                "cavity_depth": round(cav, 4)}
        cav_src = (f"cavidad {cav*1e3:.0f} mm leída del nombre" if gap_raw
                   else f"cavidad {cav*1e3:.0f} mm por default")
        return MaterialImpedance(
            spec=spec, has_model=True, kind="perforated", confidence="baja",
            reason=("microperforado (Maa)" if micro else "panel perforado (Maa)")
                   + f", cavidad {cav*1e3:.0f} mm (parámetros estimados, editá)",
            justification=(f"El nombre contiene «{kw}» → "
                           + ("panel microperforado (orificio <1 mm, absorción de "
                              "banda ancha por resistencia viscosa)" if micro
                              else "panel perforado")
                           + f" sobre cavidad (resonador de Helmholtz distribuido, "
                             f"Maa 1998). El α no determina de forma única t/d/%: "
                             f"diámetro y % de perforación se ponen en valores "
                             f"típicos y {cav_src} (confianza baja, editable)."))

    # (5) Membrana / placa -> masa-resorte. m = espesor x densidad. Si hay lana
    #     detras (placa de yeso + lana mineral) -> membrana con RELLENO POROSO.
    if kind == "membrane":
        gap_raw = parse_air_gap(text)
        t = parse_thickness(text)
        if t is not None and gap_raw is not None and abs(t - gap_raw) < 1e-9:
            t = None                 # el unico "NN mm" era el de la camara
        rho = parse_density(text) or _density_for(text) or 800.0
        fill = parse_porous_fill(text)
        has_fill = fill is not None and _contains_any(text, ("lana", "fibra", "espuma"))
        if t is not None:
            m = t * rho
            conf = "media"
            m_src = (f"m = espesor {t*1e3:.0f} mm × densidad {rho:.0f} kg/m³ "
                     f"= {m:.1f} kg/m²")
        else:
            t = 0.0125               # placa tipica ~12.5 mm
            m = t * rho
            conf = "baja"
            m_src = (f"sin espesor en el nombre → placa típica {t*1e3:.0f} mm × "
                     f"{rho:.0f} kg/m³ = {m:.1f} kg/m² (editable)")
        cav = gap_raw if gap_raw is not None else (fill if has_fill else 0.05)
        if has_fill:
            cav = max(cav, fill)
        spec = {"type": "membrane", "mass_per_area": round(m, 3),
                "cavity_depth": round(cav, 4), "damping": 0.02}
        if has_fill:
            sfill, _c = _estimate_sigma(mat, "porous")
            spec["porous_fill"] = {"type": "porous", "sigma": round(sfill, 1),
                                   "thickness": round(fill, 4), "model": "miki"}
        fill_txt = (f" con {fill*1e3:.0f} mm de lana en la cámara" if has_fill else "")
        just_fill = (f" La cámara lleva {fill*1e3:.0f} mm de lana (relleno poroso), "
                     f"leído del nombre." if has_fill else "")
        return MaterialImpedance(
            spec=spec, has_model=True, kind="membrane", confidence=conf,
            reason=(f"membrana m≈{m:.1f} kg/m², cámara {cav*1e3:.0f} mm{fill_txt}"),
            justification=(f"El nombre contiene «{kw}» → panel/membrana impermeable "
                           f"sobre cámara (resonador masa-resorte, Cox & D'Antonio "
                           f"cap. 6). {m_src}; cámara {cav*1e3:.0f} mm.{just_fill}"))

    # (6) Duro -> beta real (sin reactancia). ESPECIFICO (no avisa): el alpha->beta
    #     real ya es lo correcto, no falta ningun modelo.
    if kind == "hard":
        return MaterialImpedance(
            has_model=False, nonspecific=False, kind="hard",
            reason="duro: β real (α sin reactancia); no necesita modelo",
            justification=(f"El nombre contiene «{kw}» → superficie dura/rígida "
                           "(o asiento de madera/plástico). Su α es bajo y sin "
                           "resonancia de construcción que modelar. Se usa α→β real "
                           "(amortiguamiento exacto, sin corrimiento de fₙ); no "
                           "necesita modelo ni aviso."))

    # (6) Sin keyword -> inespecifico. Se distingue el alpha plano (porcentaje
    #     fijo) del resto solo para el mensaje.
    _fb, _ab = _alpha_arrays(mat)
    _mean = float(np.mean(_ab))
    _cv = float(np.std(_ab) / _mean) if _mean > 1e-9 else 0.0
    if _is_flat_alpha(mat):
        return MaterialImpedance(
            nonspecific=True, kind="flat",
            reason="α casi plano (porcentaje fijo): sin modelo, elegilo a mano",
            justification=(f"El α es casi plano en frecuencia (coef. de variación "
                           f"{_cv:.2f} < 0.12) y el nombre no tiene palabra clave de "
                           "tipo: es un «porcentaje fijo de absorción», no una "
                           "construcción física. No se le infiere reactancia; se "
                           "elige un modelo a mano si corresponde."))
    return MaterialImpedance(
        nonspecific=True, kind="unknown",
        reason="sin palabra clave de tipo constructivo: elegí el modelo a mano",
        justification=("El nombre/descripción no contiene ninguna palabra clave de "
                       "tipo constructivo (poroso, perforado, membrana, cortina, "
                       "corcho, duro…), así que no se puede inferir el modelo «con "
                       "derecho». Queda sin modelo para elegirlo a mano."))
