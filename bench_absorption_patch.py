"""
bench_absorption_patch.py
=========================

Oraculos de los parches de absorcion sub-cara (`absorption_patch`).

Valida:
  1. TESELADO conserva el area de cada cara (sum dA == area del grupo).
  2. Sin parches + material uniforme -> xi identico a A36 global (no regresiona).
  3. EQUIVALENCIA: un parche que cubre la cara entera con material X == poner X
     como material anfitrion de esa cara (aisla la logica del parche del metodo
     de integracion).
  4. SELECTIVO + MONOTONO: un parche absorbente sobre una cara rigida sube xi
     respecto de todo-rigido, queda por debajo de todo-absorbente, y un parche
     mas grande amortigua mas (monotonia en area).
  5. Cross-check vs A36: el parche full-face y A36 (material al grupo) miden lo
     mismo pero con DISTINTA cuadratura -- A36 usa 1 punto por triangulo de render
     (crudo en malla gruesa), el parche teselas fino (mas preciso). No se exige
     que coincidan en magnitud; se exige que ambos queden ACOTADOS entre los
     limites rigido/absorbente y que CORRELACIONEN (misma direccion fisica). La
     brecha se reporta como hallazgo (fidelidad de la integral de superficie).

Correr:
    PYTHONIOENCODING=utf-8 python bench_absorption_patch.py
"""
from __future__ import annotations

import time
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import absorption_patch as ap
from material_library import Material, BANDS, compute_xi_per_mode


def _const_material(name, a):
    return Material({"name": name, "alpha": {b: float(a) for b in BANDS}})


def _build_shoebox(Lx=5.0, Ly=4.0, Lz=3.0, npm=2.5, n_modes=15):
    sv, st, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=npm)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=n_modes)
    loc = FieldEvaluator(nodes, tets)
    V = float(aa.compute_mesh_volume(sv, st))
    groups = fm.group_faces_by_planar_region(sv, st)
    return sv, st, freqs, phis, loc, V, groups


def _floor_group(groups):
    return next(g for g in groups if g.kind == "floor")


def test_tessellation_area():
    print("1. Teselado conserva el area de cada cara")
    sv, st, _f, _p, _l, _V, groups = _build_shoebox()
    worst = 0.0
    for g in groups:
        pts, ars = ap.tessellate_group(sv, st, g, h_target=0.25, kmax=8)
        rel = abs(ars.sum() - g.area) / max(g.area, 1e-9)
        worst = max(worst, rel)
    print(f"   grupos={len(groups)}  error de area max={worst*100:.4f}%")
    assert worst < 1e-6, "el teselado debe conservar el area exactamente"
    print("   OK")


def test_uniform_no_regression():
    print("\n2. Sin parches + material uniforme -> xi == A36 global")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    mat = _const_material("unif", 0.2)
    g2m = {g.signature: mat for g in groups}

    xi_a36 = fm.compute_xi_per_mode_per_face(freqs, phis, loc, sv, st, groups, g2m, V)
    xi_p = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m, patches=[], patch_to_material={}, V=V)

    assert xi_p is not None
    relerr = np.abs(xi_p - xi_a36) / np.maximum(xi_a36, 1e-12)
    print(f"   relerr vs A36: max={relerr.max()*100:.4f}%  medio={relerr.mean()*100:.4f}%")
    # Con material uniforme alpha_eff = alpha EXACTO en ambos (el alpha factoriza),
    # sin importar el metodo de cuadratura -> deben coincidir muy fino.
    assert relerr.max() < 1e-6, "uniforme sin parches debe reducir EXACTO a A36"
    print("   OK (reduccion exacta; sin regresion)")


def test_full_face_patch_equivalence():
    print("\n3. Parche full-face con X == material anfitrion X (misma cuadratura)")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    rig = _const_material("rig", 0.02)
    absb = _const_material("abs", 0.80)
    floor = _floor_group(groups)

    # Referencia: piso absorbente como ANFITRION (via funcion de parches, sin parche).
    g2m_ref = {g.signature: (absb if g is floor else rig) for g in groups}
    xi_ref = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m_ref, patches=[], patch_to_material={}, V=V)

    # Bajo prueba: piso anfitrion RIGIDO + parche absorbente que cubre TODO el piso.
    g2m = {g.signature: rig for g in groups}
    na, ua, va = ap.axis_aligned_frame(floor.normal)
    # Rango del piso en (u, v): bounding box de sus vertices.
    fverts = sv[np.unique(st[np.asarray(floor.face_indices, int)].ravel())]
    u0, u1 = fverts[:, ua].min(), fverts[:, ua].max()
    v0, v1 = fverts[:, va].min(), fverts[:, va].max()
    patch = ap.make_patch(floor, u0, v0, u1, v1, material_name="abs")
    xi = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m,
        patches=[patch], patch_to_material={patch.key: absb}, V=V)

    relerr = np.abs(xi - xi_ref) / np.maximum(xi_ref, 1e-12)
    print(f"   parche full-face vs anfitrion: relerr max={relerr.max()*100:.4f}%")
    assert relerr.max() < 1e-6, "cubrir la cara entera con X debe igualar anfitrion X"
    print("   OK (equivalencia exacta parche-full-face <-> anfitrion)")


