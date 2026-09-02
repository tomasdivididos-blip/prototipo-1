"""
dba.py
======

Fase S5 del modelo de fuente exacto (ver `plan_modelo_fuente.md`): subs
enfrentados (DBA/CABS) sobre la base modal distribuida de `source_coupling.py`.

Configuracion CABS (Nielsen & Celestinos): un array de pared entera en el frente
(y=0) lanza una onda plana; un array en la pared opuesta (y=Ly) reproduce la
misma senal RETARDADA por Ly/c e INVERTIDA, absorbiendo la reflexion. En estado
estacionario a frecuencia f el drive trasero es

    v_r(f) = -v0 * exp(-i*omega*Ly/c)          (retardo Ly/c + inversion)

MECANISMO (prueba analitica). El acoplamiento de un modo axial (0,m,0) es
C_m ∝ v0 + v_r*(-1)^m  (el frente da face=+1, el trasero face=(-1)^m). Con el
drive de arriba, C_m ∝ 1 - exp(-i*omega*Ly/c)*(-1)^m. En la resonancia del modo,
k = k_m = m*pi/Ly  ->  omega*Ly/c = k*Ly = m*pi  ->  exp(-i m pi) = (-1)^m, y

    C_m(k_m) ∝ 1 - (-1)^m (-1)^m = 0.

El cero del numerador cancela el polo: el modo NO resuena. El campo pasa de
estacionario (resonante) a viajero (no resonante). Esa es la razon por la que
subs enfrentados funciona, y el modelo modal de hoy (fuente puntual) no la ve.

Modelo (a) SINK MANEJADO, implementado aca. El modelo (b) sink por impedancia
matcheada (Z=rho0*c) NO es perturbativo (beta ~ 1, pared totalmente absorbente),
asi que la Capa 0 de perturbacion no lo captura; CABS es un sistema manejado, no
un absorbente pasivo, asi que (a) es la representacion fisica correcta.
"""

from __future__ import annotations

import numpy as np
from typing import Callable

from source_coupling import RectModalBasis, WallPiston


def travel_delay(basis: RectModalBasis, axis: int = 1) -> float:
    """Tiempo de transito de la onda plana a lo largo del eje: L_axis / c."""
    return basis.dims[axis] / basis.c


def front_only_coupling(basis: RectModalBasis, axis: int = 1,
                        front_vn: complex = 1.0) -> np.ndarray:
    """CABS OFF: solo el array frontal de pared entera (C_n fijo)."""
    return basis.wall_piston_coupling(
        WallPiston(axis=axis, side="min", vn=front_vn))


def dba_coupling_fn(basis: RectModalBasis, axis: int = 1,
                    front_vn: complex = 1.0, delay: float | None = None,
                    invert: bool = True) -> Callable[[float], np.ndarray]:
    """CABS ON: devuelve C(f) con el frente + trasero manejado.

    delay=None -> Ly/c (retardo de transito). invert=True -> inversion de
    polaridad del trasero (el default de CABS).
    """
    if delay is None:
        delay = travel_delay(basis, axis)
    sign = -1.0 if invert else 1.0
    front = WallPiston(axis=axis, side="min", vn=front_vn)
    C_front = basis.wall_piston_coupling(front)

    def C_of_f(f: float) -> np.ndarray:
        omega = 2.0 * np.pi * f
        vr = sign * front_vn * np.exp(-1j * omega * delay)
        rear = WallPiston(axis=axis, side="max", vn=vr)
        return C_front + basis.wall_piston_coupling(rear)

    return C_of_f


def axial_resonance_coupling(basis: RectModalBasis, axis: int, mode_index: int,
                             front_vn: complex = 1.0) -> complex:
    """|C_m| del modo axial `mode_index` evaluado en SU resonancia, con el drive
    DBA. Debe ser ~0 (cancelacion polo-cero). Para el oraculo T1."""
    C_fn = dba_coupling_fn(basis, axis=axis, front_vn=front_vn)
    f_m = basis.freqs[mode_index]
    return complex(C_fn(f_m)[mode_index])


def impulse_response(basis: RectModalBasis, receiver, coupling, *,
                     fmax: float = 200.0, n_freq: int = 4096,
                     xi: float = 0.03):
    """Respuesta impulsiva por IFFT de la FRF sobre [0, fmax].

    `coupling` puede ser un vector C_n fijo (CABS off) o un callable C(f) (DBA).
    Devuelve (t, h) con h real. Sirve para medir el colapso del decay.
    """
    freqs = np.linspace(0.0, fmax, n_freq)
    if callable(coupling):
        H = basis.frf_dispersive(receiver, freqs, coupling, xi=xi)
    else:
        H = basis.frf(receiver, freqs, coupling, xi=xi)
    H[0] = 0.0                                   # sin DC
    h = np.fft.irfft(H, n=2 * (n_freq - 1))
    fs = 2.0 * fmax
    t = np.arange(h.size) / fs
    return t, h


def schroeder_decay_db(h: np.ndarray) -> np.ndarray:
    """Curva de decaimiento de Schroeder (integral invertida de energia) en dB,
    normalizada a 0 dB en t=0."""
    energy = h[::-1] ** 2
    sch = np.cumsum(energy)[::-1]
    sch = sch / np.max(sch)
    return 10.0 * np.log10(np.maximum(sch, 1e-20))


if __name__ == "__main__":
    dims = (7.8, 4.1, 2.8)
    basis = RectModalBasis(dims, fmax=180.0)
    print(f"sala {dims}: {basis.n_modes} modos hasta 180 Hz")

    # Cancelacion polo-cero en cada axial-y.
    print("  |C_m| en resonancia (DBA on) para axiales-y:")
    for i, m in enumerate(basis.modes):
        if m[0] == 0 and m[2] == 0 and m[1] >= 1:
            Cm = abs(axial_resonance_coupling(basis, 1, i))
            print(f"    modo {m}  f={basis.freqs[i]:6.2f} Hz  |C_m(res)|={Cm:.2e}")
