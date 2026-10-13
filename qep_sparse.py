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


# Tope de Nn hasta el cual el camino de la pared matcheada USA este solver sparse.
# HISTORIA (M1, 12 Oct 2026): el oraculo INDEPENDIENTE SLEPc (bench_qep_slepc_scale.py)
# expuso que el sparse A+B era INEXACTO a escala (fundamental casi-critico 0.34 vs nodal
# 0.825 a Nn~2600) por el CONTORNO de Beyn: el polo de un modo fuertemente matcheado
# tiene δ grande Y su fₙ se corre hacia arriba (|s|~1.4-1.7·wc), quedando lejos del eje
# imaginario, y la elipse (a=1.15wc, z0=-0.1wc) no lo alcanzaba. ARREGLADO en `_beyn_band`
# (a=1.5wc, z0=-0.35wc): ensanchar en Re NO agrega modos (no satura), y captura el polo.
# VALIDADO: sparse == nodal EXACTO a 0.0000 en los 16 modos a Nn=2660 (antes 0.30 de
# error), 24x mas rapido (21 s). Por eso el tope vuelve a 6000 (cubre Control Ale 5376).
# NOTA: la unica discrepancia residual sparse-vs-SLEPc a escala es en pares
# near-degenerados (asignacion ambigua ENTRE oraculos; el sparse coincide con el nodal
# exacto, no es error). Ver [[solver-qep-sparse]] + bench_qep_slepc_scale.
SPARSE_NN_MAX = 6000


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
        # Si ARPACK no converge dentro de maxiter (shifts lentos de baja f), se usan
        # los pares de Ritz YA convergidos (el fallback modal cubre el resto): acota
        # el tiempo por shift sin perder los polos buenos (el η_Q filtra después).
        try:
            theta, xL = spla.eigs(OP, k=kk, which="LM", maxiter=maxiter, ncv=ncv)
        except spla.ArpackNoConvergence as exc:
            theta, xL = exc.eigenvalues, exc.eigenvectors
            if theta.size == 0:
                return np.array([]), np.zeros((n, 0), complex), np.array([])
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
# Método B: integral de contorno (Beyn 2012)
# ---------------------------------------------------------------------------
def beyn_contour(Tfun, z0, R, n_quad=48, ell=24, tol_rank=1e-8,
                 tol_res=1e-7, seed=0, Tresid=None, b=None, return_info=False):
    """Autopares de T(z) v = 0 DENTRO del contorno Γ (centro z0) por el método de
    integral de contorno de Beyn (2012), `referencias/Beyn...pdf`, "Integral
    algorithm 1" (p.14). T holomorfa; sirve para el QEP (T(z)=z²M+zC+K) y para un
    NEP β(ω) (T(z) cualquiera). Captura TODOS los polos en Γ, incluidos los
    sobreamortiguados (eje real) que un shift imaginario no ve.

    Γ es por defecto el CÍRCULO z(t)=z0+R·e^{it}. Con `b` distinto de R es la
    ELIPSE z(t)=z0 + R·cos t + i·b·sin t (R = semieje REAL, b = semieje
    IMAGINARIO). La elipse ANCHA en Re y ANGOSTA en Im es la clave del tileado de
    f media-alta: alcanza el polo amortiguado (a −ξωₙ del eje imaginario, Re lejos)
    sin encerrar a los vecinos en FRECUENCIA (Im). Un círculo de radio suficiente
    para alcanzar el polo encierra ~f² modos (densidad modal) y el SVD satura.

        A0 = (1/2πi)∮ T(z)⁻¹ V̂ dz,   Ã1 = (1/2πi)∮ (z−z0) T(z)⁻¹ V̂ dz
    por trapecio sobre la parametrización, con el jacobiano z'(t) (converge
    EXPONENCIAL en n_quad para Γ analítica). SVD de A0 revela el rango k = nº de
    polos adentro; B = V0ᴴ Ã1 W0 Σ0⁻¹ (k×k) tiene autovalores λ−z0.

    Tfun(z) -> matriz sparse n×n. ell = tamaño de la sonda (≥ nº de polos
    esperado; si k==ell hay más y conviene subirlo). Tresid(z) opcional para el
    residuo (default Tfun). Devuelve (lam, V, res): autovalores, autovectores
    (n×p) y residuo relativo ‖T(λ)v‖/‖v‖ por polo."""
    Qz0 = sp.csc_matrix(Tfun(z0))
    n = Qz0.shape[0]
    rng = np.random.default_rng(seed)
    Vhat = (rng.standard_normal((n, ell))
            + 1j * rng.standard_normal((n, ell)))
    M0 = np.zeros((n, ell), complex)
    M1 = np.zeros((n, ell), complex)
    bb = R if b is None else float(b)
    for j in range(n_quad):
        tj = 2.0 * np.pi * j / n_quad
        # z(t) = z0 + R cos t + i b sin t ;  z'(t) = -R sin t + i b cos t.
        zj = z0 + R * np.cos(tj) + 1j * bb * np.sin(tj)
        dzj = -R * np.sin(tj) + 1j * bb * np.cos(tj)
        lu = spla.splu(sp.csc_matrix(Tfun(zj)))
        Xj = lu.solve(Vhat)                               # T(z_j)⁻¹ V̂
        M0 += Xj * dzj                                     # ∫ T⁻¹V̂ z'(t) dt
        M1 += Xj * (zj - z0) * dzj                         # ∫ (z−z0)T⁻¹V̂ z'(t) dt
    M0 *= 1.0 / (1j * n_quad)                              # (1/2πi)·(2π/n)·Σ
    M1 *= 1.0 / (1j * n_quad)                              # A0, Ã1
    U, s, Wh = np.linalg.svd(M0, full_matrices=False)
    if s[0] == 0:
        _inf0 = {"k": 0, "ell": int(ell), "saturated": False}
        _e0 = (np.array([]), np.zeros((n, 0), complex), np.array([]))
        return (*_e0, _inf0) if return_info else _e0
    k = int(np.sum(s > tol_rank * s[0]))
    # M4: si k == ell el SVD SATURO (hay mas polos que la sonda) -> se perderian en
    # silencio; se expone `saturated` para que el caller re-tilee (bisecte en Im).
    info = {"k": int(k), "ell": int(ell), "saturated": bool(k >= ell)}
    if k == 0:
        _e = (np.array([]), np.zeros((n, 0), complex), np.array([]))
        return (*_e, info) if return_info else _e
    V0 = U[:, :k]; S0 = s[:k]; W0 = Wh.conj().T[:, :k]
    B = (V0.conj().T @ M1 @ W0) / S0[None, :]             # V0ᴴ Ã1 W0 Σ0⁻¹
    theta, Sv = np.linalg.eig(B)
    lam = z0 + theta
    V = V0 @ Sv
    Tr = Tresid if Tresid is not None else Tfun
    out_lam, out_V, out_res = [], [], []
    for i in range(len(lam)):
        v = V[:, i]; nv = np.linalg.norm(v)
        if nv == 0 or not np.isfinite(lam[i]):
            continue
        res = np.linalg.norm(Tr(lam[i]) @ v) / nv
        # dentro de Γ: círculo |·|<R, o elipse (Re/R)²+(Im/b)²<1.
        d = lam[i] - z0
        if b is None:
            inside = abs(d) < R * (1.0 + 1e-6)
        else:
            inside = ((d.real / R) ** 2 + (d.imag / float(b)) ** 2) < (1.0 + 1e-6)
        if res < tol_res and inside:
            out_lam.append(lam[i]); out_V.append(v); out_res.append(res)
    if not out_lam:
        _e = (np.array([]), np.zeros((n, 0), complex), np.array([]))
        return (*_e, info) if return_info else _e
    idx = np.argsort(np.abs(np.imag(out_lam)))
    lam_o = np.array(out_lam)[idx]
    V_o = np.array(out_V).T[:, idx]
    res_o = np.array(out_res)[idx]
    return (lam_o, V_o, res_o, info) if return_info else (lam_o, V_o, res_o)


