# -*- coding: utf-8 -*-
"""bench_rir_noise.py -- truncado por piso de ruido en el RT (hallazgo M2 de la
auditoria). ISO 3382 / Lundeby: hay que truncar la integral de Schroeder en el
cruce decaimiento-ruido y restar el ruido (Chu); si no, la cola de ruido curva la
EDC y sesga el RT justo en las RIRs reales (ruidosas/truncadas) que son la moneda
de la validacion.

Cubre lo que bench_rir no cubria: ruido DENTRO del rango de ajuste T30 (-5..-35).
"""
import numpy as np
import rir

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    ok = bool(cond)
    PASS += ok
    FAIL += (not ok)
    print(f"  [{'OK ' if ok else 'XX '}] {name}" + (f"  {extra}" if extra else ""))


def _fit(x, fs, nt):
    t, edc = rir.schroeder_curve(x, fs, noise_trunc=nt)
    r, r2 = rir._fit_rt(t, edc, -35.0, -5.0)
    return r, r2


def synth(fs, rt_true, dur, noise_db, seed=0):
    t = np.arange(int(dur * fs)) / fs
    rng = np.random.default_rng(seed)
    sig = np.exp(-6.908 * t / rt_true) * rng.standard_normal(len(t))
    sig = sig + 10 ** (noise_db / 20.0) * rng.standard_normal(len(t))
    return sig


def main():
    fs = 8000

    # 1. IR LIMPIA: el truncado NO debe cambiar el RT (reduce al comportamiento previo)
    print("1. IR limpia -> M2 no regresiona (RT_trunc ~ RT_sin_trunc)")
    clean = np.exp(-6.908 * (np.arange(int(1.5 * fs)) / fs) / 0.5) * \
        np.random.default_rng(1).standard_normal(int(1.5 * fs))
    r_off, _ = _fit(clean, fs, False)
    r_on, _ = _fit(clean, fs, True)
    check("RT_trunc ~ RT_sin_trunc en IR limpia",
          abs(r_on - r_off) / max(r_off, 1e-9) < 0.10,
          f"off={r_off:.3f}s on={r_on:.3f}s")

    # 2. RIR RUIDOSA Y TRUNCADA (ruido a -30 dB, dentro del rango T30): M2 recupera
    print("\n2. RIR ruidosa/truncada -> M2 recupera el RT real; sin truncar se dispara")
    for rt_true, noise_db in ((0.6, -30.0), (0.4, -28.0), (0.8, -33.0)):
        sig = synth(fs, rt_true, dur=1.5 * rt_true, noise_db=noise_db, seed=int(rt_true * 10))
        r_off, _ = _fit(sig, fs, False)
        r_on, q_on = _fit(sig, fs, True)
        e_off = abs(r_off - rt_true) / rt_true if np.isfinite(r_off) else 9.99
        e_on = abs(r_on - rt_true) / rt_true if np.isfinite(r_on) else 9.99
        check(f"RT_true={rt_true:.1f}s ruido={noise_db:.0f}dB: M2 dentro de 15% "
              f"y mejor que sin truncar",
              e_on < 0.15 and e_on < e_off,
              f"off={r_off:.2f}s(err{100*e_off:+.0f}%) on={r_on:.2f}s(err{100*e_on:+.0f}%)")

    # 3. el cruce de Lundeby cae ANTES del final (detecta el piso)
    print("\n3. Lundeby detecta el cruce antes del final")
    sig = synth(fs, 0.6, dur=1.2, noise_db=-30.0, seed=7)
    cross, noise = rir._noise_crosspoint(sig.astype(float) ** 2, fs)
    check("cruce < duracion total", cross < len(sig),
          f"cruce={cross/fs:.3f}s de {len(sig)/fs:.3f}s")

    print(f"\n==== {PASS} OK / {FAIL} XX ====")
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
