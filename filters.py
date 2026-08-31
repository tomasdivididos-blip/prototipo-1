"""filters.py — filtros de crossover/EQ para la respuesta de fuente.

Diseña H(f) COMPLEJO (magnitud + fase) evaluado sobre un eje de frecuencias, a
partir de prototipos analógicos de `scipy.signal`. Multiplica la curva g(f) del
parlante en `OmniSource.effective_Q_spectrum`, igual que el delay/fase.

Núcleo numpy/scipy (D0: no viola la regla, el diseño de filtros es numérica
estándar, no un solver de EDP de terceros). Se usan filtros ANALÓGICOS (plano s,
`analog=True`) porque la señal acústica es continua: no hay warping bilineal ni
frecuencia de Nyquist, y H(f) queda definido para todo f del eje modal.

Convención de fase: el solver usa e^{+iωt}. `scipy.signal.freqs` devuelve
H(jω)=B(jω)/A(jω) con s=jω, que es exactamente esa convención, así que H se
multiplica directo sobre q(f) (mismo criterio que el delay exp(-i2πfτ)).

Familias (todas las usadas en audio profesional para crossovers/EQ):
  - Butterworth      : máxima planitud en banda de paso; -3 dB en fc.
  - Linkwitz-Riley   : dos Butterworth de orden N/2 en cascada -> -6 dB en fc;
                       el estándar de crossovers (LP+HP suman en fase). N par.
  - Bessel           : retardo de grupo máximamente plano (fase casi lineal).
  - Chebyshev I      : corte más abrupto a cambio de ripple en la banda de paso.
  - Chebyshev II     : banda de paso plana, ripple (equiripple) en la de rechazo.
  - Elíptico (Cauer) : el corte más abrupto para un orden dado; ripple en ambas.

Refs.: Butterworth/Chebyshev/Bessel/elíptico -> Oppenheim & Schafer, "Discrete-
Time Signal Processing" cap. 7; Linkwitz-Riley -> Linkwitz, JAES 24(1), 1976
("Active Crossover Networks for Noncoincident Drivers"). scipy: butter/cheby1/
cheby2/ellip/bessel + freqs (docs.scipy.org/doc/scipy/reference/signal.html).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

# clave -> (etiqueta UI, usa_ripple, usa_atten)
FILTER_TYPES = {
    "none":           ("Sin filtro",                    False, False),
    "butterworth":    ("Butterworth (máx. planitud)",   False, False),
    "linkwitz_riley": ("Linkwitz-Riley (crossover)",    False, False),
    "bessel":         ("Bessel (fase lineal)",          False, False),
    "chebyshev1":     ("Chebyshev I (ripple en paso)",  True,  False),
    "chebyshev2":     ("Chebyshev II (ripple en rechazo)", False, True),
    "elliptic":       ("Elíptico / Cauer (corte abrupto)", True, True),
}

# Órdenes válidos por familia (Linkwitz-Riley solo pares).
def valid_orders(ftype: str):
    if ftype == "linkwitz_riley":
        return [2, 4, 8]
    return [1, 2, 3, 4, 6, 8]


def filter_transfer(freq_hz, ftype: str = "butterworth", order: int = 4,
                    fc: float = 100.0, kind: str = "lowpass",
                    ripple_db: float = 1.0, atten_db: float = 40.0) -> np.ndarray:
    """H(f) complejo (Nf,) sobre `freq_hz`.

    ftype   : clave de FILTER_TYPES.
    order   : orden del filtro (LR usa N par; internamente Butterworth N/2 ²).
    fc      : frecuencia de corte [Hz] (-3 dB Butterworth/Cheby/Bessel; -6 dB LR).
    kind    : "lowpass" | "highpass" (el pedido es pasabajos; pasaaltos gratis).
    ripple_db: ripple de banda de paso [dB] (Chebyshev I / elíptico).
    atten_db : atenuación mínima de rechazo [dB] (Chebyshev II / elíptico).

    Sin filtro / orden<=0 / fc<=0 -> H=1 (reduce EXACTO a no tener filtro).
    """
    fa = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    if ftype in (None, "none") or int(order) <= 0 or float(fc) <= 0.0:
        return np.ones(fa.shape, dtype=complex)

    order = int(order)
    wn = 2.0 * np.pi * float(fc)          # rad/s (prototipo analógico)
    w = 2.0 * np.pi * fa                  # eje en rad/s
    btype = "highpass" if kind == "highpass" else "lowpass"

    if ftype == "linkwitz_riley":
        # LR-N = [Butterworth(N/2)]²  (dos secciones idénticas en cascada).
        n2 = max(1, order // 2)
        b, a = signal.butter(n2, wn, btype=btype, analog=True)
        _, h1 = signal.freqs(b, a, worN=w)
        return (h1 * h1).astype(complex)

    if ftype == "butterworth":
        b, a = signal.butter(order, wn, btype=btype, analog=True)
    elif ftype == "bessel":
        b, a = signal.bessel(order, wn, btype=btype, analog=True, norm="mag")
    elif ftype == "chebyshev1":
        b, a = signal.cheby1(order, float(ripple_db), wn, btype=btype, analog=True)
    elif ftype == "chebyshev2":
        b, a = signal.cheby2(order, float(atten_db), wn, btype=btype, analog=True)
    elif ftype == "elliptic":
        b, a = signal.ellip(order, float(ripple_db), float(atten_db), wn,
                            btype=btype, analog=True)
    else:
        return np.ones(fa.shape, dtype=complex)

    _, h = signal.freqs(b, a, worN=w)
    return h.astype(complex)


def filter_magnitude_db(freq_hz, **kw) -> np.ndarray:
    """|H(f)| en dB (para el preview de la UI). -inf clampeado a -120 dB."""
    h = filter_transfer(freq_hz, **kw)
    mag = 20.0 * np.log10(np.maximum(np.abs(h), 1e-6))
    return mag
