"""
bench_material_fallback.py
==========================

Bench HEADLESS de los dos arreglos del 1 Oct 2026 motivados por Control Ale.room
(material custom no cargado -> f_Schroeder falso). Ver bug-material-no-resuelto-rigido.

  A. CONSISTENCIA de caminos: una cara cuyo material NO resuelve (no esta en el
     catalogo) debe absorber alpha=0.03 por DEFAULT en el camino de perturbacion
     UNIFICADO (`compute_xi_shift_with_impedance`), igual que en el SIMPLE
     (`perturbation_xi_per_mode`), NO volverse RIGIDA (beta=0). Antes el unificado
     usaba default_surf=None -> beta=0 -> RT explota -> f_S falso.
       A1  el puente: AcousticPanel._default_alpha_surface().alpha_random ~ 0.03.
       A2  kernel: default_surf resistivo == camino simple (xi), y el default
           RIGIDO (None) da MUCHO menos amortiguamiento (reproduce el bug).
       A3  deteccion: AcousticPanel._unresolved_material_names() lista el material
           asignado-pero-faltante, e ignora caras sin asignar y resueltas.

  B. EMBEBIDO robusto al RE-GUARDAR: si un material usado no esta en la biblioteca
     local pero el .room lo trajo embebido (cache), se re-embebe (portabilidad
     lossless). Si no esta ni en lib ni en cache, se AVISA (no se pierde en
     silencio). Ejercita el codigo REAL de MainWindow._serialize_acoustic_state.

Correr:
  PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen \\
    /c/Users/aceve/anaconda3/python.exe bench_material_fallback.py
"""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
except Exception as e:
    print(f"FATAL: no se pudo crear QApplication: {e}")
    sys.exit(2)

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import absorption_patch as ap
from viewer import IsoViewer
from acoustic_panel import AcousticPanel
from material_library import Material

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    _N_OK += int(bool(cond))
    _N_FAIL += int(not cond)
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def _custom_mat(name="Emplacado del Control Room SMA", a=0.30):
    thirds = [50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
              800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]
    return Material({"name": name, "category": "propio",
                     "alpha": {str(f): a for f in thirds}})


# ---------------------------------------------------------------------------
# Setup modal compartido (shoebox pequeno)
# ---------------------------------------------------------------------------
Lx, Ly, Lz = 4.8, 3.9, 3.1
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
vr = np.asarray(vr, float); tr = np.asarray(tr, int)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.4)
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=10)
loc = FieldEvaluator(nodes, tets)
groups = fm.group_faces_by_planar_region(vr, tr)
V = aa.compute_mesh_volume(vr, tr)


def test_A1_default_surface():
    print("A1  _default_alpha_surface: puente Paris (alpha_random ~ 0.03)")
    s = AcousticPanel._default_alpha_surface(0.03)
    ar = float(np.asarray(s.alpha_random(np.array([125.0]))).ravel()[0])
    check("alpha_random de la superficie default ~ 0.03",
          abs(ar - 0.03) < 5e-3, f"ar={ar:.4f}")
    # beta real -> Z real -> sin reactancia (no corre f_n)
    z = complex(np.asarray(s.Z(125.0)).ravel()[0])
    check("Z real (reactancia ~ 0, sin corrimiento de f_n)",
          abs(z.imag) < 1e-6 * abs(z.real) + 1e-9, f"Im(Z)={z.imag:.3g}")


def test_A2_kernel_consistency():
    print("\nA2  kernel unificado: default resistivo == camino simple; "
          "RIGIDO (None) reproduce el bug")
    # Todas las caras SIN surface (material no resuelto): surf vacio.
    surf_g, surf_p = {}, {}
    # (i) default RIGIDO (como antes del fix): beta=0 en todas las caras.
    res_rig = ap.compute_xi_shift_with_impedance(
        freqs, phis, loc, vr, tr, groups, surf_g, [], surf_p, V,
        default_surf=None)
    xi_rig = res_rig[0]
    # (ii) default resistivo alpha=0.03 (el fix).
    res_def = ap.compute_xi_shift_with_impedance(
        freqs, phis, loc, vr, tr, groups, surf_g, [], surf_p, V,
        default_surf=AcousticPanel._default_alpha_surface(0.03))
    xi_def = res_def[0]
    # (iii) camino SIMPLE con g2m vacio -> alpha=0.03 por default.
    xi_simple = fm.perturbation_xi_per_mode(
        freqs, phis, loc, vr, tr, groups, {}, V)

    rel = np.max(np.abs(xi_def - xi_simple) / np.maximum(np.abs(xi_simple), 1e-12))
    check("default resistivo == camino simple (xi por modo)",
          rel < 0.03, f"max rel={rel:.3%}")
    ratio = float(np.mean(xi_rig) / max(np.mean(xi_def), 1e-12))
    check("default RIGIDO (None) sub-amortigua fuerte (reproduce el bug)",
          ratio < 0.2, f"xi_rigido/xi_default={ratio:.3f}")
    check("el fix sube el amortiguamiento de las caras no resueltas",
          np.mean(xi_def) > 5.0 * np.mean(xi_rig),
          f"xi_def={np.mean(xi_def):.5f} vs xi_rig={np.mean(xi_rig):.5f}")


