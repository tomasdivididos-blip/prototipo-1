"""
bench_modal_decay.py
====================

Oraculos de `modal_decay` (Tarea C1, punto 3 del profesor): decaimiento del campo
manejado (modos + drive) en el receptor, sin/con subs.

Chequeos falsables:
  1. CONSISTENCIA IR<->FRF: FFT(IR) reproduce la H de `acoustic_fem.frequency_response`
     (banda-limitada) a precision de maquina. El decaimiento sale de la MISMA H
     validada del solver, no de una derivacion aparte.
  2. FISICA DEL DECAIMIENTO: aislando UN modo, T30 de la EDC = 6.908/(ξ·2π·fₙ)
     (energia ~ e^{-2δt}, δ=ξωₙ; RT60=6.908/δ). Se cumple <3%.
  3. EDC monotona decreciente con rango dinamico util (banda completa, multi-modo).
  4. CSD/waterfall: forma correcta (n_slices, Nf en banda) y decae en el tiempo.
  5. A/B: agregar subs con drive de cancelacion (delay=L/c + inversion) CAMBIA el
     decaimiento del campo total (no es identico a sin subs).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_modal_decay.py
"""

from __future__ import annotations

import types
import numpy as np

import geometry
import acoustic_analysis as aa
import acoustic_fem
import modal_decay as md
from sources import OmniSource, SourceArray

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def main():
    v, t, _e, _n = geometry.make_room(6.0, 8.0, 3.0, roof_type="flat",
                                      subdiv_levels=0)
    v = np.asarray(v)
    mr = aa.run_fem_modal(v, t, n_modes=12, n_per_meter=3.0)
    rec = (2.0, 1.5, 1.4)
    xi = 0.03
    sa = SourceArray([OmniSource((1.0, -2.0, 1.2), source_type="subwoofer",
                                 label="S")])

    # --- 1) consistencia IR <-> FRF -------------------------------------------
    _t, ir, fs = md.modal_impulse_response(mr, sa, rec, f_lo=20, f_hi=200,
                                           fs=800, dur=3.0, damping=xi,
                                           bandlimit=True)
    N = len(ir)
    freqs = np.fft.rfftfreq(N, 1.0 / fs)
    Href = acoustic_fem.frequency_response(mr.locator, mr.freqs, mr.phis, sa, rec,
                                           freq_axis=freqs, damping=xi)
    Href_bl = Href * md._band_window(freqs, 20, 200)
    Hback = np.fft.rfft(ir, n=N)
    band = (freqs >= 25) & (freqs <= 195)
    err = (np.max(np.abs(Hback[band] - Href_bl[band]))
           / max(np.max(np.abs(Href_bl[band])), 1e-30))
    check("IR<->FRF: FFT(IR) reproduce la H banda-limitada del solver",
          err < 1e-9, f"err rel = {err:.1e}")

    # --- 2) T30 de un modo aislado = 6.908/(xi*w_n) ---------------------------
    one = types.SimpleNamespace(locator=mr.locator, freqs=mr.freqs[:1],
                                phis=mr.phis[:, :1])
    f1 = float(mr.freqs[0])
    _t1, ir1, fs1 = md.modal_impulse_response(one, sa, rec, f_hi=60, fs=800,
                                              dur=8.0, damping=xi)
    rt = md.decay_time(ir1, fs1)
    rt_teo = 6.908 / (xi * 2.0 * np.pi * f1)
    rel = abs(rt.rt60 - rt_teo) / rt_teo if np.isfinite(rt.rt60) else 1.0
    check("decaimiento de 1 modo: T = 6.908/(ξ·ωₙ)",
          rel < 0.03, f"medido={rt.rt60:.3f}s teo={rt_teo:.3f}s err={100*rel:.1f}%")

    # T mas corto si sube xi (mas amortiguado -> decae mas rapido)
    _t2, ir2, fs2 = md.modal_impulse_response(one, sa, rec, f_hi=60, fs=800,
                                              dur=8.0, damping=0.06)
    rt2 = md.decay_time(ir2, fs2)
    check("mas amortiguamiento -> decaimiento mas corto",
          np.isfinite(rt2.rt60) and rt2.rt60 < rt.rt60 * 0.7,
          f"xi=0.03->{rt.rt60:.2f}s  xi=0.06->{rt2.rt60:.2f}s")

    # --- 3) EDC banda completa: monotona con rango util -----------------------
    _tb, irb, fsb = md.modal_impulse_response(mr, sa, rec, f_hi=200, fs=800,
                                              dur=4.0, damping=xi)
    te, edc = md.energy_decay_db(irb, fsb)
    fin = edc[np.isfinite(edc)]
    check("EDC monotona decreciente",
          bool(np.all(np.diff(fin) <= 1e-9)))
    check("EDC con rango dinamico util (> 25 dB)", (-fin.min()) > 25.0,
          f"rango={-fin.min():.0f} dB")

    # --- 4) CSD/waterfall: forma y decaimiento temporal -----------------------
    fr, ts, Z = md.cumulative_spectral_decay(irb, fsb, f_lo=15, f_hi=120,
                                             n_slices=20)
    check("CSD shape (n_slices, Nf)",
          Z.shape[0] == 20 and Z.shape[1] == len(fr) and len(ts) == 20,
          f"{Z.shape}")
    check("CSD: eje de frecuencia dentro de la banda pedida",
          fr[0] >= 15 - 1e-6 and fr[-1] <= 120 + 1e-6)
    # el nivel medio de cada rebanada baja con el tiempo (decae)
    lvl_t = np.array([np.max(Z[k]) for k in range(Z.shape[0])])
    check("CSD: el nivel maximo por rebanada decae en el tiempo",
          lvl_t[-1] < lvl_t[0] - 10.0, f"{lvl_t[0]:.1f} -> {lvl_t[-1]:.1f} dB")

    # --- 5) A/B: los subs con drive de cancelacion cambian el decaimiento -----
    mains = SourceArray([OmniSource((1.0, -3.5, 1.2), source_type="fullrange",
                                    label="M")])
    L = 8.0
    sub = OmniSource((1.0, 3.5, 1.2), source_type="subwoofer", label="sub",
                     delay_s=L / 343.0, polarity=-1)
    both = SourceArray([mains.sources[0], sub])
    _ta, ira, fsa = md.modal_impulse_response(mr, mains, rec, f_hi=180, dur=3.0,
                                              damping=xi)
    _tb2, irb2, _ = md.modal_impulse_response(mr, both, rec, f_hi=180, dur=3.0,
                                              damping=xi)
    rta = md.decay_time(ira, fsa)
    rtb = md.decay_time(irb2, fsa)
    diff = abs(rtb.rt60 - rta.rt60) if (np.isfinite(rta.rt60)
                                        and np.isfinite(rtb.rt60)) else 1.0
    check("A/B: agregar subs (drive CABS) cambia el decaimiento del campo total",
          diff > 1e-3, f"sin={rta.rt60:.3f}s con={rtb.rt60:.3f}s Δ={diff:.3f}s")

    print("-" * 64)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
