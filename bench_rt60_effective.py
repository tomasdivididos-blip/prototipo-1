"""Bench del RT60 efectivo por banda (Etapa 2a de la perturbacion, v2.24).

Nucleo `modal_metrics.rt60_by_band_from_modal_decay` (+ `_t30_of_decay`) y su
cableo en `AcousticPanel._effective_rt60_by_band` / `_rt60_callable` /
`_perturbation_rt60_by_band`.

Oraculos:
  T1  banda MONO-exponencial (delta uniforme): T30 == 6.91/delta EXACTO.
  T2  banda MULTI-exponencial: T30 > 6.91/<delta> (la cola la manda el modo
      lento); auto-consistencia con una grilla mas fina.
  T3  banda vacia -> no aparece en el dict.
  T4  asignacion de modos a bandas de octava (bordes en fc/sqrt2, fc*sqrt2).
  T5  REGRESION: con modelo a36, el RT efectivo == Sabine por cara BIT A BIT.
  T6  con perturbacion, blend: T30 en la banda modal + Sabine por encima.
  T7  f_cross via `_rt60_callable` cambia entre a36 y perturbacion.
  T8  sin modos, perturbacion cae a Sabine.
  T9  caso con SOLVE REAL: T30 > media-de-tasas y banda baja > Sabine.

Correr:  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python bench_rt60_effective.py
"""
from __future__ import annotations

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtWidgets import QApplication

import modal_metrics as mm
import face_materials as fm
import acoustic_analysis as aa
from geometry import make_room
from viewer import IsoViewer
from acoustic_panel import AcousticPanel

_app = QApplication.instance() or QApplication([])

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


class _UniformMat:
    def __init__(self, a): self._a = float(a); self.name = f"a={a}"
    def alpha(self, f): return self._a


print(__doc__.splitlines()[0])
print()

# ---------------------------------------------------------------------------
print("T1  banda mono-exponencial: T30 == 6.91/delta exacto")
for d0 in (2.0, 8.0, 25.0):
    freqs = np.array([120.0, 125.0, 130.0])       # 3 modos, misma tasa
    delta = np.full(3, d0)
    rt = mm.rt60_by_band_from_modal_decay(freqs, delta, bands=(125,))
    rt125 = rt.get(125, np.nan)
    ref = 6.91 / d0
    check(f"T1 delta={d0}: T30 coincide con 6.91/delta",
          abs(rt125 / ref - 1) < 2e-3, f"T30={rt125:.4f} vs 6.91/d={ref:.4f}")

# ---------------------------------------------------------------------------
print("\nT2  banda multi-exponencial: T30 > media de tasas (cola lenta)")
freqs = np.array([110.0, 120.0, 130.0, 140.0, 150.0, 160.0])
delta = np.array([4.0, 6.0, 8.0, 10.0, 14.0, 18.0])
rt = mm.rt60_by_band_from_modal_decay(freqs, delta, bands=(125,))[125]
rt_meanrate = 6.91 / delta.mean()
check("T2 T30 supera 6.91/<delta>", rt > rt_meanrate * 1.02,
      f"T30={rt:.4f} vs 6.91/<d>={rt_meanrate:.4f} (ratio {rt/rt_meanrate:.3f})")
check("T2b T30 no supera el RT del modo mas lento", rt <= 6.91 / delta.min() + 1e-6,
      f"T30={rt:.4f} <= 6.91/dmin={6.91/delta.min():.4f}")
# auto-consistencia: grilla temporal mas fina no mueve el T30 > 0.5%
rt_fine = mm._t30_of_decay(delta, np.ones_like(delta), n_t=16000)
check("T2c estable al refinar la grilla temporal", abs(rt / rt_fine - 1) < 5e-3,
      f"n_t=4000 {rt:.4f} vs n_t=16000 {rt_fine:.4f}")

# ---------------------------------------------------------------------------
print("\nT3-T4  seleccion de bandas")
freqs = np.array([40.0, 90.0, 200.0])   # 40->31.5?, 90->63/125 borde, 200->250
delta = np.array([5.0, 5.0, 5.0])
rt = mm.rt60_by_band_from_modal_decay(freqs, delta)
check("T3 banda sin modos no aparece", 500 not in rt and 1000 not in rt,
      f"bandas={sorted(rt.keys())}")
