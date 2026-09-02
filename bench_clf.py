"""bench_clf.py — validación del lector CLF (frd.load_clf).

Ground truth = la respuesta en eje que muestra el CLF Viewer para el QSC AC-C2T
(q_spk_acc_2t_clf.cf2), pasada por el usuario. 27 bandas de 1/3 de octava
(50 Hz .. 20 kHz). Los .cf2 se buscan en el directorio del proyecto o en Downloads.

Cubre: match exacto vs viewer, los otros parlantes, deteccion de version, y el
ANCLAJE ROBUSTO (corrida de tension) generalizado mas alla del offset fijo 4764.
"""
import os
import numpy as np
import frd

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIRS = [_HERE, r"C:\Users\aceve\Downloads"]


def _find(name):
    for d in _DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


F_2T = _find("q_spk_acc_2t_clf.cf2")
F_4T = _find("q_spk_acs_4t_clf.cf2")
F_6T = _find("q_spk_acs_6t_clf.cf2")

# Ground truth del viewer para el AC-C2T (dB SPL @ 1W/1m), 50 Hz .. 20 kHz.
GT_2T = np.array([70.1, 77.2, 84.9, 88.8, 90.0, 90.2, 88.9, 87.8, 86.0, 84.1,
                  83.3, 83.8, 84.1, 84.4, 84.0, 84.6, 84.8, 84.9, 84.3, 83.3,
                  83.1, 85.4, 88.8, 90.2, 89.9, 87.4, 83.9])

fails = []
def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

if F_2T is None:
    print("SKIP: no está q_spk_acc_2t_clf.cf2 en", _DIRS)
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

# --- deteccion de version del formato ---
data = open(F_2T, "rb").read()
ver = frd._clf_format_version(data)
ck(ver == "v2.0c", f"versión detectada = {ver!r} (esperado 'v2.0c')")

# --- los otros dos parlantes: parsea y da respuesta plausible ---
for path, name in [(F_4T, "acs_4t"), (F_6T, "acs_6t")]:
    if path is None:
        print("  (skip", name, "- no está)")
        continue
    f2, s2, _ = frd.load_clf(path)
    ck(s2.shape == (27,) and np.all(np.isfinite(s2)),
       f"{name}: 27 valores finitos")
    ck(20.0 < s2.min() and s2.max() < 150.0 and np.max(np.abs(np.diff(s2))) < 20.0,
       f"{name}: respuesta suave y en rango [{s2.min():.0f},{s2.max():.0f}] dB")

# --- ANCLAJE ROBUSTO: la corrida de tensión localiza el on-axis ---
run = frd._find_voltage_run(data)
ck(run is not None and run[1] == 27 and abs(run[2] - 2.83) < 0.02,
   f"corrida de tensión: {run[1] if run else 0} valores de "
   f"{run[2] if run else 0:.3f} V @ byte {run[0] if run else -1}")

# Padear el frente con 40 bytes (10 float32) INVALIDA el offset fijo 4764 (el
# array se corre a 4804), forzando el anclaje por corrida de tensión. Debe
# devolver EXACTO el mismo ground truth.
padded = b"\x00" * 40 + data
spl_anchor = frd._find_clf_onaxis(padded)
ck(np.allclose(np.round(spl_anchor, 1), GT_2T, atol=0.05),
   f"anclaje robusto tras padeo reproduce el GT (máx Δ="
   f"{np.max(np.abs(np.round(spl_anchor,1)-GT_2T)):.3f} dB)")

# El offset fijo directo sigue reproduciendo el GT (no hubo regresión).
spl_fixed = np.frombuffer(data[4764:4764 + 27 * 4], dtype="<f4").astype(float)
ck(np.allclose(np.round(spl_fixed, 1), GT_2T, atol=0.05),
   "offset fijo 4764 reproduce el ground truth (sin regresión)")

# --- integración con SourceResponse (el pipeline real del panel) ---
from sources import SourceResponse
resp = SourceResponse.from_frd(freq, spl, None, name="AC-C2T", anchor="absolute")
g = resp.gain_spectrum(np.array([125.0, 1000.0]))
ck(np.all(np.isfinite(g)), "SourceResponse.from_frd consume el CLF sin romper")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
