"""bench_hybrid_crossover.py - R5 del motor geometrico: empalme hibrido en f_S
(el `bench_hybrid_crossover` + end-to-end del plan).

El nucleo de R5 es el crossover complementario Linkwitz-Riley y el ensamble
FEM(<f_S) (+) geometrico(>f_S). Cada oraculo es una ley cerrada o un campo
EXACTO independiente (no es modelo-vs-modelo del propio motor):

  O1  PARTICION DE UNIDAD LR: lr_crossover da w_lo+w_hi=1 EXACTO (maquina) en
      toda la grilla; en f_S ambos valen 1/2 (cruce LR -6 dB); w_lo decrece y w_hi
      crece monotonamente. Linkwitz, JAES 1976.
  O2  TRANSPARENCIA / SIN SALTO EN f_S: si FEM y geometrico COINCIDEN en el solape
      (H_fem==H_geo==H0, espectro complejo ARBITRARIO), el hibrido reproduce H0
      EXACTO en modulo y fase en toda la grilla, en particular en f_S (no hay
      discontinuidad). Es el oraculo 'continuidad de la FRF en f_S' hecho riguroso.
  O3  LIMITES: muy por debajo de f_S el hibrido -> FEM (w_hi->0); muy por encima
      -> geometrico (w_lo->0). Con H_fem != H_geo, el error relativo al limite
      correspondiente es <1e-3 a +/- 3 octavas de f_S.
  O4  PENDIENTE LR4 = 24 dB/oct: la caida asintotica de w_lo (y de w_hi hacia
      abajo) es 6*order dB/oct; el cruce en f_S es -6.02 dB (20log10 1/2).
  O5  END-TO-END (geometria real): shoebox real; H_geo = geometric_frf (early
      reflections coherentes) y H_fem = campo modal ANALITICO del shoebox rigido
      (Kuttruff Room Acoustics sec 3.1, expansion modal, EXACTO abajo de f_S). El
      ensamble corre sin NaN, es continuo, y en f_S H_hib == (H_fem+H_geo)/2.

NOTA (regla 0, honestidad): esta bench valida la MATEMATICA del empalme y el
ensamble sobre geometria real. La validacion de CAMPO end-to-end vs MEDICION por
encima de f_S (extender MeshRIR/FLAIR al rango geometrico, tolerancia por JND,
Vorlander 2011 / Rindel et al. 1999) es el gate final y queda PENDIENTE: requiere
cablear los IR medidos de banda alta, no se finge aca.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_hybrid_crossover.py
"""
import numpy as np

import geometry
import acoustic_mesh
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


c = 343.0
fS = 120.0
freqs = np.linspace(20.0, 2000.0, 4000)

# =========================================================================
print("O1: particion de unidad del crossover LR (w_lo+w_hi=1, cruce en f_S)")
w_lo, w_hi = ge.lr_crossover(freqs, fS, order=4)
unit_err = float(np.max(np.abs(w_lo + w_hi - 1.0)))
wl_c, wh_c = ge.lr_crossover([fS], fS, order=4)
cross_ok = abs(wl_c[0] - 0.5) < 1e-12 and abs(wh_c[0] - 0.5) < 1e-12
mono = bool(np.all(np.diff(w_lo) <= 1e-15) and np.all(np.diff(w_hi) >= -1e-15))
check("O1 w_lo+w_hi == 1 (maquina)", unit_err < 1e-12, f"max err={unit_err:.1e}")
check("O1 cruce en f_S: w_lo=w_hi=1/2", cross_ok,
      f"w_lo(fS)={wl_c[0]:.6f} w_hi(fS)={wh_c[0]:.6f}")
check("O1 w_lo decreciente, w_hi creciente", mono)

