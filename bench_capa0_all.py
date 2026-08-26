"""
bench_capa0_all.py - suite unificada de Capa 0 (modelado de impedancia)
=======================================================================
Corre en secuencia TODOS los benches de Capa 0 y agrega el conteo. Un unico
comando para regresion completa del modulo de impedancia + perturbacion:

  Etapa 1a/1b/2a  bench_impedance.py            (Z_c/k_c, TMM, JCA, oblicuo, medida)
  Etapa 1c        bench_perturbation_complex.py (beta compleja vs QEP exacto)
  Etapa 2b        bench_extended_reaction.py    (angulo por modo, reaccion extendida)
  Etapa 3         bench_resonant_facings.py     (perforado/MPP/membrana/Helmholtz)
  Etapa 4         bench_capa0_audit.py          (auditoria integral pre-conexion)

Cada bench se corre en su propio proceso (aislado) con el MISMO interprete que
lanza esta suite. Sale con codigo != 0 si alguno falla.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_capa0_all.py
"""
from __future__ import annotations
import os
import re
import sys
import subprocess

BENCHES = [
    ("Etapa 1a/1b/2a  impedancia (Zc/kc, TMM, JCA, oblicuo)", "bench_impedance.py"),
    ("Etapa 1c        perturbacion compleja vs QEP", "bench_perturbation_complex.py"),
    ("Etapa 2b        reaccion extendida (angulo por modo)", "bench_extended_reaction.py"),
    ("Etapa 3         resonantes (perforado/MPP/membrana)", "bench_resonant_facings.py"),
    ("Etapa 4         auditoria integral", "bench_capa0_audit.py"),
    ("Etapa 5a        wiring a la fisica (FRF/corrimiento)", "bench_capa0_wiring.py"),
]

_RES = re.compile(r"RESULTADO:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL")


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")     # los que tocan FEM/Qt
    env.setdefault("PYTHONIOENCODING", "utf-8")

    print("=" * 70)
    print(" SUITE CAPA 0 - modelado de impedancia de superficie")
    print("=" * 70)
    tot_ok = tot_fail = 0
    failed_benches = []
    for label, fname in BENCHES:
        path = os.path.join(here, fname)
        if not os.path.exists(path):
            print(f"  [MISS] {label:52s} {fname} no existe")
            failed_benches.append(fname)
            continue
        p = subprocess.run([sys.executable, path], cwd=here, env=env,
                           capture_output=True, text=True)
        m = None
        for line in reversed(p.stdout.splitlines()):
            m = _RES.search(line)
            if m:
                break
        ok = int(m.group(1)) if m else 0
        fail = int(m.group(2)) if m else -1
        tot_ok += ok
        tot_fail += max(fail, 0)
        if p.returncode != 0 or fail != 0 or m is None:
            failed_benches.append(fname)
            status = "FAIL"
        else:
            status = "OK  "
        cnt = f"{ok} OK, {fail} FAIL" if m else "sin conteo"
        print(f"  [{status}] {label:52s} {cnt}")
        if p.returncode != 0 and m is None:
            # mostrar la cola del error para diagnosticar
            tail = "\n".join((p.stdout + p.stderr).splitlines()[-8:])
            print("        " + tail.replace("\n", "\n        "))

    print("=" * 70)
    print(f" TOTAL CAPA 0: {tot_ok} OK, {tot_fail} FAIL"
          + (f"  |  benches con fallo: {', '.join(failed_benches)}"
             if failed_benches else "  |  TODO VERDE"))
    print("=" * 70)
    return 1 if failed_benches else 0


if __name__ == "__main__":
    raise SystemExit(main())
