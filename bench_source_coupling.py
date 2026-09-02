"""
bench_source_coupling.py
========================

Oraculos de la Fase S1 (fuente distribuida, base rectangular analitica).
Ver `plan_modelo_fuente.md`.

  T1  selectividad axial: piston de pared ENTERA -> solo modos axiales
  T2  reduccion: piston -> punto  (C_n -> Q*phi_n(x_wall)) al achicar la huella
  T3  reciprocidad de la FRF (fuente<->receptor)
  T4  prefactor: pico de un modo aislado = rho0*c^2*|Q phi_r phi_s|/(2 xi omega_n)
  T5  ortonormalidad: int phi_n^2 dV = 1  (numerico)
  T6  campo 1-D: piston de pared entera -> |p| independiente de x,z (payoff S1)

Correr:  /c/Users/aceve/anaconda3/python.exe bench_source_coupling.py
"""

import numpy as np

from source_coupling import (RectModalBasis, WallPiston, _seg_cos_integral,
                             total_coupling)
from sources import RHO0, C0

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  OK   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}  {detail}")


DIMS = (7.8, 4.1, 2.8)   # sala Santillan/CABS


# ---------------------------------------------------------------------------
# T1 — selectividad axial
# ---------------------------------------------------------------------------
def t1_axial_selectivity():
    basis = RectModalBasis(DIMS, fmax=160.0)
    C = basis.wall_piston_coupling(WallPiston(axis=1, side="min", vn=1.0))
    bad = []
    for i, (nx, ny, nz) in enumerate(basis.modes):
        excited = abs(C[i]) > 1e-9
        is_axial_y = (nx == 0 and nz == 0 and ny >= 1)
        if excited != is_axial_y:
            bad.append((basis.modes[i], abs(C[i])))
    check("T1 pared entera y=0 -> solo axiales (0,ny,0)", not bad,
          f"violaciones={bad[:4]}")
    # Idem pared x -> solo axiales-x.
    Cx = basis.wall_piston_coupling(WallPiston(axis=0, side="min", vn=1.0))
    bad_x = [basis.modes[i] for i in range(basis.n_modes)
             if (abs(Cx[i]) > 1e-9) != (basis.modes[i][1] == 0
                                        and basis.modes[i][2] == 0
                                        and basis.modes[i][0] >= 1)]
    check("T1 pared entera x=0 -> solo axiales (nx,0,0)", not bad_x,
          f"violaciones={bad_x[:4]}")


# ---------------------------------------------------------------------------
# T2 — reduccion piston -> punto
# ---------------------------------------------------------------------------
def t2_piston_to_point():
    basis = RectModalBasis(DIMS, fmax=160.0)
    # Centro de la pared y=0.
    xc, zc = DIMS[0] / 2.0, DIMS[2] / 2.0
    x_wall = np.array([xc, 0.0, zc])
    Q = 1.0
    errs = []
    for half in (0.4, 0.1, 0.02, 0.005):
        span = (xc - half, xc + half, zc - half, zc + half)
        area = (2 * half) ** 2
        piston = WallPiston(axis=1, side="min", span=span, vn=Q / area)
        C_piston = basis.wall_piston_coupling(piston)
        C_point = basis.point_coupling(Q, x_wall)
        errs.append(np.max(np.abs(C_piston - C_point)))
    check("T2 piston->punto converge al achicar huella",
          errs[-1] < errs[0] and errs[-1] < 1e-2,
          f"errs={['%.2e' % e for e in errs]}")


# ---------------------------------------------------------------------------
# T3 — reciprocidad
# ---------------------------------------------------------------------------
def t3_reciprocity():
    basis = RectModalBasis(DIMS, fmax=120.0)
    xs = np.array([0.3, 0.4, 0.5])
    xr = np.array([6.9, 3.5, 2.2])
    fa = np.linspace(20.0, 110.0, 200)
    H_sr = basis.frf(xr, fa, basis.point_coupling(1.0, xs), xi=0.02)
    H_rs = basis.frf(xs, fa, basis.point_coupling(1.0, xr), xi=0.02)
    check("T3 reciprocidad H(s->r)=H(r->s)",
          np.allclose(H_sr, H_rs, rtol=1e-9, atol=1e-12),
          f"max err={np.max(np.abs(H_sr - H_rs)):.2e}")


