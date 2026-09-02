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
from sources import RHO0


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


# ---------------------------------------------------------------------------
# Drive LS-optimo (Santillan): arrays de pistones + minimos cuadrados
# ---------------------------------------------------------------------------
def piston_wall_grid(basis: RectModalBasis, axis: int, side: str,
                     n_a: int, n_b: int, *, size: float = 0.1,
                     inset: float = 0.05) -> list:
    """Grilla de pistones cuadrados sobre una pared (layout de Santillan).

    n_a x n_b pistones sobre los dos ejes distintos de `axis`, con centros
    equiespaciados desde `inset` hasta L-`inset`. size = lado del piston [m].
    """
    a, b = tuple(x for x in (0, 1, 2) if x != axis)
    La, Lb = basis.dims[a], basis.dims[b]
    ca = np.linspace(inset, La - inset, n_a) if n_a > 1 else np.array([La / 2])
    cb = np.linspace(inset, Lb - inset, n_b) if n_b > 1 else np.array([Lb / 2])
    h = size / 2.0
    pistons = []
    for ua in ca:
        for ub in cb:
            span = (ua - h, ua + h, ub - h, ub + h)
            pistons.append(WallPiston(axis=axis, side=side, span=span, vn=1.0))
    return pistons


def coupling_matrix(basis: RectModalBasis, pistons: list) -> np.ndarray:
    """Matriz de acoplamiento (Nm, L): columna l = C_n del piston l con vn=1."""
    return np.column_stack([basis.wall_piston_coupling(p) for p in pistons])


def plane_wave_target(sensors, k: float, axis: int = 1) -> np.ndarray:
    """Onda plana viajera en +axis, amplitud unidad: d_m = exp(-i k y_m)."""
    pts = np.atleast_2d(np.asarray(sensors, dtype=float))
    return np.exp(-1j * k * pts[:, axis])


def ls_drive(basis: RectModalBasis, Cmat: np.ndarray, Phi_s: np.ndarray,
             sensors, f: float, *, axis: int = 1, xi: float = 0.03,
             reg: float = 0.0, rho0: float = RHO0):
    """Drive LS-optimo a la frecuencia f (metodo de Santillan, dominio de f).

    Minimiza ||Z q - d||^2 con Z_{m,l} = presion en sensor m por fuente l (vn=1),
    d = onda plana viajera objetivo. Devuelve (q, C_opt, E_LS) con:
      q      : (L,) fuerzas complejas optimas
      C_opt  : (Nm,) acoplamiento resultante = Cmat @ q
      E_LS   : ||Z q - d|| / ||d||   (error de minimos cuadrados normalizado)
    """
    omega = 2.0 * np.pi * f
    k = omega / basis.c
    denom = (basis.omega_n ** 2 - omega ** 2) + 2j * xi * basis.omega_n * omega
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    # Z = i w rho0 c^2 * Phi_s @ (Cmat / denom)
    Z = 1j * omega * rho0 * basis.c ** 2 * (Phi_s @ (Cmat / denom[:, None]))
    d = plane_wave_target(sensors, k, axis)
    if reg > 0.0:
        # Tikhonov: q = (Z^H Z + reg I)^-1 Z^H d
        ZhZ = Z.conj().T @ Z
        q = np.linalg.solve(ZhZ + reg * np.eye(Z.shape[1]), Z.conj().T @ d)
    else:
        q, *_ = np.linalg.lstsq(Z, d, rcond=None)
    resid = Z @ q - d
    E = float(np.linalg.norm(resid) / np.linalg.norm(d))
    C_opt = Cmat @ q
    return q, C_opt, E


def dba_ls_coupling_fn(basis: RectModalBasis, pistons: list, sensors, *,
                       axis: int = 1, xi: float = 0.03, reg: float = 0.0):
    """Devuelve C(f) usando el drive LS-optimo (refinamiento S5 de `dba`)."""
    Cmat = coupling_matrix(basis, pistons)
    Phi_s = basis.phi_matrix(sensors)

    def C_of_f(f: float) -> np.ndarray:
        _, C_opt, _ = ls_drive(basis, Cmat, Phi_s, sensors, f,
                               axis=axis, xi=xi, reg=reg)
        return C_opt

    return C_of_f


def ls_error_curve(basis: RectModalBasis, pistons: list, sensors, freqs, *,
                   axis: int = 1, xi: float = 0.03, reg: float = 0.0
                   ) -> np.ndarray:
    """E_LS(f) sobre un eje de frecuencias (para el cross-check vs Santillan)."""
    Cmat = coupling_matrix(basis, pistons)
    Phi_s = basis.phi_matrix(sensors)
    E = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        _, _, E[i] = ls_drive(basis, Cmat, Phi_s, sensors, float(f),
                              axis=axis, xi=xi, reg=reg)
    return E


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
