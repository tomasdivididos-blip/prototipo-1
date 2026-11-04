"""bench_geometric_r6.py - R6: respuesta de ENERGIA compuesta (directo + cola
difusa) con la NORMALIZACION DEL DETECTOR analitica y parametros ISO 3382-1.

Valida `geometric_engine.composed_energy_response`. La escala absoluta de la cola
es ANALITICA (g_tail = q/(pi S) w), no ajustada; sale de la irradiancia difusa
I=c w/4 (Kuttruff 9.8) + la energia radiada de la fuente puntual. Oraculos:

  O1  CONSERVACION DE LA COLA: sum(w)=q/alpha EXACTO (toda la energia se absorbe,
      alpha cte) -> base de la densidad w_dens=4 w/(c S dt). Kuttruff 9.8.
  O2  DENSIDAD DIFUSA: w_dens=4 w/(c S dt) extrapola a q/V con tau=4V/(cA) Eyring
      (ley cerrada, el ancla absoluta de la escala). Kuttruff 5.1.
  O3  DISTANCIA CRITICA: con la normalizacion analitica, el radio donde el directo
      iguala a la reverberante sale r_c = r_rec sqrt(e_dir/E_rev) = sqrt(S alpha/16pi),
      IGUAL para todos los receptores (q y r se cancelan). Kuttruff ec. 4.9; Kinsler.
  O4  CLARIDAD vs DISTANCIA: C80 y D50 DECRECEN al alejar el receptor (el directo
      cae 1/r^2, la reverberante no). ISO 3382-1 (C80, D50).
  O5  DECAIMIENTO COMPUESTO: el EDT iguala a Eyring dentro de la curvatura conocida
      del campo real (bench_geometric_r2 O2).

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_r6.py
"""
import numpy as np

import geometry
import acoustic_mesh
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# --- shoebox liso 5x4x3, alpha uniforme, aire OFF (r_c limpio) ---
Lx, Ly, Lz = 5.0, 4.0, 3.0
ALPHA = 0.15
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=ALPHA)
V = scn.volume; S = scn.total_area(); c = scn.c
A_ey = -S * np.log(1.0 - ALPHA)                 # area de absorcion Eyring
rc_th = np.sqrt(S * ALPHA / (16.0 * np.pi))     # distancia critica clasica
src = ge.GeoSource(pos=vmin + np.array([0.25, 0.35, 0.50]) * ext)
FC = 1000.0
print(f"shoebox V={V:.1f} S={S:.1f} A_ey={A_ey:.2f} r_c_teorico=sqrt(Sa/16pi)={rc_th:.3f} m")

# receptores a distancias crecientes del source
recs = [ge.GeoReceiver(pos=vmin + np.array([fx, 0.35, 0.50]) * ext)
        for fx in (0.33, 0.50, 0.70, 0.90)]

res = []
for rec in recs:
    r = ge.composed_energy_response(scn, src, rec, fc=FC, n_rays=9000, dt=0.001,
                                    max_refl=1500, air=False, seed=7)
    r_rec = float(np.linalg.norm(rec.pos - src.pos))
    e_dir = float(r["g_direct"][r["kd"]])
    E_rev = float(r["g_tail"].sum())
    r_c = r_rec * np.sqrt(e_dir / E_rev) if E_rev > 0 else np.nan
    res.append(dict(r_rec=r_rec, s=r["scale"], r_c=r_c, C80=r["C80"],
                    D50=r["D50"], EDT=r["EDT"], tail=r["g_tail"], t=r["t"]))
    print(f"  r={r_rec:4.2f}m  s={r['scale']:.4e}  r_c={r_c:.3f}m  "
          f"C80={r['C80']:5.2f}dB  D50={r['D50']:.3f}  EDT={r['EDT']:.3f}s")

# O1 conservacion de la cola
tl = ge.diffuse_tail(scn, src, n_rays=9000, dt=0.002, t_max=1.0, max_refl=1500,
                     e_min=1e-14, bands=[FC], air=False, seed=7)
w = tl["w"][0]; sum_w = w.sum()
print("O1: conservacion de la cola  sum(w)=q/alpha")
check("O1 sum(w)=q/alpha (exacto, <1%)",
      abs(sum_w - src.q / ALPHA) / (src.q / ALPHA) < 0.01,
      f"sum(w)={sum_w:.4f} vs q/alpha={src.q/ALPHA:.4f}")

# O2 densidad difusa extrapola a q/V (ancla absoluta)
print("O2: densidad difusa w_dens=4w/(cS dt) -> (q/V) e^{-t/tau}")
dt2 = 0.002
w_dens = 4.0 * w / (c * S * dt2)
tcw = tl["t"]; t_mix = ge.mixing_time(V, c=c)
sel = (tcw >= t_mix) & (w_dens > w_dens.max() * 1e-3)
A = np.polyfit(tcw[sel], np.log(np.maximum(w_dens[sel], 1e-30)), 1)
w0_ext = np.exp(A[1]); tau_fit = -1.0 / A[0]
tau_ey = 4.0 * V / (c * A_ey)
check("O2 w_dens(0)_ext = q/V (±8%) y tau ~ Eyring",
      abs(w0_ext - src.q / V) / (src.q / V) < 0.08 and 0.95 <= tau_fit / tau_ey <= 1.15,
      f"w_dens0={w0_ext:.5f} q/V={src.q/V:.5f} ratio={w0_ext/(src.q/V):.3f} | "
      f"tau_fit={tau_fit*1e3:.1f}ms /ey={tau_fit/tau_ey:.3f}")

# O3 distancia critica = sqrt(Sa/16pi), igual para todos los receptores
print("O3: distancia critica r_c = sqrt(S alpha/16pi), invariante en r")
rcs = np.array([x["r_c"] for x in res])
rc_med = float(np.median(rcs)); cv = float(rcs.std() / rcs.mean())
check("O3 r_c = sqrt(Sa/16pi) (±8%) e invariante (CV<5%)",
      abs(rc_med - rc_th) / rc_th < 0.08 and cv < 0.05,
      f"r_c={np.array2string(rcs, precision=3)} med={rc_med:.3f} vs {rc_th:.3f} "
      f"(err {abs(rc_med-rc_th)/rc_th*100:.1f}%, CV {cv*100:.1f}%)")

# O4 claridad vs distancia (monotonia)
print("O4: C80 y D50 decrecen con la distancia")
C = np.array([x["C80"] for x in res]); D = np.array([x["D50"] for x in res])
mono = np.all(np.diff(C) < 1e-6) and np.all(np.diff(D) < 1e-6)
check("O4 C80 y D50 monotonos decrecientes con r",
      mono, f"C80={np.array2string(C, precision=2)} D50={np.array2string(D, precision=3)}")

# O5 EDT compuesto vs Eyring
print("O5: EDT compuesto = Eyring (dentro de la curvatura conocida)")
T_ey = 24.0 * np.log(10.0) * V / (c * A_ey)
EDT_m = float(np.median([x["EDT"] for x in res]))
check("O5 EDT(compuesto)/Eyring en [0.95, 1.15]",
      0.95 <= EDT_m / T_ey <= 1.15,
      f"EDT={EDT_m:.3f}s Eyring={T_ey:.3f}s ratio={EDT_m/T_ey:.3f}")

n_ok = sum(1 for _n, cnd in results if cnd)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
