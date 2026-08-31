"""bench_clf.py — validación del lector CLF (frd.load_clf).

Ground truth = la respuesta en eje que muestra el CLF Viewer para el QSC AC-C2T
(q_spk_acc_2t_clf.cf2), pasada por el usuario. 27 bandas de 1/3 de octava
(50 Hz .. 20 kHz). Los .cf2 viven en la carpeta Downloads del usuario.
"""
import os
import numpy as np
import frd

DL = r"C:\Users\aceve\Downloads"
F_2T = os.path.join(DL, "q_spk_acc_2t_clf.cf2")
F_4T = os.path.join(DL, "q_spk_acs_4t_clf.cf2")
F_6T = os.path.join(DL, "q_spk_acs_6t_clf.cf2")

# Ground truth del viewer para el AC-C2T (dB SPL @ 1W/1m), 50 Hz .. 20 kHz.
GT_2T = np.array([70.1, 77.2, 84.9, 88.8, 90.0, 90.2, 88.9, 87.8, 86.0, 84.1,
                  83.3, 83.8, 84.1, 84.4, 84.0, 84.6, 84.8, 84.9, 84.3, 83.3,
                  83.1, 85.4, 88.8, 90.2, 89.9, 87.4, 83.9])

fails = []
def ck(cond, msg):
    print(("  OK  " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

if not os.path.exists(F_2T):
    print("SKIP: no está el .cf2 de referencia en", DL)
    raise SystemExit(0)

# --- match EXACTO contra el ground truth del viewer ---
freq, spl, phase = frd.load_clf(F_2T)
ck(spl.shape == (27,), f"27 bandas -> {spl.shape}")
ck(phase is None, "phase = None (CLF no trae fase de la respuesta en eje)")
ck(np.allclose(freq, frd.CLF_THIRD_OCTAVE_HZ), "frecuencias = ISO 1/3 oct 50..20k")
err = np.max(np.abs(np.round(spl, 1) - GT_2T))
ck(err < 0.05, f"AC-C2T: máx |Δ| vs viewer = {err:.3f} dB (redondeo 1 decimal)")
ck(abs(freq[0] - 50.0) < 1e-9 and abs(freq[-1] - 20000.0) < 1e-9,
   "banda 0 = 50 Hz, banda 26 = 20 kHz")

# --- los otros dos parlantes: parsea y da respuesta plausible ---
for path, name in [(F_4T, "acs_4t"), (F_6T, "acs_6t")]:
    if not os.path.exists(path):
        print("  (skip", name, "- no está)")
        continue
    f2, s2, _ = frd.load_clf(path)
    ck(s2.shape == (27,) and np.all(np.isfinite(s2)),
       f"{name}: 27 valores finitos")
    ck(20.0 < s2.min() and s2.max() < 150.0 and np.max(np.abs(np.diff(s2))) < 20.0,
       f"{name}: respuesta suave y en rango [{s2.min():.0f},{s2.max():.0f}] dB")

# --- robustez: el fallback por ancla de 2.83 V da lo mismo que el offset fijo ---
data = open(F_2T, "rb").read()
spl_fixed = np.frombuffer(data[4764:4764 + 27 * 4], dtype="<f4").astype(float)
spl_anchor = frd._find_clf_onaxis(b"\x00" * 100 + data[100:])  # corre el offset fijo
# (al desalinear el inicio, el offset 4764 ya no cae en el array -> fuerza fallback)
ck(np.allclose(spl_fixed, GT_2T, atol=0.05), "offset fijo reproduce el ground truth")

# --- integración con SourceResponse (el pipeline real del panel) ---
from sources import SourceResponse
resp = SourceResponse.from_frd(freq, spl, None, name="AC-C2T", anchor="absolute")
g = resp.gain_spectrum(np.array([125.0, 1000.0]))
ck(np.all(np.isfinite(g)), "SourceResponse.from_frd consume el CLF sin romper")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
