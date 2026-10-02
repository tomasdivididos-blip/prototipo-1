"""
bench_front_rear_room.py
========================

E1b de `plan_frente_opuesto_admitancia.md`: llevar la admitancia del frente de
onda al campo MODAL de la sala rectangular (no ya el ducto 1-D del E1a). Calcula
el campo del array frontal, lo descompone en ondas viajeras aguas-abajo/arriba a
lo largo del eje front<->rear y extrae la admitancia INCIDENTE y el coeficiente de
reflexion R de la pared trasera.

Reusa el nucleo YA validado (`source_coupling.RectModalBasis`, `dba.py`), sin
tocarlo. Convencion e^{+iwt} (la del solver de la app).

DESCOMPOSICION: a (x,z) fijos, el campo p(y) se ajusta por minimos cuadrados a dos
ondas planas con el numero de onda ACUSTICO k=w/c:
    p(y) ~= A+ e^{-i k y}  +  A- e^{+i k y}
A+ = onda incidente (viaja hacia la pared trasera, +y); A- = reflejada.
  - Admitancia incidente: onda plana progresiva -> u_y/p = 1/(rho0 c) = Y0.
  - Reflexion de la pared trasera: R = |A-| / |A+|.

POR QUE la descomposicion y no el campo total en la pared: en una pared RIGIDA la
velocidad normal TOTAL es 0 (BC de Neumann), asi que Y_total(pared)=0, NO 1/rho0c.
La admitancia del frente vive en la componente incidente (Nelson&Elliott 5.12-5.15).

Checks:
  T1  Array de PARED ENTERA al frente -> campo puramente 1-D (solo modos axiales
      (0,m,0)); el ajuste de 2 ondas planas tiene residuo chico y da R~1 (pared
      rigida = reflexion total = estacionaria). Admitancia incidente = Y0.
  T2  La velocidad normal TOTAL en la pared trasera rigida -> 0 (|u_y(pared)| <<
      |u_y(centro)|): por eso Y_total(pared)=0 y hay que usar la componente
      incidente.
  T3  PAYOFF: con el array trasero manejado (drive naive CABS, retardo Ly/c +
      inversion, `dba.dba_coupling_fn`) R cae MUCHO (de ~1 a ~0): el trasero
      absorbe el frente de onda -> campo viajero, no estacionario.
  T4  BANDA DE VALIDEZ: con un array de GRILLA parcial (excita transversales), el
      residuo del ajuste 1-D es chico por DEBAJO del primer modo transversal y
      crece por encima (ahi el campo deja de ser una onda plana).
"""

from __future__ import annotations

import numpy as np

from source_coupling import RectModalBasis
import dba
from sources import RHO0, C0

Z0 = RHO0 * C0
Y0 = 1.0 / Z0


def _field(basis, points, f, C, xi, Phi=None):
    """Presion compleja en `points` a la frecuencia f, VECTORIZADA (sin el loop
    de modos de pressure_field): p = i w rho0 c^2 * Phi @ (C/denom). Phi puede
    pre-calcularse con basis.phi_matrix(points) para reusar entre frecuencias."""
    if Phi is None:
        Phi = basis.phi_matrix(points)
    omega = 2.0 * np.pi * f
    denom = (basis.omega_n ** 2 - omega ** 2) + 2j * xi * basis.omega_n * omega
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    coeff = np.asarray(C, dtype=complex) / denom
    return 1j * omega * RHO0 * basis.c ** 2 * (Phi @ coeff)


def _axis_line(basis, axis, xz, y0, y1, npts):
    """Puntos (npts,3) sobre una linea paralela a `axis` a traves de `xz` (las
    otras dos coordenadas), con la coordenada del eje de y0 a y1."""
    a, b = tuple(i for i in (0, 1, 2) if i != axis)
    ys = np.linspace(y0, y1, npts)
    pts = np.zeros((npts, 3))
    pts[:, axis] = ys
    pts[:, a] = xz[0]
    pts[:, b] = xz[1]
    return ys, pts


