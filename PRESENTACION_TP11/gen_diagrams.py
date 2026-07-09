# -*- coding: utf-8 -*-
"""Diagramas, figuras de libros redibujadas, tabla de fuentes y copia de assets."""
import os, shutil, textwrap
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Ellipse

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, 'assets'); os.makedirs(A, exist_ok=True)
IMA = r'C:\Users\aceve\Tomas\UNTREF\IMA'

# ---------------------------------------------------------------- signal flow
def flow(path, labels, fc='#eaf1fb', ec='#2b6cb0', figw=11):
    n = len(labels); fig, ax = plt.subplots(figsize=(figw, 2.4), dpi=200); ax.axis('off')
    ax.set_xlim(0, 100); ax.set_ylim(0, 26)
    w = 90.0 / n; gap = w * 0.16; bw = w - gap; h = 15; y = 6
    for i, lab in enumerate(labels):
        x = 5 + i * w + gap / 2
        ax.add_patch(FancyBboxPatch((x, y), bw, h, boxstyle='round,pad=0.4,rounding_size=2',
                     linewidth=1.3, edgecolor=ec, facecolor=fc))
        ax.text(x + bw / 2, y + h / 2, lab, ha='center', va='center', fontsize=8.4, color='#12233b')
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((x + bw, y + h / 2), (x + w + gap / 2, y + h / 2),
                         arrowstyle='-|>', mutation_scale=13, linewidth=1.5, color='#5a6b7b'))
    fig.savefig(path, bbox_inches='tight', facecolor='white'); plt.close(fig)

flow(os.path.join(A, 'flow_mesh.png'),
     ['Geometría\n(recinto)', 'Grilla voxel\n(n_per_meter)', 'Freudenthal\nhex -> 6 tets',
      'Inside/outside\n(raycast)', 'Filtro de\nslivers', 'Malla + validez\nf = c/(6·h)'])
flow(os.path.join(A, 'flow_fem.png'),
     ['Malla\n(nodos, tets)', 'Ensamble K, M\n(einsum)', 'eigsh\nshift-invert',
      'Modos\n(f_n, phi_n)', 'Clip validez\n+ KDTree', 'FRF / campo /\nmétricas'],
     fc='#fef3e7', ec='#c05621')

# ---------------------------------------------------------------- code snippet
def code_img(path, lines, fs=12.5):
    h = 0.34 * len(lines) + 0.5
    fig = plt.figure(figsize=(9.2, h), dpi=200); ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.add_patch(Rectangle((0.005, 0.02), 0.99, 0.96, facecolor='#f4f6f8',
                 edgecolor='#c3ccd6', linewidth=1.2))
    y = 0.9
    for ln in lines:
        col = '#7a8896' if ln.strip().startswith('#') else '#173049'
        ax.text(0.02, y, ln, fontsize=fs, family='monospace', va='top', ha='left', color=col)
        y -= 0.9 / len(lines)
    fig.savefig(path, bbox_inches='tight', facecolor='white'); plt.close(fig)

code_img(os.path.join(A, 'code_assembly.png'), [
 "# Ensamble vectorizado de K y M (P1, sin bucle sobre elementos)",
 "grads = ...                       # (Ne, 4, 3)  grad de N por tet",
 "Ke = np.einsum('eij,ekj->eik', grads, grads) * vol[:,None,None]",
 "Me = vol[:,None,None] * M_ref     # masa consistente (V/20, V/10)",
 "K  = coo_matrix((Ke.ravel(), (rows, cols)))   # global sparse",
 "w, phi = eigsh(K, M=M, sigma=0, which='LM')    # shift-invert",
])

# ---------------------------------------------------------------- Bolt area
fig, ax = plt.subplots(figsize=(7.4, 5.2), dpi=200)
ax.add_patch(Ellipse((1.85, 1.42), 1.15, 0.62, angle=18, facecolor='#bfe0c2',
             edgecolor='#3a8f4a', alpha=0.55, linewidth=1.5, zorder=1))
ax.text(1.85, 1.66, 'Región favorable\n(Bolt, 1946)', ha='center', va='center',
        fontsize=10, color='#256b31', zorder=2)
