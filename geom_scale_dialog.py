"""
geom_scale_dialog.py
====================

Dialogo Qt para revisar y aplicar un factor de escala a una malla CAD
recien importada. Aparece cuando suggest_scale_factor(mesh) detecta que
la geometria esta probablemente en una unidad distinta a metros (mm, cm,
pulgadas, etc.) o cuando su tamano es manifiestamente irreal para un
recinto arquitectonico.

El usuario decide finalmente: aceptar la sugerencia, elegir un preset
distinto o introducir un factor manual. Tambien puede pedir "auto-encajar
a 20 m" si no confia en la heuristica.
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from style import apply_dialog_theme
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QDialogButtonBox, QGroupBox, QSizePolicy, QFrame, QComboBox,
)

import geom_import as gi


class ImportScaleDialog(QDialog):
    """Dialogo modal para escalar una malla recien importada.

    Uso:
        dlg = ImportScaleDialog(mesh, suggestion, parent=...)
        if dlg.exec_() == QDialog.Accepted:
            factor = dlg.chosen_factor
            mesh_scaled = gi.apply_scale(mesh, factor)
    """

    PRESETS = [
        ("Sin cambio  (x1)",        1.0,    "metros"),
        ("Milimetros -> metros  (/1000)", 1e-3, "mm"),
        ("Centimetros -> metros  (/100)", 1e-2, "cm"),
        ("Decimetros / x10 -> metros  (/10)", 1e-1, "dm"),
        ("Metros -> milimetros  (x1000)", 1e3, "mm-as-m"),
        ("Metros -> centimetros  (x100)", 1e2, "in/cm-as-m"),
        ("Pulgadas -> metros  (x0.0254)", 0.0254, "in"),
        ("Pies -> metros  (x0.3048)", 0.3048, "ft"),
    ]

    # Convencion de eje "up" para conversion al sistema Z-up del soft.
    UP_AXIS_PRESETS = [
        ("Z+ up   (Prototipo 1, FreeCAD, AutoCAD)",  "Z+"),
        ("Y+ up   (OBJ / glTF / Blender / Unity)",   "Y+"),
        ("X+ up   (raro)",                            "X+"),
        ("Z- up   (eje Z invertido)",                 "Z-"),
        ("Y- up   (eje Y invertido)",                 "Y-"),
        ("X- up   (eje X invertido)",                 "X-"),
    ]

    def __init__(self, mesh, suggestion: gi.ScaleSuggestion,
                  suggested_up: str = "Z+", parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Escalar y orientar geometria importada")
        self.resize(640, 640)
        self._mesh = mesh
        self._suggestion = suggestion
        self.chosen_factor: float = float(suggestion.factor)
        self.chosen_up_axis: str = (suggested_up or "Z+").upper()

        self._build_ui()
        self._update_preview()

    # -----------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # Header con sugerencia
        head = QLabel(
            f"<b>Sugerencia automatica:</b> {self._suggestion.reason}"
        )
        head.setWordWrap(True)
        head.setStyleSheet("QLabel { padding: 8px; background: #f1e9b3; "
                            "border-radius: 4px; color: #2a2410; }")
        outer.addWidget(head)

        # Info actual de la malla
        info_box = QGroupBox("Dimensiones actuales del modelo")
        info_layout = QFormLayout(info_box)
        b = np.asarray(self._mesh.bounds, dtype=float)
        size = b[1] - b[0]
        diag = float(np.linalg.norm(size))
        vol = float(self._mesh.volume) if self._mesh.is_volume else None
        info_layout.addRow("AABB X × Y × Z:",
            QLabel(f"{size[0]:.3f} × {size[1]:.3f} × {size[2]:.3f}  (interpretadas como metros)"))
        info_layout.addRow("Diagonal:", QLabel(f"{diag:.3f} m"))
        if vol is not None:
            info_layout.addRow("Volumen:", QLabel(f"{vol:,.3f} m³"))
        info_layout.addRow("Triangulos:", QLabel(f"{len(self._mesh.faces):,}"))
        outer.addWidget(info_box)

        # Presets como radio buttons
        preset_box = QGroupBox("Factor de escala")
        pv = QVBoxLayout(preset_box)
        self._radio_group = QButtonGroup(self)
        self._radios = []
        suggested_idx = self._closest_preset_index(self._suggestion.factor)
        for i, (label, factor, _unit) in enumerate(self.PRESETS):
            rb = QRadioButton(label)
            rb.toggled.connect(self._on_radio_changed)
            self._radio_group.addButton(rb, i)
            pv.addWidget(rb)
            self._radios.append((rb, factor))
            if i == suggested_idx:
                rb.setChecked(True)

        # Linea separadora
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
        pv.addWidget(line)

        # Opcion manual
        manual_row = QHBoxLayout()
        self.rb_manual = QRadioButton("Factor manual:")
        self._radio_group.addButton(self.rb_manual, len(self.PRESETS))
        self.rb_manual.toggled.connect(self._on_radio_changed)
        manual_row.addWidget(self.rb_manual)
        self.sb_manual = QDoubleSpinBox()
        self.sb_manual.setRange(1e-6, 1e6)
        self.sb_manual.setDecimals(6)
        self.sb_manual.setSingleStep(0.1)
        self.sb_manual.setValue(float(self._suggestion.factor))
        self.sb_manual.valueChanged.connect(self._on_radio_changed)
        manual_row.addWidget(self.sb_manual, 1)
        pv.addLayout(manual_row)

        # Auto-fit a 20 m
        auto_row = QHBoxLayout()
        self.btn_autofit = QPushButton("Auto-encajar diagonal a 20 m")
        self.btn_autofit.setToolTip(
            "Calcula automaticamente el factor para que la diagonal del "
            "modelo sea de 20 m. Util si la heuristica de unidad falla.")
        self.btn_autofit.clicked.connect(self._on_autofit_clicked)
        auto_row.addWidget(self.btn_autofit)
        auto_row.addStretch()
        pv.addLayout(auto_row)
        outer.addWidget(preset_box)

        # --- Orientacion del archivo (eje 'up') ---
        orient_box = QGroupBox("Orientacion del archivo (eje vertical)")
        ov = QVBoxLayout(orient_box)
        info_orient = QLabel(
            "El soft asume Z+ como eje vertical. Si el archivo usa otra "
            "convencion (tipico: OBJ/glTF usa Y+ vertical), elegi la "
            "correcta para que las paredes no queden como piso."
        )
        info_orient.setWordWrap(True)
        info_orient.setStyleSheet("QLabel { color: #6c6f85; font-size: 9pt; }")
        ov.addWidget(info_orient)
        self.combo_up = QComboBox()
        for label, key in self.UP_AXIS_PRESETS:
            self.combo_up.addItem(label, key)
        # Pre-seleccionar la convencion sugerida (por extension del archivo).
        idx_default = next((i for i, (_, k) in enumerate(self.UP_AXIS_PRESETS)
                            if k == self.chosen_up_axis), 0)
        self.combo_up.setCurrentIndex(idx_default)
        self.combo_up.currentIndexChanged.connect(self._on_up_changed)
        ov.addWidget(self.combo_up)
        outer.addWidget(orient_box)

        # Preview del resultado
        self.lbl_preview = QLabel()
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet(
            "QLabel { padding: 8px; background: #d4f0d4; "
            "border-radius: 4px; color: #1a3a1a; font-family: monospace; }"
        )
        outer.addWidget(self.lbl_preview)

        # Botones: tres opciones explicitas para que la semantica sea
        # inequivoca y "No escalar" NO cancele todo el import.
        #
        #   - Aplicar escala  -> accept() con el factor elegido
        #   - No escalar      -> accept() con factor=1.0 (sigue el import)
        #   - Cancelar import -> reject() (aborta todo)
        #
        # Esc / cerrar ventana (X) tambien rechazan (cancelan).
        btns = QDialogButtonBox()
        btn_apply = btns.addButton("Aplicar escala", QDialogButtonBox.AcceptRole)
        btn_skip  = btns.addButton("No escalar",     QDialogButtonBox.ActionRole)
        btn_cancel = btns.addButton("Cancelar import", QDialogButtonBox.RejectRole)
        btn_apply.clicked.connect(self.accept)
        btn_skip.clicked.connect(self._on_skip)
        btn_cancel.clicked.connect(self.reject)
        outer.addWidget(btns)

        # Estilo uniforme
        for b in self.findChildren(QPushButton):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # -----------------------------------------------------------------------
    def _closest_preset_index(self, factor: float) -> int:
        """Indice del preset cuyo factor mas se parece (en log) a `factor`."""
        if factor <= 0:
            return 0
        log_f = np.log10(factor)
        diffs = [abs(np.log10(p[1]) - log_f) for p in self.PRESETS]
        return int(np.argmin(diffs))

    def _on_radio_changed(self, *_):
        sel_id = self._radio_group.checkedId()
        if 0 <= sel_id < len(self.PRESETS):
            self.chosen_factor = self.PRESETS[sel_id][1]
        elif sel_id == len(self.PRESETS):   # manual
            self.chosen_factor = float(self.sb_manual.value())
        # Solo actualizar preview si ya esta creado (durante el setup
        # inicial, el radio "checked" puede dispararse antes de tener el
        # label).
        if hasattr(self, "lbl_preview") and self.lbl_preview is not None:
            self._update_preview()

    def _on_autofit_clicked(self):
        factor = gi.autofit_scale(self._mesh, target_diag=20.0)
        self.rb_manual.setChecked(True)
        self.sb_manual.setValue(factor)
        self.chosen_factor = factor
        self._update_preview()

    def _on_up_changed(self, *_):
        idx = self.combo_up.currentIndex()
        if 0 <= idx < len(self.UP_AXIS_PRESETS):
            self.chosen_up_axis = self.UP_AXIS_PRESETS[idx][1]
        if hasattr(self, "lbl_preview") and self.lbl_preview is not None:
            self._update_preview()

    def _on_skip(self):
        # "No escalar" implica factor 1.0 PERO el import continua.
        # Antes este metodo llamaba a reject() y eso abortaba el import
        # entero, lo cual era contraintuitivo (el boton dice "No escalar",
        # no "Cancelar"). Ahora accept() devuelve Accepted con factor=1.0
        # y la orquestacion en main.py ya saltea apply_scale cuando el
        # factor es exactamente 1.0.
        self.chosen_factor = 1.0
        self.accept()

    def _update_preview(self):
        b = np.asarray(self._mesh.bounds, dtype=float)
        size_xyz_file = b[1] - b[0]  # tamano en los ejes del archivo
        f = self.chosen_factor

        # Mapear los ejes del archivo a los ejes del soft segun la
        # orientacion elegida (solo para mostrar correctamente las
        # dimensiones en el preview; la transformacion real se aplica
        # al confirmar el dialogo).
        up = self.chosen_up_axis
        sx, sy, sz = size_xyz_file
        if up in ("Z+",):
            new_x, new_y, new_z = sx, sy, sz
        elif up in ("Y+",):
            new_x, new_y, new_z = sx, sz, sy
        elif up in ("X+",):
            new_x, new_y, new_z = sz, sy, sx
        elif up in ("Z-",):
            new_x, new_y, new_z = sx, sy, sz
        elif up in ("Y-",):
            new_x, new_y, new_z = sx, sz, sy
        elif up in ("X-",):
            new_x, new_y, new_z = sz, sy, sx
        else:
            new_x, new_y, new_z = sx, sy, sz

        new_x, new_y, new_z = new_x * f, new_y * f, new_z * f
        new_diag = float(np.sqrt(new_x ** 2 + new_y ** 2 + new_z ** 2))
        new_vol = None
        try:
            if self._mesh.is_volume:
                new_vol = float(self._mesh.volume) * (f ** 3)
        except Exception:
            pass

        lines = [f"Factor a aplicar:  x {f:g}",
                 f"Orientacion: {self.chosen_up_axis} -> Z+ (Prototipo 1)",
                 "Nuevas dimensiones (ya en ejes del soft):",
                 f"  X = {new_x:>12.3f} m",
                 f"  Y = {new_y:>12.3f} m",
                 f"  Z = {new_z:>12.3f} m  (altura)",
                 f"  diagonal = {new_diag:.3f} m"]
        if new_vol is not None:
            lines.append(f"  volumen  = {new_vol:,.3f} m³")
        # Comentario de plausibilidad
        if 5.0 <= new_diag <= 60.0:
            lines.append("✓ Rango plausible para un recinto arquitectonico.")
        elif new_diag < 1.0:
            lines.append("AVISO: muy pequeno, probablemente quede insumible.")
        elif new_diag > 200.0:
            lines.append("AVISO: muy grande, podria salirse de la grilla del visor.")
        self.lbl_preview.setText("\n".join(lines))
