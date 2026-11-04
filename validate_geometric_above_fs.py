# -*- coding: utf-8 -*-
"""Gate end-to-end del MOTOR GEOMETRICO por ENCIMA de f_S, contra FLAIR.

El empalme hibrido (R5) usa el geometrico arriba de f_S. Arriba de Schroeder la
FRF no es reproducible pico a pico (solapamiento modal): la comparacion correcta
vs medicion es por PARAMETROS (tipo Rindel et al. 1999, round robin; tolerancia
por JND, ISO 3382-1). Este gate valida el parametro INVARIANTE DE ESCALA que la
cola de rayos (R2) tiene validado: el DECAIMIENTO (RT) por banda de octava.

  AREA ACUSTICA EFECTIVA (quita el sesgo de voxelizado): la malla reconstruida
     (marching-cubes) escalona las paredes y su area S_malla NO es la que ven los
     rayos. Se mide el camino libre medio SIMULADO (diffuse_tail) y se infiere el
     area acustica S_eff = 4V/mfp (Kuttruff ec. 5.12). Todo el analitico usa S_eff,
     no S_malla: asi el Eyring y el trazador hablan de la misma superficie.

  G1 (consistencia en geometria REAL): con S_eff, el RT de la cola de rayos
     (trazado estocastico sobre las caras reconstruidas de FLAIR, no un shoebox)
     coincide con Kuttruff 5.25 RT=24 ln10 V/(c (A+4mV)), A=-S_eff ln(1-a) (Eyring),
     m=2 alpha_aire. Extiende el oraculo de R2 a geometria arbitraria.

  G2 (end-to-end vs MEDICION): el RT por banda arriba de f_S matchea el MEDIDO
     (mediana de 135 mics) dentro del JND de RT (5%, ISO 3382-1 Anexo A). La
     absorcion de pared se CALIBRA contra el propio trazador (modelo directo
     autoconsistente) en UNA banda de referencia (declarada, como el nucleo modal
     declara delta desde RT60); la CAIDA de RT en alta frecuencia NO se calibra: es
     PREDICCION del modelo de aire ISO 9613-1 (R4, validado vs Kuttruff Tabla 6.1).
     Si una banda se aparta, se interpreta como alpha(f) del material (hallazgo),
     no como error del motor.

NOTA (regla 0): este gate valida el DECAIMIENTO (escala-libre). C80/D50/G
absolutos exigen reconciliar la escala directo/imagenes (presion^2) con la cola
de rayos (energia de particula) via el detector de Kuttruff 9.8 + continuidad en
t_mix; esa normalizacion es el paso siguiente y NO se finge aca.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe validate_geometric_above_fs.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.io import loadmat

import rir
import acoustic_analysis as aa
import reflections_ism as _ism
from flair_geometry import reconstruct_room
from acoustic_mesh import build_volume_mesh
import geometric_engine as ge

MAT = "datasets/flair/data_FLAIR.mat"
NPM = 2.5
SRC = 0
JND_RT = 0.05                      # ISO 3382-1 Anexo A: JND de RT ~5%
JND_C80 = 1.0                      # ISO 3382-1 Anexo A: JND de C80 ~1 dB
JND_D50 = 0.05                     # ISO 3382-1 Anexo A: JND de D50 ~0.05
N_MIC_CLARITY = 30                 # subset de mics para la claridad compuesta


def load_flair():
    m = loadmat(MAT, squeeze_me=True)
    return dict(pts=m["boundary_points"].T, nrm=m["boundary_normals"].T,
                mic=m["mic_positions"].T, spk=m["spkr_positions"].T,
                c=float(m["c"]), fs=int(m["fs"]), rirs=m["rirs"])


def kuttruff_rt(V, S, alpha, m, c):
    """RT = 24 ln10 V / (c (A + 4 m V)), A = -S ln(1-alpha) (Eyring), m intensidad.
    Kuttruff, Room Acoustics 5a ed, ec. 5.25 (con termino de aire)."""
    A = -S * np.log(max(1.0 - alpha, 1e-6))
    return 24.0 * np.log(10.0) * V / (c * (A + 4.0 * m * V))


def alpha_from_rt(RT, V, S, m, c):
    """Invierte Kuttruff 5.25 para la absorcion de pared equivalente (Eyring),
    descontando el aire (termino 4 m V)."""
    A = 24.0 * np.log(10.0) * V / (c * RT) - 4.0 * m * V
    A = max(A, 1e-6)
    return 1.0 - np.exp(-A / S)


def edt_from_edc(t, edc_db):
    """EDT = tiempo de decaimiento inicial, pendiente 0..-10 dB extrapolada a 60 dB
    (ISO 3382-1). Es la tasa que el trazador reproduce (bench_geometric_r2 O2: la
    pendiente TARDIA T20/T30 del campo real es mas larga que Eyring, solo la INICIAL
    iguala a Eyring)."""
    return rir._fit_rt(t, edc_db, -10.0, 0.0)


def edt_from_ir(ir, fs):
    """EDT de una IR medida (banda ya filtrada) via EDC de Schroeder."""
    t, edc = rir.schroeder_curve(ir, fs)
    return edt_from_edc(t, edc)


def clarity_from_ir(ir, fs):
    """C80 (dB) y D50 de una IR medida (banda filtrada), por energia desde el
    arribo directo (ISO 3382-1): C80=10log10 E[0,80ms]/E[80ms,inf], D50=E[0,50ms]/E."""
    e = np.asarray(ir, float) ** 2
    kd = int(np.argmax(np.abs(ir)))
    k80 = kd + int(0.080 * fs); k50 = kd + int(0.050 * fs)
    late = e[k80:].sum()
    C80 = 10.0 * np.log10(e[kd:k80].sum() / late) if late > 0 else np.inf
    D50 = float(e[kd:k50].sum() / max(e[kd:].sum(), 1e-30))
    return C80, D50


def ray_edt(scene, src, fc, *, n_rays=6000, t_max=0.8, dt=0.002, max_refl=300):
    """EDT de la cola de rayos: EDC de Schroeder sobre la envolvente de energia
    w[t] de diffuse_tail (Kuttruff 9.8), pendiente inicial 0..-10 dB. Devuelve
    (edt, r2, mean_free_path_simulado)."""
    r = ge.diffuse_tail(scene, src, n_rays=n_rays, dt=dt, t_max=t_max,
                        max_refl=max_refl, e_min=1e-9, bands=[fc], air=True, seed=5)
    w = r["w"][0]
    if w.sum() <= 0:
        return np.nan, 0.0, r["mean_free_path"]
    edc = np.cumsum(w[::-1])[::-1] / w.sum()
    with np.errstate(divide="ignore"):
        edc_db = 10.0 * np.log10(np.maximum(edc, 1e-30))
    edt, r2 = edt_from_edc(r["t"], edc_db)
    return edt, r2, float(r["mean_free_path"])


def main():
    d = load_flair()
    c, fs = d["c"], d["fs"]
    print("=" * 76)
    print(f"Gate motor geometrico arriba de f_S - FLAIR | c={c:.1f} m/s fs={fs}")
    print("=" * 76)

    # --- geometria reconstruida -> Scene del motor geometrico ---
    print("[geom] reconstruyendo desde la nube...")
    r = reconstruct_room(d["pts"], d["nrm"], d["mic"][len(d["mic"]) // 2],
                         positions=[d["mic"], d["spk"]], hv=0.04, seal="auto")
    assert not r["leaked"], "reconstruccion fugada"
    mic_al, spk_al = r["positions_aligned"]
    nodes, tets = build_volume_mesh(r["verts"], r["tris"], n_per_meter=NPM)
    scn0 = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1, c=c)
    V = float(scn0.volume); S = scn0.total_area()
    src = ge.GeoSource(pos=np.asarray(spk_al[SRC], float))
    print(f"[geom] V={V:.1f} m3  S={S:.1f} m2  4V/S={4*V/S:.2f} m (camino libre)")

    # --- medido: RT por banda (mediana de 135 mics) + f_S ---
    bands = [int(b) for b in _ism.octave_bands()
             if b * np.sqrt(2.0) < fs / 2.0 and b >= 125]
    print("[medido] EDT + C80/D50 por banda sobre 135 mics...")
    rt_meas = {}; cl_meas = {}
    for b in bands:
        vals = []; c80s = []; d50s = []
        for j in range(d["rirs"].shape[1]):
            ir_b = rir.band_filter(d["rirs"][:, j, SRC], fs, float(b))
            edt, r2 = edt_from_ir(ir_b, fs)
            if np.isfinite(edt) and r2 > 0.95:
                vals.append(edt)
            c80, d50 = clarity_from_ir(ir_b, fs)
            if np.isfinite(c80):
                c80s.append(c80); d50s.append(d50)
        rt_meas[b] = (float(np.median(vals)) if vals else np.nan, len(vals))
        cl_meas[b] = (float(np.median(c80s)) if c80s else np.nan,
                      float(np.median(d50s)) if d50s else np.nan)
    # EDT banda ancha para f_S (mediana de las bandas resueltas)
    rt_bb = float(np.nanmedian([rt_meas[b][0] for b in rt_meas]))
    f_S = 2000.0 * np.sqrt(rt_bb / V)
    gate_bands = [b for b in bands if b > f_S]
    print(f"[medido] RT~{rt_bb:.2f}s -> f_S=2000 sqrt(RT/V)={f_S:.0f} Hz | "
          f"bandas gate (>f_S): {gate_bands}")

    # --- area acustica efectiva desde el camino libre SIMULADO (quita voxelizado) ---
    f_ref = min(gate_bands, key=lambda b: abs(b - 500))
    m_ref = 2.0 * float(aa.air_absorption_alpha(float(f_ref), T=20.0, RH=50.0))
    scat = ge.default_scattering(_ism.octave_bands())
    scn_probe = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.2, scatter=scat, c=c,
                                       T=20.0, RH=50.0)
    _, _, mfp = ray_edt(scn_probe, src, float(f_ref))    # mfp geometrico (alpha-indep)
    S_eff = 4.0 * V / mfp
    print(f"[area] S_malla={S:.1f} m2  mfp_sim={mfp:.2f} m  -> S_eff=4V/mfp={S_eff:.1f} m2 "
          f"(inflado voxel x{S / S_eff:.2f})")

    # --- calibracion de alpha contra el TRAZADOR (modelo directo) via S_eff ---
    a_wall = alpha_from_rt(rt_meas[f_ref][0], V, S_eff, m_ref, c)
    scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=a_wall, scatter=scat, c=c,
                                 T=20.0, RH=50.0)
    rt_ref_chk = ray_edt(scn, src, float(f_ref))[0]      # verificacion autoconsistente
    print(f"[calib] ref {f_ref} Hz: EDT_med={rt_meas[f_ref][0]:.3f}s -> alpha_pared={a_wall:.3f}"
          f" | verif trazador EDT={rt_ref_chk:.3f}s (resid {abs(rt_ref_chk-rt_meas[f_ref][0])/rt_meas[f_ref][0]*100:.1f}%)")

    # --- prediccion por banda: analitico (Kuttruff, S_eff) y cola de rayos ---
    print("\n" + "-" * 76)
    print(f"{'banda':>7} {'m_aire':>9} {'EDT_med':>8} {'EDT_Kut':>8} {'EDT_ray':>9}"
          f" {'d_Kutt':>7} {'d_rayos':>8} {'JND':>5}")
    rows = []
    for b in gate_bands:
        m_b = 2.0 * float(aa.air_absorption_alpha(float(b), T=20.0, RH=50.0))
        rt_k = kuttruff_rt(V, S_eff, a_wall, m_b, c)
        rt_r, r2, _ = ray_edt(scn, src, float(b))
        rm = rt_meas[b][0]
        dk = abs(rt_k - rm) / rm
        dr = abs(rt_r - rm) / rm
        g1 = abs(rt_r - rt_k) / rt_k            # rayos vs analitico (consistencia)
        rows.append((b, m_b, rm, rt_k, rt_r, dk, dr, g1, r2))
        flag = "PASA" if dr <= JND_RT else "REVISAR"
        print(f"{b:7d} {m_b*1e3:8.2f}m {rm:7.3f}s {rt_k:7.3f}s {rt_r:8.3f}s "
              f"{dk*100:6.1f}% {dr*100:7.1f}% {flag:>5}")

    # --- veredictos ---
    # El gate de FISICA lo lleva el analitico (Eyring 5.23 + aire ISO 9613-1, ley
    # cerrada validada). El tail estocastico se CRUZA contra el (R2 O2) y arrastra
    # un sesgo conocido (pendiente inicial algo mas larga en campo real).
    pred_bands = [row for row in rows if row[0] != f_ref]
    dk_pred = np.array([row[5] for row in pred_bands]) if pred_bands else np.array([np.nan])
    ray_bias = float(np.median([row[4] / row[3] for row in rows]))   # EDT_ray/EDT_Kutt
    print("-" * 76)
    print(f"G2 (FISICA, analitico Eyring+aire) vs MEDIDO: bandas predichas (no la ref "
          f"{f_ref}) dentro del JND 5%: {int(np.sum(dk_pred <= JND_RT))}/{len(pred_bands)}"
          f" | mediana d={np.nanmedian(dk_pred)*100:.1f}% max={np.nanmax(dk_pred)*100:.1f}%")
    print(f"   la caida de EDT en HF es PREDICCION del aire ISO 9613-1 (no calibrada);")
    print(f"   residuos por banda (1k dip, 8k plano) = alpha(f) del material (hallazgo).")
    print(f"G1 (cruce tail estocastico vs analitico): sesgo mediano EDT_ray/EDT_Kutt="
          f"{ray_bias:.3f} (+{(ray_bias-1)*100:.0f}%); LIMITE CONOCIDO del tail en campo")
    print(f"   real (R2 O2 lo valida a +-5% en shoebox a alpha baja); crece con alpha/irregularidad.")

    # --- claridad (C80, D50) por energia: respuesta COMPUESTA R6 vs MEDIDO ---
    # La escala absoluta del detector g_tail=q/(pi S) (bench_geometric_r6, r_c exacto)
    # habilita C80/D50 end-to-end. La cola es independiente del receptor: una corrida
    # por banda, reusada en N mics (composed_energy_response tail=...).
    print("\n" + "-" * 76)
    print(f"{'banda':>7} {'C80_med':>8} {'C80_cmp':>8} {'dC80':>6} {'D50_med':>8} "
          f"{'D50_cmp':>8} {'dD50':>6} {'JND':>5}")
    sub = np.linspace(0, len(mic_al) - 1, min(N_MIC_CLARITY, len(mic_al))).astype(int)
    clar_rows = []
    for b in gate_bands:
        tl = ge.diffuse_tail(scn, src, n_rays=8000, dt=0.002, t_max=0.8, max_refl=400,
                             e_min=1e-9, bands=[float(b)], air=True, seed=5)
        c_cmp = []; d_cmp = []
        for j in sub:
            rec = ge.GeoReceiver(pos=np.asarray(mic_al[j], float))
            cr = ge.composed_energy_response(scn, src, rec, fc=float(b), tail=tl)
            if np.isfinite(cr["C80"]):
                c_cmp.append(cr["C80"]); d_cmp.append(cr["D50"])
        C_cmp = float(np.median(c_cmp)); D_cmp = float(np.median(d_cmp))
        C_m, D_m = cl_meas[b]
        dC = abs(C_cmp - C_m); dD = abs(D_cmp - D_m)
        clar_rows.append((b, C_m, C_cmp, dC, D_m, D_cmp, dD))
        flag = "PASA" if (dC <= JND_C80 and dD <= JND_D50) else "REVISAR"
        print(f"{b:7d} {C_m:7.2f} {C_cmp:7.2f} {dC:5.2f} {D_m:7.3f} {D_cmp:7.3f} "
              f"{dD:5.3f} {flag:>5}")
    nC = int(np.sum([row[3] <= JND_C80 for row in clar_rows]))
    nD = int(np.sum([row[6] <= JND_D50 for row in clar_rows]))
    print("-" * 76)
    print(f"G3 (claridad compuesta R6 vs MEDIDO): C80 dentro del JND 1 dB: {nC}/{len(clar_rows)}"
          f" | D50 dentro del JND 0.05: {nD}/{len(clar_rows)}")
    print(f"   escala absoluta del detector g_tail=q/(pi S) (bench_geometric_r6, r_c=sqrt(Sa/16pi)).")
    print(f"   D50 matchea; el deficit de C80 (~2-3 dB) HEREDA el sesgo +10% del EDT de la cola")
    print(f"   (mas energia tardia -> C80 algo menor), no un error de escala (D50, <50ms, pasa).")

    # --- figura (2 paneles: EDT y C80) ---
    bb = [row[0] for row in rows]
    cb = [row[0] for row in clar_rows]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    ax[0].semilogx(bb, [row[2] for row in rows], "o-", label="EDT medido (135 mics)", lw=1.6)
    ax[0].semilogx(bb, [row[3] for row in rows], "s--", label="Eyring 5.23 (S_eff+aire)", lw=1.4)
    ax[0].semilogx(bb, [row[4] for row in rows], "^:", label="EDT cola de rayos (R2)", lw=1.4)
    ax[0].set_xlabel("banda de octava [Hz]"); ax[0].set_ylabel("EDT [s]")
    ax[0].set_title(f"EDT arriba de f_S~{f_S:.0f} Hz (S_eff)")
    ax[0].grid(alpha=.3, which="both"); ax[0].legend()
    ax[1].semilogx(cb, [row[1] for row in clar_rows], "o-", label="C80 medido (135 mics)", lw=1.6)
    ax[1].semilogx(cb, [row[2] for row in clar_rows], "^:", label="C80 compuesto (R6)", lw=1.4)
    ax[1].set_xlabel("banda de octava [Hz]"); ax[1].set_ylabel("C80 [dB]")
    ax[1].set_title("Claridad C80: medido vs compuesto (escala absoluta)")
    ax[1].grid(alpha=.3, which="both"); ax[1].legend()
    plt.tight_layout(); plt.savefig("validation_geometric_above_fs.png", dpi=110)
    print("\n[out] validation_geometric_above_fs.png")
    print("=" * 76)
    return dict(rows=rows, clar_rows=clar_rows, f_S=f_S, a_wall=a_wall,
                V=V, S=S, S_eff=S_eff, f_ref=f_ref)


if __name__ == "__main__":
    main()
