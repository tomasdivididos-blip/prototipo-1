"""
bench_domain_quantify.py
========================

Oraculo de la CUANTIFICACION DEL ERROR DE DOMINIO (bug 3 del auditor):
acoustic_mesh.domain_fill_estimate debe dar un numero que delate cuando un CAD
no estanco hace degenerar el dominio hacia el AABB. Sobre una malla abierta,
points_inside_surface (paridad de rayo 1-dir) clasifica casi toda la caja como
'adentro' -> frac ~ alto y domain_error grande; sobre una caja cerrada el error
es ~0.

Falsable, autocontenido (cajas sinteticas). Headless (no Qt).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_domain_quantify.py
"""

from __future__ import annotations

import numpy as np
import trimesh as tm

import acoustic_mesh as am

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


def test_closed_box_small_error():
    print("T1  caja cerrada (watertight) -> domain_error ~ 0")
    b = tm.creation.box(extents=(5.0, 4.0, 3.0))
    v = np.asarray(b.vertices, float)
    f = np.asarray(b.faces, int)
    res = am.domain_fill_estimate(v, f)
    check("devuelve resultado", res is not None)
    frac, v_dom, v_surf, derr = res
    check("V_surf ~ 60 m3", abs(v_surf - 60.0) < 1e-6, f"V_surf={v_surf:.3f}")
    check("frac ~ 1 (la caja llena su AABB)", frac > 0.98, f"frac={frac:.3f}")
    check("domain_error < 3%", derr < 0.03, f"err={derr*100:.1f}%")


def test_open_box_large_error():
    print("\nT2  caja ABIERTA (no estanca) -> error grande (dominio = AABB)")
    # Caja real = mitad del AABB: una caja chica apoyada en el piso de un AABB
    # que es el doble de alto. Le quitamos la tapa -> no estanca. El recinto real
    # (lo que encierra la superficie por divergencia) es ~la caja chica, pero la
    # paridad de rayos marca casi todo el AABB alto como 'adentro'.
    b = tm.creation.box(extents=(5.0, 4.0, 3.0))
    v = np.asarray(b.vertices, float)
    f = np.asarray(b.faces, int)
    # Estirar el AABB hacia arriba agregando un vertice fantasma alto y una cara
    # suelta (no cierra): sube hi[z] sin encerrar ese volumen.
    ghost = v.max(0) + np.array([0.0, 0.0, 3.0])
    v2 = np.vstack([v, ghost, ghost + [0.1, 0, 0], ghost + [0, 0.1, 0]])
    nf = np.array([[len(v), len(v) + 1, len(v) + 2]])      # triangulo suelto alto
    f_open = np.vstack([f[:-2], nf])                        # ademas quita una cara
    res = am.domain_fill_estimate(v2, f_open)
    check("devuelve resultado", res is not None)
    frac, v_dom, v_surf, derr = res
    not_wt = not bool(tm.Trimesh(vertices=v2, faces=f_open,
                                 process=False).is_watertight)
    check("la malla es NO estanca", not_wt)
    check("domain_error finito y > 10% (delata la degeneracion)",
          np.isfinite(derr) and derr > 0.10, f"err={derr*100:.0f}%")
    check("V_dom > V_surf (dominio inflado hacia el AABB)", v_dom > v_surf,
          f"V_dom={v_dom:.1f} vs V_surf={v_surf:.1f}")


def test_degenerate_guards():
    print("\nT3  guardas: malla vacia / caja aplastada -> None")
    check("malla vacia -> None",
          am.domain_fill_estimate(np.zeros((0, 3)), np.zeros((0, 3), int)) is None)
    # Caja aplastada en z (AABB con volumen ~0).
    flat = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    tri = np.array([[0, 1, 2], [0, 2, 3]], int)
    check("AABB de volumen ~0 -> None",
          am.domain_fill_estimate(flat, tri) is None)


def main():
    print("=" * 68)
    print("bench_domain_quantify.py  —  cuantificacion del error de dominio (bug 3)")
    print("=" * 68)
    test_closed_box_small_error()
    test_open_box_large_error()
    test_degenerate_guards()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
