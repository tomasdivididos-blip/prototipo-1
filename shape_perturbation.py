"""
shape_perturbation.py
=====================

Corrimiento modal por PERTURBACION DE FORMA del dominio (teorema de Slater;
Morse & Ingard, *Theoretical Acoustics*, §9.4; Pierce, *Acoustics*, §9). Ruta d
del plan `plan_optimizacion_fuentes_unificada.md` §8: alternativa ANALITICA rapida
al FEM real (ruta e). Cuando una sala no rectangular se aproxima por su caja
envolvente (AABB), la caja AGREGA volumen (esquinas/chaflanes que la sala real no
tiene). Este modulo corrige las frecuencias modales analiticas de la caja quitando
ese volumen extra, SIN re-resolver un FEM.

Formula (para quitar un volumen δV de una cavidad de paredes rigidas):

    Δf_n / f_n  =  [ ∫_δV ( p_n² − k_n⁻² |∇p_n|² ) dV ]  /  [ 2 ∫_V p_n² dV ]

Signo (derivado en 1D y validado contra el modo exacto de la caja mas chica):
quitar volumen donde el modo tiene MAXIMO DE PRESION (p² grande, ∇p≈0) SUBE f_n;
donde tiene MAXIMO DE VELOCIDAD (∇p grande, p≈0) la BAJA. (El plan tenia el signo
invertido en el LaTeX; la prosa era correcta.)

Validez: δV chico frente a V y frente a λ (primer orden). Para correcciones grandes
o geometrias arbitrarias, usar el FEM real (ruta e, ya implementada).

Modos analiticos de la caja rigida Lx×Ly×Lz (Morse & Ingard 9.4.5):
    p_n(x,y,z) = cos(nx π x/Lx) cos(ny π y/Ly) cos(nz π z/Lz)
    f_n = (c/2) sqrt( (nx/Lx)² + (ny/Ly)² + (nz/Lz)² )
"""

from __future__ import annotations

import numpy as np

from sources import C0


def enumerate_modes(dims, n_modes: int, c: float = C0):
    """Los `n_modes` modos rigidos mas bajos de la caja (excluye el (0,0,0)).
    Devuelve lista de (f_n, (nx, ny, nz)) ordenada por frecuencia."""
    Lx, Ly, Lz = [float(x) for x in dims]
    # cota de indices holgada para no perder modos bajos
    nmax = int(np.ceil((2.0 * n_modes) ** (1.0 / 3.0))) + 3
    cand = []
    for nx in range(nmax + 1):
        for ny in range(nmax + 1):
            for nz in range(nmax + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue
                f = 0.5 * c * np.sqrt((nx / Lx) ** 2 + (ny / Ly) ** 2 + (nz / Lz) ** 2)
                cand.append((float(f), (nx, ny, nz)))
    cand.sort(key=lambda t: t[0])
    return cand[:n_modes]


def _mode_norm(dims, n):
    """∫_V p_n² dV analitico = V · ∏(1/2 si n_i≥1, 1 si n_i=0)."""
    V = float(np.prod([float(x) for x in dims]))
    fac = 1.0
    for ni in n:
        fac *= 0.5 if ni >= 1 else 1.0
    return V * fac


def perturbed_freqs(dims, inside_mask, *, n_modes: int = 20, c: float = C0,
                    grid_n: int = 40, origin=(0.0, 0.0, 0.0)):
    """Frecuencias modales de la caja AABB CORREGIDAS por quitar el volumen extra.

    Parameters
    ----------
    dims : (Lx, Ly, Lz) de la caja AABB.
    inside_mask : callable (P,3)->bool(P,). True si el punto (coords caja, es decir
        mundo − origin, en [0,L]) esta DENTRO del recinto REAL. El volumen a quitar
        es δV = {puntos de la caja que NO estan dentro del recinto real}.
    n_modes : cuantos modos corregir (los mas bajos).
    grid_n : resolucion de la cuadratura por eje (grid_n³ celdas).
    origin : esquina min del AABB en mundo (para llamar a inside_mask en coords caja).

    Returns
    -------
    lista de dicts {n, f_aabb, f_corr, rel_shift}, ordenada por f_aabb.
    """
    Lx, Ly, Lz = [float(x) for x in dims]
    modes = enumerate_modes(dims, n_modes, c)

    # Grilla de centros de celda sobre la caja.
    gx = (np.arange(grid_n) + 0.5) / grid_n * Lx
    gy = (np.arange(grid_n) + 0.5) / grid_n * Ly
    gz = (np.arange(grid_n) + 0.5) / grid_n * Lz
    X, Y, Z = np.meshgrid(gx, gy, gz, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)   # (P,3) coords caja
    dV = (Lx * Ly * Lz) / (grid_n ** 3)

    ins = np.asarray(inside_mask(pts), dtype=bool)
    dv_mask = ~ins                                  # δV = caja \ recinto real
    if not dv_mask.any():
        # la caja ES el recinto (o inside_mask no discrimina): sin correccion
        return [{"n": n, "f_aabb": f, "f_corr": f, "rel_shift": 0.0}
                for f, n in modes]
    xd, yd, zd = pts[dv_mask, 0], pts[dv_mask, 1], pts[dv_mask, 2]

    out = []
    for f, (nx, ny, nz) in modes:
        ax, ay, az = nx * np.pi / Lx, ny * np.pi / Ly, nz * np.pi / Lz
        cx, cy, cz = np.cos(ax * xd), np.cos(ay * yd), np.cos(az * zd)
        sx, sy, sz = np.sin(ax * xd), np.sin(ay * yd), np.sin(az * zd)
        p = cx * cy * cz
        # ∇p componentes
        dpx = -ax * sx * cy * cz
        dpy = -ay * cx * sy * cz
        dpz = -az * cx * cy * sz
        grad2 = dpx * dpx + dpy * dpy + dpz * dpz
        kn = 2.0 * np.pi * f / c
        integrand = p * p - (grad2 / (kn * kn) if kn > 0 else 0.0)
        num = float(np.sum(integrand) * dV)
        denom = 2.0 * _mode_norm(dims, (nx, ny, nz))
        rel = num / denom if denom > 0 else 0.0
        out.append({"n": (nx, ny, nz), "f_aabb": float(f),
                    "f_corr": float(f * (1.0 + rel)), "rel_shift": float(rel)})
    return out
