# -*- coding: utf-8 -*-
"""Genera todas las ecuaciones del deck como imagenes (mathtext / Computer Modern)."""
import os, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['mathtext.fontset'] = 'cm'
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
os.makedirs(A, exist_ok=True)

def eq(name, tex, fs=30):
    fig = plt.figure(figsize=(9, 1.4)); ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
    ax.text(0.02, 0.5, '$' + tex + '$', fontsize=fs, va='center', ha='left', color='#101010')
    fig.savefig(os.path.join(A, name), dpi=220, bbox_inches='tight', pad_inches=0.08, facecolor='white')
    plt.close(fig)

# Acto 2
eq('eq_wave.png',      r'\dfrac{\partial^2 p}{\partial t^2} = c^2\,\nabla^2 p')
eq('eq_helmholtz.png', r'\nabla^2 p + k^2 p = 0, \qquad k=\omega/c')
eq('eq_eigen.png',     r'\nabla^2 \phi_n + k_n^2\,\phi_n = 0, \qquad \left.\dfrac{\partial \phi_n}{\partial n}\right|_{\partial\Omega}=0')
eq('eq_modes.png',     r'f_{n_x n_y n_z}=\dfrac{c}{2}\sqrt{\left(\dfrac{n_x}{L_x}\right)^2+\left(\dfrac{n_y}{L_y}\right)^2+\left(\dfrac{n_z}{L_z}\right)^2}')
eq('eq_schroeder.png', r'f_S \approx 2000\,\sqrt{\dfrac{T_{60}}{V}}\;\;[\mathrm{Hz}]')
eq('eq_weyl.png',      r'N(f)\approx \dfrac{4\pi V}{3}\dfrac{f^{3}}{c^{3}}+\dfrac{\pi S}{4}\dfrac{f^{2}}{c^{2}}+\dfrac{L}{8}\dfrac{f}{c}')
eq('eq_green.png',     r'p(\mathbf{x},\omega)= i\omega\rho_0\,c^{2}\sum_n \dfrac{\phi_n(\mathbf{x})\,\phi_n(\mathbf{x}_s)\,Q_s}{\omega_n^{2}-\omega^{2}+2i\,\xi_n\,\omega_n\,\omega}')
eq('eq_xi.png',        r'\xi_n = \dfrac{1{,}1}{f_n\,T_{60}(f_n)}')
eq('eq_sabine.png',    r'T_{60}=\dfrac{0{,}161\,V}{\sum_i \alpha_i\,S_i}')
eq('eq_eyring.png',    r'T_{60}=\dfrac{0{,}161\,V}{-S\,\ln(1-\bar{\alpha})}, \qquad \bar{\alpha}=\dfrac{\sum_i\alpha_i S_i}{S}')

# Acto 3 (FEM)
eq('eq_weak.png',      r'K_{ij}=\!\int_\Omega \nabla N_i\!\cdot\!\nabla N_j\,dV,\quad M_{ij}=\!\int_\Omega N_i N_j\,dV')
eq('eq_eigprob.png',   r'K\,\boldsymbol{\phi}_n = \lambda_n\,M\,\boldsymbol{\phi}_n, \qquad f_n=\dfrac{c}{2\pi}\sqrt{\lambda_n}')
eq('eq_fmax.png',      r'f_{\max}=\dfrac{c}{6\,h_{\max}}')

# Acto 5 (metricas)
eq('eq_fom.png',       r'\mathrm{FoM}_{\mathrm{flat}}=\sigma\,[\,\overline{L}_p(f)\,]_{f\leq f_{\max}},\quad \mathrm{FoM}_{\mathrm{esp}}=\langle\,\sigma_{\mathrm{esp}}(f)\,\rangle')
eq('eq_sbir.png',      r'\mathrm{SBIR}(f)=20\log_{10}\dfrac{|\,p_{\mathrm{dir}}+\sum_i p_{\mathrm{img},i}\,|}{|\,p_{\mathrm{dir}}\,|}, \quad f_{\mathrm{notch}}=\dfrac{c}{4d}')
eq('eq_image.png',     r'\mathbf{x}_{\mathrm{img}}=\mathbf{x}_s-2\,[(\mathbf{x}_s-\mathbf{p}_0)\cdot\mathbf{n}]\,\mathbf{n}')

print('ecuaciones OK:', len([f for f in os.listdir(A) if f.startswith('eq_')]))
