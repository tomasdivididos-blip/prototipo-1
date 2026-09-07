# -*- coding: utf-8 -*-
"""Reconstruccion de la geometria de FLAIR desde la nube de puntos.

FLAIR entrega la frontera como nube de 2.9M puntos + normales (escaneo laser), no
como un .obj. Para simular necesitamos una superficie CERRADA que alimente
`acoustic_mesh.build_volume_mesh`. La sala es casi-shoebox (98.7% de normales
axiales) PERO (a) esta rotada ~8.5 deg respecto de los ejes del dato y (b) tiene
features reales (nicho, escalon de techo). Ademas la nube es un muestreo finito:
rasterizada en voxeles queda POROSA y el flood-fill de 6-conectividad se cuela.

Metodo (encaja con D0: nucleo numpy/scipy; skimage/scipy = IO/mallado):
  1. Alinear: estimar el yaw de la sala desde las normales horizontales y ROTAR
     la nube (y las posiciones) para dejar las paredes paralelas a los ejes.
     Es un rigido: no cambia la fisica, baja el escalonado y hace Lx/Ly/Lz
     interpretables. Las fn son invariantes a rotacion; las posiciones de M4 se
     mapean con el mismo transform.
  2. Occupancy grid -> mascara de PARED.
  3. Sellar la porosidad por dilatacion (s vox), flood-fill desde un mic = INTERIOR,
     y CORREGIR el engorde re-dilatando el interior s vox sin cruzar los puntos
     originales (& ~wall). Converge estable en s.
  4. marching_cubes sobre el interior -> superficie cerrada.
"""
import numpy as np
from scipy import ndimage
from skimage import measure


def _rot_z(angle_rad):
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def estimate_yaw_deg(normals):
    """Yaw de la sala [deg] desde las normales casi-horizontales (moda mod 90)."""
    h = normals[np.abs(normals[:, 2]) < 0.2]
    a90 = np.mod(np.degrees(np.arctan2(h[:, 1], h[:, 0])), 90.0)
    hist, edges = np.histogram(a90, bins=90, range=(0, 90))
    peak = edges[np.argmax(hist)] + 0.5
    sel = np.abs(a90 - peak) < 8.0
    return float(a90[sel].mean())


def _touches_grid_boundary(mask):
    """True si la mascara toca cualquiera de las 6 caras de la grilla.

    Un interior SELLADO esta rodeado de pared (la nube se padea con exterior),
    asi que no debe tocar el borde. Si lo toca, el flood-fill se escapo (fuga).
    """
    return bool(mask[0].any() or mask[-1].any()
                or mask[:, 0].any() or mask[:, -1].any()
                or mask[:, :, 0].any() or mask[:, :, -1].any())


