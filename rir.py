"""rir.py — Carga y análisis de respuestas al impulso medidas (RIR).

Fase 0 del pipeline de calibración contra mediciones reales (Jul 2026):
del WAV de una RIR salen las tres magnitudes comparables contra el modelo:

    1. FRF medida        -> rir_to_frf()        (comparar forma vs FEM, banda LF)
    2. RT60 por banda    -> rt60_per_band()     (reemplaza al Sabine estimado -> xi_n)
    3. Picos modales     -> find_modal_peaks()  (comparar f_n reales vs FEM)

Diseño:
- Módulo PURO (numpy + scipy, sin Qt) como modal_metrics / sbir / frd.
- Las RIR reales suelen venir TRUNCADAS (ej.: 190 ms) y con banda limitada
  (el sweep no baja de ~70 Hz si lo emiten monitores). Cada resultado lleva
  flags de calidad en lugar de fallar: RT por banda reporta el rango dinámico
  disponible y si el ajuste es confiable.
- El RT usa la integración regresiva de Schroeder + ajuste lineal T30/T20/T10
  (el mejor que entre en el rango dinámico disponible), estilo ISO 3382.

Smoke test: ``python rir.py`` (oráculos completos en ``bench_rir.py``).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfiltfilt, find_peaks

# Bandas de octava estándar (mismas que material_library.BANDS; se repiten
# acá para mantener el módulo autónomo).
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def load_rir(path) -> Tuple[int, np.ndarray]:
    """Carga un WAV de RIR -> (fs, ir) con ir float64 mono.

    - Estéreo: se queda con el canal de mayor energía (una RIR medida con un
      solo micrófono suele venir mono; si viene estéreo, un canal es ruido).
    - Enteros (int16/int32): se escalan a [-1, 1) por el fondo de escala del
      formato — se PRESERVA la escala relativa entre archivos grabados igual
      (no se normaliza al pico).
    """
    with warnings.catch_warnings():
        # WAVs exportados por software de medición traen chunks de metadata
        # que scipy no entiende (warning inofensivo).
        warnings.simplefilter("ignore")
        src = path if hasattr(path, "read") else str(path)
        fs, x = wavfile.read(src)
    x = np.asarray(x)
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float64) / float(np.iinfo(x.dtype).max)
    else:
        x = x.astype(np.float64)
    if x.ndim > 1:
        energies = [float(np.sum(x[:, c] ** 2)) for c in range(x.shape[1])]
        x = x[:, int(np.argmax(energies))]
    return int(fs), x


# ---------------------------------------------------------------------------
# Deconvolución de sweep grabado -> RIR
# ---------------------------------------------------------------------------
def deconvolve_sweep(rec: np.ndarray, inv_filter: np.ndarray, fs: int,
                     pre_ms: float = 20.0,
                     tail_s: Optional[float] = None) -> np.ndarray:
    """Sweep grabado (x) filtro inverso -> RIR recortada alrededor del pico.

    Misma convención que el flujo de IMA (``fftconvolve(rec, inv, 'full')``
    y recorte). ``pre_ms`` conserva un pre-roll antes del directo; ``tail_s``
    fija la cola (default: hasta que la envolvente cae al piso de ruido,
    estimado del último 10 % de la convolución, +10 dB de margen).

    OJO: aplicar esto a algo que YA es una RIR la arruina (doble
    deconvolución). Un sweep grabado dura al menos lo que el sweep;
    una RIR dura ~el RT de la sala.
    """
    rec = np.asarray(rec, dtype=np.float64)
    inv_filter = np.asarray(inv_filter, dtype=np.float64)
    full = fftconvolve(rec, inv_filter, mode="full")
    ipk = int(np.argmax(np.abs(full)))
    i0 = max(0, ipk - int(pre_ms * 1e-3 * fs))
    if tail_s is not None:
        i1 = min(len(full), ipk + int(tail_s * fs))
    else:
        # Piso de ruido de la cola de la convolución (último 10 %):
        tail = full[int(0.9 * len(full)):]
        floor = float(np.sqrt(np.mean(tail ** 2))) or 1e-15
        # Envolvente RMS en ventanas de 10 ms desde el pico
        w = max(1, int(0.010 * fs))
        i1 = len(full)
        for j in range(ipk, len(full) - w, w):
            if np.sqrt(np.mean(full[j:j + w] ** 2)) < floor * 10 ** (10 / 20):
                i1 = j + w
                break
    return full[i0:i1]


# ---------------------------------------------------------------------------
# FRF medida
# ---------------------------------------------------------------------------
def rir_to_frf(ir: np.ndarray, fs: int,
               f_min: float = 10.0, f_max: Optional[float] = None,
               pad_factor: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """FFT de la RIR -> (freq, H) complejo en [f_min, f_max].

    La RIR ES la transferencia del sistema: su FFT da la FRF medida en ese
    punto. ``pad_factor`` agrega zero-padding (interpola el espectro para
    localizar picos más fino; NO agrega resolución real, que queda fijada
    por la duración: df_real = 1/T).
    """
    ir = np.asarray(ir, dtype=np.float64)
    n = int(len(ir) * max(1, int(pad_factor)))
    H = np.fft.rfft(ir, n=n)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    hi = float(f_max) if f_max is not None else fs / 2.0
    m = (f >= float(f_min)) & (f <= hi)
    return f[m], H[m]


def spectrum_db(H: np.ndarray, ref: Optional[float] = None) -> np.ndarray:
    """|H| en dB. Sin ref -> dB relativos al máximo (forma, no nivel)."""
    mag = np.abs(np.asarray(H))
    r = float(ref) if ref else float(np.max(mag)) or 1.0
    return 20.0 * np.log10(np.maximum(mag, 1e-15) / r)


# ---------------------------------------------------------------------------
# RT60 por Schroeder
# ---------------------------------------------------------------------------
@dataclass
class RTResult:
    """Resultado del ajuste de RT en una banda, con flags de calidad."""
    rt60: float          # [s] extrapolado a -60 dB (nan si no ajustó)
    method: str          # "T30" | "T20" | "T10" | "none"
    r2: float            # bondad del ajuste lineal sobre la EDC
    dyn_range_db: float  # rango dinámico útil de la EDC (hasta el ruido)
    ok: bool             # True si el ajuste es confiable

    def __repr__(self):
        if not np.isfinite(self.rt60):
            return f"RT(--, rango {self.dyn_range_db:.0f} dB)"
        star = "" if self.ok else "?"
        return f"RT={self.rt60:.2f}s{star} ({self.method}, r2={self.r2:.3f})"


def band_filter(ir: np.ndarray, fs: int, center: float,
                order: int = 3) -> np.ndarray:
    """Filtro de banda de octava (Butterworth, fase cero con sosfiltfilt)."""
    lo = center / np.sqrt(2.0)
    hi = center * np.sqrt(2.0)
    nyq = fs / 2.0
    hi = min(hi, 0.95 * nyq)
    sos = butter(order, [lo / nyq, hi / nyq], btype="band", output="sos")
    return sosfiltfilt(sos, np.asarray(ir, dtype=np.float64))


def schroeder_curve(ir: np.ndarray, fs: int,
                    trim_tail_frac: float = 0.05
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """Curva de decaimiento (EDC) por integración regresiva de Schroeder.

        EDC(t) = 10*log10( int_t^T ir^2 / int_0^T ir^2 )

    Con RIR truncada la EDC se desploma artificialmente cerca del final
    (queda poca energía por integrar): se descarta el último
    ``trim_tail_frac`` de la curva.
    """
    x2 = np.asarray(ir, dtype=np.float64) ** 2
    total = float(np.sum(x2))
    if total <= 0:
        t = np.arange(len(x2)) / fs
        return t, np.full(len(x2), -np.inf)
    edc = np.cumsum(x2[::-1])[::-1] / total
    n_keep = max(2, int(len(edc) * (1.0 - trim_tail_frac)))
    t = np.arange(n_keep) / fs
    with np.errstate(divide="ignore"):
        edc_db = 10.0 * np.log10(np.maximum(edc[:n_keep], 1e-30))
    return t, edc_db


def _fit_rt(t: np.ndarray, edc_db: np.ndarray,
            lo_db: float, hi_db: float) -> Tuple[float, float]:
    """Ajuste lineal de la EDC entre hi_db y lo_db (ej.: -5 y -25).
    Devuelve (rt60, r2). rt60 = -60/pendiente."""
    m = (edc_db <= hi_db) & (edc_db >= lo_db)
    if int(np.sum(m)) < 8:
        return float("nan"), 0.0
    tt, yy = t[m], edc_db[m]
    A = np.vstack([tt, np.ones_like(tt)]).T
    (slope, _b), res, *_ = np.linalg.lstsq(A, yy, rcond=None)
    if slope >= 0:
        return float("nan"), 0.0
    ss_tot = float(np.sum((yy - yy.mean()) ** 2))
    r2 = 1.0 - float(res[0]) / ss_tot if (len(res) and ss_tot > 0) else 0.0
    return float(-60.0 / slope), r2


def rt_from_ir(ir: np.ndarray, fs: int) -> RTResult:
    """RT60 de una IR (banda ancha o ya filtrada) vía Schroeder.

    Prueba T30 (-5..-35), después T20 (-5..-25), después T10 (-5..-15):
    usa el más largo que entre en el rango dinámico disponible. ``ok`` exige
    al menos T20 con r2 > 0.98 (lineal de verdad, estilo ISO 3382).
    """
    t, edc = schroeder_curve(ir, fs)
    finite = edc[np.isfinite(edc)]
    dyn = float(-finite.min()) if len(finite) else 0.0
    for lo_db, name in ((-35.0, "T30"), (-25.0, "T20"), (-15.0, "T10")):
        if dyn < -lo_db + 5.0:      # margen de 5 dB sobre el piso
            continue
        rt, r2 = _fit_rt(t, edc, lo_db, -5.0)
        if np.isfinite(rt):
            ok = (name in ("T30", "T20")) and (r2 > 0.98)
            return RTResult(rt, name, r2, dyn, ok)
    return RTResult(float("nan"), "none", 0.0, dyn, False)


def rt60_per_band(ir: np.ndarray, fs: int,
                  bands: Optional[List[int]] = None) -> Dict[int, RTResult]:
    """RT60 por banda de octava. Cada banda trae sus flags de calidad
    (una RIR truncada o sin energía LF da bandas no-confiables, no errores)."""
    out: Dict[int, RTResult] = {}
    for c in (bands if bands is not None else BANDS):
        if c * np.sqrt(2.0) >= fs / 2.0:
            continue
        out[int(c)] = rt_from_ir(band_filter(ir, fs, float(c)), fs)
    return out


# ---------------------------------------------------------------------------
# Picos modales
# ---------------------------------------------------------------------------
def find_modal_peaks(freq: np.ndarray, mag_db: np.ndarray,
                     f_lo: float = 30.0, f_hi: float = 200.0,
                     prominence_db: float = 4.0,
                     max_peaks: int = 12) -> List[Tuple[float, float]]:
    """Picos del espectro en [f_lo, f_hi] -> [(f, mag_db)] por prominencia.

    Sobre el espectro de una RIR real conviene el zero-padding de
    rir_to_frf (localiza el pico entre bins). La resolución REAL sigue
    siendo 1/T: dos modos a menos de eso se ven como un solo pico.
    """
    freq = np.asarray(freq, dtype=float)
    mag = np.asarray(mag_db, dtype=float)
    m = (freq >= f_lo) & (freq <= f_hi)
    if int(np.sum(m)) < 5:
        return []
    fsel, ysel = freq[m], mag[m]
    idx, props = find_peaks(ysel, prominence=prominence_db)
    peaks = sorted(zip(props["prominences"], fsel[idx], ysel[idx]),
                   reverse=True)[:max_peaks]
    return sorted((float(f), float(y)) for _p, f, y in peaks)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # IR sintética: 3 modos con RT conocido -> recuperar RT y f_n.
    fs = 48000
    rt_true = 0.40
    f_modes = [85.0, 113.0, 147.0]
    t = np.arange(int(1.0 * fs)) / fs
    tau = rt_true / (3.0 * np.log(10.0))          # decae 60 dB en rt_true
    ir = sum(np.exp(-t / tau) * np.sin(2 * np.pi * fn * t) for fn in f_modes)

    res = rt_from_ir(band_filter(ir, fs, 125.0), fs)
    assert res.ok and abs(res.rt60 - rt_true) / rt_true < 0.10, res
    print(f"[OK] RT banda 125: {res!r} (true {rt_true} s)")

    f, H = rir_to_frf(ir, fs, f_max=300)
    pks = find_modal_peaks(f, spectrum_db(H), 40, 200)
    got = [p[0] for p in pks]
    assert all(any(abs(g - fn) < 2.0 for g in got) for fn in f_modes), got
    print(f"[OK] picos modales: {[f'{g:.1f}' for g in got]} "
          f"(true {f_modes})")
    print("smoke rir.py OK")
