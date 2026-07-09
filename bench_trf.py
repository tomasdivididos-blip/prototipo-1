"""
bench_trf.py
============

Oraculos del parser de trazas .trf binarias (frd.load_trf) usando las dos
mediciones reales del proyecto (Focal_L.trf / Focal_R.trf, monitor Focal
medido dual-channel con ECM8000 + Discrete 8, Hann, 16 FIFO).

Correr:  PYTHONIOENCODING=utf-8 python bench_trf.py
"""

import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from frd import load_trf, _TRF_MAGIC
from sources import SourceResponse

FILES = [os.path.join(HERE, "Focal_L.trf"), os.path.join(HERE, "Focal_R.trf")]

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK' if cond else 'FALLA'}] {name}" + (f"  ({detail})" if detail else ""))


missing = [p for p in FILES if not os.path.exists(p)]
if missing:
    print(f"SKIP: faltan fixtures {missing}")
    sys.exit(0)

for path in FILES:
    tag = os.path.basename(path)
    print(f"\n--- {tag} ---")
    freq, mag, phase_deg, coh = load_trf(path)

    # 1. Estructura: 464 bins en el archivo, 463 tras descartar DC.
    check("bins tras filtrar DC", len(freq) == 463, f"{len(freq)}")
    # 2. Eje monotono, banda completa de audio (Nyquist 48 kHz).
    check("freq monotona", bool(np.all(np.diff(freq) > 0)))
    check("banda de audio", freq[0] < 5 and 23000 < freq[-1] < 24001,
          f"[{freq[0]:.2f}, {freq[-1]:.1f}] Hz")
    # 3. Magnitud: TF relativa, en banda no puede irse de +-40 dB.
    band = (freq > 100) & (freq < 20000)
    check("mag acotada en banda", bool(np.all(np.abs(mag[band]) < 40.0)),
          f"[{mag[band].min():.1f}, {mag[band].max():.1f}] dB")
    # 4. Fase en grados, wrapped.
    check("fase wrapped en +-180", bool(np.all(np.abs(phase_deg) <= 180.001)),
          f"[{phase_deg.min():.0f}, {phase_deg.max():.0f}] deg")
    # 5. Coherencia fisica.
    check("coherencia en [0,1]", bool(np.all((coh >= 0) & (coh <= 1))))
    check("coherencia alta en banda", float(np.median(coh[band])) > 0.8,
          f"mediana={np.median(coh[band]):.3f}")

    # 6. Integracion: SourceResponse con anclaje relativo -> |g(f_ref)| = 1.
    resp = SourceResponse.from_frd(freq, mag, np.deg2rad(phase_deg),
                                   anchor="relative", q_base=1.0,
                                   f_ref=1000.0, name=tag)
    g_ref = float(np.interp(1000.0, resp.freq_pts, resp.gain_db))
    check("anclaje relativo |g(1k)|=1", abs(g_ref) < 0.5, f"{g_ref:+.3f} dB")
    fmin, fmax, npts = resp.coverage()
    check("coverage coincide", npts == len(freq) and fmin == freq[0])

# 7. Robustez: archivos invalidos deben dar ValueError legible.
print("\n--- robustez ---")
import tempfile
with tempfile.TemporaryDirectory() as td:
    bad1 = os.path.join(td, "no_es.trf")
    open(bad1, "wb").write(b"NOPE!!!!" + b"\x00" * 100)
    try:
        load_trf(bad1)
        check("magic invalido -> ValueError", False)
    except ValueError:
        check("magic invalido -> ValueError", True)

    bad2 = os.path.join(td, "trunc.trf")
    open(bad2, "wb").write(open(FILES[0], "rb").read()[:5000])
    try:
        load_trf(bad2)
        check("truncado -> ValueError", False)
    except ValueError:
        check("truncado -> ValueError", True)

n_ok = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 52)
print(f"{'TODOS OK' if n_ok == len(results) else 'HAY FALLAS'} "
      f"({n_ok}/{len(results)})")
sys.exit(0 if n_ok == len(results) else 1)
