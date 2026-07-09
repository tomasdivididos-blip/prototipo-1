"""Dialogo para dibujar (o editar) la forma del piso del recinto.

Modos:
  - Abierto (dibujando): click izquierdo agrega punto; click sobre primer punto
    o Enter cierra; click derecho / Esc deshace.
  - Cerrado (editando): click izquierdo SOBRE VERTICE = drag; click izquierdo
    SOBRE ARISTA = insertar nuevo vertice; click derecho = borrar vertice mas
    cercano (si quedan >= 3).

Grilla:
  El combo "Grilla" del dialogo ajusta el espaciado. Al cambiar, los puntos
  existentes se re-snapean a la nueva grilla y el area del canvas se escala.
"""

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QPolygonF
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
)

GRID_STEPS = [0.25, 0.5, 1.0, 2.0, 5.0]
GRID_LABELS = ["0.25 m", "0.5 m", "1 m", "2 m", "5 m"]
DEFAULT_GRID_IDX = 1       # 0.5 m
_MIN_CELLS_HALF = 24       # minimo de semi-celdas visibles (garantiza densidad util)
# Fraccion del extento que queda como margen NEGATIVO (abajo-izquierda). El
# origen (0,0) se corre cerca de la esquina inferior-izquierda para que el
# usuario pueda dibujar en el cuadrante positivo con una esquina en (0,0) (o no).
ORIGIN_MARGIN_FRAC = 0.12