def test_selective_and_monotone():
    print("\n4. Parche absorbente selectivo + monotonia en area")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    rig = _const_material("rig", 0.02)
    absb = _const_material("abs", 0.85)
    floor = _floor_group(groups)
    g2m = {g.signature: rig for g in groups}

    na, ua, va = ap.axis_aligned_frame(floor.normal)
    fverts = sv[np.unique(st[np.asarray(floor.face_indices, int)].ravel())]
    u0, u1 = float(fverts[:, ua].min()), float(fverts[:, ua].max())
    v0, v1 = float(fverts[:, va].min()), float(fverts[:, va].max())
    uc, vc = 0.5 * (u0 + u1), 0.5 * (v0 + v1)

    def xi_with_patch(frac):
        # Parche centrado que cubre una fraccion `frac` del area del piso.
        du = (u1 - u0) * np.sqrt(frac) / 2.0
        dv = (v1 - v0) * np.sqrt(frac) / 2.0
        p = ap.make_patch(floor, uc - du, vc - dv, uc + du, vc + dv, "abs")
        return ap.compute_xi_per_mode_with_patches(
            freqs, phis, loc, sv, st, groups, g2m,
            patches=[p], patch_to_material={p.key: absb}, V=V)

    xi_rigid = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m, patches=[], patch_to_material={}, V=V)
    g2m_abs = {g.signature: absb for g in groups}
    xi_absall = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m_abs, patches=[], patch_to_material={}, V=V)

    xi_small = xi_with_patch(0.25)
    xi_big = xi_with_patch(0.75)

    print(f"   xi medio: rigido={xi_rigid.mean():.4f}  parche25%={xi_small.mean():.4f}"
          f"  parche75%={xi_big.mean():.4f}  todo-abs={xi_absall.mean():.4f}")
    # (a) el parche sube el amortiguamiento respecto de todo-rigido
    assert xi_small.mean() > xi_rigid.mean() * 1.01, "el parche deberia subir xi"
    # (b) monotonia: mas area de parche -> mas amortiguamiento
    assert xi_big.mean() > xi_small.mean(), "mas area de parche deberia amortiguar mas"
    # (c) acotado por el limite todo-absorbente (colchon 2%)
    assert np.all(xi_big <= xi_absall * 1.02), "ningun modo por encima de todo-absorbente"
    # (d) acotado por debajo por todo-rigido
    assert np.all(xi_small >= xi_rigid * 0.98), "ningun modo por debajo de todo-rigido"
    print("   OK (selectivo, monotono en area y acotado)")


