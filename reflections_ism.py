"""
reflections_ism.py
==================

Fuentes-imagen (Image Source Method, ISM) EXACTO para un recinto rectangular
(shoebox), hasta un orden de reflexion dado, por banda de octava. Calcula cuanta
energia especular reflejada llega al receptor, atribuida a cada una de las 6
paredes, para el mapa de calor de reflexiones (item 1) y como ORACULO ESPECULAR
del futuro motor de ray tracing (parte 2 del plan: R1).

Fisica (Allen & Berkley 1979, *Image method for efficiently simulating
small-room acoustics*, JASA 65(4); Kuttruff, *Room Acoustics*, cap. 4):
  - Para una fuente s en [0,Lx]x[0,Ly]x[0,Lz], las imagenes viven en la red
    espejada. Sobre cada eje las posiciones son X = 2*k*L + (1-2*q)*s con q in
    {0,1}, k in Z. El orden (nº de reflexiones de pared) = suma por eje del nº de
    cruces del segmento desplegado s->X con los planos de pared k*L.
  - Cada cruce en un multiplo PAR de L es la pared en 0 de ese eje; en un multiplo
    IMPAR, la pared en L. Asi se cuenta exactamente cuantas veces rebota en cada
    una de las 6 paredes (x0/xL/y0/yL/z0/zL) -> factor de reflexion (1-alpha) por
    banda y por rebote.
  - Energia relativa en el receptor por banda:
        E = (1/(4*pi*d))^2 * prod_w (1-alpha_w)^{n_w} * exp(-2*alpha_aire*d)
    con d la distancia imagen-receptor (= longitud del camino especular real) y
    alpha_aire por ISO 9613-1 (acoustic_analysis.air_absorption_alpha; el factor
    2 convierte Np/m de presion a energia). Fuente omni, Q=1.

Regimen de validez: GEOMETRICO / especular, valido ARRIBA de Schroeder (el norte
modal del nucleo vale abajo). Shoebox convexo: ISM exacto. Para CAD no convexo
haria falta un test de visibilidad (no implementado aca; es el salto al motor RT).
"""

from __future__ import annotations

import numpy as np

import acoustic_analysis as _aa


# Ids de las 6 paredes del shoebox.
WALLS = ("x0", "xL", "y0", "yL", "z0", "zL")


def octave_bands():
    """Centros de banda de octava estandar (Hz) en el rango de interes."""
    return np.array([31.5, 63.0, 125.0, 250.0, 500.0,
                     1000.0, 2000.0, 4000.0, 8000.0], dtype=float)


def _axis_crossings(s, X, L):
    """Rebotes por pared de UN eje: despliega el segmento de s a X y cuenta los
    planos k*L estrictamente entre ambos. k PAR -> pared en 0; k IMPAR -> pared en
    L. Devuelve (n0, nL). s in (0,L); X la coord de la imagen (puede ser <0 o >L)."""
    lo, hi = (s, X) if s <= X else (X, s)
    k_min = int(np.floor(lo / L)) + 1
    k_max = int(np.ceil(hi / L)) - 1
    n0 = nL = 0
    for k in range(k_min, k_max + 1):
        xk = k * L
        if lo < xk < hi:
            if k % 2 == 0:
                n0 += 1
            else:
                nL += 1
    return n0, nL


def image_sources(src, dims, max_order=3):
    """Lista de imagenes del shoebox hasta `max_order`. Cada una:
      {pos (3,), order, nref {wall: nº de rebotes}}.
    Incluye la directa (order 0) para completitud; el consumidor la filtra si
    quiere solo reflexiones."""
    src = np.asarray(src, dtype=float)
    Lx, Ly, Lz = (float(d) for d in dims)
    sx, sy, sz = src
    out = []
    # Rango de la red que cubre el orden pedido (|2k-q| <= max_order por eje).
    kmax = max_order // 2 + 1
    for qx in (0, 1):
        for nx in range(-kmax, kmax + 1):
            X = 2 * nx * Lx + (1 - 2 * qx) * sx
            nx0, nxL = _axis_crossings(sx, X, Lx)
            ox = nx0 + nxL
            if ox > max_order:
                continue
            for qy in (0, 1):
                for ny in range(-kmax, kmax + 1):
                    Y = 2 * ny * Ly + (1 - 2 * qy) * sy
                    ny0, nyL = _axis_crossings(sy, Y, Ly)
                    oy = ny0 + nyL
                    if ox + oy > max_order:
                        continue
                    for qz in (0, 1):
                        for nz in range(-kmax, kmax + 1):
                            Z = 2 * nz * Lz + (1 - 2 * qz) * sz
                            nz0, nzL = _axis_crossings(sz, Z, Lz)
                            order = ox + oy + nz0 + nzL
                            if order > max_order:
                                continue
                            nref = {"x0": nx0, "xL": nxL, "y0": ny0, "yL": nyL,
                                    "z0": nz0, "zL": nzL}
                            out.append({"pos": np.array([X, Y, Z]),
                                        "order": int(order), "nref": nref})
    # Dedup por posicion (varias combinaciones q/n pueden coincidir en order 0).
    seen = {}
    uniq = []
    for im in out:
        key = tuple(np.round(im["pos"], 6))
        if key in seen:
            continue
        seen[key] = True
        uniq.append(im)
    return uniq