class ShapeCanvas(QWidget):
    """Canvas con grilla. Soporta dibujar (open) y editar (closed)."""

    pointsChanged = pyqtSignal()
    hoverChanged = pyqtSignal(object)
    # Ctrl+Click derecho en el canvas 2D -> colocar fuente en ese punto del piso
    sourceAddedAtFloor = pyqtSignal(float, float)   # (x, y) en metros
    # Click sobre la etiqueta de longitud de una arista -> editar su longitud.
    edgeLengthEditRequested = pyqtSignal(int)        # edge_idx

    PICK_RADIUS_PX = 14
    EDGE_LABEL_RADIUS_PX = 16

    def __init__(self, initial_polygon=None, grid_step=0.5, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 520)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.GRID_STEP = float(grid_step)
        self.MAJOR_EVERY = max(1, round(1.0 / self.GRID_STEP))
        self.WORLD_EXTENT = max(12.0, _MIN_CELLS_HALF * self.GRID_STEP)
        self._recompute_window()

        self.polygon = []
        self.closed = False
        self.hover_pos = None
        self._dragging_idx = None
        self._hover_vertex_idx = None

        if initial_polygon:
            self.polygon = [(float(x), float(y)) for (x, y) in initial_polygon]
            self.closed = len(self.polygon) >= 3

    # ---------- Grid ----------
    def set_grid_step(self, step: float):
        self.GRID_STEP = float(step)
        self.MAJOR_EVERY = max(1, round(1.0 / step))
        self.WORLD_EXTENT = max(12.0, _MIN_CELLS_HALF * step)
        self._recompute_window()
        # Re-snapear puntos existentes a la nueva grilla
        self.polygon = [self._snap(x, y) for (x, y) in self.polygon]
        self.update()
        self.pointsChanged.emit()

    def _recompute_window(self):
        """Ventana visible (en metros) corrida hacia abajo-izquierda: un margen
        negativo chico + el resto positivo, para poder poner una esquina en
        (0,0). El ancho/alto del mundo se mantiene en 2*WORLD_EXTENT."""
        span = 2.0 * self.WORLD_EXTENT
        margin = ORIGIN_MARGIN_FRAC * self.WORLD_EXTENT
        self.x_min = -margin
        self.y_min = -margin
        self.x_max = self.x_min + span
        self.y_max = self.y_min + span

    # ---------- Conversion de coordenadas ----------
    def _drawing_rect(self):
        size = min(self.width(), self.height())
        margin = 18
        rx = (self.width() - size) / 2 + margin
        ry = (self.height() - size) / 2 + margin
        return rx, ry, size - 2 * margin

    def _world_to_screen(self, x, y):
        rx, ry, rs = self._drawing_rect()
        span = self.x_max - self.x_min
        return (rx + (x - self.x_min) / span * rs,
                ry + rs - (y - self.y_min) / span * rs)

    def _screen_to_world(self, sx, sy):
        rx, ry, rs = self._drawing_rect()
        span = self.x_max - self.x_min
        return (self.x_min + (sx - rx) / rs * span,
                self.y_min + (ry + rs - sy) / rs * span)

    def _snap(self, x, y):
        gx = round(x / self.GRID_STEP) * self.GRID_STEP
        gy = round(y / self.GRID_STEP) * self.GRID_STEP
        gx = max(self.x_min, min(self.x_max, gx))
        gy = max(self.y_min, min(self.y_max, gy))
        return (gx + 0.0, gy + 0.0)

    # ---------- Picking ----------
    def _vertex_under(self, sx, sy):
        if not self.polygon:
            return None
        best, best_d2 = None, self.PICK_RADIUS_PX ** 2
        for i, (x, y) in enumerate(self.polygon):
            vx, vy = self._world_to_screen(x, y)
            d2 = (vx - sx) ** 2 + (vy - sy) ** 2
            if d2 <= best_d2:
                best_d2, best = d2, i
        return best

    def _nearest_vertex(self, sx, sy):
        """Vertice mas cercano (sin umbral — para borrar con click derecho)."""
        if not self.polygon:
            return None
        best, best_d2 = 0, float('inf')
        for i, (x, y) in enumerate(self.polygon):
            vx, vy = self._world_to_screen(x, y)
            d2 = (vx - sx) ** 2 + (vy - sy) ** 2
            if d2 < best_d2:
                best_d2, best = d2, i
        return best

    def _find_nearest_edge(self, sx, sy, threshold_px=15):
        """(edge_idx, t) del segmento mas cercano dentro del umbral, o (None, None)."""
        if not self.closed or len(self.polygon) < 2:
            return None, None
        best_idx, best_dist, best_t = None, float(threshold_px), 0.0
        for i in range(len(self.polygon)):
            j = (i + 1) % len(self.polygon)
            ax, ay = self._world_to_screen(*self.polygon[i])
            bx, by = self._world_to_screen(*self.polygon[j])
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 < 1e-9:
                continue
            t = max(0.0, min(1.0, ((sx - ax) * dx + (sy - ay) * dy) / len2))
            cx_, cy_ = ax + t * dx, ay + t * dy
            dist = ((sx - cx_) ** 2 + (sy - cy_) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best_idx, best_t = dist, i, t
        return best_idx, best_t

    # ---------- Aristas: longitud / etiquetas ----------
    def edge_length(self, edge_idx: int) -> float:
        """Longitud (m) de la arista edge_idx (de polygon[i] a polygon[i+1])."""
        n = len(self.polygon)
        if n < 2:
            return 0.0
        i = edge_idx % n
        j = (i + 1) % n
        ax, ay = self.polygon[i]
        bx, by = self.polygon[j]
        return ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5

    def _edge_midpoints_screen(self):
        """[(edge_idx, sx, sy, longitud_m), ...] para dibujar/clickear etiquetas."""
        if not self.closed or len(self.polygon) < 2:
            return []
        out = []
        n = len(self.polygon)
        for i in range(n):
            j = (i + 1) % n
            ax, ay = self.polygon[i]
            bx, by = self.polygon[j]
            L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
            mxs, mys = self._world_to_screen((ax + bx) / 2.0, (ay + by) / 2.0)
            out.append((i, mxs, mys, L))
        return out

    def _edge_label_under(self, sx, sy):
        """edge_idx cuya etiqueta de longitud cae bajo el cursor, o None."""
        r2 = self.EDGE_LABEL_RADIUS_PX ** 2
        for (i, mxs, mys, _L) in self._edge_midpoints_screen():
            if (mxs - sx) ** 2 + (mys - sy) ** 2 <= r2:
                return i
        return None

    def set_edge_length(self, edge_idx: int, new_len: float):
        """Fija la longitud de la arista: el primer vertice queda FIJO y el
        segundo se desliza sobre la misma direccion de la arista. NO se snapea
        a la grilla (el punto es el valor exacto). Clampea al extento del mundo."""
        n = len(self.polygon)
        if n < 2 or new_len <= 0:
            return
        i = edge_idx % n
        j = (i + 1) % n
        ax, ay = self.polygon[i]
        bx, by = self.polygon[j]
        dx, dy = bx - ax, by - ay
        cur = (dx * dx + dy * dy) ** 0.5
        if cur < 1e-9:
            return                       # arista degenerada: sin direccion
        ux, uy = dx / cur, dy / cur
        nx = ax + ux * new_len
        ny = ay + uy * new_len
        nx = max(self.x_min, min(self.x_max, nx))
        ny = max(self.y_min, min(self.y_max, ny))
        self.polygon[j] = (nx + 0.0, ny + 0.0)
        self.update()
        self.pointsChanged.emit()

    # ---------- Acciones ----------
    def clear(self):
        self.polygon = []
        self.closed = False
        self._dragging_idx = None
        self._hover_vertex_idx = None
        self.update()
        self.pointsChanged.emit()

    def undo_point(self):
        if self.closed:
            self.closed = False
        elif self.polygon:
            self.polygon.pop()
        self.update()
        self.pointsChanged.emit()

    def close_polygon(self):
        if len(self.polygon) >= 3 and not self.closed:
            self.closed = True
            self.update()
            self.pointsChanged.emit()

    def is_valid(self) -> bool:
        return self.closed and len(self.polygon) >= 3

    # ---------- Eventos ----------
    def mouseMoveEvent(self, ev):
        wx, wy = self._screen_to_world(ev.x(), ev.y())
        new_hover = self._snap(wx, wy)
        if new_hover != self.hover_pos:
            self.hover_pos = new_hover
            self.hoverChanged.emit(new_hover)

        self._hover_vertex_idx = (
            self._vertex_under(ev.x(), ev.y()) if self.closed else None
        )

        if self._dragging_idx is not None:
            self.polygon[self._dragging_idx] = new_hover
            self.pointsChanged.emit()

        if self.closed:
            if self._dragging_idx is not None:
                self.setCursor(Qt.ClosedHandCursor)
            elif self._hover_vertex_idx is not None:
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.CrossCursor)

        self.update()

    def leaveEvent(self, ev):
        if self.hover_pos is not None:
            self.hover_pos = None
            self.hoverChanged.emit(None)
        self._hover_vertex_idx = None
        self.update()

    def mousePressEvent(self, ev):
        # Ctrl + Click derecho -> colocar fuente acustica a 1 m del piso
        if (ev.button() == Qt.RightButton
                and ev.modifiers() & Qt.ControlModifier):
            wx, wy = self._screen_to_world(ev.x(), ev.y())
            self.sourceAddedAtFloor.emit(float(wx), float(wy))
            return

        if ev.button() == Qt.RightButton:
            if self.closed:
                # Borrar vertice mas cercano (si quedan >= 3)
                if len(self.polygon) > 3:
                    idx = self._nearest_vertex(ev.x(), ev.y())
                    if idx is not None:
                        self.polygon.pop(idx)
                        self._hover_vertex_idx = None
                        self.update()
                        self.pointsChanged.emit()
            else:
                self.undo_point()
            return

        if ev.button() != Qt.LeftButton:
            return

        if self.closed:
            # Click sobre el numero de una arista -> editar su longitud
            # (prioridad sobre insertar-vertice / drag).
            e_lbl = self._edge_label_under(ev.x(), ev.y())
            if e_lbl is not None:
                self.edgeLengthEditRequested.emit(e_lbl)
                return
            idx = self._vertex_under(ev.x(), ev.y())
            if idx is not None:
                # Drag de vertice existente
                self._dragging_idx = idx
                self.setCursor(Qt.ClosedHandCursor)
            else:
                # Insertar nuevo vertice sobre la arista mas cercana
                edge_idx, _ = self._find_nearest_edge(ev.x(), ev.y())
                if edge_idx is not None:
                    wx, wy = self._screen_to_world(ev.x(), ev.y())
                    new_pt = self._snap(wx, wy)
                    self.polygon.insert(edge_idx + 1, new_pt)
                    self.update()
                    self.pointsChanged.emit()
            return

        # Modo dibujo (poligono abierto)
        wx, wy = self._screen_to_world(ev.x(), ev.y())
        snapped = self._snap(wx, wy)
        if len(self.polygon) >= 3 and snapped == self.polygon[0]:
            self.closed = True
            self.update()
            self.pointsChanged.emit()
            return
        if self.polygon and snapped == self.polygon[-1]:
            return
        self.polygon.append(snapped)
        self.update()
        self.pointsChanged.emit()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._dragging_idx is not None:
            self._dragging_idx = None
            self.setCursor(
                Qt.OpenHandCursor if self._hover_vertex_idx is not None
                else Qt.ArrowCursor
            )

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in (Qt.Key_Escape, Qt.Key_Delete, Qt.Key_Backspace):
            self.undo_point()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.close_polygon()
        else:
            super().keyPressEvent(ev)

    # ---------- Pintado ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#fbfbfd"))

        rx, ry, rs = self._drawing_rect()
        p.setPen(QPen(QColor("#e2e8f0"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(rx, ry, rs, rs))

        ox, oy = self._world_to_screen(0, 0)
        p.setPen(QPen(QColor("#dbeafe"), 1))
        p.drawLine(QPointF(rx, oy), QPointF(rx + rs, oy))
        p.drawLine(QPointF(ox, ry), QPointF(ox, ry + rs))

        # Grilla (recorre la ventana visible, que ahora arranca cerca de 0,0)
        step = self.GRID_STEP
        i0, i1 = int(self.x_min / step), int(self.x_max / step)
        j0, j1 = int(self.y_min / step), int(self.y_max / step)
        p.setPen(Qt.NoPen)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                sx, sy = self._world_to_screen(i * step, j * step)
                if i == 0 and j == 0:
                    p.setBrush(QColor("#94a3b8"))
                    p.drawEllipse(QPointF(sx, sy), 3.5, 3.5)
                elif i % self.MAJOR_EVERY == 0 and j % self.MAJOR_EVERY == 0:
                    p.setBrush(QColor("#cbd5e1"))
                    p.drawEllipse(QPointF(sx, sy), 2.0, 2.0)
                else:
                    p.setBrush(QColor("#e2e8f0"))
                    p.drawEllipse(QPointF(sx, sy), 1.0, 1.0)

        if self.polygon:
            screen_pts = [
                QPointF(*self._world_to_screen(x, y)) for (x, y) in self.polygon
            ]

            if self.closed and len(screen_pts) >= 3:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(124, 58, 237, 38))
                p.drawPolygon(QPolygonF(screen_pts))

            edge_pen = QPen(QColor("#7c3aed"), 2.2)
            edge_pen.setCapStyle(Qt.RoundCap)
            edge_pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(edge_pen)
            p.setBrush(Qt.NoBrush)
            for i in range(len(screen_pts) - 1):
                p.drawLine(screen_pts[i], screen_pts[i + 1])
            if self.closed and len(screen_pts) >= 3:
                p.drawLine(screen_pts[-1], screen_pts[0])

            if not self.closed and self.hover_pos is not None:
                hx, hy = self._world_to_screen(*self.hover_pos)
                p.setPen(QPen(QColor("#a78bfa"), 1.5, Qt.DashLine))
                p.drawLine(screen_pts[-1], QPointF(hx, hy))
                if len(self.polygon) >= 3 and self.hover_pos == self.polygon[0]:
                    p.drawLine(QPointF(hx, hy), screen_pts[0])

            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#7c3aed"))
            for i, pt in enumerate(screen_pts):
                p.drawEllipse(pt, 5.5 if i == 0 else 4.0, 5.5 if i == 0 else 4.0)

            if not self.closed and len(screen_pts) >= 3:
                p.setPen(QPen(QColor("#7c3aed"), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(screen_pts[0], 9, 9)

            if self.closed and self._hover_vertex_idx is not None:
                pt = screen_pts[self._hover_vertex_idx]
                p.setPen(QPen(QColor("#7c3aed"), 2.5))
                p.setBrush(QColor(167, 139, 250, 70))
                p.drawEllipse(pt, 11, 11)

            # Etiquetas de longitud por arista (clickeables -> fijar longitud
            # exacta). Solo con el poligono cerrado.
            if self.closed and len(self.polygon) >= 3:
                f = p.font()
                f.setPointSizeF(8.0)
                p.setFont(f)
                fm = p.fontMetrics()
                for (i, mxs, mys, L) in self._edge_midpoints_screen():
                    txt = f"{L:.2f} m"
                    tw = (fm.horizontalAdvance(txt)
                          if hasattr(fm, "horizontalAdvance") else fm.width(txt))
                    th = fm.height()
                    pad = 3
                    chip = QRectF(mxs - tw / 2 - pad, mys - th / 2 - pad,
                                  tw + 2 * pad, th + 2 * pad)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(30, 30, 46, 215))
                    p.drawRoundedRect(chip, 4, 4)
                    p.setPen(QColor("#f9e2af"))
                    p.drawText(chip, Qt.AlignCenter, txt)

        if not self.closed and self.hover_pos is not None:
            hx, hy = self._world_to_screen(*self.hover_pos)
            if len(self.polygon) >= 3 and self.hover_pos == self.polygon[0]:
                p.setPen(QPen(QColor("#15803d"), 2))
                p.setBrush(QColor(34, 197, 94, 80))
                p.drawEllipse(QPointF(hx, hy), 11, 11)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#a78bfa"))
                p.drawEllipse(QPointF(hx, hy), 5, 5)


class ShapeDrawDialog(QDialog):
    def __init__(self, initial_polygon=None, grid_step=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dibujar / editar forma del recinto")
        self.resize(720, 860)
        self.setStyleSheet(_DIALOG_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Forma del recinto")
        title.setObjectName("DialogTitle")
        self.info_label = QLabel("")
        self.info_label.setObjectName("DialogInfo")
        self.info_label.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.info_label)

        # Selector de grilla
        grid_row = QHBoxLayout()
        lbl_grid = QLabel("Grilla:")
        lbl_grid.setFixedWidth(50)
        self.combo_grid = QComboBox()
        self.combo_grid.addItems(GRID_LABELS)
        init_idx = DEFAULT_GRID_IDX
        if grid_step is not None:
            for k, s in enumerate(GRID_STEPS):
                if abs(s - grid_step) < 1e-6:
                    init_idx = k
                    break
        self.combo_grid.setCurrentIndex(init_idx)
        self.combo_grid.wheelEvent = lambda ev: ev.ignore()
        self.combo_grid.setToolTip("Espaciado de la grilla en metros")
        grid_row.addWidget(lbl_grid)
        grid_row.addWidget(self.combo_grid)
        grid_row.addStretch()
        layout.addLayout(grid_row)

        self.canvas = ShapeCanvas(
            initial_polygon=initial_polygon,
            grid_step=GRID_STEPS[init_idx],
        )
        layout.addWidget(self.canvas, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("DialogStatus")
        self.coord_label = QLabel("")
        self.coord_label.setObjectName("DialogCoord")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.coord_label)
        layout.addLayout(status_row)

        # T7: geometria lofteada (perfiles de tope por pared).
        self._wall_profiles = None
        self._lofted_polygon = None

        btns = QHBoxLayout()
        self.btn_clear = QPushButton("Limpiar")
        self.btn_undo = QPushButton("Deshacer")
        self.btn_close = QPushButton("Cerrar poligono")
        self.btn_section = QPushButton("Cortes laterales…")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_apply = QPushButton("Aplicar")
        self.btn_apply.setObjectName("DialogPrimary")
        btns.addWidget(self.btn_clear)
        btns.addWidget(self.btn_undo)
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_section)
        btns.addStretch()
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_apply)
        layout.addLayout(btns)

        self.btn_clear.clicked.connect(self.canvas.clear)
        self.btn_undo.clicked.connect(self.canvas.undo_point)
        self.btn_close.clicked.connect(self.canvas.close_polygon)
        self.btn_section.clicked.connect(self._open_section)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._on_apply)
        self.combo_grid.currentIndexChanged.connect(self._on_grid_changed)

        self.canvas.pointsChanged.connect(self._refresh_status)
        self.canvas.hoverChanged.connect(self._on_hover_changed)
        self.canvas.edgeLengthEditRequested.connect(self._on_edit_edge_length)
        self._refresh_status()

    def _on_grid_changed(self, idx):
        self.canvas.set_grid_step(GRID_STEPS[idx])

    def _on_edit_edge_length(self, edge_idx):
        """Click sobre el numero de una arista: pedir la longitud exacta."""
        from PyQt5.QtWidgets import QInputDialog
        cur = self.canvas.edge_length(edge_idx)
        max_len = 2.0 * self.canvas.WORLD_EXTENT
        val, ok = QInputDialog.getDouble(
            self, "Longitud de arista",
            f"Longitud de la arista (actual {cur:.2f} m).\n"
            "El primer vértice queda fijo; el otro se desliza en la misma "
            "dirección de la arista.",
            cur, 0.1, max_len, 2)
        if ok:
            self.canvas.set_edge_length(edge_idx, float(val))

    def _on_hover_changed(self, pos):
        if pos is None:
            self.coord_label.setText("")
        else:
            hx, hy = pos
            self.coord_label.setText(
                f"x = {hx:+.{self._decimals()}f} m    y = {hy:+.{self._decimals()}f} m"
            )

    def _decimals(self):
        step = GRID_STEPS[self.combo_grid.currentIndex()]
        return 0 if step >= 1.0 else (1 if step >= 0.5 else 2)

    def _refresh_status(self):
        n = len(self.canvas.polygon)
        if self.canvas.closed:
            self.status_label.setText(
                f"{n} puntos · cerrado — EDICION: arrastra, click en arista=insertar, "
                "click der=borrar"
            )
            self.info_label.setText(
                "Arrastra vertices ·  Click sobre una arista = insertar punto  ·  "
                "Click derecho = borrar vertice  ·  "
                "Click en el número de una arista = fijar su longitud exacta"
            )
        else:
            self.status_label.setText(f"{n} puntos · sin cerrar")
            self.info_label.setText(
                "Click izq: agregar punto  ·  Click der / Esc: deshacer  ·  "
                "Click sobre el primer punto o Enter: cerrar"
            )
        self.btn_close.setEnabled(n >= 3 and not self.canvas.closed)
        self.btn_apply.setEnabled(self.canvas.is_valid())
        self.btn_undo.setEnabled(n > 0 or self.canvas.closed)
        self.btn_clear.setEnabled(n > 0)
        self.btn_section.setEnabled(self.canvas.is_valid())
        if self.canvas.is_valid() and self._wall_profiles:
            self.btn_section.setText("Cortes laterales ✓")
        else:
            self.btn_section.setText("Cortes laterales…")

    def _on_apply(self):
        if not self.canvas.is_valid():
            self.canvas.close_polygon()
        if self.canvas.is_valid():
            self.accept()

    def _open_section(self):
        """Lanza el wizard de cortes laterales sobre la planta actual (T7)."""
        if not self.canvas.is_valid():
            return
        from section_dialog import SectionWizard
        wiz = SectionWizard(list(self.canvas.polygon), default_height=3.0,
                            grid=self.get_grid_step(), parent=self)
        if wiz.exec_() == QDialog.Accepted:
            self._lofted_polygon = wiz.get_polygon()
            self._wall_profiles = wiz.get_wall_profiles()
            self._refresh_status()

    def get_polygon(self):
        # Si se definieron cortes, devolver la planta CCW-normalizada del wizard
        # (los perfiles corresponden a ESE orden de aristas).
        if self._lofted_polygon is not None:
            return [list(p) for p in self._lofted_polygon]
        return list(self.canvas.polygon) if self.canvas.is_valid() else None

    def get_wall_profiles(self):
        return self._wall_profiles

    def get_grid_step(self):
        return GRID_STEPS[self.combo_grid.currentIndex()]


