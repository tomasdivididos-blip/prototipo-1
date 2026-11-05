"""Keystone de la continuidad: validar la conversion flujo-de-pared -> densidad
de energia del tail contra leyes CERRADAS (no circular).
 (a) conservacion: sum(w) = q/alpha  (toda la energia se absorbe, alpha cte).
 (b) densidad w_dens(t)=4 w(t)/(c S dt) ~ (q/V) e^{-t/tau}, tau=4V/(cA_eyring).
Shoebox liso, aire OFF, alpha uniforme."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
src = ge.GeoSource(pos=vmin + np.array([0.43, 0.57, 0.5]) * ext)
print("q =", src.q)

for alpha in (0.1, 0.2, 0.3):
    sc = ge.Scene.from_tet_mesh(nodes, tets, alpha=alpha)
    V = sc.volume; S = sc.total_area(); c = sc.c
    A = -S * np.log(1.0 - alpha)                  # area de absorcion Eyring
    tau = 4.0 * V / (c * A)
    dt = 0.002
    r = ge.diffuse_tail(sc, src, n_rays=30000, dt=dt, t_max=2.5, max_refl=2000,
                        e_min=1e-16, bands=[1000.0], air=False, seed=11)
    w = r["w"][0]
    q = src.q
    # (a) conservacion
    sum_w = w.sum(); pred = q / alpha
    # (b) densidad: w_dens = 4 w /(c S dt). Ajuste exponencial en 0..-20 dB.
    w_dens = 4.0 * w / (c * S * dt)
    tc = r["t"]
    # valor inicial: promedio de los primeros bins utiles (tras el 1er arribo)
    k0 = int(np.argmax(w))
    w0_meas = w_dens[k0]
    w0_pred = q / V
    # tau medido del EDC (pendiente -5..-25 dB)
    edc = np.cumsum(w[::-1])[::-1]; edc /= edc[0]
    L = 10.0 * np.log10(np.maximum(edc, 1e-12))
    sel = (L <= -5) & (L >= -25)
    slope = np.polyfit(tc[sel], L[sel], 1)[0]
    tau_meas = -10.0 / np.log(10.0) / slope       # L=10log10 e^{-t/tau}=-(10/ln10)t/tau
    print(f"alpha={alpha:.2f} V={V:.1f} S={S:.1f} A={A:.2f} tau_ey={tau*1e3:.1f}ms")
    print(f"  (a) sum(w)={sum_w:.4f}  q/alpha={pred:.4f}  ratio={sum_w/pred:.4f}")
    print(f"  (b) w_dens0={w0_meas:.4f}  q/V={w0_pred:.4f}  ratio={w0_meas/w0_pred:.3f}"
          f" | tau_edc={tau_meas*1e3:.1f}ms /ey={tau_meas/tau:.3f}")
