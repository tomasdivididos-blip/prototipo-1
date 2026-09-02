"""
bench_sink.py
=============

Oraculos de la Fase S5 (sink / DBA-CABS). Ver `plan_modelo_fuente.md`.
Valida contra el criterio de Santillan (JASA 2001) / Nielsen & Celestinos (CABS):

  T1  cancelacion polo-cero: |C_m(f_m)| ~ 0 para cada axial (mecanismo del DBA)
  T2  supresion de picos: |H_on(f_m)| << |H_off(f_m)| en cada resonancia axial
  T3  colapso de varianza espacial: std(SPL) DBA-on << off (Test 1 del oraculo)
  T4  colapso del decay: T_decay DBA-on << off (Test 3, IR -> delta retardada)
  T5  onda viajera: ripple de |p| a lo largo de y, on << off (campo viajero)

Correr:  /c/Users/aceve/anaconda3/python.exe bench_sink.py
"""

import numpy as np

from source_coupling import RectModalBasis
from dba import (front_only_coupling, dba_coupling_fn, axial_resonance_coupling,
                 impulse_response, schroeder_decay_db)

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


DIMS = (7.8, 4.1, 2.8)     # sala Santillan/CABS
AXIS = 1                    # subs enfrentados a lo largo de y (largo del cuarto)


def _axial_indices(basis):
    return [i for i, m in enumerate(basis.modes)
            if m[0] == 0 and m[2] == 0 and m[1] >= 1]


# ---------------------------------------------------------------------------
# T1 — cancelacion polo-cero
# ---------------------------------------------------------------------------
def t1_pole_zero():
    basis = RectModalBasis(DIMS, fmax=180.0)
    worst = 0.0
    for i in _axial_indices(basis):
        Cm = abs(axial_resonance_coupling(basis, AXIS, i))
        worst = max(worst, Cm)
    check("T1 |C_m(f_m)| ~ 0 en cada axial (DBA)", worst < 1e-9,
          f"peor |C_m(res)|={worst:.2e}")


# ---------------------------------------------------------------------------
# T2 — planitud espectral de la FRF (robusta al receptor, promediada)
# ---------------------------------------------------------------------------
def t2_spectral_flatness():
    # CABS aplana la respuesta en frecuencia: la desviacion de |H(f)| en dB a lo
    # largo de la banda colapsa. Promediado sobre varios receptores (no depende
    # de si un receptor cae en un nodo modal, a diferencia de un test puntual).
    basis = RectModalBasis(DIMS, fmax=180.0)
    C_off = front_only_coupling(basis, AXIS)
    C_on = dba_coupling_fn(basis, AXIS)
    fa = np.linspace(25.0, 175.0, 400)
    recs = [np.array([2.1, 1.3, 0.9]), np.array([6.9, 3.1, 2.1]),
            np.array([3.9, 2.7, 1.4]), np.array([5.2, 0.9, 2.3])]
    ro, rn = [], []
    for xr in recs:
        Ho = 20 * np.log10(np.abs(basis.frf(xr, fa, C_off, xi=0.02)) + 1e-12)
        Hn = 20 * np.log10(np.abs(basis.frf_dispersive(xr, fa, C_on, xi=0.02)) + 1e-12)
        ro.append(np.std(Ho))
        rn.append(np.std(Hn))
    m_off, m_on = np.mean(ro), np.mean(rn)
    check("T2 planitud espectral std|H(f)| DBA-on << off",
          m_on < 0.5 * m_off, f"std off={m_off:.2f} dB  on={m_on:.2f} dB")


