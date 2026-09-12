"""
bench_cad_cure.py
=================

Oraculos de las operaciones de CURADO de CAD roto (geom_import): soldar por
distancia, quedarse con el cuerpo mas grande, borrar cuerpos chicos, borrar
caras, y el pipeline `cure_auto`. Motivado por los CAD del profesor (EASE
exporta panos sueltos con vertices duplicados -> decenas/miles de "cuerpos").

Falsable, autocontenido (malla sintetica). Si `PLANO AULA.obj` esta presente,
corre tambien un chequeo sobre esa malla real.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_cad_cure.py
"""

from __future__ import annotations

import os
import numpy as np
import trimesh as tm

import geom_import as gi

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


def _shattered_box():
    """Caja estanca 'explotada': cada triangulo con sus PROPIOS vertices (duplicados)
    -> cada cara es un cuerpo suelto, como el export de EASE. Weld deberia re-unirla."""
    box = tm.creation.box(extents=(4.0, 3.0, 2.6))
    v = np.asarray(box.vertices, float)
    f = np.asarray(box.faces, int)
    vv = v[f].reshape(-1, 3)                 # (Nf*3, 3) vertices duplicados
    ff = np.arange(len(vv)).reshape(-1, 3)   # cada cara referencia 3 propios
    return tm.Trimesh(vertices=vv, faces=ff, process=False), box


def test_weld_reunites():
    print("T1  soldar por distancia re-une panos con vertices duplicados")
    shattered, box = _shattered_box()
    s0 = gi.quick_stats(shattered)
    check("la malla explotada arranca con muchos cuerpos",
          s0["n_components"] == len(box.faces),
          f"{s0['n_components']} cuerpos, watertight={s0['watertight']}")
    welded = gi.merge_close_vertices(shattered, 1e-3)
    s1 = gi.quick_stats(welded)
    check("tras soldar queda 1 cuerpo estanco",
          s1["n_components"] == 1 and s1["watertight"] and s1["n_open_edges"] == 0,
          f"{s1['n_components']} cuerpos, borde={s1['n_open_edges']}, wt={s1['watertight']}")
    check("volumen preservado (~4*3*2.6)", abs(welded.volume - 4*3*2.6) < 1e-6,
          f"vol={welded.volume:.3f}")


def test_components_ops():
    print("\nT2  quedarse con el mas grande / borrar cuerpos chicos")
    box = tm.creation.box(extents=(4.0, 3.0, 2.6))       # 12 caras, estanca
    tri = tm.Trimesh(vertices=[[9, 9, 9], [9.1, 9, 9], [9, 9.1, 9]],
                     faces=[[0, 1, 2]], process=False)    # basura suelta (1 cara)
    mixed = tm.util.concatenate([box, tri])
    check("mezcla = 2 cuerpos", gi.quick_stats(mixed)["n_components"] == 2)
    big = gi.keep_largest_component(mixed)
    check("keep_largest deja el shell (12 caras) estanco",
          len(big.faces) == 12 and big.is_watertight)
    clean, removed = gi.remove_small_components(mixed, min_faces=4)
    check("remove_small quita la cara suelta (quitados=1) y deja estanco",
          removed == 1 and clean.is_watertight and len(clean.faces) == 12,
          f"removed={removed}")


def test_drop_faces():
    print("\nT3  borrar caras seleccionadas")
    box = tm.creation.box(extents=(2.0, 2.0, 2.0))
    n0 = len(box.faces)
    out = gi.drop_faces(box, [0, 1])
    check("quedan n-2 caras", len(out.faces) == n0 - 2, f"{len(out.faces)}/{n0}")
    check("borrar 2 caras abre el volumen (ya no estanco)", not out.is_watertight)
    check("indices fuera de rango se ignoran",
          len(gi.drop_faces(box, [999, -1]).faces) == n0)