ratios = {'Louden': (1.90, 1.40), 'Bolt': (1.59, 1.26), 'Sepmeyer': (2.33, 1.60),
          'Cox': (1.86, 1.56), 'BBC/Rindel': (1.40, 1.14)}
for name, (lh, wh) in ratios.items():
    ax.plot(lh, wh, 'o', ms=10, color='#c0392b', zorder=3)
    ax.annotate(name, (lh, wh), textcoords='offset points', xytext=(8, 6),
                fontsize=10, color='#1a1a1a', zorder=4)
ax.set_xlabel('Largo / Alto  (L/H)', fontsize=11)
ax.set_ylabel('Ancho / Alto  (W/H)', fontsize=11)
ax.set_xlim(1.1, 2.6); ax.set_ylim(1.0, 1.8); ax.grid(alpha=0.3)
ax.set_title('Proporciones óptimas en el espacio de ratios', fontsize=12)
ax.text(0.99, -0.15, 'Adaptado de Bolt (1946) y Cox & D\'Antonio (2001).',
        transform=ax.transAxes, ha='right', fontsize=8, style='italic', color='#555')
fig.savefig(os.path.join(A, 'fig_bolt.png'), bbox_inches='tight', facecolor='white'); plt.close(fig)

# ---------------------------------------------------------------- Bonello
fig, axs = plt.subplots(1, 2, figsize=(8.4, 3.4), dpi=200)
bands = ['20', '25', '31', '40', '50', '63', '80', '100']
good = [1, 1, 2, 2, 3, 4, 5, 7]; bad = [1, 3, 2, 2, 5, 3, 6, 6]
for ax, data, tit, ok in [(axs[0], good, 'Cumple (no decreciente)', True),
                          (axs[1], bad, 'No cumple (hay caídas)', False)]:
    ax.bar(bands, data, color=('#4a90d9' if ok else '#d9704a'), edgecolor='#22384f')
    ax.set_title(tit, fontsize=10, color=('#256b31' if ok else '#a23'))
    ax.set_xlabel('banda 1/3 oct [Hz]', fontsize=8.5)
    ax.tick_params(labelsize=8)
    if ax is axs[0]: ax.set_ylabel('nº de modos / banda', fontsize=9)
fig.suptitle('Criterio de Bonello (1981): densidad modal monótona', fontsize=12)
fig.text(0.99, -0.02, 'Esquema según Bonello, JAES (1981).', ha='right', fontsize=8,
         style='italic', color='#555')
fig.tight_layout(rect=[0, 0.02, 1, 0.95])
fig.savefig(os.path.join(A, 'fig_bonello.png'), bbox_inches='tight', facecolor='white'); plt.close(fig)

# ---------------------------------------------------------------- Fazenda
fig, ax = plt.subplots(figsize=(7.6, 4.2), dpi=200)
f = np.linspace(20, 200, 200)
art = 20 + 8 * np.log10(f / 20)        # umbral peor caso (artificial)
mus = art + 9                          # umbral con enmascaramiento (música)
ax.plot(f, art, color='#c0392b', lw=2.2, label='Estímulo "artificial" (peor caso)')
ax.plot(f, mus, color='#2b6cb0', lw=2.2, label='Estímulo "música" (escucha real)')
ax.fill_between(f, art, mus, color='#f0d27a', alpha=0.4)
ax.set_xlabel('Frecuencia [Hz]', fontsize=11)
ax.set_ylabel('Nivel del modo sobre el fondo [dB]', fontsize=10)
ax.set_title('Umbral de audibilidad modal (Fazenda et al., 2015)', fontsize=12)
ax.legend(fontsize=9, loc='upper left'); ax.grid(alpha=0.3)
ax.text(0.99, -0.16, 'Esquema según Fazenda, Avis & Davies, JAES (2015).',
        transform=ax.transAxes, ha='right', fontsize=8, style='italic', color='#555')
fig.savefig(os.path.join(A, 'fig_fazenda.png'), bbox_inches='tight', facecolor='white'); plt.close(fig)

