"""
section_dialog.py
=================

Fase C de T7 (geometria lofteada, Modelo 1): wizard para dibujar el CORTE
LATERAL de cada pared sobre una planta ya dibujada.

Flujo (wizard secuencial, como pidio el usuario):
  1) La planta ya viene dada (del ShapeDrawDialog).
  2) Por cada pared, en orden: se dibuja el PERFIL DE TOPE (elevacion) en un
     ProfileCanvas cuya base = el largo de esa pared.
  3) Si la pared OPUESTA ya fue dibujada, aparece "simetrica a la opuesta": al
     marcarla, copia el perfil de la opuesta espejado y bloquea el dibujo.
  4) Las alturas de esquina se arrastran (start fija = esquina previa; end libre;
     la ultima pared cierra contra la esquina 0) -> rim siempre consistente.

Salida: get_polygon() (planta CCW-normalizada) + get_wall_profiles()
(lista de n perfiles [(t, z), ...]) que alimenta geometry.make_lofted_room.

Ejecutable standalone para test visual:  python section_dialog.py
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QPolygonF, QBrush
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QDoubleSpinBox, QComboBox,
)


# ---------------------------------------------------------------------------
# Canvas de elevacion (perfil de tope de UNA pared)
# ---------------------------------------------------------------------------
class ProfileCanvas(QWidget):
    """Dibuja el perfil de tope z(x) de una pared: base x in [0, L], z in [0, ymax].

    Polilinea ABIERTA de (0, z_start) a (L, z_end) con puntos interiores
    editables. Los extremos pueden estar pinneados (altura de esquina fija).
    """

    profileChanged = pyqtSignal()
    # Click sobre la etiqueta de altura de un punto -> editar la altura exacta.
    pointHeightEditRequested = pyqtSignal(int)        # indice del punto
    PICK_PX = 14
    LABEL_DY = 18          # offset vertical (px) de la etiqueta sobre el handle
    LABEL_RADIUS_PX = 13

    def __init__(self, length, ymax=6.0, grid=0.5, z_start=3.0, z_end=3.0,
                 pin_start=True, pin_end=False, init_points=None, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.L = max(1e-6, float(length))
        self.ymax = max(1.0, float(ymax))
        self.grid = float(grid)
        self.pin_start = bool(pin_start)
        self.pin_end = bool(pin_end)
        self.enabled_draw = True
        if init_points:
            self.points = [[float(x), float(z)] for x, z in init_points]
        else:
            self.points = [[0.0, float(z_start)], [self.L, float(z_end)]]
        self._drag = None

    # ----- coordenadas -----
    def _rect(self):
        m = 38
        return m, m, max(1, self.width() - 2 * m), max(1, self.height() - 2 * m)

    def _w2s(self, x, z):
        rx, ry, rw, rh = self._rect()
        return rx + (x / self.L) * rw, ry + rh - (z / self.ymax) * rh

    def _s2w(self, sx, sy):
        rx, ry, rw, rh = self._rect()
        return (sx - rx) / rw * self.L, (ry + rh - sy) / rh * self.ymax

    def _snap(self, x, z):
        x = round(x / self.grid) * self.grid
        z = round(z / self.grid) * self.grid
        return min(self.L, max(0.0, x)), min(self.ymax, max(0.0, z))

    def _pt_under(self, sx, sy):
        best, best_d2 = None, self.PICK_PX ** 2
        for i, (x, z) in enumerate(self.points):
            vx, vy = self._w2s(x, z)
            d2 = (vx - sx) ** 2 + (vy - sy) ** 2
            if d2 <= best_d2:
                best_d2, best = d2, i
        return best

    def _is_pinned(self, i):
        """Un punto fijo de esquina (lo manda el rim) no es editable."""
        last = len(self.points) - 1
        if i == 0:
            return self.pin_start
        if i == last:
            return self.pin_end
        return False

    def _pt_label_under(self, sx, sy):
        """Indice del punto cuya etiqueta de altura cae bajo el cursor, o None."""
        r2 = self.LABEL_RADIUS_PX ** 2
        for i, (x, z) in enumerate(self.points):
            vx, vy = self._w2s(x, z)
            cx, cy = vx, vy - self.LABEL_DY
            if (cx - sx) ** 2 + (cy - sy) ** 2 <= r2:
                return i
        return None

    def set_point_height(self, i, z):
        """Fija la altura (z) exacta de un punto editable. No snapea a grilla.
        Los puntos fijos de esquina no se tocan (los manda el rim)."""
        if not self.enabled_draw or not (0 <= i < len(self.points)):
            return
        if self._is_pinned(i):
            return
        self.points[i][1] = max(0.0, min(self.ymax, float(z)))
        self.update()
        self.profileChanged.emit()

    # ----- API -----
    def set_profile(self, points, enabled=True):
        self.points = [[float(x), float(z)] for x, z in points]
        self.enabled_draw = enabled
        self.update()
        self.profileChanged.emit()

    def get_profile(self):
        """[(t, z), ...] con t = x/L en [0,1], ordenado."""
        pts = sorted(self.points, key=lambda p: p[0])
        return [(p[0] / self.L, p[1]) for p in pts]

    def end_height(self):
        return sorted(self.points, key=lambda p: p[0])[-1][1]

    def reset_flat(self, z_start, z_end):
        self.points = [[0.0, float(z_start)], [self.L, float(z_end)]]
        self.update(); self.profileChanged.emit()

    # ----- eventos -----
    def mousePressEvent(self, ev):
        if not self.enabled_draw:
            return
        sx, sy = ev.x(), ev.y()
        if ev.button() == Qt.RightButton:
            i = self._pt_under(sx, sy)
            if i is not None and 0 < i < len(self.points) - 1:   # solo interiores
                self.points.pop(i)
                self.update(); self.profileChanged.emit()
            return
        if ev.button() != Qt.LeftButton:
            return
        # Click sobre el numero de altura de un punto -> editar la altura exacta
        # (prioridad sobre arrastrar / insertar).
        li = self._pt_label_under(sx, sy)
        if li is not None and not self._is_pinned(li):
            self.pointHeightEditRequested.emit(li)
            return
        i = self._pt_under(sx, sy)
        if i is not None:
            self._drag = i
            return
        # insertar punto interior
        wx, wz = self._snap(*self._s2w(sx, sy))
        if 0.0 < wx < self.L:
            self.points.append([wx, wz])
            self.points.sort(key=lambda p: p[0])
            self.update(); self.profileChanged.emit()

    def mouseMoveEvent(self, ev):
        if self._drag is None or not self.enabled_draw:
            return
        i = self._drag
        wx, wz = self._snap(*self._s2w(ev.x(), ev.y()))
        last = len(self.points) - 1
        if i == 0:                       # extremo inicial: x=0
            if not self.pin_start:
                self.points[0][1] = wz
        elif i == last:                  # extremo final: x=L
            if not self.pin_end:
                self.points[last][1] = wz
        else:                            # interior: x (acotado) + z
            lo = self.points[i - 1][0] + self.grid * 0.5
            hi = self.points[i + 1][0] - self.grid * 0.5
            self.points[i][0] = min(hi, max(lo, wx))
            self.points[i][1] = wz
        self.update(); self.profileChanged.emit()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    # ----- pintado -----
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        rx, ry, rw, rh = self._rect()

        # grilla
        p.setPen(QPen(QColor("#313244"), 1))
        nx = int(self.L / self.grid)
        for k in range(nx + 1):
            x = k * self.grid
            sx, _ = self._w2s(x, 0)
            p.drawLine(int(sx), ry, int(sx), ry + rh)
        nz = int(self.ymax / self.grid)
        for k in range(nz + 1):
            z = k * self.grid
            _, sy = self._w2s(0, z)
            p.drawLine(rx, int(sy), rx + rw, int(sy))

        # piso (z=0) y marco
        p.setPen(QPen(QColor("#6c7086"), 2))
        y0 = self._w2s(0, 0)[1]
        p.drawLine(rx, int(y0), rx + rw, int(y0))

        # relleno de la pared
        pts = sorted(self.points, key=lambda q: q[0])
        poly = QPolygonF()
        poly.append(QPointF(*self._w2s(0, 0)))
        for (x, z) in pts:
            poly.append(QPointF(*self._w2s(x, z)))
        poly.append(QPointF(*self._w2s(self.L, 0)))
        col = QColor("#89b4fa") if self.enabled_draw else QColor("#585b70")
        fill = QColor(col); fill.setAlpha(60)
        p.setBrush(QBrush(fill))
        p.setPen(QPen(col, 2))
        p.drawPolygon(poly)

        # handles
        for i, (x, z) in enumerate(pts):
            vx, vy = self._w2s(x, z)
            pinned = (i == 0 and self.pin_start) or (i == len(pts) - 1 and self.pin_end)
            c = QColor("#f38ba8") if pinned else QColor("#fab387")
            p.setBrush(QBrush(c)); p.setPen(QPen(QColor("#11111b"), 1))
            p.drawEllipse(QPointF(vx, vy), 5, 5)

        # etiquetas de altura por punto (clickeables si el punto es editable)
        lf = p.font(); lf.setPointSizeF(8.0); p.setFont(lf)
        fm = p.fontMetrics()
        for i, (x, z) in enumerate(self.points):
            vx, vy = self._w2s(x, z)
            txt = f"{z:.2f}"
            tw = (fm.horizontalAdvance(txt)
                  if hasattr(fm, "horizontalAdvance") else fm.width(txt))
            th = fm.height(); pad = 3
            cx, cy = vx, vy - self.LABEL_DY
            chip = QRectF(cx - tw / 2 - pad, cy - th / 2 - pad,
                          tw + 2 * pad, th + 2 * pad)
            editable = self.enabled_draw and not self._is_pinned(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(17, 17, 27, 220) if editable else QColor(17, 17, 27, 120))
            p.drawRoundedRect(chip, 4, 4)
            p.setPen(QColor("#f9e2af") if editable else QColor("#6c7086"))
            p.drawText(chip, Qt.AlignCenter, txt)

        # etiquetas
        p.setPen(QPen(QColor("#cdd6f4"), 1))
        p.drawText(rx, ry + rh + 22, f"largo {self.L:.2f} m  (x: 0 .. {self.L:.2f})")
        p.drawText(rx, ry - 14, f"altura z: 0 .. {self.ymax:.1f} m   "
                                f"(rojo = esquina fija, naranja = arrastrable)")
        p.end()


# ---------------------------------------------------------------------------
# Wizard de cortes laterales
# ---------------------------------------------------------------------------
def _ccw(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        s += (x2 - x1) * (y2 + y1)
    return s < 0      # shoelace: <0 => CCW en y-arriba


class SectionWizard(QDialog):
    """Dibuja el perfil de tope de cada pared de `base_polygon`."""

    def __init__(self, base_polygon, default_height=3.0, grid=0.5,
                 wall_profiles=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cortes laterales — perfil de cada pared")
        self.resize(680, 520)

        poly = [(float(x), float(y)) for x, y in base_polygon]
        if not _ccw(poly):
            poly = poly[::-1]
        self.poly = poly
        self.n = len(poly)
        self.grid = float(grid)
        self.H = float(default_height)

        # largos de pared
        self.lengths = []
        for i in range(self.n):
            x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % self.n]
            self.lengths.append(float(np.hypot(x2 - x1, y2 - y1)))
        ymax = max(6.0, 2.0 * self.H)

        # estado: perfiles por pared (en t,z) y altura de esquina arrastrada
        self.profiles = [None] * self.n
        if wall_profiles and len(wall_profiles) == self.n:
            self.profiles = [list(map(tuple, wp)) for wp in wall_profiles]
        self.corner_h = [self.H] * self.n
        self.idx = 0
        self._ymax = ymax

        root = QVBoxLayout(self)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)

        opp_row = QHBoxLayout()
        opp_row.addWidget(QLabel("Relación con la pared opuesta:"))
        self.combo_opp = QComboBox()
        self.combo_opp.addItems(
            ["Libre", "Espejo de la opuesta", "Igual a la opuesta"])
        self.combo_opp.setToolTip(
            "Espejo: copia el perfil de la opuesta reflejado (alineado en el "
            "espacio físico).\nIgual: copia directa, misma forma sin espejar "
            "(reescalada a este largo).")
        self.combo_opp.currentIndexChanged.connect(self._on_opp_changed)
        opp_row.addWidget(self.combo_opp)
        opp_row.addStretch()
        root.addLayout(opp_row)

        self.canvas = ProfileCanvas(self.lengths[0], ymax=ymax, grid=self.grid,
                                    z_start=self.H, z_end=self.H,
                                    pin_start=True, pin_end=False)
        self.canvas.pointHeightEditRequested.connect(self._on_edit_point_height)
        root.addWidget(self.canvas, 1)

        brow = QHBoxLayout()
        self.btn_flat = QPushButton("Plano")
        self.btn_back = QPushButton("◀ Anterior")
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_finish = QPushButton("Finalizar")
        self.btn_finish.setDefault(True)
        self.btn_flat.clicked.connect(self._flat)
        self.btn_back.clicked.connect(self._back)
        self.btn_next.clicked.connect(self._next)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_finish.clicked.connect(self._finish)
        for b in (self.btn_flat, self.btn_back, self.btn_next):
            brow.addWidget(b)
        brow.addStretch()
        brow.addWidget(self.btn_cancel)
        brow.addWidget(self.btn_finish)
        root.addLayout(brow)

        self._load_wall(0)

    def _opposite(self, i):
        """Pared opuesta (solo para n par). None si no aplica o no esta dibujada."""
        if self.n % 2 != 0:
            return None
        opp = (i + self.n // 2) % self.n
        return opp

    def _store_current(self):
        """Guarda el perfil de la pared actual y arrastra la altura de esquina."""
        i = self.idx
        prof = self.canvas.get_profile()
        self.profiles[i] = prof
        # altura de esquina siguiente = z del extremo final (salvo cierre)
        end_z = prof[-1][1]
        nxt = (i + 1) % self.n
        if nxt != 0:
            self.corner_h[nxt] = end_z

    def _load_wall(self, i):
        self.idx = i
        L = self.lengths[i]
        z_start = self.corner_h[i]
        # ultima pared (cierra al 0): end pinneado a corner_h[0]
        is_last = (i == self.n - 1)
        z_end = self.corner_h[0] if is_last else self.corner_h[(i + 1) % self.n]
        pin_end = is_last

        opp = self._opposite(i)
        opp_done = opp is not None and opp < i and self.profiles[opp] is not None
        self.combo_opp.blockSignals(True)
        self.combo_opp.setEnabled(opp_done)
        self.combo_opp.setCurrentIndex(0)
        self.combo_opp.blockSignals(False)

        init = None
        if self.profiles[i] is not None:
            init = [(t * L, z) for t, z in self.profiles[i]]
        self.canvas.L = max(1e-6, L)
        self.canvas.pin_start = True
        self.canvas.pin_end = pin_end
        self.canvas.reset_flat(z_start, z_end) if init is None else \
            self.canvas.set_profile(init, enabled=True)

        sym_txt = (f"  ·  opuesta = pared {opp + 1}" if opp_done else "")
        self.lbl.setText(
            f"<b>Pared {i + 1} de {self.n}</b>  (largo {L:.2f} m){sym_txt}<br>"
            f"Dibujá el perfil de tope. Click izq = agregar punto · arrastrar = mover · "
            f"click der = borrar · click en el número (naranja) = fijar altura exacta. "
            f"Extremo izquierdo (rojo) fijo a la esquina previa."
            + ("  El extremo derecho cierra contra la esquina inicial." if pin_end else "")
        )
        self.btn_back.setEnabled(i > 0)
        self.btn_next.setEnabled(i < self.n - 1)

    def _on_opp_changed(self, idx):
        """Libre (0) / Espejo (1) / Igual (2) respecto de la pared opuesta."""
        opp = self._opposite(self.idx)
        if idx == 0 or opp is None or self.profiles[opp] is None:
            self.canvas.enabled_draw = True
            self.canvas.update()
            return
        L = self.lengths[self.idx]
        if idx == 1:      # espejo en t (1-t): alineado en el espacio fisico
            prof = sorted(((1.0 - t) * L, z) for t, z in self.profiles[opp])
        else:             # igual: copia directa (mismo t), reescalada a este L
            prof = sorted((t * L, z) for t, z in self.profiles[opp])
        self.canvas.set_profile(prof, enabled=False)

    def _on_edit_point_height(self, i):
        """Click sobre el numero de altura de un punto: pedir el valor exacto."""
        from PyQt5.QtWidgets import QInputDialog
        pts = self.canvas.points
        if not (0 <= i < len(pts)):
            return
        cur = pts[i][1]
        val, ok = QInputDialog.getDouble(
            self, "Altura del punto",
            f"Altura (z) de este punto (actual {cur:.2f} m):",
            cur, 0.0, self.canvas.ymax, 2)
        if ok:
            self.canvas.set_point_height(i, float(val))

    def _flat(self):
        i = self.idx
        is_last = (i == self.n - 1)
        z_end = self.corner_h[0] if is_last else self.corner_h[(i + 1) % self.n]
        self.combo_opp.setCurrentIndex(0)
        self.canvas.reset_flat(self.corner_h[i], z_end)

    def _back(self):
        if self.idx > 0:
            self._store_current()
            self._load_wall(self.idx - 1)

    def _next(self):
        if self.idx < self.n - 1:
            self._store_current()
            self._load_wall(self.idx + 1)

    def _finish(self):
        self._store_current()
        # completar perfiles faltantes con plano a la altura de esquina
        for i in range(self.n):
            if self.profiles[i] is None:
                self.profiles[i] = [(0.0, self.corner_h[i]),
                                    (1.0, self.corner_h[(i + 1) % self.n])]
        # validar contra el motor
        try:
            from geometry import make_lofted_room
            make_lofted_room(self.poly, self.get_wall_profiles())
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Cortes inconsistentes",
                f"El perfil no cierra bien:\n{e}\n\nRevisá las alturas de esquina.")
            return
        self.accept()

    # ----- salida -----
    def get_polygon(self):
        return [list(p) for p in self.poly]      # CCW-normalizada

    def get_wall_profiles(self):
        return [[[float(t), float(z)] for t, z in (prof or [])]
                for prof in self.profiles]


# ---------------------------------------------------------------------------
# Standalone para test visual:  python section_dialog.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    rect = [(-2.5, -2.0), (2.5, -2.0), (2.5, 2.0), (-2.5, 2.0)]
    dlg = SectionWizard(rect, default_height=3.0, grid=0.5)
    if dlg.exec_() == QDialog.Accepted:
        print("polygon:", dlg.get_polygon())
        for i, wp in enumerate(dlg.get_wall_profiles()):
            print(f"  pared {i}: {wp}")
    else:
        print("cancelado")