# =========================================================================
print("O2: transparencia / sin salto en f_S (H_fem==H_geo -> reproduce H0)")
rng = np.random.default_rng(11)
H0 = rng.standard_normal(len(freqs)) + 1j * rng.standard_normal(len(freqs))
# inyectamos H_geo = H0 y H_fem = H0 (coinciden en el solape)
out2 = ge.hybrid_response(None, None, None, freqs=freqs, fem_frf=H0,
                          f_schroeder=fS, h_geo=H0)
err_mod = float(np.max(np.abs(np.abs(out2["H"]) - np.abs(H0))))
err_full = float(np.max(np.abs(out2["H"] - H0)))
# error exactamente en f_S
iS = int(np.argmin(np.abs(freqs - fS)))
err_fS = float(abs(out2["H"][iS] - H0[iS]))
check("O2 reproduce H0 (modulo y fase) exacto", err_full < 1e-12,
      f"max|dH|={err_full:.1e} max|d|H||={err_mod:.1e}")
check("O2 sin salto en f_S (err en f_S ~ 0)", err_fS < 1e-12, f"err(f_S)={err_fS:.1e}")

# =========================================================================
print("O3: limites (abajo->FEM, arriba->geometrico)")
# el 'arrastre' del otro motor en el limite es el PESO contrario: a -3 octavas el
# geometrico entra con w_hi(f_S/8), a +3 octavas el FEM entra con w_lo(8 f_S).
# La contaminacion es H_hib - H_dom = w_otro * (H_otro - H_dom), luego el limite
# lo fija w_otro (grilla-libre, no depende de la magnitud aleatoria).
w_hi_lo = ge.lr_crossover([fS / 8.0], fS, order=4)[1][0]
w_lo_hi = ge.lr_crossover([fS * 8.0], fS, order=4)[0][0]
# verificacion del ensamble en esos puntos: H = w_lo*fem + w_hi*geo EXACTO
ff3 = np.array([fS / 8.0, fS * 8.0])
hf3 = np.array([1.0 + 0.5j, 0.3 - 0.2j]); hg3 = np.array([-0.4 + 0.7j, 0.9 + 0.1j])
o3 = ge.hybrid_response(None, None, None, freqs=ff3, fem_frf=hf3, f_schroeder=fS, h_geo=hg3)
drag_lo = abs(o3["H"][0] - hf3[0]) / abs(hg3[0] - hf3[0])   # == w_hi(f_S/8)
drag_hi = abs(o3["H"][1] - hg3[1]) / abs(hf3[1] - hg3[1])   # == w_lo(8 f_S)
check("O3 f_S/8 -> FEM (w_hi<3e-4)", w_hi_lo < 3e-4 and abs(drag_lo - w_hi_lo) < 1e-12,
      f"w_hi={w_hi_lo:.2e}")
check("O3 8 f_S -> geometrico (w_lo<3e-4)", w_lo_hi < 3e-4 and abs(drag_hi - w_lo_hi) < 1e-12,
      f"w_lo={w_lo_hi:.2e}")

# =========================================================================
print("O4: pendiente LR4 = 24 dB/oct y cruce -6.02 dB")
f_hi = 8.0 * fS
wl1, _ = ge.lr_crossover([f_hi], fS, order=4)
wl2, _ = ge.lr_crossover([2.0 * f_hi], fS, order=4)
slope = 20.0 * np.log10(wl1[0] / wl2[0])          # dB por octava (w_lo arriba)
cross_db = 20.0 * np.log10(ge.lr_crossover([fS], fS, order=4)[0][0])
check("O4 pendiente asintotica ~24 dB/oct", abs(slope - 24.0) < 0.5,
      f"slope={slope:.2f} dB/oct")
check("O4 cruce en f_S = -6.02 dB", abs(cross_db - (-6.0206)) < 1e-3,
      f"{cross_db:.4f} dB")

# =========================================================================
print("O5: end-to-end sobre geometria real (shoebox) + continuidad en f_S")
Lx, Ly, Lz = 5.4, 4.1, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0)
src = ge.GeoSource(pos=vmin + np.array([0.30, 0.40, 0.50]) * (vmax - vmin))
rec = ge.GeoReceiver(pos=vmin + np.array([0.70, 0.65, 0.50]) * (vmax - vmin))
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.08)

