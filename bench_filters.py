"""bench_filters.py — validación del núcleo de filtros (filters.py).

Chequea propiedades físicas conocidas contra teoría analítica:
  - H=1 exacto sin filtro / fc<=0 / orden<=0.
  - Butterworth: -3 dB en fc; |H(0)|=0 dB; pendiente asintótica ~ -6N dB/oct.
  - Linkwitz-Riley: -6 dB en fc; N par; = Butterworth² en magnitud.
  - Bessel/Cheby/Elíptico: pasa-bajo (atenúa arriba), monotonía de magnitud DC.
  - Chebyshev I: ripple de banda de paso acotado por ripple_db.
  - Pasaaltos: espejo (atenúa abajo, pasa arriba).
"""
import numpy as np
import filters as flt

fails = []
def ck(cond, msg):
    print(("  OK  " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

f = np.array([1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000], dtype=float)

# --- H=1 exacto sin filtro / degenerados ---
ck(np.allclose(flt.filter_transfer(f, "none"), 1.0),
   "ftype=none -> H=1 exacto")
ck(np.allclose(flt.filter_transfer(f, "butterworth", order=0, fc=100), 1.0),
   "orden=0 -> H=1 exacto")
ck(np.allclose(flt.filter_transfer(f, "butterworth", order=4, fc=0), 1.0),
   "fc=0 -> H=1 exacto")

def mdb(**kw):
    return flt.filter_magnitude_db(np.array([kw.pop("f")]), **kw)[0]

# --- Butterworth: -3 dB en fc, 0 dB en DC, roll-off -6N dB/oct ---
fc = 100.0
ck(abs(mdb(f=fc, ftype="butterworth", order=4, fc=fc) - (-3.0103)) < 0.05,
   "Butterworth: -3.01 dB en fc")
ck(abs(mdb(f=1.0, ftype="butterworth", order=4, fc=fc) - 0.0) < 0.02,
   "Butterworth: ~0 dB muy por debajo de fc")
# pendiente entre 4fc y 8fc ~ -6*N dB/oct
N = 4
m1 = mdb(f=4*fc, ftype="butterworth", order=N, fc=fc)
m2 = mdb(f=8*fc, ftype="butterworth", order=N, fc=fc)
ck(abs((m2 - m1) - (-6.0206*N)) < 0.6,
   f"Butterworth N={N}: roll-off {m2-m1:.1f} dB/oct ~ {-6.02*N:.0f}")

# --- Linkwitz-Riley: -6 dB en fc, N par, = Butterworth^2 ---
ck(abs(mdb(f=fc, ftype="linkwitz_riley", order=4, fc=fc) - (-6.0206)) < 0.1,
   "Linkwitz-Riley LR4: -6.02 dB en fc")
h_lr = flt.filter_transfer(f, "linkwitz_riley", order=4, fc=fc)
h_bw = flt.filter_transfer(f, "butterworth", order=2, fc=fc)
ck(np.allclose(h_lr, h_bw * h_bw),
   "LR4 == Butterworth(2)^2 en complejo")
ck(flt.valid_orders("linkwitz_riley") == [2, 4, 8],
   "LR: órdenes válidos pares")

# --- monotonía de pasa-bajo (magnitud no crece con f) para varias familias ---
fg = np.geomspace(1, 5000, 200)
for ft, kw in [("butterworth", {}), ("bessel", {}),
               ("chebyshev2", {"atten_db": 40}), ("elliptic", {"ripple_db": 0.5, "atten_db": 60})]:
    m = flt.filter_magnitude_db(fg, ftype=ft, order=4, fc=100, **kw)
    # el promedio de la banda de rechazo debe estar muy por debajo de la de paso
    passband = m[fg < 30].mean()
    stopband = m[fg > 1000].mean()
    ck(stopband < passband - 20, f"{ft}: rechazo {stopband:.0f} dB << paso {passband:.0f} dB")

# --- Chebyshev I: ripple de banda de paso acotado ---
rip = 1.0
m = flt.filter_magnitude_db(np.geomspace(1, 90, 300), ftype="chebyshev1",
                            order=6, fc=100, ripple_db=rip)
ck(m.max() <= 0.05 and m.min() >= -rip - 0.2,
   f"Chebyshev I: ripple de paso dentro de [-{rip},0] dB (min {m.min():.2f})")

# --- pasaaltos: espejo ---
mlo = mdb(f=10.0, ftype="butterworth", order=4, fc=100, kind="highpass")
mhi = mdb(f=1000.0, ftype="butterworth", order=4, fc=100, kind="highpass")
ck(mlo < -20 and abs(mhi) < 0.5, "Butterworth highpass: atenúa abajo, pasa arriba")

# --- shape ---
ck(flt.filter_transfer(f, "elliptic", order=4, fc=100).shape == f.shape,
   "H tiene la shape del eje")

print("\nRESULTADO:", ("TODO VERDE" if not fails else f"{len(fails)} FAIL"))
import sys
sys.exit(1 if fails else 0)
