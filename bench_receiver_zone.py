"""
bench_receiver_zone.py
======================

Oráculo del item 3 (multi-receptor): `evaluate_cabs`/`cabs_optimize` aceptan un
`zone_box` explícito (coords caja) = los RECEPTORES ACTIVOS elegidos por el
usuario, en vez de la zona fina default. Chequeos falsables:

  T1  zone_box=None (default) corre y da métricas finitas (sin regresión).
  T2  zone_box de 1 punto -> varianza espacial (SD) = 0 (std sobre 1 posición),
      mientras que la zona default da SD > 0. Prueba que SÍ se usan los puntos.
  T3  zone_box de varios puntos -> SD finita; distinto de la zona default.
  T4  cabs_optimize acepta zone_box sin romper (corre y devuelve dict).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_receiver_zone.py
"""

from __future__ import annotations

import numpy as np

import dba_evaluate as dev
import cabs_optimize as copt
from sources import OmniSource

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


def _subs(dims):
    Lx, Ly, Lz = dims
    return [OmniSource(position=(1.0, 0.3, Lz / 2), Q=1e-3 + 0j, source_type="subwoofer"),
            OmniSource(position=(Lx - 1.0, 0.3, Lz / 2), Q=1e-3 + 0j, source_type="subwoofer"),
            OmniSource(position=(1.0, Ly - 0.3, Lz / 2), Q=1e-3 + 0j, source_type="subwoofer"),
            OmniSource(position=(Lx - 1.0, Ly - 0.3, Lz / 2), Q=1e-3 + 0j, source_type="subwoofer")]


def main():
    print("=" * 68)
    print("bench_receiver_zone.py  —  optimizar/evaluar sobre receptores (item 3)")
    print("=" * 68)
    dims = (4.0, 6.0, 3.0); origin = (0.0, 0.0, 0.0)
    rec = (2.0, 3.0, 1.5)
    subs = _subs(dims)

    print("T1  zone_box=None (default) corre y da métricas finitas")
    r0 = dev.evaluate_cabs(subs, dims, rec, origin=origin, criterion="flat",
                           fmax=180.0)
    check("flat/spatial finitos", np.isfinite(r0["flat_real"])
          and np.isfinite(r0["spatial_real"]),
          f"flat={r0['flat_real']:.2f} SD={r0['spatial_real']:.2f}")

    print("\nT2  zone_box de 1 punto -> SD = 0 (std sobre 1 posición)")
    one = np.array([[2.0, 3.0, 1.5]])          # coords caja (origin=0)
    r1 = dev.evaluate_cabs(subs, dims, rec, origin=origin, criterion="flat",
                           fmax=180.0, zone_box=one)
    check("SD ~ 0 con 1 receptor", r1["spatial_real"] < 1e-9,
          f"SD={r1['spatial_real']:.2e}")
    check("la zona default tenía SD > 0 (se usaron los puntos)",
          r0["spatial_real"] > 1e-3, f"SD_default={r0['spatial_real']:.3f}")

    print("\nT3  zone_box de varios puntos -> SD finita y distinta de la default")
    pts = np.array([[1.0, 1.5, 1.2], [3.0, 1.5, 1.2],
                    [1.0, 4.5, 1.8], [3.0, 4.5, 1.8]])
    r3 = dev.evaluate_cabs(subs, dims, rec, origin=origin, criterion="flat",
                           fmax=180.0, zone_box=pts)
    check("SD finita", np.isfinite(r3["spatial_real"]),
          f"SD={r3['spatial_real']:.2f}")
    check("distinta de la zona default",
          abs(r3["spatial_real"] - r0["spatial_real"]) > 1e-6,
          f"{r3['spatial_real']:.3f} vs {r0['spatial_real']:.3f}")

    print("\nT4  cabs_optimize acepta zone_box (corre y devuelve dict)")
    subs_free = _subs(dims)
    subs_free[0].free_vars = frozenset({"delay"})
    out = copt.optimize_cabs(subs_free, dims, rec, origin=origin,
                             criterion="flat", zone_box=pts, maxiter=3,
                             fmax=150.0)
    check("devuelve dict con métricas", isinstance(out, dict)
          and "metrics_after" in out or "cost_after" in out or len(out) > 0,
          f"keys={list(out)[:4]}")

    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
