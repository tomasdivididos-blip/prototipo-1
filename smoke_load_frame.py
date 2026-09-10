"""
smoke_load_frame.py
===================

Smoke (puro numpy, sin Qt) del arreglo de carga de .room con CAD re-anclado
(9 Sep 2026). Valida la MATEMATICA exacta que aplica `MainWindow.load_from_path`:

  - Al cargar, el CAD se re-ancla al `origin_mode` guardado: verts_new = verts - off,
    con off = [origin_offset(verts, mode)_xy, zmin].
  - Si off != 0 (frame guardado del CAD != origin_mode guardado, o archivo legacy),
    el recinto se MUEVE -off. Los objetos (fuentes/muebles/receptor) se restauran en
    el frame viejo, asi que hay que correrlos el MISMO -off para que sigan al
    recinto (si no, al reabrir el recinto queda corrido respecto de los objetos).

Se valida con un caso inconsistente (CAD centrado + origin_mode="corner"):
  1. off != 0 (el CAD se re-ancla a esquina al cargar).
  2. Sin correr los objetos: la fuente queda FUERA del CAD re-anclado (el bug).
  3. Corriendo los objetos por -off: la fuente queda DENTRO (el fix).
  4. Caso consistente (origin_mode="auto", CAD ya centrado): off == 0 -> no se mueve
     nada (no-regresion: los archivos normales, como aula.room, reabren idem).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe smoke_load_frame.py
"""

from __future__ import annotations

import numpy as np

from geometry import origin_offset
from acoustic_mesh import points_inside_surface

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


def _box(ex=(8.0, 5.0, 2.6)):
    """Caja centrada en XY, apoyada en z=0 (como un CAD recien importado)."""
    import trimesh as tm
    m = tm.creation.box(extents=ex)
    v = np.asarray(m.vertices, float)
    v[:, 2] -= v[:, 2].min()        # piso a z=0
    return v, np.asarray(m.faces, int)


def _load_reanchor(verts, origin_mode):
    """Replica EXACTAMENTE el calculo de offset de load_from_path."""
    off_xy = origin_offset(verts, "center" if origin_mode == "auto" else origin_mode)
    off = np.array([off_xy[0], off_xy[1], float(verts[:, 2].min())])
    verts_new = verts - off if float(np.linalg.norm(off)) > 1e-9 else verts
    return verts_new, off


def _inside(p, v, t):
    return bool(points_inside_surface(np.asarray(p, float).reshape(1, 3), v, t)[0])


def test_inconsistent_file_fix():
    print("T1  CAD centrado + origin_mode='corner' (archivo inconsistente)")
    v, t = _box()
    # Objetos guardados en el frame CENTRADO (consistentes con el CAD centrado).
    # Interior claro del recinto centrado [-4,4]x[-2.5,2.5]; tras re-anclar a
    # esquina ([0,8]x[0,5]) queda netamente afuera si no se corre.
    src_saved = np.array([-3.5, -2.0, 1.3])
    v_new, off = _load_reanchor(v, "corner")
    check("off != 0 (el CAD se re-ancla a esquina al cargar)",
          float(np.linalg.norm(off)) > 1e-9, f"off={np.round(off,2)}")
    # CONTRAPRUEBA: sin correr los objetos, la fuente queda fuera del CAD re-anclado.
    check("CONTRAPRUEBA: sin correr objetos la fuente queda FUERA",
          not _inside(src_saved, v_new, t))
    # FIX: correr los objetos por -off.
    src_fixed = src_saved - off
    check("con el fix (objetos -off) la fuente queda DENTRO",
          _inside(src_fixed, v_new, t),
          f"src={np.round(src_fixed,2)}")


def test_consistent_file_no_shift():
    print("\nT2  origin_mode='auto' + CAD ya centrado (archivo normal): off==0")
    v, _t = _box()
    _v_new, off = _load_reanchor(v, "auto")
    check("off == 0 (no se mueve nada -> no regresion, reabre idem)",
          float(np.linalg.norm(off)) < 1e-9, f"off={np.round(off,4)}")


def test_consistent_corner_no_shift():
    print("\nT3  origin_mode='corner' + CAD ya en esquina (consistente): off==0")
    v, _t = _box()
    v_corner = v - origin_offset(v, "corner")        # ya anclado a esquina
    _v_new, off = _load_reanchor(v_corner, "corner")
    check("off == 0 (CAD ya en el frame guardado -> no se toca)",
          float(np.linalg.norm(off)) < 1e-9, f"off={np.round(off,4)}")


def main():
    print("=" * 64)
    print("smoke_load_frame.py  —  re-anclaje de CAD al cargar (objetos lo siguen)")
    print("=" * 64)
    test_inconsistent_file_fix()
    test_consistent_file_no_shift()
    test_consistent_corner_no_shift()
    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
