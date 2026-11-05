# -*- coding: utf-8 -*-
"""Cross-check en FLAIR de la respuesta compuesta R6 (directo + cola, escala
analitica del detector) vs MEDIDO (135 mics) vs cola-sola. Objetivo: ver si el
EDT de respuesta completa baja el +10% de la cola-sola hacia el medido, y cruzar
C80/D50 por banda (ahora con escala absoluta)."""
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
c, fs = float(m["c"]), int(m["fs"]); rirs = m["rirs"]; SRC = 0

r = reconstruct_room(pts, nrm, mic[len(mic)//2], positions=[mic, spk],
                     hv=0.04, seal="auto")
mic_al, spk_al = r["positions_aligned"]
nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=2.5)
scat = ge.default_scattering(_ism.octave_bands())
V = float(ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1, c=c).volume)
src = ge.GeoSource(pos=np.asarray(spk_al[SRC], float))

def edt_from_edc(t, L):      # 0..-10 dB
    return rir._fit_rt(t, L, -10.0, 0.0)[0]

def params_from_energy(g, t, kd, dt):
    e_tot = g[kd:].sum()
    if e_tot <= 0: return np.nan, np.nan, np.nan
    k80 = kd + int(round(0.08/dt)); k50 = kd + int(round(0.05/dt))
    late = g[k80:].sum()
    C80 = 10*np.log10(g[kd:k80].sum()/late) if late > 0 else np.inf
    D50 = g[kd:k50].sum()/e_tot
    edc = np.cumsum(g[kd:][::-1])[::-1]; edc /= max(edc[0],1e-30)
    L = 10*np.log10(np.maximum(edc,1e-12)); tt = np.arange(len(L))*dt
    return edt_from_edc(tt, L), C80, D50

def meas_params(ir, fs):
    t, L = rir.schroeder_curve(ir, fs)
    edt = edt_from_edc(t, L)
    # C80/D50 de la energia de la IR desde el arribo directo
    e = ir.astype(float)**2
    kd = int(np.argmax(np.abs(ir)))
    dt = 1.0/fs; k80 = kd+int(0.08*fs); k50 = kd+int(0.05*fs)
    late = e[k80:].sum()
    C80 = 10*np.log10(e[kd:k80].sum()/late) if late > 0 else np.inf
    D50 = e[kd:k50].sum()/max(e[kd:].sum(),1e-30)
    return edt, C80, D50

bands = [b for b in (250,500,1000,2000,4000,8000)]
# area efectiva (quita voxelizado) desde el mfp simulado
scn_p = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.2, scatter=scat, c=c, T=20, RH=50)
mfp = ge.diffuse_tail(scn_p, src, n_rays=6000, dt=0.002, t_max=0.6, max_refl=300,
                      e_min=1e-9, bands=[500.0], air=True, seed=5)["mean_free_path"]
S_eff = 4.0*V/mfp
# calibrar alpha a 500 Hz con Eyring+aire (como el gate)
def eyring_air(a, mb):
    A = -S_eff*np.log(1-a); return 24*np.log(10)*V/(c*(A+4*mb*V))
# medido 500
vals = []
for j in range(rirs.shape[1]):
    e,_c,_d = meas_params(rir.band_filter(rirs[:,j,SRC], fs, 500.0), fs)
    if np.isfinite(e): vals.append(e)
edt500 = float(np.median(vals))
mb500 = 2.0*float(aa.air_absorption_alpha(500.0, T=20, RH=50))
# invertir eyring_air para a_wall
from scipy.optimize import brentq
a_wall = brentq(lambda a: eyring_air(a, mb500)-edt500, 1e-3, 0.95)
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=a_wall, scatter=scat, c=c, T=20, RH=50)
print(f"V={V:.1f} S_eff={S_eff:.1f} mfp={mfp:.2f} a_wall(500)={a_wall:.3f}")

dt = 0.001; t_max = 1.0
sub = np.linspace(0, rirs.shape[1]-1, 30).astype(int)   # 30 mics para la compuesta
print(f"{'band':>5} | {'EDT_meas':>8} {'EDT_comp':>8} {'EDT_tail':>8} | "
      f"{'C80_meas':>8} {'C80_comp':>8} | {'D50_meas':>8} {'D50_comp':>8}")
for b in bands:
    mb = 2.0*float(aa.air_absorption_alpha(float(b), T=20, RH=50))
    # medido (135 mics)
    em, cm, dm = [], [], []
    for j in range(rirs.shape[1]):
        e,cc,dd = meas_params(rir.band_filter(rirs[:,j,SRC], fs, float(b)), fs)
        if np.isfinite(e): em.append(e); cm.append(cc); dm.append(dd)
    # cola UNA vez
    tl = ge.diffuse_tail(scn, src, n_rays=9000, dt=dt, t_max=t_max, max_refl=1000,
                         e_min=1e-12, bands=[float(b)], air=True, seed=5)
    w = tl["w"][0]; n_bins = len(w); s = src.q/(np.pi*S_eff); g_tail = s*w
    # cola-sola EDT (gate viejo)
    edc = np.cumsum(w[::-1])[::-1]/max(w.sum(),1e-30)
    Lt = 10*np.log10(np.maximum(edc,1e-30))
    edt_tail = edt_from_edc(tl["t"], Lt)
    # compuesta por mic (directo inline + cola)
    ec, cc2, dd2 = [], [], []
    for j in sub:
        rr = float(np.linalg.norm(mic_al[j]-src.pos))
        e_dir = (src.q/(4*np.pi*rr))**2 * np.exp(-2*float(aa.air_absorption_alpha(float(b),T=20,RH=50))*rr)
        g = g_tail.copy(); kd = int(rr/c/dt)
        if kd < n_bins: g[kd] += e_dir
        e,c80,d50 = params_from_energy(g, tl["t"], kd, dt)
        if np.isfinite(e): ec.append(e); cc2.append(c80); dd2.append(d50)
    print(f"{b:5d} | {np.median(em):8.3f} {np.median(ec):8.3f} {edt_tail:8.3f} | "
          f"{np.median(cm):8.2f} {np.median(cc2):8.2f} | "
          f"{np.median(dm):8.3f} {np.median(dd2):8.3f}")
