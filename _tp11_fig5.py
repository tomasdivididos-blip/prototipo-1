# -*- coding: utf-8 -*-
"""Figura 5 del TP11: mapa de calor de SPL sobre un plano de corte horizontal,
para un modo seleccionado. Usa el pipeline real del solver (FEM modal + campo
de presion + FieldEvaluator), igual que la app."""
import os
import numpy as np

OUT_DIR = r"C:\Users\aceve\Tomas\UNTREF\IMA"

import geometry, acoustic_analysis as aa
import acoustic_fem as af
from sources import OmniSource, SourceArray

# --- recinto de referencia y modos FEM ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
mr = aa.run_fem_modal(v, t, n_modes=40, n_per_meter=3.0)
nodes = np.asarray(mr.nodes, float)
freqs = np.asarray(mr.freqs, float)
phis = mr.phis
loc = mr.locator

mn = nodes.min(axis=0); mx = nodes.max(axis=0)
print("bbox:", mn, mx)

# --- fuente (monopolo, |Q| de una sensibilidad de 90 dB/W/m) ---
xc = 0.5 * (mn[0] + mx[0]); yc = 0.5 * (mn[1] + mx[1])
src_pos = (mn[0] + 0.6, mn[1] + 0.6, 1.2)          # cerca de una esquina
arr = SourceArray()
arr.add(OmniSource(src_pos, Q=1.045e-3 + 0j, label="S1"))

# --- modo a visualizar: el tangencial mas cercano a 55 Hz (patron 2x2 en planta) ---
target = 55.0
idx = int(np.argmin(np.abs(freqs[freqs > 1.0] - target)))
# reindexar sobre el array completo (descartando el ~0 Hz)
valid_idx = np.where(freqs > 1.0)[0]
mode_i = valid_idx[idx]
f_mode = float(freqs[mode_i])
print("modo elegido: indice %d  f = %.2f Hz" % (mode_i, f_mode))

# --- campo de presion complejo en los nodos, a la resonancia del modo ---
p_nodes = af.modal_pressure_field(loc, freqs, phis, arr, f_mode, damping=0.03)

# --- grilla del plano horizontal z = 1.2 m ---
z_cut = 1.2
pad = 0.35
nx, ny = 260, 210
xs = np.linspace(mn[0] - pad, mx[0] + pad, nx)
ys = np.linspace(mn[1] - pad, mx[1] + pad, ny)
XX, YY = np.meshgrid(xs, ys)
pts = np.column_stack([XX.ravel(), YY.ravel(), np.full(XX.size, z_cut)])

p_grid = loc.evaluate_many(p_nodes, pts).reshape(ny, nx)   # complejo, NaN fuera
amp = np.abs(p_grid)
with np.errstate(divide="ignore", invalid="ignore"):
    spl = 20.0 * np.log10(amp / 20e-6)
spl = np.ma.masked_invalid(spl)
print("SPL rango: %.1f a %.1f dB" % (spl.min(), spl.max()))

# --- render estilo app: inferno, fuera del recinto en gris, grilla, ejes en m ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams["font.family"] = "serif"
fig, ax = plt.subplots(figsize=(7.2, 5.8), dpi=200)

cmap = plt.cm.inferno.copy()
cmap.set_bad("#c9c9c9")          # zona fuera del recinto

vmax = float(spl.max()); vmin = vmax - 45.0    # ventana dinamica de 45 dB
im = ax.pcolormesh(XX, YY, spl, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")

# contorno del recinto (planta)
ax.add_patch(Rectangle((mn[0], mn[1]), mx[0] - mn[0], mx[1] - mn[1],
                       fill=False, edgecolor="white", linewidth=1.6, zorder=3))
# fuente y receptor de muestra
ax.plot(src_pos[0], src_pos[1], marker="o", ms=9, mfc="#39d3ff", mec="white",
        mew=1.2, zorder=4)
ax.text(src_pos[0] + 0.12, src_pos[1] + 0.12, "S", color="white", fontsize=11,
        fontweight="bold", zorder=4)

ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
ax.set_aspect("equal")
ax.grid(True, color="white", alpha=0.25, linewidth=0.6)
ax.set_title("Plano horizontal z = %.1f m — modo a f = %.1f Hz" % (z_cut, f_mode),
             fontsize=11)

cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
cb.set_label("SPL [dB re 20 µPa]", fontsize=10)

plt.tight_layout()
out = os.path.join(OUT_DIR, "fig5_heatmap_spl.png")
fig.savefig(out, bbox_inches="tight", facecolor="white")
print("Figura 5 guardada ->", out)