def beyn_qep(M, C, K, z0, R, n_quad=48, ell=24, tol_rank=1e-8, tol_res=1e-7,
             seed=0, b=None, return_info=False):
    """Beyn para el QEP (z²M+zC+K)v=0 dentro del contorno (z0, R[, b]). Círculo si
    b=None, ELIPSE (R=semieje Re, b=semieje Im) si no. Devuelve (lam, V, res) con
    el residuo = error hacia atrás η_Q del QEP. Con `return_info` devuelve además el
    dict {k, ell, saturated} del SVD (M4: saturated=True si k>=ell → faltan polos)."""
    M = sp.csr_matrix(M, dtype=complex)
    C = sp.csr_matrix(C, dtype=complex)
    K = sp.csr_matrix(K, dtype=complex)
    nM, nC, nK = _qep_norms(M, C, K)

    def T(z):
        return (z * z) * M + z * C + K

    lam, V, _res, info = beyn_contour(T, z0, R, n_quad=n_quad, ell=ell,
                                      tol_rank=tol_rank, tol_res=1e-1, seed=seed,
                                      Tresid=T, b=b, return_info=True)
    # recomputar el residuo como η_Q (certificado del QEP) y filtrar.
    keep, eta = [], []
    for i in range(len(lam)):
        e = _backward_error(M, C, K, lam[i], V[:, i], nM, nC, nK)
        if e < tol_res:
            keep.append(i); eta.append(e)
    keep = np.array(keep, int)
    if keep.size == 0:
        _e = (np.array([]), np.zeros((M.shape[0], 0), complex), np.array([]))
        return (*_e, info) if return_info else _e
    _r = (lam[keep], V[:, keep], np.array(eta))
    return (*_r, info) if return_info else _r


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


