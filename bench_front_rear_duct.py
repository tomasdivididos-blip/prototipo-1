"""
bench_front_rear_duct.py
========================

ORACULO ANALITICO (E1) para `plan_frente_opuesto_admitancia.md`: la interaccion
front<->rear de subs como absorcion activa / terminacion de admitancia, en el
analogo 1-D exacto de Nelson & Elliott, *Active Control of Sound* (1992), cap. 5
(fuente primaria q_p en x=0, secundaria q_s en x=L; = pared frontal / trasera).

Valida, SIN FEM, las ecuaciones OCR-eadas del cap. 5 que sostienen el marco:
  T1  Admitancia del frente de onda: un monopolo plano en ducto infinito radia
      aguas abajo una onda plana con u/p = 1/(rho0 c0) = Y0 (admitancia
      caracteristica). Es "la admitancia del frente de onda impuesto por el sub".
  T2  Cancelacion aguas abajo (5.3): la presion downstream se anula con
      q_s = -q_p e^{-jkL} (absorcion activa de la radiacion incidente).
  T3  Potencia minima del par (5.6): con la fuerza optima q_s0 = -q_p cos(kL)
      (Ec 5.6.4), W0/Wpp = sin^2(kL) (Ec 5.6.6).
  T4  Terminacion absorbente en recinto (5.15): la componente que viaja
      aguas-arriba (la reflejada por la pared trasera) se anula con
      q_s = -q_p e^{-jkL} (Ec 5.15.3) -> coef. de reflexion R = 0 -> sin
      estacionaria en el eje -> el campo remanente es una onda plana viajera
      con admitancia Y0.

NO toca el solver ni el nucleo de la app; es un prototipo/oraculo de referencia.
Convencion de tiempo e^{+jwt} (la del texto, 5.15); el solver de la app usa
e^{+iwt} tambien para el campo, pero el modulo de impedancia usa e^{-iwt} (gotcha
conocido: conj(beta) al cablear). Aca se trabaja todo en la convencion del texto.
"""

from __future__ import annotations

import numpy as np

from sources import C0, RHO0

Z0 = RHO0 * C0           # impedancia caracteristica rho0 c0
Y0 = 1.0 / Z0            # admitancia caracteristica


# ---------------------------------------------------------------------------
# Modelo 1-D (ducto de seccion S). Monopolo plano de "fuerza" q [m^3/s] en x0:
# radia p_+-(x) = (rho0 c0 q / 2S) e^{-jk|x-x0|}, onda plana a cada lado.
# ---------------------------------------------------------------------------
def monopole_field(x, x0, q, k, S=1.0):
    """Presion de un monopolo plano de fuerza q en x0, en ducto infinito."""
    return (Z0 * q / (2.0 * S)) * np.exp(-1j * k * np.abs(np.asarray(x) - x0))


def downstream_amplitude(q_p, q_s, k, L, S=1.0):
    """Amplitud compleja de la onda que viaja aguas ABAJO (x>L), factor comun
    e^{-jkx} sacado: p(x>L) = (rho0 c0/2S) e^{-jkx} [q_p + q_s e^{jkL}]."""
    return (Z0 / (2.0 * S)) * (q_p + q_s * np.exp(1j * k * L))


def total_power_pair(q_p, q_s, k, L, S=1.0):
    """Potencia total del par primario+secundario, Nelson&Elliott Ec 5.6.2:
    W = (rho0 c0/4S)[|q_s|^2 + (q_p cos kL)* q_s + q_s*(q_p cos kL) + |q_p|^2]."""
    c = np.cos(k * L)
    b = q_p * c
    return (Z0 / (4.0 * S)) * (np.abs(q_s) ** 2
                               + np.conj(b) * q_s + np.conj(q_s) * b
                               + np.abs(q_p) ** 2)


def wpp(q_p, S=1.0):
    """Potencia del primario solo (ausente el secundario): rho0 c0 |q_p|^2/4S."""
    return Z0 * np.abs(q_p) ** 2 / (4.0 * S)


# ---------------------------------------------------------------------------
# Recinto 1-D rigido-rigido con los dos monopolos (Nelson&Elliott 5.14/5.15):
# descomposicion en onda que viaja aguas-abajo (e^{-jkx}) y aguas-arriba (e^{+jkx}).
# ---------------------------------------------------------------------------
def traveling_components(q_p, q_s, k, L):
    """(A_down, A_up): amplitudes de las ondas viajeras downstream (+x) y
    upstream (-x) del campo del par. La upstream es la 'reflejada' de la pared
    trasera; R = |A_up| / |A_down|. A_up se anula con q_s = -q_p e^{-jkL}."""
    A_down = q_p * np.exp(1j * k * L) + q_s          # ~ e^{-jkx}
    A_up = q_p * np.exp(-1j * k * L) + q_s           # ~ e^{+jkx}
    return A_down, A_up


