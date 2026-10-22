"""
bench_santillan_eq.py
=====================

Oráculo del item 2: EQ GLOBAL de banda ancha de Santillán (JASA 110(4), 2001,
§IV, ec. 10, Fig. 4): diseño de FIR por fuente con delay de modelado que ecualiza
TODA la zona, no un punto.

Chequeos falsables:
  T1  E_LS(f) crece con la frecuencia (Fig. 3 del paper) y es chico a graves.
  T2  donde E_LS<0.3, la zona corregida es más plana que el array frontal solo
      (criterio ±3 dB del paper, §III-E).
  T3  los FIR son causales: la energía antes del delay de modelado es despreciable.
  T4  límite 1 sensor -> EQ puntual: E_LS ~ 0 en ese punto (LS exacto).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_santillan_eq.py
"""

from __future__ import annotations

import numpy as np

from source_coupling import RectModalBasis
import dba

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def _setup(fmax=150.0, n=4, c=343.0):
    dims = (3.0, 5.0, 2.7); axis = 1
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    basis = RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)
    front = dba.piston_wall_grid(basis, axis, "min", n, n)
    rear = dba.piston_wall_grid(basis, axis, "max", n, n)
    zone = dba._zone_grid(dims, axis)
    return basis, front + rear, front, zone, axis, dims, c


def test_els_vs_freq():
    print("T1  E_LS: bajo en la banda útil; ALTO bajo el 1er axial (no hay onda "
          "viajera posible debajo del fundamental)")
    basis, pistons, front, zone, axis, dims, c = _setup()
    f1 = c / (2.0 * dims[axis])                   # 1er axial sobre el eje (~34 Hz)
    freqs = np.linspace(0.0, 150.0, 129)
    res = dba.santillan_global_eq(basis, pistons, zone, freqs, axis=axis, reg=0.01)
    E = res["E_ls"]
    valid = (freqs >= f1 + 10) & (freqs <= 150)
    below = (freqs >= 20) & (freqs < f1)
    check("E_LS bajo en la banda útil (> 1er axial)",
          float(np.median(E[valid])) < 0.3,
          f"median E_LS={np.median(E[valid]):.3f} (f1={f1:.1f} Hz)")
    check("E_LS mayor por debajo del 1er axial (no se puede onda viajera)",
          float(np.mean(E[below])) > float(np.median(E[valid])),
          f"below {np.mean(E[below]):.3f} > útil {np.median(E[valid]):.3f}")


def test_zone_flatter():
    print("\nT2  la zona corregida (EQ global) es más plana que el array frontal solo")
    basis, pistons, front, zone, axis, dims, c = _setup()
    freqs = np.linspace(0.0, 150.0, 129)
    res = dba.santillan_global_eq(basis, pistons, zone, freqs, axis=axis,
                                  reg=0.01, zone=zone)
    # Front-only: L_bar(f) de la zona con solo el array frontal.
    C_front = dba.coupling_matrix(basis, front).sum(axis=1)
    Lbar0 = []
    for f in freqs:
        if f <= 0:
            continue
        p = np.abs(basis.pressure_field(zone, float(f), C_front, xi=0.03))
        Lbar0.append(20.0 * np.log10(np.mean(p) + 1e-30))
    flat_front = float(np.std(Lbar0))
    check("EQ global más plano que frontal solo",
          res["zone_flat"] < flat_front,
          f"frontal {flat_front:.2f} dB -> EQ {res['zone_flat']:.2f} dB")


def test_causal_fir():
    print("\nT3  FIR causales: energía antes del delay de modelado despreciable")
    basis, pistons, front, zone, axis, dims, c = _setup()
    freqs = np.linspace(0.0, 150.0, 257)
    res = dba.santillan_global_eq(basis, pistons, zone, freqs, axis=axis, reg=0.01)
    h = res["filters"]; fs = res["fs"]; md = res["model_delay"]
    n0 = int(0.5 * md * fs)                       # media ventana del delay
    e_pre = float(np.sum(h[:, :n0] ** 2))
    e_tot = float(np.sum(h ** 2)) + 1e-30
    check("energía pre-delay < 5% del total", e_pre / e_tot < 0.05,
          f"pre/tot={e_pre/e_tot*100:.2f}%  (md={md*1e3:.1f} ms)")


def test_single_sensor():
    print("\nT4  límite 1 sensor -> EQ puntual (E_LS ~ 0 en ese punto)")
    basis, pistons, front, zone, axis, dims, c = _setup()
    sensor = np.array([[dims[0] / 2, dims[1] / 2, dims[2] / 2]])
    freqs = np.linspace(30.0, 120.0, 40)
    res = dba.santillan_global_eq(basis, pistons, sensor, freqs, axis=axis, reg=0.0)
    check("E_LS ~ 0 en 1 punto (sistema sobre-determinado)",
          float(np.nanmedian(res["E_ls"])) < 1e-6,
          f"median E_LS={np.nanmedian(res['E_ls']):.2e}")


def main():
    print("=" * 70)
    print("bench_santillan_eq.py  —  EQ global de banda ancha (item 2)")
    print("=" * 70)
    test_els_vs_freq()
    test_zone_flatter()
    test_causal_fir()
    test_single_sensor()
    print("-" * 70)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
