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
            return np.trapz(integ, th, axis=1)
        # Reaccion extendida: Z(f,theta) por angulo -> bucle en theta. Se excluye
        # theta=pi/2 (rasante): una capa de aire tiene k_z=sqrt(k0^2-k_t^2)->0 ahi
        # (singularidad TMM) y el peso sin(2theta) ya tiende a 0.
        th = np.linspace(0.0, np.pi / 2.0 * (1.0 - 1e-4), 361)
        integ = np.empty((f.size, th.size))
        for k, t in enumerate(th):
            integ[:, k] = self.alpha(f, float(t)) * np.sin(2.0 * t)
        return np.trapz(integ, th, axis=1)


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
