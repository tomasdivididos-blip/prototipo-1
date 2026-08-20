"""
sources.py
==========

Modulo de fuentes sonoras puntuales omnidireccionales (monopolos) para
inyectar en solvers acusticos. Disenado para ser importado por fem_modal.py.

Convencion fisica:
   - Fasor temporal e^{+i*omega*t} (estandar en acustica).
   - Q (caudal volumetrico, "volume velocity") en m^3/s, complejo:
     |Q| controla la amplitud, arg(Q) la fase relativa entre fuentes.
   - La presion radiada por un monopolo en campo libre es
        p(x) = i*omega*rho0 * Q * exp(i*k*r) / (4*pi*r),
     con r = ||x - x_s||  y  k = omega/c.
   - El campo total de varias fuentes incoherentes-en-fase pero coherentes
     en el solver es la superposicion lineal de los campos individuales
     (la ecuacion de Helmholtz es lineal).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constantes fisicas (aire a 20 C, 1 atm)
# ---------------------------------------------------------------------------
RHO0 = 1.21          # densidad de equilibrio del aire [kg/m^3]
C0 = 343.0           # velocidad del sonido en aire [m/s]
Z0 = RHO0 * C0       # impedancia caracteristica del aire [Pa s / m]


# ---------------------------------------------------------------------------
# Fuente puntual
# ---------------------------------------------------------------------------
def q_from_sensitivity(sensitivity_dB: float, power_W: float = 1.0,
                        f_ref: float = 1000.0) -> complex:
    """Convierte sensibilidad de altavoz (dB SPL @ 1W/1m) a caudal volumetrico Q.

    Modelo de monopolo:  |p(1m)| = omega * rho0 * |Q| / (4*pi)
    Despejando |Q| para la presion equivalente a la sensibilidad a f_ref:

        p_1W1m = 20e-6 * 10^(sensitivity_dB / 20)
        |Q| = p_1W1m * 4*pi / (2*pi*f_ref * rho0) * sqrt(power_W)

    Ejemplo: 90 dB/W/m @ 1 kHz, 1 W  →  |Q| ≈ 1.05e-3 m³/s
    """
    p_ref_Pa = 20e-6                              # Pa
    p_1w1m   = p_ref_Pa * 10.0 ** (sensitivity_dB / 20.0)
    omega_r  = 2.0 * np.pi * f_ref
    q_mag    = p_1w1m * 4.0 * np.pi / (omega_r * RHO0) * np.sqrt(max(power_W, 0.0))
    return complex(q_mag, 0.0)


# ---------------------------------------------------------------------------
# Respuesta en frecuencia de una fuente (Fase 0 — plan_fuentes)
# ---------------------------------------------------------------------------
@dataclass
class SourceResponse:
    """Respuesta en frecuencia de una fuente como GANANCIA compleja relativa
    al Q baseline (effective_Q).

    Decision de diseno (16 Jun 2026, opcion 1 del plan): la curva NO es un SPL
    absoluto, sino un multiplicador adimensional g(f) que se aplica encima del
    Q que la fuente ya tiene hoy:

        effective_Q_spectrum(f) = effective_Q() * g(f)

    Ventaja: 'sin curva' equivale exactamente a g(f) ≡ 1, asi el Q de hoy queda
    intacto como ancla y la FRF baseline se reproduce bit a bit. El FRD real
    (SPL absoluto medido) entra en Fase 1 convirtiendolo a g(f) = Q_FRD/Q_base.

    Almacena muestras:
        freq_pts  : (Nf,) frecuencias [Hz], crecientes.
        gain_db   : (Nf,) magnitud de la ganancia [dB]   (0 dB = x1).
        phase_rad : (Nf,) fase [rad], convencion e^{+iωt}, SIN envolver
                    (un retardo τ da fase lineal -2πfτ; la interpolacion
                    lineal de una fase desenvuelta es exacta).

        g(f) = 10^(gain_db/20) * exp(i * phase_rad)
    """

    freq_pts:  np.ndarray
    gain_db:   np.ndarray
    phase_rad: np.ndarray
    name:      str = ""
    anchor:    str = ""        # "absolute" | "relative" | "" (sintetica)

    def __post_init__(self):
        self.freq_pts  = np.asarray(self.freq_pts,  dtype=float)
        self.gain_db   = np.asarray(self.gain_db,   dtype=float)
        self.phase_rad = np.asarray(self.phase_rad, dtype=float)

    def gain_spectrum(self, freq_axis) -> np.ndarray:
        """g(f) complejo muestreado sobre freq_axis -> (Nf,) complex.

        Interpola la magnitud en dB (= log-amplitud, estable) y la fase en
        rad, ambas linealmente. Fuera de la cobertura del archivo: hold-flat
        en los bordes (comportamiento de np.interp), documentado en el plan.
        """
        fa = np.atleast_1d(np.asarray(freq_axis, dtype=float))
        mag_db = np.interp(fa, self.freq_pts, self.gain_db)
        ph     = np.interp(fa, self.freq_pts, self.phase_rad)
        return (10.0 ** (mag_db / 20.0)) * np.exp(1j * ph)

    def coverage(self) -> Tuple[float, float, int]:
        """(f_min, f_max, n_puntos) de la curva, para mostrar en la UI."""
        return float(self.freq_pts[0]), float(self.freq_pts[-1]), len(self.freq_pts)

    # ----- construccion desde un FRD (Fase 1) -------------------------------
    @classmethod
    def from_frd(cls, freq_hz, spl_db, phase_rad=None, *,
                 anchor: str = "absolute",
                 q_base: float = 1.0,
                 f_ref: float = 1000.0,
                 rho0: float = RHO0,
                 name: str = "FRD") -> "SourceResponse":
        """Construye la ganancia g(f) a partir de una medicion FRD (SPL + fase).

        Mapeo monopolo (§3.1 del plan), generalizado por frecuencia:
            |p(f,1m)| = 20µPa · 10^(spl_db/20)
            |Q_FRD(f)| = |p(f,1m)| · 4π / (2π f ρ₀)
            Q_FRD(f)   = |Q_FRD(f)| · exp(i·phase_rad)

        g(f) (ganancia relativa al Q baseline `q_base` = effective_Q de la
        fuente) segun el modo de anclaje:
          - "absolute": g = Q_FRD / q_base  → effective_Q()·g = Q_FRD exacto
                        (el nivel medido manda; la sensibilidad queda no-op).
          - "relative": g = Q_FRD / |Q_FRD(f_ref)|  → |g(f_ref)| = 1
                        (la forma viene del FRD; el nivel, de la sensibilidad).

        En ambos modos la FASE de g es la del FRD (dividir por un real positivo
        no la altera). El factor (f_ref/f) implicito refleja que un SPL plano
        corresponde a Q∝1/f (ver DECISION opcion 1 en plan_fuentes).
        """
        f = np.asarray(freq_hz, dtype=float)
        spl = np.asarray(spl_db, dtype=float)
        ph = (np.zeros_like(f) if phase_rad is None
              else np.asarray(phase_rad, dtype=float))

        p_1m = 20e-6 * 10.0 ** (spl / 20.0)
        omega = 2.0 * np.pi * np.maximum(f, 1e-9)
        q_mag = p_1m * 4.0 * np.pi / (omega * rho0)        # |Q_FRD(f)|

        a = (anchor or "absolute").lower()
        if a == "relative":
            denom = float(np.interp(f_ref, f, q_mag))      # |Q_FRD(f_ref)|
            denom = denom if denom > 0 else 1.0
        elif a == "absolute":
            denom = float(abs(q_base)) if abs(q_base) > 0 else 1.0
        else:
            raise ValueError(f"anchor desconocido: {anchor!r} (absolute|relative)")

        gain_db = 20.0 * np.log10(np.maximum(q_mag / denom, 1e-12))
        return cls(f, gain_db, ph, name=name, anchor=a)

    # ----- persistencia (.room v5) ------------------------------------------
    def to_dict(self) -> dict:
        """Serializa la g(f) horneada (auto-contenida; reload exacto)."""
        return {
            "name": self.name,
            "anchor": self.anchor,
            "freq_pts":  [float(x) for x in self.freq_pts],
            "gain_db":   [float(x) for x in self.gain_db],
            "phase_rad": [float(x) for x in self.phase_rad],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceResponse":
        return cls(
            freq_pts=np.asarray(d["freq_pts"], dtype=float),
            gain_db=np.asarray(d["gain_db"], dtype=float),
            phase_rad=np.asarray(d["phase_rad"], dtype=float),
            name=str(d.get("name", "")),
            anchor=str(d.get("anchor", "")),
        )


def synth_response(kind: str,
                   freq_pts: np.ndarray | None = None,
                   *,
                   tau: float = 1.0e-3,
                   fc: float = 40.0,
                   peak_freq: float = 50.0,
                   peak_db: float = 6.0,
                   peak_bw: float = 10.0,
                   name: str | None = None) -> SourceResponse:
    """Genera una de las 5 curvas sinteticas 'oraculo' del plan (§2).

    Sirven como placeholders de UX y, mas importante, como ORACULOS de
    validacion permanentes porque su comportamiento analitico es conocido:

      'flat'     : g≡1.            -> FRF identica a la baseline (regresion).
      'delay'    : |g|=1, fase -2πfτ (retardo puro, conv. e^{+iωt}).
      'polarity' : g≡-1 (fase π).  -> inversion de polaridad.
      'highpass' : |g|=f/√(f²+fc²) + fase minima de 1 polo (rolloff de sub).
      'peak'     : bump gaussiano en dB centrado en peak_freq (no monotono).

    Parametros (segun kind):
      tau       [s]  retardo para 'delay'.
      fc        [Hz] frecuencia de corte para 'highpass'.
      peak_freq [Hz], peak_db [dB], peak_bw [Hz] para 'peak'.
    """
    if freq_pts is None:
        freq_pts = np.linspace(1.0, 1000.0, 2000)
    f = np.asarray(freq_pts, dtype=float)
    k = kind.lower()

    if k == "flat":
        gdb = np.zeros_like(f)
        ph  = np.zeros_like(f)
    elif k == "delay":
        gdb = np.zeros_like(f)
        ph  = -2.0 * np.pi * f * tau          # conv. e^{+iωt}: retardo = -ωτ
    elif k == "polarity":
        gdb = np.zeros_like(f)
        ph  = np.full_like(f, np.pi)
    elif k == "highpass":
        mag = f / np.sqrt(f**2 + fc**2)
        gdb = 20.0 * np.log10(np.maximum(mag, 1e-12))
        ph  = np.arctan2(fc, f)               # fase minima de un polo (lead)
    elif k == "peak":
        gdb = peak_db * np.exp(-((f - peak_freq) / peak_bw) ** 2)
        ph  = np.zeros_like(f)
    else:
        raise ValueError(
            f"kind desconocido: {kind!r}. Use flat/delay/polarity/highpass/peak.")

    return SourceResponse(f, gdb, ph, name=name or k)


@dataclass
class OmniSource:
    """Fuente puntual omnidireccional (monopolo acustico ideal).

    Modos de configuracion:
      (a) Directo:        Q   = caudal volumetrico en m³/s  (sensitivity_dB=None)
      (b) Por altavoz:    sensitivity_dB + power_W  →  Q calculado automaticamente

    En el modo (b) los solvers usan effective_Q() en lugar de Q directamente.

    Respuesta en frecuencia (opcional): si `response` no es None, la amplitud
    pasa a depender de f via effective_Q_spectrum() = effective_Q() * g(f).
    Sin response, el comportamiento es identico al historico (Q constante).
    """

    position:       Tuple[float, float, float]
    Q:              complex = 1.0 + 0.0j
    label:          str     = ""
    # Configuración por sensibilidad de altavoz
    sensitivity_dB: float | None = None   # dB SPL @ 1W/1m  (None = modo directo)
    power_W:        float        = 1.0    # potencia electrica de entrada [W]
    f_ref:          float        = 1000.0 # frecuencia de referencia de la sens. [Hz]
    response:       "SourceResponse | None" = None   # curva g(f), o None (Q cte)
    # T4: bafle (puramente visual + insumo del optimizador de ubicacion T8).
    # La fuente sigue siendo acusticamente OMNI; orientacion y dims no afectan
    # el campo (la directividad se descarto). orientation = azimut del frente
    # [grados, 0=+X, CCW]; None -> default 90 (hacia +Y). baffle_size = (ancho,
    # alto, profundidad) [m]; por convencion alto>ancho y profundidad>ancho.
    # pitch = inclinacion del frente [grados, 0=horizontal, + arriba]; mounted =
    # montada en pared (flush, one-shot informativa: insumo de T8 + senal visual).
    orientation:    "float | None" = None
    baffle_size:    Tuple[float, float, float] = (0.30, 0.50, 0.40)
    pitch:          float = 0.0
    mounted:        bool  = False
    # v2.16: mute por fuente. Una fuente inactiva sigue en la lista (posicion,
    # curva, bafle intactos) pero NO radia: los caminos de computo (FRF, SBIR,
    # FoM, campo 3D, comparaciones) la excluyen. Permite analizar parlante por
    # parlante sin borrar y recrear fuentes.
    active:         bool  = True
    # v2.23: polaridad del cableado. +1 = 0° (normal), -1 = 180° (invertida).
    # Es una propiedad del DRIVE, no del transductor: un FRD/TRF mide el
    # parlante, dar vuelta los cables es otra cosa que multiplica por -1. Por
    # eso vive aparte de `response` y se COMPONE con ella en vez de pisarla
    # (el atajo manual viejo horneaba la fase pi dentro de la curva, lo que
    # destruia el FRD cargado y no se podia leer de vuelta en la UI).
    # polarity=+1 reduce EXACTO al comportamiento historico.
    polarity:       int   = 1

    def __post_init__(self):
        x, y, z = self.position
        self.position = (float(x), float(y), float(z))
        self.Q = complex(self.Q)
        if self.sensitivity_dB is not None:
            # Auto-calcula Q al construir la fuente
            self.Q = q_from_sensitivity(self.sensitivity_dB,
                                        self.power_W, self.f_ref)
        self.baffle_size = tuple(float(x) for x in self.baffle_size)
        if self.orientation is not None:
            self.orientation = float(self.orientation)
        self.pitch = float(self.pitch)
        self.mounted = bool(self.mounted)
        self.active = bool(self.active)
        self.polarity = -1 if int(self.polarity) < 0 else 1

    def effective_Q(self) -> complex:
        """Q efectivo (escalar): recalculado desde sensibilidad si corresponde.

        NO aplica la curva de respuesta — es el Q baseline / de banda ancha.
        Para el Q dependiente de f usar effective_Q_spectrum().

        SI aplica la polaridad (factor +-1). Se hace aca a proposito: es el
        unico punto por el que pasan TODOS los caminos de computo
        (effective_Q_spectrum -> amplitudes_spectrum -> FRF / campo modal /
        SBIR / FoM / optimizador de ubicacion, y tambien amplitudes() del
        path legacy), asi que la polaridad entra en todos sin tocar ninguno.
        """
        if self.sensitivity_dB is not None:
            q = q_from_sensitivity(self.sensitivity_dB,
                                   self.power_W, self.f_ref)
        else:
            q = self.Q
        return q * self.polarity

    def effective_Q_spectrum(self, freq_axis) -> np.ndarray:
        """Q(f) complejo sobre freq_axis -> (Nf,) complex.

        Sin curva de respuesta: el Q baseline broadcasteado (comportamiento
        historico). Con curva: Q_base * g(f).
        """
        fa = np.atleast_1d(np.asarray(freq_axis, dtype=float))
        q0 = self.effective_Q()
        if self.response is None:
            return np.full(fa.shape, q0, dtype=complex)
        return q0 * self.response.gain_spectrum(fa)

    # ----- consultas ---------------------------------------------------------
    def is_inside(self, dims: Sequence[float], tol: float = 0.0) -> bool:
        """True si la fuente esta dentro del paralelepipedo Lx x Ly x Lz."""
        Lx, Ly, Lz = dims
        x, y, z = self.position
        return (-tol <= x <= Lx + tol and
                -tol <= y <= Ly + tol and
                -tol <= z <= Lz + tol)

    def as_array(self) -> np.ndarray:
        return np.asarray(self.position, dtype=float)

    # ----- campo libre -------------------------------------------------------
    def free_field_pressure(
        self,
        x_obs: np.ndarray,
        f: float,
        c: float = C0,
        rho0: float = RHO0,
    ) -> np.ndarray:
        """Presion compleja de campo libre (sin paredes) en x_obs.

        p(x) = i*omega*rho0 * Q * exp(i*k*r) / (4*pi*r),
            r = ||x - x_s||, k = omega/c.

        Parameters
        ----------
        x_obs : array_like, forma (N, 3) o (3,)
            Posiciones de los receptores.
        f : float
            Frecuencia en Hz.
        """
        x_obs = np.atleast_2d(np.asarray(x_obs, dtype=float))
        omega = 2.0 * np.pi * f
        k = omega / c
        x_s = self.as_array()
        r = np.linalg.norm(x_obs - x_s, axis=1)
        # Evitar division por cero en el origen exacto de la fuente.
        r = np.where(r < 1e-9, 1e-9, r)
        return (1j * omega * rho0 * self.Q) * np.exp(1j * k * r) / (4.0 * np.pi * r)


# ---------------------------------------------------------------------------
# Conjunto de fuentes
# ---------------------------------------------------------------------------
@dataclass
class SourceArray:
    """Coleccion ordenada de OmniSource, con superposicion lineal de campos."""

    sources: List[OmniSource] = field(default_factory=list)

    # ----- gestion ----------------------------------------------------------
    def add(self, src: OmniSource) -> None:
        self.sources.append(src)

    def add_at(self, position, Q: complex = 1.0 + 0.0j, label: str = "") -> None:
        self.sources.append(OmniSource(tuple(position), Q=Q, label=label))

    def active_only(self) -> "SourceArray":
        """Sub-array con las fuentes ACTIVAS (mute v2.16). Las fuentes son las
        mismas instancias (no copias): editar una se refleja en ambas vistas."""
        return SourceArray([s for s in self.sources
                            if getattr(s, "active", True)])

    def positions(self) -> np.ndarray:
        if not self.sources:
            return np.zeros((0, 3))
        return np.array([s.position for s in self.sources], dtype=float)

    def amplitudes(self) -> np.ndarray:
        """Devuelve el array de Q efectivos (usa sensibilidad si corresponde).

        Q de banda ancha por fuente (NO aplica curva de respuesta). Path de
        frecuencia unica / compatibilidad. Para Q(f) usar amplitudes_spectrum.
        """
        return np.array([s.effective_Q() for s in self.sources], dtype=complex)

    def amplitudes_spectrum(self, freq_axis) -> np.ndarray:
        """Q(f) de todas las fuentes -> (Nf, Ns) complex.

        Columna s = effective_Q_spectrum(freq_axis) de la fuente s. Si ninguna
        fuente tiene curva, cada fila es constante e igual a amplitudes() →
        continuidad exacta con el path historico (la FRF no cambia).
        """
        fa = np.atleast_1d(np.asarray(freq_axis, dtype=float))
        Ns = len(self.sources)
        out = np.empty((fa.shape[0], Ns), dtype=complex)
        for s_idx, s in enumerate(self.sources):
            out[:, s_idx] = s.effective_Q_spectrum(fa)
        return out

    def has_response(self) -> bool:
        """True si alguna fuente tiene curva de respuesta cargada."""
        return any(s.response is not None for s in self.sources)

    def __len__(self) -> int:
        return len(self.sources)

    def __iter__(self):
        return iter(self.sources)

    def __getitem__(self, idx) -> OmniSource:
        return self.sources[idx]

    # ----- validacion -------------------------------------------------------
    def validate(self, dims: Sequence[float]) -> None:
        """Lanza ValueError si alguna fuente esta fuera del recinto."""
        for i, s in enumerate(self.sources):
            if not s.is_inside(dims):
                raise ValueError(
                    f"Fuente {i} ({s.label!r}) en {s.position} fuera del recinto {dims}.")

    # ----- campo libre superpuesto ------------------------------------------
    def free_field_pressure(
        self,
        x_obs: np.ndarray,
        f: float,
        c: float = C0,
        rho0: float = RHO0,
    ) -> np.ndarray:
        x_obs = np.atleast_2d(np.asarray(x_obs, dtype=float))
        p = np.zeros(len(x_obs), dtype=complex)
        for s in self.sources:
            p += s.free_field_pressure(x_obs, f=f, c=c, rho0=rho0)
        return p


# ---------------------------------------------------------------------------
# Constructores rapidos
# ---------------------------------------------------------------------------
def single_source(position, Q: complex = 1.0 + 0.0j, label: str = "src") -> SourceArray:
    """Helper: construye una SourceArray con una unica fuente."""
    return SourceArray([OmniSource(tuple(position), Q=Q, label=label)])


def stereo_sources(
    left,
    right,
    Q_left: complex = 1.0 + 0.0j,
    Q_right: complex = 1.0 + 0.0j,
) -> SourceArray:
    """Helper: dos fuentes etiquetadas 'L' y 'R'."""
    return SourceArray([
        OmniSource(tuple(left), Q=Q_left, label="L"),
        OmniSource(tuple(right), Q=Q_right, label="R"),
    ])


def line_array(
    start, end, n: int,
    Q: complex = 1.0 + 0.0j,
    label_prefix: str = "src",
) -> SourceArray:
    """Helper: n fuentes equiespaciadas entre los puntos start y end."""
    s = np.asarray(start, dtype=float)
    e = np.asarray(end, dtype=float)
    arr = SourceArray()
    for i in range(n):
        t = i / max(1, n - 1)
        p = s + t * (e - s)
        arr.add(OmniSource(tuple(p), Q=Q, label=f"{label_prefix}{i}"))
    return arr


# ---------------------------------------------------------------------------
# Demo / autotest
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Demo: dos fuentes en una habitacion 5x4x3.
    arr = stereo_sources(left=(1.0, 1.0, 1.5), right=(4.0, 1.0, 1.5))
    arr.validate(dims=(5.0, 4.0, 3.0))

    obs = np.array([[2.5, 2.0, 1.5]])      # centro del recinto
    p = arr.free_field_pressure(obs, f=80.0)
    print(f"Demo sources.py:")
    print(f"  fuentes: {len(arr)}")
    for i, s in enumerate(arr):
        print(f"    [{i}] {s.label!r} @ {s.position}, Q={s.Q}")
    print(f"  campo libre @ {tuple(obs[0])}: "
          f"|p|={np.abs(p[0]):.4g} Pa, fase={np.angle(p[0]):+.3f} rad")

    # --- Fase 0: chequeo de SourceResponse / synth_response (sin FEM) -------
    print("\n  SourceResponse / synth_response:")
    fa = np.linspace(20.0, 100.0, 9)
    # flat -> g == 1 exacto
    g_flat = synth_response("flat").gain_spectrum(fa)
    assert np.allclose(g_flat, 1.0 + 0j, rtol=1e-12), "flat no da g=1"
    # polarity -> g == -1
    g_pol = synth_response("polarity").gain_spectrum(fa)
    assert np.allclose(g_pol, -1.0 + 0j, rtol=1e-12), "polarity no da g=-1"
    # delay -> |g|=1 y fase = -2πfτ exacta (curva lineal interp lineal = exacta)
    tau = 1.5e-3
    g_del = synth_response("delay", tau=tau).gain_spectrum(fa)
    assert np.allclose(np.abs(g_del), 1.0, rtol=1e-12), "delay altera |g|"
    assert np.allclose(np.angle(g_del), np.angle(np.exp(-2j*np.pi*fa*tau)),
                       atol=1e-9), "delay: fase incorrecta"
    # effective_Q_spectrum sin curva == effective_Q broadcasteado
    s = OmniSource((1, 1, 1), sensitivity_dB=90.0)
    assert np.allclose(s.effective_Q_spectrum(fa), s.effective_Q()), \
        "spectrum sin curva != Q constante"
    # con curva flat: idem (g=1)
    s.response = synth_response("flat")
    assert np.allclose(s.effective_Q_spectrum(fa), s.effective_Q()), \
        "spectrum con flat != Q constante"
    print("    OK (flat=1, polarity=-1, delay fase lineal, Q-spectrum continuo)")
