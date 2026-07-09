"""
verify_examples_c2.py
======================

Recomputa los ejemplos analiticos de EXPLICACION_TECNICA.md §13.2 y §13.3
CON el factor c^2 (v2.11) y los contrasta contra el FEM real, para
re-sincronizar los numeros del doc (estaban en la calibracion pre-c^2).

No es un test permanente; es el script de verificacion puntual de la
re-sincronizacion del 16 jun 2026.
"""
from __future__ import annotations
import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info
from acoustic_fem import build_KM, solve_modes, FieldEvaluator, frequency_response
from sources import SourceArray, OmniSource, q_from_sensitivity, RHO0, C0

Lx, Ly, Lz = 6.0, 8.0, 3.0
XI = 0.03
S_DB = 90.0
Q = q_from_sensitivity(S_DB).real
print(f"Q(90 dB @1kHz) = {Q:.4e} m^3/s")

sv, st, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat")
nodes, tets = build_volume_mesh(sv, st, n_per_meter=3.0)
info = mesh_info(nodes, tets)
xmin, ymin, zmin = nodes.min(axis=0)
xmax, ymax, zmax = nodes.max(axis=0)
cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
print(f"malla: {info['n_nodes']} nodos, {info['n_tets']} tets")
print(f"bbox: x[{xmin:.2f},{xmax:.2f}] y[{ymin:.2f},{ymax:.2f}] z[{zmin:.2f},{zmax:.2f}]")
print(f"centro XY = ({cx:.2f}, {cy:.2f})")

K, M, _ = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
locator = FieldEvaluator(nodes, tets)
print("modos [Hz]:", ", ".join(f"{f:.2f}" for f in freqs))


def phi_lmn(x, y, z, l, m, n):
    """Modo analitico de caja rigida, normalizado int phi^2 dV = 1."""
    u, v, w = x - xmin, y - ymin, z - zmin
    V = Lx * Ly * Lz
    e = lambda i: 1.0 if i == 0 else 2.0
    norm = np.sqrt(e(l) * e(m) * e(n) / V)
    return norm * (np.cos(l*np.pi*u/Lx) * np.cos(m*np.pi*v/Ly) * np.cos(n*np.pi*w/Lz))


def analytic_peak_db(phi_r, phi_s_list, fn):
    """|p| en resonancia del modo, sumando las fuentes (con c^2)."""
    wn = 2*np.pi*fn
    denom = 2j*XI*wn**2
    coupling = sum(phi_s_list)
    p = 1j*wn*RHO0*(C0**2) * phi_r * coupling * Q / denom
    return 20*np.log10(abs(p)/20e-6)


def fem_peak_db(src_positions, f_lo, f_hi, f_target):
    arr = SourceArray([OmniSource(p, sensitivity_dB=S_DB) for p in src_positions])
    fa = np.linspace(f_lo, f_hi, 600)
    H = frequency_response(locator, freqs, phis, arr, (cx-1, cy-2 if abs(cy-2)>0 else cy, 1.5),
                           fa, damping=XI)
    # recortar a una ventana alrededor del modo target
    sel = (fa > f_target-3) & (fa < f_target+3)
    i = np.argmax(np.abs(H[sel]))
    fpk = fa[sel][i]
    return 20*np.log10(np.abs(H[sel][i])/20e-6), fpk


print("\n========== §13.2  modo (1,0,0) ==========")
f100 = (C0/2)*(1/Lx)
print(f"f_100 = {f100:.2f} Hz")
s_pos = (cx-2, cy, 1.5)
r_pos = (cx+2, cy, 1.5)
phi_s = phi_lmn(*s_pos, 1, 0, 0)
phi_r = phi_lmn(*r_pos, 1, 0, 0)
print(f"phi_s={phi_s:+.4f}  phi_r={phi_r:+.4f}")
db_an = analytic_peak_db(phi_r, [phi_s], f100)
print(f"analitico (1 modo, c^2):  {db_an:+.2f} dB SPL")
# FEM
arr = SourceArray([OmniSource(s_pos, sensitivity_dB=S_DB)])
fa = np.linspace(20, 60, 800)
H = frequency_response(locator, freqs, phis, arr, r_pos, fa, damping=XI)
sel = (fa > f100-3) & (fa < f100+3)
i = np.argmax(np.abs(H[sel]))
print(f"FEM (todos los modos):    {20*np.log10(np.abs(H[sel][i])/20e-6):+.2f} dB SPL "
      f"@ {fa[sel][i]:.2f} Hz")

print("\n========== §13.3  modo (1,1,0), 2 fuentes ==========")
f110 = (C0/2)*np.sqrt((1/Lx)**2 + (1/Ly)**2)
print(f"f_110 = {f110:.2f} Hz")
s1 = (cx-2, cy-2, 1.5)
s2 = (cx+2, cy+2, 1.5)
rr = (cx-1, cy-2, 1.5)
ph_s1 = phi_lmn(*s1, 1, 1, 0)
ph_s2 = phi_lmn(*s2, 1, 1, 0)
ph_r  = phi_lmn(*rr, 1, 1, 0)
print(f"phi_s1={ph_s1:+.4f}  phi_s2={ph_s2:+.4f}  phi_r={ph_r:+.4f}")
db1_an = analytic_peak_db(ph_r, [ph_s1], f110)
db2_an = analytic_peak_db(ph_r, [ph_s1, ph_s2], f110)
print(f"analitico 1 fuente: {db1_an:+.2f} dB  | 2 fuentes: {db2_an:+.2f} dB  "
      f"| diff {db2_an-db1_an:+.2f} dB")
# FEM
fa = np.linspace(20, 60, 800)
def fem_db(positions):
    arr = SourceArray([OmniSource(p, sensitivity_dB=S_DB) for p in positions])
    H = frequency_response(locator, freqs, phis, arr, rr, fa, damping=XI)
    sel = (fa > f110-3) & (fa < f110+3)
    i = np.argmax(np.abs(H[sel]))
    return 20*np.log10(np.abs(H[sel][i])/20e-6), fa[sel][i]
db1_fem, f1 = fem_db([s1])
db2_fem, f2 = fem_db([s1, s2])
print(f"FEM 1 fuente: {db1_fem:+.2f} dB @ {f1:.2f}  | 2 fuentes: {db2_fem:+.2f} dB @ {f2:.2f}  "
      f"| diff {db2_fem-db1_fem:+.2f} dB")
