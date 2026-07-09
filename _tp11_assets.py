# -*- coding: utf-8 -*-
"""Genera assets del TP11: datos de validacion (Tabla 1) + diagrama (Figura 1)."""
import numpy as np
import json, os

OUT_DIR = r"C:\Users\aceve\Tomas\UNTREF\IMA"
C0 = 343.0

# ---------------------------------------------------------------------------
# TABLA 1: modos analiticos vs FEM para la caja 5 x 4 x 3
# ---------------------------------------------------------------------------
Lx, Ly, Lz = 5.0, 4.0, 3.0

def analytic_modes(Lx, Ly, Lz, fmax=130.0, nmax=6):
    out = []
    for nx in range(nmax):
        for ny in range(nmax):
            for nz in range(nmax):
                if nx == ny == nz == 0:
                    continue
                f = 0.5 * C0 * np.sqrt((nx/Lx)**2 + (ny/Ly)**2 + (nz/Lz)**2)
                if f <= fmax:
                    out.append((f, (nx, ny, nz)))
    out.sort()
    return out

ana = analytic_modes(Lx, Ly, Lz)

import geometry, acoustic_analysis as aa
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
mr = aa.run_fem_modal(v, t, n_modes=40, n_per_meter=2.0)
fem = np.asarray(mr.freqs, float)
fem = fem[fem > 1.0]        # descarta el modo ~0 Hz
fem.sort()

# Emparejar cada analitico con el FEM mas cercano, hasta la validez (~114 Hz)
rows = []
for f_a, mode in ana:
    if f_a > 114.0:
        break
    j = int(np.argmin(np.abs(fem - f_a)))
    f_f = float(fem[j])
    err = 100.0 * (f_f - f_a) / f_a
    rows.append({"mode": "".join(str(m) for m in mode),
                 "ana": round(f_a, 2), "fem": round(f_f, 2),
                 "err": round(err, 2)})

errs = [abs(r["err"]) for r in rows]
print("Tabla 1 rows:", len(rows), "| err medio %.2f  max %.2f" %
      (float(np.mean(errs)), float(np.max(errs))))
for r in rows:
    print(r)

with open(os.path.join(OUT_DIR, "_tabla1.json"), "w", encoding="utf-8") as fh:
    json.dump({"rows": rows,
               "err_mean": round(float(np.mean(errs)), 2),
               "err_max": round(float(np.max(errs)), 2),
               "box": [Lx, Ly, Lz],
               "n_valid_fem": int((fem <= 114.0).sum())}, fh, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# FIGURA 1: diagrama de arquitectura de modulos
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(9.2, 5.6), dpi=200)
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

def box(x, y, w, h, text, fc, ec, fs=8.5, tc="#1a1a1a"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2",
                       linewidth=1.2, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(p)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fs, color=tc, zorder=3, wrap=True)

# Titulos de capa
ax.text(50, 96, "Capa de interfaz  (PyQt5 / pyqtgraph OpenGL)",
        ha="center", va="center", fontsize=10, fontweight="bold", color="#0b3d66")
ax.text(50, 50.5, "Núcleo de cómputo puro  (numpy · scipy)",
        ha="center", va="center", fontsize=10, fontweight="bold", color="#5a3a0b")

# Capa GUI (arriba)
gui = "#dbeafe"; gui_e = "#2563eb"
box(3, 78, 22, 12, "main.py\n(orquestación, .room,\nundo/redo global)", gui, gui_e)
box(27.5, 78, 20, 12, "acoustic_panel\n(pestaña Acústica)", gui, gui_e)
box(50, 78, 20, 12, "prediction_panel\n(pestaña Predicción)", gui, gui_e)
box(72.5, 78, 24.5, 12, "viewer / acoustic_viewer\n(visor 3D, fuentes,\nreceptor)", gui, gui_e)
box(20, 62, 60, 10,
    "Diálogos: shape_dialog · section_dialog · materiales · FRF · SBIR",
    "#eff6ff", gui_e, fs=8)

# Capa núcleo (abajo)
core = "#fef3c7"; core_e = "#d97706"
row_y = 30
box(2, row_y, 15, 12, "geometry\n(planta, lofting,\nquiebres)", core, core_e, fs=7.8)
box(18.5, row_y, 15, 12, "acoustic_mesh\nmesh_router\n(malla voxel)", core, core_e, fs=7.8)
box(35, row_y, 15, 12, "acoustic_fem\n(K, M, eigsh,\nFRF, KDTree)", core, core_e, fs=7.8)
box(51.5, row_y, 15, 12, "modal_metrics\n(FoM_flat/esp,\ncruce modal)", core, core_e, fs=7.8)
box(68, row_y, 13.5, 12, "sbir\n(fuentes\nimagen)", core, core_e, fs=7.8)
box(83, row_y, 14.5, 12, "sources · frd\n(monopolos,\nQ(f))", core, core_e, fs=7.8)

box(14, 13, 30, 11, "prediction\n(3 ejes · scoring · candidatos)", "#fde68a", core_e, fs=8.2)
box(46, 13, 26, 11, "location_opt\n(semillas + refinamiento)", "#fde68a", core_e, fs=8.2)
box(74, 13, 23.5, 11, "face_materials\n(RT60, α por cara)", "#fde68a", core_e, fs=8.2)

# Flecha grande GUI -> nucleo
ar = FancyArrowPatch((50, 61.5), (50, 43), arrowstyle="-|>", mutation_scale=22,
                     linewidth=2.2, color="#64748b", zorder=1)
ax.add_patch(ar)
ax.text(52.5, 52.5, "invoca", fontsize=8, color="#475569", style="italic")

# Linea divisoria de capas
ax.plot([1, 99], [55.5, 55.5], color="#cbd5e1", linewidth=1, linestyle="--", zorder=0)

plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig1_arquitectura.png"),
            bbox_inches="tight", facecolor="white")
print("Figura 1 guardada -> fig1_arquitectura.png")
