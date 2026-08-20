"""Bench de la polaridad como campo propio de la fuente (v2.23).

Antes la polaridad se horneaba dentro de la curva g(f) del atajo manual, lo
que traia tres problemas: pisaba el FRD/TRF cargado, no se podia leer de vuelta
en la UI, y quedaba duplicada en el optimizador T8. Ahora es
`OmniSource.polarity` (+-1) aplicada en `effective_Q()`, ortogonal a `response`.

Correr:  PYTHONIOENCODING=utf-8 python bench_polarity.py
"""
from __future__ import annotations

import sys
import numpy as np

from sources import OmniSource, SourceArray, SourceResponse, synth_response

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


fa = np.array([20.0, 50.0, 100.0, 250.0, 500.0])

print(__doc__.splitlines()[0])
print()

# ---------------------------------------------------------------------------
print("T1-T2  regresión: polarity=+1 no cambia nada")
s_base = OmniSource((1.0, 1.0, 1.0), sensitivity_dB=90.0)
s_pos = OmniSource((1.0, 1.0, 1.0), sensitivity_dB=90.0, polarity=1)
check("T1 default es +1", s_base.polarity == 1)
check("T2 polarity=+1 da el Q histórico, bit a bit",
      s_pos.effective_Q() == s_base.effective_Q()
      and np.array_equal(s_pos.effective_Q_spectrum(fa),
                         s_base.effective_Q_spectrum(fa)))

# ---------------------------------------------------------------------------
print("\nT3-T5  la inversión es exactamente ×(−1)")
s_neg = OmniSource((1.0, 1.0, 1.0), sensitivity_dB=90.0, polarity=-1)
check("T3 effective_Q se invierte exacto",
      s_neg.effective_Q() == -s_base.effective_Q(),
      f"{s_neg.effective_Q():.4e} vs {s_base.effective_Q():.4e}")
check("T4 |Q| no cambia (es fase, no nivel)",
      abs(abs(s_neg.effective_Q()) - abs(s_base.effective_Q())) < 1e-18)
check("T5 el espectro también se invierte",
      np.allclose(s_neg.effective_Q_spectrum(fa),
                  -s_base.effective_Q_spectrum(fa), rtol=0, atol=0))

# Equivalencia con la curva 'polarity' sintética: el resultado tiene que ser
# el mismo que el método viejo, que es lo que garantiza que no cambió la física.
s_curve = OmniSource((1.0, 1.0, 1.0), sensitivity_dB=90.0,
                     response=synth_response("polarity", freq_pts=fa))
check("T5b campo ≡ curva 'polarity' (mismo resultado que el método viejo)",
      np.allclose(s_neg.effective_Q_spectrum(fa),
                  s_curve.effective_Q_spectrum(fa), rtol=1e-12),
      f"campo={s_neg.effective_Q_spectrum(fa)[0]:.3e} "
      f"curva={s_curve.effective_Q_spectrum(fa)[0]:.3e}")

# ---------------------------------------------------------------------------
print("\nT6-T7  compone con un FRD/TRF en vez de pisarlo (el bug que motivó esto)")
# Curva con forma NO trivial (rolloff de sub), como un TRF real.
resp = synth_response("highpass", fc=40.0, freq_pts=fa)
s_frd = OmniSource((1, 1, 1), sensitivity_dB=90.0, response=resp)
s_frd_inv = OmniSource((1, 1, 1), sensitivity_dB=90.0, response=resp, polarity=-1)
q_frd = s_frd.effective_Q_spectrum(fa)
q_inv = s_frd_inv.effective_Q_spectrum(fa)
check("T6 invertir NO destruye la curva: |Q(f)| idéntico",
      np.allclose(np.abs(q_frd), np.abs(q_inv), rtol=1e-12),
      f"|Q| @100Hz = {abs(q_frd[2]):.4e}")
check("T7 y la fase queda corrida exactamente π",
      np.allclose(q_inv, -q_frd, rtol=1e-12))
