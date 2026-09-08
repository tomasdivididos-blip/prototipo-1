"""
bench_dipole.py
===============

Oraculos del acoplamiento DIPOLO (bafle abierto, item 5 Fase B). El dipolo se
modela como dos monopolos opuestos separados por ell (ancho del bafle) a lo largo
del eje del bafle; su acoplamiento C_n = phi_n(x+) - phi_n(x-) es la derivada
direccional del modo (figura-8). Sin evaluar gradiente.

Correr:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_dipole.py
"""

from __future__ import annotations

import numpy as np

from source_coupling import RectModalBasis
from sources import OmniSource
import dba_evaluate as dev
import driver as drv

DIMS = (5.0, 6.2, 3.0)
XS = (1.3, 2.0, 1.1)          # punto generico (no nodo de (1,0,0))
_n = _ok = 0


def check(name, cond, detail=""):
    global _n, _ok
    _n += 1
    _ok += 1 if cond else 0
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def _basis():
    return RectModalBasis(DIMS, fmax=160.0, n_max=12)


def _grad_phi(basis, x):
    """Gradiente analitico (Nm,3) de phi_n en x (derivada de cosenos / sqrtK)."""
    x = np.asarray(x, float)
    Lx, Ly, Lz = basis.dims
    G = np.zeros((basis.n_modes, 3))
    for i, (nx, ny, nz) in enumerate(basis.modes):
        ax, ay, az = nx * np.pi / Lx, ny * np.pi / Ly, nz * np.pi / Lz
        cx, cy, cz = np.cos(ax * x[0]), np.cos(ay * x[1]), np.cos(az * x[2])
        sx, sy, sz = np.sin(ax * x[0]), np.sin(ay * x[1]), np.sin(az * x[2])
        k = basis._sqrtK[i]
        G[i, 0] = -ax * sx * cy * cz / k
        G[i, 1] = -ay * cx * sy * cz / k
        G[i, 2] = -az * cx * cy * sz / k
    return G


def test_figure8():
    """T1: un dipolo orientado en Y NO acopla a los modos axiales-X (d perp grad);
    un monopolo en el mismo punto SI. Es la firma de la figura-8."""
    print("T1 figura-8 (dipolo-Y ciego a axiales-X)")
    b = _basis()
    i_ax = b.modes.index((1, 0, 0))
    mono = OmniSource(XS, radiator_kind="box")
    dip_y = OmniSource(XS, radiator_kind="open_baffle", orientation=90.0,
                       baffle_size=(0.3, 0.5, 0.4))
    dip_x = OmniSource(XS, radiator_kind="open_baffle", orientation=0.0,
                       baffle_size=(0.3, 0.5, 0.4))
    k_mono = dev._modal_coupling(b, [mono], (0, 0, 0))[0]
    k_dy = dev._modal_coupling(b, [dip_y], (0, 0, 0))[0]
    k_dx = dev._modal_coupling(b, [dip_x], (0, 0, 0))[0]
    check("monopolo acopla al axial-X (!=0)", abs(k_mono[i_ax]) > 1e-3,
          f"|k|={abs(k_mono[i_ax]):.4f}")
    check("dipolo-Y NO acopla al axial-X (~0)", abs(k_dy[i_ax]) < 1e-9,
          f"|k|={abs(k_dy[i_ax]):.2e}")
    check("dipolo-X SI acopla al axial-X (!=0)", abs(k_dx[i_ax]) > 1e-3,
          f"|k|={abs(k_dx[i_ax]):.4f}")