# ---------------------------------------------------------------- tabla fuentes
def table_png(path, title, headers, rows, cw, align, wrap, fig_w=9.2, fs=11):
    s = float(sum(cw)); cwn = [w / s for w in cw]; xe = [0.0]
    for w in cwn: xe.append(xe[-1] + w)
    def wr(t, w): t = str(t); return textwrap.fill(t, w) if (w and len(t) > w) else t
    hh = 1.6; hrows = []
    rows_w = [[wr(c, wrap[i]) for i, c in enumerate(r)] for r in rows]
    for r in rows_w: hrows.append(max(c.count('\n') + 1 for c in r) + 0.7)
    th = 1.7; total = th + hh + sum(hrows)
    H = total * 0.30; fig = plt.figure(figsize=(fig_w, H)); ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off'); ax.set_xlim(0, 1); ax.set_ylim(0, total)
    def cell(x0, x1, y0, y1, fcv, txt, al='center', bold=False, fsz=fs):
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=fcv, edgecolor='#a9c0dd', linewidth=0.9))
        ha = {'center': 'center', 'left': 'left'}[al]
        tx = (x0 + x1) / 2 if al == 'center' else x0 + 0.008
        ax.text(tx, (y0 + y1) / 2, txt, ha=ha, va='center', fontsize=fsz,
                fontweight='bold' if bold else 'normal', color='#151515')
    y = total
    cell(0, 1, y - th, y, '#c6d9ee', title, 'left', True, fs + 1); y -= th
    for c in range(len(headers)):
        cell(xe[c], xe[c + 1], y - hh, y, '#c6d9ee', headers[c], 'center', True);
    y -= hh
    for ri, r in enumerate(rows_w):
        hr = hrows[ri]; bg = '#eef4fb' if ri % 2 else '#ffffff'
        for c in range(len(headers)):
            cell(xe[c], xe[c + 1], y - hr, y, bg, r[c], align[c])
        y -= hr
    ax.add_patch(Rectangle((0, 0), 1, total, fill=False, edgecolor='#20395a', linewidth=2.4))
    fig.savefig(path, dpi=200, bbox_inches='tight', facecolor='white'); plt.close(fig)

table_png(os.path.join(A, 'table_sources.png'),
    'Criterios de predicción: de dónde salen',
    ['Criterio', 'Fuente', 'Uso en el software'],
    [['Proporciones óptimas', 'Bolt (1946); Louden (1971); Sepmeyer (1965);\nCox & D\'Antonio (2001); BBC/Walker', 'RATIO_LIBRARY (5 ternas)'],
     ['Densidad modal no decreciente', 'Bonello, JAES (1981)', 'bonello_score'],
     ['Espaciado modal / FSI', 'Rindel', 'modal_fsi'],
     ['Audibilidad modal', 'Fazenda, Avis & Davies (2015)', 'fazenda_modal_threshold'],
     ['Planitud / consistencia espacial', 'Welti & Devantier (2006); Toole (2017)', 'FoM_flat / FoM_esp'],
     ['Interferencia fuente-frontera', 'Toole (2017); Everest & Pohlmann', 'sbir (fuentes imagen)'],
     ['RT60 objetivo por uso', 'Everest; handbooks de acústica', 'USE_PRESETS']],
    cw=[2.0, 3.4, 2.4], align=['left', 'left', 'left'], wrap=[22, 46, 24], fig_w=9.4, fs=10)

# ---------------------------------------------------------------- copiar reusados
for src in ['fig1_arquitectura.png', 'fig4_frf.png', 'fig5_heatmap_spl.png', 'fig7_ejes.png',
            'tabla1_validacion.png', 'tabla2_ratios.png', 'fig2_editor.png', 'fig3_gui.png',
            'fig6_prediccion.png']:
    s = os.path.join(IMA, src)
    if os.path.exists(s): shutil.copyfile(s, os.path.join(A, src))
    else: print('FALTA', src)

print('diagramas + figuras + tabla + copias OK')
print('assets totales:', len(os.listdir(A)))
