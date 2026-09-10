"""
smoke_optimize_material.py
==========================

Smoke headless (falsable) de los tres arreglos pedidos por el profesor (9 Sep 2026):

  1. BUG materiales: al re-anclar el origen (esquina/centro) la malla se TRASLADA
     y `face_materials._signature` hashea el centroide ABSOLUTO -> cambian todas
     las firmas y las caras volvian al material default. El fix
     `remap_signatures_after_translation` traslada las claves del mapa. Se prueba
     habiendo CARGADO UN MATERIAL PERSONALIZADO (por tercios), como pidio el user.

  2. BUG optimizador: en un recinto IRREGULAR el AABB es mas grande que la planta
     y el optimizador podia colocar una fuente FUERA del recinto. El fix pasa un
     `inside_fn` (poligono real) a `optimize_cabs`, que penaliza las posiciones
     afuera. Se verifica que TODAS las posiciones optimizadas caen dentro.

  3. NIVEL: nueva variable libre "level" (sensibilidad dB) que el optimizador
     puede ajustar (MSO; Welti & Devantier, JAES 54, 2006).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe smoke_optimize_material.py
"""

from __future__ import annotations

import numpy as np

import face_materials as fm
from material_library import Material
from geometry import build_room_geometry
from acoustic_mesh import points_inside_surface
from sources import OmniSource, q_from_sensitivity
import cabs_optimize as copt

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


_SHOEBOX = {"width": 5.0, "length": 4.0, "height": 3.0, "n_walls": 4,
            "taper": 0.0, "twist": 0.0, "arch_height": 0.0, "roof_type": "flat"}


def _custom_material():
    """Material PROPIO por tercios de octava (alpha alto y distintivo = 0.55),
    como el que arma el formulario «Crear material…». alpha != default (~0.03)."""
    thirds = [50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
              800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]
    return Material({"name": "MiPanel (tercios)", "category": "propio",
                     "alpha": {str(f): 0.55 for f in thirds}})


# ---------------------------------------------------------------------------
def test_material_survives_reanchor():
    """BUG #2: un material propio asignado a una cara sobrevive a la traslacion
    del recinto (re-anclaje de origen) via el remapeo de firmas."""
    print("T1  material propio sobrevive al re-anclaje (traslacion)")
    v, t, _e, _n = build_room_geometry(_SHOEBOX)
    v = np.asarray(v, dtype=float)
    t = np.asarray(t, dtype=int)
    groups = fm.group_faces_by_planar_region(v, t)
    check("hay grupos de cara", len(groups) >= 4, f"{len(groups)} grupos")

    mat = _custom_material()
    # Elegir el piso (o el grupo de mayor area) para asignarle el material propio.
    target = next((g for g in groups if g.kind == "floor"), groups[0])
    fmap = fm.FaceMaterialMap(default_material="Alfombra fina")
    fmap.assign(target.signature, mat.name)

    # alpha efectivo ANTES de trasladar (el material propio manda: 0.55).
    a_before = mat.alpha(100.0) if fmap.get(target.signature) == mat.name else 0.03
    check("alpha del material propio antes (=0.55)", abs(a_before - 0.55) < 1e-9,
          f"{a_before:.3f}")

    # Simular re-anclaje: trasladar TODA la malla (esquina min a 0,0,0 => delta
    # grande, tipico de "ajustar a esquina inferior").
    delta = np.array([-2.5, -2.0, 0.0])
    v2 = v + delta
    groups2 = fm.group_faces_by_planar_region(v2, t)

    # CONTRAPRUEBA (bug sin fix): el mapa VIEJO no encuentra la firma nueva.
    tgt2 = min(groups2, key=lambda g: np.linalg.norm(
        np.asarray(g.centroid) - (np.asarray(target.centroid) + delta)))
    got_old = fmap.get(tgt2.signature)     # sin remap -> cae al default
    check("CONTRAPRUEBA: sin remap la cara vuelve al default",
          got_old == "Alfombra fina" and tgt2.signature != target.signature,
          f"got={got_old!r}")

    # FIX: remapear las firmas por la traslacion y reescribir el mapa.
    remap = fm.remap_signatures_after_translation(groups, delta)
    check("la firma nueva del remap coincide con la del re-agrupado",
          remap.get(target.signature) == tgt2.signature,
          f"remap={remap.get(target.signature)!r} vs regroup={tgt2.signature!r}")
    fmap.from_dict({remap.get(k, k): val for k, val in fmap.to_dict().items()})

    got_new = fmap.get(tgt2.signature)
    check("con remap la cara conserva el material propio", got_new == mat.name,
          f"got={got_new!r}")

    # alpha efectivo DESPUES (via _alpha_for, el camino real de RT/xi).
    g2m = {tgt2.signature: mat}
    a_after = fm._alpha_for(tgt2, g2m, 100.0)
    check("alpha del material propio despues (=0.55, no default)",
          abs(a_after - 0.55) < 1e-9, f"{a_after:.3f}")