# ---------------------------------------------------------------------------
# T4 — prefactor por pico de modo aislado
# ---------------------------------------------------------------------------
def t4_single_mode_peak():
    basis = RectModalBasis(DIMS, fmax=120.0)
    xi = 0.005
    # Modo fundamental (menor f no nula): esta bien separado.
    i0 = 0
    f0 = basis.freqs[i0]
    xs = np.array([0.2, 0.2, 0.2])
    xr = np.array([7.6, 3.9, 2.6])
    Q = 1.0
    C = basis.point_coupling(Q, xs)
    H = basis.frf(xr, [f0], C, xi=xi)[0]
    phi_s = basis.phi(xs)[i0]
    phi_r = basis.phi(xr)[i0]
    omega_n = 2.0 * np.pi * f0
    expected = RHO0 * C0 ** 2 * abs(Q * phi_r * phi_s) / (2.0 * xi * omega_n)
    check(f"T4 pico modo aislado (modo {basis.modes[i0]})",
          np.isclose(abs(H), expected, rtol=3e-2),
          f"|H|={abs(H):.4g} vs {expected:.4g}")


# ---------------------------------------------------------------------------
# T5 — ortonormalidad numerica
# ---------------------------------------------------------------------------
def t5_orthonormal():
    basis = RectModalBasis(DIMS, fmax=90.0)
    Lx, Ly, Lz = DIMS
    ng = 40
    gx = (np.arange(ng) + 0.5) / ng * Lx
    gy = (np.arange(ng) + 0.5) / ng * Ly
    gz = (np.arange(ng) + 0.5) / ng * Lz
    dV = (Lx / ng) * (Ly / ng) * (Lz / ng)
    # Chequear un par de modos: int phi^2 dV ~ 1.
    worst = 0.0
    for idx in [0, 3, 7]:
        nx, ny, nz = basis.modes[idx]
        px = np.cos(nx * np.pi * gx / Lx)
        py = np.cos(ny * np.pi * gy / Ly)
        pz = np.cos(nz * np.pi * gz / Lz)
        p = px[:, None, None] * py[None, :, None] * pz[None, None, :]
        integral = np.sum((p / basis._sqrtK[idx]) ** 2) * dV
        worst = max(worst, abs(integral - 1.0))
    check("T5 int phi_n^2 dV = 1 (ortonormal)", worst < 2e-2,
          f"max|int-1|={worst:.3e}")


# ---------------------------------------------------------------------------
# T6 — campo 1-D (payoff S1): pared entera -> |p| indep. de x,z
# ---------------------------------------------------------------------------
def t6_one_dimensional_field():
    basis = RectModalBasis(DIMS, fmax=120.0)
    f = float(basis.freqs[0])           # primera resonancia axial-y
    # Grilla en un plano y=cte, variando x y z.
    y0 = 1.7
    xs = np.linspace(0.5, DIMS[0] - 0.5, 6)
    zs = np.linspace(0.4, DIMS[2] - 0.4, 5)
    pts = np.array([[x, y0, z] for x in xs for z in zs])

    # Piston de pared ENTERA en y=0 -> campo deberia depender solo de y.
    C_wall = basis.wall_piston_coupling(WallPiston(axis=1, side="min", vn=1.0))
    p_wall = np.abs(basis.pressure_field(pts, f, C_wall, xi=0.02))
    spl_wall = 20.0 * np.log10(p_wall / np.mean(p_wall))
    std_wall = np.std(spl_wall)

    # Fuente PUNTUAL en la esquina -> excita todos los modos -> varia en x,z.
    C_pt = basis.point_coupling(1.0, [0.05, 0.05, 0.05])
    p_pt = np.abs(basis.pressure_field(pts, f, C_pt, xi=0.02))
    spl_pt = 20.0 * np.log10(p_pt / np.mean(p_pt))
    std_pt = np.std(spl_pt)

    check("T6 pared entera -> campo indep. de x,z (std~0 dB)", std_wall < 1e-3,
          f"std_wall={std_wall:.2e} dB")
    check("T6 puntual esquina -> campo varia en x,z", std_pt > 1.0,
          f"std_pt={std_pt:.2f} dB")


if __name__ == "__main__":
    print("bench_source_coupling.py — oraculos Fase S1 (fuente distribuida)\n")
    t1_axial_selectivity()
    t2_piston_to_point()
    t3_reciprocity()
    t4_single_mode_peak()
    t5_orthonormal()
    t6_one_dimensional_field()
    print(f"\n  {_PASS} OK, {_FAIL} FAIL")
    raise SystemExit(1 if _FAIL else 0)