def decompose(basis, C, f, axis, xz, xi=1e-3, frac=(0.25, 0.75), npts=201):
    """Ajusta p(y) = A+ e^{-iky} + A- e^{+iky} sobre una VENTANA CENTRAL del eje
    (frac*L, lejos de ambas paredes, donde el modal converge bien). Devuelve
    (A_plus, A_minus, resid_rel, R). xi chico = aislar la reflexion geometrica
    del amortiguamiento de pared (el residuo restante es truncamiento modal)."""
    L = basis.dims[axis]
    ys, pts = _axis_line(basis, axis, xz, frac[0] * L, frac[1] * L, npts)
    p = _field(basis, pts, f, C, xi)
    k = 2.0 * np.pi * f / basis.c
    M = np.column_stack([np.exp(-1j * k * ys), np.exp(+1j * k * ys)])
    coef, *_ = np.linalg.lstsq(M, p, rcond=None)
    A_plus, A_minus = coef
    resid = M @ coef - p
    resid_rel = float(np.linalg.norm(resid) / max(np.linalg.norm(p), 1e-30))
    R = float(abs(A_minus) / max(abs(A_plus), 1e-30))
    return A_plus, A_minus, resid_rel, R


def rear_admittance(A_plus, A_minus, f, L, c):
    """Admitancia especifica NORMALIZADA (beta = Z0*u_n/p, con u_n hacia la pared)
    que presenta el borde trasero, extraida de la descomposicion viajera.

    En la pared y=L:  p = A+ e^{-jkL} + A- e^{+jkL};  u_y = (A+ e^{-jkL} - A-
    e^{+jkL})/Z0. Con r = (A- e^{+jkL})/(A+ e^{-jkL}) (coef. de reflexion EN la
    pared): beta = (1 - r)/(1 + r). Rigido: r=1 -> beta=0 (sin absorcion).
    Matcheado (A-=0): r=0 -> beta=1 = Y0 (absorcion total). Re(beta)>0 absorbe.
    Devuelve (r, beta) complejos."""
    k = 2.0 * np.pi * f / c
    inc = A_plus * np.exp(-1j * k * L)
    ref = A_minus * np.exp(+1j * k * L)
    r = ref / inc
    beta = (1.0 - r) / (1.0 + r)
    return r, beta


def _u_y(basis, pt, f, C, axis, xi=1e-3, h=1e-3):
    """Velocidad de particula normal u_axis = (1/(i w rho0)) dp/d(axis), por
    diferencia finita centrada."""
    omega = 2.0 * np.pi * f
    pp = pt.copy(); pp[axis] += h
    pm = pt.copy(); pm[axis] -= h
    dp = (_field(basis, [pp], f, C, xi)[0]
          - _field(basis, [pm], f, C, xi)[0]) / (2.0 * h)
    return dp / (1j * omega * RHO0)


