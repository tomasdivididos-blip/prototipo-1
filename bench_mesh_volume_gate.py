"""
bench_mesh_volume_gate.py
=========================

Oraculo del GATE DE PLAUSIBILIDAD DE VOLUMEN (bug 2 del auditor): mesh_router
._check_mesh_volume debe RECHAZAR (MeshVolumeError) un tet-mesh cuyo volumen se
aparta mas que _VOLUME_GATE_TOL del volumen encerrado por la superficie de
entrada, PERO solo cuando la superficie de referencia es confiable (watertight).
Reproduce el caso que el auditor dejo marcado: la reparametrizacion de gmsh
completa sin excepcion pero con el volumen ~21% incorrecto, y antes pasaba en
silencio.

Falsable, autocontenido (caja sintetica). El gate solo lee info['volume'], asi
que los nodes/tets pueden ser dummy: lo que importa es la referencia de superficie.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_mesh_volume_gate.py
"""

from __future__ import annotations

import numpy as np
import trimesh as tm

import mesh_router as mr

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


def _box_surface(extents=(5.0, 4.0, 3.0)):
    """Caja ESTANCA (watertight). Volumen = prod(extents)."""
    b = tm.creation.box(extents=extents)
    return (np.asarray(b.vertices, float), np.asarray(b.faces, int),
            float(np.prod(extents)))


def _open_box_surface(extents=(5.0, 4.0, 3.0)):
    """Caja con una cara removida -> NO watertight (referencia no confiable)."""
    v, f, _ = _box_surface(extents)
    return v, f[:-2], float(np.prod(extents))      # quita 2 tris (una cara)


def test_rejects_bad_volume():
    print("T1  referencia watertight + volumen 21% desviado -> RECHAZA")
    v, f, vref = _box_surface()
    info = {"volume": vref * 1.21}                  # reparam que inflo el volumen
    raised = False
    try:
        mr._check_mesh_volume(None, None, info, v, f, progress=None)
    except mr.MeshVolumeError:
        raised = True
    check("lanza MeshVolumeError", raised,
          f"err={info.get('volume_error', float('nan'))*100:.1f}%")
    check("anota volume_ref y volume_error", "volume_ref" in info and "volume_error" in info,
          f"ref={info.get('volume_ref'):.2f}, err={info.get('volume_error'):.3f}")


def test_passes_good_volume():
    print("\nT2  referencia watertight + volumen <5% -> PASA")
    v, f, vref = _box_surface()
    info = {"volume": vref * 1.02}                  # dentro de tolerancia
    raised = False
    try:
        mr._check_mesh_volume(None, None, info, v, f, progress=None)
    except mr.MeshVolumeError:
        raised = True
    check("NO lanza", not raised)
    check("volume_error ~ 2%", abs(info.get("volume_error", 0) - 0.02) < 1e-6,
          f"err={info.get('volume_error'):.4f}")


def test_skips_untrustworthy_ref():
    print("\nT3  referencia NO watertight -> NO rechaza (solo registra)")
    v, f, vref = _open_box_surface()
    info = {"volume": vref * 1.50}                  # error enorme a proposito
    raised = False
    try:
        mr._check_mesh_volume(None, None, info, v, f, progress=None)
    except mr.MeshVolumeError:
        raised = True
    # trimesh debe ver la malla abierta como NO estanca.
    not_wt = not bool(tm.Trimesh(vertices=v, faces=f, process=False).is_watertight)
    check("la referencia abierta NO es watertight", not_wt)
    check("NO lanza pese al error grande", not raised)
    check("igual registra volume_error (diagnostico)", "volume_error" in info,
          f"err={info.get('volume_error', float('nan'))*100:.0f}%")


def main():
    print("=" * 68)
    print("bench_mesh_volume_gate.py  —  gate de plausibilidad de volumen (bug 2)")
    print("=" * 68)
    test_rejects_bad_volume()
    test_passes_good_volume()
    test_skips_untrustworthy_ref()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
