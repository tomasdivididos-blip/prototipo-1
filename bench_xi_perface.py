"""
bench_xi_perface.py
===================

Oraculo del criterio A36: xi_n por modo pesado por la forma modal en cada cara
(`face_materials.compute_xi_per_mode_per_face`).

Valida dos propiedades:
  (A) Material UNIFORME -> se reduce a la Sabine global per-cara (no regresiona).
  (B) Tratamiento ASIMETRICO (piso absorbente) -> diferencia los modos y queda
      acotado entre el limite rigido y el absorbente.

Correr:
    PYTHONIOENCODING=utf-8 python bench_xi_perface.py
"""
from __future__ import annotations

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
from material_library import Material, BANDS, compute_xi_per_mode


def _const_material(name, a):
    return Material({"name": name, "alpha": {b: float(a) for b in BANDS}})


def _build_shoebox():
    sv, st, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=2.5)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=15)
    loc = FieldEvaluator(nodes, tets)
    V = float(aa.compute_mesh_volume(sv, st))
    groups = fm.group_faces_by_planar_region(sv, st)
    return sv, st, freqs, phis, loc, V, groups


def test_uniform_reduces_to_global():
    print("1. Material UNIFORME -> reduce a la Sabine global per-cara")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    print(f"   modos={len(freqs)} ({freqs[0]:.1f}-{freqs[-1]:.1f} Hz), "
          f"grupos de cara={len(groups)}, V={V:.1f} m3")

    mat = _const_material("unif", 0.2)
    g2m = {g.signature: mat for g in groups}

    xi_pf = fm.compute_xi_per_mode_per_face(freqs, phis, loc, sv, st, groups, g2m, V)
    rt60 = fm.compute_sabine_rt60_per_face(V, groups, g2m)
    xi_gl = compute_xi_per_mode(freqs, rt60)

    assert xi_pf is not None
    relerr = np.abs(xi_pf - xi_gl) / np.maximum(xi_gl, 1e-12)
    print(f"   xi per-face vs global: relerr max={relerr.max()*100:.2f}%  "
          f"medio={relerr.mean()*100:.2f}%")
    assert relerr.max() < 0.03, "con material uniforme NO deberia diferir de la Sabine global"
    print("   OK (reduccion exacta a la Sabine global; sin regresion)")


def test_asymmetric_differentiates():
    print("\n2. Tratamiento ASIMETRICO (piso absorbente) -> diferencia modos")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()

    mat_abs = _const_material("abs", 0.80)
    mat_rig = _const_material("rig", 0.02)
    g2m = {g.signature: (mat_abs if g.kind == "floor" else mat_rig) for g in groups}
    kinds = {g.kind for g in groups}
    n_floor = sum(1 for g in groups if g.kind == "floor")
    print(f"   tipos de cara={kinds}, grupos 'floor'={n_floor}")

    xi = fm.compute_xi_per_mode_per_face(freqs, phis, loc, sv, st, groups, g2m, V)
    assert xi is not None and np.all(np.isfinite(xi)) and np.all(xi > 0)

    # Limites: xi con TODO rigido y xi con TODO absorbente (Sabine global).
    g2m_rig = {g.signature: mat_rig for g in groups}
    g2m_abs = {g.signature: mat_abs for g in groups}
    xi_rig = compute_xi_per_mode(freqs, fm.compute_sabine_rt60_per_face(V, groups, g2m_rig))
    xi_abs = compute_xi_per_mode(freqs, fm.compute_sabine_rt60_per_face(V, groups, g2m_abs))

    spread = xi.max() / xi.min()
    print(f"   xi: min={xi.min():.4f}  max={xi.max():.4f}  spread={spread:.2f}x")
    print(f"   limite rigido (medio)={xi_rig.mean():.4f}  "
          f"absorbente (medio)={xi_abs.mean():.4f}")

    # (a) El piso absorbente DIFERENCIA los modos (la version global daria xi
    #     identico salvo por la frecuencia): exigimos dispersion apreciable.
    assert spread > 1.3, "el tratamiento asimetrico deberia separar los modos"
    # (b) Acotado: cada modo entre el limite rigido y el absorbente a su freq
    #     (con un colchon del 5% por interpolacion/evaluacion).
    assert np.all(xi >= xi_rig * 0.95), "ningun modo debajo del piso rigido"
    assert np.all(xi <= xi_abs * 1.05), "ningun modo arriba del techo absorbente"
    print("   OK (diferencia los modos y queda acotado entre rigido y absorbente)")


if __name__ == "__main__":
    test_uniform_reduces_to_global()
    test_asymmetric_differentiates()
    print("\nTODOS OK")
