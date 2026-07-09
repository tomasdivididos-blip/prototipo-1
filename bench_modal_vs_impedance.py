"""
bench_modal_vs_impedance.py
===========================

Comparativa empirica entre:
  (A) Modal damping con xi_n derivado de RT60_Sabine (lo que ya hace la app).
  (B) Matriz C de impedancia ensamblada en superficie, Z derivada de alpha
      via reflection coefficient (asume Z real, incidencia normal).

Setup:
  - Shoebox 5x4x3 m, paredes con alpha=0.30 uniforme.
  - Malla voxel n_per_meter=2.
  - 12 modos.
  - Fuente puntual en esquina, receptor central.
  - FRF en 40 puntos entre 20 y 150 Hz (regimen modal).

Reporta:
  - Tabla de modos analiticos vs FEM.
  - Tabla FRF |H(f)| en dB SPL para ambos metodos + diferencia.
  - Tiempos de cada paso.
  - Resumen estadistico de diferencias.
"""

from __future__ import annotations

import sys
import time
import json
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

sys.path.insert(0, r"C:\Users\aceve\OneDrive\Escritorio\prototipo 1")

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import (build_KM, solve_modes, FieldEvaluator,
                          frequency_response)
from sources import SourceArray, OmniSource, RHO0, C0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def analytic_modes(Lx, Ly, Lz, max_n=5, c=343.0, n_keep=12):
    out = []
    for l in range(max_n):
        for m in range(max_n):
            for n in range(max_n):
                if l + m + n == 0:
                    continue
                f = (c / 2.0) * np.sqrt((l / Lx) ** 2 + (m / Ly) ** 2 + (n / Lz) ** 2)
                out.append((f, l, m, n))
    out.sort()
    return out[:n_keep]


def extract_boundary_faces(tets, Nn):
    """Caras tri de frontera = caras compartidas por un solo tet."""
    face_combos = [(1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2)]
    parts = [tets[:, list(c)] for c in face_combos]
    all_faces = np.vstack(parts)                # (4*Ne, 3)
    sorted_faces = np.sort(all_faces, axis=1)
    # Hash compuesta para detectar duplicados.
    keys = (sorted_faces[:, 0].astype(np.int64) * (Nn ** 2)
            + sorted_faces[:, 1].astype(np.int64) * Nn
            + sorted_faces[:, 2].astype(np.int64))
    order = np.argsort(keys)
    sorted_keys = keys[order]
    diff_prev = np.concatenate([[True], sorted_keys[1:] != sorted_keys[:-1]])
    diff_next = np.concatenate([sorted_keys[:-1] != sorted_keys[1:], [True]])
    is_unique = diff_prev & diff_next
    boundary_idx = order[is_unique]
    return sorted_faces[boundary_idx]