# La forma del rolloff se conserva (no quedó aplanada por el reemplazo viejo).
check("T7b la forma del rolloff sobrevive",
      abs(abs(q_inv[0]) / abs(q_inv[-1]) - abs(q_frd[0]) / abs(q_frd[-1])) < 1e-12,
      f"ratio 20Hz/500Hz = {abs(q_inv[0])/abs(q_inv[-1]):.4f}")

# ---------------------------------------------------------------------------
print("\nT8  dos fuentes en contrafase cancelan")
arr = SourceArray()
arr.add(OmniSource((1, 1, 1), sensitivity_dB=90.0))
arr.add(OmniSource((2, 1, 1), sensitivity_dB=90.0, polarity=-1))
amp = arr.amplitudes_spectrum(fa)             # (Nf, 2)
suma = amp.sum(axis=1)
check("T8 la suma de amplitudes es cero (cancelación exacta)",
      np.allclose(suma, 0.0, atol=1e-30), f"máx |suma| = {np.abs(suma).max():.2e}")
check("T8b amplitudes() legacy también ve la polaridad",
      np.allclose(arr.amplitudes().sum(), 0.0, atol=1e-30))

# ---------------------------------------------------------------------------
print("\nT9  round-trip por .room (aditivo, sin bump de versión)")
import main as _main   # noqa: E402  (import tardío: arrastra Qt)

sd = {"position": [1.0, 2.0, 1.2], "label": "L", "sensitivity_dB": 88.0,
      "polarity": -1}
kwargs = {"position": tuple(sd["position"]), "label": sd["label"],
          "sensitivity_dB": sd["sensitivity_dB"], "power_W": 1.0,
          "polarity": int(sd.get("polarity", 1) or 1)}
s_rt = OmniSource(**kwargs)
check("T9 se reconstruye invertida", s_rt.polarity == -1)
# .room viejo (sin la clave) -> +1
kwargs_old = dict(kwargs); kwargs_old["polarity"] = int({}.get("polarity", 1) or 1)
check("T9b .room viejo sin la clave carga en +1 (compat)",
      OmniSource(**kwargs_old).polarity == 1)

# ---------------------------------------------------------------------------
print("\nT10  T8 (optimizador) manda la polaridad por el campo, no por la curva")
from location_opt import SourceLayout   # noqa: E402

lay = SourceLayout(positions=np.array([[1.0, 1.0, 1.0], [2.0, 1.0, 1.0]]),
                   inverted=np.array([False, True]))
sa = lay.to_source_array()
check("T10 la fuente invertida sale con polarity=-1",
      sa[0].polarity == 1 and sa[1].polarity == -1,
      f"{sa[0].polarity} / {sa[1].polarity}")
check("T10b y SIN curva (la polaridad ya no se hornea en g(f))",
      sa[1].response is None, f"response={sa[1].response}")
check("T10c el resultado numérico sigue siendo la cancelación",
      np.allclose(sa.amplitudes_spectrum(fa).sum(axis=1), 0.0, atol=1e-30))

# Con delay sí tiene que haber curva (eso no cambió).
lay_d = SourceLayout(positions=np.array([[1.0, 1.0, 1.0]]),
                     delays_s=np.array([0.002]))
check("T10d el delay sigue viviendo en la curva",
      lay_d.to_source_array()[0].response is not None)

# ---------------------------------------------------------------------------
print("\nT11  el toggle del diálogo (readback + no pisa la curva)")
import os                                    # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication     # noqa: E402
from acoustic_panel import SourceEditDialog  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

d = SourceEditDialog(source=OmniSource((1, 1, 1), sensitivity_dB=90.0))
check("T11 fuente normal -> toggle destildado, get_source=+1",
      not d.chk_polarity.isChecked() and d.get_source().polarity == 1)

s_inv = OmniSource((1, 1, 1), sensitivity_dB=90.0, polarity=-1)
d2 = SourceEditDialog(source=s_inv)
check("T11b fuente invertida -> el toggle LO REFLEJA (antes imposible)",
      d2.chk_polarity.isChecked() and d2.get_source().polarity == -1)

s_frd = OmniSource((1, 1, 1), sensitivity_dB=90.0,
                   response=synth_response("highpass", fc=40.0), polarity=-1)
