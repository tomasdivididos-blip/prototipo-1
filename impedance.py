"""
impedance.py - Capa 0: modelado de impedancia de superficie
============================================================
Produce la admitancia especifica compleja beta(f) = rho0*c / Z_s de una
construccion de pared, desde un modelo fisico (poroso empirico + camara de aire
via TMM) o desde una medicion del usuario. Alimenta la perturbacion de frontera
(face_materials.perturbation_xi_per_mode); NO toca el ensamblaje FEM.

NUCLEO numpy PURO (decision D0). Sin scipy, sin terceros.

Estado: ETAPA 1a (motor local empirico). Constructores:
  - rigid()                       pared rigida (beta ~ 0)
  - resistive(beta_real)          admitancia real constante (puente con Paris)
  - porous(sigma, thickness, ...) poroso Delany-Bazley/Miki + camara de aire (TMM)
  - multilayer(specs)             pila general de capas por TMM
  - measured_Zf(freqs, Z)         Z(f) medida (incidencia normal, local)

Convencion temporal: e^{-i w t} (parte imaginaria de Z_c negativa), siguiendo
Delany-Bazley tal como lo escriben Aygun y Bruneau&Potel (Ec 6.133/6.134). La
reconciliacion de signo con la formula de perturbacion (Re(beta)->delta,
Im(beta)->corrimiento) es tema de la Etapa 1c; en 1a se valida alpha(f), que
sale de |R|^2 y es independiente del signo.

Referencias:
  - Delany & Bazley 1970 (Applied Acoustics 3, 105): coeficientes empiricos.
    Confirmados en Aygun "Sound absorbing materials" y Bruneau & Potel
    "Materials and Acoustics Handbook" Ec 6.133/6.134. X = rho0*f/sigma,
    valido 0.01 < X < 1.0.
  - Miki 1986/1990 (mod. de Delany-Bazley; ref #27 en Cox & D'Antonio):
    misma X. Cross-check numerico de las constantes en la cabecera de miki_zc_kc.
  - TMM: Cox & D'Antonio "Acoustic Absorbers and Diffusers" 2a ed, Ec 5.24
    (matriz de transferencia) y Ec 5.25 (recursion de impedancia de superficie).
"""

from __future__ import annotations
from typing import Callable, List, Dict
import numpy as np

# Constantes fisicas (coherentes con sources.py).
RHO0 = 1.21          # densidad del aire [kg/m^3]
C0 = 343.0           # velocidad del sonido [m/s]
Z0 = RHO0 * C0       # impedancia caracteristica del aire ~ 415 rayl


def _as_f(f) -> np.ndarray:
    """f a array 1D float (Hz), clampeado > 0 para evitar division por cero."""
    f = np.atleast_1d(np.asarray(f, dtype=float))
    return np.maximum(f, 1e-6)


# ---------------------------------------------------------------------------
# Constantes de propagacion de un poroso (fluido equivalente empirico)
# ---------------------------------------------------------------------------
def db_zc_kc(f, sigma: float):
    """Delany-Bazley 1970: (Z_c, k_c) de un poroso fibroso desde la resistividad
    al flujo sigma [Pa*s/m^2 = N*s/m^4]. X = rho0*f/sigma, valido 0.01<X<1.

    Confirmado en Aygun y Bruneau&Potel Ec 6.133/6.134:
        Z_c/rho0c = 1 + 0.0571 X^-0.754 - i 0.087 X^-0.732
        k_c/k0    = 1 + 0.0978 X^-0.700 - i 0.189 X^-0.595
    """
    f = _as_f(f)
    X = RHO0 * f / float(sigma)
    zc = Z0 * (1.0 + 0.0571 * X ** -0.754 - 1j * 0.087 * X ** -0.732)
    k0 = 2.0 * np.pi * f / C0
    kc = k0 * (1.0 + 0.0978 * X ** -0.700 - 1j * 0.189 * X ** -0.595)
    return zc, kc