def _panel():
    return AcousticPanel(viewer=IsoViewer(),
                         get_surface=lambda: (vr, tr),
                         get_dims_hint=lambda: (Lx, Ly, Lz))


def test_A3_unresolved_detection():
    print("\nA3  _unresolved_material_names: detecta asignado-faltante, "
          "ignora resuelto y sin-asignar")
    panel = _panel()
    gs = panel._get_face_groups()[0]
    known = _custom_mat(name="Marmol test", a=0.01)
    panel._mat_lib.add_material(known)
    walls = [g for g in gs if g.kind == "wall"]
    floor = next(g for g in gs if g.kind == "floor")
    # pared 0: material FALTANTE (no en lib); piso: material resuelto; resto: sin asignar
    panel._face_mat_map.assign(walls[0].signature, "Emplacado del Control Room SMA")
    panel._face_mat_map.assign(floor.signature, "Marmol test")
    miss = panel._unresolved_material_names()
    check("lista el material asignado-faltante",
          "Emplacado del Control Room SMA" in miss, f"miss={sorted(miss)}")
    check("NO lista el material resuelto (en lib)",
          "Marmol test" not in miss)
    check("exactamente 1 faltante (las caras sin asignar no cuentan)",
          len(miss) == 1, f"n={len(miss)}")


def test_B_embed_cache_forward():
    print("\nB  re-guardado: cache-forward re-embebe el material no cargado; "
          "sin cache avisa")
    from main import MainWindow

    class _Status:
        def __init__(self): self.text = ""
        def setText(self, t): self.text = str(t)

    class _FakeMW:
        def __init__(self, panel):
            self.acoustic = panel
            self.status = _Status()

    # Panel con un material ASIGNADO que NO esta en la biblioteca local.
    panel = _panel()
    gs = panel._get_face_groups()[0]
    wall = next(g for g in gs if g.kind == "wall")
    panel._face_mat_map.assign(wall.signature, "Techo de madera machihembrada")
    # Caso 1: el .room traia ese material embebido (cache poblado por el loader).
    panel._embedded_mat_cache = {
        "Techo de madera machihembrada":
            _custom_mat(name="Techo de madera machihembrada", a=0.53).to_dict()}
    mw = _FakeMW(panel)
    ac = MainWindow._serialize_acoustic_state(mw)
    names = {m.get("name") for m in ac.get("embedded_materials", [])}
    check("cache-forward: re-embebe el material no cargado",
          "Techo de madera machihembrada" in names, f"embebidos={sorted(names)}")
    check("no se avisa de perdida cuando el cache lo cubre",
          "no se pudo embeber" not in mw.status.text)

    # Caso 2: SIN cache -> no se puede embeber -> AVISA (no silencioso).
    panel2 = _panel()
    gs2 = panel2._get_face_groups()[0]
    wall2 = next(g for g in gs2 if g.kind == "wall")
    panel2._face_mat_map.assign(wall2.signature, "Material fantasma")
    panel2._embedded_mat_cache = {}
    mw2 = _FakeMW(panel2)
    ac2 = MainWindow._serialize_acoustic_state(mw2)
    names2 = {m.get("name") for m in ac2.get("embedded_materials", [])}
    check("sin cache: el material fantasma NO se embebe",
          "Material fantasma" not in names2)
    check("sin cache: AVISA la perdida (no silencioso)",
          "Material fantasma" in mw2.status.text
          and "no se pudo embeber" in mw2.status.text,
          f"status='{mw2.status.text[:60]}...'")

    # Caso 3: material SI en la biblioteca -> embebido normal, sin aviso.
    panel3 = _panel()
    gs3 = panel3._get_face_groups()[0]
    wall3 = next(g for g in gs3 if g.kind == "wall")
    m_ok = _custom_mat(name="Panel cargado OK", a=0.42)
    panel3._mat_lib.add_material(m_ok)
    panel3._face_mat_map.assign(wall3.signature, "Panel cargado OK")
    panel3._embedded_mat_cache = {}
    ac3 = MainWindow._serialize_acoustic_state(_FakeMW(panel3))
    names3 = {m.get("name") for m in ac3.get("embedded_materials", [])}
    check("material en lib: se embebe por el camino normal",
          "Panel cargado OK" in names3)


def main():
    print("=" * 68)
    print("bench_material_fallback.py  —  fallback alpha=0.03 + embebido robusto")
    print("=" * 68)
    test_A1_default_surface()
    test_A2_kernel_consistency()
    test_A3_unresolved_detection()
    test_B_embed_cache_forward()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