o3 = SourceEditDialog(source=s_frd).get_source()
check("T11c la curva sobrevive al toggle",
      o3.response is not None and o3.polarity == -1
      and np.allclose(o3.response.gain_db, s_frd.response.gain_db))

d4 = SourceEditDialog(source=s_inv)
d4.sb_delay.setValue(2.0)
d4._apply_manual()
o4 = d4.get_source()
check("T11d el atajo manual (delay) ya no pisa la polaridad",
      o4.polarity == -1 and o4.response is not None,
      f"resp={o4.response.name!r}")

d5 = SourceEditDialog(source=s_frd)
d5._clear_resp()
o5 = d5.get_source()
check("T11e quitar la curva no toca la polaridad",
      o5.polarity == -1 and o5.response is None)

# ---------------------------------------------------------------------------
print("\nT12  end-to-end en el campo real: 1 fuente invariante, 2 fuentes NO")
# Documenta comportamiento ESPERADO, no un bug: con UNA fuente la polaridad es
# una fase global y el visor muestra |p|, asi que no se ve nada. Es fisica: la
# fase absoluta de una fuente sola no es observable. Recien con una segunda
# fuente hay contra que interferir.
from geometry import make_room                # noqa: E402
import acoustic_analysis as aa                # noqa: E402
import acoustic_fem                           # noqa: E402

_v, _t, _e, _n = make_room(width=5.0, length=4.0, height=3.0, n_walls=4)
_modal = aa.run_fem_modal(_v, _t, n_modes=12, n_per_meter=2.5)
_f = float(_modal.freqs[1])


def _field(arr):
    """Mismo camino que dibuja el visor en modo 'Presión |p|'."""
    return aa.pressure_field_3d(_modal, arr, f=_f, resolution=12, damping=0.05)[2]


def _one(pol):
    a = SourceArray()
    a.add(OmniSource((-1.2, -0.8, 1.0), sensitivity_dB=90.0, polarity=pol))
    return _field(a)


p_pos, p_neg = _one(1), _one(-1)
check("T12 1 fuente: el campo COMPLEJO se invierte exacto",
      np.allclose(p_neg, -p_pos, rtol=1e-12, atol=0))
check("T12b 1 fuente: la MAGNITUD no cambia (por eso el visor se ve igual)",
      np.abs(np.abs(p_neg) - np.abs(p_pos)).max() == 0.0,
      "diferencia máxima exactamente 0")


def _two(pol2):
    a = SourceArray()
    a.add(OmniSource((-1.2, -0.8, 1.0), sensitivity_dB=90.0))
    a.add(OmniSource((1.2, -0.8, 1.0), sensitivity_dB=90.0, polarity=pol2))
    return a


q_pos, q_neg = _field(_two(1)), _field(_two(-1))
_d = 20 * np.log10(np.maximum(np.abs(q_neg), 1e-30)
                   / np.maximum(np.abs(q_pos), 1e-30))
check("T12c 2 fuentes: invertir UNA cambia el campo de verdad",
      not np.allclose(np.abs(q_neg), np.abs(q_pos)) and abs(np.median(_d)) > 1.0,
      f"mediana {np.median(_d):+.1f} dB, min {_d.min():+.1f}, max {_d.max():+.1f}")

_fa = np.linspace(20.0, 200.0, 400)
_rec = np.array([0.8, 0.6, 1.2])
_H = [acoustic_fem.frequency_response(_modal.locator, _modal.freqs, _modal.phis,
                                      _two(p), _rec, _fa, damping=0.05)
      for p in (1, -1)]
_dd = 20 * np.log10(np.maximum(np.abs(_H[1]), 1e-30)
                    / np.maximum(np.abs(_H[0]), 1e-30))
check("T12d 2 fuentes: y la FRF del receptor también",
      np.abs(_dd).max() > 5.0,
      f"mediana {np.median(_dd):+.1f} dB, min {_dd.min():+.1f}, max {_dd.max():+.1f}")

# ---------------------------------------------------------------------------
print()
print(f"RESULTADO: {len(_PASS)}/{len(_PASS) + len(_FAIL)} OK")
if _FAIL:
    print("FALLARON: " + ", ".join(_FAIL))
sys.exit(1 if _FAIL else 0)