# ---------------------------------------------------------------------------
def test_optimizer_stays_inside_irregular_room():
    """BUG #1: en un recinto irregular el optimizador mantiene las fuentes DENTRO
    del poligono real (no del AABB)."""
    print("\nT2  optimizador mantiene las fuentes dentro del recinto irregular")
    poly = [(0.0, 0.0), (4.0, 0.0), (6.0, 2.0), (6.0, 5.0), (0.0, 5.0)]
    params = dict(_SHOEBOX, n_walls=5, base_polygon=poly,
                  wall_inclinations=[0.0] * 5)
    v, t, _e, _n = build_room_geometry(params)
    v = np.asarray(v, dtype=float)
    t = np.asarray(t, dtype=int)
    vmin = v.min(axis=0)
    dims = tuple((v.max(axis=0) - vmin).tolist())

    def inside_fn(p):
        return bool(points_inside_surface(
            np.asarray(p, dtype=float).reshape(1, 3), v, t)[0])

    # ¿El AABB contiene puntos fuera del recinto? (si no, el test no discrimina).
    corner = np.array([vmin[0] + dims[0] - 0.2, vmin[1] + 0.2, vmin[2] + 1.0])
    check("el AABB tiene zona fuera del recinto (test no trivial)",
          not inside_fn(corner), f"esquina AABB dentro={inside_fn(corner)}")

    # Dos subs enfrentados sobre el eje Y (largo), con posicion libre.
    axis = 1
    subs = [
        OmniSource((3.0, vmin[1] + 0.15, 1.2), label="F", source_type="subwoofer",
                   sensitivity_dB=90.0, free_vars={"pos"}),
        OmniSource((3.0, vmin[1] + dims[1] - 0.15, 1.2), label="R",
                   source_type="subwoofer", sensitivity_dB=90.0, polarity=-1,
                   free_vars={"pos"}),
    ]
    rcv = (3.0, vmin[1] + dims[1] / 2, 1.2)
    r = copt.optimize_cabs(subs, dims, rcv, origin=tuple(vmin.tolist()),
                           axis=axis, fmax=120.0, maxiter=15, seed=0,
                           criterion="cabs", inside_fn=inside_fn)
    all_in = all(inside_fn(s.position) for s in r["optimized"])
    check("todas las fuentes optimizadas caen DENTRO del recinto real", all_in,
          "; ".join(f"{s.label}={tuple(round(x,2) for x in s.position)}"
                    f"[{'in' if inside_fn(s.position) else 'OUT'}]"
                    for s in r["optimized"]))

    # CONTRAPRUEBA del mecanismo: _cost penaliza fuerte una posicion FUERA del
    # recinto (la penalizacion es la que empuja al optimizador a quedarse dentro).
    import dba_evaluate as dev
    fa = np.linspace(20.0, 120.0, 40)
    basis = dev.make_basis(dims, 120.0, 343.0)
    zb = __import__("dba")._zone_grid(dims, axis, 3, 2, 3)
    dofs = copt.collect_dofs(subs, dims, vmin, axis)   # front/rear: pos (X,Z)
    x_in = [(lo + hi) / 2 for (_i, _k, _a, lo, hi) in dofs]   # centro del AABB
    # Empujar el eje X del front hacia el AABB max (la esquina cortada => fuera).
    x_out = list(x_in)
    for j, (i, k, a, lo, hi) in enumerate(dofs):
        if i == 0 and k == "pos" and a == 0:
            x_out[j] = hi - 0.05
    args = (subs, dofs, dims, vmin, None, rcv, axis, fa, 0.03, 343.0, 80.0,
            basis, zb)
    c_in = copt._cost(x_in, *args, inside_fn)
    c_out = copt._cost(x_out, *args, inside_fn)
    check("_cost penaliza fuerte una fuente fuera del recinto (>=90 dB)",
          (c_out - c_in) >= 90.0, f"Δcosto afuera={c_out - c_in:.1f} dB")


