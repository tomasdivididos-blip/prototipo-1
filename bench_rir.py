"""bench_rir.py — Oráculos de rir.py (Fase 0 del pipeline de calibración).

IRs sintéticas con f_n y RT60 CONOCIDOS (suma de senoides con decaimiento
exponencial = forma exacta de una respuesta modal), más casos degenerados
que imitan a las RIR reales del control room: truncadas a ~190 ms, con piso
de ruido, y sin energía debajo de ~70 Hz.

Correr:  python bench_rir.py
"""

import io
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

import rir


def synth_modal_ir(fs: int, dur: float, f_modes, rt60: float,
                   amps=None) -> np.ndarray:
    """IR modal sintética: sum a_n * exp(-t/tau) * sin(2 pi f_n t)."""
    t = np.arange(int(dur * fs)) / fs
    tau = rt60 / (3.0 * np.log(10.0))   # 60 dB de caída en rt60
    if amps is None:
        amps = [1.0] * len(f_modes)
    return sum(a * np.exp(-t / tau) * np.sin(2 * np.pi * fn * t)
               for a, fn in zip(amps, f_modes))


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK' if cond else 'FAIL'}]   {name}: {detail}")


# ---------------------------------------------------------------------------
print("t1: RT60 recuperado en 3 bandas para RT = 0.2 / 0.4 / 0.8 s")
fs = 48000
for rt_true in (0.2, 0.4, 0.8):
    ir = synth_modal_ir(fs, max(4 * rt_true, 1.0),
                        [85.0, 240.0, 950.0], rt_true)
    res = rir.rt60_per_band(ir, fs, bands=[125, 250, 1000])
    errs = {c: abs(r.rt60 - rt_true) / rt_true for c, r in res.items()
            if np.isfinite(r.rt60)}
    ok = (len(errs) == 3 and all(e < 0.12 for e in errs.values())
          and all(r.ok for r in res.values()))
    check(f"RT={rt_true}s", ok,
          " ".join(f"{c}:{r.rt60:.2f}s" for c, r in res.items()))

# ---------------------------------------------------------------------------
print("t2: truncamiento — RT corto sobrevive, RT largo queda flaggeado")
# Como las RIR reales: 190 ms de señal.
ir_short = synth_modal_ir(fs, 0.19, [85.0, 113.0], 0.25)
r_short = rir.rt_from_ir(rir.band_filter(ir_short, fs, 125.0), fs)
check("RT=0.25s truncada a 190 ms ajusta",
      np.isfinite(r_short.rt60) and abs(r_short.rt60 - 0.25) / 0.25 < 0.15,
      repr(r_short))
ir_long = synth_modal_ir(fs, 0.19, [85.0, 113.0], 0.9)
r_long = rir.rt_from_ir(rir.band_filter(ir_long, fs, 125.0), fs)
# Con 190 ms de una caída de 0.9 s solo hay ~13 dB de EDC: no debe dar
# un T20/T30 "confiable" (ok=False o directamente sin ajuste).
check("RT=0.9s truncada a 190 ms NO se reporta confiable",
      (not r_long.ok), repr(r_long))

# ---------------------------------------------------------------------------
print("t3: piso de ruido — el rango dinámico se reporta y el fit lo esquiva")
rng = np.random.default_rng(7)
ir_noisy = synth_modal_ir(fs, 1.0, [85.0, 240.0], 0.4)
ir_noisy = ir_noisy + 10 ** (-45.0 / 20.0) * rng.standard_normal(len(ir_noisy))
r_n = rir.rt_from_ir(rir.band_filter(ir_noisy, fs, 250.0), fs)
check("RT con piso -45 dB", np.isfinite(r_n.rt60)
      and abs(r_n.rt60 - 0.4) / 0.4 < 0.15 and r_n.ok,
      f"{r_n!r}, rango {r_n.dyn_range_db:.0f} dB")

# ---------------------------------------------------------------------------
print("t4: FRF — picos en las f_n exactas y resolución honesta")
ir4 = synth_modal_ir(fs, 1.0, [61.0, 88.5, 132.0], 0.4)
f4, H4 = rir.rir_to_frf(ir4, fs, f_max=300)
pks = rir.find_modal_peaks(f4, rir.spectrum_db(H4), 40, 200)
got = [p[0] for p in pks]
check("3 picos localizados a <1.5 Hz",
      len(got) == 3 and all(any(abs(g - fn) < 1.5 for g in got)
                            for fn in [61.0, 88.5, 132.0]),
      f"{[f'{g:.1f}' for g in got]}")
