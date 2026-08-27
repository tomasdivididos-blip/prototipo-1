"""
bench_capa0_wiring.py - Etapa 5a: wiring de Capa 0 a la fisica (headless)
=========================================================================
Valida el nucleo del cableado de la Capa 0 al panel, SIN instanciar la GUI (Qt):
la serializacion de construcciones, el camino de perturbacion compleja/extendida
que arma el panel, y la PROPAGACION del corrimiento de f_n a la FRF.
  W1  serializacion: build_surface reconstruye cada spec (JSON round-trip) y
      alpha in [0,1]  (espejo del .room).
  W2  reproducibilidad: run_fem_frf con modal_freqs=None == pasar modal.freqs
      (bit a bit) -> un .room sin construcciones no cambia ni un digito.
  W3  puente material: la superficie resistiva derivada de alpha(f) (caras SIN
      construccion) reproduce el xi de alpha->beta de perturbation_xi_per_mode.
  W4  construccion -> corrimiento: una pared con construccion (perforado+camara)
      da f_new != f_n via perturbation_xi_shift_extended, y ese f_new MUEVE el
      pico de la FRF (la reactancia de pared se ve en la respuesta).
  W5  mezcla: construccion en unas paredes + material en el resto -> xi fisico y
      corrimiento solo donde hay reactancia.

Correr:  QT_QPA_PLATFORM=offscreen python bench_capa0_wiring.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import acoustic_fem as afem
import face_materials as fm
import impedance as imp
from sources import single_source

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# --- superficie resistiva desde alpha(f) de un material (espejo de
#     AcousticPanel._material_surface, para no instanciar la GUI) ---
class _UniformMat:
    def __init__(self, a):
        self._a = float(a)
        self.name = f"a={a}"

    def alpha(self, f):
        return self._a


def material_surface(mat):
    def zf(f, theta=0.0):
        f = np.atleast_1d(np.asarray(f, dtype=float))
        a = np.array([float(mat.alpha(float(ff))) for ff in f])
        beta = fm.beta_from_alpha_random(a)
        return imp.Z0 / np.maximum(beta, 1e-12)
    return imp.SurfaceImpedance(zf, is_locally_reacting=True, label=mat.name)


# --- Setup: shoebox modal ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.6)
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
loc = FieldEvaluator(nodes, tets)
gr = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)


class _Modal:
    """ModalSolution minima para run_fem_frf (solo lo que usa)."""
    def __init__(self):
        self.locator = loc
        self.freqs = freqs
        self.phis = phis


modal = _Modal()
# Fuente y receptor INTERIORES a la malla real (make_room centra el shoebox en el
# origen -> hay que ubicarlos por los bounds, no por dims absolutas).
_lo, _hi = nodes.min(axis=0), nodes.max(axis=0)


def _inside(fr):
    return tuple(_lo + np.asarray(fr) * (_hi - _lo))


src = single_source(_inside((0.30, 0.30, 0.5)))
rcv = _inside((0.72, 0.65, 0.55))
assert loc.evaluate_one(phis[:, 0], rcv) is not None, "receptor fuera de malla"
print(f"  malla {nodes.shape[0]} nodos, {len(freqs)} modos, {len(gr)} paredes")


# ---------------------------------------------------------------------------
print("\nW1  serializacion de construcciones (espejo del .room)")
specs = [
    {"type": "porous", "sigma": 15000, "thickness": 0.05, "air_gap": 0.10},
    {"type": "perforated", "thickness": 2e-3, "hole_diam": 1.5e-3,
     "ratio": 0.02, "cavity_depth": 0.10},
    {"type": "membrane", "mass_per_area": 3.0, "cavity_depth": 0.08},
    {"type": "measured_Zf", "freqs": [50, 200, 500],
     "Z_re": [400, 500, 460], "Z_im": [-300, -80, 40]},
]
fg = np.geomspace(30.0, 2000.0, 60)
w1 = True
for s in specs:
    su = imp.build_surface(json.loads(json.dumps(s)))   # round-trip JSON
    a = su.alpha_random(fg)
    w1 = w1 and bool(np.all(a >= -1e-9) and np.all(a <= 1 + 1e-9))
check("W1 build_surface reconstruye cada spec, alpha in [0,1] (JSON round-trip)",
      w1, f"{len(specs)} tipos")


# ---------------------------------------------------------------------------
print("\nW2  reproducibilidad: modal_freqs=None == modal.freqs (bit a bit)")
xi_uni = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr,
                                     {g.signature: _UniformMat(0.15) for g in gr}, Vr)
r_none = aa.run_fem_frf(modal, src, rcv, 20, 200, 300, damping=xi_uni,
                        modal_freqs=None)
r_expl = aa.run_fem_frf(modal, src, rcv, 20, 200, 300, damping=xi_uni,
                        modal_freqs=freqs)
check("W2 FRF(None) == FRF(modal.freqs) bit a bit",
      np.allclose(r_none.H, r_expl.H, rtol=1e-12, atol=1e-15),
      f"max dif {np.max(np.abs(r_none.H - r_expl.H)):.2e}")


# ---------------------------------------------------------------------------
print("\nW3  puente material: superficie resistiva == alpha->beta")
mat = _UniformMat(0.20)
g2m = {g.signature: mat for g in gr}
xi_ab = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m, Vr, subdiv=3)
surf_mat = {g.signature: material_surface(mat) for g in gr}
xi_ms, f_ms = fm.perturbation_xi_shift_extended(
    freqs, phis, loc, vr, tr, gr, surf_mat, Vr, subdiv=3)
check("W3a xi(superficie material) == xi(alpha->beta) (<1%)",
      np.allclose(xi_ms, xi_ab, rtol=0.01),
      f"max rel {np.max(np.abs(xi_ms/np.maximum(xi_ab,1e-12)-1)):.2e}")
check("W3b sin reactancia (beta real) el corrimiento ~ 0",
      np.allclose(f_ms, freqs, atol=0.2),
      f"max |df| {np.max(np.abs(f_ms-freqs)):.3f} Hz")


# ---------------------------------------------------------------------------
print("\nW4  construccion -> corrimiento de f_n -> mueve la FRF")
# Perforado+camara en TODAS las paredes (reactancia clara).
con = {"type": "perforated", "thickness": 2e-3, "hole_diam": 1.5e-3,
       "ratio": 0.02, "cavity_depth": 0.12}
surf_con = {g.signature: imp.build_surface(con) for g in gr}
xi_c, f_c = fm.perturbation_xi_shift_extended(
    freqs, phis, loc, vr, tr, gr, surf_con, Vr, subdiv=3)
dshift = np.abs(f_c - freqs)
check("W4a construccion produce corrimiento de f_n observable",
      np.max(dshift) > 0.1, f"max |df_n| {np.max(dshift):.2f} Hz")
check("W4b xi fisico (>=0, finito) con la construccion",
      np.all(np.isfinite(xi_c)) and np.all(xi_c >= -1e-9),
      f"xi in [{xi_c.min():.4f},{xi_c.max():.4f}]")
# La FRF con f_n corridas cambia respecto de las rigidas: diferencia RELATIVA
# (invariante a escala; |H| es pequeno en Pa y atol de allclose enganaria).
band = (30.0, 160.0)                                  # banda modal poblada
fa = np.linspace(*band, 1200)
H_rigid = afem.frequency_response(loc, freqs, phis, src, rcv, fa, damping=xi_c)
H_shift = afem.frequency_response(loc, f_c, phis, src, rcv, fa, damping=xi_c)
rel = np.linalg.norm(H_shift - H_rigid) / max(np.linalg.norm(H_rigid), 1e-30)
# pico dominante en banda y su corrimiento
i_pk = int(np.argmax(np.abs(H_rigid)))
i_dom = int(np.argmin(np.abs(freqs - fa[i_pk])))
df_dom = f_c[i_dom] - freqs[i_dom]
check("W4c la FRF cambia al usar f_n corridas (dif relativa > 1%)",
      rel > 0.01, f"dif rel L2 = {100*rel:.1f}%, df modo dominante "
      f"({freqs[i_dom]:.1f}Hz) = {df_dom:+.2f}Hz")


# ---------------------------------------------------------------------------
print("\nW5  mezcla: construccion en unas paredes + material en el resto")
surf_mix = {}
for i, g in enumerate(gr):
    if i < 2:
        surf_mix[g.signature] = imp.build_surface(con)          # con reactancia
    else:
        surf_mix[g.signature] = material_surface(_UniformMat(0.15))  # beta real
xi_mx, f_mx = fm.perturbation_xi_shift_extended(
    freqs, phis, loc, vr, tr, gr, surf_mix, Vr, subdiv=3)
check("W5a mezcla: xi fisico y f_new finito",
      np.all(np.isfinite(xi_mx)) and np.all(xi_mx >= -1e-9)
      and np.all(np.isfinite(f_mx)),
      f"xi in [{xi_mx.min():.4f},{xi_mx.max():.4f}]")
check("W5b hay corrimiento (menor que todo-construccion, mayor que 0)",
      0 < np.max(np.abs(f_mx - freqs)) <= np.max(dshift) + 1e-6,
      f"max |df| mezcla {np.max(np.abs(f_mx-freqs)):.2f} vs todo-con {np.max(dshift):.2f} Hz")


print("\nW6  camino unificado (impedancia por slot) = puente material == alpha->beta")
import absorption_patch as apx
mat2 = _UniformMat(0.20)
g2m2 = {g.signature: mat2 for g in gr}
xi_ref2 = fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m2, Vr)
surf_g = {g.signature: material_surface(mat2) for g in gr}
res6 = apx.compute_xi_shift_with_impedance(
    freqs, phis, loc, vr, tr, gr, surf_g, [], {}, Vr)
xi6, f6 = res6
check("W6a xi(unificado, material) == alpha->beta (<2%, dif de cuadratura)",
      np.max(np.abs(xi6 / np.maximum(xi_ref2, 1e-12) - 1)) < 0.02,
      f"max rel {np.max(np.abs(xi6/np.maximum(xi_ref2,1e-12)-1)):.3e}")
check("W6b sin construccion el corrimiento ~ 0",
      np.allclose(f6, freqs, atol=0.2),
      f"max |df| {np.max(np.abs(f6-freqs)):.3f} Hz")


print("\nW7  construccion en un PARCHE se rutea (corrimiento donde esta el parche)")
# parche que cubre buena parte de una pared
gwall = next(g for g in gr if abs(g.normal[2]) < 0.5)     # una pared vertical
p = apx.make_patch(gwall, -10.0, -10.0, 10.0, 10.0, material_name="", label="test")
con_p = imp.build_surface({"type": "perforated", "thickness": 2e-3,
                           "hole_diam": 1.5e-3, "ratio": 0.02, "cavity_depth": 0.12})
surf_g0 = {g.signature: material_surface(mat2) for g in gr}
# (a) parche con MATERIAL (beta real) -> sin corrimiento
xi_pm, f_pm = apx.compute_xi_shift_with_impedance(
    freqs, phis, loc, vr, tr, gr, surf_g0, [p],
    {p.key: material_surface(mat2)}, Vr)
# (b) parche con CONSTRUCCION -> corrimiento
xi_pc, f_pc = apx.compute_xi_shift_with_impedance(
    freqs, phis, loc, vr, tr, gr, surf_g0, [p], {p.key: con_p}, Vr)
check("W7a parche con material: corrimiento ~ 0",
      np.allclose(f_pm, freqs, atol=0.2),
      f"max |df| {np.max(np.abs(f_pm-freqs)):.3f} Hz")
check("W7b parche con construccion: corrimiento observable",
      np.max(np.abs(f_pc - freqs)) > 0.1,
      f"max |df| {np.max(np.abs(f_pc-freqs)):.2f} Hz")


print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
raise SystemExit(1 if _FAIL else 0)
