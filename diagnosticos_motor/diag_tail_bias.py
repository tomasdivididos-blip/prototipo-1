"""Diagnostico del sesgo +EDT del tail estocastico vs Eyring.
Separa: (1) ritmo ASINTOTICO del tail (Sabine vs Eyring), (2) EDT inicial,
(3) artefacto del buildup en el EDC (0 dB mal referenciado).
Shoebox 5x4x3, aire OFF, barrido de alpha. Sin dependencias de GUI."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

def eyring_T(V, S, a, c):
    return 24.0 * V * np.log(10.0) / (c * S * (-np.log(1.0 - a)))

def sabine_T(V, S, a, c):
    return 24.0 * V * np.log(10.0) / (c * S * a)

def edc_db(w):
    edc = np.cumsum(w[::-1])[::-1]
    edc = edc / max(edc[0], 1e-30)
    return 10.0 * np.log10(np.maximum(edc, 1e-12))

def fit_rt(L, dt, lo, hi):
    t = np.arange(len(L)) * dt
    sel = (L <= lo) & (L >= hi)
    if sel.sum() < 3:
        return float("nan")
    slope = np.polyfit(t[sel], L[sel], 1)[0]
    return -60.0 / slope

def edc_db_from_peak(w):
    """EDC referenciado al PICO del buildup (descarta la subida inicial):
    integral de Schroeder empezando en el bin del maximo de w."""
    k = int(np.argmax(w))
    ww = w.copy(); ww[:k] = 0.0
    edc = np.cumsum(ww[::-1])[::-1]
    edc = edc / max(edc[k], 1e-30)
    L = 10.0 * np.log10(np.maximum(edc, 1e-12))
    return L, k

Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0); ext = vmax - vmin
src = ge.GeoSource(pos=vmin + np.array([0.43, 0.57, 0.50]) * ext)
sc0 = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1)
V = sc0.volume; S = sc0.total_area(); c = sc0.c
print(f"shoebox V={V:.2f} S={S:.2f} 4V/S={4*V/S:.3f} c={c:.1f}")
print(f"{'alpha':>6} {'Eyr':>6} {'Sab':>6} | {'EDTn':>6} {'/Ey':>6} | "
      f"{'EDTpk':>6} {'/Ey':>6} | {'T30':>6} {'/Ey':>6} {'/Sab':>6}")

for a in (0.05, 0.10, 0.15, 0.24, 0.35, 0.50):
    sc = ge.Scene.from_tet_mesh(nodes, tets, alpha=a)
    Tey = eyring_T(V, S, a, c); Tsa = sabine_T(V, S, a, c)
    r = ge.diffuse_tail(sc, src, n_rays=20000, dt=0.002, t_max=3.0,
                        max_refl=1200, e_min=1e-15, bands=[1000.0],
                        air=False, seed=7)
    w = r["w"][0]; dt = r["dt"]
    Ln = edc_db(w)
    edt_n = fit_rt(Ln, dt, 0.0, -10.0)
    Lp, kpk = edc_db_from_peak(w)
    tp = np.arange(len(Lp)) * dt
    selp = (Lp <= 0.0) & (Lp >= -10.0) & (np.arange(len(Lp)) >= kpk)
    edt_p = (-60.0 / np.polyfit(tp[selp], Lp[selp], 1)[0]) if selp.sum() >= 3 else float("nan")
    t30 = fit_rt(Ln, dt, -5.0, -35.0)
    print(f"{a:>6.2f} {Tey:>6.3f} {Tsa:>6.3f} | {edt_n:>6.3f} {edt_n/Tey:>6.3f} | "
          f"{edt_p:>6.3f} {edt_p/Tey:>6.3f} | {t30:>6.3f} {t30/Tey:>6.3f} {t30/Tsa:>6.3f}")
