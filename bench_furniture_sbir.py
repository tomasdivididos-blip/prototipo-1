"""bench_furniture_sbir.py — canal SBIR del mueble (panel finito, Rindel).

Oraculos del rolloff de tamano finito:
  1. Regresion: Wall.area=None (paredes) reproduce EXACTO el SBIR previo.
  2. k(f) monotono creciente en [0,1], -> 1 arriba de f_g = c*pi*d_eff/area.
  3. Panel finito atenua el realce/notch LF vs plano infinito (difraccion).
  4. Panel mas grande -> menos rolloff (se acerca al infinito).
  5. furniture_walls arma la cara superior con area = huella.

Correr:  python bench_furniture_sbir.py
"""
import numpy as np

import sbir
import furniture as fu
from sources import C0

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


f = np.linspace(20.0, 500.0, 2000)
Q = np.ones((len(f), 1), dtype=complex)
# Geometria desktop: fuente ~35 cm SOBRE un panel horizontal en z=0; oyente
# cerca. Reflexion fuerte (boundary lift claro) y f_g dentro de la banda.
x_s = [0.0, 0.0, 0.35]
rx = [0.5, 0.0, 0.40]
x_img = np.array([0.0, 0.0, -0.35])              # imagen en z=0
AREA = 1.2                                        # huella ~ escritorio

def sbir_of(area):
    w = sbir.Wall(point=[0, 0, 0], normal=[0, 0, 1], label="p", R=1.0, area=area)
    return sbir.sbir_response([x_s], Q, [w], rx, f)

r_inf = sbir_of(None)          # plano infinito
r_fin = sbir_of(AREA)          # panel finito
r_big = sbir_of(20.0)          # panel casi infinito

# ---------------------------------------------------------------------------
print("t1: regresion — area=None reproduce el plano infinito exacto")
r_inf0 = sbir.sbir_response(
    [x_s], Q, [sbir.Wall([0, 0, 0], [0, 0, 1], "p", 1.0)], rx, f)
check("area=None == comportamiento previo",
      np.allclose(r_inf.total_sbir_db, r_inf0.total_sbir_db),
      f"max diff {np.max(np.abs(r_inf.total_sbir_db-r_inf0.total_sbir_db)):.2e} dB")

# ---------------------------------------------------------------------------
print("t2: k(f) crece de ~0 a 1 y cruza 1 cerca de f_g")
k = sbir.finite_panel_factor(x_s, x_img, rx, [0, 0, 0], [0, 0, 1], AREA, f, C0)
dirv = np.array(rx) - x_img
t = np.dot(-x_img, [0, 0, 1]) / np.dot(dirv, [0, 0, 1])
refl = x_img + t * dirv
a = np.linalg.norm(refl - x_s); b = np.linalg.norm(refl - np.array(rx))
d_eff = a * b / (a + b); f_g = C0 * np.pi * d_eff / AREA
check("k monotono creciente en [0,1]",
      np.all(np.diff(k) >= -1e-12) and k.min() >= 0 and k.max() <= 1.0 + 1e-9,
      f"k[20Hz]={k[0]:.3f}, k[500Hz]={k[-1]:.3f}")
check("k ~ 1 arriba de f_g, < 1 debajo",
      np.interp(min(f_g*1.3, 490), f, k) > 0.85 and np.interp(f_g*0.4, f, k) < 0.6,
      f"f_g={f_g:.0f}Hz; k(1.3f_g)={np.interp(min(f_g*1.3,490),f,k):.2f}, "
      f"k(0.4f_g)={np.interp(f_g*0.4,f,k):.2f}")

# ---------------------------------------------------------------------------
print("t3: panel finito acerca el SBIR a 0 dB en LF (menos reflexion)")
lo = f <= 80.0
dev_inf = np.mean(np.abs(r_inf.total_sbir_db[lo]))
dev_fin = np.mean(np.abs(r_fin.total_sbir_db[lo]))
check("|SBIR| LF del panel finito < infinito (difraccion atenua)",
      dev_fin < dev_inf - 0.3,
      f"|SBIR|<80Hz: infinito {dev_inf:.2f} dB vs finito {dev_fin:.2f} dB")

# ---------------------------------------------------------------------------
print("t4: panel mas grande -> menos rolloff (tiende al infinito)")
d_small = np.mean(np.abs(r_fin.total_sbir_db[lo] - r_inf.total_sbir_db[lo]))
d_big = np.mean(np.abs(r_big.total_sbir_db[lo] - r_inf.total_sbir_db[lo]))
check("panel grande mas cerca del infinito que el chico", d_big < d_small,
      f"desvio LF: grande {d_big:.2f} dB < chico {d_small:.2f} dB")

# ---------------------------------------------------------------------------
print("t5: furniture_walls arma la cara superior con area = huella")
sofa = fu.Furniture("box", (1.0, 1.0, 0.4), (1.2, 0.8, 0.8), label="sofa")
walls = fu.furniture_walls([sofa], {}, f)
w = walls[0]
top_z = 0.4 + 0.8 / 2.0
check("wall en el tope, normal +z, area=huella",
      abs(w.point[2] - top_z) < 1e-9 and abs(w.normal[2] - 1.0) < 1e-9
      and abs(float(w.area) - 1.2 * 0.8) < 1e-9,
      f"z={w.point[2]:.2f}, area={w.area:.2f} m2 (huella 0.96)")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
