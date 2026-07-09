"""
modal_metrics.py
================

Fase 2c del plan de fuentes. Dos metricas de calidad modal, ambas "conscientes
de la forma" del recinto porque parten de los modos FEM resueltos:

  §8  Figura de merito de la respuesta forzada:
        FoM_flat     = std_f[ L̄ˢ(f) ]   planitud de la respuesta media [dB]
        FoM_espacial = ⟨ σ_esp(f) ⟩_f    consistencia asiento-a-asiento [dB]
      Corrige los 4 defectos del σ_SPL de Gunawan 2018 (un punto, sin perdidas,
      dB crudo, banda invalida): usa ξₙ de materiales, promedia/varia sobre una
      grilla de receptores, suaviza en ENERGIA por 1/N octava y se limita a la
      banda valida.

  §9  Cruce por solapamiento modal numerico (estilo MDCF, Wang/Du/Yu 2026):
        M(f) = B_HP(f) · n(f),   f_cross = min{ f : M̄(f) ≥ 3 }
      Con densidad modal NUMERICA n(f) (ve la forma) y B_HP = 2.2/RT60 del
      modelo Sabine (D5b: ancho de banda por modo necesitaria matriz C, fuera).

No depende de Qt. Reusa la fisica de superposicion modal de acoustic_fem.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Callable, Optional

from sources import RHO0, C0


# ---------------------------------------------------------------------------
# Grilla de receptores por defecto (§8.5)
# ---------------------------------------------------------------------------
def default_receiver_grid(nodes: np.ndarray, nx: int = 5, ny: int = 5,
                          z: float = 1.2, central_frac: float = 0.60,
                          wall_margin: float = 0.5) -> np.ndarray:
    """Grilla nx×ny a altura de oido sobre el `central_frac` central de la
    planta, excluyendo `wall_margin` de cada pared (evita el peor-caso de
    esquina del paper). Devuelve (nx*ny, 3)."""
    nodes = np.asarray(nodes, dtype=float)
    xmin, ymin, zmin = nodes.min(axis=0)
    xmax, ymax, zmax = nodes.max(axis=0)

    def span(lo, hi):
        c = 0.5 * (lo + hi)
        half = 0.5 * (hi - lo) * central_frac
        a = max(lo + wall_margin, c - half)
        b = min(hi - wall_margin, c + half)
        if b <= a:                      # recinto chico: cae al centro
            a = b = c
        return a, b

    ax, bx = span(xmin, xmax)
    ay, by = span(ymin, ymax)
    zc = float(np.clip(z, zmin + 0.1, zmax - 0.1))
    xs = np.linspace(ax, bx, nx)
    ys = np.linspace(ay, by, ny)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    return np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, zc)])


# ---------------------------------------------------------------------------
# Respuesta forzada en una grilla de receptores  -> H (N_R, N_f)
# ---------------------------------------------------------------------------
def _modal_terms(locator, freqs, phis, sources, receivers, freq_axis, damping,
                 flat_source: bool = False):
    """Pieza compartida de la superposicion modal.

    Devuelve `phi_r` (N_R,Nm), `coupling` (Nf,Nm) = src_spec@phi_s (incluye Q(f)),
    `denom` (Nf,Nm) y `omega` (Nf,). La respuesta es
        H[r,f] = iω ρ₀ c² · Σ_n phi_r[r,n] · coupling[f,n] / denom[f,n].

    `flat_source=True` ignora la curva Q(f) de las fuentes (las trata con amplitud
    plana, fase 0) -> da la transferencia de SALA SOLA en esas posiciones, sin la
    fase de fuente (delay/polaridad/FRD). Para el diagnostico de corregibilidad de
    SALA (C13/C21, nivel #5): un delay de fuente es all-pass de la FUENTE, corregible
    desde el drive, no un problema de sala -> no debe contaminar el veredicto.
    """
    freqs = np.asarray(freqs, dtype=float)
    freq_axis = np.asarray(freq_axis, dtype=float)
    Nm = phis.shape[1]
    receivers = np.atleast_2d(np.asarray(receivers, dtype=float))
    N_R = receivers.shape[0]

    omega_n = 2.0 * np.pi * freqs                       # (Nm,)
    omega = 2.0 * np.pi * freq_axis                     # (Nf,)
    xi = (np.full(Nm, float(damping)) if np.isscalar(damping)
          else np.asarray(damping, dtype=float)[:Nm])

    # phi en receptores (N_R, Nm) y en fuentes (Ns, Nm).
    phi_r = np.zeros((N_R, Nm), dtype=float)
    for n in range(Nm):
        vals = locator.evaluate_many(phis[:, n], receivers)
        phi_r[:, n] = np.nan_to_num(vals.real)
    src_pos = sources.positions()
    Ns = len(src_pos)
    phi_s = np.zeros((Ns, Nm), dtype=float)
    for s_idx in range(Ns):
        for n in range(Nm):
            v = locator.evaluate_one(phis[:, n], src_pos[s_idx])
            phi_s[s_idx, n] = 0.0 if v is None else v.real

    if flat_source:                                      # sala sola (sin fase de fuente)
        src_spec = np.ones((len(freq_axis), Ns), dtype=complex)
    else:
        src_spec = sources.amplitudes_spectrum(freq_axis)   # (Nf, Ns) complejo
    coupling = src_spec @ phi_s                          # (Nf, Nm)
    denom = ((omega_n[None, :] ** 2 - omega[:, None] ** 2)
             + 2j * xi[None, :] * omega_n[None, :] * omega[:, None])   # (Nf,Nm)
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    return phi_r, coupling, denom, omega


def compute_forced_response(locator, freqs, phis, sources, receivers,
                            freq_axis, damping=0.03,
                            c: float = C0, rho0: float = RHO0) -> np.ndarray:
    """H(x_r, f) compleja en cada receptor (misma superposicion modal que
    acoustic_fem.frequency_response, vectorizada sobre la grilla).

    Devuelve H de forma (N_R, N_f).
    """
    phi_r, coupling, denom, omega = _modal_terms(
        locator, freqs, phis, sources, receivers, freq_axis, damping)
    A = coupling / denom                                 # (Nf, Nm)
    # H[r,f] = iω ρ₀ c² Σ_n phi_r[r,n] A[f,n]
    H = (phi_r @ A.T) * (1j * omega * rho0 * c ** 2)[None, :]   # (N_R, Nf)
    return H


def forced_response_with_envelope(locator, freqs, phis, sources, receivers,
                                  freq_axis, damping=0.03,
                                  c: float = C0, rho0: float = RHO0,
                                  flat_source: bool = False):
    """(H_real, H_env_mag) para el diagnostico de corregibilidad EQ (C13/C21).

    - `H_real` (N_R,Nf) complejo: la superposicion modal normal (= compute_forced_response).
    - `H_env_mag` (N_R,Nf) real >=0: la magnitud de la suma **sin cancelacion** —
      cada termino modal entra en MAGNITUD (`Σ|·|` en vez de `|Σ|`). Es la
      "envolvente de fase minima estructural": la respuesta que habria si la
      energia modal nunca se cancelara, construida de los propios modos (sin
      cepstrum/Hilbert -> sin el `log(~0)` de los nulos).

    Por desigualdad triangular `|H_real| <= H_env_mag` siempre, asi que la brecha
        cancel_depth = 20log10(H_env_mag) - 20log10(|H_real|)  >= 0
    mide la **cancelacion destructiva** (nulos por interferencia entre modos =
    fase NO minima, no corregibles por EQ). Ver `eq_correctability`.
    """
    phi_r, coupling, denom, omega = _modal_terms(
        locator, freqs, phis, sources, receivers, freq_axis, damping, flat_source=flat_source)
    pref = (np.abs(omega) * rho0 * c ** 2)[None, :]      # (1,Nf), real >=0
    A = coupling / denom                                 # (Nf, Nm)
    H_real = (phi_r @ A.T) * (1j * omega * rho0 * c ** 2)[None, :]
    # Suma de magnitudes por modo: |phi_r[r,n]|·|coupling[f,n]|/|denom[f,n]|.
    mag_A = np.abs(coupling) / np.abs(denom)             # (Nf, Nm)
    H_env_mag = (np.abs(phi_r) @ mag_A.T) * pref         # (N_R, Nf) real >=0
    return H_real, H_env_mag


# ---------------------------------------------------------------------------
# §8  Figura de merito
# ---------------------------------------------------------------------------
@dataclass
class FoMResult:
    FoM_flat: float          # planitud de la respuesta media [dB]
    FoM_espacial: float      # consistencia asiento-a-asiento [dB]
    freq_axis: np.ndarray
    L_mean_smooth: np.ndarray   # L̄ˢ(f) [dB]
    sigma_spatial: np.ndarray   # σ_esp(f) [dB]
    # C8 (criterios §C8): planitud con asimetria pico/nulo. Los PICOS (resonancias)
    # se oyen mas que los nulos (enmascarados) -> las desviaciones POSITIVas sobre la
    # tendencia pesan mas. RMS pesado de (L̄ˢ - media); reduce a FoM_flat si asym=1.
    FoM_flat_asym: float = 0.0


def _smooth_energy_db(power: np.ndarray, freq_axis: np.ndarray,
                      octave_frac: int = 3, p_ref: float = 20e-6) -> np.ndarray:
    """Promedia la POTENCIA en sub-bandas de 1/N octava y pasa a dB.

    power: (..., Nf) magnitudes al cuadrado |H|². Devuelve dB misma forma.
    Suavizar en energia (no en dB) evita que los nulos profundos dominen.
    """
    f = np.asarray(freq_axis, dtype=float)
    half = 2.0 ** (1.0 / (2.0 * octave_frac))           # factor de media banda
    out = np.empty_like(power, dtype=float)
    p2 = p_ref * p_ref
    for i, fc in enumerate(f):
        sel = (f >= fc / half) & (f <= fc * half)
        if not np.any(sel):
            sel = np.array([i])
        mean_pow = power[..., sel].mean(axis=-1)
        out[..., i] = 10.0 * np.log10(np.maximum(mean_pow, 1e-30) / p2)
    return out


def response_figures_of_merit(H: np.ndarray, freq_axis: np.ndarray,
                              octave_frac: int = 3,
                              p_ref: float = 20e-6,
                              asym_weight: float = 3.0) -> FoMResult:
    """Calcula (FoM_flat, FoM_espacial[, FoM_flat_asym]) a partir de H (N_R, N_f).

    Es matematica pura sobre H -> testeable con H sintetico. La banda ya debe
    venir recortada a la valida (f ≤ f_max_malla) por el caller.

    `asym_weight` (C8): peso de las desviaciones POSITIVAS (picos) respecto de las
    negativas (nulos) en `FoM_flat_asym`. asym_weight=1 -> = FoM_flat (RMS sin sesgo);
    >1 penaliza mas los picos (default 3, los picos son ~3x mas audibles).
    """
    H = np.atleast_2d(np.asarray(H))
    f = np.asarray(freq_axis, dtype=float)
    power = np.abs(H) ** 2                                # (N_R, Nf)

    # (2) suavizado por receptor en energia -> dB
    S_hat = _smooth_energy_db(power, f, octave_frac, p_ref)     # (N_R, Nf)
    # (3) respuesta media espacial (energia), luego suavizada
    mean_pow_r = power.mean(axis=0, keepdims=True)              # (1, Nf)
    L_mean_smooth = _smooth_energy_db(mean_pow_r, f, octave_frac, p_ref)[0]
    # (4) dispersion espacial por frecuencia
    sigma_spatial = S_hat.std(axis=0)                          # (Nf,)
    # (5) dos numeros
    FoM_flat = float(np.std(L_mean_smooth))
    FoM_espacial = float(np.mean(sigma_spatial))
    # (6) C8: planitud con asimetria pico/nulo (RMS pesado de la desviacion).
    dev = L_mean_smooth - L_mean_smooth.mean()
    w = np.where(dev > 0.0, float(asym_weight), 1.0)
    FoM_flat_asym = float(np.sqrt(np.average(dev ** 2, weights=w)))
    return FoMResult(FoM_flat, FoM_espacial, f, L_mean_smooth, sigma_spatial,
                     FoM_flat_asym)


# ---------------------------------------------------------------------------
# §10  Corregibilidad por EQ — fase minima vs no-minima  [criterios C13/C21]
# ---------------------------------------------------------------------------
@dataclass
class EQCorrectabilityResult:
    """Diagnostico por frecuencia de que se arregla con EQ global y que exige acustica.

    El resultado NO es un flag binario duro (el test de convergencia #3 mostro que
    binarizar cerca del umbral es fragil aunque la fisica converja). Se reporta:
      - `correctability[f]` en [0,1]: GRADO continuo (1=corregible por EQ global,
        0=exige acustica), via rampas suaves sobre las 3 senales. Converge mejor
        que el binario porque cerca del umbral vale ~0.5 en vez de saltar.
      - `verdict[f]` en {2=si, 1=incierto, 0=no}: 3 estados con banda de incertidumbre.
    Una banda es NO corregible cuando: (a) cancelacion destructiva profunda
    (`cancel_depth`), (b) varia asiento-a-asiento (`spread`), o (c) el EQ necesitaria
    boost > `max_boost_db` (nulo no rellenable).

    Resultados ESCALARES robustos (convergen con npm>=3): `improvement_flat` y
    `fom_espacial`. Para la malla, validar con `eq_diagnosis_mesh_ok` (npm>=3).
    """
    freq_axis: np.ndarray
    cancel_depth: np.ndarray      # (Nf,) [dB] >=0: brecha envolvente-vs-real (cancelacion)
    spread: np.ndarray            # (Nf,) [dB]: desviacion asiento-a-asiento (= sigma_spatial)
    eq_gain_db: np.ndarray        # (Nf,) [dB]: EQ global aplicado (con limite de boost)
    correctability: np.ndarray    # (Nf,) [0,1]: grado continuo de corregibilidad
    verdict: np.ndarray           # (Nf,) int {0=no,1=incierto,2=si}
    frac_correctable: float       # = mean(correctability): grado medio (robusto a malla)
    frac_uncertain: float         # fraccion de banda en zona gris (verdict==1)
    # --- loop cerrado: efecto medido del EQ global de referencia ---
    fom_flat_before: float        # planitud de la respuesta media [dB], pre-EQ
    fom_flat_after: float         # idem post-EQ global
    improvement_flat: float       # = before - after (lo que el EQ gana)
    fom_espacial: float           # consistencia asiento-a-asiento [dB] (cota IRREDUCIBLE)
    espacial_invariant_err: float # |FoM_esp_post - FoM_esp_pre| sin suavizar (~0 = prueba)


def _ramp_down(m: np.ndarray, t: float, w: float) -> np.ndarray:
    """Rampa suave (smoothstep) 1 -> 0 al cruzar el umbral `t`, con semi-ancho `w`
    (banda de incertidumbre). 1 cuando m<=t-w, 0 cuando m>=t+w. Reemplaza el
    escalon duro -> el veredicto deja de flipear por diferencias chicas de malla."""
    x = np.clip((t + w - m) / (2.0 * w), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# Resolucion de malla para el diagnostico de corregibilidad: necesita MAS ppw que
# el solver (ppw~6). El veredicto vive de los signos de phi_n cerca de los nodos,
# que la malla escalonada redondea. Empirico (test de convergencia #3, sala 5x4x3):
# npm>=3 estable, npm=2 subestima cancel_depth ~1.6 dB -> ppw_required ~15.
PPW_EQ_DIAGNOSIS = 15.0


def eq_diagnosis_mesh_ok(h_max: float, f_band_hz: float,
                         ppw_required: float = PPW_EQ_DIAGNOSIS,
                         c: float = C0) -> bool:
    """True si la malla resuelve `f_band_hz` con resolucion suficiente para el
    diagnostico de corregibilidad EQ. Mas estricto que `max_solver_frequency`
    (ppw=6): aca ppw~15 (validado en el test de convergencia)."""
    if h_max <= 0:
        return False
    return c / (ppw_required * h_max) >= f_band_hz


def eq_correctability(H: np.ndarray, freq_axis: np.ndarray,
                      H_env: Optional[np.ndarray] = None,
                      octave_frac: int = 3, p_ref: float = 20e-6,
                      max_boost_db: float = 10.0,
                      cancel_thresh_db: float = 6.0,
                      spread_thresh_db: float = 3.0,
                      uncertainty_db: float = 2.0) -> EQCorrectabilityResult:
    """Diagnostico de corregibilidad EQ (C13/C21) — matematica pura sobre H.

    Cierra el loop (nivel #1 del plan de rigor): simula un **EQ global de fase
    minima** (invierte la respuesta media espacial, con limite de boost por
    headroom), lo aplica a TODOS los receptores y mide la mejora del FoM. Dos
    resultados rigurosos:
      - `improvement_flat`  = cuanto baja la falta de planitud de la media (lo que
        el EQ SI corrige).
      - `fom_espacial`      = la varianza asiento-a-asiento, que un EQ global
        **no puede tocar** (es ganancia comun -> invariante; ver `espacial_invariant_err`).
        Es la cota inferior del error tras CUALQUIER EQ global = la parte que
        exige acustica/ubicacion.

    `H` (N_R, Nf) complejo. `H_env` (N_R, Nf) real opcional (de
    `forced_response_with_envelope`): habilita la senal de cancelacion modal.

    Umbrales (anclados a audibilidad, ajustables -- nivel #6b):
      - `spread_thresh_db=3`: una variacion de nivel asiento-a-asiento >~3 dB en
        banda modal es perceptible/objetable (literatura de spatial variance,
        Welti & Devantier 2003; Toole cap 13). Por debajo, un EQ global sirve a todos.
      - `cancel_thresh_db=6`: los dips son menos audibles que los picos (enmascaramiento,
        Toole cap 4/19), pero un nulo >~6 dB ya es audible y exige boost que gasta headroom.
      - `uncertainty_db=2`: banda de transicion del veredicto (mitiga P2 del test #3;
        del orden de la incertidumbre del modelo). El anclaje fino a curvas de
        audibilidad (Olive/Toole) requiere esos datos -> parcial (ver #6 en el plan).
    """
    H = np.atleast_2d(np.asarray(H))
    f = np.asarray(freq_axis, dtype=float)
    power = np.abs(H) ** 2                                       # (N_R, Nf)

    # Respuesta media espacial (energia) suavizada -> dB.
    mean_pow = power.mean(axis=0, keepdims=True)                 # (1, Nf)
    L_mean = _smooth_energy_db(mean_pow, f, octave_frac, p_ref)[0]   # (Nf,)
    # Dispersion espacial suavizada por receptor.
    S_hat = _smooth_energy_db(power, f, octave_frac, p_ref)      # (N_R, Nf)
    spread = S_hat.std(axis=0)                                   # (Nf,)

    # --- EQ global de fase minima: invierte la media hacia un target plano ---
    target = float(L_mean.mean())
    eq_ideal = target - L_mean                                  # lo que "querria" aplicar
    eq_gain = np.minimum(eq_ideal, float(max_boost_db))         # corta el boost; atenua libre
    H_eq = H * (10.0 ** (eq_gain / 20.0))[None, :]              # ganancia comun a todo r

    fom_before = response_figures_of_merit(H, f, octave_frac, p_ref)
    fom_after = response_figures_of_merit(H_eq, f, octave_frac, p_ref)

    # Prueba de invariancia espacial (sin suavizar -> exacta): el EQ global es
    # ganancia comun g(f), 10log10|H·g|² = 10log10|H|² + 20log10|g|; el 2º termino
    # no depende de r -> std_r() lo cancela. Debe dar ~0 a precision de maquina.
    raw_pre = 10.0 * np.log10(np.maximum(power, 1e-30)).std(axis=0)
    raw_post = 10.0 * np.log10(np.maximum(np.abs(H_eq) ** 2, 1e-30)).std(axis=0)
    espacial_invariant_err = float(np.max(np.abs(raw_post - raw_pre)))

    # --- senal de cancelacion modal (fase minima estructural, sin cepstrum) ---
    if H_env is not None:
        env_pow = np.abs(np.atleast_2d(np.asarray(H_env))) ** 2
        L_env = _smooth_energy_db(env_pow.mean(axis=0, keepdims=True),
                                  f, octave_frac, p_ref)[0]
        cancel_depth = np.maximum(L_env - L_mean, 0.0)          # (Nf,) >=0
    else:
        cancel_depth = np.zeros_like(f)

    # --- grado continuo de corregibilidad (3 senales, la peor manda = AND suave) ---
    # Cada senal aporta una rampa suave 1->0 al cruzar su umbral (±uncertainty_db);
    # asi el veredicto no flipea por diferencias chicas de malla (mitiga P2 del test #3).
    g_cancel = _ramp_down(cancel_depth, float(cancel_thresh_db), float(uncertainty_db))
    g_spread = _ramp_down(spread, float(spread_thresh_db), float(uncertainty_db))
    g_boost = _ramp_down(eq_ideal, float(max_boost_db), float(uncertainty_db))
    correctability = np.minimum(np.minimum(g_cancel, g_spread), g_boost)   # (Nf,)
    verdict = np.where(correctability >= 0.66, 2,
                       np.where(correctability <= 0.33, 0, 1)).astype(int)

    return EQCorrectabilityResult(
        freq_axis=f, cancel_depth=cancel_depth, spread=spread,
        eq_gain_db=eq_gain, correctability=correctability, verdict=verdict,
        frac_correctable=float(correctability.mean()),
        frac_uncertain=float((verdict == 1).mean()),
        fom_flat_before=fom_before.FoM_flat,
        fom_flat_after=fom_after.FoM_flat,
        improvement_flat=fom_before.FoM_flat - fom_after.FoM_flat,
        fom_espacial=fom_before.FoM_espacial,
        espacial_invariant_err=espacial_invariant_err,
    )


# ---------------------------------------------------------------------------
# §10b  Fase minima EXACTA por factorizacion (ceros RHP)  [C13, nivel #2b]
# ---------------------------------------------------------------------------
def modal_minphase_zeros(freqs: np.ndarray, xi, residues: np.ndarray,
                         tol: float = 1e-6):
    """Ceros del numerador modal y cuantos caen en el semiplano derecho (RHP).

    Para UN receptor, la FRF modal es la racional
        H(s) = Σ_n r_n / (s² + 2ξ_n ω_n s + ω_n²) = N(s) / D(s),
        D(s) = Π_n (s² + 2ξ_n ω_n s + ω_n²),   N(s) = Σ_n r_n · D(s)/p_n(s).
    H es de FASE MINIMA sii N no tiene ceros con Re(s) > 0 (definicion exacta;
    `cancel_depth` de `eq_correctability` es solo un proxy de esto). Los polos (D)
    estan siempre en el LHP (ξ>0 -> sistema causal estable).

    Se normaliza por `omega_ref` (media de ω_n) para condicionar `np.roots`: sin
    esto los coeficientes escalan como ω^(2M) (~10^100 para M~20) y la factorizacion
    se vuelve basura. El signo de Re(s) es invariante a la escala positiva.

    Devuelve (zeros_norm, n_rhp, is_minphase). `zeros_norm` en s' = s/omega_ref.
    """
    freqs = np.asarray(freqs, dtype=float)
    r = np.asarray(residues, dtype=float)
    Nm = len(freqs)
    xi_arr = (np.full(Nm, float(xi)) if np.isscalar(xi)
              else np.asarray(xi, dtype=float)[:Nm])
    keep = freqs > 0.0
    freqs, r, xi_arr = freqs[keep], r[keep], xi_arr[keep]
    if len(freqs) < 2:
        return np.array([]), 0, True

    omega_n = 2.0 * np.pi * freqs
    omega_ref = float(omega_n.mean())
    a = omega_n / omega_ref                              # frecuencias normalizadas
    polys = [np.array([1.0, 2.0 * xi_arr[n] * a[n], a[n] ** 2])
             for n in range(len(a))]
    D = np.array([1.0])
    for p in polys:
        D = np.convolve(D, p)                            # D(s'), grado 2M
    N = np.zeros(len(D) - 2)                             # grado 2M-2
    for n in range(len(polys)):
        q, _rem = np.polydiv(D, polys[n])               # D/p_n (exacto: p_n | D)
        N = N + r[n] * q
    N = np.trim_zeros(N, "f")                            # quitar ceros lider nulos
    if len(N) < 2:
        return np.array([]), 0, True                    # sin ceros finitos -> min-phase
    z = np.roots(N)
    n_rhp = int((z.real > tol).sum())
    return z, n_rhp, n_rhp == 0


# ---------------------------------------------------------------------------
# §8b  FSI — Frequency Spacing Index (Rindel 2021)  [criterios §A6]
# ---------------------------------------------------------------------------
def modal_fsi(freqs: np.ndarray, n: int = 25) -> float:
    """Frequency Spacing Index ψ(n) de Rindel (2021).

        ψ = (1/(n-1)) · Σ (δᵢ / δ̄)²     sobre los primeros n modos,

    con δᵢ los intervalos entre modos consecutivos y δ̄ su media. Mide la
    **varianza relativa del espaciado modal**:
      - ψ = 1   -> equiespaciado perfecto (ideal teorico),
      - ψ ≈ 1.3 -> mejor caso real alcanzable,
      - ψ > 1.6 -> EVITAR (distribucion despareja, coloracion).
    Independiente de V y de la absorcion; `l/w` domina sobre `w/h`.

    Usa min(n, #modos disponibles). Devuelve nan si hay < 3 modos (no robusto).
    """
    f = np.sort(np.asarray(freqs, dtype=float))
    f = f[np.isfinite(f)]
    m = min(int(n), len(f))
    if m < 3:
        return float("nan")
    d = np.diff(f[:m])                          # intervalos δᵢ (m-1,)
    dbar = d.mean()
    if dbar <= 0:
        return float("nan")
    return float(np.mean((d / dbar) ** 2))


# ---------------------------------------------------------------------------
# §8c  Umbral perceptual de decaimiento modal (Fazenda 2015)  [criterios §C9]
# ---------------------------------------------------------------------------
# Fazenda, Stephenson & Goldberg (2015), "Perceptual thresholds for the effects
# of room modes as a function of modal decay", JASA 137(3). Un modo COLOREA si su
# tiempo de decaimiento T60_modo > umbral(f). Reemplaza el proxy Q>30 fijo (laxo).
# DOS curvas medidas:
#   "artificial" (sine bursts) = umbrales ABSOLUTOS, sin enmascaramiento -> PEOR
#       CASO / mas estricto. Fig. 4: 0.90 s @32 Hz, rodilla @63 (~0.30), plano
#       ~0.17-0.20 s de 100 Hz para arriba.
#   "music" (muestras musicales) = umbrales con ENMASCARAMIENTO musical -> ESCUCHA
#       REAL / mas permisivo. Fig. 5: 0.51 s @63 Hz, ~0.30 @125, 0.12 @250 Hz.
# El punto @32 Hz de la curva music no se midio aparte; se ancla al de artificial
# (0.90) — abajo de 63 Hz el enmascaramiento no se caracterizo y hay pocos modos.
_FAZENDA_F_ART = np.array([32.0, 63.0, 100.0, 200.0])
_FAZENDA_T60_ART = np.array([0.90, 0.30, 0.20, 0.17])
_FAZENDA_F_MUS = np.array([32.0, 63.0, 125.0, 250.0])
_FAZENDA_T60_MUS = np.array([0.90, 0.51, 0.30, 0.12])


def fazenda_modal_threshold(f, stimulus: str = "artificial"):
    """Umbral perceptual de decaimiento modal T60_thr(f) [s] (Fazenda 2015).

    `stimulus`:
      - "artificial" (default): umbral ABSOLUTO sin enmascaramiento = PEOR CASO
        (conservador para diseno; mas modos flaggeados).
      - "music": umbral con enmascaramiento musical = ESCUCHA REAL (mas permisivo;
        menos modos flaggeados).

    Interpolacion en log-frecuencia, clampada al rango medido. Acepta escalar o
    array. Un modo a frecuencia `f` con decaimiento `T60_modo` **colorea** si
    `T60_modo > fazenda_modal_threshold(f, stimulus)`.
    """
    if stimulus == "music":
        Fx, Ty = _FAZENDA_F_MUS, _FAZENDA_T60_MUS
    elif stimulus == "artificial":
        Fx, Ty = _FAZENDA_F_ART, _FAZENDA_T60_ART
    else:
        raise ValueError("stimulus debe ser 'artificial' o 'music'")
    fa = np.asarray(f, dtype=float)
    lf = np.log(np.clip(fa, Fx[0], Fx[-1]))
    thr = np.interp(lf, np.log(Fx), Ty)
    return float(thr) if np.isscalar(f) or fa.ndim == 0 else thr


# ---------------------------------------------------------------------------
# §9  Cruce por solapamiento modal numerico
# ---------------------------------------------------------------------------
def modal_density(freqs: np.ndarray, f_grid: np.ndarray,
                  octave_frac: int = 3) -> np.ndarray:
    """Densidad modal local n(f) [modos/Hz] por ventana de 1/N octava.

    n(f) = (# modos en [f·2^(-1/2N), f·2^(+1/2N)]) / ancho_de_ventana.
    Robusta (no usa 1/(fₙ−fₙ₋₁) crudo). f_grid: donde evaluar.
    """
    fr = np.asarray(freqs, dtype=float)
    fg = np.asarray(f_grid, dtype=float)
    half = 2.0 ** (1.0 / (2.0 * octave_frac))
    lo, hi = fg / half, fg * half
    width = hi - lo
    counts = np.array([np.count_nonzero((fr >= a) & (fr < b))
                       for a, b in zip(lo, hi)], dtype=float)
    return counts / np.maximum(width, 1e-9)


def modal_overlap_crossover(freqs: np.ndarray,
                            rt60,                      # float o callable f->RT60
                            f_lo: float = 20.0,
                            f_hi: Optional[float] = None,
                            n_pts: int = 500,
                            octave_frac: int = 3,
                            threshold: float = 3.0):
    """Cruce de solapamiento modal M(f) = B_HP(f)·n(f) >= threshold.

    B_HP(f) = 2.2/RT60(f)  (ancho de media potencia, modelo Sabine; D5b: no se
    puede tener ancho por-modo sin matriz C). n(f): densidad numerica (ve la
    forma). Continuidad: con la densidad de Weyl se recupera Schroeder.

    Devuelve (f_cross | None, f_grid, M_curve).
    """
    fr = np.sort(np.asarray(freqs, dtype=float))
    if f_hi is None:
        f_hi = float(fr[-1])
    fg = np.linspace(f_lo, f_hi, n_pts)
    rt = rt60 if callable(rt60) else (lambda _f, _v=float(rt60): _v)
    B_HP = 2.2 / np.maximum(np.array([rt(f) for f in fg]), 1e-6)
    n_f = modal_density(fr, fg, octave_frac)
    M = B_HP * n_f
    # Primer cruce de M sobre el umbral (M ya viene suavizado por la ventana).
    above = M >= threshold
    f_cross = None
    idx = np.where(above)[0]
    if idx.size > 0:
        i = idx[0]
        if i == 0:
            f_cross = float(fg[0])
        else:                            # interpolar el cruce exacto
            f0, f1 = fg[i - 1], fg[i]
            m0, m1 = M[i - 1], M[i]
            f_cross = float(f0 + (threshold - m0) * (f1 - f0) / (m1 - m0)) \
                if m1 != m0 else float(f1)
    return f_cross, fg, M


def schroeder_frequency(rt60_s: float, volume_m3: float) -> float:
    """f_Schroeder analitica clasica (densidad de Weyl): 2000·√(RT60/V)."""
    return 2000.0 * np.sqrt(rt60_s / max(volume_m3, 1e-9))