fgrid = np.linspace(30.0, 400.0, 1200)
fSs = 140.0


def modal_frf_rigid(rs, rr, fg):
    """Campo modal ANALITICO del shoebox rigido (Kuttruff sec 3.1): suma sobre
    modos propios Psi_n=cos(nx pi x/Lx)... con amortiguamiento modal ligero. Es
    el campo EXACTO abajo de f_S (no es el motor geometrico)."""
    k = 2.0 * np.pi * fg / c
    H = np.zeros(len(fg), complex)
    nmax = 8
    delta = 2.0 * np.pi * 6.0 / c        # ancho de banda modal (amort. ligero)
    for nx in range(nmax):
        for ny in range(nmax):
            for nz in range(nmax):
                kn = np.pi * np.hypot(np.hypot(nx / Lx, ny / Ly), nz / Lz)
                if kn / (2 * np.pi) * c > 1.3 * fSs:   # modos hasta ~f_S
                    continue
                en = (1.0 if nx == 0 else 2.0) * (1.0 if ny == 0 else 2.0) * \
                     (1.0 if nz == 0 else 2.0)
                ps = np.cos(nx * np.pi * rs[0] / Lx) * np.cos(ny * np.pi * rs[1] / Ly) * \
                    np.cos(nz * np.pi * rs[2] / Lz)
                pr = np.cos(nx * np.pi * rr[0] / Lx) * np.cos(ny * np.pi * rr[1] / Ly) * \
                    np.cos(nz * np.pi * rr[2] / Lz)
                H += en * ps * pr / (kn ** 2 - k ** 2 - 1j * 2.0 * delta * k + 1e-12)
    return H


H_fem5 = modal_frf_rigid(src.pos, rec.pos, fgrid)
H_geo5, er5 = ge.geometric_frf(scn, src, rec, freqs=fgrid, max_order=2)
out5 = ge.hybrid_response(scn, src, rec, freqs=fgrid, fem_frf=H_fem5,
                          f_schroeder=fSs, h_geo=H_geo5)
H5 = out5["H"]
finite = bool(np.all(np.isfinite(H5)))
# continuidad: el salto entre bins adyacentes del hibrido no excede el maximo de
# los saltos de sus dos ingredientes (es combinacion convexa de funciones suaves)
jump_h = np.max(np.abs(np.diff(H5)))
jump_in = max(np.max(np.abs(np.diff(H_fem5))), np.max(np.abs(np.diff(H_geo5))))
cont = jump_h <= jump_in + 1e-9
# ensamble: H == w_lo*H_fem + w_hi*H_geo EXACTO en toda la grilla (invariante del
# crossfade); y en el bin mas cercano a f_S los pesos valen ~1/2 (dentro del paso)
id_err = float(np.max(np.abs(H5 - (out5["w_lo"] * H_fem5 + out5["w_hi"] * H_geo5))))
iS5 = int(np.argmin(np.abs(fgrid - fSs)))
w_near = out5["w_lo"][iS5]
check("O5 ensamble finito (sin NaN/Inf)", finite)
check("O5 continuo (salto hibrido <= salto ingredientes)", cont,
      f"jump_hib={jump_h:.3e} jump_in={jump_in:.3e}")
check("O5 ensamble = w_lo*fem + w_hi*geo exacto; w(f_S)~1/2", id_err < 1e-9 and abs(w_near - 0.5) < 0.01,
      f"id_err={id_err:.1e} w_lo(~f_S)={w_near:.4f}  (n_paths={er5['n_paths']})")

# =========================================================================
ok = sum(1 for _, p in results if p)
print(f"\nbench_hybrid_crossover: {ok}/{len(results)} tests OK")
raise SystemExit(0 if ok == len(results) else 1)
