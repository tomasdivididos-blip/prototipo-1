"""Panel lateral con sliders y controles."""

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QSlider, QLabel,
    QSpinBox, QPushButton, QScrollArea, QFrame, QInputDialog, QComboBox,
)


class LabeledSlider(QWidget):
    """Slider con titulo + valor en vivo. UX:
    - Doble click sobre el slider -> reset a 0 (o limite cercano si 0 fuera de rango).
    - Doble click sobre el numero -> dialog para tipear el valor exacto.
    - Rueda del mouse: ignorada (asi la rueda scrolea el panel, no el slider).
    """

    valueChanged = pyqtSignal(float)

    def __init__(self, label: str, minimum: float, maximum: float,
                 default: float, decimals: int = 1, suffix: str = ""):
        super().__init__()
        self.label = label
        self.minimum = minimum
        self.maximum = maximum
        self.decimals = decimals
        self.suffix = suffix
        self._scale = 10 ** decimals

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(label)
        self.value_label = QLabel()
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Nota: `font-variant-numeric` no es soportada por Qt5 (genera
        # warnings "Unknown property font-variant-numeric" en consola).
        # La quitamos: el efecto visual (digitos de ancho tabular) es minimo.
        self.value_label.setStyleSheet(
            "color: #f9e2af; font-weight: 600;"
            " padding: 0 2px;"
        )
        self.value_label.setCursor(Qt.IBeamCursor)
        self.value_label.setToolTip("Doble click para tipear un valor")
        # Reasignamos handlers de doble click sin subclasear los widgets internos.
        self.value_label.mouseDoubleClickEvent = self._on_value_double_click
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.value_label)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(int(round(minimum * self._scale)))
        self.slider.setMaximum(int(round(maximum * self._scale)))
        self.slider.setValue(int(round(default * self._scale)))
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, self._scale))
        self.slider.valueChanged.connect(self._on_change)
        self.slider.setToolTip("Doble click para resetear a 0")
        # Anulamos rueda y mapeamos doble click
        self.slider.wheelEvent = lambda ev: ev.ignore()
        self.slider.mouseDoubleClickEvent = self._on_slider_double_click

        layout.addLayout(header)
        layout.addWidget(self.slider)

        self._update_label(default)

    def _on_change(self, raw: int):
        v = raw / self._scale
        self._update_label(v)
        self.valueChanged.emit(v)

    def _update_label(self, v: float):
        if self.decimals == 0:
            self.value_label.setText(f"{int(round(v))}{self.suffix}")
        else:
            self.value_label.setText(f"{v:.{self.decimals}f}{self.suffix}")

    def value(self) -> float:
        return self.slider.value() / self._scale

    def set_value(self, v: float):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v * self._scale)))
        self.slider.blockSignals(False)
        self._update_label(v)

    # ---- UX: doble click ----
    def _on_slider_double_click(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        target = 0.0 if self.minimum <= 0.0 <= self.maximum else float(self.minimum)
        self.set_value(target)
        self.valueChanged.emit(target)

    def _on_value_double_click(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        cur = self.value()
        prompt = (f"{self.label}\n"
                  f"(rango: {self._fmt(self.minimum)} a {self._fmt(self.maximum)}{self.suffix})")
        if self.decimals == 0:
            new_val, ok = QInputDialog.getInt(
                self, "Editar valor", prompt,
                int(round(cur)), int(self.minimum), int(self.maximum), 1,
            )
        else:
            new_val, ok = QInputDialog.getDouble(
                self, "Editar valor", prompt,
                cur, float(self.minimum), float(self.maximum), self.decimals,
            )
        if ok:
            new_val = max(self.minimum, min(self.maximum, float(new_val)))
            self.set_value(new_val)
            self.valueChanged.emit(new_val)

    def _fmt(self, v):
        if self.decimals == 0:
            return f"{int(v)}"
        return f"{v:.{self.decimals}f}"


class ControlPanel(QWidget):
    """Panel: scrollable arriba (sliders + grupos), footer fijo abajo (botones)."""

    parametersChanged = pyqtSignal(dict)
    parametersCommitted = pyqtSignal(dict)
    cameraResetRequested = pyqtSignal()
    drawShapeRequested = pyqtSignal()
    showLabelsToggled = pyqtSignal(bool)
    viewModeChanged = pyqtSignal(str)  # "aristas" | "externa" | "contorno"

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Estado custom polygon
        self._custom_polygon = None

        # Debounce commits (Undo/Redo)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(450)
        self._commit_timer.timeout.connect(self._fire_committed)

        # ---------- Area scrollable ----------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Modelador de Recintos")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Prototipo 1 · vista isometrica en tiempo real")
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Dimensiones
        dims = QGroupBox("Dimensiones")
        dl = QVBoxLayout(dims)
        self.s_width = LabeledSlider("Ancho (X)", 1.0, 20.0, 6.0, 1, " m")
        self.s_length = LabeledSlider("Largo (Y)", 1.0, 20.0, 8.0, 1, " m")
        self.s_height = LabeledSlider("Alto (Z)", 1.0, 10.0, 3.0, 1, " m")
        dl.addWidget(self.s_width)
        dl.addWidget(self.s_length)
        dl.addWidget(self.s_height)
        # Convencion de origen (0,0,0): donde queda el origen respecto del
        # recinto. Aplica a los 3 caminos (parametrico / planta dibujada /
        # CAD importado). "Auto" = comportamiento historico de cada camino.
        orow = QHBoxLayout()
        orow.setContentsMargins(0, 4, 0, 0)
        orow.addWidget(QLabel("Origen (0,0,0)"))
        orow.addStretch()
        self.combo_origin = QComboBox()
        self.combo_origin.addItem("Auto (según diseño)", "auto")
        self.combo_origin.addItem("Centro de planta", "center")
        self.combo_origin.addItem("Esquina inf.-izq.", "corner")
        self.combo_origin.setToolTip(
            "Dónde queda el (0,0,0) del sistema de coordenadas:\n"
            "• Auto: paramétrico centrado, planta dibujada como se dibujó,\n"
            "  CAD centrado (comportamiento histórico).\n"
            "• Centro de planta: el centro del recinto cae en (0,0).\n"
            "• Esquina: el recinto vive en el cuadrante positivo, con la\n"
            "  esquina inferior-izquierda en (0,0).\n"
            "Las fuentes y el receptor se trasladan junto con el recinto."
        )
        self.combo_origin.wheelEvent = lambda ev: ev.ignore()
        orow.addWidget(self.combo_origin)
        dl.addLayout(orow)
        layout.addWidget(dims)

        # Forma (regular)
        self.shape_group = QGroupBox("Forma")
        sl = QVBoxLayout(self.shape_group)
        n_widget = QWidget()
        nh = QHBoxLayout(n_widget)
        nh.setContentsMargins(0, 4, 0, 4)
        self.n_label = QLabel("Cantidad de paredes laterales")
        nh.addWidget(self.n_label)
        nh.addStretch()
        self.spin_n = QSpinBox()
        self.spin_n.setMinimum(3)
        self.spin_n.setMaximum(12)
        self.spin_n.setValue(4)
        self.spin_n.setFixedWidth(80)
        # Tambien ignoramos rueda en spinbox (consistencia)
        self.spin_n.wheelEvent = lambda ev: ev.ignore()
        nh.addWidget(self.spin_n)
        sl.addWidget(n_widget)
        self.s_taper = LabeledSlider("Estrechamiento del techo", -0.6, 0.6, 0.0, 2, "")
        self.s_twist = LabeledSlider("Torsion del techo", -45, 45, 0, 0, "°")
        sl.addWidget(self.s_taper)
        sl.addWidget(self.s_twist)
        layout.addWidget(self.shape_group)

        # Forma personalizada
        custom = QGroupBox("Forma personalizada")
        cl = QVBoxLayout(custom)
        self.custom_label = QLabel("")
        self.custom_label.setWordWrap(True)
        cl.addWidget(self.custom_label)
        cb = QHBoxLayout()
        self.btn_draw = QPushButton("Dibujar / editar forma...")
        self.btn_clear_custom = QPushButton("Quitar forma")
        cb.addWidget(self.btn_draw)
        cb.addWidget(self.btn_clear_custom)
        cl.addLayout(cb)
        layout.addWidget(custom)

        # Techo y piso (incluye tipo de techo + arco/cumbre/ridge)
        roof = QGroupBox("Techo y piso")
        rl = QVBoxLayout(roof)

        # Tipo de techo (combo)
        rt_widget = QWidget()
        rth = QHBoxLayout(rt_widget)
        rth.setContentsMargins(0, 4, 0, 4)
        rth.addWidget(QLabel("Tipo de techo"))
        rth.addStretch()
        self.combo_roof = QComboBox()
        self.combo_roof.addItems(["Plano", "Arco", "Dos aguas", "Inclinado"])
        self.combo_roof.setCurrentIndex(1)  # Arco por defecto
        self.combo_roof.setFixedWidth(120)
        self.combo_roof.wheelEvent = lambda ev: ev.ignore()
        rth.addWidget(self.combo_roof)
        rl.addWidget(rt_widget)

        self.s_arch = LabeledSlider("Altura del techo", 0.0, 4.0, 0.0, 1, " m")
        self.s_ridge = LabeledSlider("Posicion de la cumbre", -0.9, 0.9, 0.0, 2, "")
        self.s_cx = LabeledSlider("Techo · pitch X", -45, 45, 0, 0, "°")
        self.s_cy = LabeledSlider("Techo · pitch Y", -45, 45, 0, 0, "°")
        self.s_fx = LabeledSlider("Piso · pitch X", -25, 25, 0, 0, "°")
        self.s_fy = LabeledSlider("Piso · pitch Y", -25, 25, 0, 0, "°")
        rl.addWidget(self.s_arch)
        rl.addWidget(self.s_ridge)
        rl.addWidget(self.s_cx)
        rl.addWidget(self.s_cy)
        rl.addWidget(self.s_fx)
        rl.addWidget(self.s_fy)
        layout.addWidget(roof)

        # Inclinacion por pared (dinamico)
        self.walls_group = QGroupBox("Inclinacion por pared")
        self.walls_layout = QVBoxLayout(self.walls_group)
        layout.addWidget(self.walls_group)

        layout.addStretch(1)
        self._scroll.setWidget(container)

        # ---------- Footer fijo ----------
        footer = QWidget()
        footer.setObjectName("FooterBar")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 8, 12, 12)
        fl.setSpacing(6)

        self.combo_view = QComboBox()
        self.combo_view.addItems(["Aristas", "Externa", "Contorno"])
        self.combo_view.setToolTip("Modo de visualizacion del recinto")
        self.combo_view.wheelEvent = lambda ev: ev.ignore()  # consistencia con sliders

        self.btn_iso = QPushButton("Iso  (0)")
        self.btn_iso.setObjectName("PrimaryButton")
        self.btn_iso.setToolTip("Vista isometrica · Tecla 0")

        self.btn_labels = QPushButton("Etiquetas")
        self.btn_labels.setCheckable(True)
        self.btn_labels.setToolTip("Mostrar / ocultar la dimension de cada arista")

        self.btn_reset = QPushButton("Restablecer")
        self.btn_reset.setToolTip("Vuelve todos los sliders al valor por defecto")

        fl.addWidget(self.combo_view)
        fl.addWidget(self.btn_iso)
        fl.addWidget(self.btn_labels)
        fl.addStretch()
        fl.addWidget(self.btn_reset)
        outer.addWidget(footer)

        # ---------- Conexiones ----------
        self.wall_sliders = []
        self._build_wall_sliders(self.spin_n.value())

        self.spin_n.valueChanged.connect(self._on_n_changed)
        for s in (self.s_width, self.s_length, self.s_height,
                  self.s_taper, self.s_twist, self.s_arch, self.s_ridge,
                  self.s_cx, self.s_cy, self.s_fx, self.s_fy):
            s.valueChanged.connect(self._emit)
        self.combo_roof.currentIndexChanged.connect(self._on_roof_changed)
        self.combo_origin.currentIndexChanged.connect(self._emit)

        self.btn_iso.clicked.connect(self.cameraResetRequested.emit)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_draw.clicked.connect(self.drawShapeRequested.emit)
        self.btn_clear_custom.clicked.connect(self._clear_custom_polygon)
        self.btn_labels.toggled.connect(self.showLabelsToggled.emit)
        self.combo_view.currentTextChanged.connect(self._on_view_changed)

        # Estado de drag de pared (right-click sobre una pared)
        self._wall_drag_idx = None
        self._wall_drag_initial = 0.0

        self._refresh_custom_state()
        self._refresh_roof_state()

    # ----------- Tipo de techo -----------
    _ROOF_KEYS = {0: "flat", 1: "arch", 2: "gable", 3: "shed"}
    _ROOF_INDEX = {v: k for k, v in _ROOF_KEYS.items()}

    def _on_roof_changed(self, *_):
        self._refresh_roof_state()
        self._emit()

    def _refresh_roof_state(self):
        rt = self._ROOF_KEYS.get(self.combo_roof.currentIndex(), "arch")
        # arch_height irrelevante si Plano
        self.s_arch.setEnabled(rt != "flat")
        # ridge solo aplica a "Dos aguas"
        self.s_ridge.setVisible(rt == "gable")

    # ----------- Vista (capas) -----------
    def _on_view_changed(self, text: str):
        mode = {"Aristas": "aristas",
                "Externa": "externa",
                "Contorno": "contorno"}.get(text, "aristas")
        self.viewModeChanged.emit(mode)

    # ----------- Drag de pared (desde el viewer) -----------
    def begin_wall_drag(self, wall_idx: int):
        if 0 <= wall_idx < len(self.wall_sliders):
            self._wall_drag_idx = wall_idx
            self._wall_drag_initial = self.wall_sliders[wall_idx].value()

    def update_wall_drag(self, delta_deg: float):
        if self._wall_drag_idx is None:
            return
        if not (0 <= self._wall_drag_idx < len(self.wall_sliders)):
            return
        slider = self.wall_sliders[self._wall_drag_idx]
        new_val = max(slider.minimum,
                      min(slider.maximum, self._wall_drag_initial + delta_deg))
        slider.set_value(new_val)
        # Disparamos manualmente el signal para que el panel re-render y el commit timer arranque.
        slider.valueChanged.emit(new_val)

    def end_wall_drag(self):
        self._wall_drag_idx = None

    # ----------- Polígono custom -----------
    def _refresh_custom_state(self):
        has = self._custom_polygon is not None
        if has:
            n = len(self._custom_polygon)
            self.custom_label.setText(f"Forma personalizada activa · {n} paredes")
            self.custom_label.setStyleSheet("color: #94e2d5; font-weight: 600;")
        else:
            self.custom_label.setText(
                "Sin forma personalizada · usando el prisma regular de arriba"
            )
            self.custom_label.setStyleSheet("color: #a6adc8; font-size: 9pt;")
        self.btn_clear_custom.setEnabled(has)
        self.shape_group.setEnabled(not has)
        self.s_width.setEnabled(not has)
        self.s_length.setEnabled(not has)
        # Alto (Z): con cortes laterales (wall_profiles) la altura la definen
        # los perfiles -> el slider seria solo estetico, lo bloqueamos. Con
        # forma de solo-planta (sin cortes) el Alto SI define la altura del
        # prisma -> queda editable.
        has_profiles = bool(getattr(self, "_wall_profiles", None))
        self.s_height.setEnabled(not has_profiles)

    def set_custom_polygon(self, polygon):
        self._custom_polygon = list(polygon) if polygon else None
        new_count = (len(self._custom_polygon) if self._custom_polygon
                     else self.spin_n.value())
        if new_count != len(self.wall_sliders):
            old_vals = [s.value() for s in self.wall_sliders]
            self._build_wall_sliders(new_count)
            for i, slider in enumerate(self.wall_sliders):
                if i < len(old_vals):
                    slider.set_value(old_vals[i])
        self._refresh_custom_state()
        self._emit()

    def set_wall_profiles(self, profiles):
        """Perfiles de tope por pared (geometria lofteada, T7). None = prisma."""
        self._wall_profiles = (list(profiles)
                               if (profiles and self._custom_polygon) else None)
        self._refresh_custom_state()   # re-evalua el bloqueo del slider de Alto
        self._emit()

    def _clear_custom_polygon(self):
        self._wall_profiles = None     # sin planta custom no hay lofting
        self.set_custom_polygon(None)

    def get_custom_polygon(self):
        return list(self._custom_polygon) if self._custom_polygon else None

    # ----------- Logica interna -----------
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _build_wall_sliders(self, n: int):
        self._clear_layout(self.walls_layout)
        self.wall_sliders = []
        for i in range(n):
            s = LabeledSlider(f"Pared {i + 1}", -30, 30, 0, 0, "°")
            s.valueChanged.connect(self._emit)
            self.walls_layout.addWidget(s)
            self.wall_sliders.append(s)

    def _on_n_changed(self, n: int):
        if self._custom_polygon is not None:
            return
        self._build_wall_sliders(n)
        self._emit()

    def _emit(self, *_):
        params = self.get_params()
        self.parametersChanged.emit(params)
        self._commit_timer.start()

    def _fire_committed(self):
        self.parametersCommitted.emit(self.get_params())

    def _reset(self):
        self._custom_polygon = None
        self.s_width.set_value(6.0)
        self.s_length.set_value(8.0)
        self.s_height.set_value(3.0)
        self.s_taper.set_value(0.0)
        self.s_twist.set_value(0.0)
        self.s_arch.set_value(0.0)
        self.s_ridge.set_value(0.0)
        self.s_cx.set_value(0.0)
        self.s_cy.set_value(0.0)
        self.s_fx.set_value(0.0)
        self.s_fy.set_value(0.0)
        self.spin_n.blockSignals(True)
        self.spin_n.setValue(4)
        self.spin_n.blockSignals(False)
        self.combo_roof.blockSignals(True)
        self.combo_roof.setCurrentIndex(1)  # Arco por defecto
        self.combo_roof.blockSignals(False)
        self._build_wall_sliders(4)
        self._refresh_custom_state()
        self._refresh_roof_state()
        self._emit()

    def set_params(self, params: dict):
        self._commit_timer.stop()

        bp = params.get("base_polygon")
        self._custom_polygon = list(bp) if bp else None
        # v6: perfiles lofteados (solo válidos junto a un base_polygon).
        wp = params.get("wall_profiles")
        self._wall_profiles = list(wp) if (wp and self._custom_polygon) else None

        self.s_width.set_value(float(params["width"]))
        self.s_length.set_value(float(params["length"]))
        self.s_height.set_value(float(params["height"]))
        self.s_taper.set_value(float(params["taper"]))
        self.s_twist.set_value(float(params["twist"]))
        self.s_arch.set_value(float(params.get("arch_height", 0.0)))
        self.s_ridge.set_value(float(params.get("ridge_offset", 0.0)))
        self.s_cx.set_value(float(params["ceiling_pitch_x"]))
        self.s_cy.set_value(float(params["ceiling_pitch_y"]))
        self.s_fx.set_value(float(params["floor_pitch_x"]))
        self.s_fy.set_value(float(params["floor_pitch_y"]))

        self.spin_n.blockSignals(True)
        self.spin_n.setValue(int(params["n_walls"]))
        self.spin_n.blockSignals(False)

        n_sliders = (len(self._custom_polygon) if self._custom_polygon
                     else int(params["n_walls"]))
        self._build_wall_sliders(n_sliders)

        wall_inc = list(params.get("wall_inclinations", []))
        for i, slider in enumerate(self.wall_sliders):
            v = wall_inc[i] if i < len(wall_inc) else 0.0
            slider.set_value(float(v))

        # Roof type
        rt = (params.get("roof_type") or "arch").lower()
        idx = self._ROOF_INDEX.get(rt, 1)
        self.combo_roof.blockSignals(True)
        self.combo_roof.setCurrentIndex(idx)
        self.combo_roof.blockSignals(False)

        # Origen (0,0,0). .room viejos no traen la clave -> "auto" (legado).
        om = (params.get("origin_mode") or "auto").lower()
        oidx = self.combo_origin.findData(om)
        self.combo_origin.blockSignals(True)
        self.combo_origin.setCurrentIndex(oidx if oidx >= 0 else 0)
        self.combo_origin.blockSignals(False)

        self._refresh_custom_state()
        self._refresh_roof_state()
        self.parametersChanged.emit(self.get_params())

    def get_params(self) -> dict:
        return {
            "width": self.s_width.value(),
            "length": self.s_length.value(),
            "height": self.s_height.value(),
            "n_walls": self.spin_n.value(),
            "taper": self.s_taper.value(),
            "twist": self.s_twist.value(),
            "arch_height": self.s_arch.value(),
            "ridge_offset": self.s_ridge.value(),
            "roof_type": self._ROOF_KEYS.get(
                self.combo_roof.currentIndex(), "arch"
            ),
            "ceiling_pitch_x": self.s_cx.value(),
            "ceiling_pitch_y": self.s_cy.value(),
            "floor_pitch_x": self.s_fx.value(),
            "floor_pitch_y": self.s_fy.value(),
            "wall_inclinations": [s.value() for s in self.wall_sliders],
            "base_polygon": (list(self._custom_polygon)
                             if self._custom_polygon else None),
            # Convencion de origen (0,0,0): "auto" | "center" | "corner".
            "origin_mode": self.combo_origin.currentData(),
            # v6: perfiles de tope por pared (geometria lofteada). Solo tienen
            # sentido con base_polygon; None = prisma de altura constante.
            "wall_profiles": (getattr(self, "_wall_profiles", None)
                              if self._custom_polygon else None),
        }
