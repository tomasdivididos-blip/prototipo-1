"""
plot_utils.py
=============

Utilidades de graficado reutilizables. Por ahora: los bordes de banda de
tercio de octava (ISO 266) para usar como xticks en graficos en frecuencia
(FRF, RT60, solapamiento modal M(f), etc.).

Sin dependencias mas alla de numpy.
"""

from __future__ import annotations

import numpy as np


# Frecuencias centrales nominales de banda de 1/3 de octava (ISO 266) [Hz].
# Cubren de 16 Hz a 8 kHz, que es mas que suficiente para el regimen modal.
_ISO266_THIRD_OCTAVE_CENTERS = np.array([
    16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315,
    400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
    5000, 6300, 8000,
], dtype=float)


def third_octave_edges(f_min: float, f_max: float) -> np.ndarray:
    """Frecuencias limite (bordes) de las bandas de 1/3 de octava ISO 266
    dentro de [f_min, f_max].

    El borde entre dos bandas adyacentes es la **media geometrica** de sus
    centros nominales:  f_edge = sqrt(fc_i * fc_{i+1}).  Asi el borde superior
    de una banda coincide exactamente con el borde inferior de la siguiente
    (equivale a fc * 2^(1/6) con centros base-2).

    Devuelve un array 1D ordenado con los bordes que caen en el rango pedido.
    Ejemplo (rango modal 20-200 Hz): 22.4, 28.1, 35.4, 44.5, 56.1, 70.7,
    89.1, 111.8, 141.4, 178.9 Hz.
    """
    c = _ISO266_THIRD_OCTAVE_CENTERS
    edges = np.sqrt(c[:-1] * c[1:])               # (N-1,) medias geometricas
    return edges[(edges >= f_min) & (edges <= f_max)]


# ---------------------------------------------------------------------------
# Overlay de corregibilidad EQ (C13/C21) — compartido por FRF, SBIR y CABS/DBA
# ---------------------------------------------------------------------------
def contiguous_runs(fa, mask):
    """[(f_ini, f_fin), ...] de las corridas contiguas donde `mask` es True."""
    spans, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            spans.append((float(fa[i]), float(fa[j])))
            i = j + 1
        else:
            i += 1
    return spans


def draw_correctability_overlay(ax, eqc):
    """Sombrea sobre `ax` (matplotlib) las zonas NO ecualizables (rojo) e inciertas
    (amarillo) del diagnostico de corregibilidad EQ (C13/C21). El veredicto es una
    propiedad de la SALA, asi que el overlay es el mismo en FRF, SBIR y CABS/DBA.
    `eqc` debe tener `.freq_axis` y `.verdict` (0=no corregible, 1=incierto, 2=ok);
    None -> no dibuja nada."""
    if eqc is None:
        return
    fe, vd = eqc.freq_axis, eqc.verdict
    first_no = first_unc = True
    for f0, f1 in contiguous_runs(fe, vd == 0):       # no corregible -> rojo
        ax.axvspan(f0, f1, color='#e05050', alpha=0.13, zorder=0,
                   label='No ecualizable (exige acústica)' if first_no else '_nolegend_')
        first_no = False
    for f0, f1 in contiguous_runs(fe, vd == 1):       # incierto -> amarillo
        ax.axvspan(f0, f1, color='#e0b020', alpha=0.10, zorder=0,
                   label='Corregibilidad incierta' if first_unc else '_nolegend_')
        first_unc = False


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    e = third_octave_edges(20.0, 200.0)
    print("Bordes 1/3 oct en 20-200 Hz:")
    print("  " + ", ".join(f"{x:.1f}" for x in e))
    # Los bordes deben ser estrictamente crecientes y caer en rango.
    assert np.all(np.diff(e) > 0), "bordes no monotonos"
    assert e.min() >= 20.0 and e.max() <= 200.0, "borde fuera de rango"
    # El borde entre 20 y 25 Hz es sqrt(500) ~ 22.36.
    assert abs(e[0] - np.sqrt(20 * 25)) < 1e-9
    print("OK")