def _alpha_vec(alpha_by_wall, wall, nbands):
    a = alpha_by_wall.get(wall, 0.0)
    a = np.asarray(a, dtype=float)
    if a.ndim == 0:
        a = np.full(nbands, float(a))
    return np.clip(a, 0.0, 0.999)


def wall_reflection_energy(src, receiver, dims, alpha_by_wall, *,
                           bands=None, max_order=3, c=343.0,
                           T=20.0, RH=50.0, P=101325.0, air=True):
    """Energia especular reflejada que llega al receptor, por BANDA y por PARED.

    `alpha_by_wall`: dict {wall: alpha} con alpha escalar o array (nbands,) por
    pared (x0/xL/y0/yL/z0/zL). Devuelve dict:
      {"bands": (B,), "wall_energy": {wall: (B,)}, "total": (B,),
       "order1_points": [(wall, point(3,), energy(B,)), ...]}
    La energia esta en unidades RELATIVAS (Q=1, 1/(4*pi*d))^2). Solo reflexiones
    (order>=1); la directa se excluye del mapa de paredes."""
    bands = octave_bands() if bands is None else np.asarray(bands, float)
    nb = len(bands)
    rec = np.asarray(receiver, dtype=float)
    amap = {w: _alpha_vec(alpha_by_wall, w, nb) for w in WALLS}
    a_air = (_aa.air_absorption_alpha(bands, T=T, RH=RH, P=P)
             if air else np.zeros(nb))

    wall_energy = {w: np.zeros(nb) for w in WALLS}
    total = np.zeros(nb)
    order1 = []
    Lx, Ly, Lz = (float(d) for d in dims)
    for im in image_sources(src, dims, max_order):
        if im["order"] < 1:
            continue
        d = float(np.linalg.norm(im["pos"] - rec))
        if d < 1e-6:
            continue
        spread = (1.0 / (4.0 * np.pi * d)) ** 2
        refl = np.ones(nb)
        for w, n in im["nref"].items():
            if n:
                refl = refl * (1.0 - amap[w]) ** n
        E = spread * refl * np.exp(-2.0 * a_air * d)     # (B,)
        total = total + E
        # Atribuir a cada pared segun los rebotes (bounces de energia).
        for w, n in im["nref"].items():
            if n:
                wall_energy[w] = wall_energy[w] + E * n
        # Punto de reflexion exacto para ORDEN 1 (una sola pared tocada).
        if im["order"] == 1:
            w = next(wk for wk, n in im["nref"].items() if n)
            pt = _reflect_point_order1(im["pos"], rec, w, dims)
            if pt is not None:
                order1.append((w, pt, E))
    return {"bands": bands, "wall_energy": wall_energy, "total": total,
            "order1_points": order1}


def _reflect_point_order1(image_pos, rec, wall, dims):
    """Punto donde el segmento imagen->receptor cruza el plano de la pared `wall`
    (reflexion de 1er orden), clamp al rectangulo de la pared. None si no cruza."""
    Lx, Ly, Lz = (float(d) for d in dims)
    plane = {"x0": (0, 0.0), "xL": (0, Lx), "y0": (1, 0.0), "yL": (1, Ly),
             "z0": (2, 0.0), "zL": (2, Lz)}[wall]
    axis, val = plane
    a = np.asarray(image_pos, float)
    b = np.asarray(rec, float)
    da = b[axis] - a[axis]
    if abs(da) < 1e-12:
        return None
    t = (val - a[axis]) / da
    if not (0.0 <= t <= 1.0):
        return None
    p = a + t * (b - a)
    p[0] = min(max(p[0], 0.0), Lx)
    p[1] = min(max(p[1], 0.0), Ly)
    p[2] = min(max(p[2], 0.0), Lz)
    p[axis] = val
    return p
