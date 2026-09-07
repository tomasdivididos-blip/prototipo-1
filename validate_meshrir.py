# -*- coding: utf-8 -*-
"""Validacion M1 (error de frecuencia modal) sobre MeshRIR.

Protocolo: validation_protocol.md (CONGELADO 2026-09-04), metrica M1.

    M1 = mediana de |f_pred - f_med| / f_med  sobre modos apareados.  Umbral <= 3%.

Por que MeshRIR y por que M1 primero (ver notas de la sesion 2026-09-05):
  - fn = (c/2) sqrt((nx/Lx)^2 + (ny/Ly)^2 + (nz/Lz)^2): dependen SOLO de la
    geometria y de c. Con la reactancia auto del material OFF (default desde
    2026-09-04) el amortiguamiento no corre las fn de forma apreciable, asi
    que M1 NO necesita el catalogo de alfa ni reconstruir el offset de
    coordenadas de MeshRIR. Es el resultado material-independiente y
    coordenada-independiente: el numero falsable mas limpio.

Regla de oro anti-sesgo (protocolo 1): nada se tunea al resultado. La geometria
sale del paper (7.0 x 6.4 x 2.7), c sale de la temperatura medida (26.3 C).

Lado MEDIDO: promedio espacial del espectro de potencia sobre los 3969 mics del
grid, picos por prominencia (rir.find_modal_peaks) en la banda modal [20, 120].
Lado PREDICHO: FEM del propio software (build_volume_mesh -> build_KM ->
solve_modes) + oraculo analitico rigido para separar el error NUMERICO del fisico.
"""
import json
import os
import numpy as np

import rir
from geometry import make_room
from acoustic_mesh import build_volume_mesh, mesh_info, max_solver_frequency
from acoustic_fem import build_KM, solve_modes

# --- Datos del recinto (del paper MeshRIR / protocolo, NO tuneados) ----------
LX, LY, LZ = 7.0, 6.4, 2.7          # m, dimensiones interiores del cuboide
TEMP_C = 26.3                        # C, temperatura media reportada (data.json)
C_SOUND = 20.05 * np.sqrt(273.15 + TEMP_C)   # m/s (Kuttruff, c ~ 20.05 sqrt(T[K]))

DATA_DIR = os.path.join("datasets", "meshrir", "S1-M3969_npy")
BAND = (20.0, 120.0)                 # banda modal de analisis (Hz)

# --- Parametros de simulacion ------------------------------------------------
N_PER_METER = 4.0     # piso de error numerico ~0.38% (converge O(h^2), ver sesion)
N_MODES = 50


# ---------------------------------------------------------------------------
# Lado MEDIDO
# ---------------------------------------------------------------------------
def load_positions(data_dir):
    """Posiciones locales (marco centrado en la region) de mics y fuente.

    OJO: MeshRIR fija el origen en el CENTRO DE LA REGION de medicion, no en la
    sala. La ubicacion absoluta del rig dentro del cuarto NO esta publicada (ni
    en el paper, ni en el repo, ni en la pagina). Ver sesion 2026-09-05.
    """
    with open(os.path.join(data_dir, "data.json"), "r") as f:
        meta = json.load(f)
    npts = int(meta["number of points"])
    mics = np.array([[meta[f"ir_{i}"]["pos"][k] for k in "xyz"] for i in range(npts)])
    src = np.array([meta["src_0"]["pos"][k] for k in "xyz"])
    return mics, src, int(meta["samplerate"]), npts


def measured_spatial_spectrum(data_dir, subsample=1):
    """Promedio espacial del espectro de POTENCIA sobre el grid de mics.

    Acumula |H(f)|^2 mic a mic (nunca carga todas las IR en RAM). Devuelve
    (freq, mean_power, used, ir_len). Es el lado medido para M1 y M4.
    """
    _mics, _src, fs, npts = load_positions(data_dir)
    freq = None
    power_sum = None
    used = 0
    ir_len = None
    for i in range(0, npts, subsample):
        ir = np.load(os.path.join(data_dir, f"ir_{i}.npy")).ravel()
        ir_len = len(ir)
        f, H = rir.rir_to_frf(ir, fs, f_min=10.0, f_max=200.0, pad_factor=4)
        if freq is None:
            freq = f
            power_sum = np.zeros_like(f, dtype=np.float64)
        power_sum += np.abs(H) ** 2
        used += 1
    return freq, power_sum / used, used, ir_len, fs


def measured_modal_peaks(data_dir, fs_expect=48000, subsample=1):
    """Promedio espacial -> picos modales medidos (banda modal)."""
    freq, mean_power, used, ir_len, fs = measured_spatial_spectrum(data_dir, subsample)
    assert fs == fs_expect, f"fs inesperado: {fs}"
    mag_db = rir.spectrum_db(np.sqrt(mean_power))          # forma, no nivel
    peaks = rir.find_modal_peaks(freq, mag_db, f_lo=BAND[0], f_hi=BAND[1],
                                 prominence_db=3.0, max_peaks=14)
    df_real = 1.0 / (ir_len / fs)    # 1/T: resolucion real de la medicion (pre-pad)
    return [p[0] for p in peaks], df_real, used


