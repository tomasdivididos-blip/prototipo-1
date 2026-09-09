"""
bench_cabs_criterion.py - selector de criterio CABS/DBA: optimizar y evaluar
============================================================================
concuerdan por construccion (cierra el bug del delay 2x)
-----------------------------------------------------------------------------
Reproduce el caso reportado por el usuario (9 Sep 2026): 4 subs enfrentados
(2 al frente, 2 atras) sobre un eje; al optimizar "fuentes libres" el soft los
acomoda, pero al evaluar decia que el trasero necesitaba OTRO delay (~el doble),
porque el optimizador minimizaba planitud (cae en ~L/2c) y el evaluador exigia el
drive DBA canonico (L/c). Con el selector de criterio, optimizar y evaluar siguen
UN SOLO criterio y concuerdan.

  G1  optimizar con criterion="dba" fija el drive canonico: trasero delay = L/c,
      polaridad invertida (no L/2c).
  G2  evaluar con criterion="dba" la config asi optimizada PASA (rear_drive OK),
      SIN tener que duplicar el delay a mano.
  G3  contraste determinista del bug: una config con delay = L/(2c) (lo que da la
      optimizacion por planitud) FALLA el criterio DBA (rear_drive critico) pero
      PASA el criterio CABS (trasero manejado, rear_drive informativo).
  G4  regresion: un DBA canonico (delay L/c, invertido) PASA en dba y en cabs.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_cabs_criterion.py
"""
from __future__ import annotations

import numpy as np

import cabs_optimize as opt
import dba_evaluate as dev
from sources import OmniSource, C0

_n = _ok = 0


def check(name, cond, detail=""):
    global _n, _ok
    _n += 1
    _ok += 1 if cond else 0
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


DIMS = (5.0, 6.2, 3.0)
AXIS = 1                     # eje largo (Y)
L = DIMS[AXIS]
TAU = L / C0                 # delay DBA canonico
RX = (2.5, 3.1, 1.2)
FMAX = 120.0


def _testigo(free):
    """4 subs enfrentados en Y: 2 al frente (y~0.1), 2 atras (y~L-0.1), spread en X.
    `free` = free_vars de cada sub (lo que el usuario libera)."""
    return [
        OmniSource((1.5, 0.10, 1.0), label="F1", source_type="subwoofer", free_vars=free),
        OmniSource((3.5, 0.10, 1.0), label="F2", source_type="subwoofer", free_vars=free),
        OmniSource((1.5, L - 0.10, 1.0), label="R1", source_type="subwoofer",
                   polarity=-1, free_vars=free),
        OmniSource((3.5, L - 0.10, 1.0), label="R2", source_type="subwoofer",
                   polarity=-1, free_vars=free),
    ]


# ---------------------------------------------------------------------------
print("G1  optimizar criterion='dba' fija el drive canonico (delay L/c, invertido)")
subs = _testigo({"pos", "delay"})           # el usuario libera posicion y delay
r_dba = opt.optimize_cabs(subs, DIMS, RX, axis=AXIS, fmax=FMAX, maxiter=12,
                          criterion="dba")
rears = [s for s in r_dba["optimized"] if s.position[AXIS] > L / 2]
delays = [s.delay_s for s in rears]
pols = [s.polarity for s in rears]
check("G1a trasero con delay = L/c (no L/2c)",
      all(abs(d - TAU) < 1e-9 for d in delays),
      f"delays={[round(d*1e3,1) for d in delays]} ms, L/c={TAU*1e3:.1f}, L/2c={TAU*5e2:.1f}")
check("G1b trasero invertido (polaridad -1)", all(p == -1 for p in pols))


# ---------------------------------------------------------------------------
print("\nG2  evaluar criterion='dba' la config optimizada PASA (sin duplicar a mano)")
e_dba = dev.evaluate_cabs(r_dba["optimized"], DIMS, RX, axis=AXIS, fmax=FMAX,
                          criterion="dba")
drv = [it for it in e_dba["checklist"] if it["key"] == "rear_drive"][0]
check("G2a rear_drive OK", drv["ok"], drv["text"])
check("G2b checklist critico PASA", e_dba["passed"])


# ---------------------------------------------------------------------------
print("\nG3  contraste: delay = L/(2c) FALLA en dba, PASA en cabs")
half = _testigo(frozenset())                # config fija (sin optimizar)
for s in half:
    if s.position[AXIS] > L / 2:            # traseros: el delay 'de planitud'
        s.delay_s = TAU / 2.0
e_half_dba = dev.evaluate_cabs(half, DIMS, RX, axis=AXIS, fmax=FMAX, criterion="dba")
e_half_cabs = dev.evaluate_cabs(half, DIMS, RX, axis=AXIS, fmax=FMAX, criterion="cabs")
drv_dba = [it for it in e_half_dba["checklist"] if it["key"] == "rear_drive"][0]
drv_cabs = [it for it in e_half_cabs["checklist"] if it["key"] == "rear_drive"][0]
check("G3a delay L/2c FALLA el criterio DBA (rear_drive critico no OK)",
      (not drv_dba["ok"]) and drv_dba["critical"] and (not e_half_dba["passed"]))
check("G3b delay L/2c PASA el criterio CABS (rear_drive informativo)",
      (not drv_cabs["critical"]) and e_half_cabs["passed"])


# ---------------------------------------------------------------------------
print("\nG4  regresion: DBA canonico (delay L/c invertido) PASA en dba y en cabs")
canon = _testigo(frozenset())
for s in canon:
    if s.position[AXIS] > L / 2:
        s.delay_s = TAU
e_c_dba = dev.evaluate_cabs(canon, DIMS, RX, axis=AXIS, fmax=FMAX, criterion="dba")
e_c_cabs = dev.evaluate_cabs(canon, DIMS, RX, axis=AXIS, fmax=FMAX, criterion="cabs")
check("G4a DBA canonico PASA en dba", e_c_dba["passed"])
check("G4b DBA canonico PASA en cabs", e_c_cabs["passed"])


print()
print("=" * 70)
print(f" RESULTADO: {_ok}/{_n} checks OK")
print("=" * 70)
raise SystemExit(0 if _ok == _n else 1)
