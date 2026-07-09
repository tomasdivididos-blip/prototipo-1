"""
bench_lofted_room.py
====================

Oraculos de la Fase A de T7 (geometria lofteada, Modelo 1). Valida el MOTOR
(make_lofted_room) sin UI: regresion contra el shoebox, volumen analitico de un
techo rakeado, watertight, y que el voxel malle + de modos coherentes.

Correr:
    PYTHONIOENCODING=utf-8 python bench_lofted_room.py
"""
from __future__ import annotations

import numpy as np

from geometry import make_lofted_room, make_room
from acoustic_mesh import build_volume_mesh, mesh_info, points_inside_surface
from acoustic_fem import build_KM, solve_modes


def _rect(W, L):
    """Planta rectangular CCW centrada en el origen (como make_room n=4)."""
    return np.array([[-W/2, -L/2], [W/2, -L/2], [W/2, L/2], [-W/2, L/2]], dtype=float)


def _flat(H):
    return [(0.0, H), (1.0, H)]


def test_regression_flat():
    print("1. Regresion: perfil plano -> caja recta")
    W, L, H = 5.0, 4.0, 3.0
    poly = _rect(W, L)
    v, t, e, M = make_lofted_room(poly, [_flat(H)] * 4)
    nodes, tets = build_volume_mesh(v, t, n_per_meter=2.5)
    info = mesh_info(nodes, tets)
    V_exact = W * L * H
    print(f"   M={M} vertices perimetro, V_malla={info['volume']:.3f}  V_exact={V_exact:.3f}")
    assert abs(info['volume'] - V_exact) / V_exact < 0.02, "volumen lejos del exacto"

    # Modos vs analitico de caja rigida.
    K, Mm, _ = build_KM(nodes, tets)
    freqs, _ = solve_modes(K, Mm, n_modes=6)
    fa = []
    for (l, m, nn) in [(1,0,0),(0,1,0),(1,1,0),(0,0,1),(2,0,0),(1,0,1)]:
        fa.append((343.0/2)*np.sqrt((l/W)**2+(m/L)**2+(nn/H)**2))
    fa = sorted(fa)[:len(freqs)]
    err = [100*abs(fn-an)/an for fn, an in zip(sorted(freqs), fa)]
    print("   modos num vs analitico:")
    for fn, an, er in zip(sorted(freqs), fa, err):
        print(f"     {fn:7.2f} Hz  vs {an:7.2f} Hz   err={er:.2f}%")
    assert max(err) < 5.0, "modos lofteados-planos no coinciden con la caja analitica"
    print("   OK (perfil plano reproduce el shoebox)")


def test_volume_raked():
    print("\n2. Techo rakeado: volumen analitico")
    # Rectangulo W x L. Paredes en y=-L/2 (i=0) e y=+L/2 (i=2) son las que
    # "suben"/"bajan"; las paredes x=cte (i=1, i=3) son rampas lineales.
    # Esquinas: (-W/2,-L/2)=v0 H=Ha, (W/2,-L/2)=v1 H=Ha,
    #           (W/2,L/2)=v2 H=Hb, (-W/2,L/2)=v3 H=Hb.
    W, L = 5.0, 4.0
    Ha, Hb = 2.5, 3.5
    poly = _rect(W, L)
    profiles = [
        _flat(Ha),              # arista v0->v1 (y=-L/2): ambos extremos Ha
        [(0.0, Ha), (1.0, Hb)], # v1->v2 (x=+W/2): rampa Ha->Hb
        _flat(Hb),              # v2->v3 (y=+L/2): ambos Hb
        [(0.0, Hb), (1.0, Ha)], # v3->v0 (x=-W/2): rampa Hb->Ha
    ]
    v, t, e, M = make_lofted_room(poly, profiles)
    nodes, tets = build_volume_mesh(v, t, n_per_meter=3.0)
    info = mesh_info(nodes, tets)
    V_exact = W * L * (Ha + Hb) / 2.0
    print(f"   V_malla={info['volume']:.3f}  V_exact={V_exact:.3f} "
          f"(rake {Ha}->{Hb} m)")
    assert abs(info['volume'] - V_exact) / V_exact < 0.03
    print("   OK")


def test_watertight():
    print("\n3. Watertight (raycast adentro/afuera)")
    poly = _rect(6.0, 4.0)
    profiles = [_flat(3.0), [(0,3.0),(0.5,4.2),(1,3.0)], _flat(3.0), [(0,3.0),(0.5,4.2),(1,3.0)]]
    v, t, e, M = make_lofted_room(poly, profiles)   # techo con pico central (gable)
    pts = np.array([
        [0.0, 0.0, 1.5],     # centro -> adentro
        [0.0, 0.0, 3.8],     # bajo el pico -> adentro
        [0.0, 0.0, 5.0],     # arriba del techo -> afuera
        [10.0, 0.0, 1.5],    # fuera del footprint -> afuera
    ])
    inside = points_inside_surface(pts, v.astype(float), t)
    print(f"   inside flags = {list(inside.astype(int))}  (esperado 1,1,0,0)")
    assert list(inside.astype(int)) == [1, 1, 0, 0]
    print("   OK")


def test_mirror():
    print("\n4. Simetria espejo (pared opuesta copia el perfil)")
    poly = _rect(5.0, 4.0)
    prof = [(0.0, 2.8), (0.5, 4.0), (1.0, 2.8)]
    # Pared 1 y su opuesta 3 con el MISMO perfil (mirror), 0 y 2 planas a 2.8.
    profiles = [_flat(2.8), prof, _flat(2.8), prof]
    v, t, e, M = make_lofted_room(poly, profiles)
    nodes, tets = build_volume_mesh(v, t, n_per_meter=2.5)
    info = mesh_info(nodes, tets)
    assert info['n_tets'] > 0 and info['volume'] > 0
    print(f"   malla OK: {info['n_tets']} tets, V={info['volume']:.2f} m³")
    print("   OK")


def test_corner_check():
    print("\n5. Chequeo de esquina inconsistente (debe fallar)")
    poly = _rect(5.0, 4.0)
    bad = [_flat(3.0), [(0.0, 99.0), (1.0, 3.0)], _flat(3.0), _flat(3.0)]
    try:
        make_lofted_room(poly, bad)
        raise AssertionError("deberia haber fallado por esquina inconsistente")
    except ValueError as ex:
        print(f"   ValueError OK: {str(ex)[:60]}...")


if __name__ == "__main__":
    test_regression_flat()
    test_volume_raked()
    test_watertight()
    test_mirror()
    test_corner_check()
    print("\nTODOS LOS ORACULOS DE FASE A (T7) OK.")