def test_drop_low_volume():
    print("\nT4b  borrar cuerpos por volumen (umbral ajustable)")
    box = tm.creation.box(extents=(4.0, 3.0, 2.6))            # 31.2 m3
    small = tm.creation.box(extents=(0.5, 0.5, 0.5))          # 0.125 m3
    small.apply_translation([9, 9, 9])
    # pano plano degenerado (volumen ~0)
    flat = tm.Trimesh(vertices=[[0, 0, 5], [1, 0, 5], [1, 1, 5], [0, 1, 5]],
                      faces=[[0, 1, 2], [0, 2, 3]], process=False)
    mixed = tm.util.concatenate([box, small, flat])
    vols = sorted(v for _, v in gi.component_face_groups(mixed))
    check("volumenes por cuerpo detectados (~0, 0.125, 31.2)",
          len(vols) == 3 and vols[0] < 1e-6 and abs(vols[-1] - 31.2) < 1e-3,
          f"{[round(v,3) for v in vols]}")
    out, n = gi.remove_low_volume_components(mixed, 0.01)
    check("umbral 0.01 saca solo el pano degenerado (1 cuerpo)",
          n == 1 and gi.quick_stats(out)["n_components"] == 2)
    out2, n2 = gi.remove_low_volume_components(mixed, 0.2)
    check("umbral 0.2 saca pano + caja chica (2 cuerpos), queda la grande",
          n2 == 2 and gi.quick_stats(out2)["n_components"] == 1
          and abs(out2.volume - 31.2) < 1e-3, f"quitados={n2}")
    keep, drop, dvols = gi.low_volume_faces(mixed, 0.01)
    check("low_volume_faces marca las caras del pano para el preview",
          len(drop) == 2 and len(keep) == len(box.faces) + len(small.faces),
          f"drop={len(drop)} keep={len(keep)}")


def test_cure_auto():
    print("\nT4  cure_auto: pipeline completo sobre la caja explotada + basura")
    shattered, box = _shattered_box()
    tri = tm.Trimesh(vertices=[[9, 9, 9], [9.05, 9, 9], [9, 9.05, 9]],
                     faces=[[0, 1, 2]], process=False)
    dirty = tm.util.concatenate([shattered, tri])
    cured, rep = gi.cure_auto(dirty, weld_tol=1e-3, min_faces=4)
    check("reporte trae before/after", "before" in rep and "after" in rep)
    check("cure_auto deja 1 cuerpo estanco",
          rep["after"]["n_components"] == 1 and rep["after"]["watertight"],
          f"antes {rep['before']['n_components']} cuerpos -> despues "
          f"{rep['after']['n_components']}, wt={rep['after']['watertight']}")
    check("volumen del shell preservado", abs(cured.volume - 4*3*2.6) < 1e-3,
          f"vol={cured.volume:.3f}")


def test_real_aula():
    path = "PLANO AULA.obj"
    if not os.path.exists(path):
        print("\nT5  (omitido: no esta PLANO AULA.obj)")
        return
    print("\nT5  aula real: el weld baja drasticamente los cuerpos")
    m = tm.load(path, force="mesh")
    s0 = gi.quick_stats(m)
    cured, rep = gi.cure_auto(m, weld_tol=0.02, min_faces=4)
    s1 = rep["after"]
    print(f"      antes: {s0['n_components']} cuerpos, {s0['n_open_edges']} aristas borde")
    print(f"      despues: {s1['n_components']} cuerpos, {s1['n_open_edges']} aristas borde, wt={s1['watertight']}")
    check("el curado reduce los cuerpos al menos 5x",
          s1["n_components"] <= max(1, s0["n_components"] // 5),
          f"{s0['n_components']} -> {s1['n_components']}")
    # El recinto queda fragmentado; el flujo 'cuerpo mas grande (bbox) + tapar'
    # lo cierra a un solido de volumen realista (no un fragmento chico).
    big = gi.keep_largest_component(gi.merge_close_vertices(m, 0.02))
    closed = gi.normalize_mesh(gi.fill_all_holes_auto(big))
    vol = float(closed.volume) if closed.is_watertight else 0.0
    print(f"      cuerpo mas grande + tapar: watertight={closed.is_watertight}, vol={vol:.1f} m3")
    check("cuerpo mas grande (bbox) + tapar -> estanco y volumen realista (>50 m3)",
          closed.is_watertight and vol > 50.0, f"vol={vol:.1f}")


def main():
    print("=" * 64)
    print("bench_cad_cure.py  —  curado de CAD roto")
    print("=" * 64)
    test_weld_reunites()
    test_components_ops()
    test_drop_faces()
    test_drop_low_volume()
    test_cure_auto()
    test_real_aula()
    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
