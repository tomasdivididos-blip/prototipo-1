"""
bench_shape_perturbation.py
===========================

Oraculos de `shape_perturbation` (ruta d del plan §8: corrimiento modal por
perturbacion de forma, Slater / Morse & Ingard §9.4).

Verdad de campo EXACTA sin FEM: quitar una LOSA fina en un extremo de un eje es lo
mismo que una caja mas chica en ese eje, cuya frecuencia modal analitica se conoce.

  - Modo AXIAL en el eje acortado: rel exacto = δ/(L−δ) (la perturbacion 1er orden
    debe coincidir dentro de ~15%).
  - Modo TANGENCIAL (no depende del eje acortado): rel ≈ 0.
  - SIGNO: quitar en un antinodo de PRESION (pared rigida) SUBE f (rel>0); quitar en
    un antinodo de VELOCIDAD la BAJA (rel<0).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_shape_perturbation.py
"""

from __future__ import annotations

import numpy as np

import shape_perturbation as sp
from sources import C0

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


def _rel_of(res, n):
    for d in res:
        if d["n"] == n:
            return d["rel_shift"]
    return None


def main():
    print("=" * 64)
    print("bench_shape_perturbation  (perturbacion de forma vs caja exacta)")
    print("=" * 64)

    dims = (5.0, 4.0, 3.0)
    Lx = dims[0]
    delta = 0.15                       # losa fina en x = Lx (pared rigida)
    # recinto real = caja mas chica en X: x <= Lx - delta
    inside = lambda P: np.asarray(P)[:, 0] <= (Lx - delta)
    # grid_n fino: la losa (0.15 m) necesita celdas < ~0.08 m para resolverse en la
    # cuadratura (con grilla gruesa el error es de INTEGRACION, no de la formula).
    res = sp.perturbed_freqs(dims, inside, n_modes=25, grid_n=64)

    rel_exact = delta / (Lx - delta)   # = 0.15/4.85 ≈ 0.0309
    print(f"  losa δ={delta} en X (Lx={Lx}); rel EXACTO axial-X = {rel_exact:.4f}")

    # --- 1. modos AXIALES en X: rel ~ δ/(L−δ) -----------------------------------
    for n in ((1, 0, 0), (2, 0, 0)):
        r = _rel_of(res, n)
        check(f"axial-X {n}: rel ≈ δ/(L−δ) (dentro de 15%)",
              r is not None and abs(r - rel_exact) <= 0.15 * rel_exact,
              f"pert={r:.4f} exacto={rel_exact:.4f}")

    # --- 2. modos TANGENCIALES (no dependen de X): rel ≈ 0 ----------------------
    for n in ((0, 1, 0), (0, 0, 1), (0, 1, 1)):
        r = _rel_of(res, n)
        check(f"tangencial {n}: rel ≈ 0 (acortar X no lo mueve)",
              r is not None and abs(r) < 0.1 * rel_exact,
              f"rel={r:.5f}")

    # --- 3. SIGNO presion: quitar en pared rigida (antinodo de p) SUBE f ---------
    check("quitar en antinodo de PRESION sube f (rel>0) para el axial-X",
          _rel_of(res, (1, 0, 0)) > 0, f"rel={_rel_of(res,(1,0,0)):.4f}")

    # --- 4. SIGNO velocidad: losa en el MEDIO (antinodo de velocidad de (1,0,0)) --
    # para el modo (1,0,0), x=Lx/2 es nodo de presion / antinodo de velocidad.
    mid = Lx / 2.0
    inside_mid = lambda P: np.abs(np.asarray(P)[:, 0] - mid) > (delta / 2.0)
    res_mid = sp.perturbed_freqs(dims, inside_mid, n_modes=4, grid_n=48)
    check("quitar en antinodo de VELOCIDAD baja f (rel<0) para el axial-X (1,0,0)",
          _rel_of(res_mid, (1, 0, 0)) < 0,
          f"rel={_rel_of(res_mid,(1,0,0)):.4f}")

    # --- 5. convergencia: grilla mas fina -> mas cerca del exacto ----------------
    r_coarse = _rel_of(sp.perturbed_freqs(dims, inside, n_modes=4, grid_n=24),
                       (1, 0, 0))
    r_fine = _rel_of(sp.perturbed_freqs(dims, inside, n_modes=4, grid_n=64),
                     (1, 0, 0))
    check("grilla mas fina acerca (o iguala) al valor exacto",
          abs(r_fine - rel_exact) <= abs(r_coarse - rel_exact) + 1e-4,
          f"coarse={r_coarse:.4f} fine={r_fine:.4f} exacto={rel_exact:.4f}")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return _N_FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