# 90 Hz cae en la banda de 125 (88.4-176.8), NO en 63 (44.5-89.1)
check("T4 90 Hz -> banda 125 (no 63)", 125 in rt and 63 not in rt,
      f"bandas={sorted(rt.keys())}")

# ---------------------------------------------------------------------------
print("\nT5-T8  cableo en el panel")
L, W, H = 5.0, 4.0, 3.0
viewer = IsoViewer()
v, t, _e, _n = make_room(width=L, length=W, height=H, n_walls=4)
panel = AcousticPanel(viewer=viewer, get_surface=lambda: (v, t),
                      get_dims_hint=lambda: (L, W, H))
panel._log = lambda *a, **k: None
panel.apply_zone_materials("Hormigón visto", "Hormigón visto", "Hormigón visto")
groups, gv, gt = panel._get_face_groups()
V = aa.compute_mesh_volume(gv, gt)
g2m = panel._group_to_material_dict(groups)
sab = panel._sabine_rt60(V, groups, g2m)

# T5: modelo a36 -> efectivo == Sabine bit a bit
panel._damping_model = "a36"
eff_a36, src_a36 = panel._effective_rt60_by_band(V, groups, g2m)
check("T5 a36 reduce EXACTO a Sabine",
      src_a36 == "sabine" and eff_a36 == sab, f"src={src_a36}")

# modal_result sintetico: modos hasta ~200 Hz con decays crecientes
freqs = np.array([55.0, 70.0, 95.0, 120.0, 150.0, 185.0, 210.0])
xi = np.array([0.010, 0.011, 0.012, 0.013, 0.015, 0.017, 0.018])
panel.modal_result = types.SimpleNamespace(freqs=freqs)
panel._xi_per_mode = xi
panel._damping_model = "perturbation"
eff_p, src_p = panel._effective_rt60_by_band(V, groups, g2m)
# bandas modales presentes: 63 (55,70), 125 (95,120,150), 250 (185,210)
delta = xi * 2 * np.pi * freqs
pert_ref = mm.rt60_by_band_from_modal_decay(freqs, delta)
modal_bands = set(pert_ref.keys())
check("T6 src = perturbacion+sabine", src_p == "perturbacion+sabine")
check("T6b banda modal usa T30 (difiere de Sabine)",
      all(abs(eff_p[b] - sab[b]) > 1e-6 for b in modal_bands),
      f"modales={sorted(modal_bands)}")
check("T6c banda por encima de los modos usa Sabine (regimen difuso)",
      all(eff_p[b] == sab[b] for b in sab if b not in modal_bands),
      f"difusas={sorted(b for b in sab if b not in modal_bands)}")
check("T6d el valor modal coincide con el nucleo",
      all(abs(eff_p[b] - pert_ref[b]) < 1e-9 for b in modal_bands))

# T7: f_cross via el callable cambia entre modelos
panel._damping_model = "a36"
cb_a = panel._rt60_callable()
panel._damping_model = "perturbation"
cb_p = panel._rt60_callable()
f_probe = 120.0
check("T7 el callable RT(f) difiere entre a36 y perturbacion en la banda modal",
      cb_a is not None and cb_p is not None
      and abs(cb_a(f_probe) - cb_p(f_probe)) > 1e-4,
      f"RT(120): a36={cb_a(f_probe):.3f} vs pert={cb_p(f_probe):.3f}")

# T8: sin modos, perturbacion cae a Sabine
panel.modal_result = None
eff_nm, src_nm = panel._effective_rt60_by_band(V, groups, g2m)
check("T8 sin modos, perturbacion cae a Sabine",
      src_nm == "sabine" and eff_nm == sab)

# ---------------------------------------------------------------------------
print("\nT9  SOLVE REAL: T30 > media de tasas y banda baja > Sabine")
vr, tr, _e2, _n2 = make_room(width=L, length=W, height=H, n_walls=4)
modal = aa.run_fem_modal(vr, tr, n_modes=120, n_per_meter=4.0)
grp = fm.group_faces_by_planar_region(vr, tr)
Vr = aa.compute_mesh_volume(vr, tr)
alpha = 0.10
g2m_u = {g.signature: _UniformMat(alpha) for g in grp}
xi_r = fm.perturbation_xi_per_mode(modal.freqs, modal.phis, modal.locator,
                                   vr, tr, grp, g2m_u, Vr, subdiv=3)
