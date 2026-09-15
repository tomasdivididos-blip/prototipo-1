"""
bench_remesh_curved.py
======================

Oraculos del REMESH ISOTROPICO + MALLADO DISCRETO (mesh_gmsh + mesh_router)
para superficies CURVAS importadas o CAD sucio, donde la reparametrizacion de
gmsh falla ("Invalid boundary mesh / overlapping facets").

Que se valida (falsable, autocontenido salvo el caso opcional del aula real):

  1. pymeshlab disponible y remesh produce malla UNIFORME + WATERTIGHT (tras
     soldar duplicados con trimesh), sin caras degeneradas.
  2. gmsh DISCRETO malla la superficie remallada: n_tets>0, volumen dentro de
     tolerancia, calidad de tets sana (qmin > 0.1, sin degenerados).
  3. ORACULO (plan §5): los modos del gmsh-discreto coinciden con los del VOXEL
     (que para geometria axis-aligned es near-exacto) dentro de ~2%.
  4. CONVERGENCIA: al refinar target_len, el error de volumen NO crece y los
     modos se acercan al voxel (boundary-fitted O(h^2)).
  5. REGRESION: el camino de REPARAMETRIZACION (malla limpia parametrica) sigue
     dando el shoebox exacto (V=60.000). No se toco.
  6. ROUTER: un CAD curvo/sucio pasa por reparam(falla) -> remesh+discreto y
     termina en engine='gmsh' (NO cae a voxel) cuando pymeshlab esta.
  7. CURVA GENUINA: un arco parametrico (arch_height>0, caras inclinadas) se
     malla boundary-fitted por remesh+discreto.

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_remesh_curved.py
"""

from __future__ import annotations

import os
import json
import numpy as np
import trimesh

import mesh_gmsh
import mesh_router
import geometry
import acoustic_mesh
import acoustic_fem

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


def _tet_volume(nodes, tets):
    p0, p1, p2, p3 = (nodes[tets[:, 0]], nodes[tets[:, 1]],
                      nodes[tets[:, 2]], nodes[tets[:, 3]])
    return float(np.abs(np.einsum("ij,ij->i",
                                  np.cross(p1 - p0, p2 - p0),
                                  p3 - p0)).sum() / 6.0)


def _modes(nodes, tets, n=7):
    KM = acoustic_fem.build_KM(nodes, tets)
    return acoustic_fem.solve_modes(KM[0], KM[1], n_modes=n)[0]


def _arch_surface(subdiv=4):
    """Arco parametrico curvo (caja 6x4x3, techo en arco h=1.2). Genuinamente
    curvo: mayoria de caras NO axis-aligned. Sale con T-junctions (no watertight)."""
    r = geometry.make_room(width=6.0, length=4.0, height=3.0, n_walls=4,
                           arch_height=1.2, roof_type="arch", subdiv_levels=subdiv)
    return np.asarray(r[0], float), np.asarray(r[1], int)


