"""
bench_patch_move_hover.py - batch UI v2.53 (items 4 y 5)
========================================================
Valida headless la logica NUEVA del editor de parches:
  - Item 4: mover un parche CONFINADO a la cara (clamp del delta al bbox) y con
    RECHAZO de solape (excluyendo el propio parche).
  - Item 5: mini-grafico de alpha(f) en hover (HTML con PNG base64).

No prueba el render Qt real (eso es test visual), solo la logica pura.

Correr:  QT_QPA_PLATFORM=offscreen python bench_patch_move_hover.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from patch_dialog import PatchCanvas, _alpha_tip_html

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_app = QApplication.instance() or QApplication([])


def _rect(u0, v0, u1, v1, name="m"):
    return {"uv": [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], "name": name}


# --- Item 4: clamp del delta al bbox de la cara ---
c = PatchCanvas()
c.set_face(0.0, 1.0, 0.0, 1.0, "X", "Z")
p0 = [(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]   # bbox u[0.2,0.4] v[0.2,0.4]
du, dv = c._clamp_delta_to_face(p0, 2.0, -1.0)
check("C1 clamp du a +0.6 (u1-pu1)", abs(du - 0.6) < 1e-9, f"du={du}")
check("C1 clamp dv a -0.2 (v0-pv0)", abs(dv + 0.2) < 1e-9, f"dv={dv}")
du2, dv2 = c._clamp_delta_to_face(p0, 0.1, 0.1)         # dentro: no recorta
check("C1 delta interior no se recorta", abs(du2 - 0.1) < 1e-9 and abs(dv2 - 0.1) < 1e-9)
du3, dv3 = c._clamp_delta_to_face(p0, -5.0, 5.0)        # topes opuestos
check("C1 clamp a -0.2 (u0-pu0) y +0.6 (v1-pv1)",
      abs(du3 + 0.2) < 1e-9 and abs(dv3 - 0.6) < 1e-9, f"({du3},{dv3})")

# --- Item 4: rechazo de solape excluyendo el propio parche ---
c.set_rects([_rect(0.2, 0.2, 0.4, 0.4, "a"), _rect(0.6, 0.6, 0.8, 0.8, "b")])
cand_over_b = [(0.6, 0.6), (0.8, 0.6), (0.8, 0.8), (0.6, 0.8)]   # = huella de b
check("C2 solapa con b mirando todos menos idx0",
      c._would_overlap_excluding(cand_over_b, exclude=0) is True)
check("C2 NO solapa si excluyo idx1 (el propio b)",
      c._would_overlap_excluding(cand_over_b, exclude=1) is False)
cand_free = [(0.45, 0.0), (0.55, 0.0), (0.55, 0.1), (0.45, 0.1)]  # libre
check("C2 candidato libre no solapa (excl. idx0)",
      c._would_overlap_excluding(cand_free, exclude=0) is False)

# --- Item 4: flujo de mover con la maquinaria del canvas ---
# press sobre el parche 0 -> arma el move; simulamos el move seteando el grab y
# recomputando como en mouseMoveEvent, y validamos el commit.
c.set_rects([_rect(0.2, 0.2, 0.4, 0.4, "a"), _rect(0.6, 0.6, 0.8, 0.8, "b")])
c._move_idx = 0
c._move_uv0 = list(c._rects[0]["uv"])
# mover +0.1,+0.1 (libre) -> valido
duv = c._clamp_delta_to_face(c._move_uv0, 0.1, 0.1)
moved = [(u + duv[0], v + duv[1]) for (u, v) in c._move_uv0]
check("C3 move libre no invalida", c._would_overlap_excluding(moved, 0) is False)
# intentar moverlo ENCIMA de b -> invalido (se rechazaria en release)
over = [(u + 0.4, v + 0.4) for (u, v) in c._move_uv0]   # a [0.6,0.8]x[0.6,0.8]
check("C3 move sobre b invalida", c._would_overlap_excluding(over, 0) is True)

# --- Item 5: mini-grafico de alpha(f), MISMA estetica que Materiales ---
_BANDS = {63: 0.15, 125: 0.35, 250: 0.65, 500: 0.85,
          1000: 0.90, 2000: 0.92, 4000: 0.93, 8000: 0.93}


class _FakeMat:
    name = "Lana de vidrio 50 mm"
    def alpha(self, f):
        ks = sorted(_BANDS)
        f = float(min(max(f, ks[0]), ks[-1]))
        import numpy as _np
        return float(_np.interp(_np.log(f), _np.log(ks), [_BANDS[k] for k in ks]))
    def alpha_bands(self):
        return dict(_BANDS)


html = _alpha_tip_html(_FakeMat())
check("H1 tooltip tiene imagen PNG base64 (matplotlib)",
      '<img src="data:image/png;base64,' in html and len(html) > 500, f"len={len(html)}")
check("H1 material None -> vacio", _alpha_tip_html(None) == "")

# La estetica la fija plot_utils.draw_alpha_curve: eje Y 0..1 paso 0.2, X en
# bandas de octava (63..8000). Se valida que dibuje sin error sobre un ax real.
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import plot_utils
_fig = Figure(); _ax = _fig.add_subplot(111)
plot_utils.draw_alpha_curve(_ax, _FakeMat())
yt = [round(float(t), 3) for t in _ax.get_yticks()]
check("H2 eje Y en pasos de 0.2 (0..1)", yt == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], str(yt))
xt = [int(round(float(t))) for t in _ax.get_xticks()]
check("H2 eje X en bandas de octava 63..8000",
      xt == [63, 125, 250, 500, 1000, 2000, 4000, 8000], str(xt))
labels = [t.get_text() for t in _ax.get_xticklabels()]
check("H2 etiquetas X legibles (63.. 8k)", labels[0] == "63" and labels[-1] == "8k",
      str(labels))
check("H2 curva azul #1f6fbf",
      any(ln.get_color() == "#1f6fbf" for ln in _ax.get_lines()))

print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
