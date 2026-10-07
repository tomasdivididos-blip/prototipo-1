"""Bench F3: ORÁCULO SLEPc (PEP / STOAR shift-invert) para el QEP de frontera.

Contraste INDEPENDIENTE de los métodos propios A (PAL) y B (Beyn) contra un solver
de PEP de biblioteca madura (SLEPc, Campos & Roman 2016), además del companion denso
de scipy. SLEPc es el oráculo del plan (`plan_solver_qep_sparse.md` §3 C, F3): un
solver de autovalores polinomiales distinto, con su propia linealización (TOAR/STOAR)
y transformación espectral shift-invert, así que un acuerdo SLEPc==propio valida el
álgebra de PAL/Beyn sin depender del mismo código.

QEP en s (Laplace, s=iω):  P(s) = s² M + s (c β) C_surf + c² K = 0,  todo REAL
SIMÉTRICO (M SPD, c²K SPSD, cβC_surf SPSD de bajo rango). Coeficientes del PEP:
A0 = c²K,  A1 = (cβ)C_surf,  A2 = M  (λ=s). Los s = −δ ± iω_d dan ξ = −Re(s)/|Im(s)|.

  T1  SLEPc (shift-invert, target σ en la banda) == companion DENSO de scipy en los
      polos sub-Schroeder (<1e-7 rel): valida SLEPc contra la verdad exacta.
  T2  PAL (método A) == SLEPc en los polos que PAL certifica (η_Q): valida A contra
      un oráculo independiente del companion propio.
  T3  Beyn (método B) == SLEPc en los polos dentro del contorno: valida B.
  T4  ξ por modo del wrapper sparse A+B == SLEPc (cross-check físico end-to-end).

REQUISITO: petsc4py + slepc4py con PETSc de ESCALARES COMPLEJOS (eigenvalores y shift
complejos). NO hay build win-64 (ver plan): en Windows va por WSL, o en CI Linux. Si
no están, el bench se SALTEA (exit 0) para no romper la suite en la máquina del autor.

Setup del oráculo (WSL Ubuntu o Linux/CI), env conda aparte `qep_oracle`:
  conda create -n qep_oracle -c conda-forge python=3.11 numpy scipy
  conda activate qep_oracle
  conda install -c conda-forge "petsc=*=*complex*" petsc4py "slepc=*=*complex*" slepc4py
  # (o: pip install petsc petsc4py slepc slepc4py  con PETSC_CONFIGURE_OPTIONS="--with-scalar-type=complex")
  QT_QPA_PLATFORM=offscreen python bench_qep_slepc.py

Correr:  QT_QPA_PLATFORM=offscreen python bench_qep_slepc.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import scipy.sparse as sp
import scipy.linalg as sla


# --- SKIP LIMPIO si no está el oráculo (suite verde en Windows sin SLEPc) ---------
def _skip(msg):
    print("Bench F3 (oráculo SLEPc) — SALTEADO")
    print(f"  {msg}")
    print("  (no hay build win-64 de SLEPc; correr en WSL/Linux/CI con PETSc complejo;")
    print("   ver el encabezado de este archivo para el setup del env `qep_oracle`.)")
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

# PETSc debe estar compilado con escalares COMPLEJOS (si no, no hay shift complejo).
if np.dtype(PETSc.ScalarType).kind != "c":
    _skip(f"PETSc es de escalares reales ({PETSc.ScalarType}); se necesita complejo.")


from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes
import face_materials as fm
import qep_sparse as qs
from sources import C0

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print(__doc__.splitlines()[0]); print()

# --- Shoebox FEM (N chico: el companion denso oráculo debe ser rápido) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.0)
N = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=12)
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
print(f"  malla: N={N}, {len(freqs)} modos, pared trasera {nf} caras")
print(f"  PETSc {PETSc.Sys.getVersion()} escalares={PETSc.ScalarType}")

beta = 1.0
Mp = sp.csr_matrix(M, dtype=complex)
Cp = (C0 * beta) * sp.csr_matrix(C_rear, dtype=complex)
Kp = (C0 * C0) * sp.csr_matrix(K, dtype=complex)
f_band = float(np.median(freqs))
sigma = 1j * 2 * np.pi * f_band


def dense_sqep_eigs(Mp, Cp, Kp):
    """Autovalores s del QEP s²Mp+sCp+Kp por companion generalizado denso (verdad)."""
    n = Mp.shape[0]
    Md, Cd, Kd = Mp.toarray(), Cp.toarray(), Kp.toarray()
    A = np.block([[-Cd, -Kd], [np.eye(n), np.zeros((n, n))]])
    B = np.block([[Md, np.zeros((n, n))], [np.zeros((n, n)), np.eye(n)]])
    s = sla.eig(A, B, right=False)
    return s[np.isfinite(s)]


def _to_petsc(Acsr):
    """scipy CSR -> PETSc AIJ (secuencial)."""
    A = sp.csr_matrix(Acsr).astype(PETSc.ScalarType)
    p = PETSc.Mat().createAIJ(size=A.shape,
                              csr=(A.indptr.astype(PETSc.IntType),
                                   A.indices.astype(PETSc.IntType), A.data))
    p.assemble()
    return p


def slepc_pep(Mp, Cp, Kp, sigma, nev=12, pep_type="toar"):
    """Polos s del QEP por SLEPc PEP, shift-invert con target σ. A0+λA1+λ²A2 con
    A0=c²K, A1=cβC, A2=M (λ=s). Devuelve array de s complejos convergidos.

    TOAR (Two-level Orthogonal ARnoldi, Lu-Su-Bai 2016) es la linealización general
    robusta y es la que se usa con target COMPLEJO + shift-invert (el polo casi-crítico
    está fuera del eje imaginario). STOAR es su variante simétrica (explota M,C,K
    simétricas) pero solo con shift REAL; se puede pedir con pep_type="stoar" y se cae
    a TOAR si no converge."""
    A0, A1, A2 = _to_petsc(Kp), _to_petsc(Cp), _to_petsc(Mp)
    pep = SLEPc.PEP().create()
    pep.setOperators([A0, A1, A2])
    want = pep_type.lower()
    if want == "stoar":
        pep.setProblemType(SLEPc.PEP.ProblemType.HERMITIAN)
        pep.setType(SLEPc.PEP.Type.STOAR)
    else:
        pep.setProblemType(SLEPc.PEP.ProblemType.GENERAL)
        pep.setType(SLEPc.PEP.Type.TOAR)
    pep.setDimensions(nev=nev)
    pep.setTarget(complex(sigma))
    pep.setWhichEigenpairs(SLEPc.PEP.Which.TARGET_MAGNITUDE)
    pep.getST().setType(SLEPc.ST.Type.SINVERT)
    pep.setFromOptions()
    try:
        pep.solve()
        nconv = pep.getConverged()
        if nconv == 0:
            raise RuntimeError("0 convergidos")
    except Exception:
        # fallback robusto: TOAR general (p.ej. STOAR no admite target complejo).
        pep.setProblemType(SLEPc.PEP.ProblemType.GENERAL)
        pep.setType(SLEPc.PEP.Type.TOAR)
        pep.solve()
        nconv = pep.getConverged()
    return np.array([complex(pep.getEigenpair(i)) for i in range(nconv)])


def slepc_pep_pairs(Mp, Cp, Kp, targets, nev=8):
    """SLEPc PEP MULTI-TARGET: resuelve shift-invert en cada target de `targets`
    (una frecuencia por modo, como PAL multi-shift) y junta (s, autovector) de todos.
    Devuelve (lam (p,), V (n,p)) con los autovectores en el espacio nodal (para
    matchear modo↔polo por solapamiento M, igual que qep_boundary_nodal)."""
    A0, A1, A2 = _to_petsc(Kp), _to_petsc(Cp), _to_petsc(Mp)
    n = Mp.shape[0]
    lam_all, V_all = [], []
    vr = A0.createVecRight()
    vi = A0.createVecRight()
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
            continue
        for i in range(pep.getConverged()):
            s = complex(pep.getEigenpair(i, vr, vi))
            if s.imag <= 1.0:                     # solo físicos (semiplano superior)
                continue
            v = vr.getArray(readonly=True).copy()  # PETSc complejo: vr es el vector completo
            lam_all.append(s); V_all.append(v)
        pep.destroy()
    if not lam_all:
        return np.array([]), np.zeros((n, 0), complex)
    return np.array(lam_all), np.array(V_all).T


s_dense = dense_sqep_eigs(Mp, Cp, Kp)
s_near = s_dense[np.argsort(np.abs(s_dense - sigma))][:12]
print(f"  shift σ = {sigma:.1f}  (f_band={f_band:.1f} Hz)")
print(f"  densos cerca de σ: "
      f"{', '.join(f'{s.real:.1f}{s.imag:+.1f}i' for s in s_near[:4])}")
print()


def match_set(lam, ref):
    """Para cada λ, min|λ−ref| relativo a |ref| típico."""
    if len(lam) == 0:
        return np.array([])
    scale = max(float(np.median(np.abs(ref))), 1.0)
    return np.array([np.min(np.abs(L - ref)) / scale for L in lam])


# ---------------------------------------------------------------------------
print("T1  SLEPc (shift-invert) == companion DENSO en los polos cerca de σ")
s_slepc = slepc_pep(Mp, Cp, Kp, sigma, nev=12)
# solo los físicos en el semiplano superior (Im>0), cerca de σ
s_sl_up = s_slepc[s_slepc.imag > 0]
s_sl_near = s_sl_up[np.argsort(np.abs(s_sl_up - sigma))][:8] if s_sl_up.size else s_sl_up
err1 = match_set(s_sl_near, s_dense)
check("T1 autovalores de SLEPc coinciden con el QEP denso (<1e-7 rel)",
      s_sl_near.size >= 4 and float(np.max(err1)) < 1e-7,
      f"{s_sl_near.size} polos; max err rel = {np.max(err1) if err1.size else 1:.2e}")
print()

# ---------------------------------------------------------------------------
print("T2  PAL (método A) == SLEPc en los polos que PAL certifica (η_Q)")
lam_pal, X_pal, eta_pal = qs.pal_qep(Mp, Cp, Kp, sigma, k=12, m=3, mode="sparse")
cert = eta_pal < 1e-9
err2 = match_set(lam_pal[cert], s_slepc)
check("T2 polos PAL certificados == SLEPc (<1e-6 rel)",
      int(cert.sum()) >= 4 and float(np.max(err2)) < 1e-6,
      f"{int(cert.sum())} certificados; max err rel = {np.max(err2) if err2.size else 1:.2e}")
print()

# ---------------------------------------------------------------------------
print("T3  Beyn (método B) == SLEPc en los polos dentro del contorno")
# contorno: círculo centrado en la banda que abarca los modos sub-Schroeder
fc = float(np.median(freqs))
z0 = 1j * 2 * np.pi * fc
R = 1.2 * (2 * np.pi * (float(freqs.max()) - float(freqs.min())) / 2 + 2 * np.pi * 10)
lam_beyn, V_beyn, eta_beyn = qs.beyn_qep(Mp, Cp, Kp, z0, R, n_quad=64, ell=24,
                                         tol_res=1e-6)
# Beyn captura TODOS los polos de Γ; SLEPc solo pidió nev cerca de σ. La atadura
# correcta es: cada polo SLEPc (cerca de σ) tiene un polo de Beyn cercano (SLEPc⊆Beyn).
err3 = match_set(s_sl_near, lam_beyn)
check("T3 cada polo SLEPc tiene un polo de Beyn cercano (<1e-5 rel)",
      s_sl_near.size >= 4 and lam_beyn.size >= s_sl_near.size
      and float(np.max(err3)) < 1e-5,
      f"{lam_beyn.size} polos de Beyn en Γ; max err rel = {np.max(err3) if err3.size else 1:.2e}")
print()

# ---------------------------------------------------------------------------
print("T4  ξ por modo de SLEPc (multi-target, matcheo por solape) == QEP nodal denso")
# SLEPc MULTI-TARGET: un target por modo cubre toda la banda sub-Schroeder (un solo
# target solo ve su vecindad). ξ por modo por SOLAPAMIENTO del autovector con el modo
# rígido (idéntico a qep_boundary_nodal), el oráculo end-to-end independiente.
targets = [1j * 2 * np.pi * float(f) for f in np.unique(np.round(freqs, 1))]
lam_ml, V_ml = slepc_pep_pairs(Mp, Cp, Kp, targets, nev=8)
xi_slepc = np.full(len(freqs), np.nan)
f_slepc = np.full(len(freqs), np.nan)
if lam_ml.size:
    MV = Mp @ V_ml
    den = np.sqrt(np.abs(np.einsum("ik,ik->k", V_ml.conj(), MV)))
    for nmo in range(len(freqs)):
        num = np.abs(phis[:, nmo].conj() @ MV)
        kb = int(np.argmax(num / np.maximum(den, 1e-30)))
        s = lam_ml[kb]
        xi_slepc[nmo] = -s.real / max(abs(s.imag), 1e-9)
        f_slepc[nmo] = abs(s.imag) / (2 * np.pi)
xi_nod_t4, f_nod_t4 = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0)
cov = np.isfinite(xi_slepc) & np.isfinite(xi_nod_t4)
dxi = np.abs(xi_slepc[cov] - xi_nod_t4[cov])
tol4 = 0.01 + 0.02 * np.abs(xi_nod_t4[cov])     # |Δξ| ≤ 0.01 + 2%·ξ (ambos exactos)
check("T4 ξ(SLEPc multi-target) == ξ(nodal denso) por modo (|Δξ|≤0.01+2%)",
      int(cov.sum()) >= 10 and bool(np.all(dxi <= tol4)),
      f"{lam_ml.size} polos SLEPc; {int(cov.sum())} modos; "
      f"max |Δξ| = {np.max(dxi) if dxi.size else 1:.4f} (fuera de tol: {int(np.sum(dxi>tol4))})")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