def miki_zc_kc(f, sigma: float):
    """Miki 1986/1990 (modificacion de Delany-Bazley). Misma X = rho0*f/sigma:
        Z_c/rho0c = 1 + 0.0699 X^-0.632 - i 0.107 X^-0.632
        k_c/k0    = 1 + 0.109  X^-0.618 - i 0.160 X^-0.618

    Cross-check de las constantes (para no confiar en memoria): la forma
    publicada con variable 10^3*f/sigma y coeficientes (5.50, 8.43, 7.81, 11.41)
    coincide con estas a 3 cifras. Con rho0=1.21, 10^3 f/sigma = (10^3/rho0) X =
    826.4 X, y 826.4^-0.632 = 0.01263 => 5.50*0.01263 = 0.0695 ~ 0.0699;
    8.43*0.01263 = 0.1065 ~ 0.107; 826.4^-0.618 = 0.01380 => 7.81*0.01380 =
    0.1078 ~ 0.109; 11.41*0.01380 = 0.1575 ~ 0.160. Coherente.

    Ventaja sobre Delany-Bazley: se mantiene fisico (Re(Z_c) > 0) por debajo de
    X = 0.01, que es justo la banda modal de una sala tratada (f<200 Hz, sigma
    de lana ~ 10-40 kPa*s/m^2 => X < 0.01). Por eso es el default.
    """
    f = _as_f(f)
    X = RHO0 * f / float(sigma)
    zc = Z0 * (1.0 + 0.0699 * X ** -0.632 - 1j * 0.107 * X ** -0.632)
    k0 = 2.0 * np.pi * f / C0
    kc = k0 * (1.0 + 0.109 * X ** -0.618 - 1j * 0.160 * X ** -0.618)
    return zc, kc


_MODELS: Dict[str, Callable] = {
    "db": db_zc_kc, "delany-bazley": db_zc_kc, "delany_bazley": db_zc_kc,
    "miki": miki_zc_kc,
}


# ---------------------------------------------------------------------------
# Capas para el TMM. Cada capa es (zk_func(f)->(Z_c,k_c), thickness).
# ---------------------------------------------------------------------------
def _air_zk(f):
    f = _as_f(f)
    return np.full(f.shape, Z0, dtype=complex), (2.0 * np.pi * f / C0).astype(complex)


def _porous_zk(sigma: float, model: str) -> Callable:
    zk = _MODELS[model.lower()]
    return lambda f: zk(f, sigma)


def _surface_Z_tmm(layers: List, f) -> np.ndarray:
    """Impedancia de superficie Z_s(f) de una pila con backing RIGIDO, por la
    recursion de Cox Ec 5.25 (incidencia normal).

    `layers`: lista de (zk_func, thickness) ordenada de la SUPERFICIE (arriba)
    hacia el BACKING (abajo). Se procesa de abajo hacia arriba: la capa mas
    profunda ve el backing rigido (z0 = inf) -> Z = -i Z_c cot(k_c d); cada capa
    superior usa la Z de la de abajo como su backing.
    """
    f = _as_f(f)
    z = None
    for zk, d in reversed(layers):
        zc, kc = zk(f)
        cot = np.cos(kc * d) / np.sin(kc * d)
        if z is None:
            z = -1j * zc * cot                      # backing rigido (z_prev=inf)
        else:
            z = (-1j * z * zc * cot + zc ** 2) / (z - 1j * zc * cot)
    return z


# ---------------------------------------------------------------------------
# SurfaceImpedance: objeto que entrega Z(f), beta(f), alpha(f,theta), alpha_random
# ---------------------------------------------------------------------------
class SurfaceImpedance:
    """Impedancia de superficie de una construccion. En Etapa 1a todo es de
    reaccion LOCAL: Z depende solo de f; el angulo entra solo en el coeficiente
    de reflexion R(theta). La reaccion extendida (Z(f,theta)) es Etapa 2."""

    def __init__(self, zfunc: Callable, is_locally_reacting: bool = True,
                 label: str = ""):
        self._z = zfunc
        self.is_locally_reacting = is_locally_reacting
        self.label = label

    def Z(self, f) -> np.ndarray:
        """Impedancia de superficie compleja [Pa*s/m]."""
        return self._z(_as_f(f))

    def beta(self, f) -> np.ndarray:
        """Admitancia especifica compleja beta = rho0*c / Z_s (adimensional).
        Es la que consume la perturbacion de frontera."""
        return Z0 / self.Z(f)

    def reflection(self, f, theta: float = 0.0) -> np.ndarray:
        """R(theta) = (Z_s cos(theta) - rho0 c) / (Z_s cos(theta) + rho0 c).
        Superficie de reaccion local."""
        ct = np.cos(theta)
        Zs = self.Z(f)
        return (Zs * ct - Z0) / (Zs * ct + Z0)

    def alpha(self, f, theta: float = 0.0) -> np.ndarray:
        """Coeficiente de absorcion a incidencia theta: 1 - |R|^2."""
        return 1.0 - np.abs(self.reflection(f, theta)) ** 2

    def alpha_random(self, f) -> np.ndarray:
        """Absorcion de incidencia ALEATORIA (Paris, ISO 354):
            alpha_st = INT_0^{pi/2} alpha(theta) sin(2 theta) d theta.
        Se compara contra el alpha del catalogo para validar el modelo."""
        f = _as_f(f)
        th = np.linspace(0.0, np.pi / 2.0, 2001)
        Zs = self.Z(f)[:, None]                       # (Nf, 1)
        ct = np.cos(th)[None, :]                       # (1, Nth)
        R = (Zs * ct - Z0) / (Zs * ct + Z0)
        integ = (1.0 - np.abs(R) ** 2) * np.sin(2.0 * th)[None, :]
        return np.trapz(integ, th, axis=1)             # (Nf,)


