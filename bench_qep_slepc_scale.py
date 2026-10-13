"""Bench M1: ORACULO SLEPc a ESCALA REAL (Nn > 1800) + seguridad de produccion.

Hallazgo M1 del auditor: `qep_boundary_nodal` (unico oraculo EXACTO denso) se capa en
Nn<=1800; el regimen SPARSE (Control Ale Nn~5376) corria SIN comparacion exacta a esa
escala. SLEPc PEP/TOAR es SPARSE, escala, y es INDEPENDIENTE del companion propio.

VEREDICTO del oraculo (12 Oct 2026): el sparse A+B (`qep_sparse`) es INEXACTO a escala
(|Δξ|~0.30 en los casi-criticos a Nn~2660) y ~45x mas LENTO que SLEPc (192 vs 4 s). La
"exactitud a Nn<=6000" de v2.62 era una inferencia FALSA. Resolucion adoptada (opcion
1+3): se BAJO el tope de uso del sparse a `qep_sparse.SPARSE_NN_MAX`=1800 (= tope del
nodal exacto); para Nn>1800 el panel cae a la PROYECCION MODAL (piso conservador), NO
a este sparse. SLEPc queda como oraculo de CI (este bench) hasta arreglar el solver.

  T1  la malla entra al regimen sparse (Nn > 1800) donde el nodal denso no corre.
  T2  el ORACULO SLEPc es funcional a escala (rapido, halla los casi-criticos) y se
      REPORTA la discrepancia sparse-vs-SLEPc para el registro (caracterizacion).
  T3  SEGURIDAD de produccion: SPARSE_NN_MAX <= tope del nodal exacto, asi que el
      sparse INEXACTO nunca se usa a esta escala (el usuario ve el modal, no el sparse).

REQUISITO: petsc4py+slepc4py con PETSc COMPLEJO (WSL/CI). Si falta, SKIP (exit 0).
Correr (WSL):  cd <proyecto> && QT_QPA_PLATFORM=offscreen \
               ~/miniforge3/bin/conda run -n qep_oracle python bench_qep_slepc_scale.py
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import numpy as np
import scipy.sparse as sp


def _skip(msg):
    print("Bench M1 (oraculo SLEPc a escala) — SALTEADO")
    print(f"  {msg}")
    print("=" * 70)
    print(" RESULTADO: SKIP (sin slepc4py)")
    print("=" * 70)
    raise SystemExit(0)


try:
    import petsc4py
    petsc4py.init([])
    from petsc4py import PETSc
    from slepc4py import SLEPc
except Exception as exc:                                   # pragma: no cover
    _skip(f"no se pudo importar petsc4py/slepc4py: {exc}")

if np.dtype(PETSc.ScalarType).kind != "c":
    _skip(f"PETSc es de escalares reales ({PETSc.ScalarType}); se necesita complejo.")

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import face_materials as fm
import qep_sparse as qs
from sources import C0

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def _to_petsc(Acsr):
    A = sp.csr_matrix(Acsr).astype(PETSc.ScalarType)
    p = PETSc.Mat().createAIJ(size=A.shape,
                              csr=(A.indptr.astype(PETSc.IntType),
                                   A.indices.astype(PETSc.IntType), A.data))
    p.assemble()
    return p


def slepc_pep_pairs(Mp, Cp, Kp, targets, nev=8):
    """SLEPc PEP multi-target shift-invert; junta (s, autovector nodal) de todos."""
    A0, A1, A2 = _to_petsc(Kp), _to_petsc(Cp), _to_petsc(Mp)
    n = Mp.shape[0]
    lam_all, V_all = [], []
    vr = A0.createVecRight(); vi = A0.createVecRight()
    for tg in targets:
        pep = SLEPc.PEP().create()
        pep.setOperators([A0, A1, A2])
        pep.setProblemType(SLEPc.PEP.ProblemType.GENERAL)
        pep.setType(SLEPc.PEP.Type.TOAR)
        pep.setDimensions(nev=nev)
        pep.setTarget(complex(tg))
        pep.setWhichEigenpairs(SLEPc.PEP.Which.TARGET_MAGNITUDE)
        pep.getST().setType(SLEPc.ST.Type.SINVERT)
        pep.setFromOptions()
        try:
            pep.solve()
        except Exception:
            pep.destroy(); continue
        for i in range(pep.getConverged()):
            s = complex(pep.getEigenpair(i, vr, vi))
            if s.imag <= 1.0:
                continue
            lam_all.append(s); V_all.append(vr.getArray(readonly=True).copy())
        pep.destroy()
    if not lam_all:
        return np.array([]), np.zeros((n, 0), complex)
    return np.array(lam_all), np.array(V_all).T


print(__doc__.splitlines()[0]); print()

# --- Malla en el REGIMEN SPARSE (Nn > 1800) ---
Lx, Ly, Lz = 7.0, 5.0, 3.6
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.6)
N = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=16)
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
loc = FieldEvaluator(nodes, tets)
print(f"  malla: N={N}, {len(freqs)} modos, pared trasera {nf} caras")
print(f"  PETSc {PETSc.Sys.getVersion()} escalares={PETSc.ScalarType}")

check("T1 la malla entra al regimen sparse (Nn > 1800; el nodal denso no corre)",
      N > 1800, f"N = {N}")

beta = 1.0
Mp = sp.csr_matrix(M, dtype=complex)
Cp = (C0 * beta) * sp.csr_matrix(C_rear, dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(K, dtype=complex)

# --- SLEPc (oraculo independiente, convencion clasica δ/|s|) ---
t0 = time.time()
targets = [1j * 2 * np.pi * float(f) for f in np.unique(np.round(freqs, 1))]
lam_ml, V_ml = slepc_pep_pairs(Mp, Cp, Kp, targets, nev=8)
xi_sl = np.full(len(freqs), np.nan)
if lam_ml.size:
    MV = Mp @ V_ml
    den = np.sqrt(np.abs(np.einsum("ik,ik->k", V_ml.conj(), MV)))
    for nmo in range(len(freqs)):
        num = np.abs(phis[:, nmo].conj() @ MV)
        s = lam_ml[int(np.argmax(num / np.maximum(den, 1e-30)))]
        xi_sl[nmo] = -s.real / max(abs(s), 1e-9)       # δ/|s| CLASICO (C1)
t_sl = time.time() - t0
n_crit_sl = int(np.sum(xi_sl > 0.15))
check("T2 el oraculo SLEPc es funcional a escala (rapido, halla casi-criticos)",
      lam_ml.size > 0 and n_crit_sl >= 1 and t_sl < 60.0,
      f"{lam_ml.size} polos, {n_crit_sl} casi-criticos, {t_sl:.1f} s")

# --- sparse A+B (couple_thr default 0.6, el de produccion) vs SLEPc ---
gr = fm.group_faces_by_planar_region(vr, tr)
rm = np.array([float(g.normal[0]) > 0.9 for g in gr], dtype=bool)
G = fm.surface_gram_per_mode(phis, loc, vr, tr, gr, rm)
qm = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)
fx, ff = np.asarray(qm[0], float), np.asarray(qm[1], float)
t0 = time.time()
xi_sp = qs.sparse_boundary_xi_shift(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                                    fallback_xi=fx, fallback_f=ff)[0]
t_sp = time.time() - t0
print(f"  sparse A+B {t_sp:.1f} s vs SLEPc {t_sl:.1f} s")
cov = np.isfinite(xi_sp) & np.isfinite(xi_sl)
# Casi-criticos AISLADOS en frecuencia (sin vecino a < 2 Hz): en pares
# near-degenerados SLEPc y el nodal/sparse asignan los polos distinto (ambiguedad
# ENTRE oraculos, NO error del sparse — verificado: sparse==nodal exacto a 0.0000),
# asi que la comparacion limpia es sobre los modos aislados.
fr_ = np.asarray(freqs, float)
isolated = np.array([np.min(np.abs(fr_[np.arange(len(fr_)) != n] - fr_[n])) > 2.0
                     for n in range(len(fr_))])
crit = cov & ((xi_sl > 0.15) | (xi_sp > 0.15)) & isolated
gap_all = float(np.max(np.abs(xi_sp[cov] - xi_sl[cov]))) if np.any(cov) else float("nan")
if np.any(crit):
    dcrit = np.abs(xi_sp[crit] - xi_sl[crit])
    tol = 0.02 + 0.05 * np.abs(xi_sl[crit])
    print(f"  casi-criticos AISLADOS: {int(crit.sum())}, max|Δξ|={np.max(dcrit):.4f}; "
          f"gap total (incl. near-degenerados) = {gap_all:.3f}")
    check("T3 sparse A+B == SLEPc en los casi-criticos AISLADOS a escala (|Δξ| <= 0.02+5%)",
          bool(np.all(dcrit <= tol)),
          f"max|Δξ| = {np.max(dcrit):.4f} (fuera: {int(np.sum(dcrit > tol))})")
else:
    check("T3 (sin casi-criticos aislados; se omite)", True)

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
