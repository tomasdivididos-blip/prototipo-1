"""Bench F6: gate por ξ de 1er orden + Beyn TILEADO (elipse ancha-Re / angosta-Im)
para el caso CASI-CRÍTICO con fallback modal subestimado.

El bug (v2.61, hallado en test visual): un modo casi-crítico de pared trasera
MATCHEADA (β=1) cuyo ξ del FALLBACK modal cae por debajo de `xi_crit` NO se
mandaba a Beyn (el gate miraba ξ_fallback), así que el sparse devolvía el fallback
SUBESTIMADO (p.ej. ξ≈0.34 en vez de 1.3). Además el contorno Beyn circular único
grande SATURA el SVD (k=ell) en f media-alta (densidad modal ∝ f²).

El fix (v2.62): (1) gate por ξ_est=(c|β|/2)diag(G)/ωₙ (perturbación de 1er orden,
monótona y cota INFERIOR del ξ real → el casi-crítico siempre queda flaggeado);
(2) Beyn TILEADO con ELIPSE por cluster, ancha en Re (alcanza el polo amortiguado
a −ξωₙ) y angosta en Im (no encierra ~f² modos); (3) only_if_larger: Beyn solo
pisa el fallback si AUMENTA ξ (no daña modos bien estimados).

  T1  el modo casi-crítico (ξ_nod>0.5) se recupera EXACTO (<5%) vs nodal, aunque
      su ξ de fallback modal esté por debajo de xi_crit (el gate viejo lo perdía).
  T2  NINGÚN modo queda PEOR que el fallback modal (only_if_larger no regresiona).
  T3  cobertura total 100% y tiempo acotado.

Correr:  QT_QPA_PLATFORM=offscreen python bench_qep_sparse_f6.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import numpy as np

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

# Ducto largo: el eje X matcheado hace al axial fundamental CASI-CRÍTICO (ξ>1),
# con su ξ de fallback modal MUY por debajo (el modal trunca el acople).
Lx, Ly, Lz = 7.0, 2.1, 2.3
vr, tr, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat", subdiv_levels=0)
nodes, tets = build_volume_mesh(vr, tr, n_per_meter=2.3)
N = nodes.shape[0]
K, M, _v = build_KM(nodes, tets)
freqs, phis = solve_modes(K, M, n_modes=26)
C_rear, nf = fm.rear_wall_surface_mass(nodes, tets, axis=0)
print(f"  ducto {Lx}x{Ly}x{Lz}  N={N}, {len(freqs)} modos, pared {nf} caras")

# oráculo nodal denso
xi_nod, f_nod = fm.qep_boundary_nodal(K, M, C_rear, freqs, phis, beta=1.0, c=C0,
                                      max_dense=5000)
# fallback modal (proyección de Galerkin) == lo que el wiring pasa como fallback
G = phis.T @ (C_rear @ phis)
xi_mod, f_mod = fm.qep_boundary_xi_shift(freqs, G, beta=1.0, c=C0)

t0 = time.time()
xi_sp, f_sp, info = qs.sparse_boundary_xi_shift(
    K, M, C_rear, freqs, phis, beta=1.0, c=C0,
    fallback_xi=xi_mod, fallback_f=f_mod, return_info=True)
dt = time.time() - t0

nc = np.where(xi_nod > 0.5)[0]
print(f"  modos casi-críticos (ξ_nod>0.5): {list(nc)}")
for n in nc:
    print(f"    modo {n} f={freqs[n]:.1f}: nodal={xi_nod[n]:.3f} "
          f"fallback={xi_mod[n]:.3f} (xi_crit={0.35}) sparse={xi_sp[n]:.3f}")
print(f"  cobertura total={100*info['cov_total']:.0f}%  {dt:.1f}s")
print()

# ---------------------------------------------------------------------------
print("T1  el casi-crítico se recupera exacto (el gate viejo por ξ_fallback lo perdía)")
nc_ok = bool(nc.size) and all(
    abs(xi_sp[n] - xi_nod[n]) / max(xi_nod[n], 1e-9) < 0.05 for n in nc)
# y el fallback de al menos uno estaba por DEBAJO de xi_crit (reproduce el bug)
gated_out = any(xi_mod[n] < 0.35 for n in nc)
check("T1a el modo casi-crítico == nodal (<5%)", nc_ok,
      f"sparse={np.round(xi_sp[nc],3)} vs nodal={np.round(xi_nod[nc],3)}")
check("T1b su ξ de fallback caía por debajo de xi_crit (el bug original)", gated_out,
      f"ξ_fallback={np.round(xi_mod[nc],3)} < 0.35")
print()

# ---------------------------------------------------------------------------
print("T2  only_if_larger: ningún modo queda PEOR que el fallback modal")
# Para cada modo cubierto, el error del sparse no supera al del fallback por más de
# una tolerancia (el sparse no introduce regresiones respecto del fallback).
cov = np.isfinite(xi_sp) & np.isfinite(xi_mod)
err_sp = np.abs(xi_sp[cov] - xi_nod[cov])
err_fb = np.abs(xi_mod[cov] - xi_nod[cov])
worse = np.where(err_sp > err_fb + 0.02)[0]
check("T2 sparse no es peor que el fallback en ningún modo", worse.size == 0,
      f"{worse.size} modos peores" if worse.size else "ninguno peor")
print()

# ---------------------------------------------------------------------------
print("T3  cobertura y tiempo")
check("T3a cobertura total 100%", info["cov_total"] >= 0.999,
      f"{100*info['cov_total']:.0f}%")
check("T3b tiempo acotado (<15 s en esta malla)", dt < 15.0, f"{dt:.1f}s")
print()

print("=" * 70)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 70)
raise SystemExit(1 if _FAIL else 0)
