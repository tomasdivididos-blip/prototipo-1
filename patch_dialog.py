"""patch_dialog.py
================

Editor 2D de parches de absorcion sub-cara (ver `absorption_patch`).

Flujo:
  1. Elegis una cara de la lista (izquierda). Solo se listan caras axis-aligned
     (paredes/piso/techo perpendiculares a un eje), que es el alcance de v1.
  2. En el canvas central (el plano local u-v de esa cara) dibujas el parche.
     Dos modos:
       - "Rectangulo (arrastrar)": manten el boton izquierdo y arrastra.
       - "Poligono (clicks)": click izquierdo por cada vertice; volves a
         clickear cerca del primer punto (o Enter / doble click) para cerrar;
         boton derecho / Esc deshace el ultimo vertice / cancela.
  3. Elegis el material del combo (derecha): se aplica al parche nuevo o al
     seleccionado. Boton derecho sobre un parche (sin dibujar) lo borra.
  4. Rueda del mouse = zoom in/out sobre la grilla, centrado en el cursor.
  5. Los parches NO pueden solaparse: si el candidato pisaria a otro, se dibuja
     en rojo y no se agrega.

El dialogo NO calcula fisica: solo edita geometria+material de los parches.
El panel acustico los mete en `compute_xi_per_mode_with_patches` (A36 fino).
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

import numpy as np

from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygonF
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QDialogButtonBox, QGroupBox, QAbstractItemView,
)

import absorption_patch as ap


GRID_STEPS = [0.1, 0.25, 0.5, 1.0]
GRID_LABELS = ["0.1 m", "0.25 m", "0.5 m", "1 m"]
DEFAULT_GRID_IDX = 1

# Caras cuya normal se aparta menos de ~15 grados de un eje se consideran
# axis-aligned (soportadas en v1).
_AXIS_COS = 0.966


def _is_axis_aligned(normal) -> bool:
    n = np.abs(np.asarray(normal, dtype=float))
    return float(n.max()) >= _AXIS_COS


def _axis_label(axis: int) -> str:
    return {0: "X", 1: "Y", 2: "Z"}[axis]


def _material_color(name: str, alpha: int = 150) -> QColor:
    """Color deterministico por nombre de material (tono estable)."""
    if not name:
        return QColor(150, 150, 150, alpha)
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    hue = h % 360
    return QColor.fromHsv(hue, 150, 230, alpha)


# ---------------------------------------------------------------------------
# Canvas del plano local u-v de una cara
# ---------------------------------------------------------------------------
class PatchCanvas(QWidget):
    """Dibuja el rectangulo de una cara (su bbox local) y los parches encima.

    Modos:
      - 'rect': arrastrar boton izquierdo -> rectangulo.
      - 'poly': click por vertice; cerrar cerca del primer punto / Enter / doble
                click; boton derecho / Esc deshace / cancela.
    Rueda del mouse = zoom centrado en el cursor. Los parches no pueden solaparse.
    """

    rectDrawn = pyqtSignal(float, float, float, float)   # u0, v0, u1, v1
    polyDrawn = pyqtSignal(list)                          # [(u, v), ...]
    selectionChanged = pyqtSignal(int)                   # indice o -1
    deleteRequested = pyqtSignal(int)                    # indice
    rejected = pyqtSignal(str)                            # mensaje de rechazo

    PICK_PX = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 460)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._bbox = (0.0, 1.0, 0.0, 1.0)   # u_min, u_max, v_min, v_max
        self._u_label = "u"
        self._v_label = "v"
        self._grid = GRID_STEPS[DEFAULT_GRID_IDX]
        self._rects: List[dict] = []        # [{uv:[(u,v)...], name}]
        self._sel = -1
        self._mode = "rect"
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        # rect en curso
        self._drag_start: Optional[Tuple[float, float]] = None
        self._drag_cur: Optional[Tuple[float, float]] = None
        # poligono en curso
        self._poly_pts: List[Tuple[float, float]] = []
        self._poly_hover: Optional[Tuple[float, float]] = None
        self._invalid = False               # el candidato solaparia

    # ---- API ----
    def set_face(self, u_min, u_max, v_min, v_max, u_label, v_label):
        self._bbox = (float(u_min), float(u_max), float(v_min), float(v_max))
        self._u_label, self._v_label = u_label, v_label
        self._reset_draw()
        self._zoom = 1.0
        self._pan_x = self._pan_y = 0.0
        self.update()

    def set_rects(self, rects: List[dict], selected: int = -1):
        self._rects = list(rects)
        self._sel = selected
        self.update()

    def set_grid(self, step: float):
        self._grid = float(step)
        self.update()

    def set_mode(self, mode: str):
        self._mode = "poly" if mode == "poly" else "rect"
        self._reset_draw()
        self.update()

    def _reset_draw(self):
        self._drag_start = self._drag_cur = None
        self._poly_pts = []
        self._poly_hover = None
        self._invalid = False

    # ---- Transformacion (anclada al centro, con zoom + pan) ----
    def _xform(self):
        u0, u1, v0, v1 = self._bbox
        du = max(u1 - u0, 1e-6)
        dv = max(v1 - v0, 1e-6)
        margin = 30
        aw = max(self.width() - 2 * margin, 10)
        ah = max(self.height() - 2 * margin, 10)
        scale = min(aw / du, ah / dv) * self._zoom
        cu, cv = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
        cx = self.width() / 2.0 + self._pan_x
        cy = self.height() / 2.0 + self._pan_y
        return scale, cu, cv, cx, cy

    def _w2s(self, u, v):
        s, cu, cv, cx, cy = self._xform()
        return QPointF(cx + (u - cu) * s, cy - (v - cv) * s)

    def _s2w(self, sx, sy):
        s, cu, cv, cx, cy = self._xform()
        return (cu + (sx - cx) / s, cv - (sy - cy) / s)

    def _snap(self, u, v):
        u0, u1, v0, v1 = self._bbox
        g = self._grid
        su = min(max(round(u / g) * g, u0), u1)
        sv = min(max(round(v / g) * g, v0), v1)
        return (su, sv)

    # ---- Picking / solape ----
    def _rect_under(self, sx, sy) -> int:
        u, v = self._s2w(sx, sy)
        ua, va = np.array([u]), np.array([v])
        for i in range(len(self._rects) - 1, -1, -1):
            if ap.points_in_poly(self._rects[i]["uv"], ua, va)[0]:
                return i
        return -1

    def _would_overlap(self, cand_uv) -> bool:
        for r in self._rects:
            if ap.polys_overlap(cand_uv, r["uv"]):
                return True
        return False

    @staticmethod
    def _rect_uv(a, b):
        (u0, v0), (u1, v1) = a, b
        return [(min(u0, u1), min(v0, v1)), (max(u0, u1), min(v0, v1)),
                (max(u0, u1), max(v0, v1)), (min(u0, u1), max(v0, v1))]

    @staticmethod
    def _dedupe(pts):
        out = []
        for p in pts:
            if not out or abs(out[-1][0] - p[0]) > 1e-9 or abs(out[-1][1] - p[1]) > 1e-9:
                out.append(p)
        if (len(out) >= 2 and abs(out[0][0] - out[-1][0]) < 1e-9
                and abs(out[0][1] - out[-1][1]) < 1e-9):
            out.pop()
        return out

    def _recompute_invalid_poly(self):
        pts = list(self._poly_pts)
        if self._poly_hover is not None:
            pts = pts + [self._poly_hover]
        self._invalid = len(pts) >= 3 and self._would_overlap(pts)

    # ---- Mouse ----
    def wheelEvent(self, ev):
        before = self._s2w(ev.x(), ev.y())
        factor = 1.2 ** (ev.angleDelta().y() / 120.0)
        self._zoom = min(max(self._zoom * factor, 0.2), 40.0)
        s, cu, cv, _cx, _cy = self._xform()
        # Ajustar el pan para que el punto del mundo bajo el cursor no se mueva.
        self._pan_x = ev.x() - self.width() / 2.0 - (before[0] - cu) * s
        self._pan_y = ev.y() - self.height() / 2.0 + (before[1] - cv) * s
        self.update()

    def mousePressEvent(self, ev):
        sx, sy = ev.x(), ev.y()
        if ev.button() == Qt.RightButton:
            if self._mode == "poly" and self._poly_pts:
                self._poly_pts.pop()
                self._recompute_invalid_poly()
                self.update()
                return
            i = self._rect_under(sx, sy)
            if i >= 0:
                self.deleteRequested.emit(i)
            return
        if ev.button() != Qt.LeftButton:
            return
        if self._mode == "rect":
            i = self._rect_under(sx, sy)
            if i >= 0:
                self._sel = i
                self.selectionChanged.emit(i)
                self.update()
                return
            u, v = self._s2w(sx, sy)
            self._drag_start = self._snap(u, v)
            self._drag_cur = self._drag_start
            self.update()
        else:  # poly
            if len(self._poly_pts) >= 3:
                p0 = self._w2s(*self._poly_pts[0])
                if (p0.x() - sx) ** 2 + (p0.y() - sy) ** 2 <= self.PICK_PX ** 2:
                    self._commit_poly()
                    return
            u, v = self._s2w(sx, sy)
            self._poly_pts.append(self._snap(u, v))
            self._recompute_invalid_poly()
            self.update()

    def mouseMoveEvent(self, ev):
        if self._mode == "rect" and self._drag_start is not None:
            u, v = self._s2w(ev.x(), ev.y())
            self._drag_cur = self._snap(u, v)
            self._invalid = self._would_overlap(
                self._rect_uv(self._drag_start, self._drag_cur))
            self.update()
        elif self._mode == "poly" and self._poly_pts:
            u, v = self._s2w(ev.x(), ev.y())
            self._poly_hover = self._snap(u, v)
            self._recompute_invalid_poly()
            self.update()

    def mouseReleaseEvent(self, ev):
        if (ev.button() == Qt.LeftButton and self._mode == "rect"
                and self._drag_start is not None):
            u0, v0 = self._drag_start
            u1, v1 = self._drag_cur
            self._drag_start = self._drag_cur = None
            self._invalid = False
            if abs(u1 - u0) > 1e-6 and abs(v1 - v0) > 1e-6:
                cand = self._rect_uv((u0, v0), (u1, v1))
                if self._would_overlap(cand):
                    self.rejected.emit(
                        "El parche se solaparia con otro. No se agrego.")
                else:
                    self.rectDrawn.emit(min(u0, u1), min(v0, v1),
                                        max(u0, u1), max(v0, v1))
            self.update()

    def mouseDoubleClickEvent(self, ev):
        if self._mode == "poly" and len(self._poly_pts) >= 3:
            self._commit_poly()

    def keyPressEvent(self, ev):
        if self._mode == "poly":
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._commit_poly()
                return
            if ev.key() == Qt.Key_Escape:
                self._reset_draw()
                self.update()
                return
        super().keyPressEvent(ev)

    def _commit_poly(self):
        pts = self._dedupe(self._poly_pts)
        self._poly_pts = []
        self._poly_hover = None
        self._invalid = False
        if len(pts) < 3 or ap.poly_area(pts) < 1e-6:
            self.update()
            return
        if self._would_overlap(pts):
            self.rejected.emit(
                "El poligono se solaparia con otro parche. No se agrego.")
            self.update()
            return
        self.polyDrawn.emit([(float(a), float(b)) for (a, b) in pts])
        self.update()

    # ---- Pintado ----
    def paintEvent(self, _ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, True)
        qp.fillRect(self.rect(), QColor(30, 30, 46))

        u0, u1, v0, v1 = self._bbox
        # Grilla
        qp.setPen(QPen(QColor(69, 71, 90), 1))
        g = self._grid
        for u in np.arange(np.ceil(u0 / g) * g, u1 + 1e-9, g):
            qp.drawLine(self._w2s(u, v0), self._w2s(u, v1))
        for v in np.arange(np.ceil(v0 / g) * g, v1 + 1e-9, g):
            qp.drawLine(self._w2s(u0, v), self._w2s(u1, v))

        # Contorno de la cara
        qp.setPen(QPen(QColor(205, 214, 244), 2))
        qp.setBrush(Qt.NoBrush)
        qp.drawPolygon(QPolygonF([self._w2s(u0, v0), self._w2s(u1, v0),
                                  self._w2s(u1, v1), self._w2s(u0, v1)]))

        # Parches existentes
        f = QFont(); f.setPointSize(8); qp.setFont(f)
        for i, r in enumerate(self._rects):
            poly = QPolygonF([self._w2s(u, v) for (u, v) in r["uv"]])
            qp.setBrush(QBrush(_material_color(r.get("name", ""))))
            border = QColor(249, 226, 175) if i == self._sel else QColor(180, 190, 210)
            qp.setPen(QPen(border, 3 if i == self._sel else 1.5))
            qp.drawPolygon(poly)
            cx = sum(p.x() for p in poly) / max(len(poly), 1)
            cy = sum(p.y() for p in poly) / max(len(poly), 1)
            qp.setPen(QPen(QColor(17, 17, 27)))
            qp.drawText(QRectF(cx - 62, cy - 12, 124, 24), Qt.AlignCenter,
                        r.get("name", "") or "(sin material)")

        invalid = QColor(243, 139, 168)
        ok = QColor(148, 226, 213)
        # Rect en curso
        if self._mode == "rect" and self._drag_start is not None and self._drag_cur is not None:
            a = self._w2s(*self._drag_start); b = self._w2s(*self._drag_cur)
            c = invalid if self._invalid else ok
            qp.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), 80)))
            qp.setPen(QPen(c, 1, Qt.DashLine))
            qp.drawRect(QRectF(a, b))
        # Poligono en curso
        if self._mode == "poly" and self._poly_pts:
            c = invalid if self._invalid else ok
            prev = list(self._poly_pts)
            if self._poly_hover is not None:
                prev = prev + [self._poly_hover]
            qp.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), 70)))
            qp.setPen(QPen(c, 2))
            qp.drawPolygon(QPolygonF([self._w2s(u, v) for (u, v) in prev]))
            qp.setBrush(QBrush(QColor(249, 226, 175)))
            qp.setPen(Qt.NoPen)
            for (u, v) in self._poly_pts:
                qp.drawEllipse(self._w2s(u, v), 3, 3)
            s0 = self._w2s(*self._poly_pts[0])
            qp.setPen(QPen(QColor(166, 227, 161), 2)); qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(s0, self.PICK_PX / 2, self.PICK_PX / 2)

        # Ejes
        qp.setPen(QPen(QColor(147, 153, 178)))
        qp.drawText(int(self.width() - 40), int(self.height() - 12),
                    f"{self._u_label} ->")
        qp.drawText(8, 20, f"^ {self._v_label}")


# ---------------------------------------------------------------------------
# Dialogo
# ---------------------------------------------------------------------------
class PatchEditorDialog(QDialog):
    """Editor de parches. Emite `applied` al Apply/OK; deja el resultado en
    `self.result_patches` (lista de AbsorptionPatch de TODAS las caras)."""

    applied = pyqtSignal()
    changed = pyqtSignal(list)   # preview en vivo: lista actual de AbsorptionPatch

    def __init__(self, groups, verts, tris, mat_lib,
                 patches: Optional[List[ap.AbsorptionPatch]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parches de absorcion por cara")
        self.setModal(True)
        self.resize(940, 640)

        self._verts = np.asarray(verts, dtype=float)
        self._tris = np.asarray(tris, dtype=int)
        self._mat_lib = mat_lib
        self._groups = [g for g in groups if _is_axis_aligned(g.normal)]
        self._n_skipped = len(groups) - len(self._groups)
        self._patches: List[ap.AbsorptionPatch] = [
            ap.AbsorptionPatch.from_dict(p.to_dict()) for p in (patches or [])
        ]
        self._cur_group = None
        self._sel_patch = -1

        self._build_ui()
        if self._groups:
            self.face_list.setCurrentRow(0)

    # ---- UI ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        help_lbl = QLabel(
            "Elegi una cara y dibuja un parche. Modo Rectangulo: arrastra con el "
            "boton izquierdo. Modo Poligono: click por vertice, cerra cerca del "
            "primer punto (o Enter / doble click); boton derecho o Esc deshace. "
            "Rueda = zoom. Los parches no pueden solaparse. Alcance v1: caras "
            "perpendiculares a un eje."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        v.addWidget(help_lbl)

        body = QHBoxLayout()
        v.addLayout(body, 1)

        # Izquierda: lista de caras
        left = QVBoxLayout()
        left.addWidget(QLabel("Caras"))
        self.face_list = QListWidget()
        self.face_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for g in self._groups:
            na = int(np.argmax(np.abs(g.normal)))
            self.face_list.addItem(
                QListWidgetItem(f"{g.label}   ({g.area:.1f} m2, perp {_axis_label(na)})"))
        self.face_list.currentRowChanged.connect(self._on_face_changed)
        left.addWidget(self.face_list, 1)
        if self._n_skipped:
            skip = QLabel(f"({self._n_skipped} cara(s) no axis-aligned omitidas en v1)")
            skip.setWordWrap(True)
            skip.setStyleSheet("color: #f9e2af; font-size: 8pt;")
            left.addWidget(skip)
        body.addLayout(left, 0)

        # Centro: canvas
        self.canvas = PatchCanvas()
        self.canvas.rectDrawn.connect(self._on_rect_drawn)
        self.canvas.polyDrawn.connect(self._on_poly_drawn)
        self.canvas.selectionChanged.connect(self._on_canvas_selection)
        self.canvas.deleteRequested.connect(self._on_delete)
        self.canvas.rejected.connect(self._on_rejected)
        body.addWidget(self.canvas, 1)

        # Derecha: modo, material, grilla, lista de parches
        right = QVBoxLayout()

        gb_mode = QGroupBox("Modo de dibujo")
        mo = QVBoxLayout(gb_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Rectangulo (arrastrar)", "Poligono (clicks)"])
        self.combo_mode.currentIndexChanged.connect(
            lambda i: self.canvas.set_mode("poly" if i == 1 else "rect"))
        mo.addWidget(self.combo_mode)
        right.addWidget(gb_mode)

        gb_mat = QGroupBox("Material del parche")
        mv = QVBoxLayout(gb_mat)
        self.combo_mat = QComboBox()
        self.combo_mat.addItems(list(self._mat_lib.names))
        self.combo_mat.currentTextChanged.connect(self._on_material_changed)
        mv.addWidget(self.combo_mat)
        right.addWidget(gb_mat)

        gb_grid = QGroupBox("Grilla")
        gv2 = QVBoxLayout(gb_grid)
        self.combo_grid = QComboBox()
        self.combo_grid.addItems(GRID_LABELS)
        self.combo_grid.setCurrentIndex(DEFAULT_GRID_IDX)
        self.combo_grid.currentIndexChanged.connect(
            lambda i: self.canvas.set_grid(GRID_STEPS[i]))
        gv2.addWidget(self.combo_grid)
        right.addWidget(gb_grid)

        gb_list = QGroupBox("Parches de esta cara")
        lv = QVBoxLayout(gb_list)
        self.patch_list = QListWidget()
        self.patch_list.currentRowChanged.connect(self._on_patchlist_changed)
        lv.addWidget(self.patch_list, 1)
        self.btn_del = QPushButton("Borrar seleccionado")
        self.btn_del.clicked.connect(self._on_delete_selected)
        lv.addWidget(self.btn_del)
        right.addWidget(gb_list, 1)

        self.lbl_info = QLabel("-")
        self.lbl_info.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        self.lbl_info.setWordWrap(True)
        right.addWidget(self.lbl_info)
        body.addLayout(right, 0)

        bb = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        v.addWidget(bb)

    # ---- Helpers ----
    def _face_bbox(self, group):
        idx = np.unique(self._tris[np.asarray(group.face_indices, int)].ravel())
        fv = self._verts[idx]
        na, ua, va = ap.axis_aligned_frame(group.normal)
        return (float(fv[:, ua].min()), float(fv[:, ua].max()),
                float(fv[:, va].min()), float(fv[:, va].max()), ua, va)

    def _cur_patches(self):
        if self._cur_group is None:
            return []
        sig = self._cur_group.signature
        return [(i, p) for i, p in enumerate(self._patches)
                if p.face_signature == sig]

    def _refresh_canvas(self):
        rects = [{"uv": p.polygon_uv(), "name": p.material_name}
                 for (_i, p) in self._cur_patches()]
        sel_local = -1
        for li, (gi, _p) in enumerate(self._cur_patches()):
            if gi == self._sel_patch:
                sel_local = li
        self.canvas.set_rects(rects, sel_local)

    def _refresh_patch_list(self):
        self.patch_list.blockSignals(True)
        self.patch_list.clear()
        cps = self._cur_patches()
        for (_gi, p) in cps:
            shape = "poligono" if p.poly else "rect"
            self.patch_list.addItem(
                f"{p.material_name or '(sin material)'}  -  {p.area:.2f} m2 ({shape})")
        for li, (gi, _p) in enumerate(cps):
            if gi == self._sel_patch:
                self.patch_list.setCurrentRow(li)
        self.patch_list.blockSignals(False)

    def _refresh_info(self, extra: str = ""):
        cps = self._cur_patches()
        area_cur = sum(p.area for (_i, p) in cps)
        base = (f"Parches totales: {len(self._patches)}   ·   en esta cara: "
                f"{len(cps)} ({area_cur:.2f} m2)")
        self.lbl_info.setText(base + (("   ·   " + extra) if extra else ""))

    def _refresh_all(self, extra: str = ""):
        self._refresh_canvas()
        self._refresh_patch_list()
        self._refresh_info(extra)
        self.changed.emit(list(self._patches))    # preview 3D en vivo

    # ---- Slots ----
    def _on_face_changed(self, row):
        if not (0 <= row < len(self._groups)):
            self._cur_group = None
            return
        self._cur_group = self._groups[row]
        self._sel_patch = -1
        u0, u1, v0, v1, ua, va = self._face_bbox(self._cur_group)
        self.canvas.set_face(u0, u1, v0, v1, _axis_label(ua), _axis_label(va))
        self.canvas.set_grid(GRID_STEPS[self.combo_grid.currentIndex()])
        self.canvas.set_mode("poly" if self.combo_mode.currentIndex() == 1 else "rect")
        self._refresh_all()

    def _on_rect_drawn(self, u0, v0, u1, v1):
        if self._cur_group is None:
            return
        p = ap.make_patch(self._cur_group, u0, v0, u1, v1,
                          material_name=self.combo_mat.currentText())
        self._patches.append(p)
        self._sel_patch = len(self._patches) - 1
        self._refresh_all()

    def _on_poly_drawn(self, pts):
        if self._cur_group is None or len(pts) < 3:
            return
        p = ap.make_polygon_patch(self._cur_group, pts,
                                  material_name=self.combo_mat.currentText())
        self._patches.append(p)
        self._sel_patch = len(self._patches) - 1
        self._refresh_all()

    def _on_rejected(self, msg):
        self._refresh_info(msg)

    def _on_canvas_selection(self, local_idx):
        cps = self._cur_patches()
        if 0 <= local_idx < len(cps):
            self._sel_patch = cps[local_idx][0]
            name = self._patches[self._sel_patch].material_name
            i = self.combo_mat.findText(name)
            if i >= 0:
                self.combo_mat.blockSignals(True)
                self.combo_mat.setCurrentIndex(i)
                self.combo_mat.blockSignals(False)
        self._refresh_all()

    def _on_patchlist_changed(self, local_idx):
        cps = self._cur_patches()
        if 0 <= local_idx < len(cps):
            self._sel_patch = cps[local_idx][0]
            self._refresh_canvas()

    def _on_material_changed(self, name):
        if 0 <= self._sel_patch < len(self._patches):
            self._patches[self._sel_patch].material_name = name
            self._refresh_all()

    def _on_delete(self, local_idx):
        cps = self._cur_patches()
        if 0 <= local_idx < len(cps):
            del self._patches[cps[local_idx][0]]
            self._sel_patch = -1
            self._refresh_all()

    def _on_delete_selected(self):
        if 0 <= self._sel_patch < len(self._patches):
            del self._patches[self._sel_patch]
            self._sel_patch = -1
            self._refresh_all()

    # ---- Commit ----
    @property
    def result_patches(self) -> List[ap.AbsorptionPatch]:
        return list(self._patches)

    def _on_apply(self):
        self.applied.emit()

    def _on_accept(self):
        self.applied.emit()
        self.accept()
