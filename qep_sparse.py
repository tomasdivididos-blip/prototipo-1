"""qep_sparse.py
================

Solver SPARSE para el QEP de frontera complejo, para salas grandes donde el eig
denso O((2N)^3) de `face_materials.qep_boundary_nodal` es inviable.

Método A: PAL (Padé Approximate Linearization), Lu, Huang, Bai & Su (2015),
`referencias/Lu, Huang, Bai & Su (2015)...pdf`. Explota el BAJO RANGO del
amortiguamiento de frontera (C = masa de superficie de la pared trasera,
rank(C)=ℓ ≪ N): el LEP tiene dimensión n+ℓm (no 2n), y el shift-invert factoriza
SOLO Q(σ)=σ²M+σC+K de orden n (eqs 5.2-5.3), no el LEP entero.

QEP (convención del paper):  Q(λ) x = (λ² M + λ C + K) x = 0,  C = E Fᵀ, rank ℓ.
Nuestro QEP de frontera P(ω) = −M ω² + i c β C_surf ω + c² K con s=iω se vuelve
el QEP viscoso REAL simétrico  s² M + s (c β) C_surf + c² K = 0  (M→M, C→c β
C_surf, K→c² K, λ→s). Los autovalores s=−δ±iω_d dan δ (decaimiento) y ω_d.

Validación por etapas (bench_qep_sparse.py):
  - PAL DENSO (arma A_s,B_s y eig denso) == QEP denso  → valida el álgebra.
  - PAL SPARSE (Q(σ) + matvec estructurado 5.3 + eigs) == PAL denso → implement.
  - error hacia atrás η_Q por polo (certificado independiente de oráculo).

NÚCLEO numpy+scipy puro (D0). Convención e^{+iωt}.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import scipy.linalg as sla


# ---------------------------------------------------------------------------
# Piezas del algoritmo
# ---------------------------------------------------------------------------
def pade_sqrt_coeffs(m: int):
    """Aproximante de Padé diagonal (m,m) de sqrt(mu+1) (Lu et al. ec. 3.1):
        r_m(mu) = -aᵀ (I_m - mu D_m)^{-1} a + d,
    con a_j=sqrt(gamma_j/xi_j), D_m=-diag(xi_j), d=2m+1,
        gamma_j = (2/(2m+1)) sin²(jπ/(2m+1)),  xi_j = cos²(jπ/(2m+1)).
    Devuelve (a (m,), Dm_diag (m,), d)."""
    j = np.arange(1, m + 1)
    ang = j * np.pi / (2 * m + 1)
    xi = np.cos(ang) ** 2
    gamma = (2.0 / (2 * m + 1)) * np.sin(ang) ** 2
    a = np.sqrt(gamma / xi)
    return a, -xi, float(2 * m + 1)


def lowrank_factor(C, tol=1e-12):
    """Factor de rango revelador de C simétrica semidefinida positiva:
    C ≈ E Eᵀ con E (n×ℓ), ℓ=rank(C). Se explota que C (masa de superficie de la
    pared) es cero fuera del soporte (los nodos de esa pared): se extrae el bloque
    denso del soporte, se diagonaliza y se re-dispersa. Devuelve E (n×ℓ, real) o
    None si C≈0."""
    C = sp.csr_matrix(C)
    n = C.shape[0]
    d = np.asarray(C.diagonal(), dtype=float)
    supp = np.where(np.abs(d) > tol)[0]              # nodos con masa (soporte)
    if supp.size == 0:
        return None
    Csub = np.asarray(C[np.ix_(supp, supp)].todense(), dtype=float)
    Csub = 0.5 * (Csub + Csub.T)
    w, U = np.linalg.eigh(Csub)
    keep = w > tol * max(1.0, w.max())
    if not np.any(keep):
        return None
    Esub = U[:, keep] * np.sqrt(w[keep])             # (|supp|, ℓ)
    E = np.zeros((n, int(keep.sum())), dtype=float)
    E[supp, :] = Esub
    return E


def _qep_norms(M, C, K):
    """1-normas (max suma de columna en abs) de M, C, K sparse."""
    def n1(A):
        A = sp.csr_matrix(A)
        return float(np.max(np.abs(A).sum(axis=0))) if A.nnz else 0.0
    return n1(M), n1(C), n1(K)


def _backward_error(M, C, K, lam, x, nM, nC, nK):
    """η_Q = ‖Q(λ)x‖ / ((|λ|²‖M‖+|λ|‖C‖+‖K‖)‖x‖), Tisseur 2001."""
    Qx = (lam * lam) * (M @ x) + lam * (C @ x) + (K @ x)
    den = (abs(lam) ** 2 * nM + abs(lam) * nC + nK) * np.linalg.norm(x)
    return float(np.linalg.norm(Qx) / max(den, 1e-300))


# ---------------------------------------------------------------------------
# PAL
# ---------------------------------------------------------------------------
def pal_qep(M, C, K, sigma, k=24, m=3, mode="sparse", E=None,
            maxiter=None, ncv=None):
    """Autopares del QEP (λ²M+λC+K)x=0 cerca del shift sigma (≠0) por PAL.

    M, C, K: sparse n×n (C de BAJO RANGO = amortiguamiento de frontera). sigma:
    shift complejo (para el QEP de frontera, imaginario puro ≈ i·2π·f_banda). k:
    nº de autopares. m: orden de Padé (3 por defecto, como el Ej.2 del paper). E:
    factor opcional C=EEᵀ (si None se calcula). mode: "dense" arma A_s,B_s y hace
    eig denso (validación del álgebra); "sparse" factoriza SOLO Q(σ) y aplica
    A_s⁻¹B_s por matvec estructurado (eqs 5.2-5.3) + eigs.

    Devuelve (lam (p,), X (n,p), eta (p,)): autovalores λ=σ√(μ+1), autovectores
    del QEP (n filas) y error hacia atrás η_Q por polo. p≤k (se descartan polos
    de Padé y espurios)."""
    M = sp.csr_matrix(M, dtype=complex)
    K = sp.csr_matrix(K, dtype=complex)
    C = sp.csr_matrix(C, dtype=complex)
    n = M.shape[0]
    sigma = complex(sigma)
    if E is None:
        E = lowrank_factor(C.real if np.allclose(C.imag.data if C.nnz else 0, 0)
                            else C)
    if E is None:
        return np.array([]), np.zeros((n, 0), complex), np.array([])
    # C = E Fᵀ. Para C simétrica (posible escalar complejo delante) E=F.
    E = np.asarray(E, dtype=complex)
    F = E
    ell = E.shape[1]

    a, Dm_diag, d = pade_sqrt_coeffs(m)                 # (m,), (m,), 2m+1
    a = a.astype(complex)
    # Escalado ζ (Teorema 4, ec. 4.13): ζ=1/max{‖σ²M‖, 2m‖σC‖, ‖K‖}.
    nM, nC, nK = _qep_norms(M, C, K)
    zeta = 1.0 / max(abs(sigma) ** 2 * nM, 2 * m * abs(sigma) * nC, nK, 1e-300)
    # Shift splitting σ=σ1σ2, |σ1|‖E‖=|σ2|‖F‖=sqrt(|σ|‖C‖). E=F (PSD) → σ1=σ2=√σ.
    s1 = np.sqrt(sigma)
    s2 = np.sqrt(sigma)

    # Q(σ) = σ²M + σC + K  (orden n, el ÚNICO que se factoriza).
    Qsig = (sigma * sigma) * M + sigma * C + K

    # Operadores de Kron como funciones (evita formar I_ℓ⊗· denso).
    Dm = Dm_diag                                        # (m,)

    def IaT(u2):                                        # (I_ℓ⊗aᵀ) u2 : ℓm→ℓ
        return (u2.reshape(ell, m) @ a)                 # (ℓ,)

    def Ia(y):                                          # (I_ℓ⊗a) y : ℓ→ℓm
        return np.outer(y, a).reshape(ell * m)          # (ℓm,)

    def IaTDm(u2):                                      # (I_ℓ⊗(aᵀD_m)) u2 : ℓm→ℓ
        return (u2.reshape(ell, m) * Dm) @ a            # (ℓ,)

    def IDm(u2):                                        # (I_ℓ⊗D_m) u2 : ℓm→ℓm
        return (u2.reshape(ell, m) * Dm).reshape(ell * m)

    if mode == "dense":
        # A_s, B_s densos (ec. 4.8) para validar el álgebra. n+ℓm chico.
        Im = np.eye(m)
        IaT_full = np.kron(np.eye(ell), a[None, :])     # (ℓ, ℓm)
        Esig1 = s1 * (E @ IaT_full)                     # (n, ℓm)
        Fsig2 = s2 * (F @ IaT_full)                     # (n, ℓm)
        Ksig = (K + sigma * sigma * M).toarray()
        Msig = (-sigma * sigma * M).toarray()
        IDm_full = np.kron(np.eye(ell), np.diag(Dm))    # (ℓm, ℓm)
        A = np.zeros((n + ell * m, n + ell * m), complex)
        B = np.zeros_like(A)
        A[:n, :n] = zeta * (Ksig + sigma * d * C.toarray())
        A[:n, n:] = np.sqrt(zeta) * Esig1
        A[n:, :n] = np.sqrt(zeta) * Fsig2.T
        A[n:, n:] = np.eye(ell * m)
        B[:n, :n] = zeta * Msig
        B[n:, n:] = IDm_full
        mu, V = sla.eig(A, B)
        xL = V
        good = np.isfinite(mu)
        mu, xL = mu[good], xL[:, good]
        order = np.argsort(np.abs(mu))[:k]              # los k más chicos |μ|
        mu, xL = mu[order], xL[:, order]
        X = xL[:n, :]
    else:
        # SPARSE: LU de Q(σ) una vez; OP u = A_s⁻¹ B_s u por ecs. 5.3.
        lu = spla.splu(sp.csc_matrix(Qsig))

        def op(u):
            u = np.asarray(u, dtype=complex).ravel()
            u1, u2 = u[:n], u[n:]
            # v1 = -Q(σ)⁻¹ ( σ² M u1 + (σ1/√ζ) E (I_ℓ⊗(aᵀD_m)) u2 )   (5.3a)
            rhs = (sigma * sigma) * (M @ u1) + (s1 / np.sqrt(zeta)) * (E @ IaTDm(u2))
            v1 = -lu.solve(rhs)
            # v2 = (I_ℓ⊗D_m) u2 - √ζ σ2 (I_ℓ⊗a) Fᵀ v1                  (5.3b)
            v2 = IDm(u2) - np.sqrt(zeta) * s2 * Ia(F.T @ v1)
            return np.concatenate([v1, v2])

        N = n + ell * m
        OP = spla.LinearOperator((N, N), matvec=op, dtype=complex)
        kk = min(k, N - 2)
        if ncv is None:
            ncv = min(N - 1, max(2 * kk + 1, 20))
        # eigenvalores de A_s⁻¹B_s = 1/μ_s ; los μ_s chicos ↔ 1/μ_s grandes (LM).
        theta, xL = spla.eigs(OP, k=kk, which="LM", maxiter=maxiter, ncv=ncv)
        mu = 1.0 / theta
        X = xL[:n, :]

    # Recuperación λ=σ√(μ+1) (rama principal) y error hacia atrás.
    lam = sigma * np.sqrt(mu + 1.0)
    # Descartar polos de Padé (-1/ξ_j) y no finitos.
    pole_mu = -1.0 / (-Dm)                              # -1/ξ_j
    keep = np.isfinite(lam)
    for pm in pole_mu:
        keep &= np.abs(mu - pm) > 1e-6
    lam, X = lam[keep], X[:, keep]
    eta = np.array([_backward_error(M, C, K, lam[i], X[:, i], nM, nC, nK)
                    for i in range(len(lam))])
    order = np.argsort(np.abs(lam.imag))               # por frecuencia
    return lam[order], X[:, order], eta[order]


# ---------------------------------------------------------------------------
# Envoltorio para el QEP de frontera (interfaz como qep_boundary_nodal)
# ---------------------------------------------------------------------------
def pal_boundary_xi_shift(K, M, Csurf, freqs_ref, phis_ref, beta, c=343.0,
                          m=3, k_per_shift=12, eta_tol=1e-8, shifts_hz=None,
                          return_cov=False):
    """QEP de frontera por PAL MULTI-SHIFT, interfaz paralela a
    `face_materials.qep_boundary_nodal`: c²K + i c β Csurf ω − M ω² = 0, resuelto
    en s=iω como s²M + s(cβ)Csurf + c²K.

    Un shift σ de PAL solo capta los polos en su VECINDAD (dominio de confianza,
    Lu et al. Fig 2.2). Para cubrir toda la banda sub-Schroeder se coloca un shift
    en CADA frecuencia modal (σ=i·2π·f_n), se juntan los polos cuyo error hacia
    atrás η_Q < eta_tol (auto-certificado) y con Im(s)>0 (dominio 𝕊_σ = semiplano
    superior), se deduplican y se matchean a los modos rígidos por solapamiento.

    Devuelve (xi, f_new) (Nm,); los modos SIN polo certificado (p. ej.
    sobreamortiguados, cuyo polo está sobre el eje real negativo y no lo capta un
    shift imaginario → los cubre el método B/Beyn) quedan en NaN. Con
    return_cov=True devuelve además la fracción de modos cubiertos."""
    M = sp.csr_matrix(M); K = sp.csr_matrix(K); Csurf = sp.csr_matrix(Csurf)
    freqs_ref = np.asarray(freqs_ref, float)
    phis_ref = np.asarray(phis_ref)
    Nm = int(phis_ref.shape[1]) if phis_ref.ndim == 2 else 0
    if Nm == 0 or freqs_ref.size < Nm:
        return None
    Mp = sp.csr_matrix(M, dtype=complex)
    Cp = (c * complex(beta)) * sp.csr_matrix(Csurf, dtype=complex)
    Kp = (c * c) * sp.csr_matrix(K, dtype=complex)
    E_surf = lowrank_factor(Csurf)                       # factor de Csurf (real)
    if E_surf is None:
        return None
    E = np.sqrt(c * complex(beta)) * E_surf              # C_p = E Eᵀ
    if shifts_hz is None:
        shifts_hz = np.unique(np.round(freqs_ref[:Nm], 2))
    # Pool de polos certificados de todos los shifts.
    lam_pool, X_pool = [], []
    for fsh in shifts_hz:
        sigma = 1j * 2.0 * np.pi * float(fsh)
        lam, X, eta = pal_qep(Mp, Cp, Kp, sigma, k=k_per_shift, m=m,
                              mode="sparse", E=E)
        sel = (eta < eta_tol) & (lam.imag > 0)
        if np.any(sel):
            lam_pool.append(lam[sel]); X_pool.append(X[:, sel])
    if not lam_pool:
        return None
    lam_all = np.concatenate(lam_pool)
    X_all = np.concatenate(X_pool, axis=1)
    # Dedupe (polos repetidos entre shifts): ordenar por Im y fusionar cercanos.
    order = np.argsort(lam_all.imag)
    lam_all, X_all = lam_all[order], X_all[:, order]
    keep = np.ones(len(lam_all), bool)
    for i in range(1, len(lam_all)):
        if keep[i - 1] and abs(lam_all[i] - lam_all[i - 1]) < 1e-3 * abs(lam_all[i]):
            keep[i] = False
    lam_all, X_all = lam_all[keep], X_all[:, keep]
    # Matcheo por solapamiento (M-producto) con cada modo rígido.
    MX = Mp @ X_all
    den = np.sqrt(np.abs(np.einsum("ik,ik->k", X_all.conj(), MX)))
    xi = np.full(Nm, np.nan); f_new = np.full(Nm, np.nan)
    covered = 0
    for nmo in range(Nm):
        num = np.abs(phis_ref[:, nmo].conj() @ MX)
        rel = num / np.maximum(den, 1e-30)
        kbest = int(np.argmax(rel))
        if rel[kbest] < 0.3:                             # sin polo que solape
            continue
        s = lam_all[kbest]; wd = abs(s.imag)
        xi[nmo] = (-s.real) / max(wd, 1e-9)
        f_new[nmo] = wd / (2.0 * np.pi)
        covered += 1
    if return_cov:
        return xi, f_new, covered / Nm
    return xi, f_new