f_r = np.asarray(modal.freqs, dtype=float)
d_r = xi_r * 2 * np.pi * f_r
rt_pert = mm.rt60_by_band_from_modal_decay(f_r, d_r)
rt_sab = 0.161 * Vr / (alpha * 2 * (L*W + W*H + L*H))
# comparar en una banda con varios modos (125 o 250)
band = 125 if 125 in rt_pert else 250
m = (f_r >= band/np.sqrt(2)) & (f_r < band*np.sqrt(2))
rt_meanrate = 6.91 / d_r[m].mean()
check(f"T9 banda {band}: T30 > media de tasas",
      rt_pert[band] > rt_meanrate,
      f"T30={rt_pert[band]:.3f} vs 6.91/<d>={rt_meanrate:.3f}")
# banda mas baja disponible: debe superar a Sabine (axiales suenan mas)
band_lo = min(rt_pert.keys())
check(f"T9b banda mas baja ({band_lo}) suena mas que Sabine",
      rt_pert[band_lo] > rt_sab,
      f"T30={rt_pert[band_lo]:.3f} > Sabine={rt_sab:.3f} "
      f"(+{100*(rt_pert[band_lo]/rt_sab-1):.0f}%)")

# ---------------------------------------------------------------------------
print("\nT10-T12  Etapa 2b: f_Schroeder de dos pasadas")
# Panel nuevo con material asignado uniforme (reflectante en graves).
viewer2 = IsoViewer()
vb, tb, _e3, _n3 = make_room(width=L, length=W, height=H, n_walls=4)
p2 = AcousticPanel(viewer=viewer2, get_surface=lambda: (vb, tb),
                   get_dims_hint=lambda: (L, W, H))
_logs = []
p2._log = lambda *a, **k: _logs.append(" ".join(str(x) for x in a))
p2.apply_zone_materials("Alfombra fina", "Yeso pintado", "Yeso pintado")

# T10: PRE-solve (sin modos) -> Sabine, aunque el modelo sea perturbacion.
p2._damping_model = "perturbation"
p2.modal_result = None
ctx_pre = p2._schroeder_context()
check("T10 pre-solve: rt_src = sabine (Pass 1, sin delta_n)",
      ctx_pre is not None and ctx_pre["rt_src"] == "sabine",
      f"rt_src={ctx_pre['rt_src']}, f_S={ctx_pre['fs']:.0f} Hz")
fs_sabine = ctx_pre["fs"]

# POST-solve: inyectar un solve real + xi de perturbacion del panel.
gb, vgb, tgb = p2._get_face_groups()
mr = aa.run_fem_modal(vgb, tgb, n_modes=80, n_per_meter=4.0)
p2.modal_result = mr
p2._xi_per_mode = p2._compute_xi_from_materials()   # perturbacion (modelo activo)
ctx_post = p2._schroeder_context()
check("T11 post-solve: rt_src = perturbacion+sabine (Pass 2)",
      ctx_post is not None and ctx_post["rt_src"] == "perturbacion+sabine",
      f"rt_src={ctx_post['rt_src']}, f_S={ctx_post['fs']:.0f} Hz")
fs_pert = ctx_post["fs"]
# Direccion fisica: el T30 alarga los graves -> f_S sube (o al menos no baja).
check("T11b f_S de perturbacion >= f_S de Sabine (graves más largos)",
      fs_pert >= fs_sabine * 0.999,
      f"f_S pert={fs_pert:.0f} vs Sabine={fs_sabine:.0f} Hz "
      f"({100*(fs_pert/fs_sabine-1):+.0f}%)")

# T12: el chequeo de cobertura avisa si la malla (Sabine) sub-cubre f_S.
mr.mesh_info = dict(getattr(mr, "mesh_info", {}) or {})
mr.mesh_info["h_max"] = 2.0            # -> f_max ~28 Hz, muy por debajo de f_S
_logs.clear()
p2._post_solve_schroeder_coherence()
warned = any("sub-cubierta" in s for s in _logs)
label_ok = p2.lbl_schroeder.text().startswith("f_Schroeder")
check("T12 post-solve avisa sub-cobertura y refresca el label",
      warned and label_ok,
      f"warned={warned}, label='{p2.lbl_schroeder.text()}'")

# ---------------------------------------------------------------------------
print(f"\nRESULTADO: {len(_PASS)}/{len(_PASS)+len(_FAIL)} OK")
if _FAIL:
    for n in _FAIL:
        print("   FALLO:", n)
    raise SystemExit(1)
