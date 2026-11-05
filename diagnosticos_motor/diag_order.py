"""Separar las dos causas del fallo de r_c: (1) E_rev debe ser total-menos-directo
(las reflexiones tempranas tambien son reverberantes), (2) el pin de s se trunca
con max_order bajo. Reusa UNA cola; varia receptor y max_order."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

Lx, Ly, Lz = 5.0, 4.0, 3.0; ALPHA = 0.15; FC = 1000.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=ALPHA)
V = scn.volume; S = scn.total_area(); c = scn.c
A_ey = -S * np.log(1 - ALPHA); rc_ey = np.sqrt(A_ey / (16 * np.pi))
src = ge.GeoSource(pos=vmin + np.array([0.25, 0.35, 0.5]) * ext)
print(f"V={V:.1f} S={S:.1f} r_c(Eyring)={rc_ey:.3f} m")

dt = 0.001; t_max = 1.0
tl = ge.diffuse_tail(scn, src, n_rays=12000, dt=dt, t_max=t_max, max_refl=1500,
                     e_min=1e-13, bands=[FC], air=False, seed=7)
w = tl["w"][0]; n_bins = len(w)
t_mix = ge.mixing_time(V, c=c)
lo = int(t_mix * 0.4 / dt); hi = int(t_mix * 1.6 / dt)
print(f"t_mix={t_mix*1e3:.1f}ms  ventana [{lo*dt*1e3:.1f},{hi*dt*1e3:.1f}]ms")

for fx in (0.50, 0.70, 0.90):
    rec = ge.GeoReceiver(pos=vmin + np.array([fx, 0.35, 0.5]) * ext)
    r_rec = np.linalg.norm(rec.pos - src.pos)
    for mo in (3, 5, 7):
        er = ge.early_reflections(scn, src, rec, max_order=mo)
        g_e = np.zeros(n_bins)
        kd = int(er["direct"]["r"] / c / dt); g_e[kd] += er["direct"]["energy"][-1]
        for p in er["paths"]:
            k = int(p["r"] / c / dt)
            if k < n_bins: g_e[k] += p["energy"][-1]
        s = g_e[lo:hi].sum() / max(w[lo:hi].sum(), 1e-30)
        g = g_e.copy(); g[hi:] = s * w[hi:]
        a = np.linspace(0, 1, hi - lo); g[lo:hi] = (1 - a) * g_e[lo:hi] + a * s * w[lo:hi]
        e_dir = g[kd]
        E_tail = (s * w).sum()
        E_nondir = g[kd + 1:].sum()
        rc_tail = r_rec * np.sqrt(e_dir / E_tail)
        rc_nd = r_rec * np.sqrt(e_dir / E_nondir)
        print(f" r={r_rec:4.2f} mo={mo}  s={s:.3e}  rc(tail)={rc_tail:.3f} "
              f"rc(total-dir)={rc_nd:.3f}  (Ey={rc_ey:.3f})")
