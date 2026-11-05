"""bench_range_gate.py — Gates de validez de rango de los modelos empiricos (v2.93).

Cierra el MENOR de la auditoria (Komatsu/slit/db/miki sin aviso fuera de regimen).
El gate NO bloquea: avisa (misma decision que el dominio no-estanco de v2.72). Son
funciones PURAS, testeables headless.

  G1. db/miki fuera de 0.01<X<1 (X=rho0 f/sigma) avisan; adentro NO.
  G2. komatsu fuera de f/sigma in [0.002,0.83] avisa; adentro NO.
  G3. modelo fisico (jca) o desconocido -> sin gate (None).
  G4. facing (perforado/ranurado) arriba de c/(2*paso) avisa; en banda modal NO.
  G5. SurfaceImpedance.range_warning cablea la metadata de los constructores;
      resistive/rigid (no empiricos) -> [] (sin aviso).

Correr:  python bench_range_gate.py
"""
import numpy as np
import impedance as imp

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


print("G1: db/miki — rango X=rho0 f/sigma in [0.01, 1]")
# sigma=20000: en banda modal grave X=1.21*f/2e4 es ~0.001-0.012 -> casi todo DEBAJO.
w_low = imp.porous_range_warning("miki", np.linspace(20, 200, 40), 20000.0)
check("miki en banda grave (sigma 20k) avisa (X<0.01)", w_low is not None
      and "por debajo" in w_low, (w_low or "None")[:60])
# Banda media donde X cae adentro: f tal que X in [0.05,0.5] -> f = X*sigma/rho0.
f_mid = np.array([0.05, 0.1, 0.3, 0.5]) * 20000.0 / imp.RHO0   # ~826..8264 Hz
check("miki en rango (X in 0.05..0.5) NO avisa",
      imp.porous_range_warning("miki", f_mid, 20000.0) is None,
      f"X={imp.RHO0*f_mid/20000.0}")
# X>1: f muy alto.
w_hi = imp.porous_range_warning("db", np.array([25000.0, 30000.0]), 20000.0)
check("db con X>1 avisa (por encima)", w_hi is not None and "por encima" in w_hi,
      (w_hi or "None")[:50])

print("\nG2: komatsu — rango f/sigma in [0.002, 0.83] m^3/kg")
# sigma=20000: f/sigma en 20-200 Hz = 0.001-0.01 -> parte DEBAJO de 0.002.
w_k = imp.porous_range_warning("komatsu", np.linspace(20, 200, 40), 20000.0)
check("komatsu con f/sigma<0.002 avisa", w_k is not None, (w_k or "None")[:60])
# f/sigma adentro: f=0.01*sigma..0.5*sigma -> 200..10000 Hz.
f_in = np.array([0.01, 0.1, 0.5]) * 20000.0
check("komatsu en rango (f/sigma 0.01..0.5) NO avisa",
      imp.porous_range_warning("komatsu", f_in, 20000.0) is None,
      f"f/sigma={f_in/20000.0}")

print("\nG3: modelo fisico/desconocido -> sin gate")
check("jca (fisico) -> None", imp.porous_range_warning("jca", [50, 100], 20000.0) is None)
check("modelo desconocido -> None", imp.porous_range_warning("xyz", [50], 20000.0) is None)
check("sigma<=0 -> None", imp.porous_range_warning("miki", [50], 0.0) is None)

print("\nG4: facing — periodicidad arriba de c/(2*paso)")
# perforado d=2mm ratio=2% -> paso~12.5mm -> f_lim~13.7kHz.
w_fac_hi = imp.facing_range_warning("perforado", np.array([14000.0, 18000.0]), 0.0125)
w_fac_lo = imp.facing_range_warning("perforado", np.linspace(20, 200, 20), 0.0125)
check("facing arriba de f_lim avisa", w_fac_hi is not None, (w_fac_hi or "None")[:55])
check("facing en banda modal NO avisa", w_fac_lo is None)
check("paso None/<=0 -> None", imp.facing_range_warning("x", [100], 0.0) is None)

print("\nG5: SurfaceImpedance.range_warning (metadata de constructores)")
f_modal = np.linspace(20, 200, 40)
f_wide = np.array([50.0, 200.0, 2000.0, 16000.0])
# poroso de lana en banda modal -> avisa (X bajo).
si_por = imp.porous(sigma=20000.0, thickness=0.05, model="miki")
check("porous() avisa en banda modal (X<0.01)",
      len(si_por.range_warning(f_modal)) >= 1,
      f"{len(si_por.range_warning(f_modal))} avisos")
# perforado: en banda modal sin aviso; con 16 kHz avisa.
si_perf = imp.perforated(thickness=0.005, hole_diam=0.002, ratio=0.02, cavity_depth=0.1)
check("perforated() sin aviso en banda modal",
      si_perf.range_warning(f_modal) == [])
check("perforated() avisa incluyendo 16 kHz",
      any("facing" in m for m in si_perf.range_warning(f_wide)),
      f"{si_perf.range_warning(f_wide)}")
# ranurado: idem.
si_slit = imp.slit_panel(thickness=0.005, slit_width=0.002, ratio=0.02, cavity_depth=0.1)
check("slit_panel() avisa incluyendo 16 kHz",
      any("facing" in m for m in si_slit.range_warning(f_wide)))
# no empiricos -> sin metadata -> []
check("resistive() sin gate ([])", imp.resistive(0.1).range_warning(f_wide) == [])
check("rigid() sin gate ([])", imp.rigid().range_warning(f_wide) == [])

print()
n_ok = sum(1 for _n, c, _d in results if c)
print(f"{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