def run():
    results = []
    ks = 2 * np.pi * np.linspace(20.0, 180.0, 40) / C0   # banda sub-Schroeder
    L = 4.1                                              # eje front-rear [m]
    q_p = 1.0 + 0.0j

    # T1: admitancia del frente de onda (onda plana) = Y0.
    # u = p/(rho0 c0) para onda plana progresiva -> u/p = Y0.
    k0 = 2 * np.pi * 50.0 / C0
    x = np.linspace(0.5, 3.0, 200)
    p = monopole_field(x, 0.0, q_p, k0)                 # downstream (x>0)
    u = p / Z0                                          # onda plana: u = p/Z0
    Y = u / p
    err_Y = float(np.max(np.abs(Y - Y0)) / Y0)
    t1 = err_Y < 1e-12
    results.append(("T1 admitancia del frente u/p = Y0 (onda plana)",
                    t1, f"max|Y-Y0|/Y0 = {err_Y:.2e}"))

    # T2: cancelacion aguas abajo con q_s = -q_p e^{-jkL}.
    worst = 0.0
    for k in ks:
        q_s = -q_p * np.exp(-1j * k * L)
        A = downstream_amplitude(q_p, q_s, k, L)
        worst = max(worst, abs(A) / abs(downstream_amplitude(q_p, 0.0, k, L)))
    t2 = worst < 1e-12
    results.append(("T2 cancelacion downstream (q_s=-q_p e^{-jkL})",
                    t2, f"max |p_down|/|p_down(solo primario)| = {worst:.2e}"))

    # T3: potencia minima del par. Optimo q_s0 = -q_p cos kL -> W0/Wpp = sin^2 kL.
    worst_law = 0.0
    worst_opt = 0.0
    for k in ks:
        c = np.cos(k * L)
        q_s0 = -q_p * c
        W0 = total_power_pair(q_p, q_s0, k, L).real
        law = W0 / wpp(q_p)
        worst_law = max(worst_law, abs(law - np.sin(k * L) ** 2))
        # q_s0 es realmente el minimo: barrido local de |q_s| y fase.
        grid = q_s0 + (np.linspace(-0.5, 0.5, 21)[:, None]
                       + 1j * np.linspace(-0.5, 0.5, 21)[None, :])
        Wg = total_power_pair(q_p, grid, k, L).real
        worst_opt = max(worst_opt, (W0 - Wg.min()) / wpp(q_p))
    t3 = worst_law < 1e-12 and worst_opt < 1e-9
    results.append(("T3 W0/Wpp = sin^2(kL) con q_s0=-q_p cos kL (5.6.6)",
                    t3, f"max|ley-sin^2| = {worst_law:.2e}; "
                        f"exceso sobre el minimo barrido = {worst_opt:.2e}"))

    # T4: terminacion absorbente: R -> 0 con q_s = -q_p e^{-jkL} (5.15.3).
    worst_R0 = 0.0      # R con secundario optimo (deberia ser ~0)
    min_R_off = np.inf  # R sin secundario (pared rigida: |A_up|=|A_down|)
    for k in ks:
        q_s = -q_p * np.exp(-1j * k * L)
        Ad, Au = traveling_components(q_p, q_s, k, L)
        worst_R0 = max(worst_R0, abs(Au) / abs(Ad))
        Ad0, Au0 = traveling_components(q_p, 0.0, k, L)
        min_R_off = min(min_R_off, abs(Au0) / abs(Ad0))
    t4 = worst_R0 < 1e-12 and min_R_off > 0.99
    results.append(("T4 terminacion absorbente R->0 (5.15.3)",
                    t4, f"max R(optimo) = {worst_R0:.2e}; "
                        f"min R(sin secundario) = {min_R_off:.3f} (rigido=1)"))

    return results


if __name__ == "__main__":
    rs = run()
    npass = sum(1 for _, ok, _ in rs if ok)
    for name, ok, detail in rs:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    print(f"\n{npass}/{len(rs)} checks OK  "
          f"(Z0 = rho0 c0 = {Z0:.1f} Pa.s/m, Y0 = {Y0:.3e} m/Pa.s)")
    raise SystemExit(0 if npass == len(rs) else 1)
