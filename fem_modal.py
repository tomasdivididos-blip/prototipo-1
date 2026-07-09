"""
fem_modal.py
============

Solver FEM modal para un recinto rectangular Lx x Ly x Lz con paredes rigidas.

Discretiza el dominio Omega = [0,Lx] x [0,Ly] x [0,Lz] en una malla
estructurada hexaedrica que se subdivide en 6 tetraedros lineales por
hexaedro (split conforme). Ensambla las matrices globales dispersas:

   K (rigidez)     K_ij = integral_Omega  grad N_i . grad N_j  dV
   M (masa)        M_ij = integral_Omega  N_i N_j              dV

y resuelve el problema de autovalores generalizado

   K phi_n = lambda_n M phi_n,    lambda_n = k_n^2,    f_n = c sqrt(lambda_n) / (2 pi)

con paredes rigidas (Neumann homogenea, impuesta de forma natural via
forma debil de Galerkin -- no requiere modificar K ni M).

Calcula la respuesta en frecuencia en un receptor a partir de un conjunto de
fuentes omnidireccionales (modulo sources.py) por superposicion modal:

   H(f; x_r) = i*omega*rho0*c^2 * sum_n  phi_n(x_r) [sum_s Q_s phi_n(x_s)]
                                  / (omega_n^2 - omega^2 + 2 i xi_n omega_n omega).

Referencias: Ihlenburg (1998), Zienkiewicz-Taylor (2000), Kuttruff (2016).
Ver tambien la seccion FEM y el Anexo A del documento principal.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import eigsh
from typing import Tuple

from sources import SourceArray, RHO0, C0


# ---------------------------------------------------------------------------
# Mallado: hexaedros estructurados particionados en 6 tetraedros conformes
# ---------------------------------------------------------------------------
# Numeracion de los 8 vertices del hexaedro de referencia [0,1]^3:
#   0=(0,0,0) 1=(1,0,0) 2=(0,1,0) 3=(1,1,0)
#   4=(0,0,1) 5=(1,0,1) 6=(0,1,1) 7=(1,1,1)
# Split en 6 tetraedros que comparten la diagonal 0-7 (Freudenthal, conforme):
HEX_TO_TETS = np.array([
    [0, 1, 3, 7],
    [0, 1, 7, 5],
    [0, 5, 7, 4],
    [0, 3, 2, 7],
    [0, 2, 6, 7],
    [0, 6, 4, 7],
], dtype=int)


def build_box_mesh(Lx: float, Ly: float, Lz: float,
                   nx: int, ny: int, nz: int):
    """Malla estructurada de tetraedros para un paralelepipedo Lx*Ly*Lz.

    Returns
    -------
    nodes : (Nn, 3) coordenadas de los nodos.
    tets  : (Ne, 4) indices de los 4 nodos de cada tetraedro.
    """
    xs = np.linspace(0.0, Lx, nx + 1)
    ys = np.linspace(0.0, Ly, ny + 1)
    zs = np.linspace(0.0, Lz, nz + 1)

    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    def gid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    tets = np.empty((nx * ny * nz * 6, 4), dtype=int)
    e = 0
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                v = (
                    gid(i,     j,     k),     # 0
                    gid(i + 1, j,     k),     # 1
                    gid(i,     j + 1, k),     # 2
                    gid(i + 1, j + 1, k),     # 3
                    gid(i,     j,     k + 1), # 4
                    gid(i + 1, j,     k + 1), # 5
                    gid(i,     j + 1, k + 1), # 6
                    gid(i + 1, j + 1, k + 1), # 7
                )
                for tet in HEX_TO_TETS:
                    tets[e] = (v[tet[0]], v[tet[1]], v[tet[2]], v[tet[3]])
                    e += 1
    return nodes, tets


# ---------------------------------------------------------------------------
# Matrices elementales (tetraedro lineal)
# ---------------------------------------------------------------------------
def _element_KM(coords: np.ndarray):
    """Devuelve K_e (4x4) y M_e (4x4) para un tetraedro de vertices coords (4,3).

    Para un tetraedro lineal:
       N_j(x) = (a_j + b_j x + c_j y + d_j z) / (6 V_e),
       grad N_j = (b_j, c_j, d_j) / (6 V_e)  =>  constante en el elemento.
    Luego:
       K_ij = V_e * grad N_i . grad N_j,
       M_ij = (V_e / 20) * (1 + delta_ij)   (matriz de masa consistente).
    """
    # Volumen con signo a partir del determinante de la matriz de Vandermonde.
    V4 = np.column_stack([np.ones(4), coords])      # (4,4)
    detV = np.linalg.det(V4)
    V_e = abs(detV) / 6.0

    # Inversa de V4: las filas de Vinv contienen (a_j, b_j, c_j, d_j) / det,
    # tal que N_j(x,y,z) = Vinv[0,j] + Vinv[1,j]*x + Vinv[2,j]*y + Vinv[3,j]*z
    # ya es el polinomio "limpio" (la division por 6 V_e queda implicita en det).
    Vinv = np.linalg.inv(V4)
    grads = Vinv[1:4, :].T         # (4,3): fila j = grad N_j

    K_e = V_e * (grads @ grads.T)
    M_e = (V_e / 20.0) * (np.ones((4, 4)) + np.eye(4))
    return K_e, M_e


# ---------------------------------------------------------------------------
# Ensamblaje global (COO -> CSR)
# ---------------------------------------------------------------------------
def assemble(nodes: np.ndarray, tets: np.ndarray):
    """Ensambla las matrices globales K y M en formato CSR."""
    Nn = nodes.shape[0]
    Ne = tets.shape[0]

    rows = np.empty(16 * Ne, dtype=np.int64)
    cols = np.empty(16 * Ne, dtype=np.int64)
    Kdata = np.empty(16 * Ne, dtype=float)
    Mdata = np.empty(16 * Ne, dtype=float)

    for e in range(Ne):
        idx = tets[e]
        coords = nodes[idx]
        K_e, M_e = _element_KM(coords)

        # Aplanar el bloque 4x4 en 16 entradas (orden fila-mayor).
        base = 16 * e
        for i in range(4):
            for j in range(4):
                p = base + 4 * i + j
                rows[p] = idx[i]
                cols[p] = idx[j]
                Kdata[p] = K_e[i, j]
                Mdata[p] = M_e[i, j]

    K = sp.coo_matrix((Kdata, (rows, cols)), shape=(Nn, Nn)).tocsr()
    M = sp.coo_matrix((Mdata, (rows, cols)), shape=(Nn, Nn)).tocsr()
    # Las entradas duplicadas (mismo (i,j) por varios elementos) ya se
    # suman automaticamente al construir COO->CSR.
    return K, M


# ---------------------------------------------------------------------------
# Resolucion del problema de autovalores
# ---------------------------------------------------------------------------
def solve_modes(K, M, n_modes: int = 20, c: float = C0, sigma: float = 1e-6):
    """Resuelve K phi = lambda M phi para los n_modes autovalores menores.

    Devuelve frecuencias en Hz y autovectores M-ortonormalizados.

    `sigma` se usa como punto de shift para el shift-invert (Lanczos):
    poner exactamente 0 puede ser numericamente fragil porque (K - 0*M) es
    semidefinida (modo constante con lambda = 0).
    """
    eigvals, eigvecs = eigsh(K, k=n_modes, M=M, sigma=sigma, which="LM")
    # eigsh devuelve los autovalores ya cerca de sigma; aseguramos signo.
    eigvals = np.clip(eigvals.real, 0.0, None)

    # Reordenar por autovalor creciente.
    order = np.argsort(eigvals)
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    # M-ortonormalizar: phi^T M phi = 1.
    for n in range(eigvecs.shape[1]):
        norm2 = float(eigvecs[:, n] @ (M @ eigvecs[:, n]))
        if norm2 > 0.0:
            eigvecs[:, n] /= np.sqrt(norm2)

    freqs = np.sqrt(eigvals) * c / (2.0 * np.pi)
    return freqs, eigvecs


# ---------------------------------------------------------------------------
# Localizacion de un punto en la malla -> interpolacion
# ---------------------------------------------------------------------------
def _locate(nodes: np.ndarray, tets: np.ndarray,
            x: np.ndarray, tol: float = 1e-9):
    """Encuentra el tetraedro que contiene x. Devuelve (e, N) con N en R^4
    (coordenadas baricentricas) o (None, None) si x esta fuera.

    Implementacion O(N_e), suficiente para mallas medianas.
    """
    x = np.asarray(x, dtype=float)
    for e in range(tets.shape[0]):
        coords = nodes[tets[e]]
        A = np.column_stack([
            coords[1] - coords[0],
            coords[2] - coords[0],
            coords[3] - coords[0],
        ])
        try:
            sol = np.linalg.solve(A, x - coords[0])
        except np.linalg.LinAlgError:
            continue
        s, t, u = sol
        N = np.array([1.0 - s - t - u, s, t, u])
        if np.all(N >= -tol):
            return e, N
    return None, None


def evaluate_mode_at_point(nodes, tets, phi, x):
    """Interpola un campo nodal phi en el punto x usando funciones de forma."""
    e, N = _locate(nodes, tets, x)
    if e is None:
        raise ValueError(f"Punto {tuple(x)} fuera de la malla.")
    return float(np.dot(phi[tets[e]], N))


# ---------------------------------------------------------------------------
# Respuesta en frecuencia por superposicion modal
# ---------------------------------------------------------------------------
def frequency_response(
    nodes: np.ndarray,
    tets: np.ndarray,
    freqs: np.ndarray,
    phis: np.ndarray,
    sources: SourceArray,
    receiver,
    freq_axis: np.ndarray,
    damping: float = 0.03,
    c: float = C0,
    rho0: float = RHO0,
):
    """FRF en el receptor para una SourceArray dada.

       H(f) = i*omega*rho0*c^2 * sum_n  phi_n(x_r) * [sum_s Q_s phi_n(x_s)]
                                  / (omega_n^2 - omega^2 + 2 i xi omega_n omega)

    El factor c^2 sale de la derivacion canonica de la Green function modal
    de Helmholtz (ver `acoustic_fem.frequency_response` para la justificacion
    completa). Agregado en v2.11.

    `damping` es xi (factor de amortiguamiento adimensional, igual para todos
    los modos, modelo simplificado).
    """
    receiver = np.asarray(receiver, dtype=float)
    Nm = phis.shape[1]
    omega_n = 2.0 * np.pi * freqs

    # Pre-evaluar phi_n en las fuentes y en el receptor.
    phi_r = np.array([
        evaluate_mode_at_point(nodes, tets, phis[:, n], receiver)
        for n in range(Nm)
    ])
    phi_s_per_src = []
    for s in sources:
        phi_s_per_src.append(np.array([
            evaluate_mode_at_point(nodes, tets, phis[:, n], s.position)
            for n in range(Nm)
        ]))
    Q_array = sources.amplitudes()

    # Acumulador del numerador independiente de omega:
    #   num_n = phi_n(x_r) * sum_s Q_s phi_n(x_s).
    num = np.zeros(Nm, dtype=complex)
    for s_idx in range(len(sources)):
        num += Q_array[s_idx] * phi_s_per_src[s_idx]
    num *= phi_r

    c_sq = c ** 2                                        # v2.11
    H = np.zeros(len(freq_axis), dtype=complex)
    for i, f in enumerate(freq_axis):
        omega = 2.0 * np.pi * f
        denom = (omega_n**2 - omega**2) + 2j * damping * omega_n * omega
        # El modo cero (omega_n = 0) tiene denom = -omega^2; no es resonante.
        # Sustituir valores muy chicos para evitar 0/0 si omega_n=0 y omega=0.
        denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
        H[i] = 1j * omega * rho0 * c_sq * np.sum(num / denom)
    return H


# ---------------------------------------------------------------------------
# Comparacion con la solucion analitica
# ---------------------------------------------------------------------------
def analytic_modes(Lx: float, Ly: float, Lz: float,
                   n_max: int = 6, c: float = C0):
    """Frecuencias modales exactas del paralelepipedo rigido, ordenadas."""
    out = []
    for nx in range(n_max):
        for ny in range(n_max):
            for nz in range(n_max):
                if nx == 0 and ny == 0 and nz == 0:
                    continue  # modo trivial p = const, f = 0
                f = (c / 2.0) * np.sqrt(
                    (nx / Lx) ** 2 + (ny / Ly) ** 2 + (nz / Lz) ** 2)
                out.append((f, (nx, ny, nz)))
    out.sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# Demo / driver
# ---------------------------------------------------------------------------
def demo():
    Lx, Ly, Lz = 5.0, 4.0, 3.0
    nx, ny, nz = 8, 6, 5     # h ~ 0.6 m  (regla lambda/6 para f_max ~ 95 Hz)

    print("[FEM] mallado...")
    nodes, tets = build_box_mesh(Lx, Ly, Lz, nx, ny, nz)
    print(f"      {nodes.shape[0]} nodos, {tets.shape[0]} tetraedros")

    print("[FEM] ensamblaje K, M...")
    K, M = assemble(nodes, tets)
    print(f"      K nnz={K.nnz}, M nnz={M.nnz}")

    print("[FEM] resolviendo modos...")
    freqs_num, phis = solve_modes(K, M, n_modes=15)

    print("[FEM] modos numericos vs analiticos:")
    print(f"   {'#':>2} {'f_num [Hz]':>12} {'f_an [Hz]':>12}  modo (nx,ny,nz)")
    f_an = analytic_modes(Lx, Ly, Lz)
    # Saltar el modo cero (f_num[0] ~ 0).
    for i in range(min(10, len(freqs_num))):
        f_num = freqs_num[i]
        if i == 0:
            print(f"   {i:>2} {f_num:>12.3f} {0.0:>12.3f}  (0,0,0)  modo constante")
        else:
            f_a, idx = f_an[i - 1]
            print(f"   {i:>2} {f_num:>12.3f} {f_a:>12.3f}  ({idx[0]},{idx[1]},{idx[2]})")

    print("\n[FEM] respuesta en frecuencia (FRF)...")
    arr = SourceArray([
        # Dos fuentes esquinadas para excitar todos los modos posibles.
        # Una esquina excita maximos de TODOS los modos cosenoidales.
        # Las muevo un poco hacia adentro para que esten dentro de un tetraedro.
        # (en una esquina exacta el localizador puede caer en frontera).
    ])
    arr.add_at(position=(0.5, 0.5, 0.5), Q=1.0 + 0j, label="esq1")
    arr.add_at(position=(4.5, 0.5, 0.5), Q=1.0 + 0j, label="esq2")
    arr.validate(dims=(Lx, Ly, Lz))
    receiver = (2.5, 2.0, 1.5)
    fa = np.linspace(20.0, 120.0, 201)
    Hfrf = frequency_response(nodes, tets, freqs_num, phis, arr, receiver, fa)
    i_peak = int(np.argmax(np.abs(Hfrf)))
    print(f"      pico de |H(f)|: f={fa[i_peak]:.2f} Hz, |H|={np.abs(Hfrf[i_peak]):.3g}")
    return freqs_num, fa, Hfrf


if __name__ == "__main__":
    demo()
