# -*- coding: utf-8 -*-
"""Mueve el EDT de FLAIR hacia el medido el TEMPRANO ESPECULAR? Reusa la cola por
banda; por mic agrega directo + reflexiones por imagenes (orden 2) en [0,t_mix],
crossfade a la cola. Compara EDT: medido vs compuesta(solo directo) vs
compuesta+especular. Subset de mics, bandas 500 y 2000."""
import numpy as np
import rir, acoustic_analysis as aa
import reflections_ism as _ism
from flair_geometry import reconstruct_room
from acoustic_mesh import build_volume_mesh
import geometric_engine as ge
from scipy.io import loadmat
from scipy.optimize import brentq

m = loadmat("datasets/flair/data_FLAIR.mat", squeeze_me=True)
pts, nrm = m["boundary_points"].T, m["boundary_normals"].T
mic, spk = m["mic_positions"].T, m["spkr_positions"].T
c, fs = float(m["c"]), int(m["fs"]); rirs = m["rirs"]; SRC = 0
r = reconstruct_room(pts, nrm, mic[len(mic)//2], positions=[mic, spk], hv=0.04, seal="auto")
mic_al, spk_al = r["positions_aligned"]
nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=2.5)
scat = ge.default_scattering(_ism.octave_bands())
scn0 = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1, c=c); V = float(scn0.volume)
src = ge.GeoSource(pos=np.asarray(spk_al[SRC], float))

def edt(t, L): return rir._fit_rt(t, L, -10.0, 0.0)[0]
def edt_g(g, kd, dt):
    edc = np.cumsum(g[kd:][::-1])[::-1]; edc /= max(edc[0],1e-30)
    L = 10*np.log10(np.maximum(edc,1e-12)); return edt(np.arange(len(L))*dt, L)
def meas_edt(ir, fs):
    t, L = rir.schroeder_curve(ir, fs); return edt(t, L)

scn_p = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.2, scatter=scat, c=c, T=20, RH=50)
mfp = ge.diffuse_tail(scn_p, src, n_rays=6000, dt=0.002, t_max=0.6, max_refl=300,
                      e_min=1e-9, bands=[500.0], air=True, seed=5)["mean_free_path"]
S_eff = 4*V/mfp
mb500 = 2*float(aa.air_absorption_alpha(500.0, T=20, RH=50))
def eyring_air(a, mb): A=-S_eff*np.log(1-a); return 24*np.log(10)*V/(c*(A+4*mb*V))
vals=[meas_edt(rir.band_filter(rirs[:,j,SRC], fs, 500.0), fs) for j in range(rirs.shape[1])]
vals=[x for x in vals if np.isfinite(x)]
a_wall = brentq(lambda a: eyring_air(a, mb500)-np.median(vals), 1e-3, 0.95)
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=a_wall, scatter=scat, c=c, T=20, RH=50)
t_mix = ge.mixing_time(V, c=c)
print(f"S_eff={S_eff:.1f} a_wall={a_wall:.3f} t_mix={t_mix*1e3:.1f}ms")

dt=0.001; t_max=1.0; sub=np.linspace(0, rirs.shape[1]-1, 8).astype(int)
print(f"{'band':>5} {'EDT_meas':>9} {'EDT_dir':>9} {'EDT_spec':>9}")
for b in (500.0, 2000.0):
    em=[meas_edt(rir.band_filter(rirs[:,j,SRC], fs, b), fs) for j in range(rirs.shape[1])]
    em=[x for x in em if np.isfinite(x)]
    tl=ge.diffuse_tail(scn, src, n_rays=9000, dt=dt, t_max=t_max, max_refl=1000,
                       e_min=1e-12, bands=[b], air=True, seed=5)
    w=tl["w"][0]; n_bins=len(w); s=src.q/(np.pi*S_eff); g_tail=s*w; bi=int(np.argmin(np.abs(scn.bands-b)))
    hi=min(int(t_mix/dt), n_bins)
    ed_dir, ed_spec=[],[]
    for j in sub:
        rec=ge.GeoReceiver(pos=np.asarray(mic_al[j],float))
        rr=float(np.linalg.norm(mic_al[j]-src.pos)); kd=int(rr/c/dt)
        mba=2*float(aa.air_absorption_alpha(b,T=20,RH=50))
        e_dir=(src.q/(4*np.pi*rr))**2*np.exp(-mba*rr)
        g=g_tail.copy();
        if kd<n_bins: g[kd]+=e_dir
        ed_dir.append(edt_g(g, kd, dt))
        # + especular orden 2
        er=ge.early_reflections(scn, src, rec, max_order=2)
        g2=g_tail.copy();
        if kd<n_bins: g2[kd]+=er["direct"]["energy"][bi]
        gsp=np.zeros(n_bins)
        for p in er["paths"]:
            k=int(p["r"]/c/dt)
            if kd<k<hi: gsp[k]+=float(p["energy"][bi])
        if hi>kd+1:
            a=np.linspace(0,1,hi-kd-1); g2[kd+1:hi]=(1-a)*gsp[kd+1:hi]+a*g_tail[kd+1:hi]
        ed_spec.append(edt_g(g2, kd, dt))
    print(f"{b:5.0f} {np.median(em):9.3f} {np.median(ed_dir):9.3f} {np.median(ed_spec):9.3f}")