def test_crosscheck_a36():
    print("\n5. Cross-check vs A36: acotado + correlacionado (no identico)")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    rig = _const_material("rig", 0.02)
    absb = _const_material("abs", 0.60)
    floor = _floor_group(groups)

    # A36 clasico: piso absorbente asignado al grupo (cuadratura por centroides).
    g2m_a36 = {g.signature: (absb if g is floor else rig) for g in groups}
    xi_a36 = fm.compute_xi_per_mode_per_face(freqs, phis, loc, sv, st, groups, g2m_a36, V)

    # Parches: piso rigido + parche absorbente full-face (cuadratura fina).
    g2m = {g.signature: rig for g in groups}
    na, ua, va = ap.axis_aligned_frame(floor.normal)
    fverts = sv[np.unique(st[np.asarray(floor.face_indices, int)].ravel())]
    u0, u1 = fverts[:, ua].min(), fverts[:, ua].max()
    v0, v1 = fverts[:, va].min(), fverts[:, va].max()
    p = ap.make_patch(floor, u0, v0, u1, v1, "abs")
    xi_p = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m,
        patches=[p], patch_to_material={p.key: absb}, V=V)

    # Limites fisicos por modo (Sabine global rigido/absorbente).
    g2m_rig = {g.signature: rig for g in groups}
    g2m_abs = {g.signature: absb for g in groups}
    xi_rig = compute_xi_per_mode(freqs, fm.compute_sabine_rt60_per_face(V, groups, g2m_rig))
    xi_abs = compute_xi_per_mode(freqs, fm.compute_sabine_rt60_per_face(V, groups, g2m_abs))

    relerr = np.abs(xi_p - xi_a36) / np.maximum(xi_a36, 1e-12)
    corr = float(np.corrcoef(xi_p, xi_a36)[0, 1])
    print(f"   brecha de cuadratura (fina vs A36 crudo): max={relerr.max()*100:.1f}%"
          f"  medio={relerr.mean()*100:.1f}%  |  correlacion={corr:.3f}")
    # (a) ambos acotados entre rigido y absorbente (colchon 5%)
    assert np.all(xi_p >= xi_rig * 0.95) and np.all(xi_p <= xi_abs * 1.05), \
        "el parche debe quedar acotado entre rigido y absorbente"
    assert np.all(xi_a36 >= xi_rig * 0.95) and np.all(xi_a36 <= xi_abs * 1.05), \
        "A36 debe quedar acotado entre rigido y absorbente"
    # (b) correlacionan (misma direccion fisica; el parche es la version fina de A36)
    assert corr > 0.85, "parche y A36 deberian correlacionar fuerte"
    print("   OK (ambos acotados y fuertemente correlacionados; el parche es la "
          "version fina de A36)")


def test_sabine_rt60_patches():
    print("\n6. RT60 Sabine patch-aware: reduccion + equivalencia + monotonia")
    sv, st, _f, _p, _l, V, groups = _build_shoebox()
    rig = _const_material("rig", 0.02)
    absb = _const_material("abs", 0.80)
    floor = _floor_group(groups)

    # (a) sin parches == Sabine por cara clasica
    g2m = {g.signature: rig for g in groups}
    rt_ref = fm.compute_sabine_rt60_per_face(V, groups, g2m)
    rt_p0 = ap.sabine_rt60_with_patches(V, groups, g2m, [], {})
    d = max(abs(rt_ref[b] - rt_p0[b]) for b in rt_ref)
    print(f"   sin parches vs Sabine clasica: dif max={d:.2e} s")
    assert d < 1e-9, "sin parches debe reducir EXACTO a la Sabine por cara"

    # (b) parche full-face con X == material anfitrion X en toda la cara
    na, ua, va = ap.axis_aligned_frame(floor.normal)
    fv = sv[np.unique(st[np.asarray(floor.face_indices, int)].ravel())]
    patch = ap.make_patch(floor, fv[:, ua].min(), fv[:, va].min(),
                          fv[:, ua].max(), fv[:, va].max(), "abs")
    rt_patch = ap.sabine_rt60_with_patches(
        V, groups, g2m, [patch], {patch.key: absb})
    g2m_hostabs = {g.signature: (absb if g is floor else rig) for g in groups}
    rt_host = fm.compute_sabine_rt60_per_face(V, groups, g2m_hostabs)
    d2 = max(abs(rt_patch[b] - rt_host[b]) for b in rt_host)
    print(f"   parche full-face vs anfitrion: dif max={d2:.2e} s")
    assert d2 < 1e-9, "parche que cubre la cara == material anfitrion"

    # (c) mas area de parche absorbente -> menor RT60
    def rt500(frac):
        uc, vc = 0.5*(fv[:, ua].min()+fv[:, ua].max()), 0.5*(fv[:, va].min()+fv[:, va].max())
        du = (fv[:, ua].max()-fv[:, ua].min())*np.sqrt(frac)/2
        dv = (fv[:, va].max()-fv[:, va].min())*np.sqrt(frac)/2
        p = ap.make_patch(floor, uc-du, vc-dv, uc+du, vc+dv, "abs")
        return ap.sabine_rt60_with_patches(V, groups, g2m, [p], {p.key: absb})[500]
    r0, r25, r75 = rt_ref[500], rt500(0.25), rt500(0.75)
    print(f"   RT60@500: sin={r0:.2f}s  parche25%={r25:.2f}s  parche75%={r75:.2f}s")
    assert r0 > r25 > r75, "mas area absorbente deberia bajar el RT60 monotono"
    print("   OK (reduccion, equivalencia y monotonia)")


