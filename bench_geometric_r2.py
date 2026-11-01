"""bench_geometric_r2.py - R2 del motor geometrico: cola difusa por rayos.

Valida el TRAZADO ESTOCASTICO DE RAYOS (`geometric_engine.diffuse_tail`) contra
los resultados analiticos EXACTOS del campo difuso (Kuttruff, Room Acoustics, 5a
ed). No es modelo-vs-modelo: cada oraculo es una ley cerrada.

Oraculos:
  O1  CAMINO LIBRE MEDIO: la media de los trayectos pared-pared converge a
      l = 4V/S  (Kuttruff ec. 5.12), independiente de la absorcion.
  O2  DECAIMIENTO DE EYRING: con absorcion uniforme y SIN aire, la TASA INICIAL
      de decaimiento (EDT, 0..-10 dB del EDC de Schroeder) iguala a Eyring
      T = -24 V ln10 / (c S ln(1-alpha))  (Kuttruff ec. 5.22/5.23). Eyring es la
      tasa de la "particula media" (reemplaza N por su media n*t, ec. 5.22); la
      curva completa de rayos se DESACELERA (las particulas de trayecto largo
      acumulan menos reflexiones y dominan la cola), por eso T30 corre ~10% largo.
      Ese es un efecto fisico del campo real, no un error: se valida la tasa
      inicial, que es la que Eyring predice.
  O3  CONSERVACION DE ENERGIA: con alpha=0 y sin aire, no hay perdida -> la RIR
      energetica es estadisticamente PLANA (no decae).
  O4  LEY DE LAMBERT: las direcciones difusas (ec. 9.21-9.22) siguen la ley del
      coseno -> <cos(theta)> = 2/3, todas en el hemisferio de la normal (D.n>0).
  O5  CONVERGENCIA MONTE CARLO: la dispersion del estimador (camino libre medio)
      cae como 1/sqrt(N) -> al cuadruplicar N la desviacion estandar baja ~2x.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_r2.py
"""
import numpy as np

import geometry
import acoustic_mesh
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def eyring_T(V, S, alpha, c=343.0):
    """Tiempo de reverberacion de Eyring (Kuttruff ec. 5.23)."""
    return 24.0 * V * np.log(10.0) / (c * S * (-np.log(1.0 - alpha)))


def rt_from_w(w, dt, lo=0.0, hi=-10.0):
    """Tiempo de reverberacion del EDC de Schroeder de la RIR energetica w(t):
    integral hacia atras, en dB, ajuste lineal entre lo y hi dB -> T = -60/pend.
    Por default lo=0, hi=-10 -> EDT (tasa de decaimiento INICIAL)."""
    edc = np.cumsum(w[::-1])[::-1]
    edc = edc / max(edc[0], 1e-30)
    L = 10.0 * np.log10(np.maximum(edc, 1e-12))
    t = np.arange(len(L)) * dt
    sel = (L <= lo) & (L >= hi)
    if sel.sum() < 3:
        return float("nan")
    slope = np.polyfit(t[sel], L[sel], 1)[0]
    return -60.0 / slope


# --- shoebox 5x4x3, malla GRUESA (paredes planas -> geometria exacta, rapido) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0)
ext = vmax - vmin
src = ge.GeoSource(pos=vmin + np.array([0.43, 0.57, 0.50]) * ext)
V = ge._tet_volume(nodes, tets)
S = None  # se calcula de la Scene

print("O1: camino libre medio -> 4V/S (Kuttruff 5.12)")
scene = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.12)
S = scene.total_area()
mfp_true = 4.0 * scene.volume / S
r1 = ge.diffuse_tail(scene, src, n_rays=4000, dt=0.005, t_max=0.4,
                     max_refl=60, e_min=1e-12, bands=[1000.0], air=False, seed=1)
mfp = r1["mean_free_path"]
check("O1 <l_libre> = 4V/S (±5%)",
      abs(mfp - mfp_true) / mfp_true < 0.05,
      f"medido={mfp:.4f} m vs 4V/S={mfp_true:.4f} (V={scene.volume:.2f}, S={S:.2f}, "
      f"err {abs(mfp-mfp_true)/mfp_true*100:.2f}%)")

print("O2: decaimiento inicial = Eyring (sin aire) (Kuttruff 5.22/5.23)")
alpha = 0.12
T_ey = eyring_T(scene.volume, S, alpha, c=scene.c)
r2 = ge.diffuse_tail(scene, src, n_rays=6000, dt=0.005, t_max=2.0,
                     max_refl=400, e_min=1e-13, bands=[1000.0], air=False, seed=2)
T_edt = rt_from_w(r2["w"][0], r2["dt"], lo=0.0, hi=-10.0)   # tasa inicial (EDT)
check("O2 EDT(rayos) = Eyring (±5%)",
      np.isfinite(T_edt) and abs(T_edt - T_ey) / T_ey < 0.05,
      f"EDT={T_edt:.3f} s vs Eyring={T_ey:.3f} s "
      f"(err {abs(T_edt-T_ey)/T_ey*100:.2f}%)")

print("O3: conservacion de energia (alpha=0, sin aire) -> RIR plana")
scene0 = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.0)
r3 = ge.diffuse_tail(scene0, src, n_rays=4000, dt=0.005, t_max=0.8,
                     max_refl=400, e_min=1e-13, bands=[1000.0], air=False, seed=3)
w3 = r3["w"][0]
nb = len(w3)
# comparar energia media del primer tercio vs ultimo tercio del tramo util
e_early = w3[nb // 6: nb // 3].mean()
e_late = w3[2 * nb // 3: 5 * nb // 6].mean()
ratio = e_late / max(e_early, 1e-30)
check("O3 RIR plana (energia late/early ~ 1, ±15%)",
      abs(ratio - 1.0) < 0.15,
      f"late/early={ratio:.3f}")

print("O4: ley de Lambert (ec. 9.21-9.22) -> <cos>=2/3, hemisferio")
rng = np.random.default_rng(0)
n = np.tile(np.array([0.0, 0.0, 1.0]), (200000, 1))
D = ge._lambert_dirs(n, rng)
costh = D[:, 2]
in_hemi = np.all(costh > 0)
unit = np.allclose(np.linalg.norm(D, axis=1), 1.0, atol=1e-9)
mean_cos = costh.mean()
check("O4 Lambert: todas en el hemisferio, unitarias, <cos>=2/3 (±1%)",
      in_hemi and unit and abs(mean_cos - 2.0 / 3.0) < 0.01,
      f"<cos>={mean_cos:.4f} (2/3={2/3:.4f}), hemi={in_hemi}, unit={unit}")

print("O5: convergencia Monte Carlo (sigma ~ 1/sqrt(N))")


def mfp_runs(N, seeds):
    out = []
    for sd in seeds:
        rr = ge.diffuse_tail(scene, src, n_rays=N, dt=0.005, t_max=0.3,
                             max_refl=40, e_min=1e-12, bands=[1000.0],
                             air=False, seed=sd)
        out.append(rr["mean_free_path"])
    return np.array(out)


seeds = [10, 11, 12, 13, 14, 15]
s_lo = mfp_runs(400, seeds).std()
s_hi = mfp_runs(1600, seeds).std()   # 4x N -> sigma deberia bajar ~2x
ratio_mc = s_lo / max(s_hi, 1e-9)
check("O5 sigma(N) / sigma(4N) ~ 2 (1/sqrt(N), banda [1.4,3.0])",
      1.4 < ratio_mc < 3.0,
      f"sigma(400)={s_lo:.4f}, sigma(1600)={s_hi:.4f}, ratio={ratio_mc:.2f}")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
