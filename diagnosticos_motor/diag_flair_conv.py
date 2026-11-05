"""FLAIR real: el +10% del EDT del tail, es convergencia de la medicion o
fisica de geometria irregular? Compara ray EDT (ajustes del gate vs convergidos)
contra Eyring con la alpha/S_eff calibradas del gate."""
import numpy as np
import rir, acoustic_analysis as aa
import reflections_ism as _ism
from flair_geometry import reconstruct_room
from acoustic_mesh import build_volume_mesh
import geometric_engine as ge
from scipy.io import loadmat

m = loadmat("datasets/flair/data_FLAIR.mat", squeeze_me=True)
pts, nrm = m["boundary_points"].T, m["boundary_normals"].T
mic, spk = m["mic_positions"].T, m["spkr_positions"].T
c = float(m["c"])

r = reconstruct_room(pts, nrm, mic[len(mic)//2], positions=[mic, spk],
                     hv=0.04, seal="auto")
mic_al, spk_al = r["positions_aligned"]
nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=2.5)
scat = ge.default_scattering(_ism.octave_bands())
V = float(ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1, c=c).volume)
src = ge.GeoSource(pos=np.asarray(spk_al[0], float))
a_wall = 0.240; S_eff = 131.8        # del gate (calibrado a 500 Hz)
print(f"FLAIR V={V:.1f} S_eff={S_eff} a_wall={a_wall} c={c:.1f}")

def eyring_air(a, m_b):
    A = -S_eff * np.log(1.0 - a)
    return 24.0 * np.log(10.0) * V / (c * (A + 4.0 * m_b * V))

def ray_edt(scn, fc, n_rays, t_max, dt, e_min, max_refl):
    rr = ge.diffuse_tail(scn, src, n_rays=n_rays, dt=dt, t_max=t_max,
                         max_refl=max_refl, e_min=e_min, bands=[fc],
                         air=True, seed=5)
    w = rr["w"][0]
    edc = np.cumsum(w[::-1])[::-1] / max(w.sum(), 1e-30)
    L = 10.0 * np.log10(np.maximum(edc, 1e-30))
    edt, r2 = rir._fit_rt(rr["t"], L, -10.0, 0.0)
    t30, _ = rir._fit_rt(rr["t"], L, -35.0, -5.0)
    return edt, t30, r2

scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=a_wall, scatter=scat, c=c,
                             T=20.0, RH=50.0)
print(f"{'fc':>6} {'m_b':>7} {'Eyr':>6} | {'set':>8} {'EDT':>6} {'/Ey':>6} "
      f"{'T30':>6} {'/Ey':>6} {'r2':>5}")
for fc in (500.0, 1000.0, 2000.0):
    m_b = 2.0 * float(aa.air_absorption_alpha(fc, T=20.0, RH=50.0))
    Tey = eyring_air(a_wall, m_b)
    for tag, kw in (("gate", dict(n_rays=6000, t_max=0.8, dt=0.002, e_min=1e-9, max_refl=300)),
                    ("conv", dict(n_rays=24000, t_max=2.0, dt=0.002, e_min=1e-14, max_refl=1500))):
        edt, t30, r2 = ray_edt(scn, fc, **kw)
        print(f"{fc:6.0f} {m_b*1e3:6.2f}m {Tey:6.3f} | {tag:>8} {edt:6.3f} "
              f"{edt/Tey:6.3f} {t30:6.3f} {t30/Tey:6.3f} {r2:5.2f}")
