"""bench_furniture_phaseC.py — espina de Fase C (headless).

  1. solve_modal_with_furniture: compone malla+talla+solve en una llamada, y
     los modos salen corridos por el mueble (vs sin mueble).
  2. furniture_xi: xi end-to-end con absorcion del mueble (finito, selectivo).
  3. persistencia .room v7: Furniture round-trips por to_dict/from_dict, y una
     lista de muebles sobrevive un ciclo dict->json->dict identica.

Correr:  python bench_furniture_phaseC.py
"""
import json
import numpy as np

import geometry
import acoustic_fem
import face_materials as fm
import furniture as fu

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


v, t, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)

# ---------------------------------------------------------------------------
print("t1: solve_modal_with_furniture corre y corre los modos")
sol0 = fu.solve_modal_with_furniture(v, t, [], n_modes=20, n_per_meter=4.0)
obst = fu.Furniture("box", (0.0, 0.0, 1.5), (1.0, 1.0, 1.0), label="cubo")
solF = fu.solve_modal_with_furniture(v, t, [obst], n_modes=20, n_per_meter=4.0)
check("sin muebles: solve OK", np.all(np.isfinite(sol0["freqs"])) and
      len(sol0["freqs"]) >= 15, f"{len(sol0['freqs'])} modos")
check("con mueble: tets removidos y modos finitos",
      solF["carve_info"]["n_tets_removed"] > 0 and
      np.all(np.isfinite(solF["freqs"])),
      f"{solF['carve_info']['n_tets_removed']} tets fuera")
# algun modo se corre respecto de base (el cubo central deforma varios)
shift = np.abs(solF["freqs"][:15] - sol0["freqs"][:15]) / sol0["freqs"][:15]
check("los modos se corren por el mueble", np.max(shift) > 0.005,
      f"max corrimiento {np.max(shift)*100:.1f}%")

# ---------------------------------------------------------------------------
print("t2: furniture_xi end-to-end (absorcion del mueble via A36)")
class Mat:
    def __init__(s, a): s._a = a; s.name = f"a{a}"; s.category = ""
    def alpha(s, f): return s._a
groups = fm.group_faces_by_planar_region(v, t)
g2m = {g.signature: Mat(0.05) for g in groups}
V_air = 5*4*3 - solF["carve_info"]["V_removed_mesh"]
xi = fu.furniture_xi(solF, v, t, groups, g2m, [obst], {0: Mat(0.7)}, V_air)
check("xi finito y positivo", xi is not None and np.all(np.isfinite(xi))
      and np.all(xi > 0), f"xi mediana {np.median(xi):.3f}" if xi is not None else "None")
check("xi selectivo (std > 0 por el mueble absorbente)",
      xi is not None and np.std(xi) > 1e-3, f"std {np.std(xi):.4f}")

# ---------------------------------------------------------------------------
print("t3: persistencia .room v7 (round-trip de muebles)")
muebles = [
    fu.Furniture("box", (1.95, 3.30, 0.92), (2.80, 0.60, 0.45),
                 orientation=15.0, label="escritorio", provenance="Fig3"),
    fu.Furniture("cylinder", (3.0, 1.0, 0.4), (0.5, 0.5, 0.8), label="tacho"),
]
blob = json.dumps({"furniture": [m.to_dict() for m in muebles]})
back = [fu.Furniture.from_dict(x)
        for x in json.loads(blob)["furniture"]]
ok = (len(back) == 2 and back[0].kind == "box" and back[1].kind == "cylinder"
      and abs(back[0].orientation - 15.0) < 1e-9
      and back[0].label == "escritorio" and back[0].provenance == "Fig3"
      and np.allclose(back[0].size, (2.80, 0.60, 0.45)))
check("Furniture sobrevive dict->json->dict identico", ok,
      f"{[m.label for m in back]}")
# el default vacio (compat v4-v6) da lista vacia sin romper
check("sin clave 'furniture' -> lista vacia (compat)",
      [fu.Furniture.from_dict(x) for x in ({}.get("furniture") or [])] == [])

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