# Dos modos separados MENOS que 1/T (=5.3 Hz con 190 ms) se funden en uno:
ir5 = synth_modal_ir(fs, 0.19, [100.0, 103.0], 0.25)
f5, H5 = rir.rir_to_frf(ir5, fs, f_max=300)
pks5 = rir.find_modal_peaks(f5, rir.spectrum_db(H5), 60, 160)
check("modos a 3 Hz con T=190 ms se ven como 1 pico (df=1/T)",
      len(pks5) == 1, f"{[f'{p[0]:.1f}' for p in pks5]}")

# ---------------------------------------------------------------------------
print("t5: load_rir — escala de enteros preservada y canal por energía")
buf = io.BytesIO()
sig = (0.5 * synth_modal_ir(fs, 0.2, [90.0], 0.2))
wavfile.write(buf, fs, (sig * 32767).astype(np.int16))
buf.seek(0)
fs_r, x_r = rir.load_rir(buf)
peak_true = float(np.max(np.abs(sig)))
check("int16 escala a [-1,1] sin normalizar al pico",
      fs_r == fs and abs(np.max(np.abs(x_r)) - peak_true) < 0.005,
      f"pico={np.max(np.abs(x_r)):.3f} (señal original {peak_true:.3f})")
buf2 = io.BytesIO()
stereo = np.stack([0.001 * rng.standard_normal(len(sig)), sig], axis=1)
wavfile.write(buf2, fs, (stereo * 32767).astype(np.int16))
buf2.seek(0)
_fs2, x_st = rir.load_rir(buf2)
check("estéreo elige el canal con energía",
      np.corrcoef(x_st, sig)[0, 1] > 0.99, "canal 2 (señal)")

# ---------------------------------------------------------------------------
print("t6: spectrum_db — relativo al máximo por default, ref explícita")
mag = rir.spectrum_db(np.array([1.0, 10.0]))
check("relativo: max=0 dB", abs(mag[1]) < 1e-9 and abs(mag[0] + 20) < 1e-9,
      f"{mag}")
mag2 = rir.spectrum_db(np.array([1.0]), ref=0.1)
check("ref=0.1 -> +20 dB", abs(mag2[0] - 20.0) < 1e-9, f"{mag2}")

# ---------------------------------------------------------------------------
print("t7: deconvolve_sweep — sweep grabado en sala sintética -> RIR conocida")
# Sweep log 70-8000 Hz de 3 s + su inverso por inversión espectral regularizada
fs7 = 48000
T_sw = 3.0
t7 = np.arange(int(T_sw * fs7)) / fs7
f0, f1 = 70.0, 8000.0
k = np.log(f1 / f0)
sweep = np.sin(2 * np.pi * f0 * T_sw / k * (np.exp(t7 / T_sw * k) - 1.0))
# Inverso de Farina: sweep invertido en el tiempo con compensación -6 dB/oct
inv = sweep[::-1] * np.exp(-t7 / T_sw * k)
h_true = synth_modal_ir(fs7, 0.8, [85.0, 113.0, 147.0], 0.35)
rec = fftconvolve(sweep, h_true, mode="full")
h_rec = rir.deconvolve_sweep(rec, inv, fs7, tail_s=0.8)
f7, H7 = rir.rir_to_frf(h_rec, fs7, f_max=300)
pk7 = [p[0] for p in rir.find_modal_peaks(f7, rir.spectrum_db(H7), 60, 200)]
check("picos de la RIR recuperada = f_n originales",
      all(any(abs(g - fn) < 2.0 for g in pk7) for fn in [85.0, 113.0, 147.0]),
      f"{[f'{g:.1f}' for g in pk7]}")
r7 = rir.rt_from_ir(rir.band_filter(h_rec, fs7, 125.0), fs7)
check("RT de la RIR recuperada = RT original (0.35 s)",
      np.isfinite(r7.rt60) and abs(r7.rt60 - 0.35) / 0.35 < 0.15, repr(r7))

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