def reconstruct_room(points, normals, seed_xyz, positions=None,
                     hv=0.04, seal=3):
    """Nube -> superficie cerrada del interior (sala alineada a ejes).

    Parameters
    ----------
    points, normals : (N,3)   nube de frontera + normales (coords del dato).
    seed_xyz : (3,)           un punto seguro adentro (una posicion de mic).
    positions : list[(M,3)]   arrays de posiciones a mapear al marco alineado (mic, spk).
    hv : float                voxel [m] de la occupancy.
    seal : int                vox de dilatacion para sellar la porosidad.

    Returns dict con: verts, tris (superficie alineada), Lx/Ly/Lz, V_interior,
    theta_deg, R, pivot, y `positions_aligned` (misma lista, rotada).
    """
    points = np.asarray(points, float)
    theta = estimate_yaw_deg(np.asarray(normals, float))
    R = _rot_z(np.deg2rad(-theta))                 # alinear: deshacer el yaw
    pivot = points.mean(axis=0)

    def apply(x):
        return (np.atleast_2d(x) - pivot) @ R.T + pivot

    P = apply(points)
    seed = apply(seed_xyz)[0]

    pmin = P.min(axis=0) - 3 * hv
    pmax = P.max(axis=0) + 3 * hv
    dims = np.ceil((pmax - pmin) / hv).astype(int) + 1

    idx = np.clip(np.floor((P - pmin) / hv).astype(int), 0, dims - 1)
    wall = np.zeros(dims, dtype=bool)
    wall[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    sidx0 = np.clip(np.floor((seed - pmin) / hv).astype(int), 0, dims - 1)

    def _fill(s):
        """Sella con dilatacion s, flood-fill desde el seed. Devuelve (interior_pre, leaked)."""
        wall_d = ndimage.binary_dilation(wall, iterations=s)
        lbl, _n = ndimage.label(~wall_d)
        sidx = sidx0.copy()
        seed_lab = lbl[sidx[0], sidx[1], sidx[2]]
        if seed_lab == 0:                           # seed en pared: vox libre mas cercano
            fi = np.argwhere(~wall_d)
            sidx = fi[np.argmin(np.sum((fi - sidx) ** 2, axis=1))]
            seed_lab = lbl[sidx[0], sidx[1], sidx[2]]
        interior_pre = (lbl == seed_lab)
        return interior_pre, _touches_grid_boundary(interior_pre)

    # Guard de regimen (auditor M1, 2026-09-06): un seal chico deja la pared porosa y
    # el fill se escapa (interior toca el borde de la grilla). "auto" sube el seal
    # hasta sellar; con seal fijo, se marca leaked si no sello.
    if seal == "auto":
        seal_used, leaked = None, True
        for s in range(1, 9):
            interior_pre, leaked = _fill(s)
            if not leaked:
                seal_used = s
                break
        if leaked:
            raise RuntimeError("reconstruct_room: no se pudo sellar la nube (fuga con seal<=8); "
                               "la geometria no es reconstruible con este metodo/resolucion.")
        seal = seal_used
    else:
        interior_pre, leaked = _fill(int(seal))
        seal_used = int(seal)

    # corregir el engorde: re-dilatar sin cruzar los puntos originales
    interior = ndimage.binary_dilation(interior_pre, iterations=seal_used) & ~wall

    V_int = float(interior.sum() * hv ** 3)
    ijk = np.argwhere(interior)
    L = (ijk.max(0) - ijk.min(0) + 1) * hv          # extent interior por eje

    vol = np.pad(interior.astype(np.float32), 1, mode="constant", constant_values=0.0)
    verts_vox, faces, _nrm, _val = measure.marching_cubes(vol, level=0.5)
    verts = (verts_vox - 1.0) * hv + pmin

    pos_al = None
    if positions is not None:
        pos_al = [apply(np.asarray(p, float)) for p in positions]

    return dict(verts=verts, tris=faces.astype(int), V_interior=V_int,
                Lx=float(L[0]), Ly=float(L[1]), Lz=float(L[2]),
                theta_deg=theta, R=R, pivot=pivot, hv=hv,
                seal_used=seal_used, leaked=bool(leaked),
                positions_aligned=pos_al)


if __name__ == "__main__":
    from scipy.io import loadmat
    from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
    from acoustic_fem import build_KM, solve_modes
    m = loadmat("datasets/flair/data_FLAIR.mat", squeeze_me=True)
    pts, nrm = m["boundary_points"].T, m["boundary_normals"].T
    mic, spk = m["mic_positions"].T, m["spkr_positions"].T
    c = float(m["c"])
    seed = mic[len(mic) // 2]

    print("Reconstruyendo FLAIR (alineado)...")
    for hv in (0.05, 0.04):
        r = reconstruct_room(pts, nrm, seed, positions=[mic, spk], hv=hv, seal=3)
        print(f"  hv={hv}: theta={r['theta_deg']:.2f} deg | "
              f"L={r['Lx']:.2f}x{r['Ly']:.2f}x{r['Lz']:.2f} | V={r['V_interior']:.1f} m3 | "
              f"tris={len(r['tris'])}")
    # confirmar que la superficie mallea y resuelve
    r = reconstruct_room(pts, nrm, seed, positions=[mic, spk], hv=0.04, seal=3)
    nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=4.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, _ph = solve_modes(K, M, n_modes=20, c=c)
    info = mesh_info(nodes, tets)
    print(f"  malla FEM: nodes={len(nodes)} tets={len(tets)} h_max={info['h_max']:.3f} "
          f"f_max={max_solver_frequency(info['h_max']):.0f} Hz")
    print(f"  primeros modos FEM [Hz]: {np.round(freqs[:8], 1)}")