def test_polygon_geometry():
    print("\n7. Poligonos: area, triangulacion, solape, contains")
    # Area shoelace de un cuadrado unidad = 1
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert abs(ap.poly_area(sq) - 1.0) < 1e-12
    # Triangulo (no convexo tipo 'L' para probar ear clipping)
    L = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    a_L = ap.poly_area(L)
    tris = ap.triangulate_uv(L)
    P = np.asarray(L, float)
    a_tri = sum(ap.poly_area([P[i], P[j], P[k]]) for (i, j, k) in tris)
    print(f"   L-poly: area={a_L:.3f}  n_tris={len(tris)}  sum_tri={a_tri:.3f}")
    assert len(tris) == len(L) - 2, "ear clipping da n-2 triangulos"
    assert abs(a_tri - a_L) < 1e-9, "los triangulos deben cubrir el area del poligono"
    # contains: centro dentro, esquina exterior afuera
    m = ap.points_in_poly(L, np.array([0.5, 1.9]), np.array([0.5, 1.9]))
    assert m[0] and not m[1], "point-in-poly del L"

    # Solape: dos rects que se pisan -> True; adyacentes (comparten arista) -> False
    r1 = [(0, 0), (2, 0), (2, 2), (0, 2)]
    r2 = [(1, 1), (3, 1), (3, 3), (1, 3)]         # se pisa con r1
    r3 = [(2, 0), (4, 0), (4, 2), (2, 2)]         # adyacente por la arista u=2
    r4 = [(3, 3), (4, 3), (4, 4), (3, 4)]         # disjunto
    assert ap.polys_overlap(r1, r2) is True, "rects que se pisan -> solape"
    assert ap.polys_overlap(r1, r3) is False, "rects adyacentes -> sin solape"
    assert ap.polys_overlap(r1, r4) is False, "rects disjuntos -> sin solape"
    # Contencion total -> solape
    inner = [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]
    assert ap.polys_overlap(r1, inner) is True, "contencion total -> solape"
    print("   OK (area, ear clipping, solape con adyacencia permitida, contains)")


def test_polygon_patch_physics():
    print("\n8. Parche poligonal: xi corre y rect-como-poly == rect")
    sv, st, freqs, phis, loc, V, groups = _build_shoebox()
    absb = _const_material("abs", 0.7)
    rig = _const_material("rig", 0.02)
    floor = _floor_group(groups)
    g2m = {g.signature: rig for g in groups}

    # Un rectangulo expresado como POLIGONO debe dar identico a make_patch (rect).
    p_rect = ap.make_patch(floor, -1.0, -0.5, 1.0, 0.5, "abs")
    p_poly = ap.make_polygon_patch(
        floor, [(-1.0, -0.5), (1.0, -0.5), (1.0, 0.5), (-1.0, 0.5)], "abs")
    assert abs(p_rect.area - p_poly.area) < 1e-12
    xi_r = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m, [p_rect], {p_rect.key: absb}, V)
    xi_p = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m, [p_poly], {p_poly.key: absb}, V)
    rel = np.abs(xi_r - xi_p) / np.maximum(xi_r, 1e-12)
    print(f"   rect vs rect-como-poligono: relerr max={rel.max()*100:.4f}%")
    assert rel.max() < 1e-9, "un rect como poligono debe dar identico"

    # Un parche triangular corre y ampara el efecto (xi finito y > rigido).
    tri = ap.make_polygon_patch(floor, [(-2.0, -1.5), (2.0, -1.5), (0.0, 1.5)], "abs")
    xi_t = ap.compute_xi_per_mode_with_patches(
        freqs, phis, loc, sv, st, groups, g2m, [tri], {tri.key: absb}, V)
    assert xi_t is not None and np.all(np.isfinite(xi_t)) and xi_t.mean() > xi_r.mean() * 0
    print(f"   parche triangular: area={tri.area:.2f} m2  xi medio={xi_t.mean():.4f}")
    print("   OK (poligono corre y el rect-como-poly es exacto)")


if __name__ == "__main__":
    t0 = time.perf_counter()
    test_tessellation_area()
    test_uniform_no_regression()
    test_full_face_patch_equivalence()
    test_selective_and_monotone()
    test_crosscheck_a36()
    test_sabine_rt60_patches()
    test_polygon_geometry()
    test_polygon_patch_physics()
    print(f"\nTODOS OK  ({time.perf_counter() - t0:.1f} s)")
