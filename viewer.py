"""Vista 3D con modos de visualizacion, etiquetas de longitud y area,
ejes con flechas, costillas del arco y picking de paredes.

Etiquetas (toggle "Etiquetas"):
  - Longitud de arista: fondo blanco, texto negro. Solo en paredes visibles.
  - Area de pared: fondo celeste pastel, texto negro. Solo en paredes visibles.
  Las etiquetas desaparecen en las paredes que dan la espalda a la camara.

Modos de vista (combo):
  aristas / externa / contorno
"""

import os
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

from math import radians, sin, cos, degrees, asin, atan2
import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtCore import Qt, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QFont, QPen, QVector4D, QMatrix4x4
from PyQt5.QtWidgets import QFrame, QLabel, QHBoxLayout


# ---------------------------------------------------------------------------
# Widget overlay del indicador de ejes (esquina inferior derecha)
# ---------------------------------------------------------------------------
class _ClickableAxisLabel(QLabel):
    """QLabel que emite una senal al hacer click izquierdo."""
    clicked = pyqtSignal(str)

    def __init__(self, axis: str, parent=None):
        super().__init__(axis.upper(), parent)
        self._axis = axis.lower()
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._axis)
            ev.accept()
        else:
            super().mousePressEvent(ev)


class AxisIndicator(QFrame):
    """Overlay flotante con tres cuadrados X / Y / Z.

    Click izquierdo sobre un cuadrado: fija ese eje (toggle).
    Cuando un eje esta fijo, su cuadrado se ilumina con un color
    distinto y la senal `axisClicked` se emite con su letra.
    """

    axisClicked = pyqtSignal(str)   # 'x' / 'y' / 'z'

    _COL_BG          = "#262633"
    _COL_BOX         = "#3a3a4d"
    _COL_BOX_ACTIVE  = {"x": "#e84545", "y": "#3a86ff", "z": "#5cc46c"}
    _COL_TEXT        = "#cdd6f4"
    _COL_TEXT_ACTIVE = "#ffffff"
    _BOX_PX          = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {self._COL_BG}; border-radius: 5px; }}"
        )
        self.setFixedHeight(self._BOX_PX + 12)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        self._labels: dict = {}
        for axis in ("x", "y", "z"):
            lab = _ClickableAxisLabel(axis)
            lab.setFixedSize(self._BOX_PX, self._BOX_PX)
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(self._style_inactive())
            lab.setToolTip(
                f"Eje {axis.upper()}.\n"
                "Click izquierdo aqui para fijar (toggle).\n"
                f"Tambien: Ctrl+Shift+Alt+{axis.upper()}.\n"
                "Con un eje fijo, rueda del mouse presionada rota el "
                "recinto solo alrededor de ese eje."
            )
            lab.clicked.connect(self.axisClicked.emit)
            layout.addWidget(lab)
            self._labels[axis] = lab
        self.setFixedWidth(3 * (self._BOX_PX + 5) + 7)
        self._active: str | None = None

    def _style_inactive(self):
        return (f"QLabel {{ background: {self._COL_BOX}; "
                f"color: {self._COL_TEXT}; font-weight: 700; "
                "border-radius: 3px; font-family: monospace; }}")

    def _style_active(self, axis: str):
        bg = self._COL_BOX_ACTIVE.get(axis, self._COL_BOX)
        return (f"QLabel {{ background: {bg}; "
                f"color: {self._COL_TEXT_ACTIVE}; font-weight: 700; "
                "border-radius: 3px; font-family: monospace; }}")

    def set_active(self, axis: str | None):
        """axis: 'x' | 'y' | 'z' | None."""
        axis = axis.lower() if isinstance(axis, str) else None
        self._active = axis
        for k, lab in self._labels.items():
            lab.setStyleSheet(self._style_active(k) if k == axis
                              else self._style_inactive())

AXIS_X = (0.94, 0.27, 0.27, 1.0)
AXIS_Y = (0.23, 0.51, 0.96, 1.0)
AXIS_Z = (0.13, 0.77, 0.37, 1.0)
EDGE_COLOR = (0.96, 0.74, 0.95, 1.0)


