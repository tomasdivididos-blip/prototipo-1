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
from sources import RHO0, C0


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


def array_naive_coupling_fn(basis: RectModalBasis, front: list, rear: list,
                            axis: int = 1, delay: float | None = None
                            ) -> Callable[[float], np.ndarray]:
    """Drive de RETARDO naive para arrays de pistones front/rear (generaliza
    dba_coupling_fn a grillas): C(f) = Cf - e^{-i w tau} * Cr, con Cf/Cr los
    acoplamientos de las grillas (vn=1) y tau el tiempo de tránsito."""
    if delay is None:
        delay = travel_delay(basis, axis)
    Cf = coupling_matrix(basis, front).sum(axis=1)
    Cr = coupling_matrix(basis, rear).sum(axis=1)

    def C_of_f(f: float) -> np.ndarray:
        return Cf - np.exp(-1j * 2.0 * np.pi * f * delay) * Cr

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
        # Tikhonov con penalización RELATIVA al esfuerzo (reg escala con la
        # magnitud de Z, así el mismo reg vale a toda frecuencia): tamiza los
        # nulos profundos del LS sin regularizar (mal condicionado con pocos
        # subs). q = (Z^H Z + reg*<|diag|> I)^-1 Z^H d.
        ZhZ = Z.conj().T @ Z
        dd = float(np.mean(np.abs(np.diag(ZhZ))))
        if dd < 1e-30:                       # Z ~ 0 (p.ej. DC): sin drive
            q = np.zeros(Z.shape[1], dtype=complex)
        else:
            q = np.linalg.solve(ZhZ + reg * dd * np.eye(Z.shape[1]),
                                Z.conj().T @ d)
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


def _zone_grid(dims, axis: int, n_a=5, n_b=4, n_c=5, margin=0.5):
    """Grilla de receptores en la zona de escucha: descuenta `margin` de las
    dos paredes perpendiculares a `axis` (donde están los arrays) y de bordes."""
    los = [margin, margin, margin]
    his = [d - margin for d in dims]
    ns = [n_a, n_b, n_c]
    axes = [np.linspace(los[k], his[k], ns[k]) if his[k] > los[k]
            else np.array([dims[k] / 2]) for k in range(3)]
    return np.array([[x, y, z] for x in axes[0] for y in axes[1] for z in axes[2]])


def _t_decay(t, sch, level_db=-15.0):
    i = int(np.argmax(sch <= level_db))
    return float(t[i]) if sch[i] <= level_db else float(t[-1])


def alias_fmax(dims, axis: int, n_a: int, n_b: int, c: float = C0,
               inset: float = 0.05) -> float:
    """Frecuencia máxima de ecualización f_max = c/d (Santillán), con d el mayor
    espaciado entre subs adyacentes en los dos ejes transversales a `axis`. Por
    encima de f_max el array no puede sintetizar la onda plana (aliasing
    espacial) y el DBA deja de servir. Devuelve inf si hay 1 sub por eje."""
    a, b = tuple(x for x in (0, 1, 2) if x != axis)
    ds = []
    for L, n in ((dims[a], n_a), (dims[b], n_b)):
        if n > 1:
            ds.append((L - 2 * inset) / (n - 1))
    return float(c / max(ds)) if ds else float("inf")


def compute_dba(dims, receiver, *, axis: int = 1, n_x: int = 4, n_z: int = 4,
                drive: str = "ls", xi: float = 0.03, fmin: float = 20.0,
                fmax: float = 200.0, n_freq: int = 220, reg: float = 0.005,
                c: float = C0) -> dict:
    """Análisis DBA/CABS para una sala rectangular (motor headless de la
    herramienta de GUI). Compara CABS off (array frontal solo) vs on (front +
    rear con el drive elegido).

    Las métricas (planitud espectral, varianza espacial) se miden en la BANDA
    VÁLIDA [fmin, min(fmax, f_max=c/d)]: arriba de f_max hay aliasing espacial y
    el DBA no aplica, así que promediar ahí ensuciaría el número. El drive LS se
    regulariza (reg) para no crear nulos profundos. drive: "ls" | "naive".
    """
    dims = tuple(float(x) for x in dims)
    receiver = np.asarray(receiver, dtype=float)
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    basis = RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)
    front = piston_wall_grid(basis, axis, "min", n_x, n_z)
    rear = piston_wall_grid(basis, axis, "max", n_x, n_z)
    zone = _zone_grid(dims, axis)

    C_before = coupling_matrix(basis, front).sum(axis=1)
    if drive == "naive":
        C_after = array_naive_coupling_fn(basis, front, rear, axis)
    else:
        C_after = dba_ls_coupling_fn(basis, front + rear, zone, axis=axis,
                                     xi=xi, reg=reg)

    f_max = alias_fmax(dims, axis, n_x, n_z, c=c)
    band_hi = min(fmax, f_max)

    fa = np.linspace(fmin, fmax, n_freq)
    Hb = basis.frf(receiver, fa, C_before, xi=xi)
    Ha = basis.frf_dispersive(receiver, fa, C_after, xi=xi)
    Hb_db = 20.0 * np.log10(np.abs(Hb) + 1e-12)
    Ha_db = 20.0 * np.log10(np.abs(Ha) + 1e-12)

    # planitud espectral SOLO en la banda válida
    inb = (fa >= fmin) & (fa <= band_hi)
    if np.count_nonzero(inb) < 4:            # banda válida muy chica
        inb = fa <= max(band_hi, fa[3])
    flat_before = float(np.std(Hb_db[inb]))
    flat_after = float(np.std(Ha_db[inb]))

    # varianza espacial en la banda válida
    sb, sa = [], []
    for f in np.linspace(max(fmin, 25.0), band_hi, 18):
        pb = np.abs(basis.pressure_field(zone, f, C_before, xi=xi))
        Cf = C_after(f) if callable(C_after) else C_after
        pa = np.abs(basis.pressure_field(zone, f, Cf, xi=xi))
        sb.append(np.std(20.0 * np.log10(pb / pb.mean())))
        sa.append(np.std(20.0 * np.log10(pa / pa.mean())))

    return {
        "freq": fa, "Hb_db": Hb_db, "Ha_db": Ha_db,
        "flat_before": flat_before, "flat_after": flat_after,
        "spatial_before": float(np.mean(sb)), "spatial_after": float(np.mean(sa)),
        "f_max": f_max, "band_hi": float(band_hi),
        "n_modes": basis.n_modes,
        "n_front": len(front), "n_rear": len(rear),
    }


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