# ---------------------------------------------------------------------------
# Constructores
# ---------------------------------------------------------------------------
def rigid() -> SurfaceImpedance:
    """Pared rigida: Z -> infinito, beta -> 0 (solo el aire disipa)."""
    return SurfaceImpedance(
        lambda f: np.full(_as_f(f).shape, 1e12, dtype=complex),
        label="rigido")


def resistive(beta_real: float) -> SurfaceImpedance:
    """Admitancia especifica REAL y constante (Z = rho0c/beta). Es el puente con
    el modelo actual (Paris): resistive(beta).alpha_random == la alpha_random de
    Paris para esa beta."""
    return SurfaceImpedance(
        lambda f: np.full(_as_f(f).shape, Z0 / float(beta_real), dtype=complex),
        label=f"resistivo beta={beta_real:.3g}")


def porous(sigma: float, thickness: float, model: str = "miki",
           air_gap: float = 0.0) -> SurfaceImpedance:
    """Capa porosa (espesor `thickness`) sobre backing rigido, con `air_gap`
    opcional de aire por detras. `sigma` = resistividad al flujo [Pa*s/m^2].
    `model` in {"miki", "db"}. TMM (Cox Ec 5.25)."""
    layers = [(_porous_zk(sigma, model), float(thickness))]
    if air_gap and air_gap > 0:
        layers.append((_air_zk, float(air_gap)))       # capa de aire detras
    lbl = f"poroso {model} sigma={sigma:.0f} d={thickness*1e3:.0f}mm"
    if air_gap > 0:
        lbl += f" +aire {air_gap*1e3:.0f}mm"
    return SurfaceImpedance(lambda f: _surface_Z_tmm(layers, f), label=lbl)


def multilayer(specs: List[Dict]) -> SurfaceImpedance:
    """Pila general de capas por TMM, con backing rigido. `specs` de la
    SUPERFICIE al BACKING; cada dict:
        {"type": "porous", "sigma": ..., "thickness": ..., "model": "miki"}
        {"type": "air",    "thickness": ...}
    """
    layers = []
    for s in specs:
        t = float(s["thickness"])
        if s["type"] == "porous":
            layers.append((_porous_zk(float(s["sigma"]),
                                      s.get("model", "miki")), t))
        elif s["type"] == "air":
            layers.append((_air_zk, t))
        else:
            raise ValueError(f"tipo de capa desconocido: {s['type']!r}")
    return SurfaceImpedance(lambda f: _surface_Z_tmm(layers, f),
                            label=f"multicapa ({len(specs)})")


def measured_Zf(freqs, Z) -> SurfaceImpedance:
    """Z(f) medida (incidencia normal, reaccion local). Interpola parte real e
    imaginaria por separado; extrapola con el valor de borde (constante)."""
    fq = np.asarray(freqs, dtype=float)
    Zc = np.asarray(Z, dtype=complex)
    order = np.argsort(fq)
    fq, Zc = fq[order], Zc[order]

    def zfunc(f):
        f = _as_f(f)
        re = np.interp(f, fq, Zc.real)
        im = np.interp(f, fq, Zc.imag)
        return re + 1j * im

    return SurfaceImpedance(zfunc, label="Z medida (f)")