# ---------------------------------------------------------------------------
def test_level_is_optimizable():
    """NIVEL: la variable libre 'level' entra como DOF, se optimiza y queda en
    el rango [sens-12, sens+12] acotado a [40,130]; Q queda consistente."""
    print("\nT3  el nivel (sensibilidad) es una variable optimizable")
    dims = (5.0, 4.0, 3.0)
    subs = [
        OmniSource((2.5, 0.15, 1.2), label="F", source_type="subwoofer",
                   sensitivity_dB=85.0, free_vars={"pos", "level"}),
        OmniSource((2.5, 3.85, 1.2), label="R", source_type="subwoofer",
                   sensitivity_dB=95.0, polarity=-1, free_vars=frozenset()),
    ]
    dofs = copt.collect_dofs(subs, dims, (0.0, 0.0, 0.0), 1)
    lvl = [d for d in dofs if d[1] == "level"]
    check("hay 1 DOF de nivel", len(lvl) == 1, f"{len(lvl)} DOF de nivel")
    if lvl:
        _i, _k, _a, lo, hi = lvl[0]
        check("rango de nivel = [73, 97] dB (85 +-12)",
              abs(lo - 73.0) < 1e-6 and abs(hi - 97.0) < 1e-6,
              f"[{lo:.0f},{hi:.0f}]")

    r = copt.optimize_cabs(subs, dims, (2.5, 2.0, 1.2), axis=1, fmax=120.0,
                           maxiter=18, seed=1, criterion="cabs")
    front = r["optimized"][0]
    check("la sensibilidad optimizada queda en rango [73,97]",
          73.0 - 1e-6 <= front.sensitivity_dB <= 97.0 + 1e-6,
          f"{front.sensitivity_dB:.1f} dB")
    q_exp = q_from_sensitivity(front.sensitivity_dB, front.power_W, front.f_ref)
    check("Q consistente con la sensibilidad optimizada",
          abs(abs(front.Q) - abs(q_exp)) < 1e-9,
          f"|Q|={abs(front.Q):.4g}")
    # El nivel afecta el objetivo (esta cableado): cambiar la sensibilidad mueve
    # el costo (si no, optimizarlo seria inerte).
    base = [OmniSource(s.position, label=s.label, source_type="subwoofer",
                       sensitivity_dB=s.sensitivity_dB, polarity=s.polarity)
            for s in subs]
    import dba_evaluate as dev
    fa = np.linspace(20.0, 120.0, 50)
    basis = dev.make_basis(dims, 120.0, 343.0)
    zb = __import__("dba")._zone_grid(dims, 1, 3, 2, 3)
    def _cost_at(sens):
        b2 = [OmniSource(s.position, label=s.label, source_type="subwoofer",
                         sensitivity_dB=(sens if s.label == "F"
                                         else s.sensitivity_dB),
                         polarity=s.polarity) for s in base]
        m = dev._config_metrics(b2, dims, (0.0, 0.0, 0.0), None, (2.5, 2.0, 1.2),
                                axis=1, fa=fa, xi=0.03, c=343.0, f_s=80.0,
                                basis=basis, with_decay=False, zone_box=zb)
        return m["flat"] + m["spatial"]
    d_cost = abs(_cost_at(80.0) - _cost_at(95.0))
    check("cambiar el nivel mueve el objetivo (>0.05 dB)", d_cost > 0.05,
          f"Δcosto={d_cost:.3f} dB")


def main():
    print("=" * 64)
    print("smoke_optimize_material.py  —  materiales + optimizador (inside/nivel)")
    print("=" * 64)
    test_material_survives_reanchor()
    test_optimizer_stays_inside_irregular_room()
    test_level_is_optimizable()
    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
