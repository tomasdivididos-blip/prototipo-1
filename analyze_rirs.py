"""analyze_rirs.py — Reporte de un set de RIRs medidas (pipeline calibración).

Uso:
    python analyze_rirs.py "C:\\ruta\\a\\carpeta\\con\\wavs" [f_lo] [f_hi]

Para cada WAV: RT60 por banda (con flags de calidad) y picos modales en la
banda LF. Si el set tiene el patrón L / R / LR por posición (archivos
"... P1 - L.wav" etc.), chequea además que la medición LR sea la suma
COMPLEJA de L y R (consistencia del set: sistema LTI + niveles estables).

Los WAV se cargan sin normalizar: la escala relativa entre archivos
grabados con la misma cadena se preserva.
"""

import re
import sys
from pathlib import Path

import numpy as np

import rir

F_LO_DEF, F_HI_DEF = 60.0, 200.0     # banda de análisis modal por defecto
RT_BANDS = [63, 125, 250, 500, 1000, 2000, 4000]


def main(folder: str, f_lo: float = F_LO_DEF, f_hi: float = F_HI_DEF) -> None:
    files = sorted(Path(folder).glob("*.wav"))
    files = [p for p in files if "calibra" not in p.name.lower()]
    if not files:
        print(f"No hay .wav en {folder}")
        return

    print(f"{len(files)} RIRs en {folder}")
    print(f"banda modal analizada: {f_lo:.0f}-{f_hi:.0f} Hz\n")

    # ------------------------------------------------------------------
    # 1) RT60 por banda + picos modales por archivo
    # ------------------------------------------------------------------
    hdr = f"{'archivo':28s} {'dur':>6s} " + \
        " ".join(f"{c:>7d}" for c in RT_BANDS)
    print(hdr + "   (RT60 [s]; ? = fit poco confiable, -- = sin rango)")
    print("-" * len(hdr))

    frfs = {}       # nombre -> (freq, H) para el chequeo LR
    rt_ok = {c: [] for c in RT_BANDS}
    for p in files:
        fs, x = rir.load_rir(p)
        res = rir.rt60_per_band(x, fs, bands=RT_BANDS)
        cells = []
        for c in RT_BANDS:
            r = res.get(c)
            if r is None or not np.isfinite(r.rt60):
                cells.append(f"{'--':>7s}")
            else:
                cells.append(f"{r.rt60:6.2f}{'' if r.ok else '?':1s}")
                if r.ok:
                    rt_ok[c].append(r.rt60)
        print(f"{p.stem:28s} {len(x)/fs:5.2f}s " + " ".join(cells))
        frfs[p.stem] = rir.rir_to_frf(x, fs, f_min=20.0, f_max=500.0)

    print("-" * len(hdr))
    cells = []
    for c in RT_BANDS:
        v = rt_ok[c]
        cells.append(f"{np.mean(v):6.2f} " if v else f"{'--':>7s}")
    print(f"{'PROMEDIO (solo fits ok)':28s} {'':6s} " + " ".join(cells))

    # ------------------------------------------------------------------
    # 2) Picos modales por archivo
    # ------------------------------------------------------------------
    print(f"\npicos modales {f_lo:.0f}-{f_hi:.0f} Hz "
          f"(prominencia >= 4 dB, resolución real = 1/dur):")
    all_peaks = []
    for name, (f, H) in frfs.items():
        pks = rir.find_modal_peaks(f, rir.spectrum_db(H), f_lo, f_hi)
        all_peaks.extend(pk[0] for pk in pks)
        print(f"  {name:28s} " +
              "  ".join(f"{pk[0]:5.1f}" for pk in pks))

    # Histograma grueso de consenso entre archivos (bins de 3 Hz)
    if all_peaks:
        bins = np.arange(f_lo, f_hi + 3.0, 3.0)
        hist, edges = np.histogram(all_peaks, bins=bins)
        consenso = [(0.5 * (edges[i] + edges[i + 1]), int(h))
                    for i, h in enumerate(hist) if h >= max(3, len(files) // 3)]
        print("\nfrecuencias con consenso entre mediciones (candidatas a modo):")
        print("  " + "  ".join(f"{fc:.0f}Hz(x{h})" for fc, h in consenso))

    # ------------------------------------------------------------------
    # 3) Chequeo L + R vs LR (suma compleja) por posición
    # ------------------------------------------------------------------
    pat = re.compile(r"^(?P<base>.*?)\s*-\s*(?P<ch>LR|L|R)$")
    grupos = {}
    for name in frfs:
        m = pat.match(name)
        if m:
            grupos.setdefault(m.group("base"), {})[m.group("ch")] = name
    tríos = {b: g for b, g in grupos.items() if set(g) >= {"L", "R", "LR"}}
    if tríos:
        print(f"\nchequeo LR = L + R (suma compleja) en {f_lo:.0f}-{f_hi:.0f} Hz:")
        print(f"  {'posición':20s} {'RMS coherente':>14s} "
              f"{'RMS incoherente':>16s}   (dB; menor = mejor)")
        for base, g in sorted(tríos.items()):
            fL, HL = frfs[g["L"]]
            fR, HR = frfs[g["R"]]
            fS, HS = frfs[g["LR"]]
            # ejes iguales si dur igual; interpolar al eje de LR por robustez
            HLs = np.interp(fS, fL, HL.real) + 1j * np.interp(fS, fL, HL.imag)
            HRs = np.interp(fS, fR, HR.real) + 1j * np.interp(fS, fR, HR.imag)
            m_band = (fS >= f_lo) & (fS <= f_hi)

            def rms_db_vs(H_pred):
                a = rir.spectrum_db(HS[m_band], ref=1.0)
                b = rir.spectrum_db(H_pred[m_band], ref=1.0)
                d = a - b
                return float(np.sqrt(np.mean((d - d.mean()) ** 2)))

            rms_coh = rms_db_vs(HLs + HRs)                    # suma compleja
            rms_inc = rms_db_vs(np.sqrt(np.abs(HLs) ** 2
                                        + np.abs(HRs) ** 2))  # suma de energía
            print(f"  {base:20s} {rms_coh:13.2f} {rms_inc:15.2f}")
        print("  (si 'coherente' << 'incoherente', el set es consistente y")
        print("   valida la suma compleja multi-fuente que usa el simulador)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    lo = float(sys.argv[2]) if len(sys.argv) > 2 else F_LO_DEF
    hi = float(sys.argv[3]) if len(sys.argv) > 3 else F_HI_DEF
    main(sys.argv[1], lo, hi)
