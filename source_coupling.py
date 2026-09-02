"""
source_coupling.py
==================

Fase S1 del modelo de fuente exacto (ver `plan_modelo_fuente.md`): acoplamiento
de fuentes DISTRIBUIDAS a los modos de un recinto rectangular, por integral de
superficie. Es el nucleo que hace falta para simular subs enfrentados (DBA/CABS).

Kuttruff, *Room Acoustics* §3.6, Ec. 3.6-3.7:

    nabla^2 p + k^2 p = -i*omega*rho0*q(r)
    p(r) = i*omega*rho0 * sum_n  phi_n(r) * C_n / (k_n^2 - k^2)
    C_n  = integral_V phi_n(r) q(r) dV        (phi_n ORTONORMAL: int phi_n^2 dV = 1)

con q(r) la densidad de velocidad volumetrica de la fuente. Para una fuente
puntual q = Q*delta(r - r0)  ->  C_n = Q*phi_n(r0)  (reduce al modelo de hoy,
Ec. 3.10 / `fem_modal.frequency_response`). Para un piston montado en pared, q es
una velocidad de superficie y

    C_n = integral_S phi_n(r) v_n(r) dS.

Base rectangular ANALITICA (decision S1, Opcion A): los modos exactos del
paralelepipedo rigido son  p_n = cos(nx*pi*x/Lx) cos(ny*pi*y/Ly) cos(nz*pi*z/Lz),
y la integral de superficie de un piston rectangular es ANALITICA (cosenos), sin
error geometrico. Cubre el 100% del uso real (CABS/DBA son cuartos rectangulares).

Convencion: e^{+i*omega*t}, s = i*omega (igual que sources.py / filters.py /
driver.py). La FRF aca reproduce el prefactor de `fem_modal.frequency_response`
(i*omega*rho0*c^2 / (omega_n^2 - omega^2 + 2 i xi omega_n omega)).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from sources import RHO0, C0


# ---------------------------------------------------------------------------
# Integral de un coseno de modo sobre un segmento (nucleo de la integral 2D)
# ---------------------------------------------------------------------------
def _seg_cos_integral(m: int, L: float, u0: float, u1: float) -> float:
    """integral_{u0}^{u1} cos(m*pi*u/L) du.

        m = 0:  u1 - u0
        m >=1:  (L/(m*pi)) * [sin(m*pi*u1/L) - sin(m*pi*u0/L)]

    Clave del DBA: si el segmento cubre la arista completa [0, L], da 0 para
    m>=1 y L para m=0. O sea una velocidad uniforme sobre la pared entera anula
    los ordenes in-plane no nulos -> solo sobreviven los axiales.
    """
    if m == 0:
        return float(u1 - u0)
    a = m * np.pi / L
    return float((np.sin(a * u1) - np.sin(a * u0)) / a)


# ---------------------------------------------------------------------------
# Fuente de pared: piston rectangular con velocidad normal uniforme
# ---------------------------------------------------------------------------
@dataclass
class WallPiston:
    """Piston rectangular montado en una pared del recinto, velocidad normal
    uniforme (compleja, para fase/delay del DBA).

    axis  : 0|1|2  -> pared perpendicular al eje x|y|z.
    side  : "min" (coordenada 0) o "max" (coordenada L_axis).
    span  : (a0, a1, b0, b1) huella sobre los DOS ejes restantes, en orden
            creciente de indice de eje (p.ej. axis=1 -> ejes (x, z), span=
            (x0,x1,z0,z1)). None -> pared entera.
    vn    : velocidad normal compleja [m/s] (hacia adentro del recinto). El
            caudal volumetrico del piston es Q = vn * area.
    label : etiqueta.
    """
    axis:  int
    side:  str = "min"
    span:  Tuple[float, float, float, float] | None = None
    vn:    complex = 1.0 + 0.0j
    label: str = ""

    def other_axes(self) -> Tuple[int, int]:
        return tuple(a for a in (0, 1, 2) if a != self.axis)  # type: ignore

    def resolved_span(self, dims) -> Tuple[float, float, float, float]:
        if self.span is not None:
            return tuple(float(x) for x in self.span)  # type: ignore
        a, b = self.other_axes()
        return (0.0, float(dims[a]), 0.0, float(dims[b]))

    def area(self, dims) -> float:
        a0, a1, b0, b1 = self.resolved_span(dims)
        return abs((a1 - a0) * (b1 - b0))


# ---------------------------------------------------------------------------
# Base modal rectangular analitica (ortonormal)
# ---------------------------------------------------------------------------
class RectModalBasis:
    """Modos exactos ORTONORMALES de un recinto rectangular rigido.

        phi_n(r) = p_n(r) / sqrt(K_n),   p_n = prod_d cos(n_d*pi*x_d/L_d),
        K_n = integral_V p_n^2 dV = V * prod_d (1 si n_d=0 else 1/2).

    Asi int phi_n^2 dV = 1 (misma normalizacion que los modos M-ortonormales del
    FEM, phi^T M phi = 1), y el acoplamiento puntual C_n = Q*phi_n(r0) reproduce
    `fem_modal.frequency_response`.
    """

    def __init__(self, dims: Sequence[float], *, fmax: float | None = None,
                 n_max: int = 12, c: float = C0, include_zero: bool = False):
        self.dims = tuple(float(x) for x in dims)
        self.c = float(c)
        self.V = float(np.prod(self.dims))
        Lx, Ly, Lz = self.dims

        modes: List[Tuple[int, int, int]] = []
        freqs: List[float] = []
        for nx in range(n_max):
            for ny in range(n_max):
                for nz in range(n_max):
                    if nx == 0 and ny == 0 and nz == 0 and not include_zero:
                        continue
                    f = (c / 2.0) * np.sqrt((nx / Lx) ** 2 + (ny / Ly) ** 2
                                            + (nz / Lz) ** 2)
                    if fmax is not None and f > fmax:
                        continue
                    modes.append((nx, ny, nz))
                    freqs.append(f)
        order = np.argsort(freqs)
        self.modes = [modes[i] for i in order]
        self.freqs = np.array([freqs[i] for i in order], dtype=float)
        self.omega_n = 2.0 * np.pi * self.freqs
        self._sqrtK = np.array([self._mode_sqrtK(m) for m in self.modes])

    def _mode_sqrtK(self, mode: Tuple[int, int, int]) -> float:
        Lam = 1.0
        for n_d in mode:
            Lam *= 1.0 if n_d == 0 else 0.5
        return float(np.sqrt(self.V * Lam))

    @property
    def n_modes(self) -> int:
        return len(self.modes)

    # ----- evaluacion del campo modal --------------------------------------
    def phi(self, x) -> np.ndarray:
        """phi_n(x) ortonormal en un punto -> (Nm,)."""
        x = np.asarray(x, dtype=float)
        Lx, Ly, Lz = self.dims
        out = np.empty(self.n_modes, dtype=float)
        for i, (nx, ny, nz) in enumerate(self.modes):
            p = (np.cos(nx * np.pi * x[0] / Lx) *
                 np.cos(ny * np.pi * x[1] / Ly) *
                 np.cos(nz * np.pi * x[2] / Lz))
            out[i] = p / self._sqrtK[i]
        return out

    # ----- acoplamiento puntual (reduce a hoy) -----------------------------
    def point_coupling(self, Q: complex, x_s) -> np.ndarray:
        """C_n = Q * phi_n(x_s)  -> (Nm,) complex."""
        return complex(Q) * self.phi(x_s)

    # ----- acoplamiento de piston de pared (integral de superficie) --------
    def wall_piston_coupling(self, piston: WallPiston) -> np.ndarray:
        """C_n = integral_S phi_n v_n dS para un WallPiston -> (Nm,) complex.

        En la pared axis=d, side, el factor del eje d de p_n es constante:
            side="min" (x_d=0)   -> cos(0) = 1
            side="max" (x_d=L_d) -> cos(n_d*pi) = (-1)^{n_d}
        y la integral sobre la huella factoriza en los dos ejes restantes.
        """
        d = piston.axis
        a, b = piston.other_axes()
        La, Lb = self.dims[a], self.dims[b]
        a0, a1, b0, b1 = piston.resolved_span(self.dims)
        vn = complex(piston.vn)

        out = np.empty(self.n_modes, dtype=complex)
        for i, mode in enumerate(self.modes):
            n_d = mode[d]
            face = 1.0 if piston.side == "min" else float((-1) ** n_d)
            Ia = _seg_cos_integral(mode[a], La, a0, a1)
            Ib = _seg_cos_integral(mode[b], Lb, b0, b1)
            out[i] = vn * face * Ia * Ib / self._sqrtK[i]
        return out

    # ----- FRF por superposicion modal -------------------------------------
    def frf(self, receiver, freq_axis, C: np.ndarray, *, xi: float = 0.03,
            rho0: float = RHO0) -> np.ndarray:
        """FRF en `receiver` dado el vector de acoplamiento C_n (suma de todas
        las fuentes) -> (Nf,) complex.

            H(f) = i*omega*rho0*c^2 * sum_n phi_n(x_r) C_n
                                     / (omega_n^2 - omega^2 + 2 i xi omega_n omega)

        Identico prefactor a `fem_modal.frequency_response`.
        """
        fa = np.atleast_1d(np.asarray(freq_axis, dtype=float))
        phi_r = self.phi(receiver)
        num = phi_r * np.asarray(C, dtype=complex)      # (Nm,)
        c_sq = self.c ** 2
        H = np.empty(fa.shape[0], dtype=complex)
        for i, f in enumerate(fa):
            omega = 2.0 * np.pi * f
            denom = (self.omega_n ** 2 - omega ** 2) + 2j * xi * self.omega_n * omega
            denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
            H[i] = 1j * omega * rho0 * c_sq * np.sum(num / denom)
        return H

    def frf_dispersive(self, receiver, freq_axis, coupling_of_f, *,
                       xi: float = 0.03, rho0: float = RHO0) -> np.ndarray:
        """FRF cuando el acoplamiento depende de la frecuencia (p.ej. el drive
        del DBA: el trasero = delantero retardado, v_r(f)=... e^{-i w tau}).

        `coupling_of_f(f) -> (Nm,) complex`. Sigue siendo LTI (el retardo es un
        filtro e^{-i w tau}), asi que la IFFT de H es la respuesta impulsiva
        fisica del sistema DBA.
        """
        fa = np.atleast_1d(np.asarray(freq_axis, dtype=float))
        phi_r = self.phi(receiver)
        c_sq = self.c ** 2
        H = np.empty(fa.shape[0], dtype=complex)
        for i, f in enumerate(fa):
            omega = 2.0 * np.pi * f
            C = np.asarray(coupling_of_f(f), dtype=complex)
            denom = (self.omega_n ** 2 - omega ** 2) + 2j * xi * self.omega_n * omega
            denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
            H[i] = 1j * omega * rho0 * c_sq * np.sum(phi_r * C / denom)
        return H

    def pressure_field(self, points, f: float, C: np.ndarray, *,
                       xi: float = 0.03, rho0: float = RHO0) -> np.ndarray:
        """|p| complejo en un conjunto de puntos a la frecuencia f -> (Np,)."""
        pts = np.atleast_2d(np.asarray(points, dtype=float))
        omega = 2.0 * np.pi * f
        denom = (self.omega_n ** 2 - omega ** 2) + 2j * xi * self.omega_n * omega
        denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
        coeff = (np.asarray(C, dtype=complex) / denom)          # (Nm,)
        out = np.empty(len(pts), dtype=complex)
        for j, x in enumerate(pts):
            out[j] = 1j * omega * rho0 * self.c ** 2 * np.sum(self.phi(x) * coeff)
        return out


# ---------------------------------------------------------------------------
# Helper: sumar acoplamientos de varias fuentes (puntuales y/o pistones)
# ---------------------------------------------------------------------------
def total_coupling(basis: RectModalBasis, *,
                   pistons: Sequence[WallPiston] = (),
                   point_sources: Sequence[Tuple[complex, Sequence[float]]] = ()
                   ) -> np.ndarray:
    """Suma C_n de todas las fuentes (linealidad de Helmholtz) -> (Nm,)."""
    C = np.zeros(basis.n_modes, dtype=complex)
    for p in pistons:
        C += basis.wall_piston_coupling(p)
    for Q, xs in point_sources:
        C += basis.point_coupling(Q, xs)
    return C


if __name__ == "__main__":
    dims = (7.8, 4.1, 2.8)      # sala de Santillan/CABS
    basis = RectModalBasis(dims, fmax=120.0)
    print(f"base rectangular: {basis.n_modes} modos hasta 120 Hz")

    # Piston de pared ENTERA en y=0 -> solo axiales-y (0,ny,0).
    piston = WallPiston(axis=1, side="min", vn=1.0)
    C = basis.wall_piston_coupling(piston)
    nz_axial = [(m, abs(C[i])) for i, m in enumerate(basis.modes)
                if abs(C[i]) > 1e-9]
    print("  pared entera y=0 excita:")
    for m, c in nz_axial[:8]:
        print(f"    modo {m}  |C|={c:.4f}")
