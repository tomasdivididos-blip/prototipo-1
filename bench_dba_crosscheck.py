"""
bench_dba_crosscheck.py
=======================

Refinamiento S5 (drive LS-optimo de Santillan) + CROSS-CHECK contra Santillan
(JASA 110(4), 1989-1997, 2001). Ver `plan_modelo_fuente.md`.

Setup de Santillan (minado del paper): sala 2.7 x 5.0 x 2.2 m, c=346.4 m/s,
xi=0.03 (RT~0.2 s @ 180 Hz), pistones cuadrados 0.1 m, 16 parlantes por pared
(grilla 4x4) en las dos paredes perpendiculares a y. Zona de escucha y in
[0.6, 4.4], todo Lx, piso a techo. Target = onda plana viajera en +y.

  T1  E_LS pequeno bajo f_max (la onda plana se sintetiza) [Santillan Fig 7]
  T2  E_LS crece sobre f_max (aliasing espacial)
  T3  LEY f_max = c/d  (d = espaciado entre fuentes) al variar N   [Fig 9]
  T4  refinamiento: drive LS < retardo naive (mismo par de fuentes de pared)

Correr:  /c/Users/aceve/anaconda3/python.exe bench_dba_crosscheck.py
"""

import numpy as np

from source_coupling import RectModalBasis, WallPiston
from sources import RHO0
from dba import (piston_wall_grid, coupling_matrix, plane_wave_target, ls_drive,
                 ls_error_curve)

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


# --- constantes de Santillan ----------------------------------------------
DIMS = (2.7, 5.0, 2.2)
C_SANT = 346.4
XI = 0.03
AXIS = 1
FMAX_MODES = 620.0


def _listening_zone(n_y=7, n_x=6, n_z=4):
    ys = np.linspace(0.6, 4.4, n_y)
    xs = np.linspace(0.25, DIMS[0] - 0.25, n_x)
    zs = np.linspace(0.25, DIMS[2] - 0.25, n_z)
    return np.array([[x, y, z] for x in xs for y in ys for z in zs])


def _basis():
    return RectModalBasis(DIMS, fmax=FMAX_MODES, n_max=18, c=C_SANT)


def _f_cross(freqs, E, level=0.3):
    """Primera frecuencia donde E cruza `level` de abajo hacia arriba."""
    for i in range(1, len(E)):
        if E[i - 1] < level <= E[i]:
            # interpolacion lineal
            t = (level - E[i - 1]) / (E[i] - E[i - 1])
            return freqs[i - 1] + t * (freqs[i] - freqs[i - 1])
    return freqs[-1] if E[-1] < level else freqs[0]


# ---------------------------------------------------------------------------
# T1 + T2 — E_LS(f): pequeno bajo f_max, crece por aliasing (Fig 7)
# ---------------------------------------------------------------------------
def t1_t2_error_curve():
    basis = _basis()
    front = piston_wall_grid(basis, AXIS, "min", 4, 4)
    rear = piston_wall_grid(basis, AXIS, "max", 4, 4)
    pistons = front + rear
    sensors = _listening_zone()
    freqs = np.linspace(40.0, 460.0, 43)
    E = ls_error_curve(basis, pistons, sensors, freqs, axis=AXIS, xi=XI)

    # Banda de diseño (encima del arranque modal, debajo de f_max). El criterio
    # de Santillan es E<0.3 = buena ecualizacion. Robusto a los bumps de
    # resonancia (que el propio paper reporta en 110/165/220 Hz).
    band = (freqs >= 60) & (freqs <= 320)
    med = np.median(E[band])
    frac = np.mean(E[band] < 0.3)
    e_hi = np.mean(E[freqs > 420])
    check("T1 E_LS < 0.3 en la banda de diseno (mediana<0.2, >85% bajo 0.3)",
          med < 0.2 and frac > 0.85, f"mediana={med:.3f}  frac<0.3={frac:.2f}")
    check("T2 E_LS crece por aliasing (E@>420 >> banda)", e_hi > 2.5 * med,
          f"E(>420)={e_hi:.3f}  mediana banda={med:.3f}")
    fx = _f_cross(freqs, E, 0.3)
    # d_x del layout 4x4 (limitante) y f_max = c/d
    dx = (DIMS[0] - 0.10) / (4 - 1)          # centros 0.05..Lx-0.05
    fmax_pred = C_SANT / dx
    print(f"       E_LS cruza 0.3 en {fx:.0f} Hz  (c/d_x = {fmax_pred:.0f} Hz)")