_DIALOG_QSS = """
QDialog { background-color: #1e1e2e; }
QLabel { color: #cdd6f4; }
QLabel#DialogTitle { color: #cba6f7; font-size: 14pt; font-weight: 700; }
QLabel#DialogInfo { color: #a6adc8; font-size: 9pt; padding-bottom: 2px; }
QLabel#DialogStatus { color: #94e2d5; font-weight: 600; font-size: 8pt; }
QLabel#DialogCoord { color: #f9e2af; }
QComboBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 4px 8px; font-weight: 600; min-width: 70px;
}
QComboBox:hover { border-color: #89b4fa; color: #f5e0dc; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #313244; color: #cdd6f4;
    selection-background-color: #45475a; border: 1px solid #45475a;
}
QPushButton {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 7px 14px; font-weight: 600;
}
QPushButton:hover { background-color: #45475a; border-color: #89b4fa; color: #f5e0dc; }
QPushButton:disabled { color: #6c7086; background-color: #181825; border-color: #313244; }
QPushButton#DialogPrimary {
    background-color: #89b4fa; color: #1e1e2e; border-color: #cba6f7;
}
QPushButton#DialogPrimary:hover { background-color: #cba6f7; }
QPushButton#DialogPrimary:disabled { background-color: #45475a; color: #6c7086; }
"""