# ---------------------------------------------------------------------------
# Lado PREDICHO
# ---------------------------------------------------------------------------
def analytic_modes(lx, ly, lz, c, f_hi):
    """Modos de caja de paredes rigidas (oraculo). fn <= f_hi."""
    out = []
    nmax = int(np.ceil(2 * lx * f_hi / c)) + 1
    for nx in range(nmax + 1):
        for ny in range(nmax + 1):
            for nz in range(nmax + 1):
                if nx == ny == nz == 0:
                    continue
                fn = (c / 2.0) * np.sqrt((nx / lx) ** 2 + (ny / ly) ** 2 + (nz / lz) ** 2)
                if fn <= f_hi:
                    out.append((fn, (nx, ny, nz)))
    return sorted(out)


def fem_solve(lx, ly, lz, c, npm, n_modes):
    """Solve modal completo: evaluador de campo + freqs + modos + f_max."""
    from acoustic_fem import FieldEvaluator
    sv, st, _e, _n = make_room(lx, ly, lz, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=npm)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=n_modes, c=c)
    info = mesh_info(nodes, tets)
    f_max = max_solver_frequency(info["h_max"])
    loc = FieldEvaluator(nodes, tets)
    return loc, freqs, phis, f_max, info


def fem_modes(lx, ly, lz, c, npm, n_modes):
    """FEM del software: fn que efectivamente predice el producto."""
    _loc, freqs, _phis, f_max, info = fem_solve(lx, ly, lz, c, npm, n_modes)
    return freqs, f_max, info


# ---------------------------------------------------------------------------
# Emparejamiento + metrica
# ---------------------------------------------------------------------------
def match_nearest(measured, predicted):
    """Para cada pico medido -> fn predicho mas cercano. Devuelve (f_med, f_pred, rel)."""
    predicted = np.asarray(predicted, dtype=float)
    rows = []
    for fm in measured:
        j = int(np.argmin(np.abs(predicted - fm)))
        fp = float(predicted[j])
        rows.append((fm, fp, abs(fp - fm) / fm))
    return rows


def main():
    print("=" * 74)
    print("Validacion M1 - MeshRIR (error de frecuencia modal)")
    print(f"  Caja {LX} x {LY} x {LZ} m | T={TEMP_C} C -> c={C_SOUND:.1f} m/s")
    print("=" * 74)

    # PREDICHO
    fa = analytic_modes(LX, LY, LZ, C_SOUND, BAND[1] + 15.0)
    f_ana = np.array([f for f, _ in fa])
    freqs_fem, f_max_mesh, info = fem_modes(LX, LY, LZ, C_SOUND, N_PER_METER, N_MODES)
    fem_in = freqs_fem[(freqs_fem >= BAND[0]) & (freqs_fem <= BAND[1])]
    ana_in = f_ana[(f_ana >= BAND[0]) & (f_ana <= BAND[1])]

    print(f"\n[malla] h_max={info['h_max']:.3f} m -> f_max_solver={f_max_mesh:.1f} Hz "
          f"({'cubre' if f_max_mesh >= BAND[1] else 'NO cubre'} la banda {BAND[1]:.0f} Hz)")

    # Error numerico: FEM vs analitico (mismo modo por cercania)
    num_err = []
    for f in fem_in:
        j = int(np.argmin(np.abs(f_ana - f)))
        num_err.append(abs(f - f_ana[j]) / f_ana[j])
    num_err = np.array(num_err)
    print(f"[num]  FEM vs analitico en banda: mediana {np.median(num_err)*100:.2f}% "
          f"| max {np.max(num_err)*100:.2f}%  (piso de error numerico)")

    # MEDIDO
    print("\n[medido] promediando espectro sobre el grid de mics...")
    meas, df_real, used = measured_modal_peaks(DATA_DIR)
    print(f"[medido] {used} mics | resolucion real 1/T = {df_real:.2f} Hz")
    print(f"[medido] picos modales: {', '.join(f'{p:.1f}' for p in meas)} Hz")

    # Piso modal fisico: no puede haber resonancia de sala por debajo del 1er modo.
    f1 = float(ana_in.min())     # primer modo axial (c/2Lmax)
    # Tolerancia de apareo fija = umbral de M1 (3%), no tuneada al resultado.
    # (df_real ~1.5 Hz es < 3% arriba de 50 Hz, no manda salvo en la banda mas baja.)
    tol = 0.03

    # M1: apareo contra FEM (lo que predice el producto) y contra analitico
    print("\n" + "-" * 74)
    print(f"{'f_med':>8} {'f_FEM':>8} {'drel_FEM':>9}   {'f_ana':>8} {'drel_ana':>9}  nota")
    print("-" * 74)
    rows_fem = match_nearest(meas, fem_in)
    rows_ana = match_nearest(meas, ana_in)
    table = []
    for (fm, fp, rf), (_, fa2, ra) in zip(rows_fem, rows_ana):
        submodal = fm < f1 * (1 - tol)       # por debajo del 1er modo -> sin socio
        nota = "sub-modal (sin socio)" if submodal else ("apareado" if rf <= tol else "residual")
        hit = " " if submodal else ("*" if rf <= tol else " ")
        print(f"{fm:8.1f} {fp:8.1f} {rf*100:8.2f}%{hit}  {fa2:8.1f} {ra*100:8.2f}%  {nota}")
        table.append((fm, fp, rf, fa2, ra, submodal))

    modal = [r for r in table if not r[5]]           # picos que SI son modos de sala
    rel_fem = [r[2] for r in modal]
    rel_ana = [r[4] for r in modal]
    matched = sum(1 for r in modal if r[2] <= tol)
    m1_fem = float(np.median(rel_fem))
    m1_ana = float(np.median(rel_ana))
    cov = matched / len(modal) if modal else 0.0
    n_sub = sum(1 for r in table if r[5])

    print("-" * 74)
    print(f"(se excluyen {n_sub} pico(s) sub-modal(es) < 1er modo {f1:.1f} Hz: no son resonancias de sala)")
    print(f"M1 (vs FEM)      = {m1_fem*100:.2f}%   (umbral <= 3%)  -> "
          f"{'PASA' if m1_fem <= 0.03 else 'FALLA'}")
    print(f"M1 (vs analitico)= {m1_ana*100:.2f}%   (error numerico del FEM ~{np.median(num_err)*100:.2f}%)")
    print(f"M2 (cobertura)   = {cov*100:.0f}%  ({matched}/{len(modal)} modos apareados "
          f"dentro de tol={tol*100:.1f}%)   (umbral >= 80%) -> "
          f"{'PASA' if cov >= 0.80 else 'FALLA'}")
    print("=" * 74)

    _write_results(meas, table, m1_fem, m1_ana, cov, matched, len(modal),
                   n_sub, f1, tol, np.median(num_err), f_max_mesh, used)


