"""composed_response.py — Respuesta compuesta canónica (modal + SBIR), SPL absoluto.

Única fuente de verdad de "la respuesta en el receptor" que comparten FRF, SBIR y
CABS (grupo A del backlog del profesor; ver `plan_respuesta_compuesta.md`). Combina
los dos modelos en su régimen de validez:

  - la TRANSFERENCIA MODAL (FEM, Green con c², absoluta en Pa) debajo de f_Schroeder,
    donde la solución modal es completa (contiene las reflexiones como modos);
  - el PEINE ESPECULAR (SBIR de imágenes de 1er orden, absoluto en Pa) por encima,
    donde la densidad modal es alta y el FEM truncado deja de ser confiable;

con un crossfade suave en f_Schroeder (`sbir.modal_sbir_crossfade`). Todo en SPL
absoluto re 20 µPa (dBSPL): es el nivel que graba un micrófono calibrado y la
referencia que ya usa el plot de la FRF (decisión D1, plan §2). La FRF modal ya está
en dBSPL (factor c² de B5); el SBIR, que internamente es presión absoluta en Pa
(`SBIRResult.total_p_total`), se lleva a dBSPL con la misma referencia.

Caveat honesto (D1): el nivel absoluto es físico solo si las fuentes traen su nivel
real (sensibilidad de FRD/CLF/TRF). Una fuente con Q nominal (monopolo Q=1, sin
curva) da un dBSPL referido a esa unidad nominal, no medible con un sonómetro. La
escala es la misma para la parte modal y la SBIR (misma Q, misma referencia), así
que el crossfade queda invariante.

Reducciones exactas (garantizadas por `bench_composed_response.py`):
  - walls vacías / None  -> la compuesta ES la FRF modal (20log10|H|/pref).
  - modal_result = None  -> la compuesta ES el SBIR absoluto.

D0: numpy + acoustic_fem/sbir/sources del propio proyecto. Sin Qt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

import acoustic_fem
import sbir as _sbir
from sources import C0, RHO0

# Referencia SPL estándar (Pa). IDÉNTICA a la del plot de FRF (acoustic_panel,
# FRFDialog: `_P_REF = 20e-6`), para que la compuesta y la FRF coincidan en nivel.
P_REF = 20e-6


@dataclass
class ComposedResponse:
    """Respuesta compuesta en un receptor, en SPL absoluto (dBSPL).

    composed_spl es la curva "de verdad" (la que muestran FRF/SBIR/CABS). modal_spl
    y sbir_spl son las componentes para graficar/diagnóstico. H_modal y p_sbir son
    las presiones complejas (Pa) por si el downstream necesita fase/audio.
    """
    freq: np.ndarray                          # (Nf,)
    composed_spl: np.ndarray                  # (Nf,) dBSPL
    modal_spl: Optional[np.ndarray] = None    # (Nf,) dBSPL modal-only (None si sin modos)
    sbir_spl: Optional[np.ndarray] = None     # (Nf,) dBSPL SBIR-only (None si sin paredes)
    f_schroeder: Optional[float] = None
    H_modal: Optional[np.ndarray] = None      # (Nf,) complejo, Pa
    p_sbir: Optional[np.ndarray] = None       # (Nf,) complejo, Pa (directo + imágenes)
    has_modal: bool = False
    has_sbir: bool = False


def to_spl(p_complex) -> np.ndarray:
    """Presión compleja (Pa) -> SPL absoluto (dBSPL re 20 µPa)."""
    return 20.0 * np.log10(np.maximum(np.abs(p_complex), 1e-30) / P_REF)


def composed_response(sources, receiver, freq, *,
                      modal_result=None, walls=None, modal_freqs=None,
                      f_schroeder: Optional[float] = None,
                      damping=0.03, transition_oct: float = 0.5,
                      c: float = C0, rho0: float = RHO0) -> ComposedResponse:
    """Respuesta compuesta modal + SBIR en un receptor, en SPL absoluto.

    Parameters
    ----------
    sources : SourceArray
        Fuentes activas; su `amplitudes_spectrum(freq)` ya aplica Q(f)/fase/filtros.
    receiver : (3,)
        Punto de escucha en coordenadas de sala.
    freq : (Nf,)
        Eje de frecuencias [Hz] (arbitrario; no hace falta linspace).
    modal_result : objeto con `.locator`, `.freqs`, `.phis` (ModalSolution o shim).
        None -> sin componente modal (la compuesta es SBIR puro).
    walls : lista de `sbir.Wall`.
        None o vacía -> sin SBIR (la compuesta es modal pura).
    modal_freqs : (Nm,) opcional
        Frecuencias de resonancia efectivas (Capa 0, Im(β) -> fₙ corrida). None ->
        las rígidas de `modal_result.freqs`.
    f_schroeder : float
        Frontera del crossfade. REQUERIDA si hay modal Y SBIR.
    damping : float | (Nm,)
        ξ uniforme o por modo.

    Returns
    -------
    ComposedResponse
    """
    freq = np.asarray(freq, dtype=float)
    has_modal = (modal_result is not None
                 and getattr(modal_result, "freqs", None) is not None
                 and len(modal_result.freqs) > 0)
    walls = list(walls) if walls is not None else []
    has_sbir = len(walls) > 0

    modal_spl = None
    H_modal = None
    if has_modal:
        freqs_res = (np.asarray(modal_result.freqs, dtype=float) if modal_freqs is None
                     else np.asarray(modal_freqs, dtype=float))
        H_modal = acoustic_fem.frequency_response(
            modal_result.locator, freqs_res, modal_result.phis,
            sources, receiver, freq_axis=freq, damping=damping, c=c, rho0=rho0)
        modal_spl = to_spl(H_modal)

    sbir_spl = None
    p_sbir = None
    if has_sbir:
        res = _sbir.sbir_from_sources(sources, walls, receiver, freq, c=c, rho0=rho0)
        p_sbir = res.total_p_total
        sbir_spl = to_spl(p_sbir)

    if has_modal and has_sbir:
        if f_schroeder is None:
            raise ValueError(
                "composed_response: hay componente modal Y SBIR, así que f_schroeder "
                "es requerida para el crossfade.")
        composed_spl = _sbir.modal_sbir_crossfade(
            freq, sbir_spl, modal_spl, float(f_schroeder),
            transition_oct=transition_oct)
    elif has_modal:
        composed_spl = modal_spl.copy()
    elif has_sbir:
        composed_spl = sbir_spl.copy()
    else:
        raise ValueError(
            "composed_response: sin componente modal y sin SBIR -> nada que componer.")

    return ComposedResponse(
        freq=freq, composed_spl=composed_spl,
        modal_spl=modal_spl, sbir_spl=sbir_spl,
        f_schroeder=(float(f_schroeder) if f_schroeder is not None else None),
        H_modal=H_modal, p_sbir=p_sbir,
        has_modal=has_modal, has_sbir=has_sbir)