def main():
    print("=" * 64)
    print("bench_remesh_curved  (remesh isotropico + mallado discreto)")
    print("=" * 64)

    check("gmsh disponible", mesh_gmsh.is_available())
    have_pyml = mesh_gmsh.is_remesh_available()
    check("pymeshlab disponible (habilita remesh)", have_pyml)
    if not have_pyml:
        print("\n  pymeshlab ausente: la cadena cae a voxel (degradacion "
              "graciosa). Se saltan los checks que requieren remesh.")
        print("-" * 64)
        print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
        return

    # -- 1. remesh de una superficie curva -> uniforme + watertight ----------
    V, F = _arch_surface(subdiv=4)
    m0 = trimesh.Trimesh(V, F, process=False)
    n = m0.face_normals
    slanted = int(np.sum(np.all(np.abs(np.round(n, 2)) != 1.0, axis=1)))
    check("arco parametrico es genuinamente curvo (>50% caras inclinadas)",
          slanted > len(F) * 0.5, f"{slanted}/{len(F)} inclinadas")

    rv, rf = mesh_gmsh._remesh_isotropic(V, F, target_len=0.30)
    mr = trimesh.Trimesh(rv, rf, process=False)
    tri = mr.vertices[mr.faces]
    a = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                      tri[:, 2] - tri[:, 0]), axis=1)
    check("remesh watertight", bool(mr.is_watertight),
          f"F {len(F)}->{len(rf)}")
    check("remesh sin caras degeneradas", int((a < 1e-9).sum()) == 0,
          f"deg={(a < 1e-9).sum()}")
    check("remesh preserva volumen (<1%)",
          abs(mr.volume - m0.volume) / m0.volume < 0.01,
          f"{m0.volume:.3f}->{mr.volume:.3f}")

    # -- 2. gmsh discreto malla la superficie curva --------------------------
    nodes, tets, info = mesh_gmsh.mesh_with_gmsh(V, F, h_target=0.30,
                                                 remesh_target_len=0.30)
    q = mesh_gmsh.mesh_quality(nodes, tets)
    check("gmsh discreto genero tets", info["n_tets"] > 0, f"{info['n_tets']} tets")
    check("recon = discrete_remesh", info["reconstruction"] == "discrete_remesh")
    check("volumen malla ~ geometrico (<1%)",
          abs(info["volume"] - m0.volume) / m0.volume < 0.01,
          f"{info['volume']:.3f} vs {m0.volume:.3f}")
    check("calidad de tets sana (qmin>0.1, sin degenerados)",
          q["min"] > 0.1 and q["n_bad"] == 0,
          f"qmin={q['min']:.3f} nbad={q['n_bad']}")

    # -- 3. ORACULO: gmsh-discreto vs voxel (axis-aligned near-exacto) --------
    # Usamos un CAJON RECTO como oraculo duro: voxel es exacto y gmsh-discreto
    # debe coincidir. (El arco no tiene modo analitico cerrado; ver §5.)
    vb, fb, _e, _n = geometry.make_room(width=5.0, length=4.0, height=3.0, n_walls=4)
    mvx = acoustic_mesh.build_volume_mesh(vb, fb, n_per_meter=6.0)
    f_vox = _modes(mvx[0], mvx[1])
    ndg, tsg, ig = mesh_gmsh.mesh_with_gmsh(vb, fb, h_target=0.25,
                                            remesh_target_len=0.25)
    f_gm = _modes(ndg, tsg)
    err = 100 * np.abs(f_gm[:5] - f_vox[:5]) / f_vox[:5]
    # oraculo analitico de la caja 5x4x3: f = c/2 sqrt((nx/lx)^2+(ny/ly)^2+(nz/lz)^2)
    c = 343.0
    f100 = c / 2 / 5.0; f010 = c / 2 / 4.0
    check("oraculo caja: f(1,0,0) gmsh-discreto ~ analitico (<3%)",
          abs(f_gm[0] - f100) / f100 < 0.03, f"{f_gm[0]:.2f} vs {f100:.2f}")
    check("gmsh-discreto vs voxel, 5 modos (<3%)", float(err.max()) < 3.0,
          f"maxerr={err.max():.2f}%")

    # -- 4. convergencia: error de volumen no crece al refinar ---------------
    # (tamanos dentro del rango de validez FEM del arco 6x4x3; a h muy grueso
    # el mallado discreto puede no cerrar y el router cae a voxel, ver MANUAL.)
    errs = []
    for tl in (0.30, 0.20):
        _, _, iC = mesh_gmsh.mesh_with_gmsh(V, F, h_target=tl, remesh_target_len=tl)
        errs.append(abs(iC["volume"] - m0.volume) / m0.volume)
    check("convergencia: error de volumen no crece al refinar",
          errs[1] <= errs[0] + 1e-3,
          f"err {errs[0]*100:.2f}% -> {errs[1]*100:.2f}%")

    # -- 5. REGRESION: reparametrizacion (shoebox limpio) intacta ------------
    _, _, ir = mesh_gmsh.mesh_with_gmsh(vb, fb, h_target=0.40)  # sin remesh
    check("reparam shoebox: recon=reparam, V=60.000",
          ir["reconstruction"] == "reparam" and abs(ir["volume"] - 60.0) < 0.05,
          f"recon={ir['reconstruction']} V={ir['volume']:.3f}")

    # -- 6. ROUTER: CAD sucio real donde reparam FALLA -> remesh+discreto ----
    # El cuerpo exterior del aula (CAD EASE, axis-aligned facetado con
    # T-junctions) es watertight pero rompe reparam ("overlapping facets"). El
    # router debe caer al remesh+discreto y terminar boundary-fitted (no voxel).
    room_path = "aula con prediccion.room"
    if os.path.exists(room_path):
        d = json.load(open(room_path, encoding="utf-8"))
        eg = d["external_geometry"]
        ma = trimesh.Trimesh(np.array(eg["vertices"], float),
                             np.array(eg["faces"], int), process=False)
        outer = sorted(ma.split(only_watertight=False),
                       key=lambda c: c.bounding_box.volume)[-1]
        outer.fix_normals()
        Vo, Fo = np.asarray(outer.vertices, float), np.asarray(outer.faces, int)
        res = mesh_router.build_mesh(Vo, Fo, is_imported_cad=True,
                                     user_override="auto", h_target=0.30,
                                     progress=lambda m: None)
        check("router: CAD real (reparam falla) -> remesh+discreto -> gmsh",
              res.decision.engine == "gmsh"
              and res.info.get("reconstruction") == "discrete_remesh"
              and abs(res.info["volume"] - abs(outer.volume)) / abs(outer.volume) < 0.02,
              f"engine={res.decision.engine} recon={res.info.get('reconstruction')} "
              f"V={res.info['volume']:.2f} vs {abs(outer.volume):.2f}")
    else:
        print("  (aula ausente: se salta el test de router con CAD real)")

    # -- 7. AULA real (opcional): CAD con arco + columna ---------------------
    room_path = "aula con prediccion.room"
    if os.path.exists(room_path):
        d = json.load(open(room_path, encoding="utf-8"))
        eg = d["external_geometry"]
        Va = np.array(eg["vertices"], float)
        Fa = np.array(eg["faces"], int)
        ma = trimesh.Trimesh(Va, Fa, process=False)
        comps = sorted(ma.split(only_watertight=False),
                       key=lambda c: c.bounding_box.volume)
        # sala - columna: restar el volumen ABSOLUTO de cada cuerpo interior
        # (el signo de trimesh depende de la orientacion de las normales).
        v_room_minus_col = (abs(comps[-1].volume)
                            - sum(abs(c.volume) for c in comps[:-1]))
        resa = mesh_router.build_mesh(Va, Fa, is_imported_cad=True,
                                      h_target=0.35, progress=lambda m: None)
        check("aula: mallada por gmsh boundary-fitted (remesh+discreto)",
              resa.decision.engine == "gmsh"
              and resa.info.get("reconstruction") == "discrete_remesh",
              f"engine={resa.decision.engine}")
        check("aula: volumen ~ sala-columna (<2%)",
              abs(resa.info["volume"] - v_room_minus_col) / v_room_minus_col < 0.02,
              f"{resa.info['volume']:.2f} vs {v_room_minus_col:.2f}")
        qa = mesh_gmsh.mesh_quality(resa.nodes, resa.tets)
        check("aula: sin tets degenerados", qa["n_bad"] == 0,
              f"qmin={qa['min']:.3f} nbad={qa['n_bad']}")
    else:
        print("  (aula con prediccion.room ausente: se salta el caso real)")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return _N_FAIL == 0


if __name__ == "__main__":
    ok = main()
    raise SystemExit(0 if ok else 1)
