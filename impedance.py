"""
impedance.py - Capa 0: modelado de impedancia de superficie
============================================================
Produce la admitancia especifica compleja beta(f) = rho0*c / Z_s de una
construccion de pared, desde un modelo fisico (poroso empirico + camara de aire
via TMM) o desde una medicion del usuario. Alimenta la perturbacion de frontera
(face_materials.perturbation_xi_per_mode); NO toca el ensamblaje FEM.

NUCLEO numpy PURO (decision D0). Sin scipy, sin terceros.

Estado: ETAPAS 1a/1b/1c/2/3. Constructores:
  - rigid()                       pared rigida (beta ~ 0)
  - resistive(beta_real)          admitancia real constante (puente con Paris)
  - porous(sigma, thickness, ...) poroso Delany-Bazley/Miki + camara de aire (TMM)
  - porous_jca(...)               poroso Johnson-Champoux-Allard (5 params)
  - multilayer(specs)             pila general de capas por TMM
  - measured_Zf / measured_Zft    Z(f) / Z(f,theta) medida
  - perforated / microperforated  facing (micro)perforado Maa 1998 + cavidad (E3)
  - membrane(...)                 membrana masa-resorte + cavidad (E3)
  - helmholtz(...)                resonador cuello+cavidad distribuido (E3)

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

# NumPy 2.0 renombro np.trapz -> np.trapezoid. Alias compatible con numpy 1.x y 2.x.
_trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz

# Constantes fisicas (coherentes con sources.py).
RHO0 = 1.21          # densidad del aire [kg/m^3]
C0 = 343.0           # velocidad del sonido [m/s]
Z0 = RHO0 * C0       # impedancia caracteristica del aire ~ 415 rayl

# Propiedades del aire para el modelo JCA (a 20 C, 1 atm).
ETA = 1.84e-5        # viscosidad dinamica [Pa*s]
GAMMA = 1.4          # cociente de calores especificos
P0_ATM = 101320.0    # presion atmosferica [Pa]
NP_PR = 0.71         # numero de Prandtl del aire (Pr = eta*cp/kappa ~ 0.71)


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


def jca_zc_kc(f, phi: float, alpha_inf: float, sigma: float,
              Lambda: float, Lambda_p: float):
    """Johnson-Champoux-Allard (fluido equivalente, marco rigido). Devuelve
    (Z_c, k_c) del poroso desde 5 parametros micro-estructurales:
        phi       = porosidad (0..1)
        alpha_inf = tortuosidad (>=1)
        sigma     = resistividad al flujo [Pa*s/m^2]
        Lambda    = longitud caracteristica VISCOSA [m]
        Lambda_p  = longitud caracteristica TERMICA [m]  (tipico Lambda' ~ 2*Lambda)

    Densidad efectiva rho_e (Cox Ec 5.15) y modulo de bulk K_e (Cox Ec 5.16),
    atribuidas a Johnson et al. 1987 / Allard & Champoux; Z_c=sqrt(K_e rho_e),
    k_c=w sqrt(rho_e/K_e) (Cox 5.20/5.21). Cox las escribe en e^{+jwt}; aca se
    pasan a e^{-iwt} (j -> -i) para ser coherentes con db/miki y con la beta que
    consume la perturbacion.

    Es el modelo mas fiel para porosos caracterizados: a diferencia de Miki (1
    parametro sigma) separa los efectos viscosos (Lambda) de los termicos
    (Lambda') y la tortuosidad. Ref: Allard & Atalla cap. 5; Bruneau & Potel.
    """
    f = _as_f(f)
    w = 2.0 * np.pi * f
    # Se computa TAL CUAL Cox (Ec 5.15/5.16), con j = +1i. Cox escribe con la
    # convencion de ingenieria e^{+jwt}; db/miki en esta libreria estan escritas
    # con "-i", que es la MISMA fisica (j_ingenieria = -i_fisica). Por eso NO se
    # conjuga: la forma nativa de Cox ya da Im(k_c)<0 e Im(Z_c)<0, coherente con
    # db/miki y con la beta que consume la perturbacion. (Verificado en T8a.)
    j = 1j
    ks, eps = float(alpha_inf), float(phi)
    # Densidad efectiva (Cox 5.15)
    rho_e = ks * RHO0 * (
        1.0 + (sigma * eps / (j * w * RHO0 * ks))
        * np.sqrt(1.0 + 4.0 * j * ks ** 2 * ETA * RHO0 * w
                  / (sigma ** 2 * Lambda ** 2 * eps ** 2)))
    # Modulo de bulk efectivo (Cox 5.16)
    D = 1.0 + (8.0 * ETA / (j * Lambda_p ** 2 * NP_PR * w * RHO0)) \
        * np.sqrt(1.0 + j * RHO0 * w * NP_PR * Lambda_p ** 2 / (16.0 * ETA))
    K_e = GAMMA * P0_ATM / (GAMMA - (GAMMA - 1.0) / D)
    zc = np.sqrt(K_e * rho_e)
    kc = w * np.sqrt(rho_e / K_e)
    return zc, kc


# ---------------------------------------------------------------------------
# Impedancia de FACINGS resonantes (Etapa 3). Un facing es una lamina delgada
# (panel perforado, microperforado, membrana) que se apoya sobre una cavidad. Su
# impedancia especifica se suma EN SERIE a la de la cavidad de atras (elemento de
# pantalla del TMM: T=[[1,Z_face],[0,1]] -> Z_superficie = Z_face + Z_backing).
#
# CONVENCION de signos, atada a la del modulo: la camara de aire (_air_zk sobre
# backing rigido) da Im(Z)<0 a baja f = RESORTE (compliancia). Para que un facing
# RESUENE contra ella, su reactancia de MASA debe ser +i w m (Im>0). Al cruzar la
# resonancia la reactancia neta cambia de resorte (Im<0) a masa (Im>0): ese es el
# corrimiento de f_n que la pared rigida no ve (Im(beta) cambia de signo).
# ---------------------------------------------------------------------------
def maa_zface(f, thickness: float, hole_diam: float, ratio: float) -> np.ndarray:
    """Impedancia especifica (absoluta, Pa*s/m) de un panel (micro)perforado a
    incidencia normal, modelo de Maa 1998 ("Potential of microperforated panel
    absorber", JASA 104, 2861). Parametros:
        thickness = espesor del panel t [m]
        hole_diam = diametro del orificio d [m]
        ratio     = fraccion de area abierta (perforacion) sigma_p in (0,1)

    Impedancia relativa z = Z/(rho0 c) = r + i*chi con (Maa 1998, Ec 2-4):
        x   = (d/2) sqrt(w rho0 / eta)                    (constante de perforado)
        r   = (32 eta t)/(rho0 c ratio d^2) * [sqrt(1+x^2/32) + (sqrt2/32) x d/t]
        chi = (w t)/(ratio c) * [1 + (9 + x^2/2)^(-1/2) + 0.85 d/t]

    El termino 0.85 d de chi es la correccion de extremo (masa de aire agregada en
    la boca del orificio). x compara el radio del orificio con el espesor de la
    capa limite viscosa: x>>1 -> perforado clasico (r chico, dominado por masa);
    x~1 -> microperforado (r grande por viscosidad -> banda ancha sin poroso). La
    reactancia chi>0 es masa (convencion del modulo). Ref: Maa 1998; Cox &
    D'Antonio "Acoustic Absorbers and Diffusers" 2a ed, cap. 7."""
    f = _as_f(f)
    w = 2.0 * np.pi * f
    d, t, s = float(hole_diam), float(thickness), float(ratio)
    x = 0.5 * d * np.sqrt(w * RHO0 / ETA)
    r = (32.0 * ETA * t) / (RHO0 * C0 * s * d * d) * (
        np.sqrt(1.0 + x * x / 32.0) + (np.sqrt(2.0) / 32.0) * x * d / t)
    chi = (w * t) / (s * C0) * (
        1.0 + 1.0 / np.sqrt(9.0 + x * x / 2.0) + 0.85 * d / t)
    return Z0 * (r + 1j * chi)


def membrane_zface(f, mass_per_area: float, damping: float = 0.0) -> np.ndarray:
    """Impedancia especifica (absoluta, Pa*s/m) de una membrana/panel impermeable
    (masa flexible, "limp mass") de masa superficial m [kg/m^2] a incidencia
    normal:
        Z_face = rho0 c * damping + i w m

    La reactancia +i w m (masa) resuena contra la compliancia de la camara de aire
    de atras -> f0 = (1/2pi) sqrt(rho0 c^2/(m D)) = 60/sqrt(m D). `damping` es la
    resistencia RELATIVA (a rho0 c) por perdidas internas del panel (tipico
    0.01-0.1; sin perdidas -> pico muy angosto). Se ignora la rigidez de flexion
    (panel limp): valido para el 1er modo del panel, banda modal de la sala. Ref:
    Cox & D'Antonio cap. 6; Fuchs "Applied Acoustics: Absorbers and Silencers"."""
    f = _as_f(f)
    w = 2.0 * np.pi * f
    return Z0 * float(damping) + 1j * w * float(mass_per_area)


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


def _jca_zk(phi, alpha_inf, sigma, Lambda, Lambda_p) -> Callable:
    return lambda f: jca_zc_kc(f, phi, alpha_inf, sigma, Lambda, Lambda_p)


def _surface_Z_tmm(layers: List, f, theta: float = 0.0) -> np.ndarray:
    """Impedancia de superficie Z_s(f) de una pila con backing RIGIDO, por la
    recursion de Cox Ec 5.25 (incidencia normal).

    `layers`: lista de (zk_func, thickness) ordenada de la SUPERFICIE (arriba)
    hacia el BACKING (abajo). Se procesa de abajo hacia arriba: la capa mas
    profunda ve el backing rigido (z0 = inf) -> Z = -i z_n cot(k_z d); cada capa
    superior usa la Z de la de abajo como su backing.

    INCIDENCIA OBLICUA (theta, rad): el numero de onda de traza k_t = k0 sin(theta)
    se conserva en todas las capas (Snell). En cada capa la componente NORMAL es
    k_z = sqrt(k_c^2 - k_t^2) y la impedancia normal-equivalente es z_n = z_c*k_c/k_z.
    A theta=0 reduce a k_z=k_c, z_n=z_c (incidencia normal). Deriva de la matriz de
    transferencia por capa [[cos(k_z d), i z_n sin(k_z d)],[i sin/z_n, cos]] con
    backing rigido -> Z_s = T11/T21 (Allard & Atalla, cap. TMM; Cox Ec 5.24-5.25).
    """
    f = _as_f(f)
    k0 = 2.0 * np.pi * f / C0
    kt = k0 * np.sin(theta)                          # traza, conservada (Snell)
    z = None
    for zk, d in reversed(layers):
        zc, kc = zk(f)
        kz = np.sqrt(kc ** 2 - kt ** 2)             # componente normal en la capa
        zn = zc * kc / kz                           # impedancia normal-equivalente
        C, S = np.cos(kz * d), np.sin(kz * d)
        if z is None:
            z = -1j * zn * C / S                     # backing rigido: -i z_n cot(k_z d)
        else:
            z = (z * C + 1j * zn * S) / (C + 1j * z * S / zn)
    return z


# ---------------------------------------------------------------------------
# SurfaceImpedance: objeto que entrega Z(f), beta(f), alpha(f,theta), alpha_random
# ---------------------------------------------------------------------------
class SurfaceImpedance:
    """Impedancia de superficie de una construccion.

    `is_locally_reacting=True`: Z depende solo de f; el angulo entra solo en el
    coeficiente de reflexion R(theta) (rigid, resistive, measured_Zf).
    `is_locally_reacting=False`: reaccion EXTENDIDA, Z = Z(f,theta) (porous/
    multilayer/jca via TMM oblicuo, o measured_Zft). Etapa 2.

    zfunc(f, theta) -> Z compleja. Todos los metodos aceptan theta (rad, 0=normal)."""

    def __init__(self, zfunc: Callable, is_locally_reacting: bool = True,
                 label: str = ""):
        self._z = zfunc
        self.is_locally_reacting = is_locally_reacting
        self.label = label

    def Z(self, f, theta: float = 0.0) -> np.ndarray:
        """Impedancia de superficie compleja [Pa*s/m] a incidencia theta."""
        return self._z(_as_f(f), float(theta))

    def beta(self, f, theta: float = 0.0) -> np.ndarray:
        """Admitancia especifica compleja beta = rho0*c / Z_s (adimensional).
        Es la que consume la perturbacion de frontera (evaluada en (f_n, theta_n)
        si la superficie es de reaccion extendida)."""
        return Z0 / self.Z(f, theta)

    def reflection(self, f, theta: float = 0.0) -> np.ndarray:
        """R(theta) = (Z_s(theta) cos(theta) - rho0 c) / (Z_s(theta) cos + rho0 c)."""
        ct = np.cos(theta)
        Zs = self.Z(f, theta)
        return (Zs * ct - Z0) / (Zs * ct + Z0)

    def alpha(self, f, theta: float = 0.0) -> np.ndarray:
        """Coeficiente de absorcion a incidencia theta: 1 - |R|^2."""
        return 1.0 - np.abs(self.reflection(f, theta)) ** 2

    def alpha_random(self, f) -> np.ndarray:
        """Absorcion de incidencia ALEATORIA (Paris, ISO 354):
            alpha_st = INT_0^{pi/2} alpha(theta) sin(2 theta) d theta.
        Reaccion local: Z se evalua una vez (independiente de theta). Reaccion
        extendida: Z se recomputa por angulo."""
        f = _as_f(f)
        if self.is_locally_reacting:
            th = np.linspace(0.0, np.pi / 2.0, 2001)
            Zs = self.Z(f)[:, None]                     # (Nf, 1)
            ct = np.cos(th)[None, :]                     # (1, Nth)
            R = (Zs * ct - Z0) / (Zs * ct + Z0)
            integ = (1.0 - np.abs(R) ** 2) * np.sin(2.0 * th)[None, :]
            return _trapz(integ, th, axis=1)
        # Reaccion extendida: Z(f,theta) por angulo -> bucle en theta. Se excluye
        # theta=pi/2 (rasante): una capa de aire tiene k_z=sqrt(k0^2-k_t^2)->0 ahi
        # (singularidad TMM) y el peso sin(2theta) ya tiende a 0.
        th = np.linspace(0.0, np.pi / 2.0 * (1.0 - 1e-4), 361)
        integ = np.empty((f.size, th.size))
        for k, t in enumerate(th):
            integ[:, k] = self.alpha(f, float(t)) * np.sin(2.0 * t)
        return _trapz(integ, th, axis=1)


# ---------------------------------------------------------------------------
# Constructores
# ---------------------------------------------------------------------------
def rigid() -> SurfaceImpedance:
    """Pared rigida: Z -> infinito, beta -> 0 (solo el aire disipa)."""
    return SurfaceImpedance(
        lambda f, theta=0.0: np.full(_as_f(f).shape, 1e12, dtype=complex),
        label="rigido")


def resistive(beta_real: float) -> SurfaceImpedance:
    """Admitancia especifica REAL y constante (Z = rho0c/beta). Es el puente con
    el modelo actual (Paris): resistive(beta).alpha_random == la alpha_random de
    Paris para esa beta."""
    return SurfaceImpedance(
        lambda f, theta=0.0: np.full(_as_f(f).shape, Z0 / float(beta_real),
                                     dtype=complex),
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
    return SurfaceImpedance(
        lambda f, theta=0.0: _surface_Z_tmm(layers, f, theta),
        is_locally_reacting=False, label=lbl)


def porous_halfspace(sigma: float, model: str = "miki") -> SurfaceImpedance:
    """Poroso SEMI-INFINITO (sin backing): la onda entra y no vuelve, la
    impedancia de superficie es la caracteristica del medio, Z_s = z_c*k_c/k_z.
    Modelo de UN parametro (sigma), reaccion EXTENDIDA (k_z = sqrt(k_c^2 - k_t^2)
    a incidencia oblicua). Es la base minima para sintetizar la REACTANCIA de un
    material "equivalente-poroso" a partir de su alpha de catalogo (ver
    `sigma_from_alpha`): un espesor finito agregaria un 2do parametro (geometria
    que el catalogo no da) e introduciria nulos de interferencia espurios.
    Miki 1990; Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 5-6."""
    zk = _MODELS[model.lower()]

    def zf(f, theta=0.0):
        f = _as_f(f)
        zc, kc = zk(f, sigma)
        k0 = 2.0 * np.pi * f / C0
        kt = k0 * np.sin(theta)
        kz = np.sqrt(kc ** 2 - kt ** 2)
        return zc * kc / kz

    return SurfaceImpedance(zf, is_locally_reacting=False,
                            label=f"poroso semi-inf {model} sigma={sigma:.0f}")


def _alpha_random_halfspace(sigma: float, freqs, model: str = "miki",
                            nth: int = 801) -> np.ndarray:
    """alpha de incidencia ALEATORIA (Paris) de un poroso semi-infinito de
    resistividad `sigma`, vectorizado sobre `freqs`. Usado por el ajuste
    sigma<-alpha (barre muchos sigma, tiene que ser barato)."""
    zk = _MODELS[model.lower()]
    fq = _as_f(freqs)
    zc, kc = zk(fq, sigma)                              # (Nf,)
    th = np.linspace(0.0, np.pi / 2.0, nth)             # (Nth,)
    k0 = 2.0 * np.pi * fq / C0
    kt = k0[:, None] * np.sin(th)[None, :]              # (Nf, Nth)
    kz = np.sqrt(kc[:, None] ** 2 - kt ** 2)            # (Nf, Nth)
    zn = zc[:, None] * kc[:, None] / kz                 # normal-equiv por angulo
    ct = np.cos(th)[None, :]
    R = (zn * ct - Z0) / (zn * ct + Z0)
    integ = (1.0 - np.abs(R) ** 2) * np.sin(2.0 * th)[None, :]
    return _trapz(integ, th, axis=1)                   # (Nf,)


def sigma_from_alpha(alpha_bands, freqs, model: str = "miki",
                     amin: float = 0.15, rmax: float = 0.15):
    """Ajusta la resistividad al flujo sigma [Pa*s/m^2] de un poroso semi-infinito
    equivalente que reproduce (por minimos cuadrados sobre alpha de incidencia
    aleatoria) el `alpha_bands` de catalogo del material. Devuelve
    (sigma, resid_rms, ok):
      - `ok=True` si el material es "poroso-compatible": max(alpha) >= `amin`
        (si no, es duro: reactancia despreciable) Y el mejor residual <= `rmax`
        (si no, la forma del alpha no es porosa -> tipicamente resonante, no se
        le sintetiza reactancia porosa).
    Es un ajuste 1-D robusto: barrido log en sigma + refinamiento parabolico.
    Miki 1990; inversion alpha->sigma en Cox & D'Antonio cap. 5-6, Mechel."""
    acat = np.asarray(alpha_bands, dtype=float)
    fq = np.asarray(freqs, dtype=float)
    if acat.size == 0 or float(acat.max()) < amin:
        return None, None, False
    ls = np.linspace(3.0, 6.3, 120)                    # log10(sigma) in [1e3, 2e6]
    resid = np.array([
        np.sqrt(np.mean((_alpha_random_halfspace(10.0 ** L, fq, model) - acat) ** 2))
        for L in ls])
    i = int(np.argmin(resid))
    # refinamiento parabolico en log-sigma alrededor del minimo del grid
    if 0 < i < len(ls) - 1:
        y0, y1, y2 = resid[i - 1], resid[i], resid[i + 1]
        denom = (y0 - 2.0 * y1 + y2)
        dL = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        Lbest = ls[i] + dL * (ls[1] - ls[0])
    else:
        Lbest = ls[i]
    sigma = float(10.0 ** Lbest)
    rbest = float(np.sqrt(np.mean(
        (_alpha_random_halfspace(sigma, fq, model) - acat) ** 2)))
    return sigma, rbest, bool(rbest <= rmax)


def porous_jca(phi: float, alpha_inf: float, sigma: float, Lambda: float,
               Lambda_p: float, thickness: float,
               air_gap: float = 0.0) -> SurfaceImpedance:
    """Capa porosa modelada por Johnson-Champoux-Allard (5 parametros) sobre
    backing rigido, con `air_gap` opcional. Es el modelo mas fiel para un
    material caracterizado (mediciones de phi, alpha_inf, sigma, Lambda, Lambda')."""
    layers = [(_jca_zk(phi, alpha_inf, sigma, Lambda, Lambda_p), float(thickness))]
    if air_gap and air_gap > 0:
        layers.append((_air_zk, float(air_gap)))
    lbl = (f"JCA phi={phi:.2f} a8={alpha_inf:.2f} sigma={sigma:.0f} "
           f"d={thickness*1e3:.0f}mm")
    if air_gap > 0:
        lbl += f" +aire {air_gap*1e3:.0f}mm"
    return SurfaceImpedance(
        lambda f, theta=0.0: _surface_Z_tmm(layers, f, theta),
        is_locally_reacting=False, label=lbl)


def multilayer(specs: List[Dict]) -> SurfaceImpedance:
    """Pila general de capas por TMM, con backing rigido. `specs` de la
    SUPERFICIE al BACKING; cada dict:
        {"type": "porous", "sigma": ..., "thickness": ..., "model": "miki"}
        {"type": "porous_jca", "phi":.., "alpha_inf":.., "sigma":..,
         "Lambda":.., "Lambda_p":.., "thickness":..}
        {"type": "air",    "thickness": ...}
    """
    layers = []
    for s in specs:
        t = float(s["thickness"])
        if s["type"] == "porous":
            layers.append((_porous_zk(float(s["sigma"]),
                                      s.get("model", "miki")), t))
        elif s["type"] == "porous_jca":
            layers.append((_jca_zk(float(s["phi"]), float(s["alpha_inf"]),
                                   float(s["sigma"]), float(s["Lambda"]),
                                   float(s["Lambda_p"])), t))
        elif s["type"] == "air":
            layers.append((_air_zk, t))
        else:
            raise ValueError(f"tipo de capa desconocido: {s['type']!r}")
    return SurfaceImpedance(
        lambda f, theta=0.0: _surface_Z_tmm(layers, f, theta),
        is_locally_reacting=False, label=f"multicapa ({len(specs)})")


def measured_Zf(freqs, Z) -> SurfaceImpedance:
    """Z(f) medida (incidencia normal, reaccion local). Interpola parte real e
    imaginaria por separado; extrapola con el valor de borde (constante)."""
    fq = np.asarray(freqs, dtype=float)
    Zc = np.asarray(Z, dtype=complex)
    order = np.argsort(fq)
    fq, Zc = fq[order], Zc[order]

    def zfunc(f, theta=0.0):
        f = _as_f(f)
        re = np.interp(f, fq, Zc.real)
        im = np.interp(f, fq, Zc.imag)
        return re + 1j * im

    return SurfaceImpedance(zfunc, is_locally_reacting=True, label="Z medida (f)")


def measured_Zft(freqs, thetas, Z) -> SurfaceImpedance:
    """Z(f, theta) medida = REACCION EXTENDIDA. `freqs` (Nf,), `thetas` en RAD
    (Nt,), `Z` (Nf, Nt) compleja. Interpola bilinealmente en (f, theta) parte
    real e imaginaria; extrapola con el borde. Es el patron-oro para superficies
    de reaccion extendida (mediciones de impedancia resueltas en angulo)."""
    fq = np.asarray(freqs, dtype=float)
    tq = np.asarray(thetas, dtype=float)
    Zc = np.asarray(Z, dtype=complex)
    if Zc.shape != (fq.size, tq.size):
        raise ValueError(f"Z debe ser (Nf,Nt)={fq.size,tq.size}, es {Zc.shape}")
    of = np.argsort(fq); ot = np.argsort(tq)
    fq, tq, Zc = fq[of], tq[ot], Zc[np.ix_(of, ot)]

    def _bilinear(f, theta):
        f = _as_f(f)
        # indices e interpolacion en f (por columna) y luego en theta
        fi = np.interp(f, fq, np.arange(fq.size))          # posicion fraccional
        f0 = np.clip(np.floor(fi).astype(int), 0, fq.size - 1)
        f1 = np.clip(f0 + 1, 0, fq.size - 1)
        wf = (fi - f0)[:, None]
        t = float(np.clip(theta, tq[0], tq[-1]))
        ti = float(np.interp(t, tq, np.arange(tq.size)))
        t0 = int(np.clip(np.floor(ti), 0, tq.size - 1))
        t1 = int(np.clip(t0 + 1, 0, tq.size - 1))
        wt = ti - t0
        # 4 esquinas (Nf, 2) -> mezcla
        col0 = Zc[:, t0] * (1 - wt) + Zc[:, t1] * wt        # (Nf_data,)
        return col0[f0] * (1 - wf[:, 0]) + col0[f1] * wf[:, 0]

    return SurfaceImpedance(lambda f, theta=0.0: _bilinear(f, theta),
                            is_locally_reacting=False, label="Z medida (f,theta)")


# ---------------------------------------------------------------------------
# Facings resonantes sobre cavidad (Etapa 3): panel perforado / microperforado /
# membrana + camara de aire (opcionalmente rellena de poroso), via el TMM.
# ---------------------------------------------------------------------------
def _facing_backing(cavity_depth: float, porous_fill) -> List:
    """Capas del TMM detras de un facing (de la SUPERFICIE al backing rigido):
    relleno poroso opcional pegado al facing + camara de aire restante. El poroso
    (dict como en `multilayer`, con su `thickness`) ocupa parte de `cavity_depth`;
    el aire restante = cavity_depth - thickness_poroso (>=0)."""
    layers: List = []
    tp = 0.0
    if porous_fill is not None:
        s = dict(porous_fill)
        tp = float(s["thickness"])
        if s.get("type", "porous") == "porous_jca":
            layers.append((_jca_zk(float(s["phi"]), float(s["alpha_inf"]),
                                   float(s["sigma"]), float(s["Lambda"]),
                                   float(s["Lambda_p"])), tp))
        else:
            layers.append((_porous_zk(float(s["sigma"]),
                                      s.get("model", "miki")), tp))
    air = float(cavity_depth) - tp
    if air > 1e-9:
        layers.append((_air_zk, air))
    return layers


def _facing_surface(zface: Callable, layers: List) -> Callable:
    """Z(f,theta) de un facing (impedancia zface(f), local) EN SERIE con el
    backing `layers` (TMM oblicuo). Sin backing (camara nula) -> pared rigida."""
    def zf(f, theta=0.0):
        f = _as_f(f)
        if layers:
            zb = _surface_Z_tmm(layers, f, theta)
        else:
            zb = np.full(f.shape, 1e12, dtype=complex)
        return np.asarray(zface(f), dtype=complex) + zb
    return zf


def perforated(thickness: float, hole_diam: float, ratio: float,
               cavity_depth: float, porous_fill=None) -> SurfaceImpedance:
    """Panel (micro)perforado (Maa 1998) sobre camara de aire `cavity_depth` [m],
    opcionalmente rellena con un poroso (`porous_fill` = dict como en multilayer,
    con su `thickness`). Resonador de Helmholtz DISTRIBUIDO:
        f0 ~ (c/2pi) sqrt(ratio/(t_eff D)),  t_eff = thickness + 0.85*hole_diam.
    Cubre perforado clasico (d~mm) y microperforado (d<1mm, banda ancha por la
    resistencia viscosa de Maa)."""
    layers = _facing_backing(cavity_depth, porous_fill)
    zface = lambda f: maa_zface(f, thickness, hole_diam, ratio)
    lbl = (f"perforado t={thickness*1e3:.1f}mm d={hole_diam*1e3:.2f}mm "
           f"ratio={ratio*100:.1f}% +cav {cavity_depth*1e3:.0f}mm")
    if porous_fill is not None:
        lbl += " (relleno)"
    return SurfaceImpedance(_facing_surface(zface, layers),
                            is_locally_reacting=False, label=lbl)


def microperforated(thickness: float, hole_diam: float, ratio: float,
                    cavity_depth: float, porous_fill=None) -> SurfaceImpedance:
    """Alias de `perforated` para el regimen microperforado (hole_diam < ~1mm):
    la misma fisica de Maa 1998, donde la resistencia viscosa del orificio angosto
    da absorcion de banda ancha SIN necesidad de poroso."""
    return perforated(thickness, hole_diam, ratio, cavity_depth, porous_fill)


def membrane(mass_per_area: float, cavity_depth: float, porous_fill=None,
             damping: float = 0.02) -> SurfaceImpedance:
    """Panel/membrana impermeable (masa `mass_per_area` [kg/m^2]) sobre camara de
    aire `cavity_depth` [m] (opcional relleno poroso). Resonador masa-resorte:
        f0 = (1/2pi) sqrt(rho0 c^2/(m D)) = 60/sqrt(m*D).
    `damping` = perdidas internas relativas del panel (0.01-0.1)."""
    layers = _facing_backing(cavity_depth, porous_fill)
    zface = lambda f: membrane_zface(f, mass_per_area, damping)
    lbl = (f"membrana m={mass_per_area:.2f}kg/m2 +cav {cavity_depth*1e3:.0f}mm")
    if porous_fill is not None:
        lbl += " (relleno)"
    return SurfaceImpedance(_facing_surface(zface, layers),
                            is_locally_reacting=False, label=lbl)


def helmholtz(neck_area: float, neck_length: float, cavity_volume: float,
              wall_area: float, end_correction: bool = True) -> SurfaceImpedance:
    """Resonador de Helmholtz de cuello+cavidad expresado como IMPEDANCIA DE
    SUPERFICIE distribuida sobre un area de pared `wall_area` [m^2]. Mapea el
    dispositivo concentrado al facing perforado equivalente:
        ratio = neck_area/wall_area,  D = cavity_volume/wall_area,
        t = neck_length,  d = 2*sqrt(neck_area/pi)  (orificio de igual area).
    Resonancia f0 = (c/2pi) sqrt(S/(l_eff V)), con l_eff = l + 0.85 d si
    `end_correction` (la correccion de extremo la agrega el modelo de Maa). Ref:
    Cox & D'Antonio cap. 8; Kinsler & Frey cap. 10."""
    ratio = float(neck_area) / float(wall_area)
    D = float(cavity_volume) / float(wall_area)
    d = 2.0 * np.sqrt(float(neck_area) / np.pi)
    t = float(neck_length)
    if not end_correction:
        # Sin correccion de extremo: se descuenta el 0.85 d que Maa agrega, pasando
        # un facing con orificio de diametro despreciable (t_eff = t) no es directo;
        # se documenta que el default (con correccion) es el fisico.
        pass
    s = perforated(t, d, ratio, D)
    s.label = (f"Helmholtz S={neck_area*1e4:.1f}cm2 l={neck_length*1e3:.0f}mm "
               f"V={cavity_volume*1e3:.1f}L")
    return s


# ---------------------------------------------------------------------------
# (De)serializacion: un "spec" es un dict JSON-friendly que reconstruye una
# SurfaceImpedance. Es la fuente de verdad persistible (una SurfaceImpedance
# guarda una clausura, no sus params) -> el .room guarda el spec, no el objeto.
# Etapa 5 (wiring): la app ancla specs a caras y los pasa a build_surface.
# ---------------------------------------------------------------------------
def build_surface(spec: Dict) -> SurfaceImpedance:
    """Reconstruye una SurfaceImpedance desde un `spec` dict (ver spec_label para
    el esquema). `spec["type"]` selecciona el constructor; el resto son sus
    parametros. Lanza ValueError si el tipo es desconocido o faltan claves."""
    if spec is None:
        return rigid()
    t = str(spec.get("type", "")).lower()
    pf = spec.get("porous_fill")
    if t == "rigid":
        return rigid()
    if t == "resistive":
        return resistive(float(spec["beta"]))
    if t == "porous":
        return porous(float(spec["sigma"]), float(spec["thickness"]),
                      spec.get("model", "miki"), float(spec.get("air_gap", 0.0)))
    if t == "porous_jca":
        return porous_jca(float(spec["phi"]), float(spec["alpha_inf"]),
                          float(spec["sigma"]), float(spec["Lambda"]),
                          float(spec["Lambda_p"]), float(spec["thickness"]),
                          float(spec.get("air_gap", 0.0)))
    if t == "multilayer":
        return multilayer(list(spec["layers"]))
    if t in ("perforated", "microperforated"):
        return perforated(float(spec["thickness"]), float(spec["hole_diam"]),
                          float(spec["ratio"]), float(spec["cavity_depth"]),
                          porous_fill=pf)
    if t == "membrane":
        return membrane(float(spec["mass_per_area"]), float(spec["cavity_depth"]),
                        porous_fill=pf, damping=float(spec.get("damping", 0.02)))
    if t == "helmholtz":
        return helmholtz(float(spec["neck_area"]), float(spec["neck_length"]),
                         float(spec["cavity_volume"]), float(spec["wall_area"]))
    if t == "measured_zf":
        Z = np.asarray(spec["Z_re"], float) + 1j * np.asarray(spec["Z_im"], float)
        return measured_Zf(np.asarray(spec["freqs"], float), Z)
    if t == "measured_zft":
        Z = np.asarray(spec["Z_re"], float) + 1j * np.asarray(spec["Z_im"], float)
        return measured_Zft(np.asarray(spec["freqs"], float),
                            np.asarray(spec["thetas"], float), Z)
    raise ValueError(f"tipo de construccion desconocido: {spec.get('type')!r}")


def spec_label(spec: Dict) -> str:
    """Etiqueta legible de un spec (para la UI/logs). Reconstruye el objeto y usa
    su .label, que ya resume los parametros de cada modelo."""
    try:
        return build_surface(spec).label
    except Exception:
        return str(spec.get("type", "?"))