def assemble_surface_M(nodes, faces):
    """C_surf[i,j] = integral_dOmega Ni Nj dS (sin escalar por 1/Z).

    Para triangulo lineal: integral Ni Nj dS = (A/12) * (1 + delta_ij).
    El factor iw*rho0/Z se aplica en el loop de frecuencia.
    """
    Nn = nodes.shape[0]
    coords = nodes[faces]                              # (Nf, 3, 3)
    v0, v1, v2 = coords[:, 0], coords[:, 1], coords[:, 2]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)        # (Nf,)
    local = np.ones((3, 3)) + np.eye(3)                # 2 diag, 1 off
    Ce = (areas[:, None, None] / 12.0) * local[None]   # (Nf, 3, 3)
    rows = np.repeat(faces, 3, axis=1).reshape(-1, 3, 3)
    cols = np.tile(faces[:, None, :], (1, 3, 1))
    C = sp.coo_matrix(
        (Ce.ravel(), (rows.ravel(), cols.ravel())),
        shape=(Nn, Nn),
    ).tocsr()
    return C


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    Lx, Ly, Lz = 5.0, 4.0, 3.0
    alpha = 0.30
    n_per_meter = 2.0
    n_modes = 12
    f_min, f_max, n_freqs = 20.0, 150.0, 40

    V = Lx * Ly * Lz
    S = 2.0 * (Lx * Ly + Lx * Lz + Ly * Lz)

    print("=" * 70)
    print(f"BENCHMARK Modal damping vs C-matrix de impedancia")
    print("=" * 70)
    print(f"Sala: {Lx} x {Ly} x {Lz} m  |  V={V} m^3  |  S={S} m^2")
    print(f"alpha={alpha} (uniforme)  |  n_per_meter={n_per_meter}  |  n_modes={n_modes}")
    print()

    # ---- Geometria + malla
    t0 = time.perf_counter()
    verts, tris, edges, n_walls_ = make_room(Lx, Ly, Lz, n_walls=4,
                                              roof_type="flat", subdiv_levels=0)
    t_geom = time.perf_counter() - t0

    t0 = time.perf_counter()
    nodes, tets = build_volume_mesh(verts, tris, n_per_meter=n_per_meter)
    t_mesh = time.perf_counter() - t0
    Nn, Ne = nodes.shape[0], tets.shape[0]
    print(f"Malla: {Nn} nodos, {Ne} tets")

    # ---- K, M
    t0 = time.perf_counter()
    K, M, vols = build_KM(nodes, tets)
    t_KM = time.perf_counter() - t0

    # ---- Caras de frontera
    t0 = time.perf_counter()
    bfaces = extract_boundary_faces(tets, Nn)
    t_bnd = time.perf_counter() - t0
    print(f"Caras de frontera: {bfaces.shape[0]}")

    # ---- Modos
    t0 = time.perf_counter()
    freqs, phis = solve_modes(K, M, n_modes=n_modes)
    t_eigsh = time.perf_counter() - t0

    print()
    print(f"Modos (FEM vs analitico):")
    ana = analytic_modes(Lx, Ly, Lz, n_keep=n_modes)
    err_modos = []
    for i, f in enumerate(freqs):
        fa, l, m, n = ana[i]
        err = (f - fa) / fa * 100.0
        err_modos.append(err)
        print(f"  modo {i+1:2d}: FEM={f:7.2f} Hz | analitico ({l}{m}{n})={fa:7.2f} Hz | err={err:+6.2f}%")
    err_modos = np.array(err_modos)

    # ---- xi_n por modo (Sabine)
    RT60 = 0.161 * V / (alpha * S)
    xi_n = 1.1 / (freqs * RT60)
    print()
    print(f"RT60 Sabine (alpha={alpha}) = {RT60*1000:.0f} ms")
    print(f"xi_n: min={xi_n.min():.4f}, max={xi_n.max():.4f}, mean={xi_n.mean():.4f}")

    # ---- Fuente, receptor
    src_pos = (0.30, 0.30, 0.30)        # esquina (excita todos los modos)
    rx_pos = (2.50, 2.00, 1.50)         # centro
    src_Q = 1.0e-3                      # m^3/s

    sources = SourceArray()
    sources.add(OmniSource(position=src_pos, Q=complex(src_Q, 0)))
    locator = FieldEvaluator(nodes, tets)

    freq_axis = np.linspace(f_min, f_max, n_freqs)

    # ---- Metodo A: modal damping (lo de la app)
    t0 = time.perf_counter()
    H_modal = frequency_response(locator, freqs, phis, sources, rx_pos,
                                 freq_axis, damping=xi_n)
    t_modal = time.perf_counter() - t0

    # ---- Metodo B: matriz C, sweep directo
    # Z = rho0*c * (1+r)/(1-r),  r = sqrt(1-alpha)  (asume normal incid., Z real)
    r_coef = np.sqrt(1.0 - alpha)
    Z = RHO0 * C0 * (1.0 + r_coef) / (1.0 - r_coef)
    print(f"\nZ_pared (alpha={alpha}) = {Z:.1f} Pa*s/m  |  Z/(rho0*c) = {Z/(RHO0*C0):.2f}")

    t0 = time.perf_counter()
    C_surf = assemble_surface_M(nodes, bfaces)         # geom, sin 1/Z
    t_C = time.perf_counter() - t0

    # Source vector (peso por bary del tet contenedor)
    e_src, N_src = locator.locate(np.asarray(src_pos, dtype=float))
    if e_src is None:
        print("ERROR: fuente fuera de la malla.")
        return
    source_node_w = np.zeros(Nn)
    src_tet = tets[e_src]
    for j, idx in enumerate(src_tet):
        source_node_w[idx] += N_src[j] * src_Q

    # Sweep frecuencia. Forma debil: (K - k^2 M + iw*rho0/Z * C_surf) p = iw*rho0 f
    # con k = omega/c (NO omega).
    t0 = time.perf_counter()
    H_direct = np.zeros(n_freqs, dtype=complex)
    for i, f in enumerate(freq_axis):
        omega = 2.0 * np.pi * f
        k_sq = (omega / C0) ** 2
        A = (K - k_sq * M + (1j * omega * RHO0 / Z) * C_surf).tocsc()
        b = 1j * omega * RHO0 * source_node_w
        p = spsolve(A, b)
        p_rx = locator.evaluate_one(p, rx_pos)
        H_direct[i] = 0.0 if p_rx is None else complex(p_rx)
    t_direct = time.perf_counter() - t0

    # ---- Comparativa
    # Desde v2.11: frequency_response devuelve H ya escalado con el factor c^2
    # canonico de la Green function modal de Helmholtz. No hace falta shift.
    eps = 1e-30
    mag_modal = 20.0 * np.log10(np.abs(H_modal) / 20e-6 + eps)
    mag_direct = 20.0 * np.log10(np.abs(H_direct) / 20e-6 + eps)
    diff_db = mag_modal - mag_direct

    print()
    print("=" * 70)
    print("TABLA FRF — modal (post-fix v2.11) vs C-matrix (dB SPL re 20 uPa)")
    print("=" * 70)
    print(f"{'f [Hz]':>8} {'modal':>10} {'C-matrix':>10} {'diff [dB]':>10}")
    print("-" * 44)
    for i, f in enumerate(freq_axis):
        print(f"{f:8.1f} {mag_modal[i]:10.2f} {mag_direct[i]:10.2f} {diff_db[i]:+10.2f}")

    print()
    print("=" * 70)
    print("TIEMPOS")
    print("=" * 70)
    print(f"make_room          : {t_geom*1000:8.1f} ms")
    print(f"build_volume_mesh  : {t_mesh*1000:8.1f} ms")
    print(f"build_KM           : {t_KM*1000:8.1f} ms")
    print(f"extract bound faces: {t_bnd*1000:8.1f} ms")
    print(f"eigsh ({n_modes} modos)   : {t_eigsh*1000:8.1f} ms")
    print(f"assemble C         : {t_C*1000:8.1f} ms")
    print(f"FRF modal ({n_freqs} pts): {t_modal*1000:8.1f} ms")
    print(f"FRF directo ({n_freqs} pts): {t_direct*1000:8.1f} ms")

    pipeline_modal = t_KM + t_eigsh + t_modal
    pipeline_direct = t_KM + t_bnd + t_C + t_direct
    print()
    print(f"Pipeline COMPLETO modal damping: {pipeline_modal*1000:.0f} ms")
    print(f"Pipeline COMPLETO C-matrix    : {pipeline_direct*1000:.0f} ms")
    print(f"Ratio direct / modal: {pipeline_direct/pipeline_modal:.1f}x")

    # Stats segmentadas
    in_modal_band = (freq_axis >= 30.0) & (freq_axis <= 100.0)
    out_modal_band = ~in_modal_band

    print()
    print("=" * 70)
    print("ESTADISTICAS DE DIFERENCIA (post-compensacion calibracion)")
    print("=" * 70)
    print(f"Banda 20-100 Hz (regimen modal):")
    print(f"  Max |diff|: {np.max(np.abs(diff_db[in_modal_band])):.2f} dB")
    print(f"  RMS diff  : {np.sqrt(np.mean(diff_db[in_modal_band]**2)):.2f} dB")
    print(f"  Mean diff : {np.mean(diff_db[in_modal_band]):+.2f} dB")
    print(f"Banda total 20-150 Hz:")
    print(f"  Max |diff|: {np.max(np.abs(diff_db)):.2f} dB")
    print(f"  RMS diff  : {np.sqrt(np.mean(diff_db**2)):.2f} dB")
    print(f"  Mean diff : {np.mean(diff_db):+.2f} dB")
    print()
    print(f"Error modos FEM vs analitico: max={np.max(np.abs(err_modos)):.2f}%, "
          f"rms={np.sqrt(np.mean(err_modos**2)):.2f}%")

    # ---- Picos modales
    print()
    print("PICOS modales en la FRF (modal vs C-matrix):")
    from scipy.signal import find_peaks
    pk_m, _ = find_peaks(mag_modal, prominence=3.0)
    pk_d, _ = find_peaks(mag_direct, prominence=3.0)
    print(f"  picos modal:    {[f'{freq_axis[i]:.1f}Hz/{mag_modal[i]:.1f}dB' for i in pk_m]}")
    print(f"  picos C-matrix: {[f'{freq_axis[i]:.1f}Hz/{mag_direct[i]:.1f}dB' for i in pk_d]}")

    # ---- Dump JSON
    out = {
        "config": {
            "L": [Lx, Ly, Lz], "V": V, "S": S, "alpha": alpha,
            "n_per_meter": n_per_meter, "n_modes": n_modes,
            "freq_axis": freq_axis.tolist(),
        },
        "mesh": {"Nn": int(Nn), "Ne": int(Ne), "n_bfaces": int(bfaces.shape[0])},
        "RT60_sabine": RT60,
        "Z_wall": Z,
        "modes_fem": freqs.tolist(),
        "modes_analytic": [a[0] for a in ana],
        "err_modos_pct": err_modos.tolist(),
        "xi_n": xi_n.tolist(),
        "H_modal_db": mag_modal.tolist(),
        "H_direct_db": mag_direct.tolist(),
        "diff_db": diff_db.tolist(),
        "stats": {
            "max_abs_diff_db_full": float(np.max(np.abs(diff_db))),
            "rms_diff_db_full": float(np.sqrt(np.mean(diff_db**2))),
            "mean_diff_db_full": float(np.mean(diff_db)),
            "max_abs_diff_db_modal_band": float(np.max(np.abs(diff_db[in_modal_band]))),
            "rms_diff_db_modal_band": float(np.sqrt(np.mean(diff_db[in_modal_band]**2))),
        },
        "times_ms": {
            "geom": t_geom*1000, "mesh": t_mesh*1000, "KM": t_KM*1000,
            "bnd": t_bnd*1000, "eigsh": t_eigsh*1000, "C": t_C*1000,
            "frf_modal": t_modal*1000, "frf_direct": t_direct*1000,
            "pipeline_modal": pipeline_modal*1000,
            "pipeline_direct": pipeline_direct*1000,
            "ratio": pipeline_direct/pipeline_modal,
        },
    }
    with open("bench_modal_vs_impedance.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print()
    print("[OK] Resultados en bench_modal_vs_impedance.json")


if __name__ == "__main__":
    main()