def sparse_boundary_xi_shift(K, M, Csurf, freqs_ref, phis_ref, beta, c=343.0,
                             m=3, conf_hz=18.0, max_shifts=10, k_per_shift=24,
                             eta_tol=1e-7, n_quad=48, beyn_tol=1e-5,
                             beyn_fill=True, fallback_xi=None, fallback_f=None,
                             xi_crit=0.35, pal_maxiter=None, couple_thr=0.6,
                             xi_gate=0.08, overlap_strong=0.5, overlap_margin=0.1,
                             return_info=False):
    """QEP de frontera por A+B: PAL (banda de shifts, rápido) para los modos
    OSCILATORIOS + Beyn (contorno) para los que quedan, incluidos los
    SOBREAMORTIGUADOS (polos reales/muy amortiguados, ξ≳1, que un shift imaginario
    no ve). Es el reemplazo del tope Nn≤1800 de `qep_boundary_nodal`. Interfaz
    paralela: devuelve (xi, f_new) (Nm,). Con return_info devuelve además un dict
    {cov_pal, cov_total, n_shifts, n_overdamped, n_beyn}.

    GATE (clave, `xi_gate`): cada contorno Beyn cuesta n_quad factorizaciones LU, así
    que Beyn se dispara SOLO en los modos CASI-CRÍTICOS, que son donde la proyección
    modal subestima; donde el amortiguamiento es modesto el modal ya es exacto
    (bench_front_rear_qep_modal). El "¿es casi-crítico?" se decide con el ξ de 1er
    ORDEN (perturbación diagonal, Morse & Ingard 9.4.14):
        ξ_est_n = (c·|β|/2)·diag(G)_n / ωₙ,   diag(G)_n = φₙᵀ Csurf φₙ,
    que es MONÓTONO en el ξ real y su COTA INFERIOR → todo casi-crítico tiene ξ_est
    no despreciable y queda flaggeado. NO se gatea por el ξ del FALLBACK modal: ese
    SUBESTIMA justo los casi-críticos (p.ej. ξ_fallback=0.34 para un modo de ξ_real
    =1.3, que con el gate viejo `ξ_fallback>xi_crit` quedaba afuera; bug v2.61→2.62,
    bench_qep_sparse_f6). Si se pasa `fallback_xi/f` (la proyección modal), los modos
    que PAL no cubre se rellenan con él, y Beyn se dispara para ξ_est>xi_gate (o el
    ξ_fallback>xi_crit, por si acaso). Beyn pisa el fallback SOLO si AUMENTA el ξ
    (only_if_larger): corrige la subestimación sin dañar un modo ya bien estimado si
    un polo se mis-asigna. Sin fallback, Beyn rellena todo lo que PAL deja (caro).

    Beyn TILEADO (clave para f media-alta): un contorno CIRCULAR único grande SATURA
    el SVD (k=ell, sin gap) porque la densidad modal crece como f² → encierra ~2·Nm
    polos. Se usa en cambio una ELIPSE por cluster de frecuencia, ANCHA en Re (semieje
    a=1.15ωc: alcanza el polo casi-crítico, que está a −ξωₙ del eje imaginario) y
    ANGOSTA en Im (semieje atado a la banda del cluster + el corrimiento de fₙ): el
    ancho en Im controla cuántos modos se encierran, el ancho en Re casi no agrega
    (pocos modos tienen amortiguamiento grande). Todo polo del QEP nodal tiene Im(s)>1
    (filtro Re(ω)>1), así que se descartan los no-físicos (DC, Re≥0).

    VELOCIDAD (`couple_thr`, con fallback): los shifts de PAL se concentran en la
    BANDA de frecuencias de los modos FUERTEMENTE acoplados a la pared trasera
    (diag(G)=φₙᵀCsurfφₙ > couple_thr·max), que son los únicos donde el modal
    subestima; los modos fuera de esa banda (acople débil) usan la proyección modal
    (exacta <7%, bench_front_rear_qep_modal). Esto evita los shifts LENTOS de baja
    frecuencia (ARPACK converge mal ahí) cuando esos modos no lo necesitan. En
    Control Ale baja de ~17 s (couple_thr=0) a ~10 s (couple_thr=0.6) preservando la
    corrección de los modos acoplados, con error ≤0.03 en ξ en los débiles (dentro
    de la precisión del modal). couple_thr=0 = exacto en toda la banda (más lento).

    Para un modo sobreamortiguado se recupera ξ de sus DOS polos reales s1,s2:
    ω_n=√(s1 s2), ξ=−(s1+s2)/(2ω_n) (los polos de la Lorentziana ωₙ²−ω²+2iξωₙω en
    ω=i s son s=iω=reales), y f_new=ω_n/2π."""
    Mp = sp.csr_matrix(M, dtype=complex)
    Cp = (c * complex(beta)) * sp.csr_matrix(Csurf, dtype=complex)
    Kp = (c * c) * sp.csr_matrix(K, dtype=complex)
    freqs_ref = np.asarray(freqs_ref, float)
    phis_ref = np.asarray(phis_ref)
    Nm = int(phis_ref.shape[1]) if phis_ref.ndim == 2 else 0
    if Nm == 0 or freqs_ref.size < Nm:
        return None
    E_surf = lowrank_factor(sp.csr_matrix(Csurf))
    if E_surf is None:
        return None
    E = np.sqrt(c * complex(beta)) * E_surf
    fr = freqs_ref[:Nm]

    # Indicador de acople con la pared trasera por modo: diag(G)=φₙᵀ Csurf φₙ. Los
    # modos de diag(G) GRANDE son los fuertemente amortiguados, donde la proyección
    # modal subestima y hace falta el QEP exacto; los de diag(G) chico los cubre
    # bien el fallback modal. Si hay fallback, los shifts de PAL se concentran en el
    # RANGO de frecuencias de los modos acoplados (evita los shifts lentos de baja
    # frecuencia donde el modal ya es exacto).
    Cs = sp.csr_matrix(Csurf)
    diagG = np.real(np.einsum("in,in->n", phis_ref[:, :Nm],
                              (Cs @ phis_ref[:, :Nm])))
    fb = fallback_xi is not None and fallback_f is not None
    coupled = diagG > couple_thr * float(diagG.max()) if diagG.max() > 0 else np.ones(Nm, bool)
    frng = fr[coupled] if (fb and np.any(coupled)) else fr
    fmin, fmax = float(fr.min()), float(fr.max())
    f_lo, f_hi = float(frng.min()), float(frng.max())

    # --- PAL: banda de shifts (solo sobre el rango acoplado si hay fallback) ---
    ns = int(np.clip(np.ceil((f_hi - f_lo) / (2.0 * conf_hz)) + 1, 2, max_shifts))
    shifts = np.linspace(f_lo, f_hi, ns)
    lam_pool, X_pool = [], []
    for fsh in shifts:
        sigma = 1j * 2.0 * np.pi * float(fsh)
        # k adaptativo: tantos polos como modos haya cerca (+ margen).
        nloc = int(np.sum(np.abs(fr - fsh) < 1.5 * conf_hz))
        k_sh = int(min(k_per_shift, max(2 * nloc + 4, 6)))
        lam, X, eta = pal_qep(Mp, Cp, Kp, sigma, k=k_sh, m=m,
                              mode="sparse", E=E, maxiter=pal_maxiter)
        sel = (eta < eta_tol) & (lam.imag > 0)
        if np.any(sel):
            lam_pool.append(lam[sel]); X_pool.append(X[:, sel])
    lam_all = np.concatenate(lam_pool) if lam_pool else np.array([])
    X_all = (np.concatenate(X_pool, axis=1) if X_pool
             else np.zeros((Mp.shape[0], 0), complex))
    # dedupe
    if lam_all.size:
        order = np.argsort(lam_all.imag)
        lam_all, X_all = lam_all[order], X_all[:, order]
        keep = np.ones(len(lam_all), bool)
        for i in range(1, len(lam_all)):
            if keep[i - 1] and abs(lam_all[i] - lam_all[i - 1]) < 1e-3 * abs(lam_all[i]):
                keep[i] = False
        lam_all, X_all = lam_all[keep], X_all[:, keep]

    xi = np.full(Nm, np.nan); f_new = np.full(Nm, np.nan)

    def _assign(lam_set, X_set, modes, overlap_min=0.3, only_if_larger=False):
        """Voto POLO->MODO: cada polo vota por el modo que mejor solapa (M-prod).
        Un modo recibe sus polos; si no recibe ninguno queda sin cubrir (lo
        rellena Beyn). Con 1 polo complejo: ξ=−Re/Im. Con >=2 reales:
        sobreamortiguado, ξ=−(s1+s2)/(2√(s1 s2)). `only_if_larger`: escribe solo si
        el ξ nuevo SUPERA al que ya había (para el relleno Beyn, cuyo fin es corregir
        la SUBESTIMACIÓN del fallback; si Beyn mis-asigna un polo de menor ξ, no
        pisa el fallback bueno)."""
        if lam_set.size == 0:
            return

        def _put(nm, newxi, newf, conf=1.0, margin=1.0):
            if only_if_larger:
                if np.isfinite(xi[nm]) and not (newxi > xi[nm]):
                    return
                # M3: guarda anti-inflacion en el relleno Beyn. Solo se PISA un modo
                # ya estimado si la asignacion polo->modo es CONFIABLE (solape fuerte
                # y con margen sobre el 2do modo), para no inflar un modo modesto con
                # un polo mal asignado de un vecino casi-degenerado. El 1er pase PAL
                # (only_if_larger=False) es el baseline y escribe sin guarda.
                if conf < overlap_strong or margin < overlap_margin:
                    return
            xi[nm] = newxi; f_new[nm] = newf

        modes = list(modes)
        MX = Mp @ X_set
        den = np.sqrt(np.abs(np.einsum("ik,ik->k", X_set.conj(), MX)))
        IM_ABS = 1.0                                      # |Im(s)|<1 rad/s = real
        votes = {nm: [] for nm in modes}                  # modo -> [(overlap, p, margen)]
        sub = phis_ref[:, modes]                          # (n, |modes|)
        for p in range(X_set.shape[1]):
            rel = np.abs(sub.conj().T @ MX[:, p]) / max(den[p], 1e-30)
            order = np.argsort(rel)[::-1]
            jb = int(order[0])
            second = float(rel[order[1]]) if rel.size > 1 else 0.0
            if rel[jb] >= overlap_min:
                votes[modes[jb]].append((float(rel[jb]), p, float(rel[jb]) - second))
        for nm, vp in votes.items():
            if not vp:
                continue
            vp.sort(reverse=True)                         # por overlap descendente
            conf, pdom, margin = vp[0]                     # polo dominante = mayor overlap
            s_dom = lam_set[pdom]
            if abs(s_dom.imag) >= IM_ABS:                 # oscilatorio
                # s-dominio: Re(s)=-delta, Im(s)=omega_d, |s|=omega_n (natural).
                # xi CLASICO = delta/omega_n (lo que consume el Lorentziano), NO
                # delta/omega_d (bug C1): divergen en el regimen casi-critico.
                smag = abs(s_dom)                         # |s| = omega_n
                _put(nm, (-s_dom.real) / max(smag, 1e-9), smag / (2.0 * np.pi),
                     conf, margin)
            else:                                         # sobreamortiguado (real)
                reals = [lam_set[p].real for _o, p, _m in vp
                         if abs(lam_set[p].imag) < IM_ABS]
                if len(reals) >= 2:
                    reals = sorted(reals, key=abs)        # |s| menor = polo dominante
                    s1, s2 = reals[0], reals[1]
                    wn = np.sqrt(abs(s1 * s2))
                    _put(nm, -(s1 + s2) / (2.0 * max(wn, 1e-9)), wn / (2.0 * np.pi),
                         conf, margin)

    _assign(lam_all, X_all, range(Nm))
    cov_pal = int(np.isfinite(xi).sum()) / Nm
    n_over = 0
    n_beyn = 0
    n_sat = 0                                    # M4: clusters que saturaron el SVD

    # --- Relleno de los modos que PAL no cubre ---
    unc = np.where(~np.isfinite(xi))[0]
    fb = fallback_xi is not None and fallback_f is not None
    # GATE (M2: empiricamente calibrado, NO una cota DEMOSTRADA):
    #   ξ_est_n = (c·|β|/2)·diag(G)_n / ωₙ,   diag(G)_n = φₙᵀ Csurf φₙ (φ M-orton.),
    # es la perturbacion de 1er orden (diagonal, Morse & Ingard 9.4.14). El auditor
    # señaló que NO es cota inferior PROBADA del ξ real. El audit sobre una familia de
    # shoeboxes (bench_qep_sparse_m2) mide ξ_est/ξ_nodal ∈ [0.40, 0.43] para el axial
    # casi-critico, asi que xi_gate=0.08 (< 0.40·xi_crit=0.139) captura todo casi-critico
    # con ξ_real ≳ 0.20, con margen. DOS redes extra cierran la subestimacion del modal:
    #   (a) fallback modal > xi_crit (el modal ya lo ve casi-critico);
    #   (b) SOSPECHA: fallback < ξ_est (con ξ_est no despreciable) → el modal da MENOS
    #       amortiguamiento que la perturbacion diagonal ⇒ probable subestimacion por
    #       truncamiento (p.ej. un modo de ξ_real~0.19 con fallback 0.004 que escaparia
    #       al gate de ξ_est); se flaggea para que Beyn lo verifique.
    # Err hacia flaggear de mas: Beyn de mas = mas lento, pero only_if_larger + la guarda
    # de confianza (M3) no dañan un modo ya bien estimado. Un certificado η con la forma
    # RIGIDA φ_n NO sirve de gate (no separa: mide cuan autovector es φ_n, no el error del
    # ξ del fallback; medido en el bench M2).
    wn_all = np.maximum(2.0 * np.pi * fr, 1e-9)
    xi_est = (c * abs(complex(beta)) / 2.0) * diagG[:Nm] / wn_all
    if fb:
        fbx = np.asarray(fallback_xi, float); fbf = np.asarray(fallback_f, float)
        for n in unc:                                     # proyección modal (rápida)
            if np.isfinite(fbx[n]):
                xi[n] = fbx[n]; f_new[n] = fbf[n]
        beyn_modes = [int(n) for n in unc if xi_est[n] > xi_gate
                      or (np.isfinite(fbx[n]) and fbx[n] > xi_crit)
                      or (np.isfinite(fbx[n]) and fbx[n] < xi_est[n]
                          and xi_est[n] > 0.5 * xi_gate)]
    else:
        beyn_modes = [int(n) for n in unc]

    # --- Beyn TILEADO: una ELIPSE por cluster de frecuencia, ANCHA en Re y ANGOSTA
    # en Im. El ancho en Im controla cuántos modos se encierran (densidad ∝ f²), así
    # que se lo ata a la BANDA de frecuencia del cluster (+ margen por el corrimiento
    # de fₙ de la pared matcheada); el ancho en Re casi no agrega modos (pocos tienen
    # amortiguamiento grande) y es el que ALCANZA el polo casi-crítico, que está a
    # −δ del eje imaginario con δ grande (p.ej. s=−201+i168, δ=201 Np/s). El contorno circular
    # único grande SATURA el SVD (k=ell) en f media-alta. Todo polo del QEP nodal
    # tiene Im(s)>1 (el nodal filtra Re(ω)>1), así que NO hay polos reales puros: se
    # queda la rama oscilatoria y se descartan los polos no-físicos (Re≥0, el DC).
    # Ver auditor_contexto v2.62.
    if beyn_fill and len(beyn_modes) > 0:
        bm_all = np.array(sorted(beyn_modes), int)
        fu = fr[bm_all]
        order = np.argsort(fu)
        bm_all, fu = bm_all[order], fu[order]
        # Clusterizar por hueco en frecuencia (nuevo cluster si salto > conf_hz).
        clusters = []
        cur = [0]
        for i in range(1, len(fu)):
            if fu[i] - fu[i - 1] > conf_hz:
                clusters.append(cur); cur = [i]
            else:
                cur.append(i)
        clusters.append(cur)
        # M4: una banda [fa,fbb] Hz -> una ELIPSE Beyn. Si el SVD SATURA (k>=ell:
        # hay mas polos en el contorno que la sonda), los polos de mas se perderian
        # en SILENCIO; en vez de eso se BISECTA la banda en Im y se recursa (reduce
        # modos-por-contorno a la mitad por nivel) hasta recuperar un SVD con hueco o
        # agotar la profundidad. `ell` se provisiona por la densidad REAL de la banda
        # (todos los modos de `fr` dentro del semieje Im), no por los flaggeados.
        BEYN_MAX_DEPTH = 3

        def _beyn_band(fa, fbb, xg, depth=0):
            fcl = 0.5 * (fa + fbb)
            wc = 2.0 * np.pi * fcl
            margin_hz = (0.10 + 0.35 * xg) * fcl + 8.0
            b_im = 2.0 * np.pi * (0.5 * (fbb - fa) + margin_hz)
            # ALCANCE en Re (clave del fix M1, 12 Oct 2026): el polo de un modo
            # fuertemente matcheado tiene δ=Re GRANDE (amortiguamiento alto) Y su fₙ
            # se CORRE hacia arriba (|s| hasta ~1.7·wc), asi que esta lejos del eje
            # imaginario: s=−δ+iω_d con δ=|s|·ξ. La elipse vieja (a=1.15wc, z0=−0.1wc)
            # NO lo alcanzaba (verificado: fundamental ducto Nn=2430, polo s=−181+124i
            # fuera del contorno → Beyn 0 polos → sparse caia al fallback 0.34 vs nodal
            # 0.825). Se ENSANCHA en Re y se corre el centro a −0.35wc: alcanza δ hasta
            # ~1.85wc (ξ~0.97 con corrimiento 1.7×). Ensanchar en Re NO agrega modos (se
            # diferencian en Im/frecuencia, no en Re), asi que NO satura el SVD. El Im
            # (ω_d) se mantiene en banda porque el corrimiento de |s| compensa la caida
            # por el amortiguamiento. Oraculo: SLEPc a escala (bench_qep_slepc_scale).
            a_re = 1.5 * wc                                # alcanza ξ→1 + corrimiento
            z0 = -0.35 * wc + 1j * wc                      # centro en el 2do cuadrante
            lo_hz = fcl - b_im / (2.0 * np.pi)
            hi_hz = fcl + b_im / (2.0 * np.pi)
            nband = int(np.sum((fr >= lo_hz) & (fr <= hi_hz)))   # densidad REAL
            ellp = int(min(Mp.shape[0] - 2, max(2 * nband + 12, 18)))
            lam_b, V_b, _e, info = beyn_qep(Mp, Cp, Kp, z0, a_re, n_quad=n_quad,
                                            ell=ellp, tol_res=beyn_tol, b=b_im,
                                            return_info=True)
            if (info.get("saturated") and depth < BEYN_MAX_DEPTH
                    and (fbb - fa) > 0.5 * conf_hz):
                fmid = fcl
                l1, v1, s1 = _beyn_band(fa, fmid, xg, depth + 1)
                l2, v2, s2 = _beyn_band(fmid, fbb, xg, depth + 1)
                ll = [x for x in (l1, l2) if x.size]
                vv = [x for x in (v1, v2) if x.size]
                lam_c = np.concatenate(ll) if ll else np.zeros(0, complex)
                V_c = (np.concatenate(vv, axis=1) if vv
                       else np.zeros((Mp.shape[0], 0), complex))
                return lam_c, V_c, s1 + s2
            return lam_b, V_b, (1 if info.get("saturated") else 0)

        lam_pool_b, X_pool_b = [], []
        for cl in clusters:
            idx = np.array(cl, int)
            fa, fbb = float(fu[idx].min()), float(fu[idx].max())
            # ξ_est medio del cluster: alto = casi-crítico (fₙ cae mucho) → margen de
            # Im grande; bajo = modesto (fₙ casi no se mueve) → Im angosto.
            xg = float(np.clip(np.mean(xi_est[bm_all[idx]]), 0.0, 1.0))
            lam_b, V_b, s_sat = _beyn_band(fa, fbb, xg)
            n_sat += int(s_sat)
            if lam_b.size:
                lam_pool_b.append(lam_b); X_pool_b.append(V_b)
        if lam_pool_b:
            lam_b_all = np.concatenate(lam_pool_b)
            X_b_all = np.concatenate(X_pool_b, axis=1)
            # Solo polos físicos: oscilatorios (Im>1), estables y amortiguados (Re<0).
            phys = (lam_b_all.imag > 1.0) & (lam_b_all.real < -1e-9)
            lam_b_all, X_b_all = lam_b_all[phys], X_b_all[:, phys]
            n_over = int(np.sum(lam_b_all.real < -lam_b_all.imag))  # ξ>1
            n_beyn = len(bm_all)
            if lam_b_all.size:
                _assign(lam_b_all, X_b_all, list(bm_all), only_if_larger=True)
    cov_total = int(np.isfinite(xi).sum()) / Nm
    if return_info:
        return xi, f_new, {"cov_pal": cov_pal, "cov_total": cov_total,
                           "n_shifts": ns, "n_overdamped": n_over,
                           "n_beyn": n_beyn, "n_saturated": n_sat}
    return xi, f_new
