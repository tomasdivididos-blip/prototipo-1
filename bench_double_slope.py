"""bench_double_slope.py - Oraculos del detector de doble pendiente (A34).

A34 (Rose/BBC R&D §3.2): el decaimiento de un control room NO debe tener doble
pendiente (el RT tardio −20…−35 dB no debe diferir del temprano −5…−20 dB). Una
doble pendiente delata volumenes acoplados o amortiguamiento modal muy desparejo.

Se valida `modal_decay.double_slope` con IRs SINTETICOS donde la respuesta es
conocida por construccion (sin FEM, para aislar el detector):

  1. UNA sola tasa (un exponencial): ratio T_late/T_early ~ 1 -> is_double False.
  2. DOS poblaciones (rapida + lenta): la cola se quiebra -> ratio >> 1 -> is_double True.
  3. Monotonia: cuanto mas separadas las dos tasas, mayor el ratio.
  4. No evaluable: rango dinamico corto (< −35 dB) -> is_double None.

Correr:  python bench_double_slope.py
"""

import numpy as np

import modal_decay as md

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def ir_single(d, w=2 * np.pi * 60, fs=2000.0, dur=4.0):
    """IR de una sola tasa: exp(-d t) cos(w t). Energia ~ exp(-2d t), T60=6.908/d."""
    t = np.arange(int(fs * dur)) / fs
    return np.exp(-d * t) * np.cos(w * t), fs


def ir_double(d_fast, d_slow, a_slow=0.025, fs=2000.0, dur=7.0):
    """IR de dos poblaciones: una cresta rapida + una lenta de menor amplitud, con
    la amplitud lenta elegida para que el CRUCE de energias caiga DENTRO de la
    ventana −5…−35 dB (si no, la rapida se apaga antes de −5 dB y se ve una sola
    tasa). El decaimiento temprano lo marca la rapida; el tardio, la lenta."""
    t = np.arange(int(fs * dur)) / fs
    fast = np.exp(-d_fast * t) * np.cos(2 * np.pi * 55 * t)
    slow = a_slow * np.exp(-d_slow * t) * np.cos(2 * np.pi * 70 * t)
    return fast + slow, fs


# ---------------------------------------------------------------------------
print("1. una sola tasa -> NO doble pendiente (ratio ~ 1)")
ir, fs = ir_single(d=3.0)
r = md.double_slope(ir, fs)
check("ratio ~ 1 (|ratio-1| < 0.15)", r["is_double"] is False,
      f"T_early={r['T_early']:.2f}s T_late={r['T_late']:.2f}s ratio={r['ratio']:.3f}")

print("\n2. dos poblaciones (rapida + lenta) -> DOBLE pendiente")
ir, fs = ir_double(d_fast=20.0, d_slow=1.2, a_slow=0.025)
r2 = md.double_slope(ir, fs)
check("detecta doble pendiente (is_double True)", r2["is_double"] is True,
      f"T_early={r2['T_early']:.2f}s T_late={r2['T_late']:.2f}s ratio={r2['ratio']:.3f}")
check("la cola es claramente mas lenta (T_late > 1.5 T_early)",
      np.isfinite(r2["T_late"]) and r2["T_late"] > 1.5 * r2["T_early"],
      f"{r2['T_late']:.2f} > 1.5 x {r2['T_early']:.2f}")
# El tramo tardio RECUPERA la tasa lenta: T60_lento = 6.908/d_slow = 5.76 s.
check("el tramo tardio recupera la tasa lenta (T_late ~ 6.908/d_slow, <30%)",
      abs(r2["T_late"] - 6.908 / 1.2) / (6.908 / 1.2) < 0.30,
      f"T_late={r2['T_late']:.2f}s vs 6.908/1.2={6.908/1.2:.2f}s")

print("\n3. una cola mas lenta -> tramo tardio mas largo (monotonia en la tasa lenta)")
r_a = md.double_slope(*ir_double(d_fast=20.0, d_slow=2.0, a_slow=0.025))
r_b = md.double_slope(*ir_double(d_fast=20.0, d_slow=1.0, a_slow=0.025))
check("T_late(d_slow=1.0) > T_late(d_slow=2.0)",
      np.isfinite(r_b["T_late"]) and np.isfinite(r_a["T_late"])
      and r_b["T_late"] > r_a["T_late"],
      f"T_late(1.0)={r_b['T_late']:.2f}s > T_late(2.0)={r_a['T_late']:.2f}s")

print("\n4. rango dinamico corto (< -35 dB) -> no evaluable (None)")
# IR muy corto: se apaga antes de llegar a -35 dB.
t = np.arange(int(2000 * 0.05)) / 2000.0
ir_short = np.exp(-3.0 * t) * np.cos(2 * np.pi * 60 * t)
r4 = md.double_slope(ir_short, 2000.0)
check("is_double None cuando no llega a -35 dB", r4["is_double"] is None,
      f"dyn={r4['dyn_db']:.1f} dB")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
