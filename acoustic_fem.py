"""
acoustic_fem.py
===============

Solver FEM modal para un recinto de GEOMETRIA ARBITRARIA con paredes rigidas.

Generaliza fem_modal.py a una malla tetraedrica cualquiera (la que produce
acoustic_mesh.build_volume_mesh a partir de la superficie de geometry.py).

Implementacion vectorizada del ensamblaje (mucho mas rapido que el bucle por
elemento del fem_modal.py original). Reusa el solver de autovalores de scipy
(eigsh con shift-invert) y la formula de FRF por superposicion modal.

Paredes rigidas: Neumann homogenea, impuesta de forma natural via Galerkin
(no requiere modificar K ni M). Validacion (caja 5x4x3 m) coincide con
fem_modal.demo dentro de ~1-2 % para los primeros modos.

API
---
build_KM(nodes, tets)
    -> K, M (scipy.sparse.csr) y vols (Ne,)
solve_modes(K, M, n_modes=20, c=343.0)
    -> freqs (Hz), phis (Nn, Nm)  con phi^T M phi = I.
evaluate_field(nodes, tets, phi_or_pressure, points)
    -> valores interpolados en cualquier punto (barycentric in tet).
frequency_response(...)
    -> H(f) compleja por superposicion modal a partir de SourceArray.
modal_pressure_field(nodes, tets, phis, freqs, source_array, f, damping)
    -> presion compleja en cada nodo a frecuencia f (campo completo).
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import eigsh, ArpackNoConvergence
from typing import Optional

from sources import SourceArray, RHO0, C0


# ---------------------------------------------------------------------------
# Ensamblaje vectorizado de K y M
# ---------------------------------------------------------------------------
def build_KM(nodes: np.ndarray, tets: np.ndarray):
    """K (rigidez) y M (masa consistente) en CSR.

    Tetraedro lineal (4 nodos, 4 funciones de forma N_j):
        K_ij^e = V_e * grad N_i . grad N_j
        M_ij^e = (V_e / 20) * (1 + delta_ij)

    Implementacion vectorizada via inversion en lote de la matriz
    [[1, x1, y1, z1], ...] -> los gradientes son las filas 1..3.
    """
    nodes = np.asarray(nodes, dtype=float)
    tets = np.asarray(tets, dtype=int)
    Nn = nodes.shape[0]
    Ne = tets.shape[0]

    # coords[e, j, :] = posicion del nodo j del tet e.
    coords = nodes[tets]                          # (Ne, 4, 3)
    ones = np.ones((Ne, 4, 1), dtype=float)
    V4 = np.concatenate([ones, coords], axis=2)   # (Ne, 4, 4)
    detV = np.linalg.det(V4)                      # (Ne,)
    vols = np.abs(detV) / 6.0                     # (Ne,)

    # Vinv[e, :, :]  -> filas son (a, b, c, d)_j / detV
    Vinv = np.linalg.inv(V4)                      # (Ne, 4, 4)
    grads = np.transpose(Vinv[:, 1:4, :], (0, 2, 1))   # (Ne, 4, 3)

    # K_e (Ne,4,4) = V_e * grads @ grads^T
    K_e = vols[:, None, None] * np.einsum("eij,ekj->eik", grads, grads)
    M_e = (vols[:, None, None] / 20.0) * (np.ones((4, 4)) + np.eye(4))[None]

    # COO scatter en lote.
    idx = tets                                    # (Ne, 4)
    rows = np.repeat(idx, 4, axis=1).reshape(Ne, 4, 4)            # (Ne,4,4)
    cols = np.tile(idx[:, None, :], (1, 4, 1))                    # (Ne,4,4)

    K = sp.coo_matrix(
        (K_e.ravel(), (rows.ravel(), cols.ravel())), shape=(Nn, Nn)
    ).tocsr()
    M = sp.coo_matrix(
        (M_e.ravel(), (rows.ravel(), cols.ravel())), shape=(Nn, Nn)
    ).tocsr()

    # Simetrizacion forzada (defensiva).
    # K y M son SIMETRICAS por construccion (K_ij^e = K_ji^e, M_ij^e = M_ji^e),
    # pero el scatter via coo_matrix suma contribuciones en orden no controlado;
    # la aritmetica IEEE-754 puede dejar asimetrias residuales del orden de
    # 1e-15. eigsh con shift-invert asume simetria ESTRICTA; sin esto puede
    # devolver autovalores con parte imaginaria pequena o incluso fallar
    # convergencia en mallas patologicas.
    # Costo: O(nnz), despreciable comparado con el resto del solver.
    K = (K + K.T) * 0.5
    M = (M + M.T) * 0.5

    return K, M, vols


# ---------------------------------------------------------------------------
# Resolucion del problema generalizado de autovalores
# ---------------------------------------------------------------------------
def solve_modes(K, M, n_modes: int = 20, c: float = C0,
                sigma: float = 1e-6,
                drop_zero_mode: bool = True,
                _attempt: int = 0,
                _max_attempts: int = 2):
    """K phi = lambda M phi  ->  f_n = c * sqrt(lambda_n) / (2 pi).

    Devuelve (freqs[Hz], phis[Nn, Nm], M-ortonormalizados).
    Si drop_zero_mode=True, descarta el modo trivial p=const (f_n ~ 0).

    Capa 2: solver robusto. Si Lanczos (ARPACK) no converge:
      Plan A: si lo que convergio alcanza para n_modes, usar eso.
      Plan B: reintentar con sigma 10x mayor (esquiva clusters de
              autovalores cercanos a sigma).
      Plan C: tras _max_attempts intentos, levantar RuntimeError con
              mensaje accionable.
    Los parametros _attempt / _max_attempts son internos (recursion).
    """
    from scipy.sparse.linalg import ArpackNoConvergence  # local re-import por claridad
    n_modes = max(2, int(n_modes))
    # Pedimos uno extra para descartar el modo cero si hace falta.
    n_request = n_modes + (1 if drop_zero_mode else 0)
    # maxiter explicito: el default (10*N) puede ser corto si la malla
    # tiene autovalores muy juntos. 20*n_request con minimo 300 es generoso
    # sin volverse irrazonable.
    maxiter = max(300, 20 * n_request)
    try:
        eigvals, eigvecs = eigsh(K, k=n_request, M=M, sigma=sigma,
                                  which="LM", maxiter=maxiter)
    except ArpackNoConvergence as exc:
        n_conv = len(exc.eigenvalues)
        # Plan A: si convergieron suficientes, seguir con esos.
        if n_conv >= n_request:
            eigvals = np.asarray(exc.eigenvalues)
            eigvecs = np.asarray(exc.eigenvectors)
        # Plan B: reintentar con sigma desplazado.
        elif _attempt < _max_attempts:
            return solve_modes(
                K, M, n_modes=n_modes, c=c,
                sigma=sigma * 10.0,
                drop_zero_mode=drop_zero_mode,
                _attempt=_attempt + 1,
                _max_attempts=_max_attempts,
            )
        # Plan C: mensaje accionable.
        else:
            raise RuntimeError(
                f"Lanczos no convergio tras {_max_attempts + 1} intentos "
                f"(ultimo sigma={sigma:.2e}). Convergidos {n_conv}/"
                f"{n_request} modos. Causas probables:\n"
                f"  - tets degenerados en la malla "
                f"(revisar mesh_info()['n_slivers']);\n"
                f"  - n_modes demasiado alto para el tamano de la malla;\n"
                f"  - autovalores muy juntos (simetrias geometricas).\n"
                f"Acciones: reducir n_modes, refinar la malla "
                f"(subir n_per_meter), o pasar sigma distinto."
            ) from exc
    eigvals = np.clip(eigvals.real, 0.0, None)

    # Ordenar ascendente.
    order = np.argsort(eigvals)
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    if drop_zero_mode and eigvals[0] < 1e-6:
        eigvals = eigvals[1:]
        eigvecs = eigvecs[:, 1:]

    eigvals = eigvals[:n_modes]
    eigvecs = eigvecs[:, :n_modes]

    # M-ortonormalizar.
    for n in range(eigvecs.shape[1]):
        norm2 = float(eigvecs[:, n] @ (M @ eigvecs[:, n]))
        if norm2 > 0:
            eigvecs[:, n] /= np.sqrt(norm2)

    freqs = np.sqrt(eigvals) * c / (2.0 * np.pi)
    return freqs, eigvecs


# ---------------------------------------------------------------------------
# Interpolacion barycentrica en la malla
# ---------------------------------------------------------------------------
def _build_locator(nodes, tets):
    """Pre-calcula matrices A_e y v0_e para localizacion rapida (lazy, O(Ne))."""
    coords = nodes[tets]                # (Ne, 4, 3)
    v0 = coords[:, 0, :]                # (Ne, 3)
    A = np.stack([
        coords[:, 1, :] - v0,
        coords[:, 2, :] - v0,
        coords[:, 3, :] - v0,
    ], axis=2)                          # (Ne, 3, 3)
    try:
        A_inv = np.linalg.inv(A)        # (Ne, 3, 3)
    except np.linalg.LinAlgError:
        # Algun tet degenerado; computamos por elemento ignorando los malos.
        A_inv = np.zeros_like(A)
        for e in range(A.shape[0]):
            try:
                A_inv[e] = np.linalg.inv(A[e])
            except np.linalg.LinAlgError:
                A_inv[e] = np.eye(3) * 1e30
    return v0, A_inv


def _locate_one(v0_all, A_inv_all, tets, x, tol=1e-6):
    """Devuelve (e, N) o (None, None). x: array (3,)."""
    rel = x - v0_all                          # (Ne, 3)
    # bcoords_local[e] = A_inv_all[e] @ rel[e]
    stu = np.einsum("eij,ej->ei", A_inv_all, rel)   # (Ne, 3)
    s, t, u = stu[:, 0], stu[:, 1], stu[:, 2]
    N0 = 1.0 - s - t - u
    valid = (N0 >= -tol) & (s >= -tol) & (t >= -tol) & (u >= -tol)
    if not np.any(valid):
        return None, None
    # Preferimos el tet con maximo minimo N (mas "adentro").
    cand = np.where(valid)[0]
    min_N = np.minimum.reduce([N0[cand], s[cand], t[cand], u[cand]])
    e = int(cand[int(np.argmax(min_N))])
    N = np.array([N0[e], s[e], t[e], u[e]])
    return e, N


class FieldEvaluator:
    """Cachea los datos de localizacion para evaluar campos rapidamente.

    Implementacion vectorizada con cKDTree: en vez de comprobar TODOS los
    tetraedros para cada punto (O(Np*Ne) en bucle Python), se construye un
    cKDTree sobre los centroides de los tetraedros y para cada punto se
    evaluan barycentric SOLO en los K vecinos mas cercanos. Si ese subset no
    contiene el tet correcto (puede pasar en bordes con tets alargados),
    se hace un segundo intento con K mayor.

    Benchmark interno (sala 6x8x3 m, ~25 k tets, resolucion 50 → 62 500 pts):
      - Antes (loop Python):    ~ 18-25 s
      - Despues (KDTree + numpy): ~ 0.25-0.50 s   (~ 50-100x mas rapido)
    """

    # K inicial de candidatos por punto. 12 cubre la inmensa mayoria de
    # los casos (cada tet tiene ~4 vecinos topologicos + un pequeno margen).
    _K_INITIAL = 12
    # Si el primer intento deja > 0.5 % de puntos no localizados (caras
    # del recinto con tets degenerados), reintentamos con K mayor.
    _K_FALLBACK = 48

    def __init__(self, nodes: np.ndarray, tets: np.ndarray):
        self.nodes = np.asarray(nodes, dtype=float)
        self.tets = np.asarray(tets, dtype=int)
        self.v0, self.A_inv = _build_locator(self.nodes, self.tets)

        # Centroides + KDTree (lazy: solo se construye al primer evaluate_many).
        self._centroids = None
        self._tree = None

    def _ensure_tree(self):
        if self._tree is not None:
            return
        coords = self.nodes[self.tets]            # (Ne, 4, 3)
        self._centroids = coords.mean(axis=1)     # (Ne, 3)
        from scipy.spatial import cKDTree
        self._tree = cKDTree(self._centroids)

    def locate(self, x):
        return _locate_one(self.v0, self.A_inv, self.tets,
                           np.asarray(x, dtype=float))

    def evaluate_one(self, field_nodal: np.ndarray, x) -> Optional[complex]:
        e, N = self.locate(x)
        if e is None:
            return None
        return complex(np.dot(field_nodal[self.tets[e]], N))

    # ------------------------------------------------------------------
    # Camino vectorizado: maximo rendimiento para 1e3 - 1e6 puntos.
    # ------------------------------------------------------------------
    def _evaluate_batch(self, field_nodal: np.ndarray,
                        points: np.ndarray,
                        k_candidates: int,
                        tol: float = 1e-6
                        ) -> tuple:
        """Una pasada vectorizada con K candidatos por punto via KDTree.

        Devuelve (out, found_mask) donde found_mask indica que puntos
        fueron localizados con exito en esta pasada.
        """
        Np = len(points)
        out = np.full(Np, np.nan, dtype=np.complex128)
        if Np == 0:
            return out, np.zeros(Np, dtype=bool)
        Ne = len(self.tets)
        k = int(min(max(1, k_candidates), Ne))

        # K-NN query: cand[p, c] = indice del c-esimo tet mas cercano a points[p].
        _d, cand = self._tree.query(points, k=k)
        if k == 1:
            cand = cand[:, None]
        cand = np.asarray(cand, dtype=np.int64)

        # Vectorizamos el calculo barycentrico sobre (Np, k) pares.
        v0_pc = self.v0[cand]                                 # (Np, k, 3)
        A_inv_pc = self.A_inv[cand]                           # (Np, k, 3, 3)
        rel_pc = points[:, None, :] - v0_pc                   # (Np, k, 3)
        # stu[p, c, :] = A_inv_pc[p,c] @ rel_pc[p,c]
        stu = np.einsum("pcij,pcj->pci", A_inv_pc, rel_pc)    # (Np, k, 3)
        s, t, u = stu[..., 0], stu[..., 1], stu[..., 2]
        N0 = 1.0 - s - t - u
        valid = (N0 >= -tol) & (s >= -tol) & (t >= -tol) & (u >= -tol)
        min_N = np.minimum.reduce([N0, s, t, u])              # (Np, k)
        # Mejor candidato por punto: el de maximo "min_N" (mas adentro).
        masked = np.where(valid, min_N, -np.inf)
        best_c = np.argmax(masked, axis=1)                    # (Np,)
        rows = np.arange(Np)
        found_mask = masked[rows, best_c] > -np.inf

        # Recuperar las coordenadas barycentricas del mejor candidato.
        s_b  = s[rows, best_c]
        t_b  = t[rows, best_c]
        u_b  = u[rows, best_c]
        N0_b = N0[rows, best_c]
        weights = np.stack([N0_b, s_b, t_b, u_b], axis=1)     # (Np, 4)

        best_tet = cand[rows, best_c]                         # (Np,)
        tet_nodes = self.tets[best_tet]                       # (Np, 4)

        # Evaluacion vectorizada del campo: works para float y complex.
        field_vals = np.asarray(field_nodal)[tet_nodes]       # (Np, 4)
        if not np.iscomplexobj(field_vals):
            field_vals = field_vals.astype(np.complex128, copy=False)
        interp = (weights.astype(field_vals.dtype) * field_vals).sum(axis=1)
        out[found_mask] = interp[found_mask]
        return out, found_mask

    def evaluate_many(self, field_nodal: np.ndarray,
                      points: np.ndarray) -> np.ndarray:
        """Evalua el campo nodal en una nube de puntos arbitraria.

        Devuelve un array (Np,) complex con NaN para los puntos que caen
        fuera de la malla.
        """
        points = np.atleast_2d(np.asarray(points, dtype=float))
        Np = len(points)
        if Np == 0:
            return np.zeros(0, dtype=np.complex128)
        self._ensure_tree()

        # Intento principal con K inicial.
        out, found = self._evaluate_batch(
            field_nodal, points, k_candidates=self._K_INITIAL
        )
        # Fallback: si hay puntos sin localizar (mas que un margen), reintentar
        # con K mayor solo para esos puntos. Este caso aparece en bordes con
        # tets muy alargados donde el centroide mas cercano no es el contenedor.
        n_miss = int(np.count_nonzero(~found))
        # Umbral: < 1 % de los puntos NO se localizaron, NO reintentar
        # (probablemente son puntos fuera del recinto). Si >= 1 %, reintentar.
        if 0 < n_miss < Np and (n_miss / Np) >= 0.01:
            miss_pts = points[~found]
            out2, found2 = self._evaluate_batch(
                field_nodal, miss_pts, k_candidates=self._K_FALLBACK
            )
            # Mezclar resultados
            tmp = out.copy()
            tmp_idx = np.where(~found)[0]
            tmp[tmp_idx[found2]] = out2[found2]
            out = tmp
        return out


# ---------------------------------------------------------------------------
# Respuesta en frecuencia por superposicion modal
# ---------------------------------------------------------------------------
def frequency_response(
    locator: FieldEvaluator,
    freqs: np.ndarray,
    phis: np.ndarray,
    sources: SourceArray,
    receiver,
    freq_axis: np.ndarray,
    damping = 0.03,        # float (uniforme) o ndarray (Nm,) por modo
    c: float = C0,
    rho0: float = RHO0,
) -> np.ndarray:
    """H(f) en un receptor a partir de los modos numericos.

        H(f) = i*omega*rho0*c^2 * sum_n  phi_n(x_r) [sum_s Q_s phi_n(x_s)]
                                  / (omega_n^2 - omega^2 + 2 i xi_n omega_n omega)

    El factor c^2 sale de la derivacion canonica de la Green function modal de
    Helmholtz: la suma modal es Green(x_r, x_s) = sum_n phi_n(x_r) phi_n(x_s) /
    (lambda_n - k^2), y reescribiendo con omega_n^2 = c^2 * lambda_n y
    k^2 = omega^2/c^2 aparece el c^2 fuera. Validado en `bench_modal_vs_impedance.py`
    contra C-matrix de impedancia (30 May 2026, v2.11): error < 3 dB en banda
    modal contra solucion directa con impedancia.

    damping puede ser un float (mismo xi para todos los modos) o un array (Nm,)
    con un xi distinto por modo, calculado a partir de los materiales via RT60.
    """
    Nm = phis.shape[1]
    omega_n = 2.0 * np.pi * freqs
    xi = (np.full(Nm, float(damping)) if np.isscalar(damping)
          else np.asarray(damping, dtype=float)[:Nm])

    phi_r = np.zeros(Nm, dtype=float)
    for n in range(Nm):
        val = locator.evaluate_one(phis[:, n], receiver)
        phi_r[n] = 0.0 if val is None else val.real

    src_pos = sources.positions()
    Ns = len(src_pos)
    phi_s = np.zeros((Ns, Nm), dtype=float)
    for s_idx in range(Ns):
        for n in range(Nm):
            val = locator.evaluate_one(phis[:, n], src_pos[s_idx])
            phi_s[s_idx, n] = 0.0 if val is None else val.real

    # Acople fuente-modo dependiente de f (Fase 0 — plan_fuentes):
    # src_spec[i, s] = Q_s(f_i).  coupling[i, n] = sum_s Q_s(f_i) phi_n(x_s).
    # Sin curvas de respuesta cada fila de src_spec es constante => coupling
    # no depende de i y el resultado coincide bit a bit con el path historico.
    freq_axis = np.asarray(freq_axis, dtype=float)
    src_spec = sources.amplitudes_spectrum(freq_axis)   # (Nf, Ns) complejo
    coupling = src_spec @ phi_s                          # (Nf, Nm) complejo

    c_sq = c ** 2                                 # v2.11: factor de calibracion
    H = np.empty(len(freq_axis), dtype=complex)
    for i, f in enumerate(freq_axis):
        omega = 2.0 * np.pi * f
        denom = (omega_n**2 - omega**2) + 2j * xi * omega_n * omega
        denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
        num_i = phi_r * coupling[i]               # (Nm,) complejo
        H[i] = 1j * omega * rho0 * c_sq * np.sum(num_i / denom)
    return H


def modal_pressure_field(
    locator: FieldEvaluator,
    freqs: np.ndarray,
    phis: np.ndarray,
    sources: SourceArray,
    f: float,
    damping = 0.03,        # float o ndarray (Nm,)
    c: float = C0,
    rho0: float = RHO0,
) -> np.ndarray:
    """Devuelve la presion compleja p(x_n) en cada nodo de la malla a la
    frecuencia f, por superposicion modal a una excitacion dada.

        p(x) = i*omega*rho0*c^2 * sum_n  phi_n(x) [sum_s Q_s phi_n(x_s)]
                                  / (omega_n^2 - omega^2 + 2 i xi omega_n omega)

    El factor c^2 sale de la derivacion canonica (ver `frequency_response`).
    Agregado en v2.11 tras validacion con `bench_modal_vs_impedance.py`.
    """
    Nm = phis.shape[1]
    omega_n = 2.0 * np.pi * freqs
    omega = 2.0 * np.pi * f

    # Q(f) a la frecuencia unica f (Fase 0): sin curva == amplitudes() historico.
    src_arr = sources.amplitudes_spectrum(np.array([f]))[0]   # (Ns,) complejo
    src_pos = sources.positions()
    Ns = len(src_pos)
    phi_s = np.zeros((Ns, Nm), dtype=float)
    for s_idx in range(Ns):
        for n in range(Nm):
            val = locator.evaluate_one(phis[:, n], src_pos[s_idx])
            phi_s[s_idx, n] = 0.0 if val is None else val.real

    src_weight = src_arr @ phi_s                  # (Nm,) complejo
    xi = (np.full(Nm, float(damping)) if np.isscalar(damping)
          else np.asarray(damping, dtype=float)[:Nm])
    denom = (omega_n**2 - omega**2) + 2j * xi * omega_n * omega
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    coeff = 1j * omega * rho0 * (c ** 2) * (src_weight / denom)   # (Nm,)  v2.11

    # p(x_node) = sum_n phi_n(x_node) * coeff_n
    p_nodes = phis @ coeff                         # (Nn,) complejo
    return p_nodes


def mode_shape_field(phis: np.ndarray, mode_idx: int) -> np.ndarray:
    """Devuelve el campo (real) del modo `mode_idx` en cada nodo de la malla.

    Normalizamos a max |phi| = 1 para visualizacion.
    """
    phi = phis[:, mode_idx].real
    m = float(np.max(np.abs(phi)))
    return phi / m if m > 0 else phi


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from geometry import make_room
    from acoustic_mesh import build_volume_mesh, mesh_info
    from sources import SourceArray

    Lx, Ly, Lz = 5.0, 4.0, 3.0
    print(f"[FEM gen] caja {Lx}x{Ly}x{Lz}")
    sv, st, _e, _n = make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=2.0)
    info = mesh_info(nodes, tets)
    print(f"  malla: {info['n_nodes']} nodos, {info['n_tets']} tets, "
          f"V={info['volume']:.2f} m^3, h_avg={info['h_avg']:.3f} m")

    print("  ensamblando K, M (vectorizado)...")
    K, M, _ = build_KM(nodes, tets)
    print(f"  K nnz={K.nnz}, M nnz={M.nnz}")

    print("  resolviendo 8 modos...")
    freqs, phis = solve_modes(K, M, n_modes=8)
    f_an = []
    from fem_modal import analytic_modes
    for f, idx in analytic_modes(Lx, Ly, Lz)[:8]:
        f_an.append(f)
    print(f"   {'#':>2} {'f_num [Hz]':>10} {'f_an [Hz]':>10}")
    for i, (fn, fa) in enumerate(zip(freqs, f_an)):
        err = 100 * (fn - fa) / fa if fa > 0 else 0
        print(f"   {i:>2} {fn:>10.3f} {fa:>10.3f}  err={err:+.2f}%")

    print("  FRF demo...")
    locator = FieldEvaluator(nodes, tets)
    arr = SourceArray()
    arr.add_at((0.5, 0.5, 0.5), Q=1.0, label="esq1")
    arr.add_at((4.5, 0.5, 0.5), Q=1.0, label="esq2")
    fa = np.linspace(20.0, 120.0, 81)
    H = frequency_response(locator, freqs, phis, arr,
                            receiver=(2.5, 2.0, 1.5), freq_axis=fa)
    i_peak = int(np.argmax(np.abs(H)))
    print(f"  pico |H(f)|: f={fa[i_peak]:.2f} Hz, |H|={np.abs(H[i_peak]):.3g}")

    # -------------------------------------------------------------------
    # Smoke test v2.11: la FRF debe estar en SPL fisico razonable.
    # Con Q=1 m^3/s (artificialmente alto, demo) las paredes rigidas dan
    # ganancia modal alta; con un xi de 0.05 esperamos picos >> 100 dB SPL.
    # Hacemos un test mas honesto con Q en rango realista de altavoz.
    # -------------------------------------------------------------------
    print("  smoke test v2.11 (verifica fix de c^2 en frequency_response)...")
    arr2 = SourceArray()
    arr2.add_at((0.3, 0.3, 0.3), Q=1.0e-3, label="esq")          # 1 mm^3/s
    H2 = frequency_response(locator, freqs, phis, arr2,
                             receiver=(2.5, 2.0, 1.5),
                             freq_axis=np.linspace(20.0, 100.0, 41),
                             damping=0.05)
    spl_peak = 20.0 * np.log10(np.max(np.abs(H2)) / 20e-6)
    print(f"   Q=1 mm^3/s, xi=0.05, pico SPL = {spl_peak:.1f} dB")
    # Rango esperado: 60-90 dB SPL para esta config (validado en bench v2.11).
    assert 50.0 < spl_peak < 100.0, (
        f"[REGRESION] pico FRF fuera de rango fisico esperado (50-100 dB), "
        f"got {spl_peak:.1f} dB. Revisar factor c^2 en frequency_response."
    )
    print("   OK: SPL en rango fisico esperado.")