def _write_results(meas, table, m1_fem, m1_ana, cov, matched, n_modal,
                   n_sub, f1, tol, num_err_med, f_max_mesh, used):
    """Vuelca la tabla de resultados a validation_results.md (protocolo 7)."""
    lines = []
    lines.append("# Resultados de validacion\n")
    lines.append("Generado por `validate_meshrir.py`. Protocolo: `validation_protocol.md` (congelado 2026-09-04).\n")
    lines.append("## MeshRIR S1-M3969 - M1 (error de frecuencia modal)\n")
    lines.append(f"- Recinto: cuboide {LX} x {LY} x {LZ} m (paper MeshRIR).")
    lines.append(f"- c = {C_SOUND:.1f} m/s (T = {TEMP_C} C medida).")
    lines.append(f"- Mics promediados: {used}. Banda modal: {BAND[0]:.0f}-{BAND[1]:.0f} Hz.")
    lines.append(f"- Malla npm={N_PER_METER:.0f}, f_max_solver={f_max_mesh:.0f} Hz, "
                 f"piso de error numerico FEM~analitico = {num_err_med*100:.2f}% (mediana).")
    lines.append(f"- Reactancia auto del material: OFF (default, protocolo 10). alfa de catalogo: N/A para M1.\n")
    lines.append("| f_med [Hz] | f_FEM [Hz] | drel_FEM | f_ana [Hz] | drel_ana | nota |")
    lines.append("|---|---|---|---|---|---|")
    for fm, fp, rf, fa2, ra, sub in table:
        nota = "sub-modal (sin socio)" if sub else ("apareado" if rf <= tol else "residual")
        lines.append(f"| {fm:.1f} | {fp:.1f} | {rf*100:.2f}% | {fa2:.1f} | {ra*100:.2f}% | {nota} |")
    lines.append("")
    lines.append(f"**M1 (vs FEM) = {m1_fem*100:.2f}%** (umbral <= 3%) -> "
                 f"{'PASA' if m1_fem <= 0.03 else 'FALLA'}  ")
    lines.append(f"M1 (vs analitico) = {m1_ana*100:.2f}%  ")
    lines.append(f"**M2 (cobertura) = {cov*100:.0f}%** ({matched}/{n_modal}) (umbral >= 80%) -> "
                 f"{'PASA' if cov >= 0.80 else 'FALLA'}  ")
    lines.append(f"\nExcluidos {n_sub} pico(s) sub-modal(es) por debajo del 1er modo axial "
                 f"({f1:.1f} Hz): no son resonancias de sala (energia sub-modal del sistema, "
                 f"no del recinto). No se tunea nada; la exclusion es fisica.\n")
    # OJO: archivo PROPIO del runner. NO escribir validation_results.md (el master
    # agregado, mantenido a mano): este runner lo sobrescribia y borraba las secciones
    # M4/FLAIR agregadas despues (bug detectado 2026-09-06, tras re-run del auditor).
    with open("validation_meshrir_m1.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n[out] validation_meshrir_m1.md escrito.")


if __name__ == "__main__":
    main()
