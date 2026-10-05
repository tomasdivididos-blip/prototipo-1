"""Bench F5: validación física del solver sparse contra el TP7 Control Room.

La sala TP7 (6x8x3, `TP 7/recinto.room`) tiene 6 RIRs medidas
(`TP 7/RIRs Control Room/`). Limitación de la medición (documentada, T2): las RIRs
son de 0.19 s → la FRF tiene resolución df≈5.3 Hz, y arriba de ~50 Hz los modos
están MÁS JUNTOS que eso (solapamiento modal M>1), así que NO se puede extraer el
amortiguamiento ξ por modo sub-Schroeder de estas RIRs (coincide con la
calibración previa, memoria calibracion-rirs). Lo que SÍ se valida:

  T1  las frecuencias modales FEM de recinto.room == la caja analítica (axiales)
      para los modos bajos bien separados (la geometría/malla reproduce la sala).
  T2  el pico modal medido más limpio de la RIR coincide con un modo FEM; y se
      documenta la limitación de resolución (df > espaciado modal arriba de 50 Hz).
  T3  el solver SPARSE (PAL) == el modelo de PERTURBACIÓN (el default ya validado
      contra medición, FLAIR 1.42%) sobre la GEOMETRÍA REAL de recinto.room, en
      régimen perturbativo (<2%). Combinado con que el sparse reproduce el QEP
      nodal a máquina (bench_qep_sparse), el solver hereda la validación empírica
      del modelo forward.

Correr:  QT_QPA_PLATFORM=offscreen python bench_qep_f5.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob
import itertools
import json
import numpy as np
import scipy.sparse as sp

import geometry as geo
import acoustic_analysis as aa
import acoustic_fem as afem
import face_materials as fm
import qep_sparse as qs
import rir
from sources import C0
from bench_modal_vs_impedance import extract_boundary_faces, assemble_surface_M

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0])
print()

ROOM = "TP 7/recinto.room"
RIRS = "TP 7/RIRs Control Room"
d = json.load(open(ROOM, encoding="utf-8"))
p = d["params"]
Lx, Ly, Lz = float(p["width"]), float(p["length"]), float(p["height"])
v, t, _e, _n = geo.build_room_geometry(p)
v = np.asarray(v, float)
mr = aa.run_fem_modal(v, t, n_modes=20, n_per_meter=2.0)
nodes = np.asarray(mr.nodes, float); tets = np.asarray(mr.tets, int)
Nn = nodes.shape[0]
print(f"  recinto TP7: {Lx}x{Ly}x{Lz} m, FEM Nn={Nn}, {len(mr.freqs)} modos")

# caja analítica (axiales/tangenciales) para los más bajos
box = sorted(set(round(C0 / 2 * np.sqrt((nx / Lx) ** 2 + (ny / Ly) ** 2
                                        + (nz / Lz) ** 2), 2)
                 for nx, ny, nz in itertools.product(range(3), repeat=3)
                 if (nx, ny, nz) != (0, 0, 0)))
box = np.array([f for f in box if f < 60])
print()


# ---------------------------------------------------------------------------
print("T1  frecuencias FEM == caja analítica (geometría reproduce la sala)")
femlo = mr.freqs[mr.freqs < 60]
err = []
for fb in box[:8]:
    err.append(np.min(np.abs(femlo - fb)) / fb)
err = np.array(err)
check("T1 los 8 modos más bajos FEM coinciden con la caja analítica (<4%)",
      float(np.max(err)) < 0.04,
      f"analítico {np.round(box[:6],1)} vs FEM {np.round(femlo[:6],1)}; "
      f"max err {100*np.max(err):.1f}%")
print()


# ---------------------------------------------------------------------------
print("T2  pico modal medido vs FEM + limitación de resolución de la RIR")
cand = glob.glob(f"{RIRS}/LSS REC P1 - L.wav")
fs, ir = rir.load_rir(cand[0]); ir = np.asarray(ir, float)
if ir.ndim > 1:
    ir = ir[:, 0]
df = fs / len(ir)
H = np.fft.rfft(ir); freq = np.fft.rfftfreq(len(ir), 1 / fs)
mag = 20 * np.log10(np.abs(H) + 1e-12)
lo = (freq > 70) & (freq < 95)                       # pico limpio ~84 Hz
f_peak = float(freq[lo][np.argmax(mag[lo])])
fem_near = float(mr.freqs[np.argmin(np.abs(mr.freqs - f_peak))])
# espaciado modal arriba de 50 Hz
sp_mod = np.diff(np.sort(mr.freqs[(mr.freqs > 50) & (mr.freqs < 120)]))
min_sp = float(np.min(sp_mod)) if sp_mod.size else 99.0
check("T2a el pico medido (~84 Hz) coincide con un modo FEM (<6%)",
      abs(f_peak - fem_near) / f_peak < 0.06,
      f"pico medido {f_peak:.1f} Hz ~ FEM {fem_near:.1f} Hz")
check("T2b limitación: df de la RIR > espaciado modal (no resuelve ξ por modo)",
      df > min_sp,
      f"df={df:.1f} Hz > min espaciado modal {min_sp:.1f} Hz (M>1) -> "
      "ξ por modo NO medible de estas RIRs")
print()


# ---------------------------------------------------------------------------
print("T3  solver SPARSE (PAL) == perturbación validada, geometría REAL TP7")
K, M, _vol = afem.build_KM(nodes, tets)
bf = extract_boundary_faces(tets, Nn)
Cfull = assemble_surface_M(nodes, bf)                 # masa de superficie, TODAS las paredes
alpha = 0.10
beta = float(fm.beta_from_alpha_random(np.array([alpha]))[0])   # β real perturbativo
Mp = sp.csr_matrix(M, dtype=complex)
Cp = (C0 * beta) * sp.csr_matrix(Cfull, dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(K, dtype=complex)
# PAL multi-shift (2 shifts) para cubrir la banda
xi_sp = np.full(len(mr.freqs), np.nan)
pool_l, pool_X = [], []
for fsh in np.linspace(mr.freqs.min(), mr.freqs.max(), 3):
    sigma = 1j * 2 * np.pi * float(fsh)
    lam, X, eta = qs.pal_qep(Mp, Cp, Kp, sigma, k=20, m=3, mode="sparse")
    sel = (eta < 1e-6) & (lam.imag > 0)
    if np.any(sel):
        pool_l.append(lam[sel]); pool_X.append(X[:, sel])
lam = np.concatenate(pool_l); X = np.concatenate(pool_X, axis=1)
MX = Mp @ X; den = np.sqrt(np.abs(np.einsum("ik,ik->k", X.conj(), MX)))
for n in range(len(mr.freqs)):
    rel = np.abs(mr.phis[:, n].conj() @ MX) / np.maximum(den, 1e-30)
    kb = int(np.argmax(rel))
    if rel[kb] > 0.3:
        s = lam[kb]; xi_sp[n] = (-s.real) / max(abs(s.imag), 1e-9)

gr = fm.group_faces_by_planar_region(v, t)


class _Um:
    def __init__(self, a): self._a = a; self.name = "u"
    def alpha(self, f): return self._a


g2m = {g.signature: _Um(alpha) for g in gr}
Vr = aa.compute_mesh_volume(v, t)
xi_pt = fm.perturbation_xi_per_mode(mr.freqs, mr.phis, mr.locator, v, t, gr,
                                    g2m, Vr, subdiv=3)
cov = np.isfinite(xi_sp)
rel = np.abs(xi_sp[cov] / np.maximum(xi_pt[cov], 1e-30) - 1.0)
check("T3 ξ sparse == ξ perturbación en la geometría real TP7 (<2%)",
      cov.sum() >= len(mr.freqs) - 1 and float(np.max(rel)) < 0.02,
      f"cobertura {100*cov.mean():.0f}%; sparse vs perturbación: "
      f"media {100*np.mean(rel):.2f}% max {100*np.max(rel):.2f}%")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
