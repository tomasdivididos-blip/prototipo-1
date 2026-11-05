"""Smoke: import del core + camino early_specular=True (coloracion) sin romper."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

v, t, *_ = geometry.make_room(5.0, 4.0, 3.0, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.15)
src = ge.GeoSource(pos=vmin + np.array([0.25, 0.35, 0.5]) * ext)
rec = ge.GeoReceiver(pos=vmin + np.array([0.6, 0.35, 0.5]) * ext)
for es in (False, True):
    r = ge.composed_energy_response(scn, src, rec, fc=1000.0, n_rays=2000,
                                    dt=0.002, t_max=0.6, max_refl=200,
                                    air=False, seed=3, early_specular=es)
    ok = np.isfinite(r["C80"]) and np.isfinite(r["EDT"]) and r["g"].sum() > 0
    print(f"early_specular={es}: C80={r['C80']:.2f} D50={r['D50']:.3f} "
          f"EDT={r['EDT']:.3f} scale={r['scale']:.3e} ok={ok}")
print("SMOKE OK")