class IsoViewer(gl.GLViewWidget):
    # Senales de acustica
    sourceAddRequested    = pyqtSignal(float, float, float)      # (x,y,z) nuevo
    sourceEditRequested   = pyqtSignal(int)                      # idx fuente
    sourceMoveRequested   = pyqtSignal(int, float, float, float) # idx,x,y,z
    receiverMoveRequested = pyqtSignal(float, float, float)      # x,y,z
    # Orientacion del bafle por gesto directo (Alt+Ctrl): delta en grados.
    sourceRotateRequested = pyqtSignal(int, float)   # idx, d_azimut (Alt+Ctrl+Left drag)
    sourceTiltRequested   = pyqtSignal(int, float)   # idx, d_pitch  (Alt+Ctrl+rueda)
    # Plano de corte interactivo
    slicePlaneHovered     = pyqtSignal(int, float)  # axis, offset (mientras mueve)
    slicePlaneConfirmed   = pyqtSignal(int, float)  # axis, offset (al hacer click)

    wallDragStarted = pyqtSignal(int)
    wallDragMoved = pyqtSignal(float)
    wallDragEnded = pyqtSignal()

    # Sensibilidad de los gestos de orientacion del bafle (ajustables).
    BAFFLE_ROTATE_DEG_PER_PX = 0.6    # azimut por px horizontal (Alt+Ctrl+Left)
    BAFFLE_TILT_DEG_PER_PX   = 0.5    # pitch por px vertical (Shift+Alt+Ctrl+Left)

    def __init__(self):
        super().__init__()
        self.setBackgroundColor(QColor("#11111b"))
        self.opts["fov"] = 4.0
        self._iso_distance = 350.0
        self.reset_camera()

        # Grilla del piso. Antes era 40x40 m con paso 1 m; quedaba muy chica
        # para auditorios grandes (un CAD de 50 m x 30 m se salia del area
        # visible). Ahora la base es 200x200 m con paso 2 m, y se puede
        # auto-ajustar al recinto via `fit_grid_to_aabb`.
        self._grid = gl.GLGridItem()
        self._grid.setSize(x=200, y=200, z=0)
        self._grid.setSpacing(x=2, y=2, z=0)
        self._grid.setColor((137, 180, 250, 70))
        self.addItem(self._grid)

        self._add_axes(length=4.0, arrow=0.45)

        # Resaltado de un grupo de caras (hover en la tabla de materiales)
        self._highlight_item = None
        # Overlay de parches de absorcion sub-cara (v8): quads pintados sobre las caras.
        self._patch_item = None
        # Resaltado de UN parche (hover en la lista de Materiales), estilo highlight.
        self._patch_highlight_item = None

        # Puntos de escucha adicionales (v2.16: lista de mics para Comparar)
        self._listen_pts_items = []

        # Posiciones de fuentes/receptor (para doble-click y arrastre)
        self._source_positions = []   # lista de (x,y,z)
        self._receiver_position = None
        self._dragging_source_idx = -1   # >=0 fuente, -2 receptor, -1 ninguno
        self._drag_source_z = 0.0
        # Modo de arrastre Shift+drag:
        #   "xy" -> default Shift+drag, mueve en el plano horizontal z=cte.
        #   "z"  -> Ctrl+Shift+drag, mueve solo en z (xy fijos en la posicion
        #           original de la fuente/receptor).
        self._drag_mode = "xy"
        self._drag_anchor_x = 0.0
        self._drag_anchor_y = 0.0
        # Orientacion de bafle por gesto sostenido (Alt+Ctrl+Left): indice de
        # fuente (o -1). Un solo gesto: horizontal=azimut, vertical=pitch.
        self._orient_source_idx = -1

        # Plano de corte interactivo
        self._slice_placement = False
        self._slice_axis      = 2
        self._slice_aabb_min  = np.zeros(3)
        self._slice_aabb_max  = np.ones(3)
        self._slice_preview   = None   # SlicePlanePreview (creado al activar)

        self.mesh_item = None
        self.edge_item = None
        self._arch_rib_items = []
        self._vertices = None
        self._triangles = None
        self._edges = None
        self._n_walls = None
        self._view_mode = "aristas"
        self.show_labels = False
        self._label_font = QFont("Segoe UI", 8)
        self._label_font.setBold(True)

        # --- Rotacion con eje fijo (Ctrl+Shift+Alt+X/Y/Z o click en el overlay) ---
        self._locked_axis: str | None = None  # None | "x" | "y" | "z"
        # Overlay flotante en la esquina inferior derecha
        self.axis_indicator = AxisIndicator(self)
        # Click en un cuadrado equivale al atajo Ctrl+Shift+Alt+<eje>.
        self.axis_indicator.axisClicked.connect(self.set_locked_axis)
        self.axis_indicator.show()
        self.axis_indicator.raise_()
        self._reposition_axis_indicator()

        self._inclining_wall = None
        self._incline_press_y = None
        self.WALL_DRAG_DEG_PER_PX = 0.25

    # ---------- Camara ----------
    def reset_camera(self):
        self.opts["azimuth"] = 45.0
        self.opts["elevation"] = 30.0
        self.opts["distance"] = self._iso_distance
        self.opts["center"] = self._make_center(0, 0, 1.5)
        self.update()

    def fit_grid_to_aabb(self, aabb_min, aabb_max, margin: float = 1.5,
                         min_size: float = 40.0):
        """Ajusta el tamano de la grilla del piso al AABB de la geometria.

        - aabb_min, aabb_max: (3,) extremos del bounding box en metros.
        - margin: factor multiplicativo (1.5 = 50% extra de espacio alrededor).
        - min_size: la grilla nunca queda mas chica que min_size x min_size m.

        El spacing entre lineas se recalcula para que haya ~20 lineas en el
        eje mayor (no muy densas, no muy esparsas). Tambien re-encuadra la
        camara al centroide horizontal del AABB para que la geometria quede
        centrada en pantalla.
        """
        try:
            mn = np.asarray(aabb_min, dtype=float).ravel()
            mx = np.asarray(aabb_max, dtype=float).ravel()
            if mn.size < 3 or mx.size < 3:
                return
            dx = float(mx[0] - mn[0])
            dy = float(mx[1] - mn[1])
            size = max(max(dx, dy) * margin, min_size)
            # Redondear a un multiplo limpio (5 m) para que el grid quede prolijo
            size = float(np.ceil(size / 5.0) * 5.0)
            # Spacing: apuntar a ~20 divisiones en el lado mayor, redondeado a [0.5, 1, 2, 5, 10] m
            target_spacing = size / 20.0
            for s in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0):
                if target_spacing <= s:
                    spacing = s
                    break
            else:
                spacing = 50.0
            self._grid.setSize(x=size, y=size, z=0)
            self._grid.setSpacing(x=spacing, y=spacing, z=0)
            # Re-encuadrar camara al centroide horizontal del AABB
            cx = 0.5 * (mn[0] + mx[0])
            cy = 0.5 * (mn[1] + mx[1])
            cz = 0.5 * (mn[2] + mx[2])
            self.opts["center"] = self._make_center(cx, cy, cz)
            # Ajustar distancia para que el AABB quepa comodo en el viewport
            diag = float(np.linalg.norm(mx - mn))
            # FOV efectivo de pyqtgraph es chico (4 deg), distancia ~ 50 * diag
            # da un encuadre razonable. Limites para no acercarse/alejarse demasiado.
            new_dist = float(np.clip(50.0 * diag, 50.0, 5000.0))
            self.opts["distance"] = new_dist
            self.update()
        except Exception:
            # Si algo sale mal, dejar la grilla como estaba — nunca crashear
            # el viewer por un ajuste estetico.
            pass

    @staticmethod
    def _make_center(x, y, z):
        from pyqtgraph import Vector
        return Vector(float(x), float(y), float(z))

    def _camera_position(self):
        az = radians(float(self.opts["azimuth"]))
        el = radians(float(self.opts["elevation"]))
        d = float(self.opts["distance"])
        c = self.opts["center"]
        return np.array([
            c.x() + d * cos(el) * sin(az),
            c.y() + d * cos(el) * cos(az),
            c.z() + d * sin(el),
        ])

    # ---------- Mouse ----------
    # ---- Fuentes acusticas: posiciones conocidas para picking ----
    # -----------------------------------------------------------------------
    # Plano de corte interactivo
    # -----------------------------------------------------------------------
    def start_slice_placement(self, axis: int,
                               aabb_min, aabb_max):
        """Activa el modo de colocacion interactiva del plano de corte."""
        import acoustic_viewer as av
        self._slice_axis     = int(axis)
        self._slice_aabb_min = np.asarray(aabb_min, dtype=float)
        self._slice_aabb_max = np.asarray(aabb_max, dtype=float)
        self._slice_placement = True
        self.setMouseTracking(True)
        if self._slice_preview is None:
            self._slice_preview = av.SlicePlanePreview(self)

    def stop_slice_placement(self):
        """Desactiva el modo de colocacion del plano."""
        self._slice_placement = False
        self.setMouseTracking(False)
        if self._slice_preview is not None:
            self._slice_preview.clear()
        self.update()

    def _ray_aabb_midpoint(self, px: int, py: int):
        """Devuelve el punto medio del rayo de camara dentro del AABB del recinto.
        Retorna None si el rayo no intersecta el AABB."""
        orig, dirn = self._ray_from_pixel(px, py)
        if orig is None or dirn is None:
            return None
        o, d = np.asarray(orig, dtype=float), np.asarray(dirn, dtype=float)
        mn, mx = self._slice_aabb_min, self._slice_aabb_max
        tmin, tmax = -np.inf, np.inf
        for i in range(3):
            if abs(d[i]) < 1e-9:
                if o[i] < mn[i] or o[i] > mx[i]:
                    return None
            else:
                t1, t2 = (mn[i] - o[i]) / d[i], (mx[i] - o[i]) / d[i]
                if t1 > t2:
                    t1, t2 = t2, t1
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)
        if tmin > tmax:
            return None
        t_mid = (max(tmin, 0.0) + tmax) * 0.5
        return o + t_mid * d

    def _compute_slice_offset(self, px: int, py: int):
        """Offset del plano de corte a partir de la posicion del cursor."""
        pos = self._ray_aabb_midpoint(px, py)
        if pos is None:
            return None
        return float(pos[self._slice_axis])

    def set_source_positions(self, positions):
        """Guarda la lista de posiciones de fuentes para picking en doble-click.
        `positions`: lista de tuplas (x, y, z).
        """
        self._source_positions = list(positions)

    def set_receiver_position(self, pos):
        """Guarda la posicion del receptor para picking en Shift+drag."""
        self._receiver_position = tuple(pos) if pos is not None else None

    def mouseDoubleClickEvent(self, ev):
        """Doble-click izquierdo sobre una esfera de fuente -> editar."""
        if ev.button() != Qt.LeftButton:
            return
        if not self._source_positions:
            return
        for i, pos in enumerate(self._source_positions):
            sp = self._project(pos)
            if sp is None:
                continue
            dx, dy = ev.x() - sp[0], ev.y() - sp[1]
            if dx * dx + dy * dy < 20 ** 2:   # 20 px de radio de clic
                self.sourceEditRequested.emit(i)
                return

    def _pick_horizontal_plane(self, px, py, z: float = 0.0):
        """Raycast contra el plano z=cte. Devuelve (x,y,z) o None."""
        orig, dirn = self._ray_from_pixel(px, py)
        if orig is None or dirn is None:
            return None
        if abs(dirn[2]) < 1e-9:
            return None
        t = (z - orig[2]) / dirn[2]
        if t < 0:
            return None
        return (float(orig[0] + t * dirn[0]),
                float(orig[1] + t * dirn[1]),
                float(z))

    def _pick_vertical_line(self, px, py, x0: float, y0: float):
        """Proyecta el cursor sobre la linea vertical (x=x0, y=y0, z libre).

        Calcula el punto de la linea mas cercano al rayo de camara — esto
        equivale a "donde estaria el cursor si lo desplazaras puramente
        en el eje z mundial". Usado en el modo Ctrl+Shift+drag (solo z).

        Devuelve el z resultante o None si la camara mira casi paralela al
        eje z (en ese caso la altura no se puede inferir de la posicion 2D
        del cursor).

        Derivacion: minimiza |line(t) - ray(s)|^2 donde
            line(t) = (x0, y0, 0) + t * (0, 0, 1)
            ray(s)  = orig + s * dirn
        Setting partial derivadas a cero y despejando t da el z buscado
        (la base de la linea esta en z=0, asi que t == z resultante).
        """
        orig, dirn = self._ray_from_pixel(px, py)
        if orig is None or dirn is None:
            return None
        dz = float(dirn[2])
        denom = 1.0 - dz * dz
        if abs(denom) < 1e-6:
            # Rayo casi paralelo al eje z: la altura no se puede determinar.
            return None
        wx = x0 - float(orig[0])
        wy = y0 - float(orig[1])
        wz = -float(orig[2])
        dot_dw = float(dirn[0]) * wx + float(dirn[1]) * wy + dz * wz
        t = (dz * dot_dw - wz) / denom
        return float(t)

    def _pick_floor_point(self, px, py):
        """Raycast contra el plano z=0 (piso). Devuelve (x,y,0) o None."""
        return self._pick_horizontal_plane(px, py, z=0.0)

    def _pick_source(self, px, py, radius_px: int = 28) -> int:
        """Devuelve el indice de la fuente mas cercana (>=0), -2 para el receptor, -1 si no hay nada."""
        best_d2 = radius_px ** 2
        best_idx = -1
        for i, pos in enumerate(self._source_positions):
            sp = self._project(pos)
            if sp is None:
                continue
            dx, dy = px - sp[0], py - sp[1]
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2, best_idx = d2, i
        # Tambien chequear receptor (indice especial -2)
        if self._receiver_position is not None:
            sp = self._project(self._receiver_position)
            if sp is not None:
                dx, dy = px - sp[0], py - sp[1]
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2, best_idx = d2, -2
        return best_idx

    def mousePressEvent(self, ev):
        self.mousePos = ev.localPos()

        # Garantia de estado limpio: si el mouseReleaseEvent del drag anterior
        # se perdio (foco fuera del widget, ventana minimizada, etc.) el
        # `_dragging_source_idx` quedaria con un indice valido y el siguiente
        # mouseMoveEvent moveria la fuente fantasma. Reseteamos siempre que el
        # press actual no sea el inicio de un nuevo Shift+Left drag (ese branch
        # lo vuelve a setear correctamente abajo).
        mods = ev.modifiers()
        shift = bool(mods & Qt.ShiftModifier)
        ctrl = bool(mods & Qt.ControlModifier)
        alt = bool(mods & Qt.AltModifier)
        left = (ev.button() == Qt.LeftButton)
        # Gestos de orientacion del bafle: Alt+Ctrl+Left = rotar (azimut, horiz.);
        # +Shift = inclinar (pitch, vert.). Mover fuente = Shift+Left SIN Alt.
        is_orient = left and alt and ctrl
        is_shift_left = left and shift and not alt
        if not is_shift_left:
            self._dragging_source_idx = -1
        self._orient_source_idx = -1     # se re-setea abajo si es gesto de orientacion

        # Modo colocacion de plano de corte
        if self._slice_placement:
            if ev.button() == Qt.LeftButton and not (
                    ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
                # Click izquierdo (sin modificadores) → confirmar plano
                offset = self._compute_slice_offset(ev.x(), ev.y())
                self.stop_slice_placement()
                if offset is not None:
                    self.slicePlaneConfirmed.emit(self._slice_axis, offset)
                return
            if ev.button() == Qt.RightButton:
                # Click derecho → cancelar
                self.stop_slice_placement()
                return
            # Cualquier otro boton: dejar que procese normalmente (camara)
            return

        # Shift + Click izquierdo -> iniciar arrastre de fuente o receptor.
        # Si ademas se mantiene Ctrl, el drag es "solo Z" (xy fijo en la
        # posicion original); sin Ctrl, drag en el plano horizontal (default).
        if is_shift_left:
            self._dragging_source_idx = -1   # reset antes de detectar
            idx = self._pick_source(ev.x(), ev.y())
            if idx >= 0:
                self._dragging_source_idx = idx
                x0, y0, z0 = self._source_positions[idx]
            elif idx == -2 and self._receiver_position is not None:
                self._dragging_source_idx = -2
                x0, y0, z0 = self._receiver_position
            else:
                return   # no hubo pick: no arrancamos drag
            self._drag_source_z = float(z0)
            self._drag_anchor_x = float(x0)
            self._drag_anchor_y = float(y0)
            ctrl_held = bool(ev.modifiers() & Qt.ControlModifier)
            self._drag_mode = "z" if ctrl_held else "xy"
            return

        # Alt+Ctrl+Left -> ORIENTAR el bafle bajo el cursor mientras se mantenga
        # el boton: mov. HORIZONTAL = azimut, mov. VERTICAL = inclinacion (pitch).
        # Un solo gesto (sin Shift: Shift+Alt es el cambio-de-idioma de Windows y
        # robaba el foco). Solo orientacion: no cambia posicion ni acustica.
        if is_orient:
            idx = self._pick_source(ev.x(), ev.y())
            self._orient_source_idx = idx if idx >= 0 else -1
            return

        # Ctrl + Click derecho -> colocar fuente acustica a 1 m del piso
        if (ev.button() == Qt.RightButton
                and ev.modifiers() & Qt.ControlModifier):
            floor_pt = self._pick_floor_point(ev.x(), ev.y())
            if floor_pt is not None:
                self.sourceAddRequested.emit(floor_pt[0], floor_pt[1], 1.0)
            return

        if ev.button() == Qt.RightButton:
            wall = self._pick_wall(ev.x(), ev.y())
            if wall is not None:
                self._inclining_wall = wall
                self._incline_press_y = float(ev.localPos().y())
                self.wallDragStarted.emit(wall)

    def mouseMoveEvent(self, ev):
        if not hasattr(self, "mousePos") or self.mousePos is None:
            self.mousePos = ev.localPos()
        lpos = ev.localPos()
        diff = lpos - self.mousePos
        self.mousePos = lpos
        btns = ev.buttons()

        # Preview del plano de corte (hover, sin necesidad de boton)
        if self._slice_placement:
            offset = self._compute_slice_offset(int(lpos.x()), int(lpos.y()))
            if offset is not None and self._slice_preview is not None:
                self._slice_preview.update(
                    self._slice_axis, offset,
                    self._slice_aabb_min, self._slice_aabb_max
                )
                self.slicePlaneHovered.emit(self._slice_axis, offset)
                self.update()
            # Dejar que continue para permitir orbitar con boton central
            if not (btns & Qt.MidButton) and not (btns & Qt.RightButton):
                return

        # Orientacion de bafle (Alt+Ctrl+Left sostenido): horizontal -> azimut,
        # vertical -> pitch (arrastrar arriba = inclinar arriba). Ambos a la vez.
        if self._orient_source_idx >= 0 and (btns & Qt.LeftButton):
            d_az = float(diff.x()) * self.BAFFLE_ROTATE_DEG_PER_PX
            d_pitch = -float(diff.y()) * self.BAFFLE_TILT_DEG_PER_PX
            if d_az != 0.0:
                self.sourceRotateRequested.emit(self._orient_source_idx, d_az)
            if d_pitch != 0.0:
                self.sourceTiltRequested.emit(self._orient_source_idx, d_pitch)
            return

        # Arrastre de fuente o receptor (Shift+LeftButton sostenido).
        if self._dragging_source_idx != -1 and (btns & Qt.LeftButton):
            if self._drag_mode == "z":
                # Solo z: proyectar cursor sobre la linea vertical que pasa
                # por la posicion original (xy fijos).
                new_z = self._pick_vertical_line(
                    int(lpos.x()), int(lpos.y()),
                    self._drag_anchor_x, self._drag_anchor_y,
                )
                if new_z is None:
                    return    # camara mira casi vertical -> sin update
                new_x, new_y = self._drag_anchor_x, self._drag_anchor_y
            else:
                # XY: proyectar cursor sobre el plano horizontal a la altura
                # original (z fijo).
                pt = self._pick_horizontal_plane(
                    int(lpos.x()), int(lpos.y()), self._drag_source_z
                )
                if pt is None:
                    return
                new_x, new_y, new_z = pt[0], pt[1], self._drag_source_z

            if self._dragging_source_idx == -2:
                self.receiverMoveRequested.emit(new_x, new_y, new_z)
            else:
                self.sourceMoveRequested.emit(
                    self._dragging_source_idx, new_x, new_y, new_z
                )
            return

        if self._inclining_wall is not None and (btns & Qt.RightButton):
            dy = float(lpos.y()) - self._incline_press_y
            self.wallDragMoved.emit(-dy * self.WALL_DRAG_DEG_PER_PX)
            return
        if btns & Qt.MidButton:
            if self._locked_axis is not None:
                # Rotacion restringida: gira el recinto alrededor del eje
                # mundial fijado. La componente horizontal del mouse es la
                # que rota; la vertical se ignora para tener un control
                # predecible.
                self._rotate_around_locked_axis(-diff.x() * 0.5)
            elif ev.modifiers() & Qt.ShiftModifier:
                self.orbit(-diff.x(), 0)
            else:
                self.orbit(-diff.x(), diff.y())
        elif btns & Qt.RightButton:
            self.pan(diff.x(), diff.y(), 0, relative="view-upright")

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._orient_source_idx >= 0:
            self._orient_source_idx = -1   # soltar -> detiene el gesto de orientacion
            return
        if ev.button() == Qt.LeftButton and self._dragging_source_idx != -1:
            self._dragging_source_idx = -1
            return
        if ev.button() == Qt.RightButton and self._inclining_wall is not None:
            self._inclining_wall = None
            self._incline_press_y = None
            self.wallDragEnded.emit()

    # ---------- Ejes ----------
    def _add_axes(self, length, arrow):
        for direction, color in (
            (np.array([1.0, 0.0, 0.0]), AXIS_X),
            (np.array([0.0, 1.0, 0.0]), AXIS_Y),
            (np.array([0.0, 0.0, 1.0]), AXIS_Z),
        ):
            tip = direction * length
            self.addItem(gl.GLLinePlotItem(
                pos=np.array([[0, 0, 0], tip]),
                color=color, width=3.5, antialias=True, mode="lines",
            ))
            self.addItem(self._make_cone(tip, direction, arrow, color))

    @staticmethod
    def _make_cone(tip, direction, size, color):
        n = 14
        base = tip - direction * size * 1.7
        if abs(direction[2]) < 0.9:
            u = np.cross(direction, [0.0, 0.0, 1.0])
        else:
            u = np.cross(direction, [1.0, 0.0, 0.0])
        u /= np.linalg.norm(u)
        v = np.cross(direction, u)
        verts = [tip]
        for k in range(n):
            ang = 2 * np.pi * k / n
            verts.append(base + size * 0.45 * (cos(ang) * u + sin(ang) * v))
        verts.append(base)
        verts = np.array(verts, dtype=float)
        tris = []
        for k in range(n):
            nk = (k + 1) % n
            tris.append([0, 1 + k, 1 + nk])
            tris.append([n + 1, 1 + nk, 1 + k])
        return gl.GLMeshItem(
            meshdata=gl.MeshData(vertexes=verts, faces=np.array(tris)),
            smooth=True, color=color, shader="shaded", glOptions="opaque",
        )

    # ---------- Geometria + modos ----------
    def update_geometry(self, vertices, triangles, edges,
                        n_walls=None, arch_ribs=None):
        # El highlight referencia triangulos de la malla VIEJA: apagarlo.
        if self._highlight_item is not None:
            self.removeItem(self._highlight_item)
            self._highlight_item = None
        self._vertices = np.asarray(vertices)
        self._triangles = np.asarray(triangles)
        self._edges = np.asarray(edges)
        self._n_walls = n_walls
        self._refresh_render()
        self._refresh_arch_ribs(arch_ribs or [])
        center = self._vertices.mean(axis=0)
        self.opts["center"] = self._make_center(*center)
        self.update()

    def set_view_mode(self, mode: str):
        if mode not in ("aristas", "externa", "contorno"):
            return
        self._view_mode = mode
        self._refresh_render()

    def set_listen_points(self, positions):
        """Dibuja los puntos de escucha (mics del Comparar) como esferas chicas.
        `positions`: iterable de (x,y,z); vacio/None = quitar.

        Implementado con GLMeshItem (mismo patron que los markers de fuentes/
        receptor, estable). La version scatter (GLScatterPlotItem persistente,
        point sprites) se descarto: sospechosa de stalls del driver GL en
        Windows al redimensionar la ventana."""
        for it in self._listen_pts_items:
            self.removeItem(it)
        self._listen_pts_items = []
        pts = np.atleast_2d(np.asarray(positions if positions is not None
                                       else [], dtype=float))
        if pts.size == 0:
            self.update()
            return
        for p in pts:
            md = gl.MeshData.sphere(rows=8, cols=10, radius=0.07)
            item = gl.GLMeshItem(meshdata=md, smooth=True,
                                 color=(0.58, 0.89, 0.84, 0.95),
                                 shader="shaded", glOptions="opaque")
            item.translate(float(p[0]), float(p[1]), float(p[2]))
            self.addItem(item)
            self._listen_pts_items.append(item)
        self.update()

    def set_highlight_faces(self, tri_indices=None):
        """Resalta un subconjunto de triangulos de la malla actual (hover en
        la fila de una cara en el dialogo de materiales). None/vacio = apagar.

        Los indices refieren a `self._triangles` (la malla renderizada, que es
        la misma que agrupa face_materials via get_surface). Se dibuja en modo
        additive (sin escritura de depth): el grupo 'brilla' incluso si otra
        pared lo tapa desde este angulo de camara — util para ubicarlo sin
        rotar la vista.
        """
        if self._highlight_item is not None:
            self.removeItem(self._highlight_item)
            self._highlight_item = None
        if (tri_indices is None or self._vertices is None
                or self._triangles is None or len(tri_indices) == 0):
            self.update()
            return
        idx = np.asarray(tri_indices, dtype=int)
        idx = idx[(idx >= 0) & (idx < len(self._triangles))]
        if len(idx) == 0:
            self.update()
            return
        self._highlight_item = gl.GLMeshItem(
            meshdata=gl.MeshData(vertexes=self._vertices,
                                 faces=self._triangles[idx]),
            smooth=False, color=(0.98, 0.83, 0.25, 0.40),
            shader=None, glOptions="additive",
        )
        self.addItem(self._highlight_item)
        self.update()

    def set_patches(self, verts=None, faces=None, face_colors=None):
        """Overlay de parches de absorcion: quads pintados sobre las caras.

        `verts` (Nv,3), `faces` (Nf,3) indices a verts, `face_colors` (Nf,4) RGBA
        en [0,1]. None/vacio = quitar.

        Render ADITIVO (mismo criterio que `set_highlight_faces`): no escribe
        profundidad, asi el parche se dibuja SIEMPRE encima de la cara (evita el
        z-fighting de un quad coplanar con una superficie opaca) y 'brilla' aun
        si otra pared lo ocluye desde este angulo — util para ubicarlo. Patron
        GLMeshItem estable (no scatter persistente).
        """
        if self._patch_item is not None:
            self.removeItem(self._patch_item)
            self._patch_item = None
        if verts is None or faces is None or len(faces) == 0:
            self.update()
            return
        md = gl.MeshData(vertexes=np.asarray(verts, dtype=float),
                         faces=np.asarray(faces, dtype=int),
                         faceColors=np.asarray(face_colors, dtype=float))
        self._patch_item = gl.GLMeshItem(
            meshdata=md, smooth=False, shader=None, glOptions="additive")
        self.addItem(self._patch_item)
        self.update()

    def set_highlight_patch(self, verts=None, faces=None):
        """Resalta UN parche (hover en la fila de Materiales) con un glow ambar,
        mismo criterio que `set_highlight_faces`. None/vacio = apagar. Item
        separado del overlay permanente (`set_patches`), no lo pisa."""
        if self._patch_highlight_item is not None:
            self.removeItem(self._patch_highlight_item)
            self._patch_highlight_item = None
        if verts is None or faces is None or len(faces) == 0:
            self.update()
            return
        self._patch_highlight_item = gl.GLMeshItem(
            meshdata=gl.MeshData(vertexes=np.asarray(verts, dtype=float),
                                 faces=np.asarray(faces, dtype=int)),
            smooth=False, color=(0.98, 0.83, 0.25, 0.75),
            shader=None, glOptions="additive")
        self.addItem(self._patch_highlight_item)
        self.update()

    def _refresh_render(self):
        if self.mesh_item is not None:
            self.removeItem(self.mesh_item)
            self.mesh_item = None
        if self.edge_item is not None:
            self.removeItem(self.edge_item)
            self.edge_item = None
        if self._vertices is None:
            return
        v, t, e = self._vertices, self._triangles, self._edges
        if self._view_mode == "aristas":
            self.mesh_item = gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=v, faces=t),
                smooth=True, color=(0.54, 0.72, 0.98, 0.32),
                shader="shaded", glOptions="translucent",
            )
            self.addItem(self.mesh_item)
            self.edge_item = gl.GLLinePlotItem(
                pos=v[e.flatten()].astype(np.float32),
                color=EDGE_COLOR, width=2.2, antialias=True, mode="lines",
            )
            self.addItem(self.edge_item)
        elif self._view_mode == "externa":
            self.mesh_item = gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=v, faces=t),
                smooth=True, color=(0.82, 0.84, 0.88, 1.0),
                shader="shaded", glOptions="opaque",
            )
            self.addItem(self.mesh_item)
        elif self._view_mode == "contorno":
            self.edge_item = gl.GLLinePlotItem(
                pos=v[e.flatten()].astype(np.float32),
                color=EDGE_COLOR, width=2.5, antialias=True, mode="lines",
            )
            self.addItem(self.edge_item)

    def _refresh_arch_ribs(self, arch_ribs):
        for item in self._arch_rib_items:
            self.removeItem(item)
        self._arch_rib_items = []
        for rib in arch_ribs:
            if len(rib) < 2:
                continue
            item = gl.GLLinePlotItem(
                pos=rib.astype(np.float32),
                color=(0.96, 0.74, 0.95, 0.85),
                width=1.8, antialias=True,
            )
            self.addItem(item)
            self._arch_rib_items.append(item)

    # ---------- Raycast + picking ----------
    def _build_view_proj(self):
        c = self.opts["center"]
        d = float(self.opts["distance"])
        az = radians(float(self.opts["azimuth"]))
        el = radians(float(self.opts["elevation"]))
        view = QMatrix4x4()
        view.translate(0.0, 0.0, -d)
        view.rotate(el * 180 / np.pi - 90, 1.0, 0.0, 0.0)
        view.rotate(az * 180 / np.pi + 90, 0.0, 0.0, -1.0)
        view.translate(-c.x(), -c.y(), -c.z())
        w, h = max(self.width(), 1), max(self.height(), 1)
        proj = QMatrix4x4()
        proj.perspective(float(self.opts["fov"]), w / h, d * 0.001, d * 1000.0)
        return view, proj, w, h

    def _ray_from_pixel(self, px, py):
        view, proj, w, h = self._build_view_proj()
        mvp = proj * view
        inv, ok = mvp.inverted()
        if not ok:
            return None, None
        ndc_x = (px / w) * 2.0 - 1.0
        ndc_y = 1.0 - (py / h) * 2.0
        nw = inv.map(QVector4D(ndc_x, ndc_y, -1.0, 1.0))
        fw = inv.map(QVector4D(ndc_x, ndc_y, 1.0, 1.0))
        if nw.w() == 0 or fw.w() == 0:
            return None, None
        n3 = np.array([nw.x()/nw.w(), nw.y()/nw.w(), nw.z()/nw.w()])
        f3 = np.array([fw.x()/fw.w(), fw.y()/fw.w(), fw.z()/fw.w()])
        d = f3 - n3
        ln = np.linalg.norm(d)
        return (n3, d / ln) if ln > 1e-9 else (None, None)

    @staticmethod
    def _ray_tri(orig, dirn, v0, v1, v2):
        e1, e2 = v1 - v0, v2 - v0
        h = np.cross(dirn, e2)
        a = float(np.dot(e1, h))
        if abs(a) < 1e-9:
            return None
        f = 1.0 / a
        s = orig - v0
        u = f * float(np.dot(s, h))
        if u < 0 or u > 1:
            return None
        q = np.cross(s, e1)
        v = f * float(np.dot(dirn, q))
        if v < 0 or u + v > 1:
            return None
        t = f * float(np.dot(e2, q))
        return t if t > 1e-6 else None

    def _pick_wall(self, px, py):
        if self._vertices is None or self._n_walls is None:
            return None
        orig, dirn = self._ray_from_pixel(px, py)
        if orig is None:
            return None
        v = self._vertices.astype(np.float64)
        n = int(self._n_walls)
        best_idx, best_t = None, float("inf")
        for i in range(n):
            j = (i + 1) % n
            v0, v1, v2, v3 = v[i], v[j], v[n + j], v[n + i]
            for tri in ((v0, v1, v2), (v0, v2, v3)):
                t = self._ray_tri(orig, dirn, *tri)
                if t is not None and t < best_t:
                    best_t, best_idx = t, i
        return best_idx

    # ---------- Proyeccion ----------
    def _project(self, point):
        view, proj, w, h = self._build_view_proj()
        mvp = proj * view
        clip = mvp.map(QVector4D(
            float(point[0]), float(point[1]), float(point[2]), 1.0
        ))
        if clip.w() == 0:
            return None
        nx, ny, nz = clip.x()/clip.w(), clip.y()/clip.w(), clip.z()/clip.w()
        if nz < -1.0 or nz > 1.0:
            return None
        return (nx + 1.0) / 2.0 * w, (1.0 - ny) / 2.0 * h

    # ---------- Etiquetas ----------
    def set_show_labels(self, show: bool):
        self.show_labels = bool(show)
        self.update()

    def paintGL(self, *args, **kwargs):
        super().paintGL(*args, **kwargs)
        if self.show_labels and self._vertices is not None and self._edges is not None:
            self._draw_edge_labels()

    @staticmethod
    def _tri_area(a, b, c):
        return float(np.linalg.norm(np.cross(b - a, c - a))) / 2.0

    def _wall_is_front_facing(self, i, v, n, cam):
        j = (i + 1) % n
        v0 = v[i].astype(np.float64)
        v1 = v[j].astype(np.float64)
        dx, dy = v1[0] - v0[0], v1[1] - v0[1]
        normal = np.array([dy, -dx, 0.0])
        nl = np.linalg.norm(normal)
        if nl < 1e-9:
            return True
        normal /= nl
        top_i = v[n + i].astype(np.float64)
        top_j = v[n + j].astype(np.float64)
        wall_center = (v0 + v1 + top_i + top_j) / 4.0
        return float(np.dot(normal, cam - wall_center)) > 0

    def _draw_edge_labels(self):
        v = self._vertices
        n = self._n_walls
        cam = self._camera_position()

        wall_visible = None
        if n is not None and n >= 3:
            wall_visible = [self._wall_is_front_facing(i, v, n, cam)
                            for i in range(n)]

        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setFont(self._label_font)
            fm = painter.fontMetrics()

            # --- Longitud de aristas (fondo blanco) ---
            for k, edge in enumerate(self._edges):
                if wall_visible is not None and n is not None:
                    if k < n:
                        visible = wall_visible[k]
                    elif k < 2 * n:
                        visible = wall_visible[k - n]
                    else:
                        wi = k - 2 * n
                        visible = (wall_visible[wi]
                                   or wall_visible[(wi - 1 + n) % n])
                else:
                    visible = True

                if not visible:
                    continue

                i, j = int(edge[0]), int(edge[1])
                a, b = v[i], v[j]
                length = float(np.linalg.norm(b - a))
                if length < 0.05:
                    continue
                screen = self._project((a + b) / 2.0)
                if screen is None:
                    continue
                self._draw_label(painter, fm, screen,
                                 f"{length:.2f} m",
                                 QColor(255, 255, 255, 235),
                                 QColor("#0f172a"))

            # --- Area de pared (fondo celeste pastel) ---
            if wall_visible is not None and n is not None:
                for i in range(n):
                    if not wall_visible[i]:
                        continue
                    j = (i + 1) % n
                    v0 = v[i].astype(np.float64)
                    v1 = v[j].astype(np.float64)
                    v2 = v[n + j].astype(np.float64)
                    v3 = v[n + i].astype(np.float64)
                    area = (self._tri_area(v0, v1, v2)
                            + self._tri_area(v0, v2, v3))
                    screen = self._project((v0 + v1 + v2 + v3) / 4.0)
                    if screen is None:
                        continue
                    self._draw_label(painter, fm, screen,
                                     f"{area:.2f} m²",
                                     QColor(176, 224, 230, 230),
                                     QColor("#0f172a"))
        finally:
            painter.end()

    @staticmethod
    def _draw_label(painter, fm, screen_pos, text, bg, fg):
        sx, sy = screen_pos
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x, pad_y = 4, 2
        rect = QRectF(sx - tw/2 - pad_x, sy - th/2 - pad_y,
                      tw + 2*pad_x, th + 2*pad_y)
        painter.setBrush(bg)
        painter.setPen(QPen(QColor("#1e293b"), 0.7))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        painter.setPen(QPen(fg))
        painter.drawText(rect, Qt.AlignCenter, text)

    # ---------- Eje fijo: indicador overlay + rotacion restringida ----------
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # Reposicionar el indicador en cada cambio de tamano.
        self._reposition_axis_indicator()

    def _reposition_axis_indicator(self):
        if not hasattr(self, "axis_indicator"):
            return
        w = self.axis_indicator.width()
        h = self.axis_indicator.height()
        # Esquina inferior derecha, con un pequeno margen.
        x = self.width() - w - 10
        y = self.height() - h - 10
        self.axis_indicator.move(max(0, x), max(0, y))
        self.axis_indicator.raise_()

    def set_locked_axis(self, axis):
        """Fija (o libera) la rotacion alrededor de un eje mundial.

        axis: 'x' | 'y' | 'z' | None.
        Pasar None libera el eje.
        Si el eje ya estaba fijo en ese mismo valor, tambien se libera
        (comportamiento toggle).
        """
        new = axis.lower() if isinstance(axis, str) else None
        if new == self._locked_axis:
            new = None
        if new is not None and new not in ("x", "y", "z"):
            return
        self._locked_axis = new
        self.axis_indicator.set_active(new)

    def get_locked_axis(self):
        return self._locked_axis

    def _rotate_around_locked_axis(self, dtheta_deg: float):
        """Rota la camara alrededor del eje mundial fijado por
        `_locked_axis` en `dtheta_deg` grados. El centro de la rotacion es
        `self.opts['center']` (el punto al que mira la camara).
        """
        if self._locked_axis is None or abs(dtheta_deg) < 1e-6:
            return
        axis = self._locked_axis

        # Posicion actual de la camara respecto del centro (vector cam).
        az = radians(float(self.opts["azimuth"]))
        el = radians(float(self.opts["elevation"]))
        d  = float(self.opts["distance"])
        cam_vec = np.array([
            d * cos(el) * sin(az),
            d * cos(el) * cos(az),
            d * sin(el),
        ], dtype=float)

        # Matriz de rotacion alrededor del eje mundial.
        th = radians(dtheta_deg)
        c, s = cos(th), sin(th)
        if axis == "x":
            R = np.array([[1, 0, 0],
                          [0, c, -s],
                          [0, s,  c]], dtype=float)
        elif axis == "y":
            R = np.array([[ c, 0, s],
                          [ 0, 1, 0],
                          [-s, 0, c]], dtype=float)
        else:  # "z"
            R = np.array([[c, -s, 0],
                          [s,  c, 0],
                          [0,  0, 1]], dtype=float)

        # Para que el RECINTO parezca rotar +theta alrededor de `axis`, la
        # camara debe rotar -theta. Equivale a aplicar R^T = R(-theta) a
        # cam_vec, lo que en la convencion de arriba es igual a usar -th.
        # Como ya armamos R con +th, multiplicamos por su transpuesta:
        new_cam = R.T @ cam_vec

        # Reconvertir a (azimuth, elevation, distance).
        new_d = float(np.linalg.norm(new_cam))
        if new_d < 1e-9:
            return
        new_el = degrees(asin(np.clip(new_cam[2] / new_d, -1.0, 1.0)))
        new_az = degrees(atan2(new_cam[0], new_cam[1]))

        self.opts["azimuth"]   = new_az
        self.opts["elevation"] = new_el
        self.opts["distance"]  = new_d
        self.update()
