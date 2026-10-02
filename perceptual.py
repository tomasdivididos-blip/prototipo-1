"""
perceptual.py
=============

Umbrales perceptuales para acustica de salas a baja frecuencia. Por ahora: el
umbral de DECAIMIENTO MODAL de Fazenda, Stephenson & Goldberg (2015), que dice a
partir de que tiempo de decaimiento T60 de un modo su efecto se vuelve AUDIBLE.
Sirve para que el analisis de modos / decaimiento no solo muestre numeros, sino
que diga cuales modos decaen audiblemente de mas.

Fuente:
  B. M. Fazenda, M. Stephenson, A. Goldberg, "Perceptual thresholds for the
  effects of room modes as a function of modal decay", JASA 137(3), 1088-1098
  (2015). referencias/Fazenda...JASA 137.pdf.

Datos (digitalizados de las figuras del paper; T = umbral de T60 modal [s]):
  - ARTIFICIAL (Fig. 4, sine-burst, nivel de reproduccion 85 dB SPL): umbral
    ABSOLUTO (sin enmascaramiento), el mas estricto. Decrece de ~0.9 s @32 Hz a
    ~0.17 s @200 Hz, con una RODILLA marcada en 63 Hz; por encima de 100 Hz el
    umbral es practicamente plano (el paper reporta diferencias significativas
    solo entre 63 Hz y el resto).
  - MUSIC (Fig. 5, muestras musicales, promedio de HC/LEN): umbral ECOLOGICO,
    mas PERMISIVO porque los eventos musicales enmascaran la cola modal. ~0.51 s
    @63 Hz a ~0.12 s @200-250 Hz.

Interpretacion: si el T60 de un modo esta POR DEBAJO del umbral de su frecuencia,
su decaimiento NO deberia ser audible (reducirlo mas no da mejora perceptual, cf.
Fazenda y tambien Karjalainen et al.). Si esta POR ENCIMA, es candidato a
tratamiento/control.

AVISOS (norte del proyecto = exactitud; esto es un APOYO perceptual, no fisica):
  - Son umbrales MEDIOS de un panel de oyentes, con intervalos de confianza
    anchos a graves (ver CI del paper): un umbral, no una frontera dura.
  - El artificial de 85 dB sube a graves con el nivel (interaccion nivel x
    frecuencia significativa < 100 Hz); a 70 dB el umbral a 63 Hz es ~0.47 s.
  - Fuera del rango medido ([32, 200] Hz artificial, [63, 250] Hz musica) se
    EXTRAPOLA PLANO (se mantiene el valor del extremo); no hay dato ahi.
  - La interpolacion es lineal en log(frecuencia) entre los puntos medidos.
"""

from __future__ import annotations

import numpy as np

# (frecuencia [Hz], umbral de T60 [s]) digitalizados de Fazenda 2015.
_ANCHORS = {
    # Fig. 4, sine-burst, 85 dB SPL (umbral absoluto, estricto).
    "artificial": [(32.0, 0.90), (63.0, 0.30), (100.0, 0.21),
                   (150.0, 0.19), (200.0, 0.17)],
    # Fig. 5, musica (promedio HC/LEN), umbral ecologico (permisivo).
    "music": [(63.0, 0.51), (125.0, 0.30), (250.0, 0.12)],
}

STIMULI = tuple(_ANCHORS.keys())


def modal_decay_threshold(f, stimulus: str = "artificial"):
    """Umbral perceptual de T60 modal [s] a la(s) frecuencia(s) `f` [Hz].

    `stimulus`: "artificial" (sine-burst 85 dB, umbral ABSOLUTO/estricto, default)
    o "music" (ecologico/permisivo). Interpola lineal en log(f) entre los puntos
    medidos y extrapola PLANO fuera del rango. Devuelve escalar o np.ndarray segun
    la entrada. Ver referencia y avisos en el docstring del modulo.
    """
    key = stimulus if stimulus in _ANCHORS else "artificial"
    anchors = _ANCHORS[key]
    fs = np.array([a[0] for a in anchors], dtype=float)
    ts = np.array([a[1] for a in anchors], dtype=float)
    f_arr = np.asarray(f, dtype=float)
    # np.interp ya hace clamp plano fuera de [fs[0], fs[-1]]; el clip evita log(0).
    lf = np.log(np.clip(f_arr, 1e-6, None))
    out = np.interp(lf, np.log(fs), ts)
    return float(out) if np.ndim(f) == 0 else out


def is_decay_audible(f, rt60, stimulus: str = "artificial"):
    """True si el decaimiento T60 (`rt60` [s]) de un modo a `f` [Hz] supera el
    umbral perceptual (es candidato a ser audible). RT60 no finito (modo sin
    amortiguamiento) -> True."""
    thr = modal_decay_threshold(f, stimulus)
    rt = np.asarray(rt60, dtype=float)
    audible = ~np.isfinite(rt) | (rt > thr)
    return bool(audible) if np.ndim(rt60) == 0 else audible