# ---------------------------------------------------------------------------
# T3 — LEY f_max = c/d al variar el numero de fuentes (Fig 9)
# ---------------------------------------------------------------------------
def t3_fmax_law():
    basis = _basis()
    sensors = _listening_zone()
    freqs = np.linspace(40.0, 560.0, 53)
    rows = []
    # n_z=6 fijo (d_z=0.42 -> c/d_z~825, siempre encima) para que el espaciado
    # en x sea SIEMPRE el limitante: asi f_max mide c/d_x limpio.
    for n_x in (2, 3, 4, 5):
        front = piston_wall_grid(basis, AXIS, "min", n_x, 6)
        rear = piston_wall_grid(basis, AXIS, "max", n_x, 6)
        E = ls_error_curve(basis, front + rear, sensors, freqs, axis=AXIS, xi=XI)
        fx = _f_cross(freqs, E, 0.3)
        d = (DIMS[0] - 0.10) / (n_x - 1)
        rows.append((n_x, d, C_SANT / d, fx))
    print("       n_x   d[m]   c/d[Hz]  f_meas[Hz]")
    for n_x, d, cd, fx in rows:
        print(f"        {n_x}    {d:.3f}   {cd:5.0f}    {fx:5.0f}")
    # La ley: f_meas ~ c/d. Correlacion alta y ratio ~ constante.
    cd = np.array([r[2] for r in rows])
    fm = np.array([r[3] for r in rows])
    corr = np.corrcoef(cd, fm)[0, 1]
    ratio = fm / cd
    check("T3 f_max escala con c/d (corr > 0.95)", corr > 0.95,
          f"corr={corr:.3f}")
    check("T3 f_meas ~ c/d (ratio constante +-25%)",
          np.std(ratio) / np.mean(ratio) < 0.25,
          f"ratios={['%.2f' % r for r in ratio]}")


# ---------------------------------------------------------------------------
# T4 — refinamiento: drive LS <= retardo naive (mismo par de fuentes de pared)
# ---------------------------------------------------------------------------
def t4_ls_beats_naive():
    basis = _basis()
    sensors = _listening_zone()
    # Par de fuentes de PARED ENTERA (front + rear), como el DBA naive.
    front = WallPiston(axis=AXIS, side="min", vn=1.0)
    rear = WallPiston(axis=AXIS, side="max", vn=1.0)
    Cmat = coupling_matrix(basis, [front, rear])
    Phi_s = basis.phi_matrix(sensors)

    freqs = np.linspace(40.0, 200.0, 30)
    E_ls, E_naive = [], []
    for f in freqs:
        omega = 2.0 * np.pi * f
        k = omega / basis.c
        denom = (basis.omega_n ** 2 - omega ** 2) + 2j * XI * basis.omega_n * omega
        Z = 1j * omega * RHO0 * basis.c ** 2 * (Phi_s @ (Cmat / denom[:, None]))
        d = plane_wave_target(sensors, k, AXIS)
        # naive: q = [1, -e^{-i w Ly/c}], comparado por FORMA (escala alfa optima)
        # para no penalizar la amplitud (LS escala libre; el naive fija vn=1).
        q_naive = np.array([1.0, -np.exp(-1j * omega * DIMS[AXIS] / basis.c)])
        p_naive = Z @ q_naive
        alpha = np.vdot(p_naive, d) / np.vdot(p_naive, p_naive)
        E_naive.append(np.linalg.norm(alpha * p_naive - d) / np.linalg.norm(d))
        _, _, e = ls_drive(basis, Cmat, Phi_s, sensors, f, axis=AXIS, xi=XI)
        E_ls.append(e)
    m_ls, m_naive = np.mean(E_ls), np.mean(E_naive)
    check("T4 drive LS <= naive (minimiza el residuo)", m_ls <= m_naive + 1e-9,
          f"E_ls={m_ls:.3f}  E_naive={m_naive:.3f}")
    check("T4 LS mejora estricta sobre naive", m_ls < 0.98 * m_naive,
          f"mejora={100*(1-m_ls/m_naive):.1f}%")


