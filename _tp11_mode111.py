# -*- coding: utf-8 -*-
"""Heatmap del modo (1,1,1): MISMO recinto y MISMA fuente que fig5, corte vertical."""
import os
import numpy as np
OUT = r"C:\Users\aceve\Downloads\PRESENTACION_TP11\assets"
import geometry, acoustic_analysis as aa
import acoustic_fem as af
from sources import OmniSource, SourceArray

Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
mr = aa.run_fem_modal(v, t, n_modes=40, n_per_meter=3.0)
nodes = np.asarray(mr.nodes, float); freqs = np.asarray(mr.freqs, float)
phis = mr.phis; loc = mr.locator
mn = nodes.min(axis=0); mx = nodes.max(axis=0)

src_pos = (mn[0] + 0.6, mn[1] + 0.6, 1.2)          # MISMA fuente que fig5
arr = SourceArray(); arr.add(OmniSource(src_pos, Q=1.045e-3 + 0j, label="S1"))

# modo (1,1,1): seleccionar por CORRELACION con la forma analitica (robusto
# frente a modos vecinos en frecuencia como el (2,1,0)).
f111 = 0.5 * 343.0 * np.sqrt((1/Lx)**2 + (1/Ly)**2 + (1/Lz)**2)
phi_ana = (np.cos(np.pi*(nodes[:,0]-mn[0])/Lx) *
           np.cos(np.pi*(nodes[:,1]-mn[1])/Ly) *
           np.cos(np.pi*(nodes[:,2]-mn[2])/Lz))
phi_ana /= np.linalg.norm(phi_ana)
corr = []
for k in range(phis.shape[1]):
    pk = phis[:, k].real; nk = np.linalg.norm(pk)
    corr.append(abs(phi_ana @ pk) / nk if nk > 0 else 0.0)
mode_i = int(np.argmax(corr)); f_mode = float(freqs[mode_i])
print("f(1,1,1) analitico=%.2f Hz -> FEM (por correlacion)=%.2f Hz  corr=%.3f"
      % (f111, f_mode, corr[mode_i]))

# forma modal (limpia); |phi| normalizado
p_nodes = af.mode_shape_field(phis, mode_i)

# --- corte VERTICAL XZ en y = y_fuente (para ver la estructura en z) ---
y_cut = src_pos[1]
pad = 0.35; nx, nz = 260, 170
xs = np.linspace(mn[0]-pad, mx[0]+pad, nx)
zs = np.linspace(mn[2]-0.15, mx[2]+0.15, nz)
XX, ZZ = np.meshgrid(xs, zs)
pts = np.column_stack([XX.ravel(), np.full(XX.size, y_cut), ZZ.ravel()])
p_grid = loc.evaluate_many(p_nodes, pts).reshape(nz, nx)
amp = np.abs(np.real(p_grid))
m = np.nanmax(amp)
if m > 0: amp = amp / m
amp = np.ma.masked_invalid(amp)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.family'] = 'serif'
fig, ax = plt.subplots(figsize=(7.2, 5.2), dpi=200)
cmap = plt.cm.inferno.copy(); cmap.set_bad('#c9c9c9')
im = ax.pcolormesh(XX, ZZ, amp, cmap=cmap, vmin=0.0, vmax=1.0, shading='auto')
ax.add_patch(Rectangle((mn[0], mn[2]), mx[0]-mn[0], mx[2]-mn[2], fill=False,
                       edgecolor='white', linewidth=1.6, zorder=3))
ax.plot(src_pos[0], src_pos[2], marker='o', ms=9, mfc='#39d3ff', mec='white', mew=1.2, zorder=4)
ax.text(src_pos[0]+0.12, src_pos[2]+0.12, 'S', color='white', fontsize=11, fontweight='bold', zorder=4)
ax.set_xlabel('x [m]'); ax.set_ylabel('z [m]'); ax.set_aspect('equal')
ax.grid(True, color='white', alpha=0.25, linewidth=0.6)
ax.set_title('Forma modal (1,1,1) - corte vertical XZ (y = %.1f m), f = %.1f Hz' % (y_cut, f_mode), fontsize=10.5)
cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label('|φ| normalizado', fontsize=10)
plt.tight_layout()
out = os.path.join(OUT, 'fig_mode111.png')
fig.savefig(out, bbox_inches='tight', facecolor='white')
print('guardado ->', out)
