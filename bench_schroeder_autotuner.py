"""Bench del gate de absorcion + coherencia f_Schroeder panel<->auto-tuner (v2.23).

Cubre los tres cambios de la sesion:
  A. `_schroeder_context` es la UNICA fuente de f_S: el label del panel y el
     auto-tuner de malla ya no pueden discrepar (antes: RT de materiales vs
     alpha=0.05 fijo, hasta 2x de diferencia).
  B. El gate detecta "ninguna cara asignada" contando asignaciones EXPLICITAS
     (el FaceMaterialMap siempre devuelve su `default`, asi que el test viejo
     por RT=None nunca disparaba) y recuerda la eleccion por sesion.
  C. Tope de npm 0.5-30 + inversa de Weyl para reportar cobertura honesta
     cuando el presupuesto de modos no llega a f_S.

Correr:  QT_QPA_PLATFORM=offscreen python bench_schroeder_autotuner.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtWidgets import QApplication

import acoustic_analysis as aa
import material_library as ml
from geometry import make_room
from viewer import IsoViewer
from acoustic_panel import AcousticPanel, AbsorptionChoiceDialog

_app = QApplication.instance() or QApplication(sys.argv)

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def make_panel(L=5.0, W=4.0, H=3.0):
    """Panel con un shoebox LxWxH (mismo patron que smoke_test_furniture_ui)."""
    viewer = IsoViewer()
    verts, tris, _e, _n = make_room(width=L, length=W, height=H, n_walls=4)
    p = AcousticPanel(viewer=viewer, get_surface=lambda: (verts, tris),
                      get_dims_hint=lambda: (L, W, H))
    p._log = lambda *a, **k: None          # silencio
    return p, verts, tris


def sabine_fs(V, S, alpha):
    rt = 0.161 * V / (alpha * S)
    return 2000.0 * np.sqrt(rt / V)


print(__doc__.splitlines()[0])
print()

# ---------------------------------------------------------------------------
print("T1-T3  gate: deteccion, memoria y alpha elegido")
panel, verts, tris = make_panel()
groups, _v, _t = panel._get_face_groups()

check("T1 shoebox sin asignar -> 0 grupos asignados",
      panel._n_assigned_groups(groups) == 0,
      f"{panel._n_assigned_groups(groups)}/{len(groups)}")

# Simula que el usuario eligio alpha=0.02 en el gate (sin abrir la ventana).
panel._abs_choice_alpha = 0.02
panel._abs_choice_asked = True
ctx = panel._schroeder_context()
V, S = ctx["V"], ctx["S"]
esperado = sabine_fs(V, S, 0.02)
check("T2 f_S usa el alpha elegido, no el default alfabetico del mapa",
      abs(ctx["fs"] - esperado) < 0.5,
      f"fs={ctx['fs']:.1f} Hz, esperado={esperado:.1f} Hz")

# El gate no vuelve a preguntar (si preguntara, sin GUI colgaria o fallaria).
before = (panel._abs_choice_alpha, panel._abs_choice_asked)
panel._ensure_absorption_choice()
check("T3 el gate no re-pregunta una vez respondido",
      (panel._abs_choice_alpha, panel._abs_choice_asked) == before)

# ---------------------------------------------------------------------------
print("\nT4-T5  el gate por preset/material asigna de verdad")
panel2, _v2, _t2 = make_panel()
ok = panel2.apply_zone_materials("Hormigón visto", "Hormigón visto", "Hormigón visto")
g2, _, _ = panel2._get_face_groups()
check("T4 asignar por zona marca todos los grupos", ok and panel2._n_assigned_groups(g2) == len(g2),
      f"{panel2._n_assigned_groups(g2)}/{len(g2)}")

ctx2 = panel2._schroeder_context()
check("T5 con materiales asignados, f_S sale del RT por bandas",
      "RT de materiales" in ctx2["src_txt"] and ctx2["n_asig"] == len(g2),
      f"src={ctx2['src_txt']}")

# Hormigon (alpha~0.01-0.02 en graves) tiene que dar f_S MUY por encima del
# alpha=0.05 fijo viejo: ese era exactamente el modo de falla silencioso.
fs_viejo = aa.schroeder_frequency(ctx2["V"], ctx2["S"], alpha=0.05)
check("T5b hormigon: f_S real supera holgadamente al α=0.05 fijo viejo",
      ctx2["fs"] > 1.3 * fs_viejo,
      f"real={ctx2['fs']:.0f} Hz vs α=0.05 -> {fs_viejo:.0f} Hz "
      f"(ratio {ctx2['fs']/fs_viejo:.2f}x)")

# ---------------------------------------------------------------------------
print("\nT6-T8  inversa de Weyl (cobertura honesta)")
Vb, Sb = 60.0, 94.0
for n in (50, 200, 500):
    f = AcousticPanel._weyl_freq_for_count(n, Vb, Sb)
    n_back = AcousticPanel._weyl_modal_count(f, Vb, Sb)
    check(f"T6 inversa de Weyl round-trip N={n}", abs(n_back - n) <= 1,
          f"f={f:.1f} Hz -> N={n_back}")

f_lo = AcousticPanel._weyl_freq_for_count(50, Vb, Sb)
f_hi = AcousticPanel._weyl_freq_for_count(500, Vb, Sb)
check("T7 la inversa es monotona", f_hi > f_lo, f"{f_lo:.0f} < {f_hi:.0f} Hz")
check("T8 N=0 devuelve 0 sin explotar",
      AcousticPanel._weyl_freq_for_count(0, Vb, Sb) == 0.0)

# ---------------------------------------------------------------------------
print("\nT9-T10  tope de npm")
check("T9 el spinbox de densidad llega a 30",
      abs(panel.sb_density.maximum() - 30.0) < 1e-9,
      f"max={panel.sb_density.maximum()}")

# alpha=0.01 (piso del catalogo) en un booth chico es el peor caso realista.
Vs, Ss = 2.5 * 2.0 * 2.2, 2 * (2.5 * 2.0 + 2.5 * 2.2 + 2.0 * 2.2)
npm_peor = 6.0 * sabine_fs(Vs, Ss, 0.01) / 343.0
check("T10 el tope 30 cubre la sala mas viva del catalogo en un booth",
      npm_peor <= 30.0, f"npm requerido={npm_peor:.1f}")

# ---------------------------------------------------------------------------
print("\nT11  regresion: con materiales asignados, f_S no cambio vs v2.22")
# El camino de materiales es identico al de v2.16; lo unico que cambio es de
# donde se llama. Se recomputa el punto fijo a mano y tiene que coincidir.
g3, _v3, _t3 = panel2._get_face_groups()
V3 = aa.compute_mesh_volume(_v3, _t3)
rt = panel2._sabine_rt60(V3, g3, panel2._group_to_material_dict(g3))
bands = np.array(sorted(rt), dtype=float)
rts = np.array([rt[b] for b in sorted(rt)], dtype=float)
fs_manual = 2000.0 * np.sqrt(max(float(rts[0]), 1e-3) / V3)
for _ in range(12):
    rt_u = float(np.interp(fs_manual, bands, rts))
    nxt = 2000.0 * np.sqrt(max(rt_u, 1e-3) / V3)
    if abs(nxt - fs_manual) < 0.5:
        fs_manual = nxt
        break
    fs_manual = nxt
check("T11 punto fijo identico al calculo historico",
      abs(ctx2["fs"] - fs_manual) < 0.5,
      f"panel={ctx2['fs']:.2f} vs manual={fs_manual:.2f}")

# ---------------------------------------------------------------------------
print("\nT12  el gate no abre dialogos en headless (offscreen segfaultea)")
panel3, _v4, _t4 = make_panel()
panel3._ensure_absorption_choice()          # si abriera el dialogo, colgaria acá
check("T12 headless -> fallback sin dialogo",
      panel3._abs_choice_asked and panel3._abs_choice_alpha == 0.05,
      f"alpha={panel3._abs_choice_alpha}, txt='{panel3._abs_choice_txt}'")

# ---------------------------------------------------------------------------
print("\nT13  clamp del auto-tuner por presupuesto de modos")
# Replica la decision del auto-tuner sobre la sala de hormigon (f_S alto):
# cubrir f_S pediria miles de modos, asi que se malla para la banda que los
# modos SI cubren. Sin el clamp, subir el tope de npm a 30 haria que una sala
# viva mallara 180k nodos para calcular modos que nunca se van a pedir.
ctx_r = panel2._schroeder_context()
Vr, Sr, fsr = ctx_r["V"], ctx_r["S"], ctx_r["fs"]
n_weyl_fs = AcousticPanel._weyl_modal_count(fsr, Vr, Sr)
n_budget = 500
f_target = AcousticPanel._weyl_freq_for_count(n_budget, Vr, Sr)
check("T13 la sala viva pide muchos mas modos de los que entran",
      n_weyl_fs > n_budget, f"f_S={fsr:.0f} Hz pide ~{n_weyl_fs} modos")
check("T13b el clamp baja el objetivo de malla por debajo de f_S",
      f_target < fsr, f"f_target={f_target:.0f} Hz < f_S={fsr:.0f} Hz")

npm_sin_clamp = 6.0 * fsr / 343.0
npm_con_clamp = 6.0 * f_target / 343.0
check("T13c el clamp mantiene npm en rango util (sin el, se dispara)",
      npm_con_clamp < npm_sin_clamp and npm_con_clamp <= 30.0,
      f"npm {npm_sin_clamp:.1f} -> {npm_con_clamp:.1f} "
      f"(nodos {Vr*npm_sin_clamp**3:.0f} -> {Vr*npm_con_clamp**3:.0f})")

# ---------------------------------------------------------------------------
print("\nT14  el dialogo del gate devuelve los 3 caminos")
# Construir el dialogo es seguro headless; lo que segfaultea es exec_().
dlg = AbsorptionChoiceDialog(panel._mat_lib.names)
dlg.sb_alpha.setValue(0.123)
check("T14 camino α", dlg.choice() == ("alpha", 0.123), f"{dlg.choice()}")
dlg.rb_preset.setChecked(True)
kind, val = dlg.choice()
check("T14b camino preset", kind == "preset" and val in ml.preset_names(), f"{kind}/{val}")
dlg.rb_uniform.setChecked(True)
kind, val = dlg.choice()
check("T14c camino material único", kind == "uniform" and val in panel._mat_lib.names,
      f"{kind}/{val}")

# ---------------------------------------------------------------------------
print("\nT15  el label de absorción sigue los cambios (bug del test visual)")
# Secuencia reportada por el usuario: gate -> "Absorción del 1%" en todas ->
# f_S OK -> cambiar materiales -> f_S cambia PERO el label seguia diciendo 1%.
panel4, _v5, _t5 = make_panel()
panel4.apply_zone_materials("Absorcion del 1%", "Absorcion del 1%", "Absorcion del 1%")
lbl_1 = panel4.lbl_abs_choice.text()
fs_1 = panel4._schroeder_context()["fs"]
# isVisible() siempre da False headless (la ventana nunca se muestra); el que
# refleja el setVisible explicito es isHidden() — mismo patron que el toggle de
# pesos de T8.
check("T15 tras asignar, el label nombra el material",
      "Absorcion del 1%" in lbl_1 and not panel4.lbl_abs_choice.isHidden(), lbl_1)

panel4.apply_zone_materials("Alfombra gruesa", "Panel acústico", "Yeso pintado")
lbl_2 = panel4.lbl_abs_choice.text()
fs_2 = panel4._schroeder_context()["fs"]
check("T15b al cambiar materiales, f_S cambia", abs(fs_2 - fs_1) > 1.0,
      f"{fs_1:.0f} Hz -> {fs_2:.0f} Hz")
check("T15c y el label lo sigue (era el bug)",
      lbl_2 != lbl_1 and "Absorcion del 1%" not in lbl_2, lbl_2)

# Un material distinto por zona -> el label los lista en vez de mentir con uno.
check("T15d con varios materiales, el label los enumera",
      "Alfombra gruesa" in lbl_2 and "Yeso pintado" in lbl_2, lbl_2)

# Asignacion parcial: tiene que avisar cuantas caras quedaron sin asignar.
panel5, _v6, _t6 = make_panel()
g5, _, _ = panel5._get_face_groups()
panel5._face_mat_map.assign(g5[0].signature, "Hormigón visto")
panel5._refresh_abs_choice_label()
check("T15e asignación parcial se reporta como parcial",
      "sin asignar" in panel5.lbl_abs_choice.text(),
      panel5.lbl_abs_choice.text())

# Sin asignaciones y con α elegido -> muestra el α, no un material inventado.
panel6, _v7, _t7 = make_panel()
panel6._abs_choice_alpha = 0.01
panel6._abs_choice_txt = ""
panel6._refresh_abs_choice_label()
check("T15f sin materiales, el label muestra el α elegido",
      "0.010" in panel6.lbl_abs_choice.text(), panel6.lbl_abs_choice.text())

# ---------------------------------------------------------------------------
print("\nT16  Opción C: sin absorción no se muestran números dependientes")
panelC, _vc, _tc = make_panel()
check("T16 sin materiales ni α -> _has_absorption_choice False",
      panelC._has_absorption_choice() is False)
panelC._refresh_materials_summary()
check("T16b el label RT60 dice «asigná absorción»",
      "asigná absorción" in panelC.lbl_rt60.text(), panelC.lbl_rt60.text())
panelC._abs_choice_alpha = 0.10
check("T16c con α elegido -> _has_absorption_choice True",
      panelC._has_absorption_choice() is True)
panelD, _vd, _td = make_panel()
panelD.apply_zone_materials("Hormigón visto", "Hormigón visto", "Hormigón visto")
check("T16d con materiales asignados -> _has_absorption_choice True",
      panelD._has_absorption_choice() is True)
# El gate headless con geometría y sin elegir devuelve True (fallback α=0.05).
panelE, _ve, _te = make_panel()
got = panelE._ensure_absorption_choice()
check("T16e gate headless -> True (fallback α=0.05, sin diálogo)",
      got is True and panelE._abs_choice_alpha == 0.05)

# ---------------------------------------------------------------------------
print("\nT17  Request 2: Calcular f_S auto-carga Nº modos = Weyl(f_S)")
panelW, _vw, _tw = make_panel()
panelW.apply_zone_materials("Hormigón visto", "Hormigón visto", "Hormigón visto")
n_before = panelW.sb_nmodes.value()
fsW = panelW.compute_and_show_schroeder()
ctxW = panelW._schroeder_context()
cap = panelW.sb_nmodes.maximum()
weyl = panelW._weyl_modal_count(ctxW["fs"], ctxW["V"], ctxW["S"])
n_expected = int(min(max(weyl, 2), cap))
check("T17 Nº modos auto-cargado al Weyl de f_S",
      panelW.sb_nmodes.value() == n_expected and n_expected != n_before,
      f"antes={n_before}, después={panelW.sb_nmodes.value()}, Weyl={weyl}, cap={cap}")

# ---------------------------------------------------------------------------
print()
print(f"RESULTADO: {len(_PASS)}/{len(_PASS) + len(_FAIL)} OK")
if _FAIL:
    print("FALLARON: " + ", ".join(_FAIL))
sys.exit(1 if _FAIL else 0)