# ---------------------------------------------------------------------------
# T3 — colapso de varianza espacial
# ---------------------------------------------------------------------------
def t3_spatial_variance():
    basis = RectModalBasis(DIMS, fmax=180.0)
    # Grilla 3D (evita bordes).
    xs = np.linspace(0.6, DIMS[0] - 0.6, 6)
    ys = np.linspace(0.6, DIMS[1] - 0.6, 8)
    zs = np.linspace(0.5, DIMS[2] - 0.5, 4)
    pts = np.array([[x, y, z] for x in xs for y in ys for z in zs])

    C_off = front_only_coupling(basis, AXIS)
    C_on_fn = dba_coupling_fn(basis, AXIS)

    freqs = np.linspace(30.0, 170.0, 29)
    std_off, std_on = [], []
    for f in freqs:
        p_off = np.abs(basis.pressure_field(pts, f, C_off, xi=0.02))
        p_on = np.abs(basis.pressure_field(pts, f, C_on_fn(f), xi=0.02))
        std_off.append(np.std(20.0 * np.log10(p_off / np.mean(p_off))))
        std_on.append(np.std(20.0 * np.log10(p_on / np.mean(p_on))))
    m_off, m_on = np.mean(std_off), np.mean(std_on)
    check("T3 std(SPL) espacial DBA-on << off (banda)",
          m_on < 0.5 * m_off and m_on < m_off,
          f"std off={m_off:.2f} dB  on={m_on:.2f} dB")


# ---------------------------------------------------------------------------
# T4 — colapso del decay
# ---------------------------------------------------------------------------
def t4_decay_collapse():
    basis = RectModalBasis(DIMS, fmax=200.0)
    xr = np.array([6.9, 2.7, 1.8])
    C_off = front_only_coupling(basis, AXIS)
    C_on = dba_coupling_fn(basis, AXIS)

    t, h_off = impulse_response(basis, xr, C_off, fmax=200.0, xi=0.03)
    _, h_on = impulse_response(basis, xr, C_on, fmax=200.0, xi=0.03)
    sch_off = schroeder_decay_db(h_off)
    sch_on = schroeder_decay_db(h_on)

    def time_to(sch, level_db):
        idx = np.argmax(sch <= level_db)
        return t[idx] if sch[idx] <= level_db else t[-1]

    td_off = time_to(sch_off, -15.0)
    td_on = time_to(sch_on, -15.0)
    check("T4 decay (t a -15 dB) DBA-on << off",
          td_on < 0.5 * td_off,
          f"t_off={td_off*1e3:.1f} ms  t_on={td_on*1e3:.1f} ms")


# ---------------------------------------------------------------------------
# T5 — onda viajera (ripple de |p| a lo largo de y)
# ---------------------------------------------------------------------------
def t5_traveling_wave():
    basis = RectModalBasis(DIMS, fmax=180.0)
    xc, zc = DIMS[0] / 2.0, DIMS[2] / 2.0
    ys = np.linspace(0.4, DIMS[1] - 0.4, 30)
    pts = np.array([[xc, y, zc] for y in ys])

    C_off = front_only_coupling(basis, AXIS)
    C_on_fn = dba_coupling_fn(basis, AXIS)

    freqs = np.linspace(35.0, 150.0, 20)
    rip_off, rip_on = [], []
    for f in freqs:
        p_off = 20*np.log10(np.abs(basis.pressure_field(pts, f, C_off, xi=0.02)))
        p_on = 20*np.log10(np.abs(basis.pressure_field(pts, f, C_on_fn(f), xi=0.02)))
        rip_off.append(np.ptp(p_off))     # peak-to-peak dB a lo largo de y
        rip_on.append(np.ptp(p_on))
    m_off, m_on = np.mean(rip_off), np.mean(rip_on)
    check("T5 ripple |p(y)| DBA-on << off (campo viajero)",
          m_on < 0.5 * m_off, f"ripple off={m_off:.1f} dB  on={m_on:.1f} dB")


if __name__ == "__main__":
    print("bench_sink.py — oraculos Fase S5 (sink / DBA-CABS)\n")
    t1_pole_zero()
    t2_spectral_flatness()
    t3_spatial_variance()
    t4_decay_collapse()
    t5_traveling_wave()
    print(f"\n  {_PASS} OK, {_FAIL} FAIL")
    raise SystemExit(1 if _FAIL else 0)
