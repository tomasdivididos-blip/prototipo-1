"""Confirmar w_dens=4w/(cS dt)=(q/V)e^{-t/tau} en la REGION DIFUSA (t>=t_mix),
no en el pico de buildup. Ajuste exponencial extrapolado a t=0."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
src = ge.GeoSource(pos=vmin + np.array([0.43, 0.57, 0.5]) * ext)
alpha = 0.20
sc = ge.Scene.from_tet_mesh(nodes, tets, alpha=alpha)
V = sc.volume; S = sc.total_area(); c = sc.c
dt = 0.001
r = ge.diffuse_tail(sc, src, n_rays=12000, dt=dt, t_max=1.0, max_refl=800,
                    e_min=1e-15, bands=[1000.0], air=False, seed=11)
w = r["w"][0]; tc = r["t"]
w_dens = 4.0 * w / (c * S * dt)
t_mix = ge.mixing_time(V, c=c)
print(f"V={V:.1f} S={S:.1f} q/V={src.q/V:.5f} t_mix={t_mix*1e3:.1f}ms")
# ventana difusa: desde t_mix hasta donde w_dens cae 3 decadas del pico
pk = w_dens.max()
sel = (tc >= t_mix) & (w_dens > pk * 1e-3)
lw = np.log(np.maximum(w_dens[sel], 1e-30))
A = np.polyfit(tc[sel], lw, 1)
w0_ext = np.exp(A[1]); tau_fit = -1.0 / A[0]
print(f"ajuste difuso: w_dens(0)_ext={w0_ext:.5f}  q/V={src.q/V:.5f}  "
      f"ratio={w0_ext/(src.q/V):.3f} | tau_fit={tau_fit*1e3:.1f}ms "
      f"tau_ey={4*V/(c*(-S*np.log(1-alpha)))*1e3:.1f}ms")
# muestras puntuales en la region difusa vs (q/V)e^{-t/tau_fit}
for frac in (1.0, 1.5, 2.0, 3.0):
    tt = frac * t_mix
    k = int(tt / dt)
    if k < len(w_dens):
        pred = w0_ext * np.exp(-tt / tau_fit)
        print(f"  t={tt*1e3:5.1f}ms w_dens={w_dens[k]:.5f} fit={pred:.5f} "
              f"ratio={w_dens[k]/pred:.3f}")
