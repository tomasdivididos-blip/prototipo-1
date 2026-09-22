"""
modal_decay.py
==============

Decaimiento temporal del campo MANEJADO (modos + drive de las fuentes) en el receptor,
para la comparacion "antes / despues" que pidio el profesor (punto 3): ver como el
array de subs (DBA/CABS) modifica el decaimiento del campo total por debajo de f_S.

QUE ES Y QUE NO ES (honestidad fisica, norte del proyecto):
  - Esto es el decaimiento del CAMPO TOTAL en el receptor con una configuracion de
    fuentes dada. El drive del array (posiciones, delays, polaridad) cambia QUE modos
    se excitan y con que fase, de modo que la ENERGIA modal se redistribuye y el
    decaimiento efectivo del campo total cambia. Es real y medible.
  - NO es un cambio del amortiguamiento propio ξₙ de cada modo (los polos del recinto
    no se tocan: la cola de un modo aislado decae igual). Eso (la impedancia del cono
    del sub como frontera que agrega Δξₙ) es la version rigurosa C2, PENDIENTE.

METODO: el IR modal se obtiene por IFFT de la MISMA H(ω) validada del solver
(`acoustic_fem.frequency_response`, factor c², bench_modal_vs_impedance), asi que el
decaimiento es consistente bit-a-bit con la FRF (no hay una derivacion de residuos
aparte que pueda diverger). De ahi salen:
  - EDC (curva de decaimiento de energia de Schroeder, ISO 3382) via `rir`.
  - CSD / "waterfall" (cumulative spectral decay): el espectro del IR desde t_k hacia
    adelante, para cada tiempo t_k -> se ve cada cresta modal decayendo a su ritmo.

Referencias:
  - Green modal de Helmholtz + factor c²: acoustic_fem.frequency_response (validado
    en bench_modal_vs_impedance.py, v2.11).
  - Schroeder backward integration: M. R. Schroeder, JASA 37 (1965); ISO 3382-1.
  - CSD/waterfall: Berman & Fincham, "The Application of Digital Techniques to the
    Measurement of Loudspeakers", JAES 25 (1977).
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

import acoustic_fem
import rir
from sources import C0, RHO0


# ---------------------------------------------------------------------------
# IR modal (IFFT de la H del solver)
# ---------------------------------------------------------------------------
def _band_window(freqs: np.ndarray, f_lo: float, f_hi: float,
                 taper_frac: float = 0.15) -> np.ndarray:
    """Ventana de banda [f_lo, f_hi] con flancos de coseno alzado (raised cosine)
    para aislar la banda modal sin el ringing de un corte rectangular. taper_frac
    es la fraccion del ancho de banda usada en cada flanco."""
    f = np.asarray(freqs, dtype=float)
    w = np.zeros_like(f)
    bw = max(f_hi - f_lo, 1e-6)
    tp = max(taper_frac * bw, 1e-6)
    # meseta
    w[(f >= f_lo) & (f <= f_hi)] = 1.0
    # flanco inferior
    lo = (f >= f_lo - tp) & (f < f_lo)
    w[lo] = 0.5 * (1.0 - np.cos(np.pi * (f[lo] - (f_lo - tp)) / tp))
    # flanco superior
    hi = (f > f_hi) & (f <= f_hi + tp)
    w[hi] = 0.5 * (1.0 + np.cos(np.pi * (f[hi] - f_hi) / tp))
    return w


def modal_impulse_response(
    modal, sources, receiver, *,
    f_lo: float = 20.0, f_hi: float = 200.0,
    fs: Optional[float] = None, dur: float = 2.0,
    damping=0.03, modal_freqs=None, c: float = C0,
    bandlimit: bool = False,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """IR del campo modal en el receptor, por IFFT de `frequency_response`.

    Devuelve (t, ir, fs). El IR es real y CAUSAL (los polos de H, con +2iξωₙω, ponen
    la cola en el semiplano correcto). fs default = 4·f_hi (Nyquist comodo sobre la
    banda modal); `dur` en segundos fija la resolucion en frecuencia (df = 1/dur) y
    el rango dinamico del decaimiento.

    `bandlimit=False` (default): IR de banda completa. Para el uso "debajo de f_S"
    NO hace falta ventanear: la solucion modal ya esta acotada a los modos < f_S
    (los mismos que la FRF), y la cola de H por encima del ultimo modo es
    despreciable. `bandlimit=True` multiplica H por una ventana [f_lo, f_hi] con
    flancos de coseno; OJO: es una ventana REAL (fase cero) -> introduce un
    pre-ring simetrico que, por la periodicidad de la IFFT, envuelve al final del IR
    y falsea la cola de la EDC. Usar solo para inspeccion espectral, NO para RT.

    Consistencia: usa las MISMAS freqs efectivas (`modal_freqs`, Capa 0) y el mismo
    `damping` por modo que la FRF -> el decaimiento concuerda con la transferencia."""
    if fs is None:
        fs = max(4.0 * float(f_hi), 800.0)
    fs = float(fs)
    N = int(round(fs * float(dur)))
    if N < 16:
        N = 16
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)             # 0 .. fs/2, N//2+1 puntos
    fr = modal.freqs if modal_freqs is None else np.asarray(modal_freqs, dtype=float)
    H = acoustic_fem.frequency_response(
        modal.locator, fr, modal.phis, sources, receiver,
        freq_axis=freqs, damping=damping, c=c)
    if bandlimit:
        H = H * _band_window(freqs, f_lo, f_hi)
    ir = np.fft.irfft(H, n=N)
    t = np.arange(N) / fs
    return t, ir, fs


# ---------------------------------------------------------------------------
# EDC (Schroeder) y RT del campo manejado
# ---------------------------------------------------------------------------
def energy_decay_db(ir: np.ndarray, fs: float) -> Tuple[np.ndarray, np.ndarray]:
    """EDC (curva de decaimiento de energia) en dB, normalizada a 0 dB en t=0.
    Para un IR SINTETICO limpio se desactiva el truncado por ruido de Lundeby
    (no hay piso de ruido; el crosspoint podria cortar mal una cola exponencial)."""
    t, edc = rir.schroeder_curve(np.asarray(ir, dtype=float), int(round(fs)),
                                 noise_trunc=False)
    return t, edc


def decay_time(ir: np.ndarray, fs: float) -> "rir.RTResult":
    """RT (T30/T20/T10) del campo manejado, via `rir.rt_from_ir` sobre el IR sintetico
    (sin truncado de ruido: se computa la EDC limpia y se ajusta la pendiente)."""
    t, edc = energy_decay_db(ir, fs)
    finite = edc[np.isfinite(edc)]
    dyn = float(-finite.min()) if len(finite) else 0.0
    for lo_db, name in ((-35.0, "T30"), (-25.0, "T20"), (-15.0, "T10")):
        if dyn < -lo_db + 5.0:
            continue
        rt, r2 = rir._fit_rt(t, edc, lo_db, -5.0)
        if np.isfinite(rt):
            ok = (name in ("T30", "T20")) and (r2 > 0.98)
            return rir.RTResult(rt, name, r2, dyn, ok)
    return rir.RTResult(float("nan"), "none", 0.0, dyn, False)


# ---------------------------------------------------------------------------
# CSD / waterfall (cumulative spectral decay)
# ---------------------------------------------------------------------------
def cumulative_spectral_decay(
    ir: np.ndarray, fs: float, *,
    f_lo: float = 20.0, f_hi: float = 200.0,
    n_slices: int = 24, slice_span_s: float = 0.30,
    ref_db: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Waterfall (CSD): para una serie de tiempos de arranque t_k, toma el IR DESDE
    t_k (ventana Hann de `slice_span_s`) y calcula su espectro. Muestra como cada
    cresta modal decae con el tiempo.

    Devuelve (freqs, times, Z_db) con:
      - freqs (Nf,): eje de frecuencia recortado a [f_lo, f_hi].
      - times (n_slices,): tiempos de arranque de cada rebanada.
      - Z_db (n_slices, Nf): nivel [dB] re el maximo global (o `ref_db`).
    """
    ir = np.asarray(ir, dtype=float)
    fs = float(fs)
    N = len(ir)
    total_s = N / fs
    win_n = max(16, int(round(slice_span_s * fs)))
    # los arranques van de 0 hasta que la ventana entra entera en el IR
    t_last = max(0.0, total_s - slice_span_s)
    times = np.linspace(0.0, t_last, int(n_slices))
    han = np.hanning(win_n)
    nfft = int(2 ** np.ceil(np.log2(win_n * 2)))
    fbin = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band = (fbin >= f_lo) & (fbin <= f_hi)
    rows = []
    for tk in times:
        i0 = int(round(tk * fs))
        seg = ir[i0:i0 + win_n]
        if len(seg) < win_n:
            seg = np.concatenate([seg, np.zeros(win_n - len(seg))])
        S = np.fft.rfft(seg * han, n=nfft)
        rows.append(np.abs(S[band]))
    Z = np.asarray(rows)                                   # (n_slices, Nf)
    ref = float(np.max(Z)) if ref_db is None else 1.0
    with np.errstate(divide="ignore"):
        Z_db = 20.0 * np.log10(np.maximum(Z, 1e-30) / max(ref, 1e-30))
    if ref_db is not None:
        Z_db = Z_db - ref_db
    return fbin[band], times, Z_db