# --- posiciones exactas de la Fig 6 de Santillan --------------------------
SANT_POS = [(0.3, 0.9, 0.3), (1.0, 1.8, 0.9), (1.7, 3.2, 1.5), (2.4, 4.1, 2.2)]


def _two_source_before():
    """'Antes': 2 pistones en la pared y=0 con la misma senal (setup de Fig 1)."""
    h = 0.05
    p1 = WallPiston(axis=AXIS, side="min",
                    span=(0.05 - h, 0.05 + h, 2.00 - h, 2.00 + h), vn=1.0)
    p2 = WallPiston(axis=AXIS, side="min",
                    span=(2.65 - h, 2.65 + h, 2.00 - h, 2.00 + h), vn=1.0)
    return [p1, p2]


# ---------------------------------------------------------------------------
# T5 — Fig 6: la FRF se aplana en las 4 posiciones tras ecualizar
# ---------------------------------------------------------------------------
def t5_fig6_frf_flattening():
    from dba import coupling_matrix, dba_ls_coupling_fn
    basis = _basis()
    sensors = _listening_zone()
    C_before = coupling_matrix(basis, _two_source_before()).sum(axis=1)
    C_after = dba_ls_coupling_fn(
        basis, piston_wall_grid(basis, AXIS, "min", 4, 4)
        + piston_wall_grid(basis, AXIS, "max", 4, 4), sensors, axis=AXIS, xi=XI)
    fa = np.linspace(40.0, 300.0, 260)
    improved = 0
    for pos in SANT_POS:
        Hb = 20 * np.log10(np.abs(basis.frf(np.array(pos), fa, C_before, xi=XI)) + 1e-12)
        Ha = 20 * np.log10(np.abs(basis.frf_dispersive(np.array(pos), fa, C_after, xi=XI)) + 1e-12)
        if np.std(Ha) < np.std(Hb):
            improved += 1
    check("T5 Fig6: FRF mas plana tras ecualizar (4/4 posiciones)",
          improved == 4, f"mejoraron {improved}/4")


# ---------------------------------------------------------------------------
# T6 — Fig 6: la respuesta impulsiva colapsa a delta retardada
# ---------------------------------------------------------------------------
def t6_fig6_impulse_delta():
    from dba import coupling_matrix, dba_ls_coupling_fn, impulse_response, schroeder_decay_db
    basis = _basis()
    sensors = _listening_zone()
    C_before = coupling_matrix(basis, _two_source_before()).sum(axis=1)
    C_after = dba_ls_coupling_fn(
        basis, piston_wall_grid(basis, AXIS, "min", 4, 4)
        + piston_wall_grid(basis, AXIS, "max", 4, 4), sensors, axis=AXIS, xi=XI)
    pos = np.array(SANT_POS[2])
    t, hb = impulse_response(basis, pos, C_before, fmax=300.0, xi=XI)
    _, ha = impulse_response(basis, pos, C_after, fmax=300.0, xi=XI)
    sb, sa = schroeder_decay_db(hb), schroeder_decay_db(ha)

    def t15(s):
        i = np.argmax(s <= -15.0)
        return t[i] if s[i] <= -15.0 else t[-1]

    check("T6 Fig6: IR colapsa (decay tras eq << antes)",
          t15(sa) < 0.5 * t15(sb),
          f"t_antes={t15(sb)*1e3:.0f} ms  t_despues={t15(sa)*1e3:.0f} ms")


if __name__ == "__main__":
    print("bench_dba_crosscheck.py — refinamiento S5 (LS) + cross-check Santillan\n")
    t1_t2_error_curve()
    t3_fmax_law()
    t4_ls_beats_naive()
    t5_fig6_frf_flattening()
    t6_fig6_impulse_delta()
    print(f"\n  {_PASS} OK, {_FAIL} FAIL")
    raise SystemExit(1 if _FAIL else 0)
