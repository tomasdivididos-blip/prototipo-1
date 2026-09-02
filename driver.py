"""
driver.py
=========

Modelo FISICO del altoparlante como fuente (Fase S2 del modelo de fuente exacto,
ver `plan_modelo_fuente.md`). Deriva el caudal volumetrico Q(f) del driver desde
parametros Thiele-Small en lugar de una curva plana o medida.

Convencion fisica (identica a `sources.py` y `filters.py`):
   - Fasor temporal e^{+i*omega*t}  ->  s = i*omega.
   - Presion de monopolo  p = i*omega*rho0*U/(4*pi*r)  ->  |p| ∝ omega*|U|.

Caja sellada (2º orden). La velocidad volumetrica del cono es

    U(s) ∝ s / (s^2 + (omega_c/Q_tc)*s + omega_c^2)

de modo que la presion radiada  p = i*omega*rho0*U ∝ s*U ∝ s^2/(denom)  es el
pasa-altos de 2º orden clasico de caja sellada (plano en banda, -12 dB/oct bajo
f_c). Ver Small (1972); Beranek & Mellow, *Sound Fields and Transducers*, Ch6-7;
Rivet, Karkar & Lissek (2018) para el modelo electro-mecano-acustico completo.

Este modulo produce una `sources.SourceResponse` (la ganancia compleja g(f) que
el resto del programa ya sabe componer en `OmniSource.effective_Q_spectrum`), asi
que NO toca el solver. Sin driver, el comportamiento es identico al historico.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Tuple

from sources import SourceResponse, RHO0, C0


# ---------------------------------------------------------------------------
# Parametros de caja sellada desde Thiele-Small crudos
# ---------------------------------------------------------------------------
def sealed_box_params(fs: float, Qts: float, Vas: float, Vb: float
                      ) -> Tuple[float, float]:
    """Convierte TS de aire libre (fs, Qts, Vas) + volumen de caja Vb a los
    parametros en caja sellada (fc, Qtc).

        alpha = Vas / Vb              (razon de compliancias)
        fc    = fs * sqrt(1 + alpha)
        Qtc   = Qts * sqrt(1 + alpha)

    Vas y Vb en las mismas unidades (m^3 o litros, se cancelan). Referencia:
    Small, "Closed-Box Loudspeaker Systems", JAES 20 (1972); Beranek & Mellow Ch7.
    """
    if Vb <= 0:
        raise ValueError("Vb (volumen de caja) debe ser > 0")
    alpha = Vas / Vb
    scale = np.sqrt(1.0 + alpha)
    return float(fs * scale), float(Qts * scale)


# ---------------------------------------------------------------------------
# Transferencia de velocidad volumetrica de caja sellada
# ---------------------------------------------------------------------------
def volume_velocity_transfer(freq, fc: float, Qtc: float) -> np.ndarray:
    """U(f) complejo (escala arbitraria) de un driver de caja sellada.

        U(s) = s / (s^2 + (wc/Qtc)*s + wc^2),   s = i*omega,  wc = 2*pi*fc

    La escala es arbitraria (se normaliza despues via el anclaje de g(f)). La
    presion radiada p = i*omega*rho0*U reproduce el pasa-altos de 2º orden.
    """
    f = np.atleast_1d(np.asarray(freq, dtype=float))
    wc = 2.0 * np.pi * float(fc)
    s = 1j * 2.0 * np.pi * f
    denom = s * s + (wc / float(Qtc)) * s + wc * wc
    return s / denom


def pressure_transfer(freq, fc: float, Qtc: float) -> np.ndarray:
    """p(f) complejo (escala arbitraria) = i*omega*rho0*U(f).

    Es el pasa-altos de 2º orden de caja sellada:
        H_p(s) = s^2 / (s^2 + (wc/Qtc)*s + wc^2)
    (salvo la constante rho0). En f=fc, |H_p| = Qtc respecto de la banda.
    """
    f = np.atleast_1d(np.asarray(freq, dtype=float))
    s = 1j * 2.0 * np.pi * f
    return s * volume_velocity_transfer(f, fc, Qtc)


# ---------------------------------------------------------------------------
# Impedancia de radiacion del piston circular bafleado (Kinsler Ch7)
# ---------------------------------------------------------------------------
def piston_radiation_impedance(ka) -> np.ndarray:
    """Impedancia de radiacion NORMALIZADA de un piston circular en bafle
    infinito:  Z_rad / (rho0*c*S) = R1(2ka) + i*X1(2ka).

        R1(x) = 1 - 2*J1(x)/x          (resistencia de radiacion)
        X1(x) = 2*H1(x)/x              (reactancia, H1 = Struve de orden 1)

    con x = 2ka. Referencia: Kinsler, Frey, Coppens & Sanders, *Fundamentals of
    Acoustics* 4ª ed, Ch7; Beranek & Mellow Ch4.

    Limites: ka->0  ->  R1 ~ (ka)^2/2,  X1 ~ 8*ka/(3*pi)  (carga de masa).
             ka->inf ->  R1 -> 1,        X1 -> 0.
    """
    from scipy.special import j1, struve
    x = 2.0 * np.atleast_1d(np.asarray(ka, dtype=float))
    # Evitar 0/0 en x=0 (limites analiticos).
    xs = np.where(x < 1e-9, 1e-9, x)
    R1 = 1.0 - 2.0 * j1(xs) / xs
    X1 = 2.0 * struve(1, xs) / xs
    return R1 + 1j * X1


# ---------------------------------------------------------------------------
# Modelo de driver
# ---------------------------------------------------------------------------
@dataclass
class DriverModel:
    """Driver electrodinamico en caja sellada, como fuente fisica.

    Dos formas de especificar la caja:
      (a) directa:   fc + Qtc  (dejar Vb=None).
      (b) desde TS:  fs, Qts, Vas + Vb  ->  fc, Qtc calculados.

    `Sd` (area efectiva del cono, m^2) y `a` (radio efectivo, m) son opcionales;
    si se da Sd se deriva a = sqrt(Sd/pi) para la impedancia de radiacion. No
    afectan g(f) (que es adimensional); solo alimentan diagnosticos/S3.
    """

    fc:   float | None = None
    Qtc:  float | None = None
    # Alternativa: TS crudos + volumen de caja.
    fs:   float | None = None
    Qts:  float | None = None
    Vas:  float | None = None
    Vb:   float | None = None
    # Geometria (opcional, para impedancia de radiacion / S3).
    Sd:   float | None = None
    a:    float | None = None
    name: str = "driver"

    def __post_init__(self):
        # Resolver fc, Qtc desde TS si hace falta.
        if self.fc is None or self.Qtc is None:
            if None in (self.fs, self.Qts, self.Vas, self.Vb):
                raise ValueError(
                    "DriverModel: dar (fc, Qtc) directo, o (fs, Qts, Vas, Vb).")
            self.fc, self.Qtc = sealed_box_params(
                self.fs, self.Qts, self.Vas, self.Vb)
        self.fc = float(self.fc)
        self.Qtc = float(self.Qtc)
        if self.a is None and self.Sd is not None:
            self.a = float(np.sqrt(self.Sd / np.pi))

    def volume_velocity(self, freq) -> np.ndarray:
        """U(f) complejo (escala arbitraria) del driver."""
        return volume_velocity_transfer(freq, self.fc, self.Qtc)

    def to_response(self, freq_pts=None, *, f_ref: float = 200.0,
                    anchor: str = "relative", name: str | None = None
                    ) -> SourceResponse:
        """Construye la ganancia g(f) del driver como `sources.SourceResponse`.

        anchor:
          - "relative": |g(f_ref)| = 1  -> el nivel lo pone la sensibilidad de
            la fuente; la FORMA (rolloff + fase) la pone el driver. f_ref debe
            estar en la banda pasante (f_ref >> fc). Es el modo recomendado.
          - "raw": g = U(f)/U(f_ref) sin re-anclar la fase (equivalente aqui;
            se mantiene por claridad de API).

        La curva se muestrea en freq_pts (por defecto 5-500 Hz, 2000 pts, densa
        para que la interpolacion lineal de la fase desenvuelta sea exacta).
        """
        if freq_pts is None:
            freq_pts = np.linspace(5.0, 500.0, 2000)
        f = np.asarray(freq_pts, dtype=float)
        U = self.volume_velocity(f)

        U_ref = complex(volume_velocity_transfer(f_ref, self.fc, self.Qtc)[0])
        if abs(U_ref) < 1e-30:
            U_ref = 1.0 + 0j
        g = U / U_ref

        gain_db = 20.0 * np.log10(np.maximum(np.abs(g), 1e-12))
        phase = np.unwrap(np.angle(g))
        return SourceResponse(f, gain_db, phase,
                              name=name or self.name, anchor="")


# ---------------------------------------------------------------------------
# Demo / autotest minimo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    drv = DriverModel(fc=40.0, Qtc=0.707, Sd=0.055, name="sub 12\"")
    print(f"driver: fc={drv.fc:.1f} Hz  Qtc={drv.Qtc:.3f}  a={drv.a:.3f} m")

    # |p(fc)|/|p(banda)| = Qtc
    p_fc = abs(pressure_transfer(drv.fc, drv.fc, drv.Qtc)[0])
    p_hi = abs(pressure_transfer(5000.0, drv.fc, drv.Qtc)[0])
    print(f"  |p(fc)|/|p(inf)| = {p_fc/p_hi:.3f}  (esperado Qtc={drv.Qtc:.3f})")

    # g(f) relativa
    r = drv.to_response(f_ref=200.0)
    fa = np.array([20.0, 40.0, 80.0, 200.0])
    g = r.gain_spectrum(fa)
    for fi, gi in zip(fa, g):
        print(f"    f={fi:6.1f} Hz  |g|={abs(gi):.3f}  fase={np.degrees(np.angle(gi)):+6.1f}°")
