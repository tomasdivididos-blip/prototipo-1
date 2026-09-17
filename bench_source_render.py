"""
bench_source_render.py
======================

Oraculos del toggle Bafle/Esfera + punto acustico en la cara delantera
(17 Sep 2026, pedido del usuario). Falsable, autocontenido, headless.

  1. El PUNTO ACUSTICO (`position`) queda en el CENTRO DE LA CARA DELANTERA del
     bafle; la caja se extiende hacia ATRAS (antes se centraba en el punto -> los
     bafles se solapaban). => nada de la caja sobresale por delante del punto.
  2. render_aabb / limit_aabb segun el modo:
       - baffle: limite = prisma (caras); esfera: limite = CENTRO (degenerado).
  3. sphere_radius = 1/2 del lado menor del bafle.
  4. La ACUSTICA no cambia: coupling_points de un monopolo sigue en `position`.
  5. render_kind sobrevive la construccion (normalizado) y un valor basura cae a
     "baffle".

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_source_render.py
"""

from __future__ import annotations

import numpy as np

from sources import OmniSource, normalize_render_kind

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def main():
    print("=" * 64)
    print("bench_source_render  (bafle/esfera + punto en la cara delantera)")
    print("=" * 64)

    pos = np.array([2.0, 1.0, 1.2])
    size = (0.30, 0.50, 0.40)          # An, Al, Pr  (d = 0.40)
    d = size[2]

    # --- 1. punto en la cara delantera; caja hacia atras -------------------------
    s = OmniSource(tuple(pos), baffle_size=size, orientation=90.0, render_kind="baffle")
    n, ey, ez = s.baffle_axes()
    box_c, n2, _ey, _ez, (hx, hy, hz) = s.baffle_frame()
    # la cara delantera pasa por el punto: la proyeccion MAX de la caja sobre n = pos.n
    amin, amax = s._baffle_aabb()
    corners = np.array([box_c + a * hx * n + b * hy * ey + e * hz * ez
                        for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)])
    proj = corners @ n
    check("el punto queda en la cara delantera (nada de la caja lo pasa por delante)",
          abs(proj.max() - float(pos @ n)) < 1e-9,
          f"max proj={proj.max():.4f} pos.n={float(pos@n):.4f}")
    check("la caja se extiende hacia ATRAS media profundidad + media (d completa)",
          abs((proj.max() - proj.min()) - d) < 1e-9,
          f"span={proj.max()-proj.min():.3f} d={d}")
    check("el centro del prisma esta a d/2 detras del punto",
          np.allclose(box_c, pos - 0.5 * d * n),
          f"box_c={np.round(box_c,3)}")

    # --- 2. limit_aabb: baffle = prisma, sphere = centro (degenerado) ------------
    lmin, lmax = s.limit_aabb()
    check("baffle: limit_aabb = prisma (no degenerado)",
          np.all(lmax - lmin > 1e-6) and np.allclose(lmin, amin),
          f"span={np.round(lmax-lmin,3)}")
    ssph = OmniSource(tuple(pos), baffle_size=size, render_kind="sphere")
    smin, smax = ssph.limit_aabb()
    check("sphere: limit_aabb DEGENERADO en el punto (limite = centro)",
          np.allclose(smin, pos) and np.allclose(smax, pos),
          f"min={np.round(smin,3)} max={np.round(smax,3)}")
    rmin, rmax = ssph.render_aabb()
    r = 0.5 * min(size)
    check("sphere: render_aabb = cubo de la esfera (radio 1/2 lado menor)",
          np.allclose(rmin, pos - r) and np.allclose(rmax, pos + r),
          f"r={r}")

    # --- 3. radio de la esfera ---------------------------------------------------
    check("sphere_radius = 1/2 del lado menor del bafle",
          abs(ssph.sphere_radius() - r) < 1e-12, f"{ssph.sphere_radius():.3f} vs {r:.3f}")

    # --- 4. la ACUSTICA no cambia: monopolo sigue en `position` ------------------
    cps = s.coupling_points()
    check("coupling_points de un monopolo sigue EXACTO en position (sin cambio fisico)",
          len(cps) == 1 and np.allclose(cps[0][0], pos) and cps[0][1] == 1.0,
          f"{[(np.round(p,3).tolist(), w) for p, w in cps]}")

    # --- 5. normalizacion de render_kind ----------------------------------------
    check("render_kind normaliza valores validos", normalize_render_kind("SPHERE") == "sphere")
    check("render_kind basura cae a 'baffle'", normalize_render_kind("xxx") == "baffle")
    check("construir con basura -> baffle",
          OmniSource((0, 0, 0), render_kind="zzz").render_kind == "baffle")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return _N_FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
