"""
sbir.py
=======

Criterio **SBIR** (Speaker-Boundary Interference Response): el peine de
interferencia entre el sonido directo de una fuente y sus reflexiones en las
superficies cercanas, evaluado en el punto de escucha.

Es un calculo **analitico** y complementario al FEM:
  - El FEM resuelve los modos del recinto (baja frecuencia, campo difuso/modal).
  - El SBIR mira la interferencia geometrica directo+reflejado en el receptor,
    via **fuentes imagen de 1er orden** (campo libre por path), que es donde
    vive el comb filtering tipico del montaje del parlante.

Convencion fisica (identica a sources.py):
  - Fasor temporal e^{+i*omega*t}.
  - Monopolo:  p(x) = i*omega*rho0 * Q * exp(i*k*r) / (4*pi*r),  k = omega/c.

Modelo de imagen de 1er orden
-----------------------------
Cada superficie es un plano (un punto `p0` sobre el plano + su normal `n`).
La fuente en `x_s` se espeja al otro lado del plano en:

    d_signed = (x_s - p0) . n           (distancia firmada fuente-plano)
    x_img    = x_s - 2 * d_signed * n    (posicion de la imagen)

La presion de la imagen en el receptor usa el MISMO monopolo (la distancia
imagen-receptor = longitud real del camino reflejado), atenuada por el
coeficiente de reflexion de presion del material de esa cara:

    R(f) = sqrt(1 - alpha(f))            (de la libreria de materiales)

La presion total en el receptor para una fuente es:

    p_tot(f) = p_dir(f) + sum_paredes R_pared(f) * p_img_pared(f)

y el SBIR (en dB **relativo al sonido directo**, el readout estandar) es:

    SBIR(f) = 20 * log10( |p_tot(f)| / |p_dir(f)| )

Asi 0 dB = anecoico; el "boundary lift" de +6 dB aparece en LF (la imagen llega
en fase, |1+R| -> 2) y el peine de notches arriba. El primer nulo teorico de
control por pared esta en  f ~ c / (4 d)  (d = distancia fuente-pared).

Solo se modela 1er orden (estandar SBIR). El parametro `order` queda reservado;
2do orden seria sumar imagenes de imagenes (no implementado).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from sources import RHO0, C0


# ---------------------------------------------------------------------------
# Coeficiente de reflexion desde alpha
# ---------------------------------------------------------------------------
def reflection_from_alpha(alpha) -> np.ndarray:
    """Coeficiente de reflexion de PRESION (magnitud) desde alpha de Sabine.

        R = sqrt(1 - alpha)

    alpha puede ser escalar o array (por frecuencia). Se clampa a [0, 1] para
    tolerar valores numericamente fuera de rango.
    """
    a = np.clip(np.asarray(alpha, dtype=float), 0.0, 1.0)
    return np.sqrt(1.0 - a)


# ---------------------------------------------------------------------------
# Pared = plano reflectante
# ---------------------------------------------------------------------------
@dataclass
class Wall:
    """Una superficie reflectante como plano infinito (para fuentes imagen).

    point  : (3,) un punto cualquiera sobre el plano (p.ej. el centroide del
             FaceGroup).
    normal : (3,) normal al plano (se normaliza en __post_init__; la
             orientacion +/- no importa para el espejado).
    label  : etiqueta legible ("Piso", "Pared N", ...).
    R      : coeficiente de reflexion de presion. Escalar o array (Nf,). Por
             defecto 1.0 (reflector perfecto, util para oraculos).
    """
    point:  np.ndarray
    normal: np.ndarray
    label:  str = ""
    R:      object = 1.0      # float o np.ndarray (Nf,)
    area:   Optional[float] = None   # m^2; None = plano INFINITO (sin rolloff)

    def __post_init__(self):
        self.point = np.asarray(self.point, dtype=float).reshape(3)
        n = np.asarray(self.normal, dtype=float).reshape(3)
        nl = float(np.linalg.norm(n))
        self.normal = n / nl if nl > 1e-12 else n

    def signed_distance(self, x_s: np.ndarray) -> float:
        """Distancia firmada de la fuente al plano (a lo largo de la normal)."""
        return float(np.dot(np.asarray(x_s, dtype=float).reshape(3) - self.point,
                            self.normal))

    def image_of(self, x_s: np.ndarray) -> np.ndarray:
        """Posicion de la imagen de x_s espejada en este plano -> (3,)."""
        x = np.asarray(x_s, dtype=float).reshape(3)
        return x - 2.0 * self.signed_distance(x) * self.normal

    def R_spectrum(self, nf: int) -> np.ndarray:
        """R como array (nf,) (broadcast del escalar si hace falta)."""
        R = np.asarray(self.R, dtype=float)
        if R.ndim == 0:
            return np.full(nf, float(R))
        return R


# ---------------------------------------------------------------------------
# Rolloff de panel finito (Rindel 1986, aproximacion por zona de Fresnel)
# ---------------------------------------------------------------------------
def finite_panel_factor(x_s: np.ndarray, x_img: np.ndarray, rx: np.ndarray,
                        point: np.ndarray, normal: np.ndarray, area: float,
                        freq: np.ndarray, c: float) -> np.ndarray:
    """Factor k(f) in [0,1] que atenua la reflexion de un panel FINITO.

    Un plano infinito refleja todo; un panel finito solo refleja bien las
    longitudes de onda cuyo primer anillo de Fresnel entra en el panel. Por
    debajo de esa frecuencia la onda es mas grande que el panel y DIFRACTA en
    vez de reflejarse especularmente -> la reflexion (y el notch SBIR) se
    atenua. Es la correccion de tamano finito de Rindel; aca via la razon
    "area del panel / area del primer Fresnel":

        d_eff       = a*b/(a+b)          (a=fuente->punto refl., b=refl->receptor)
        S_Fresnel   = pi * lambda * d_eff
        k(f)        = min(1, area / S_Fresnel)     (lambda = c/f)

    k -> 1 arriba de f_g = c*pi*d_eff/area (panel "grande" vs lambda), y cae
    ~6 dB/oct debajo (panel "chico"). Reduce el realce/notch LF que un plano
    infinito sobreestimaria. Es aproximacion de 1er orden (no Fresnel exacto).
    """
    x_s = np.asarray(x_s, float).reshape(3)
    x_img = np.asarray(x_img, float).reshape(3)
    rx = np.asarray(rx, float).reshape(3)
    n = np.asarray(normal, float).reshape(3)
    dirv = rx - x_img
    denom = float(np.dot(dirv, n))
    if abs(denom) < 1e-12:                       # rasante: sin info de tamano
        return np.ones_like(np.asarray(freq, float))
    t = float(np.dot(np.asarray(point, float).reshape(3) - x_img, n) / denom)
    refl = x_img + t * dirv                      # punto de reflexion sobre el plano
    a = float(np.linalg.norm(refl - x_s))
    b = float(np.linalg.norm(refl - rx))
    d_eff = a * b / max(a + b, 1e-9)
    lam = c / np.maximum(np.asarray(freq, float), 1e-6)
    S_fresnel = np.pi * lam * d_eff
    return np.minimum(1.0, area / np.maximum(S_fresnel, 1e-12))


# ---------------------------------------------------------------------------
# Monopolo de campo libre (espectro)
# ---------------------------------------------------------------------------
def _monopole_spectrum(x_obs: np.ndarray, x_src: np.ndarray,
                       Q_spec: np.ndarray, freq_axis: np.ndarray,
                       c: float, rho0: float) -> np.ndarray:
    """Presion compleja de un monopolo en x_obs sobre freq_axis -> (Nf,).

    p(f) = i*omega*rho0 * Q(f) * exp(i*k*r) / (4*pi*r),  r = |x_obs - x_src|.

    Identico a sources.OmniSource.free_field_pressure pero con Q dependiente de
    f (Q_spec) y vectorizado en frecuencia.
    """
    r = float(np.linalg.norm(np.asarray(x_obs, float).reshape(3)
                             - np.asarray(x_src, float).reshape(3)))
    r = max(r, 1e-9)
    omega = 2.0 * np.pi * np.asarray(freq_axis, dtype=float)
    k = omega / c
    return (1j * omega * rho0 * Q_spec) * np.exp(1j * k * r) / (4.0 * np.pi * r)


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
@dataclass
class SourceSBIR:
    """SBIR de una fuente individual."""
    label:    str
    sbir_db:  np.ndarray      # (Nf,)  20log10(|p_tot|/|p_dir|)
    p_total:  np.ndarray      # (Nf,)  complejo (directo + reflejadas)
    p_direct: np.ndarray      # (Nf,)  complejo (solo directo)


@dataclass
class Notch:
    """Primer nulo teorico de control de un par fuente-pared."""
    source_label: str
    wall_label:   str
    distance:     float       # distancia fuente-pared [m]
    f_notch:      float       # c/(4 d) [Hz]


@dataclass
class SBIRResult:
    freq_axis:      np.ndarray
    per_source:     List[SourceSBIR]
    total_sbir_db:  np.ndarray        # (Nf,) para la suma de todas las fuentes
    total_p_total:  np.ndarray        # (Nf,) complejo
    total_p_direct: np.ndarray        # (Nf,) complejo
    notches:        List[Notch] = field(default_factory=list)

    def band_extremes(self, f_lo: float = 20.0, f_hi: float = 500.0
                      ) -> Tuple[float, float, float, float]:
        """(f_pico, realce_db, f_valle, atenuacion_db) de la curva total en banda.

        realce_db   = maximo realce (pico del comb)   >= 0 tipicamente.
        atenuacion_db = maxima atenuacion (valle), en dB (negativo).
        """
        f = self.freq_axis
        mask = (f >= f_lo) & (f <= f_hi)
        if not np.any(mask):
            return (float("nan"),) * 4
        db = self.total_sbir_db[mask]
        ff = f[mask]
        i_hi = int(np.argmax(db))
        i_lo = int(np.argmin(db))
        return float(ff[i_hi]), float(db[i_hi]), float(ff[i_lo]), float(db[i_lo])

    def first_notches(self, f_lo: float = 20.0, f_hi: float = 500.0) -> List[Notch]:
        """Notches teoricos c/(4d) que caen dentro de [f_lo, f_hi], ordenados."""
        ns = [n for n in self.notches if f_lo <= n.f_notch <= f_hi]
        ns.sort(key=lambda n: n.f_notch)
        return ns


# ---------------------------------------------------------------------------
# Calculo principal
# ---------------------------------------------------------------------------
def sbir_response(
    source_positions: Sequence[Sequence[float]],
    Q_spectrum: np.ndarray,            # (Nf, Ns) complejo
    walls: Sequence[Wall],
    receiver: Sequence[float],
    freq_axis: Sequence[float],
    labels: Optional[Sequence[str]] = None,
    c: float = C0,
    rho0: float = RHO0,
    order: int = 1,
    notch_eps: float = 1e-3,
) -> SBIRResult:
    """Calcula la respuesta SBIR (fuentes imagen de 1er orden).

    Parameters
    ----------
    source_positions : (Ns, 3)  posiciones de las fuentes.
    Q_spectrum       : (Nf, Ns) caudal complejo por fuente y frecuencia
                       (p.ej. SourceArray.amplitudes_spectrum(freq_axis)).
    walls            : lista de Wall (plano + R(f)).
    receiver         : (3,) punto de escucha.
    freq_axis        : (Nf,) eje de frecuencias [Hz].
    labels           : etiquetas por fuente (default "S1", "S2", ...).
    order            : reservado; solo 1 (1er orden) esta implementado.

    Returns
    -------
    SBIRResult
    """
    if order != 1:
        raise NotImplementedError("Solo 1er orden esta implementado (order=1).")

    f = np.asarray(freq_axis, dtype=float)
    nf = f.shape[0]
    pos = np.asarray(source_positions, dtype=float).reshape(-1, 3)
    Q = np.asarray(Q_spectrum, dtype=complex).reshape(nf, -1)
    ns = pos.shape[0]
    rx = np.asarray(receiver, dtype=float).reshape(3)
    if labels is None:
        labels = [f"S{i+1}" for i in range(ns)]

    # R por pared como array (nf,), precomputado una vez.
    walls = list(walls)
    R_walls = [w.R_spectrum(nf) for w in walls]

    per_source: List[SourceSBIR] = []
    notches: List[Notch] = []
    total_dir = np.zeros(nf, dtype=complex)
    total_tot = np.zeros(nf, dtype=complex)

    for s in range(ns):
        x_s = pos[s]
        q_s = Q[:, s]
        p_dir = _monopole_spectrum(rx, x_s, q_s, f, c, rho0)
        p_tot = p_dir.copy()
        for w, R in zip(walls, R_walls):
            x_img = w.image_of(x_s)
            p_img = _monopole_spectrum(rx, x_img, q_s, f, c, rho0)
            # Panel finito (muebles): atenua la reflexion LF (rolloff de Rindel).
            # area=None (paredes) -> plano infinito, sin cambio.
            if w.area is not None:
                k = finite_panel_factor(x_s, x_img, rx, w.point, w.normal,
                                        float(w.area), f, c)
                p_img = p_img * k
            p_tot = p_tot + R * p_img
            # Notch teorico por par fuente-pared.
            d = abs(w.signed_distance(x_s))
            if d > notch_eps:
                notches.append(Notch(labels[s], w.label, d, c / (4.0 * d)))

        sbir_db = 20.0 * np.log10(np.maximum(np.abs(p_tot), 1e-30)
                                  / np.maximum(np.abs(p_dir), 1e-30))
        per_source.append(SourceSBIR(labels[s], sbir_db, p_tot, p_dir))
        total_dir = total_dir + p_dir
        total_tot = total_tot + p_tot

    total_db = 20.0 * np.log10(np.maximum(np.abs(total_tot), 1e-30)
                               / np.maximum(np.abs(total_dir), 1e-30))

    return SBIRResult(
        freq_axis=f,
        per_source=per_source,
        total_sbir_db=total_db,
        total_p_total=total_tot,
        total_p_direct=total_dir,
        notches=notches,
    )


def modal_sbir_crossfade(freq, sbir_db, modal_db, f_schroeder: float,
                         transition_oct: float = 0.5) -> np.ndarray:
    """Curva 'total' HIBRIDA modal(FEM) + imagenes(SBIR), en dB re directo de
    campo libre. Combina los dos modelos en su regimen de validez:

      - f < f_Schroeder: domina la TRANSFERENCIA MODAL (FEM). Debajo de Schroeder
        la solucion modal es completa: contiene las reflexiones de frontera como
        modos, asi que ya "incluye" el SBIR de esas frecuencias.
      - f > f_Schroeder: domina el PEINE ESPECULAR (SBIR imagenes). Ahi la densidad
        modal es alta y el FEM (truncado a N modos) deja de ser confiable.

    Crossfade suave de +/- `transition_oct` octavas alrededor de f_S:
        w(f) = 1 (modal) por debajo de f_S/2^t; 0 (sbir) por encima de f_S*2^t;
        lineal en log2(f) en el medio.  total = w*modal_db + (1-w)*sbir_db.

    Mezclar en dB es adecuado para una curva de comparacion (no reintroduce fase).
    Referencia del cruce: f_Schroeder es la frontera fisica entre el regimen modal
    (discreto) y el difuso/geometrico (Kuttruff, Room Acoustics, cap. 3-4)."""
    f = np.asarray(freq, dtype=float)
    fs = max(float(f_schroeder), 1e-6)
    lo = fs * 2.0 ** (-abs(transition_oct))
    hi = fs * 2.0 ** (+abs(transition_oct))
    denom = np.log2(hi) - np.log2(lo)
    w = np.clip((np.log2(hi) - np.log2(np.maximum(f, 1e-9))) / max(denom, 1e-9),
                0.0, 1.0)
    return w * np.asarray(modal_db, float) + (1.0 - w) * np.asarray(sbir_db, float)


def sbir_from_sources(source_array, walls, receiver, freq_axis,
                      c: float = C0, rho0: float = RHO0,
                      order: int = 1) -> SBIRResult:
    """Conveniencia: calcula el SBIR directamente desde una SourceArray.

    Extrae posiciones, Q(f) (via amplitudes_spectrum, que ya aplica la curva de
    respuesta/fase de cada fuente) y etiquetas.
    """
    f = np.asarray(freq_axis, dtype=float)
    pos = source_array.positions()
    Q = source_array.amplitudes_spectrum(f)        # (Nf, Ns)
    labels = [s.label or f"S{i+1}" for i, s in enumerate(source_array)]
    return sbir_response(pos, Q, walls, receiver, f, labels=labels,
                         c=c, rho0=rho0, order=order)


# ---------------------------------------------------------------------------
# Smoke test minimo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1 pared en x=0 (normal +x), fuente a d=0.5 m, receptor lejano sobre +x.
    d = 0.5
    wall = Wall(point=[0, 0, 0], normal=[1, 0, 0], label="pared", R=1.0)
    f = np.linspace(20.0, 500.0, 2000)
    Ns = 1
    Q = np.ones((len(f), Ns), dtype=complex)
    res = sbir_response([[d, 0.0, 0.0]], Q, [wall], [50.0, 0.0, 0.0], f)
    f_pico, realce, f_valle, aten = res.band_extremes(20, 500)
    f_notch_teor = C0 / (4 * d)
    print("smoke sbir.py:")
    print(f"  notch teorico c/(4d) = {f_notch_teor:.1f} Hz")
    print(f"  valle medido         = {f_valle:.1f} Hz ({aten:.1f} dB)")
    print(f"  realce LF            = {res.total_sbir_db[0]:.2f} dB (esperado ~+6)")
    assert abs(f_valle - f_notch_teor) / f_notch_teor < 0.05, "notch fuera de tol"
    assert res.total_sbir_db[0] > 5.0, "sin boundary lift en LF"
    print("  OK")