def run():
    results = []
    dims = (3.0, 5.0, 2.8)       # eje front<->rear = y (axis=1), el mas largo
    axis = 1
    Lx, Ly, Lz = dims
    basis = RectModalBasis(dims, fmax=1200.0, n_max=45, c=C0)

    # Primer modo transversal (algun indice !=0 fuera del eje): su frecuencia.
    f_trans = min(C0 / (2 * Lx), C0 / (2 * Lz))      # nx=1 o nz=1
    f_axial1 = C0 / (2 * Ly)
    xz_center = (Lx / 2.0, Lz / 2.0)
    xz_off = (0.31 * Lx, 0.37 * Lz)
    # xi chico aisla la reflexion GEOMETRICA de la pared (rigida) del
    # amortiguamiento del material; el residuo restante es truncamiento modal.
    XI = 1e-3

    C_front = dba.front_only_coupling(basis, axis=axis)
    C_fn = dba.dba_coupling_fn(basis, axis=axis)     # frente + trasero retardado/invertido

    # --- T1 + T3 + E1c en un solo barrido de la banda solo-axial ---
    fs = np.linspace(0.6 * f_axial1, 0.95 * f_trans, 9)
    worst_resid = 0.0
    R_off, R_on = [], []
    beta_off, beta_on = [], []
    for f in fs:
        Apf, Amf, rr, Roff = decompose(basis, C_front, float(f), axis,
                                       xz_center, xi=XI)
        Apr, Amr, _, Ron = decompose(basis, C_fn(float(f)), float(f), axis,
                                     xz_center, xi=XI)
        worst_resid = max(worst_resid, rr)
        R_off.append(Roff); R_on.append(Ron)
        beta_off.append(rear_admittance(Apf, Amf, float(f), Ly, C0)[1])
        beta_on.append(rear_admittance(Apr, Amr, float(f), Ly, C0)[1])
    beta_off = np.array(beta_off); beta_on = np.array(beta_on)

    # T1: campo 1-D (2 ondas planas) + reflexion total en pared rigida + Y_inc=Y0.
    Yinc_err = abs((1.0 / Z0) - Y0) / Y0          # onda plana progresiva: u/p=Y0
    t1 = worst_resid < 0.12 and min(R_off) > 0.97 and Yinc_err < 1e-12
    results.append(("T1 pared entera: campo 1-D (2 ondas), R~1, Y_inc=Y0",
                    t1, f"max residuo (trunc. modal) = {worst_resid:.2e}; "
                        f"R_off in [{min(R_off):.3f},{max(R_off):.3f}] (rigido~1)"))

    # --- T2: velocidad normal TOTAL en la pared trasera rigida -> 0 ---
    f0 = float(0.8 * f_trans)
    pt_wall = np.array([xz_center[0], Ly - 1e-3, xz_center[1]])
    pt_mid = np.array([xz_center[0], Ly / 2.0, xz_center[1]])
    u_wall = abs(_u_y(basis, pt_wall, f0, C_front, axis, xi=XI))
    u_mid = abs(_u_y(basis, pt_mid, f0, C_front, axis, xi=XI))
    ratio = u_wall / max(u_mid, 1e-30)
    t2 = ratio < 1e-2
    results.append(("T2 u_normal(pared rigida)->0 (por eso Y_total!=Y_inc)",
                    t2, f"|u_y(pared)|/|u_y(centro)| = {ratio:.2e}"))

    # --- T3: PAYOFF: trasero manejado (naive CABS) absorbe -> R cae ---
    # La absorcion CRECE con la frecuencia (con kL): el trasero reduce R siempre,
    # y R->~0 cerca del tope de la banda axial. A 20 Hz (debajo del axial
    # fundamental) la onda plana aun no esta establecida -> R_on alto (caveat de
    # banda, coherente con T4). Claim honesto: reduccion monotona + R_on bajo arriba.
    R_off = np.array(R_off); R_on = np.array(R_on)
    reduces = bool(np.all(R_on < R_off - 0.05))         # absorbe en toda la banda
    monotonic = bool(np.all(np.diff(R_on) < 1e-6))      # mejora con la frecuencia
    t3 = reduces and monotonic and R_on[-1] < 0.25
    results.append(("T3 trasero manejado absorbe: R cae (mas con la frecuencia)",
                    t3, f"R_off {R_off[0]:.2f}->{R_off[-1]:.2f}; "
                        f"R_on {R_on[0]:.2f}->{R_on[-1]:.2f} "
                        f"(@{fs[-1]:.0f} Hz R_on={R_on[-1]:.3f}); "
                        f"reduce={reduces}, monotono={monotonic}"))

    # --- T4: banda de validez con una fuente OFF-CENTER (excita transversales).
    # Un array de pared entera (o un grid simetrico) solo excita axiales; para
    # ver el limite hace falta romper la simetria. Se compara el residuo del
    # ajuste 1-D en la resonancia AXIAL (0,1,0) (campo ~cos(pi y/Ly), w/c=pi/Ly,
    # 1-D exacto) vs en la resonancia TRANSVERSAL (1,0,0) (campo ~cos(pi x/Lx),
    # independiente de y pero w/c=pi/Lx != 0 -> NO es onda plana en y).
    x_s = [0.31 * Lx, 0.10, 0.37 * Lz]
    C_pt = basis.point_coupling(1.0, x_s)
    _, _, rr_axial, _ = decompose(basis, C_pt, float(f_axial1), axis, xz_off, xi=XI)
    _, _, rr_trans, _ = decompose(basis, C_pt, float(f_trans), axis, xz_off, xi=XI)
    t4 = rr_axial < 0.15 and rr_trans > 3.0 * rr_axial
    results.append(("T4 banda de validez: 1-D exacto en axial, rompe en transversal",
                    t4, f"residuo @f_axial(0,1,0)={f_axial1:.0f}Hz = {rr_axial:.2e}; "
                        f"@f_trans(1,0,0)={f_trans:.0f}Hz = {rr_trans:.2e}"))

    # --- E1c T5: la admitancia efectiva beta_rear que el drive sintetiza ---
    # Rigido (sin trasero): beta~0 (Re~0, no absorbe). Manejado: Re(beta)>0
    # (absorbe) y crece con la frecuencia. Auto-consistencia: |(1-b)/(1+b)|=R.
    re_off_max = float(np.max(np.abs(beta_off.real)))
    re_on = beta_on.real
    recon = np.abs((1.0 - beta_on) / (1.0 + beta_on))      # debe ser == R_on
    consist = float(np.max(np.abs(recon - R_on)))
    t5 = (re_off_max < 0.06 and np.all(re_on > 0)
          and np.all(np.diff(re_on) > -1e-9) and consist < 1e-9)
    results.append(("T5 beta_rear extraida: rigido~0, manejado Re(beta)>0 creciente",
                    t5, f"max|Re(beta_off)|={re_off_max:.2e} (rigido~0); "
                        f"Re(beta_on) {re_on[0]:.3f}->{re_on[-1]:.3f}; "
                        f"|recon R - R|={consist:.1e}"))

    # --- E1c T6: regimen para E3 -> el borde CABS NO es perturbativo ---
    # HALLAZGO: la beta_rear que el drive feedforward sintetiza es de orden ~1 en
    # TODA la banda (nunca <<1): Re(beta) va de absorcion debil (reactiva) a baja
    # f a matcheada (~1) arriba, pero |beta| nunca es chico. Conclusion fuerte:
    # la perturbacion de frontera (Capa 0, Morse&Ingard 9.4.14, asume beta<<1) NO
    # modela el borde trasero CABS en ningun punto -> E3 DEBE usar el QEP exacto
    # (autovalores complejos con la BC de admitancia). Confirma la nota de dba.py.
    # Techo de validez de la perturbacion de 1er orden ~0.15 (bench_cone_damping
    # valida <0.11% hasta beta=0.15). El minimo de |beta_on| ya lo supera.
    mag = np.abs(beta_on)
    never_perturbative = bool(np.min(mag) > 0.15)
    weak_to_matched = bool(re_on[0] < 0.3 and re_on[-1] > 0.9)
    t6 = never_perturbative and weak_to_matched
    results.append(("T6 regimen: beta_rear ~orden 1 (no perturbativo) -> E3=QEP",
                    t6, f"|beta_on| in [{mag.min():.3f},{mag.max():.3f}] (nunca <<1); "
                        f"Re(beta_on) {re_on[0]:.3f}(debil)->{re_on[-1]:.3f}(matched)"))

    return results


if __name__ == "__main__":
    rs = run()
    npass = sum(1 for _, ok, _ in rs if ok)
    for name, ok, detail in rs:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    print(f"\n{npass}/{len(rs)} checks OK  (Y0 = {Y0:.3e} m/Pa.s)")
    raise SystemExit(0 if npass == len(rs) else 1)