def test_directional_derivative():
    """T2: con ell chico, C_n/ell -> d . grad(phi_n) (el dipolo ES la derivada
    direccional del modo)."""
    print("T2 acople = derivada direccional")
    b = _basis()
    ell = 0.02
    dip = OmniSource(XS, radiator_kind="open_baffle", orientation=35.0, pitch=20.0,
                     baffle_size=(ell, 0.5, 0.4))
    from sources import dipole_direction
    d = dipole_direction(35.0, 20.0)
    k = dev._modal_coupling(b, [dip], (0, 0, 0))[0]        # ~ ell * d.grad
    g = _grad_phi(b, XS) @ d                                # analitico
    # La diferencia central tiene error de truncamiento O(ell^2) ~ 1e-4; se
    # compara a ese orden (no a 1e-6). Con ell mas chico el error baja como ell^2.
    check("C_n/ell ~ d.grad(phi_n) (a O(ell^2))",
          np.allclose(k / ell, g, rtol=5e-3, atol=1e-3),
          f"max err={np.max(np.abs(k/ell - g)):.2e}")


def test_vanishes():
    """T3: el dipolo se anula cuando ell->0 (a Q fijo)."""
    print("T3 el dipolo se anula con ell->0")
    b = _basis()
    k_big = dev._modal_coupling(b, [OmniSource(XS, radiator_kind="open_baffle",
                                               baffle_size=(0.4, 0.5, 0.4))], (0, 0, 0))[0]
    k_tiny = dev._modal_coupling(b, [OmniSource(XS, radiator_kind="open_baffle",
                                                baffle_size=(1e-4, 0.5, 0.4))], (0, 0, 0))[0]
    check("||k(ell chico)|| << ||k(ell grande)||",
          np.linalg.norm(k_tiny) < 0.01 * np.linalg.norm(k_big))


def test_monopole_regression():
    """T4: una fuente de caja (monopolo) acopla EXACTO como phi_n(x_s): el dipolo
    no toca el path historico."""
    print("T4 monopolo = phi_n(x_s) (sin regresion)")
    b = _basis()
    k = dev._modal_coupling(b, [OmniSource(XS, radiator_kind="box")], (0, 0, 0))[0]
    check("kappa == basis.phi(x_s)", np.allclose(k, b.phi(np.asarray(XS)), rtol=1e-12))


def test_open_baffle_gain():
    """T5: rolloff dipolar (open_baffle_gain): 0 dB arriba de f_D=c/(2*ancho),
    -3 dB en f_D, cae al grave; y effective_Q_spectrum lo aplica (open_baffle +
    driver) distinto del baffle step de la caja."""
    print("T5 rolloff dipolar + dispatch por radiador")
    w = 0.3
    f_d = 343.0 / (2 * w)
    g = drv.open_baffle_gain(np.array([2.0, f_d, 5000.0]), w)
    db = 20 * np.log10(np.abs(g))
    check("HF ~ 0 dB", abs(db[2]) < 0.1, f"{db[2]:.3f}")
    check("en f_D ~ -3 dB", abs(db[1] - (-3.0)) < 0.3, f"{db[1]:.2f}")
    check("LF fuertemente atenuado (<-20 dB)", db[0] < -20.0, f"{db[0]:.1f}")
    fa = np.linspace(20, 400, 60)
    base = dict(position=(1, 1, 1), sensitivity_dB=90.0, baffle_size=(0.3, 0.5, 0.4),
                radiation_baked="driver")
    q_box = OmniSource(**base, radiator_kind="box").effective_Q_spectrum(fa)
    q_ob = OmniSource(**base, radiator_kind="open_baffle").effective_Q_spectrum(fa)
    check("open_baffle usa rolloff dipolar (!= baffle step de caja)",
          not np.allclose(q_box, q_ob, rtol=1e-3))


if __name__ == "__main__":
    print("=" * 60)
    print("bench_dipole.py  —  acoplamiento dipolo (item 5 Fase B)")
    print("=" * 60)
    test_figure8()
    test_directional_derivative()
    test_vanishes()
    test_monopole_regression()
    test_open_baffle_gain()
    print("-" * 60)
    print(f"  {_ok}/{_n} checks OK")
    if _ok != _n:
        raise SystemExit(1)
