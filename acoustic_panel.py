"""
acoustic_panel.py
=================

Panel Qt para el modulo acustico:
  - Gestion de un array de fuentes omnidireccionales (anadir / quitar / editar).
  - Posicion de un receptor unico.
  - Boton "Calcular modos" -> FEM modal sobre la malla volumetrica.
  - Selector de modo + slider de altura del slice -> overlay del campo.
  - Boton "FRF" -> dialogo con grafico de |H(f)| dB.

El panel es agnostico del viewer: se le pasa un objeto que cumple con la
interfaz minima:
    - acoustic_viewer.SourceMarkers, ReceiverMarker, FieldSliceItem
      manejados internamente, montados sobre el GLViewWidget recibido.
Y un callable `get_surface() -> (verts, tris)` para pedir la geometria
actual del recinto cada vez que el usuario lanza un calculo.
"""

from __future__ import annotations

import math
import numpy as np
from typing import Callable, Optional

import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QColor
from style import apply_dialog_theme
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QSlider, QFileDialog, QMessageBox, QDialog,
    QDialogButtonBox, QLineEdit, QProgressBar, QSizePolicy, QFrame,
    QScrollArea, QMenu, QRadioButton, QButtonGroup,
)

from sources import OmniSource, SourceArray, RHO0, C0
import acoustic_analysis as aa
import acoustic_viewer as av
import mesh_router

try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
    import matplotlib.pyplot as plt
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

from pathlib import Path
from material_library import (MaterialLibrary, compute_sabine_rt60,
                               compute_xi_per_mode, classify_surface_areas)
import material_library as ml
import face_materials as fm
import impedance as imp


# ---------------------------------------------------------------------------
# Helper: exportar tabla a CSV (Excel-es: ; con coma decimal) o TXT (tab, .)
# ---------------------------------------------------------------------------
def _write_tabular(path: str, header: list, rows: list, fmt: str) -> None:
    sep = ';' if fmt == 'csv' else '\t'
    enc = 'utf-8-sig' if fmt == 'csv' else 'utf-8'
    use_comma_decimal = (fmt == 'csv')

    def _fmt(v):
        if v is None:
            return ''
        if isinstance(v, float):
            if not np.isfinite(v):
                return ''
            s = f"{v:.6g}"
            if use_comma_decimal:
                s = s.replace('.', ',')
            return s
        if isinstance(v, (np.floating,)):
            return _fmt(float(v))
        if isinstance(v, (np.integer,)):
            return str(int(v))
        return str(v)

    with open(path, 'w', encoding=enc, newline='') as fh:
        fh.write(sep.join(str(h) for h in header) + '\n')
        for row in rows:
            fh.write(sep.join(_fmt(v) for v in row) + '\n')


# ---------------------------------------------------------------------------
# Dialog para anadir / editar una fuente
# ---------------------------------------------------------------------------
class SourceEditDialog(QDialog):
    """Diálogo para editar una fuente omnidireccional.

    La fuente se configura por su Sensibilidad (dB SPL @ 1W / 1m),
    que es el dato estándar de la ficha técnica de cualquier altavoz.
    El software calcula internamente el caudal volumétrico Q usando el
    modelo de monopolo a la frecuencia de referencia de 1 kHz.
    """

    _F_REF = 1000.0   # frecuencia de referencia para la sensibilidad [Hz]

    def __init__(self, source: Optional[OmniSource] = None,
                 dims_hint: Optional[tuple] = None, parent=None,
                 get_walls=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Fuente acústica")
        # Callback opcional -> lista de (centroide(3,), normal(3,)) de las paredes
        # (para "Pegar a pared más cercana"). El panel lo arma con los face groups.
        self._get_walls = get_walls
        # Bandera de montaje (one-shot informativa); se prende al pegar a pared.
        self._mounted = bool(getattr(source, "mounted", False)) if source else False
        # El contenido va en un QScrollArea (el diálogo puede ser alto: respuesta
        # + filtro + bafle) para que OK/Cancel queden SIEMPRE alcanzables abajo.
        _outer = QVBoxLayout(self)
        _content = QWidget()
        layout = QFormLayout(_content)
        layout.setLabelAlignment(Qt.AlignRight)

        # Etiqueta
        self.le_label = QLineEdit(source.label if source else "src")
        layout.addRow("Etiqueta:", self.le_label)

        # Posición
        def spin(val, lo=-1e3, hi=1e3, step=0.1, dec=2):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi); sb.setDecimals(dec)
            sb.setSingleStep(step); sb.setValue(val)
            return sb

        x, y, z = (source.position if source else (1.0, 1.0, 1.0))
        self.sb_x = spin(x); self.sb_y = spin(y); self.sb_z = spin(z)
        pos_row = QHBoxLayout()
        for lbl, sb in (("X:", self.sb_x), ("Y:", self.sb_y), ("Z:", self.sb_z)):
            pos_row.addWidget(QLabel(lbl)); pos_row.addWidget(sb)
        layout.addRow("Posición (m):", pos_row)

        # Sensibilidad — único parámetro de intensidad
        s_dB = 90.0
        if source is not None:
            if source.sensitivity_dB is not None:
                s_dB = float(source.sensitivity_dB)
            else:
                # Fuente definida por Q directo: no mostrar ningún valor de sens
                s_dB = 90.0
        self.sb_sens = QDoubleSpinBox()
        self.sb_sens.setRange(40.0, 130.0)
        self.sb_sens.setDecimals(1)
        self.sb_sens.setSingleStep(0.5)
        self.sb_sens.setValue(s_dB)
        self.sb_sens.setSuffix("  dB SPL")
        layout.addRow("Sensibilidad  (1W / 1m):", self.sb_sens)

        # Label informativo
        note = QLabel(
            "dB SPL medido a 1 W de potencia eléctrica y 1 m de distancia\n"
            "(dato estándar de ficha técnica del altavoz)."
        )
        note.setStyleSheet("color: #6c6f85; font-size: 8pt;")
        layout.addRow("", note)

        self.lbl_q = QLabel()
        self.lbl_q.setStyleSheet("color: #179299; font-size: 9pt;")
        layout.addRow("→ Q equivalente:", self.lbl_q)
        self._update_q_label()
        self.sb_sens.valueChanged.connect(self._update_q_label)

        # --- Polaridad (v2.23) ----------------------------------------------
        # Campo propio de la fuente, ORTOGONAL a la curva Q(f): la polaridad es
        # del cableado y se compone con la respuesta medida en vez de pisarla.
        # Antes vivia adentro del atajo manual de Q(f) y aplicarla borraba el
        # FRD/TRF cargado. Un solo bit -> se lee de vuelta y va al .room.
        pol0 = int(getattr(source, "polarity", 1) or 1) if source else 1
        self.chk_polarity = QCheckBox("Invertida (180°)")
        self.chk_polarity.setChecked(pol0 < 0)
        self.chk_polarity.setToolTip(
            "Polaridad del cableado: 0° = normal, 180° = invertida (×−1).\n"
            "Se compone con la curva Q(f): invertir NO borra un FRD/TRF cargado.\n"
            "Afecta FRF, campo 3D, SBIR y el optimizador de ubicación."
        )
        self.lbl_polarity = QLabel()
        self.lbl_polarity.setStyleSheet("color: #179299; font-size: 9pt;")
        pol_row = QHBoxLayout()
        pol_row.addWidget(self.chk_polarity)
        pol_row.addWidget(self.lbl_polarity, 1)
        layout.addRow("Polaridad:", pol_row)
        self.chk_polarity.toggled.connect(self._update_polarity_label)
        self._update_polarity_label()

        # --- Respuesta en frecuencia Q(f) (Fase 2 — plan_fuentes) -----------
        # La curva es una ganancia compleja g(f) relativa al Q baseline
        # (opcion 1). "Sin curva" = Q constante (comportamiento historico).
        self._response = (source.response
                          if (source is not None and getattr(source, "response", None))
                          else None)
        self._frd_raw = None    # (freq, spl_db, phase_rad, name) si se cargo aca
        # v2.25: delay/fase como CAMPOS de la fuente (re-leibles al reabrir).
        self._delay0_ms = (float(getattr(source, "delay_s", 0.0) or 0.0) * 1000.0
                           if source is not None else 0.0)
        self._phase0_deg = (float(getattr(source, "phase_deg", 0.0) or 0.0)
                            if source is not None else 0.0)
        # v2.29: filtro de crossover/EQ (campos re-leibles al reabrir la fuente).
        self._filt0 = {
            "type":   str(getattr(source, "filter_type", "none") or "none"),
            "order":  int(getattr(source, "filter_order", 4) or 4),
            "fc":     float(getattr(source, "filter_fc", 100.0) or 100.0),
            "kind":   str(getattr(source, "filter_kind", "lowpass") or "lowpass"),
            "ripple": float(getattr(source, "filter_ripple_db", 1.0) or 1.0),
            "atten":  float(getattr(source, "filter_atten_db", 40.0) or 40.0),
        } if source is not None else {
            "type": "none", "order": 4, "fc": 100.0, "kind": "lowpass",
            "ripple": 1.0, "atten": 40.0}

        grp_resp = QGroupBox("Respuesta en frecuencia  Q(f)   (opcional)")
        gl = QVBoxLayout(grp_resp)

        self.lbl_resp = QLabel()
        self.lbl_resp.setWordWrap(True)
        self.lbl_resp.setStyleSheet("font-size: 8pt;")
        gl.addWidget(self.lbl_resp)

        brow = QHBoxLayout()
        btn_load = QPushButton("Cargar FRD/TRF/CLF…")
        btn_load.clicked.connect(self._load_frd)
        self.btn_clear_resp = QPushButton("Quitar")
        self.btn_clear_resp.clicked.connect(self._clear_resp)
        brow.addWidget(btn_load)
        brow.addWidget(self.btn_clear_resp)
        gl.addLayout(brow)

        arow = QHBoxLayout()
        arow.addWidget(QLabel("Anclaje:"))
        self.combo_anchor = QComboBox()
        self.combo_anchor.addItem("Absoluto (nivel del FRD manda)", "absolute")
        self.combo_anchor.addItem("Relativo (forma; nivel = sensibilidad)", "relative")
        if (self._response is not None
                and getattr(self._response, "anchor", "") == "relative"):
            self.combo_anchor.setCurrentIndex(1)
        self.combo_anchor.currentIndexChanged.connect(self._rebake_frd)
        arow.addWidget(self.combo_anchor, 1)
        gl.addLayout(arow)

        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Delay (ms):"))
        self.sb_delay = QDoubleSpinBox()
        self.sb_delay.setRange(0.0, 100.0)
        self.sb_delay.setDecimals(2)
        self.sb_delay.setSingleStep(0.1)
        self.sb_delay.setValue(self._delay0_ms)
        mrow.addWidget(self.sb_delay)
        # v2.25: delay y fase son CAMPOS propios de la fuente (como la polaridad),
        # NO se hornean en la curva g(f). Se componen al calcular
        # (OmniSource.effective_Q_spectrum) y se guardan/leen como numeros, asi
        # que al reabrir la fuente el valor sigue ahi y NO pisan un FRD cargado.
        # Se aplican SOLOS al Aceptar (ya no hay boton "Aplicar").
        mrow.addWidget(QLabel("Fase (°):"))
        self.sb_phase = QDoubleSpinBox()
        self.sb_phase.setRange(-180.0, 180.0)
        self.sb_phase.setDecimals(0)
        self.sb_phase.setSingleStep(15.0)
        self.sb_phase.setValue(self._phase0_deg)
        mrow.addWidget(self.sb_phase)
        # Preview en vivo: al cambiar delay/fase se redibuja (se componen sobre
        # la curva/plana para mostrar la fase total).
        self.sb_delay.valueChanged.connect(self._draw_resp_preview)
        self.sb_phase.valueChanged.connect(self._draw_resp_preview)
        gl.addLayout(mrow)

        # Preview compacto (magnitud + fase), best-effort.
        self._resp_canvas = None
        if _HAS_MPL:
            try:
                self._resp_fig, (self._resp_ax_m, self._resp_ax_p) = plt.subplots(
                    2, 1, figsize=(4.0, 2.3), dpi=80, sharex=True)
                self._resp_fig.patch.set_facecolor('#f0f0f0')
                self._resp_canvas = FigureCanvas(self._resp_fig)
                self._resp_canvas.setMinimumHeight(150)
                gl.addWidget(self._resp_canvas)
            except Exception:
                self._resp_canvas = None

        # Modo absoluto: la sensibilidad cambia q_base → re-hornear la curva.
        self.sb_sens.valueChanged.connect(self._rebake_frd)
        layout.addRow(grp_resp)
        self._refresh_resp_ui()

        # --- Driver físico Thiele-Small (S2, modelo de fuente exacto) ---------
        # Deriva Q(f) de la física del parlante (caja sellada, pasa-altos de 2º
        # orden) en vez de una curva plana/medida. Setea self._response (se
        # compone igual que un FRD). Ver driver.py / plan_modelo_fuente.md.
        grp_drv = QGroupBox("Driver físico (Thiele-Small)   (opcional)")
        dvl = QVBoxLayout(grp_drv)
        self.combo_drv_mode = QComboBox()
        self.combo_drv_mode.addItem("fc + Qtc (caja sellada)", "direct")
        self.combo_drv_mode.addItem("fs, Qts, Vas + Vb (caja sellada)", "ts")
        drow0 = QHBoxLayout()
        drow0.addWidget(QLabel("Especificar por:"))
        drow0.addWidget(self.combo_drv_mode, 1)
        dvl.addLayout(drow0)

        self._drv_direct = QWidget()
        dd = QFormLayout(self._drv_direct)
        dd.setContentsMargins(0, 0, 0, 0)
        self.sb_drv_fc = QDoubleSpinBox()
        self.sb_drv_fc.setRange(10.0, 300.0); self.sb_drv_fc.setValue(40.0)
        self.sb_drv_fc.setSuffix(" Hz")
        self.sb_drv_qtc = QDoubleSpinBox()
        self.sb_drv_qtc.setRange(0.3, 3.0); self.sb_drv_qtc.setDecimals(3)
        self.sb_drv_qtc.setValue(0.707); self.sb_drv_qtc.setSingleStep(0.05)
        dd.addRow("fc (resonancia en caja):", self.sb_drv_fc)
        dd.addRow("Qtc (Q total en caja):", self.sb_drv_qtc)
        dvl.addWidget(self._drv_direct)

        self._drv_ts = QWidget()
        dt = QFormLayout(self._drv_ts)
        dt.setContentsMargins(0, 0, 0, 0)
        self.sb_drv_fs = QDoubleSpinBox()
        self.sb_drv_fs.setRange(5.0, 200.0); self.sb_drv_fs.setValue(25.0)
        self.sb_drv_fs.setSuffix(" Hz")
        self.sb_drv_qts = QDoubleSpinBox()
        self.sb_drv_qts.setRange(0.1, 2.0); self.sb_drv_qts.setDecimals(3)
        self.sb_drv_qts.setValue(0.35); self.sb_drv_qts.setSingleStep(0.05)
        self.sb_drv_vas = QDoubleSpinBox()
        self.sb_drv_vas.setRange(1.0, 2000.0); self.sb_drv_vas.setValue(100.0)
        self.sb_drv_vas.setSuffix(" L")
        self.sb_drv_vb = QDoubleSpinBox()
        self.sb_drv_vb.setRange(1.0, 2000.0); self.sb_drv_vb.setValue(50.0)
        self.sb_drv_vb.setSuffix(" L")
        dt.addRow("fs (resonancia libre):", self.sb_drv_fs)
        dt.addRow("Qts:", self.sb_drv_qts)
        dt.addRow("Vas (compliancia equiv.):", self.sb_drv_vas)
        dt.addRow("Vb (volumen de caja):", self.sb_drv_vb)
        dvl.addWidget(self._drv_ts)

        btn_drv = QPushButton("Aplicar como curva Q(f)")
        btn_drv.clicked.connect(self._apply_driver)
        dvl.addWidget(btn_drv)
        self.combo_drv_mode.currentIndexChanged.connect(self._on_drv_mode_changed)
        layout.addRow(grp_drv)
        self._on_drv_mode_changed()

        # --- Filtro de crossover / EQ (v2.29, pedido del profesor) -----------
        import filters as _flt
        grp_filt = QGroupBox("Filtro (crossover / EQ)   (opcional)")
        ff = QFormLayout(grp_filt)
        self.combo_filt = QComboBox()
        for key, (lbl, _r, _a) in _flt.FILTER_TYPES.items():
            self.combo_filt.addItem(lbl, key)
        i0 = self.combo_filt.findData(self._filt0["type"])
        self.combo_filt.setCurrentIndex(i0 if i0 >= 0 else 0)
        ff.addRow("Tipo:", self.combo_filt)

        self.combo_filt_kind = QComboBox()
        self.combo_filt_kind.addItem("Pasabajos", "lowpass")
        self.combo_filt_kind.addItem("Pasaaltos", "highpass")
        ik = self.combo_filt_kind.findData(self._filt0["kind"])
        self.combo_filt_kind.setCurrentIndex(ik if ik >= 0 else 0)
        ff.addRow("Banda:", self.combo_filt_kind)

        self.combo_filt_order = QComboBox()   # se repuebla según el tipo
        ff.addRow("Orden:", self.combo_filt_order)

        self.sb_filt_fc = QDoubleSpinBox()
        self.sb_filt_fc.setRange(5.0, 20000.0)
        self.sb_filt_fc.setDecimals(1)
        self.sb_filt_fc.setSingleStep(5.0)
        self.sb_filt_fc.setValue(self._filt0["fc"])
        self.sb_filt_fc.setSuffix(" Hz  (corte)")
        ff.addRow("f. corte:", self.sb_filt_fc)

        self.sb_filt_ripple = QDoubleSpinBox()
        self.sb_filt_ripple.setRange(0.01, 6.0)
        self.sb_filt_ripple.setDecimals(2)
        self.sb_filt_ripple.setSingleStep(0.1)
        self.sb_filt_ripple.setValue(self._filt0["ripple"])
        self.sb_filt_ripple.setSuffix(" dB  (ripple de paso)")
        self.lbl_filt_ripple = QLabel("Ripple:")
        ff.addRow(self.lbl_filt_ripple, self.sb_filt_ripple)

        self.sb_filt_atten = QDoubleSpinBox()
        self.sb_filt_atten.setRange(10.0, 120.0)
        self.sb_filt_atten.setDecimals(0)
        self.sb_filt_atten.setSingleStep(5.0)
        self.sb_filt_atten.setValue(self._filt0["atten"])
        self.sb_filt_atten.setSuffix(" dB  (rechazo)")
        self.lbl_filt_atten = QLabel("Atenuación:")
        ff.addRow(self.lbl_filt_atten, self.sb_filt_atten)

        self.combo_filt.currentIndexChanged.connect(self._on_filter_type_changed)
        for w in (self.combo_filt_kind, self.combo_filt_order, self.sb_filt_fc,
                  self.sb_filt_ripple, self.sb_filt_atten):
            (w.currentIndexChanged if isinstance(w, QComboBox)
             else w.valueChanged).connect(self._draw_resp_preview)
        self._on_filter_type_changed()   # puebla orden + muestra/oculta ripple/atten
        layout.addRow(grp_filt)

        # --- Bafle: orientación + dimensiones (T4, visual + insumo de T8) ----
        grp_baf = QGroupBox("Bafle (visual)")
        fb = QFormLayout(grp_baf)
        ori0 = (90.0 if (source is None or getattr(source, "orientation", None) is None)
                else float(source.orientation))
        self.sb_orient = QDoubleSpinBox()
        self.sb_orient.setRange(0.0, 359.0)
        self.sb_orient.setDecimals(0)
        self.sb_orient.setSingleStep(15.0)
        self.sb_orient.setValue(ori0)
        self.sb_orient.setSuffix("°  (azimut del frente; 0=+X)")
        fb.addRow("Orientación:", self.sb_orient)
        # Inclinación (pitch): visual + insumo de T8; no afecta la acústica.
        pit0 = float(getattr(source, "pitch", 0.0) or 0.0) if source is not None else 0.0
        self.sb_pitch = QDoubleSpinBox()
        self.sb_pitch.setRange(-90.0, 90.0)
        self.sb_pitch.setDecimals(0)
        self.sb_pitch.setSingleStep(5.0)
        self.sb_pitch.setValue(pit0)
        self.sb_pitch.setSuffix("°  (0=horizontal, + arriba)")
        fb.addRow("Inclinación:", self.sb_pitch)
        bw, bh, bd = (source.baffle_size if source is not None else (0.30, 0.50, 0.40))
        drow = QHBoxLayout()
        self.sb_bw = QDoubleSpinBox(); self.sb_bh = QDoubleSpinBox(); self.sb_bd = QDoubleSpinBox()
        for sb, val in ((self.sb_bw, bw), (self.sb_bh, bh), (self.sb_bd, bd)):
            sb.setRange(0.05, 3.0); sb.setDecimals(2); sb.setSingleStep(0.05); sb.setValue(val)
        for lbl, sb in (("An", self.sb_bw), ("Al", self.sb_bh), ("Pr", self.sb_bd)):
            drow.addWidget(QLabel(lbl)); drow.addWidget(sb)
        fb.addRow("Dim (m):", drow)
        # Montar en pared: pega la fuente flush a la pared más cercana y orienta
        # el frente hacia el interior. One-shot (no se re-pega solo).
        self.btn_snap_wall = QPushButton("Pegar a pared más cercana")
        self.btn_snap_wall.setToolTip(
            "Mueve la fuente contra la pared más cercana (distancia = mitad de la "
            "profundidad del bafle) y apunta el frente hacia adentro. Empuja el "
            "notch SBIR fuera de banda (regla flush/soffit)."
        )
        self.btn_snap_wall.setEnabled(self._get_walls is not None)
        self.btn_snap_wall.clicked.connect(self._snap_to_wall)
        fb.addRow(self.btn_snap_wall)
        self.lbl_mounted = QLabel("Montada en pared ✓" if self._mounted else "")
        self.lbl_mounted.setStyleSheet("color: #179299; font-size: 8pt;")
        fb.addRow("", self.lbl_mounted)
        layout.addRow(grp_baf)

        if dims_hint:
            hint = QLabel(f"Recinto: {dims_hint[0]:.1f} × "
                          f"{dims_hint[1]:.1f} × {dims_hint[2]:.1f} m")
            hint.setStyleSheet("color: #6c6f85; font-size: 8pt;")
            layout.addRow("", hint)

        # Scroll con el contenido; botones fijos abajo (fuera del scroll).
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.NoFrame)
        _scroll.setWidget(_content)
        _outer.addWidget(_scroll, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        _outer.addWidget(btns)
        # Alto inicial acotado a la pantalla (el resto entra por scroll).
        try:
            from PyQt5.QtWidgets import QApplication as _QA
            _avail = _QA.primaryScreen().availableGeometry().height()
            self.resize(self.sizeHint().width(), min(760, int(_avail * 0.9)))
        except Exception:
            self.resize(440, 720)

    def _update_q_label(self):
        from sources import q_from_sensitivity
        q = q_from_sensitivity(self.sb_sens.value(), power_W=1.0,
                                f_ref=self._F_REF)
        self.lbl_q.setText(f"|Q| = {abs(q):.3e} m³/s  "
                           f"(monopolo @ {self._F_REF:.0f} Hz, 1 W)")

    def _update_polarity_label(self):
        inv = self.chk_polarity.isChecked()
        self.lbl_polarity.setText(
            "Q × (−1) — en contrafase con una fuente normal" if inv
            else "0° (normal)")

    # ------------------------------------------------------------------
    # Respuesta en frecuencia Q(f) (Fase 2)
    # ------------------------------------------------------------------
    def _q_base(self) -> float:
        from sources import q_from_sensitivity
        return abs(q_from_sensitivity(self.sb_sens.value(), power_W=1.0,
                                      f_ref=self._F_REF))

    def _load_frd(self):
        from frd import load_frd, load_trf, load_clf, minimum_phase, _TRF_MAGIC
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar respuesta FRD / TRF / CLF", "",
            "Respuesta (*.frd *.trf *.txt *.dat *.cf2 *.cf1 *.clf);;"
            "CLF (*.cf2 *.cf1 *.clf);;Todos los archivos (*)")
        if not path:
            return
        # Dispatch: CLF binario por extension (.cf2/.cf1/.clf; no tiene magic
        # ASCII limpio), TRF binario por magic JACKREF!, resto = FRD de texto.
        import os
        is_clf = os.path.splitext(path)[1].lower() in (".cf2", ".cf1", ".clf")
        try:
            with open(path, "rb") as fh:
                is_trf = (not is_clf) and fh.read(8) == _TRF_MAGIC
        except Exception as e:
            QMessageBox.warning(self, "FRD/TRF/CLF", f"No se pudo abrir:\n{e}")
            return
        coh = None
        try:
            if is_clf:
                # CLF: solo la respuesta EN EJE (SPL @1W/1m). La directividad se
                # descarta (irrelevante bajo Schroeder, fuente omni). Fase None
                # -> cae en el flujo de "fase ausente" de abajo.
                freq, spl, phase_deg = load_clf(path)
            elif is_trf:
                freq, spl, phase_deg, coh = load_trf(path)
            else:
                freq, spl, phase_deg = load_frd(path)
        except Exception as e:
            QMessageBox.warning(self, "FRD/TRF/CLF",
                                f"No se pudo leer el archivo:\n{e}")
            return
        if is_clf:
            QMessageBox.information(
                self, "CLF cargado (respuesta en eje)",
                "Se cargó la respuesta EN EJE del CLF (sensibilidad SPL @1W/1m, "
                "1/3 de octava 50 Hz–20 kHz).\n\nLa directividad del globo se "
                "descarta a propósito: bajo la frecuencia de Schroeder la fuente "
                "es omnidireccional y el globo no moldea el campo modal.")
        if is_trf:
            # TF dual-channel: dB relativos (~0 en banda), no SPL absoluto.
            # Anclaje "Absoluto" mapearia 0 dB -> 20 uPa @1m (absurdo). Se
            # preselecciona Relativo (forma del TRF; nivel = sensibilidad).
            # blockSignals: _rebake_frd corre una sola vez, al final.
            self.combo_anchor.blockSignals(True)
            self.combo_anchor.setCurrentIndex(1)
            self.combo_anchor.blockSignals(False)
            coh_med = float(np.median(coh))
            if coh_med < 0.7:
                QMessageBox.information(
                    self, "TRF: coherencia baja",
                    f"La coherencia mediana de la medicion es {coh_med:.2f} "
                    f"(< 0.70). La curva puede tener zonas dominadas por "
                    f"ruido/reverberancia; usala con criterio.")
        if phase_deg is None:
            ans = QMessageBox.question(
                self, "Fase ausente",
                "El FRD no trae columna de fase.\n\n"
                "Sí = sintetizar fase mínima (Hilbert)\n"
                "No = asumir fase cero",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            phase_rad = (minimum_phase(freq, spl) if ans == QMessageBox.Yes
                         else np.zeros_like(freq))
        else:
            phase_rad = np.deg2rad(phase_deg)
        import os
        self._frd_raw = (freq, spl, phase_rad, os.path.basename(path))
        self._rebake_frd()

    def _rebake_frd(self):
        """Re-hornea g(f) desde el FRD crudo (solo si se cargó en esta sesión)."""
        if self._frd_raw is None:
            return
        from sources import SourceResponse
        freq, spl, phase_rad, name = self._frd_raw
        self._response = SourceResponse.from_frd(
            freq, spl, phase_rad,
            anchor=self.combo_anchor.currentData(),
            q_base=self._q_base(), f_ref=self._F_REF, name=name)
        self._refresh_resp_ui()

    # v2.25: delay/fase dejaron de hornearse en la curva (eran _apply_manual +
    # boton "Aplicar" + override de accept). Ahora son campos de la fuente
    # (self.sb_delay / self.sb_phase -> src.delay_s / src.phase_deg en get_source)
    # que se componen al calcular. El preview los muestra en vivo (_draw_resp_preview).

    def _clear_resp(self):
        """Quita la curva g(f). NO toca la polaridad: es del cableado, no de
        la respuesta medida, y borrar una no tiene por qué borrar la otra."""
        self._response = None
        self._frd_raw = None
        self.sb_delay.setValue(0.0)
        self.sb_phase.setValue(0.0)
        self._refresh_resp_ui()

    def _on_drv_mode_changed(self):
        """Muestra los campos fc/Qtc o los TS crudos según el modo elegido."""
        ts = (self.combo_drv_mode.currentData() == "ts")
        self._drv_direct.setVisible(not ts)
        self._drv_ts.setVisible(ts)

    def _apply_driver(self):
        """Construye un DriverModel (Thiele-Small, caja sellada) y lo aplica
        como la curva Q(f) de la fuente (S2 del modelo de fuente exacto). La
        forma (rolloff + fase) la pone el driver; el nivel, la sensibilidad
        (anclaje relativo). Es una alternativa a cargar un FRD/CLF."""
        import numpy as _np
        import driver as _drv
        mode = self.combo_drv_mode.currentData()
        try:
            if mode == "ts":
                d = _drv.DriverModel(fs=self.sb_drv_fs.value(),
                                     Qts=self.sb_drv_qts.value(),
                                     Vas=self.sb_drv_vas.value(),
                                     Vb=self.sb_drv_vb.value())
            else:
                d = _drv.DriverModel(fc=self.sb_drv_fc.value(),
                                     Qtc=self.sb_drv_qtc.value())
            # La curva cubre hasta f_ref (la sensibilidad ancla ahí, |g(f_ref)|=1).
            fpts = _np.linspace(5.0, max(600.0, self._F_REF * 1.2), 2000)
            self._response = d.to_response(
                freq_pts=fpts, f_ref=self._F_REF, anchor="relative",
                name=f"driver fc={d.fc:.0f}Hz Qtc={d.Qtc:.2f}")
        except Exception as e:
            QMessageBox.warning(self, "Driver Thiele-Small",
                                f"No se pudo construir el driver:\n{e}")
            return
        self._frd_raw = None    # curva sintética, no un FRD cargado
        self._refresh_resp_ui()

    def _refresh_resp_ui(self):
        r = self._response
        has = r is not None
        self.btn_clear_resp.setEnabled(has)
        # El anclaje solo aplica a un FRD cargado en esta sesión (necesita el
        # SPL crudo para re-hornear). Curvas manuales o cargadas del .room no.
        self.combo_anchor.setEnabled(self._frd_raw is not None)
        if not has:
            self.lbl_resp.setText(
                "Sin curva → <b>Q constante</b> (respuesta plana, como hasta hoy).")
        else:
            try:
                fmin, fmax, npts = r.coverage()
                extra = (f" · anclaje {r.anchor}"
                         if getattr(r, "anchor", "") else "")
                self.lbl_resp.setText(
                    f"Curva: <b>{r.name or '—'}</b> · {fmin:.0f}–{fmax:.0f} Hz, "
                    f"{npts} pts{extra}")
            except Exception:
                self.lbl_resp.setText("Curva cargada.")
        self._draw_resp_preview()

    def _on_filter_type_changed(self):
        """Repuebla los órdenes válidos y muestra/oculta ripple/atten según la
        familia. Con tipo 'none' deshabilita los controles. Redibuja el preview."""
        import filters as _flt
        ftype = self.combo_filt.currentData()
        is_none = (ftype in (None, "none"))
        # órdenes válidos
        cur = self.combo_filt_order.currentData()
        self.combo_filt_order.blockSignals(True)
        self.combo_filt_order.clear()
        for o in _flt.valid_orders(ftype if not is_none else "butterworth"):
            self.combo_filt_order.addItem(str(o), o)
        want = cur if cur is not None else self._filt0.get("order", 4)
        j = self.combo_filt_order.findData(want)
        self.combo_filt_order.setCurrentIndex(j if j >= 0 else 0)
        self.combo_filt_order.blockSignals(False)
        # ripple/atten según la familia
        _lbl, uses_ripple, uses_atten = _flt.FILTER_TYPES.get(
            ftype, ("", False, False))
        for w, on in ((self.lbl_filt_ripple, uses_ripple),
                      (self.sb_filt_ripple, uses_ripple),
                      (self.lbl_filt_atten, uses_atten),
                      (self.sb_filt_atten, uses_atten)):
            w.setVisible(on and not is_none)
        for w in (self.combo_filt_kind, self.combo_filt_order, self.sb_filt_fc):
            w.setEnabled(not is_none)
        self._draw_resp_preview()

    def _filter_state(self) -> dict:
        """Lee los controles de filtro -> dict de campos de OmniSource."""
        return {
            "filter_type": self.combo_filt.currentData() or "none",
            "filter_order": int(self.combo_filt_order.currentData() or 4),
            "filter_fc": float(self.sb_filt_fc.value()),
            "filter_kind": self.combo_filt_kind.currentData() or "lowpass",
            "filter_ripple_db": float(self.sb_filt_ripple.value()),
            "filter_atten_db": float(self.sb_filt_atten.value()),
        }

    def _draw_resp_preview(self):
        if self._resp_canvas is None:
            return
        try:
            # set_xscale('linear') antes de clear() evita el warning de xlim
            # no-positivo cuando el eje venía en log y no hay datos nuevos.
            for ax in (self._resp_ax_m, self._resp_ax_p):
                ax.set_xscale('linear')
                ax.clear()
            # Delay/fase (campos) se COMPONEN sobre la curva/plana para el preview
            # (convencion e^{+iωt}: retardo tau -> fase -2πfτ). |factor|=1 -> la
            # magnitud no cambia; la fase muestra la recta del delay + el offset.
            tau = self.sb_delay.value() / 1000.0
            phi0 = np.radians(self.sb_phase.value())
            has_dp = (tau > 0.0 or abs(self.sb_phase.value()) > 1e-9)
            if self._response is not None:
                fmin, fmax, _ = self._response.coverage()
                fa = np.linspace(max(fmin, 1.0), fmax, 400)
                g = self._response.gain_spectrum(fa)
            else:
                # eje ancho si hay filtro, para que se vea el roll-off completo
                _fc = float(self.sb_filt_fc.value())
                _hi = 500.0 if self.combo_filt.currentData() in (None, "none") \
                    else max(2000.0, 4.0 * _fc)
                fa = np.geomspace(20.0, _hi, 300)
                g = np.ones_like(fa, dtype=complex)
            g = g * np.exp(-1j * 2.0 * np.pi * fa * tau + 1j * phi0)
            # Filtro (v2.29): compone H(f) sobre la curva/plana (magnitud + fase).
            fst = self._filter_state()
            has_filt = fst["filter_type"] not in (None, "none")
            if has_filt:
                import filters as _flt
                g = g * _flt.filter_transfer(
                    fa, ftype=fst["filter_type"], order=fst["filter_order"],
                    fc=fst["filter_fc"], kind=fst["filter_kind"],
                    ripple_db=fst["filter_ripple_db"], atten_db=fst["filter_atten_db"])
            solid = (self._response is not None) or has_dp or has_filt
            col_m = '#1f6fbf' if solid else '#888888'
            col_p = '#e07000' if solid else '#888888'
            ls = '-' if solid else '--'
            self._resp_ax_m.semilogx(
                fa, 20 * np.log10(np.maximum(np.abs(g), 1e-9)),
                color=col_m, lw=1.4, ls=ls)
            self._resp_ax_p.semilogx(fa, np.degrees(np.angle(g)),
                                     color=col_p, lw=1.4, ls=ls)
            if self._response is None:
                self._resp_ax_m.set_ylim(-42 if has_filt else -12, 12)
                self._resp_ax_p.set_ylim(-180, 180)
                if has_filt:
                    _t = f"filtro {fst['filter_type']} · fc={fst['filter_fc']:.0f} Hz"
                elif has_dp:
                    _t = "delay / fase (magnitud plana)"
                else:
                    _t = "default: plana (Q constante)"
                self._resp_ax_m.set_title(_t, fontsize=7, color='#666666')
            self._resp_ax_m.set_ylabel("g [dB]", fontsize=7)
            self._resp_ax_p.set_ylabel("fase [°]", fontsize=7)
            self._resp_ax_p.set_xlabel("Hz", fontsize=7)
            for ax in (self._resp_ax_m, self._resp_ax_p):
                ax.tick_params(labelsize=6)
                ax.grid(True, which='both', alpha=0.3)
            self._resp_fig.tight_layout(pad=0.4)
            self._resp_canvas.draw_idle()
        except Exception:
            pass

    def _snap_to_wall(self):
        """Pega la fuente flush a la pared más cercana y orienta el frente hacia
        adentro. One-shot: setea posición + azimut + pitch + mounted=True."""
        try:
            walls = self._get_walls() if self._get_walls else None
        except Exception as e:
            walls = None
        if not walls:
            QMessageBox.information(self, "Sin paredes",
                                     "No hay geometría para pegar la fuente.")
            return
        cents = [np.asarray(c, float) for c, _ in walls]
        room_center = np.mean(cents, axis=0)
        p = np.array([self.sb_x.value(), self.sb_y.value(), self.sb_z.value()],
                     dtype=float)
        best = None
        for c, n in walls:
            c = np.asarray(c, float); n = np.asarray(n, float)
            nn = np.linalg.norm(n)
            if nn < 1e-9:
                continue
            n = n / nn
            dist = abs(float(np.dot(p - c, n)))
            if best is None or dist < best[0]:
                best = (dist, c, n)
        if best is None:
            return
        _, c, n = best
        p_wall = p - float(np.dot(p - c, n)) * n            # pie de perpendicular
        # Normal interior (robusto a la orientación del winding): la que apunta
        # hacia el centro del recinto.
        inward = n if float(np.dot(n, room_center - p_wall)) > 0 else -n
        d = float(self.sb_bd.value())
        p_new = p_wall + (d / 2.0) * inward
        yaw = float(np.degrees(np.arctan2(inward[1], inward[0]))) % 360.0
        pitch = float(np.degrees(np.arcsin(np.clip(inward[2], -1.0, 1.0))))
        self.sb_x.setValue(float(p_new[0]))
        self.sb_y.setValue(float(p_new[1]))
        self.sb_z.setValue(float(p_new[2]))
        self.sb_orient.setValue(yaw)
        self.sb_pitch.setValue(pitch)
        self._mounted = True
        self.lbl_mounted.setText("Montada en pared ✓")

    def get_source(self) -> OmniSource:
        from sources import OmniSource
        src = OmniSource(
            position=(self.sb_x.value(), self.sb_y.value(), self.sb_z.value()),
            label=self.le_label.text().strip() or "src",
            sensitivity_dB=self.sb_sens.value(),
            power_W=1.0,
            f_ref=self._F_REF,
            orientation=self.sb_orient.value(),
            baffle_size=(self.sb_bw.value(), self.sb_bh.value(), self.sb_bd.value()),
            pitch=self.sb_pitch.value(),
            mounted=self._mounted,
            polarity=(-1 if self.chk_polarity.isChecked() else 1),
            delay_s=self.sb_delay.value() / 1000.0,     # v2.25: campos propios
            phase_deg=self.sb_phase.value(),
            **self._filter_state(),                     # v2.29: filtro
        )
        src.response = self._response    # Fase 2: preservar la curva Q(f)
        return src


# ---------------------------------------------------------------------------
# Dialogo FRF (grafico matplotlib)
# ---------------------------------------------------------------------------
def _contiguous_runs(fa, mask):
    """Devuelve [(f_ini, f_fin), ...] de las corridas contiguas donde mask es True."""
    spans, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            spans.append((float(fa[i]), float(fa[j])))
            i = j + 1
        else:
            i += 1
    return spans


class FurnitureEditDialog(QDialog):
    """Editor de un mueble (caja/cilindro), edición numérica exacta.

    Devuelve `(Furniture, nombre_material | None)` via `get_furniture()`. El
    material None = mueble RÍGIDO (obstáculo sin absorción, α default 0.03). El
    mueble se persiste en el `.room` y afecta modos (carve), RT/ξ (A36) y SBIR.
    Esta versión NO arrastra el mueble en el visor (edición por spinbox); el
    drag 3D queda para un paso posterior.
    """

    _KINDS = [("box", "Caja"), ("cylinder", "Cilindro")]
    _RIGID = "Rígido (sin material)"

    def __init__(self, furn=None, mat_name=None, mat_names=None,
                 dims_hint=None, default_pos=None, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Editar mueble" if furn is not None else "Añadir mueble")
        mat_names = list(mat_names or [])
        Lx, Ly, _Lz = dims_hint or (5.0, 4.0, 3.0)
        # Un preset (compound) tiene forma fija: se edita posición/orientación/
        # material/etiqueta, NO tipo ni tamaño (se preservan sus partes).
        self._compound_src = (furn if furn is not None
                              and getattr(furn, "kind", "") == "compound" else None)
        # Un mueble CAD (kind="mesh") tiene forma fija importada: se edita
        # posición/orientación/material/etiqueta, NO tipo ni tamaño (se preserva
        # la malla). Mismo trato que un preset compound.
        self._mesh_src = (furn if furn is not None
                          and getattr(furn, "kind", "") == "mesh" else None)
        self._mat_names = mat_names
        self._default_pos = default_pos
        self._dims = (Lx, Ly)

        form = QFormLayout(self)

        self.combo_kind = QComboBox()
        for _, label in self._KINDS:
            self.combo_kind.addItem(label)
        form.addRow("Tipo:", self.combo_kind)

        # Centro (posición)
        self.sb_x = self._spin(-1e3, 1e3, 3, 0.1)
        self.sb_y = self._spin(-1e3, 1e3, 3, 0.1)
        self.sb_z = self._spin(-1e3, 1e3, 3, 0.1)
        prow = QHBoxLayout(); prow.setSpacing(3)
        for lbl, sb in (("X", self.sb_x), ("Y", self.sb_y), ("Z", self.sb_z)):
            prow.addWidget(QLabel(lbl)); prow.addWidget(sb, 1)
        form.addRow("Centro (m):", prow)

        # Tamaño (los labels cambian según el tipo)
        self.sb_sx = self._spin(0.01, 1e3, 3, 0.05)
        self.sb_sy = self._spin(0.01, 1e3, 3, 0.05)
        self.sb_sz = self._spin(0.01, 1e3, 3, 0.05)
        self.lbl_sx, self.lbl_sy, self.lbl_sz = QLabel("An"), QLabel("La"), QLabel("Al")
        srow = QHBoxLayout(); srow.setSpacing(3)
        for lbl, sb in ((self.lbl_sx, self.sb_sx), (self.lbl_sy, self.sb_sy),
                        (self.lbl_sz, self.sb_sz)):
            srow.addWidget(lbl); srow.addWidget(sb, 1)
        form.addRow("Tamaño (m):", srow)

        # Orientación (yaw) e inclinación (pitch), solo caja.
        self.sb_orient = self._spin(-360, 360, 1, 5.0)
        self.sb_orient.setSuffix(" °")
        form.addRow("Orientación (yaw):", self.sb_orient)
        self.sb_pitch = self._spin(-90, 90, 1, 5.0)
        self.sb_pitch.setSuffix(" °")
        form.addRow("Inclinación (pitch):", self.sb_pitch)
        self.sb_roll = self._spin(-180, 180, 1, 5.0)
        self.sb_roll.setSuffix(" °")
        self.sb_roll.setToolTip("Vuelca el mueble de costado (gira sobre su frente).")
        form.addRow("Vuelco (roll):", self.sb_roll)

        # Material (Rígido = sin absorción)
        self.combo_mat = QComboBox()
        self.combo_mat.addItem(self._RIGID)
        self.combo_mat.addItems(mat_names)
        form.addRow("Material:", self.combo_mat)

        self.ed_label = QLineEdit()
        form.addRow("Etiqueta:", self.ed_label)
        self.ed_prov = QLineEdit()
        self.ed_prov.setPlaceholderText("medida propia / catálogo / …")
        form.addRow("Procedencia:", self.ed_prov)

        # Importar CAD (OBJ/STL/PLY…): trae una malla como mueble kind="mesh".
        self.btn_import_cad = QPushButton("Importar CAD (OBJ)…")
        self.btn_import_cad.setToolTip(
            "Cargar una malla 3D (OBJ, STL, PLY). Ideal: escanear el estudio y "
            "exportar cada pieza por separado. La malla debe ser cerrada "
            "(watertight) para que el tallado sea confiable.")
        self.btn_import_cad.clicked.connect(self._on_import_cad)
        self.lbl_cad = QLabel("")
        self.lbl_cad.setWordWrap(True)
        crow = QHBoxLayout(); crow.setSpacing(6)
        crow.addWidget(self.btn_import_cad); crow.addWidget(self.lbl_cad, 1)
        form.addRow("CAD:", crow)

        fixed_src = self._compound_src or self._mesh_src
        if fixed_src is not None:
            # Preset compound o mesh CAD: forma fija -> bloquear tipo y tamaño.
            self._lock_fixed_geometry(fixed_src, mat_name, mat_names)
        elif furn is not None:
            self.combo_kind.setCurrentIndex(
                1 if getattr(furn, "kind", "box") == "cylinder" else 0)
            px, py, pz = furn.position
            self.sb_x.setValue(px); self.sb_y.setValue(py); self.sb_z.setValue(pz)
            sx, sy, sz = furn.size
            self.sb_sx.setValue(sx); self.sb_sy.setValue(sy); self.sb_sz.setValue(sz)
            self.sb_orient.setValue(float(getattr(furn, "orientation", 0.0) or 0.0))
            self.sb_pitch.setValue(float(getattr(furn, "pitch", 0.0) or 0.0))
            self.sb_roll.setValue(float(getattr(furn, "roll", 0.0) or 0.0))
            self.ed_label.setText(str(getattr(furn, "label", "") or ""))
            self.ed_prov.setText(str(getattr(furn, "provenance", "") or ""))
            if mat_name and mat_name in mat_names:
                self.combo_mat.setCurrentText(mat_name)
        else:
            # Default: centro real de la sala (bbox) apoyado en el piso. El
            # frame del recinto está centrado en el origen -> NO asumir esquina.
            if default_pos is not None:
                self.sb_x.setValue(float(default_pos[0]))
                self.sb_y.setValue(float(default_pos[1]))
                self.sb_z.setValue(float(default_pos[2]))
            else:
                self.sb_x.setValue(Lx / 2.0); self.sb_y.setValue(Ly / 2.0)
                self.sb_z.setValue(0.45)
            self.sb_sx.setValue(0.8); self.sb_sy.setValue(0.8); self.sb_sz.setValue(0.9)
            self.ed_label.setText("mueble")

        self.combo_kind.currentIndexChanged.connect(self._on_kind_changed)
        self._on_kind_changed()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    @staticmethod
    def _spin(lo, hi, dec, step):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi); sb.setDecimals(dec); sb.setSingleStep(step)
        sb.setMinimumWidth(0); sb.setMaximumWidth(95)
        return sb

    def _kind(self):
        return self._KINDS[self.combo_kind.currentIndex()][0]

    def _lock_fixed_geometry(self, src, mat_name, mat_names):
        """Bloquea tipo+tamaño y puebla placement desde un mueble de forma fija
        (preset compound o mesh CAD). El tamaño se muestra desde el AABB."""
        self.combo_kind.setEnabled(False)
        for w in (self.sb_sx, self.sb_sy, self.sb_sz,
                  self.lbl_sx, self.lbl_sy, self.lbl_sz):
            w.setEnabled(False)
        is_mesh = getattr(src, "kind", "") == "mesh"
        lo, hi = src.aabb(); d = hi - lo
        self.lbl_sx.setText("(CAD)" if is_mesh else "(preset)")
        self.sb_sx.setValue(float(d[0])); self.sb_sy.setValue(float(d[1]))
        self.sb_sz.setValue(float(d[2]))
        px, py, pz = src.position
        self.sb_x.setValue(px); self.sb_y.setValue(py); self.sb_z.setValue(pz)
        self.sb_orient.setValue(float(getattr(src, "orientation", 0.0) or 0.0))
        self.sb_pitch.setValue(float(getattr(src, "pitch", 0.0) or 0.0))
        self.sb_roll.setValue(float(getattr(src, "roll", 0.0) or 0.0))
        self.ed_label.setText(str(getattr(src, "label", "") or ""))
        self.ed_prov.setText(str(getattr(src, "provenance", "") or ""))
        if mat_name and mat_name in (mat_names or []):
            self.combo_mat.setCurrentText(mat_name)
        if is_mesh and src.mesh_faces is not None:
            self.lbl_cad.setText(f"malla: {len(src.mesh_faces)} caras")

    def _on_import_cad(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar CAD", "",
            "Mallas 3D (*.obj *.stl *.ply *.off *.glb *.gltf);;Todos (*)")
        if not path:
            return
        try:
            import furniture
            furn, warns = furniture.load_furniture_mesh(path)
        except Exception as e:
            QMessageBox.warning(self, "Importar CAD", f"No se pudo importar:\n{e}")
            return
        # Reubicar en la sala: XY en el default, apoyado en el piso (z=0). La
        # malla se guarda centrada en su bbox, asi que position.z = alto/2 deja
        # el fondo en z=0.
        sx, sy, sz = furn.size
        if self._default_pos is not None:
            cx, cy = float(self._default_pos[0]), float(self._default_pos[1])
        else:
            cx, cy = self._dims[0] / 2.0, self._dims[1] / 2.0
        furn.position = (cx, cy, float(sz) / 2.0)
        self._mesh_src = furn
        self._compound_src = None
        self._lock_fixed_geometry(furn, None, self._mat_names)
        if warns:
            QMessageBox.warning(self, "Importar CAD", "\n".join(warns))

    def _on_kind_changed(self):
        if self._compound_src is not None or self._mesh_src is not None:
            return   # forma fija (preset/CAD): no tocar los campos bloqueados
        cyl = self._kind() == "cylinder"
        # Cilindro: size = (diámetro, _, alto); el 2º lado y el yaw no aplican.
        self.lbl_sx.setText("Diám" if cyl else "An")
        self.lbl_sy.setVisible(not cyl)
        self.sb_sy.setVisible(not cyl)
        self.sb_orient.setEnabled(not cyl)
        self.sb_pitch.setEnabled(not cyl)
        self.sb_roll.setEnabled(not cyl)

    def get_furniture(self):
        from furniture import Furniture
        if self._compound_src is not None:
            src = self._compound_src
            furn = Furniture(
                kind="compound",
                parts=[Furniture.from_dict(p.to_dict()) for p in (src.parts or [])],
                position=(float(self.sb_x.value()), float(self.sb_y.value()),
                          float(self.sb_z.value())),
                orientation=float(self.sb_orient.value()),
                pitch=float(self.sb_pitch.value()),
                roll=float(self.sb_roll.value()),
                label=self.ed_label.text().strip() or src.label,
                provenance=self.ed_prov.text().strip())
            mat = (self.combo_mat.currentText()
                   if self.combo_mat.currentIndex() > 0 else None)
            return furn, mat
        if self._mesh_src is not None:
            src = self._mesh_src
            furn = Furniture(
                kind="mesh",
                mesh_verts=src.mesh_verts, mesh_faces=src.mesh_faces,
                size=src.size,
                position=(float(self.sb_x.value()), float(self.sb_y.value()),
                          float(self.sb_z.value())),
                orientation=float(self.sb_orient.value()),
                pitch=float(self.sb_pitch.value()),
                roll=float(self.sb_roll.value()),
                label=self.ed_label.text().strip() or src.label,
                provenance=self.ed_prov.text().strip() or src.provenance)
            mat = (self.combo_mat.currentText()
                   if self.combo_mat.currentIndex() > 0 else None)
            return furn, mat
        kind = self._kind()
        if kind == "cylinder":
            diam = float(self.sb_sx.value())
            size = (diam, diam, float(self.sb_sz.value()))
            orient = pitch = roll = 0.0
        else:
            size = (float(self.sb_sx.value()), float(self.sb_sy.value()),
                    float(self.sb_sz.value()))
            orient = float(self.sb_orient.value())
            pitch = float(self.sb_pitch.value())
            roll = float(self.sb_roll.value())
        furn = Furniture(
            kind=kind,
            position=(float(self.sb_x.value()), float(self.sb_y.value()),
                      float(self.sb_z.value())),
            size=size, orientation=orient, pitch=pitch, roll=roll,
            label=self.ed_label.text().strip() or "mueble",
            provenance=self.ed_prov.text().strip())
        mat = self.combo_mat.currentText() if self.combo_mat.currentIndex() > 0 else None
        return furn, mat


class FRFDialog(QDialog):
    """Diálogo de FRF con gráfico matplotlib, exportación y escucha con ruido rosa."""

    def __init__(self, frf_result, modal_freqs=None, parent=None,
                 fom=None, fom_band=None, eqc=None, eqc_band=None, f_valid=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle(f"FRF — {frf_result.method.upper()}")
        self.resize(980, 580)
        self._fig = None
        self._H   = frf_result.H              # guardar para audio
        self._f   = frf_result.freq_axis
        v = QVBoxLayout(self)

        if not _HAS_MPL:
            v.addWidget(QLabel("matplotlib no disponible. pip install matplotlib"))
            return

        _P_REF = 20e-6
        H = frf_result.H
        f = frf_result.freq_axis
        db = 20.0 * np.log10(np.maximum(np.abs(H), 1e-30) / _P_REF)

        self._fig, ax = plt.subplots(figsize=(9.5, 4.2), dpi=96)
        self._fig.patch.set_facecolor('#f0f0f0')
        ax.set_facecolor('#ffffff')

        # C1 (auditoria 2026-09-04): por encima de f_valid = min(f_max_malla,
        # ultimo modo) la superposicion modal es cola-suma truncada y/o esta fuera
        # de la validez numerica de la malla (hasta 27 dB de error). Se dibuja la
        # curva VALIDA en solido y la INVALIDA en gris punteado, y se sombrea la banda.
        fv = float(f_valid) if (f_valid is not None and f_valid > float(f[0])) else None
        if fv is not None and fv < float(f[-1]):
            mvalid = f <= fv
            ax.plot(f[mvalid], db[mvalid], color='#1f6fbf', linewidth=1.8,
                    label='FRF (FEM) · banda válida')
            # incluir el punto de cruce para que la curva no quede cortada
            minv = f >= fv
            ax.plot(f[minv], db[minv], color='#9aa0a6', linewidth=1.3,
                    linestyle=':', label='Fuera de banda válida (no confiable)')
            ax.axvspan(fv, float(f[-1]), color='#9aa0a6', alpha=0.16, zorder=0)
            ax.axvline(x=fv, color='#666666', linestyle='-.', linewidth=1.0,
                       alpha=0.8)
        else:
            ax.plot(f, db, color='#1f6fbf', linewidth=1.8, label='FRF (FEM)')

        if modal_freqs is not None:
            for i, fn in enumerate(modal_freqs):
                if float(f[0]) <= fn <= float(f[-1]):
                    ax.axvline(x=fn, color='#e07000', linestyle='--',
                               linewidth=1.3, alpha=0.75,
                               label='Modos FEM' if i == 0 else '_nolegend_')

        # --- Overlay de corregibilidad EQ (C13/C21): sombrear lo NO ecualizable ---
        if eqc is not None:
            fe, vd = eqc.freq_axis, eqc.verdict
            first_no = first_unc = True
            for f0, f1 in _contiguous_runs(fe, vd == 0):       # no corregible -> rojo
                ax.axvspan(f0, f1, color='#e05050', alpha=0.13, zorder=0,
                           label='No ecualizable (exige acústica)' if first_no else '_nolegend_')
                first_no = False
            for f0, f1 in _contiguous_runs(fe, vd == 1):       # incierto -> amarillo
                ax.axvspan(f0, f1, color='#e0b020', alpha=0.10, zorder=0,
                           label='Corregibilidad incierta' if first_unc else '_nolegend_')
                first_unc = False

        ax.set_xlabel('Frecuencia (Hz)', fontsize=10)
        ax.set_ylabel('Nivel SPL (dB re 20 µPa)', fontsize=10)
        ax.set_title('Respuesta en Frecuencia (FRF)',
                     fontweight='bold', fontsize=11, pad=8)

        # Grilla de 1/3 de octava (ISO 266): xticks en los bordes de banda,
        # eje log, look tipo REW. Permite leer en que banda cae cada modo.
        from matplotlib.ticker import FixedLocator, NullLocator, FuncFormatter
        from plot_utils import third_octave_edges
        edges = third_octave_edges(float(f[0]), float(f[-1]))
        if len(edges) >= 2:
            ax.set_xscale('log')
            ax.set_xlim(float(f[0]), float(f[-1]))
            ax.xaxis.set_major_locator(FixedLocator(edges))
            ax.xaxis.set_major_formatter(
                FuncFormatter(lambda x, _: f"{x:.0f}"))
            ax.xaxis.set_minor_locator(NullLocator())
        # Grilla vertical tenue en los bordes de banda; horizontal normal.
        ax.grid(True, which='major', axis='x', linestyle='-',
                linewidth=0.7, alpha=0.3, color='#bbbbbb')
        ax.grid(True, which='major', axis='y', linestyle='-',
                linewidth=0.7, alpha=0.6, color='#cccccc')
        ax.legend(fontsize=9, framealpha=0.85, loc='upper right')
        ax.tick_params(labelsize=9)
        self._fig.tight_layout(pad=1.2)

        canvas = FigureCanvas(self._fig)
        toolbar = NavigationToolbar(canvas, self)
        v.addWidget(toolbar)
        v.addWidget(canvas, 1)

        # --- Figura de merito (2c §8), si el caller la calculo ---
        if fom is not None:
            band_txt = ""
            if fom_band is not None:
                band_txt = (f"   (banda ≤ {fom_band[1]:.0f} Hz, "
                            f"{fom_band[2]} receptores)")
            fom_lbl = QLabel(
                f"FoM — planitud (FoM_flat): {fom.FoM_flat:.2f} dB"
                f"     ·     consistencia espacial (FoM_espacial): "
                f"{fom.FoM_espacial:.2f} dB" + band_txt
            )
            fom_lbl.setStyleSheet("color:#11111b; font-size:9pt; font-weight:600;")
            fom_lbl.setWordWrap(True)
            fom_lbl.setToolTip(
                "FoM_flat: planitud de la respuesta media espacial (más bajo = "
                "timbre más plano).\nFoM_espacial: dispersión asiento-a-asiento "
                "(más bajo = la sala suena parecido en toda la zona).\n"
                "Con damping de materiales, suavizado en energía 1/3 oct, sobre "
                "la grilla de receptores y solo en la banda válida de la malla."
            )
            v.addWidget(fom_lbl)

        # --- Diagnóstico de corregibilidad EQ (C13/C21), si el caller lo calculo ---
        if eqc is not None:
            band_txt = (f" (banda ≤ {eqc_band[1]:.0f} Hz)"
                        if eqc_band is not None else "")
            sube = ""
            if (eqc_band is not None and fom_band is not None
                    and eqc_band[1] < fom_band[1] - 1.0):
                sube = "   (subí npm para diagnosticar más arriba)"
            eq_lbl = QLabel(
                f"Corregibilidad EQ{band_txt}: el EQ global aplana la media en "
                f"{eqc.improvement_flat:.1f} dB · queda {eqc.fom_espacial:.1f} dB "
                f"irreducible (varía asiento-a-asiento). Zonas en rojo = NO se "
                f"arreglan con EQ → exigen acústica/ubicación." + sube
            )
            eq_lbl.setStyleSheet("color:#11111b; font-size:9pt; font-weight:600;")
            eq_lbl.setWordWrap(True)
            eq_lbl.setToolTip(
                "Diagnóstico C13/C21 (fase mínima vs no mínima):\n"
                "• Un EQ global (mismo para todos los asientos) solo arregla lo que es "
                "consistente espacialmente y de fase mínima.\n"
                "• FoM_espacial es la cota IRREDUCIBLE: un EQ global no puede tocar la "
                "varianza asiento-a-asiento (es ganancia común).\n"
                "• Rojo = nulos por cancelación/SBIR o que varían con la posición → "
                "exigen geometría/ubicación/absorción, no DSP.\n"
                "Sala-sola (no incluye delay/polaridad de fuente, que son del drive)."
            )
            v.addWidget(eq_lbl)

        # --- Fila de controles de audio ---
        audio_row = QHBoxLayout()

        self.btn_play = QPushButton("🔊  Escuchar  (ruido rosa + FRF)")
        self.btn_play.setObjectName("PrimaryButton")
        self.btn_play.setMinimumWidth(220)
        self.btn_play.clicked.connect(self._play_audio)
        audio_row.addWidget(self.btn_play)

        btn_stop = QPushButton("⏹  Detener")
        btn_stop.setMinimumWidth(90)
        btn_stop.clicked.connect(self._stop_audio)
        audio_row.addWidget(btn_stop)

        self.lbl_audio_status = QLabel("")
        self.lbl_audio_status.setStyleSheet("color:#6c6f85; font-size:8pt;")
        audio_row.addWidget(self.lbl_audio_status, 1)

        v.addLayout(audio_row)

        # --- Fila de info + exportar ---
        brow = QHBoxLayout()
        peaks = self._peak_indices(db, k=5)
        lbl = QLabel("Picos: " + ", ".join(f"{f[i]:.1f} Hz" for i in peaks)
                     + ("  ·  Naranja = modos FEM" if modal_freqs is not None else ""))
        lbl.setStyleSheet("color:#555; font-size:8pt;")
        brow.addWidget(lbl, 1)
        for fmt in ("PNG", "SVG", "PDF", "CSV", "TXT"):
            b = QPushButton(f"Exportar {fmt}")
            b.setMinimumWidth(140)       # texto "Exportar XXX" + padding QSS
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._export(f))
            brow.addWidget(b)
        v.addLayout(brow)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        v.addWidget(btns)

    # -----------------------------------------------------------------------
    def _play_audio(self):
        """Genera ruido rosa, filtra con H(f) y reproduce."""
        import audio_utils as au
        err = au.check_audio()
        if err:
            QMessageBox.information(self, "Audio no disponible", err)
            return
        try:
            self.btn_play.setEnabled(False)
            self.lbl_audio_status.setText("Generando señal…")
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

            noise    = au.pink_noise(duration=4.0)
            filtered = au.apply_frf_filter(noise, self._H, self._f)
            au.play(filtered)
            self.lbl_audio_status.setText(
                f"▶ Reproduciendo  ({len(self._f)} puntos de FRF, "
                f"{self._f[0]:.0f}–{self._f[-1]:.0f} Hz)"
            )
        except Exception as e:
            self.lbl_audio_status.setText(f"Error: {e}")
        finally:
            self.btn_play.setEnabled(True)

    def _stop_audio(self):
        import audio_utils as au
        au.stop()
        self.lbl_audio_status.setText("⏹ Detenido.")

    def closeEvent(self, ev):
        self._stop_audio()
        super().closeEvent(ev)

    # -----------------------------------------------------------------------
    def _export(self, fmt: str):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar como {fmt.upper()}",
            f"frf.{fmt}", f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        if fmt in ('csv', 'txt'):
            _P_REF = 20e-6
            f = np.asarray(self._f)
            H = np.asarray(self._H)
            absH = np.abs(H)
            db = 20.0 * np.log10(np.maximum(absH, 1e-30) / _P_REF)
            phase_deg = np.degrees(np.angle(H))
            header = ['freq_hz', 'spl_db', 'abs_H_pa', 'phase_deg']
            rows = [(float(f[i]), float(db[i]), float(absH[i]), float(phase_deg[i]))
                    for i in range(len(f))]
            _write_tabular(path, header, rows, fmt)
        elif self._fig:
            self._fig.savefig(path, dpi=300, bbox_inches='tight', facecolor='white')

    @staticmethod
    def _peak_indices(arr, k=5):
        peaks = []
        for i in range(1, len(arr) - 1):
            if arr[i] > arr[i - 1] and arr[i] > arr[i + 1]:
                peaks.append((arr[i], i))
        peaks.sort(reverse=True)
        return [i for _, i in peaks[:k]]


# ---------------------------------------------------------------------------
# Dialogo SBIR (Speaker-Boundary Interference Response)
# ---------------------------------------------------------------------------
class SBIRDialog(QDialog):
    """Diálogo SBIR: peine de interferencia directo + reflexiones de 1er orden
    en el receptor, por fuente y para la suma estéreo. dB relativo al directo.
    """

    _COLORS = ['#2a9d8f', '#e76f51', '#8a5cd1', '#577590', '#bc6c25', '#386641']

    def __init__(self, result, f_lo: float = 20.0, f_hi: float = 500.0,
                 parent=None, modal_db=None, f_schroeder=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("SBIR — interferencia fuente-frontera")
        self.resize(980, 600)
        self._fig = None
        self._res = result
        self._flo, self._fhi = float(f_lo), float(f_hi)
        # Transferencia modal de la sala (FEM) normalizada a dB re directo, y f_S
        # para el hibrido. modal_db=None -> el toggle no aparece (sin modos).
        self._modal_db = (np.asarray(modal_db, dtype=float)
                          if modal_db is not None else None)
        self._f_s = float(f_schroeder) if f_schroeder else None
        self._chk_modal = None
        v = QVBoxLayout(self)

        if not _HAS_MPL:
            v.addWidget(QLabel("matplotlib no disponible. pip install matplotlib"))
            return

        self._fig, self._ax = plt.subplots(figsize=(9.5, 4.4), dpi=96)
        self._fig.patch.set_facecolor('#f0f0f0')
        self._ax.set_facecolor('#ffffff')
        self._canvas = FigureCanvas(self._fig)
        toolbar = NavigationToolbar(self._canvas, self)
        v.addWidget(toolbar)

        # Toggle: incluir la transferencia modal de la sala (hibrido en f_S).
        if self._modal_db is not None:
            from PyQt5.QtWidgets import QCheckBox
            self._chk_modal = QCheckBox(
                "Incluir transferencia modal de la sala (híbrido en f_Schroeder)")
            self._chk_modal.setChecked(True)
            self._chk_modal.setToolTip(
                "SBIR solo = directo + imágenes de 1er orden (campo libre).\n"
                "Con transferencia modal: superpone la respuesta modal FEM de la\n"
                "sala (misma referencia 0 dB = anecoico) y una curva TOTAL híbrida\n"
                "que usa la modal por debajo de f_Schroeder (donde es exacta) y las\n"
                "imágenes por encima (peine especular).")
            self._chk_modal.stateChanged.connect(lambda _s: self._rebuild_plot())
            v.addWidget(self._chk_modal)

        v.addWidget(self._canvas, 1)
        self._rebuild_plot()

        # --- Lectura: realce/atenuacion + distancias fuente-pared (estatico) ---
        res = self._res
        f_pk, realce, f_dip, aten = res.band_extremes(self._flo, self._fhi)
        info = QLabel(
            f"Realce máx: {realce:+.1f} dB @ {f_pk:.0f} Hz     ·     "
            f"Atenuación máx: {aten:+.1f} dB @ {f_dip:.0f} Hz"
        )
        info.setStyleSheet("color:#333; font-size:9pt; font-weight:600;")
        v.addWidget(info)

        notches = res.first_notches(self._flo, self._fhi)
        if notches:
            parts = []
            for n in notches[:8]:
                tag = f"{n.source_label}/" if len(res.per_source) > 1 else ""
                parts.append(f"{tag}{n.wall_label}: {n.distance:.2f} m → "
                             f"{n.f_notch:.0f} Hz")
            dist_lbl = QLabel("Notch por pared:  " + "   ·   ".join(parts))
            dist_lbl.setWordWrap(True)
            dist_lbl.setStyleSheet("color:#666; font-size:8pt;")
            v.addWidget(dist_lbl)

        # --- Fila exportar ---
        brow = QHBoxLayout()
        brow.addStretch(1)
        for fmt in ("PNG", "SVG", "PDF", "CSV", "TXT"):
            b = QPushButton(f"Exportar {fmt}")
            b.setMinimumWidth(140)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._export(f))
            brow.addWidget(b)
        v.addLayout(brow)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        v.addWidget(btns)

    def _rebuild_plot(self):
        """Dibuja (o redibuja) las curvas segun el toggle de transferencia modal."""
        import sbir
        ax = self._ax
        ax.clear()
        res = self._res
        f = res.freq_axis
        multi = len(res.per_source) > 1
        for i, src in enumerate(res.per_source):
            ax.plot(f, src.sbir_db, linewidth=1.3,
                    alpha=0.65 if multi else 1.0,
                    color=self._COLORS[i % len(self._COLORS)],
                    label=src.label)
        total_lbl = 'SBIR total (imágenes)' if multi else 'SBIR (imágenes)'
        if multi:
            ax.plot(f, res.total_sbir_db, color='#1f6fbf', linewidth=2.4,
                    label=total_lbl)

        show_modal = (self._chk_modal is not None and self._chk_modal.isChecked()
                      and self._modal_db is not None)
        if show_modal:
            ax.plot(f, self._modal_db, color='#8a5cd1', linewidth=1.6,
                    linestyle='--', label='Transferencia modal (sala)')
            if self._f_s:
                total_hybrid = sbir.modal_sbir_crossfade(
                    f, res.total_sbir_db, self._modal_db, self._f_s)
                ax.plot(f, total_hybrid, color='#c1121f', linewidth=2.6,
                        label='Total híbrido (modal + imágenes)')
                ax.axvline(self._f_s, color='#444444', linestyle='-.',
                           linewidth=1.0, alpha=0.7,
                           label=f'f_Schroeder ≈ {self._f_s:.0f} Hz')

        # Linea de referencia 0 dB (anecoico).
        ax.axhline(0.0, color='#888888', linewidth=0.8, linestyle='--',
                   alpha=0.6)

        # Marcadores de notch teorico c/(4d) por pared (dedup por frecuencia).
        seen = set()
        for n in res.first_notches(self._flo, self._fhi):
            key = round(n.f_notch, 1)
            if key in seen:
                continue
            seen.add(key)
            ax.axvline(x=n.f_notch, color='#e07000', linestyle=':',
                       linewidth=1.1, alpha=0.7,
                       label='Notch c/(4d)' if len(seen) == 1 else '_nolegend_')

        ax.set_xlabel('Frecuencia (Hz)', fontsize=10)
        ax.set_ylabel('Nivel (dB re directo)', fontsize=10)
        ax.set_title('SBIR — directo + reflexiones de 1er orden',
                     fontweight='bold', fontsize=11, pad=8)

        # Grilla 1/3 octava (ISO 266), eje log, look tipo REW — igual que FRF.
        from matplotlib.ticker import FixedLocator, NullLocator, FuncFormatter
        from plot_utils import third_octave_edges
        edges = third_octave_edges(float(f[0]), float(f[-1]))
        if len(edges) >= 2:
            ax.set_xscale('log')
            ax.set_xlim(float(f[0]), float(f[-1]))
            ax.xaxis.set_major_locator(FixedLocator(edges))
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}"))
            ax.xaxis.set_minor_locator(NullLocator())
        ax.grid(True, which='major', axis='x', linestyle='-',
                linewidth=0.7, alpha=0.3, color='#bbbbbb')
        ax.grid(True, which='major', axis='y', linestyle='-',
                linewidth=0.7, alpha=0.6, color='#cccccc')
        ax.legend(fontsize=9, framealpha=0.85, loc='best')
        ax.tick_params(labelsize=9)
        self._fig.tight_layout(pad=1.2)
        self._canvas.draw_idle()

    def _export(self, fmt: str):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar como {fmt.upper()}",
            f"sbir.{fmt}", f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        if fmt in ('csv', 'txt'):
            res = self._res
            f = np.asarray(res.freq_axis)
            header = ['freq_hz'] + [f"sbir_db_{s.label}" for s in res.per_source]
            if len(res.per_source) > 1:
                header.append('sbir_db_total')
            # Columnas del hibrido si el toggle esta activo y hay modos.
            show_modal = (self._chk_modal is not None
                          and self._chk_modal.isChecked()
                          and self._modal_db is not None)
            hybrid = None
            if show_modal:
                header.append('modal_db')
                if self._f_s:
                    import sbir as _sbir
                    hybrid = _sbir.modal_sbir_crossfade(
                        f, res.total_sbir_db, self._modal_db, self._f_s)
                    header.append('total_hibrido_db')
            rows = []
            for i in range(len(f)):
                row = [float(f[i])] + [float(s.sbir_db[i]) for s in res.per_source]
                if len(res.per_source) > 1:
                    row.append(float(res.total_sbir_db[i]))
                if show_modal:
                    row.append(float(self._modal_db[i]))
                    if hybrid is not None:
                        row.append(float(hybrid[i]))
                rows.append(tuple(row))
            _write_tabular(path, header, rows, fmt)
        elif self._fig:
            self._fig.savefig(path, dpi=300, bbox_inches='tight',
                              facecolor='white')


# ---------------------------------------------------------------------------
# Dialogo heatmap de plano de corte
# ---------------------------------------------------------------------------
class SliceHeatmapDialog(QDialog):
    """Ventana no-modal con el mapa de calor 2D del plano de corte.

    kind=0 → forma modal (normalizada, colormap divergente)
    kind=1 → presión |p| en dB SPL (colormap inferno)
    """

    # Metadatos por tipo de plano: (etiq_eje1, etiq_eje2, nombre, etiq_fijo)
    _PLANE_META = {
        2: ('x  (m)', 'y  (m)', 'XY',  'z'),
        1: ('x  (m)', 'z  (m)', 'XZ',  'y'),
        0: ('y  (m)', 'z  (m)', 'YZ',  'x'),
    }
    _P_REF = 20e-6   # Pa
    # Distancia al plano (en el eje fijo) a partir de la cual un marcador se
    # dibuja semi-transparente: esta en la sala pero no "sobre" este corte.
    _MARKER_TOL = 0.5   # m

    def __init__(self, field_slice, mode_name: str, kind: int,
                 markers=None, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowFlags(self.windowFlags() | Qt.Window)  # independiente
        self._fig = None
        self._fs = None
        self._mode_name = ''
        self._kind = 0
        # markers: {"sources": [(nombre, (x,y,z)), ...],
        #           "receivers": [(nombre, (x,y,z)), ...]}  (v2.16)
        self._markers = markers or {}
        self._setup_layout()
        if field_slice is not None:
            self.update_slice(field_slice, mode_name, kind)

    def _setup_layout(self):
        self.resize(820, 600)
        v = QVBoxLayout(self)
        if not _HAS_MPL:
            v.addWidget(QLabel("matplotlib no disponible. pip install matplotlib"))
            return
        self._fig, self._ax = plt.subplots(figsize=(8.0, 5.5), dpi=96)
        self._fig.patch.set_facecolor('#f0f0f0')
        canvas = FigureCanvas(self._fig)
        toolbar = NavigationToolbar(canvas, self)
        v.addWidget(toolbar)
        v.addWidget(canvas, 1)
        brow = QHBoxLayout()
        for fmt in ("PNG", "SVG", "PDF", "CSV", "TXT"):
            b = QPushButton(f"Exportar {fmt}")
            b.setMinimumWidth(140)           # texto completo, sin recortar
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._export(f))
            brow.addWidget(b)
        brow.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.close)
        brow.addWidget(btns)
        v.addLayout(brow)

    def update_slice(self, field_slice, mode_name: str, kind: int,
                     markers=None):
        """Actualiza la figura con nuevos datos (reutiliza la ventana).
        Limpia la figura completa para evitar colorbars duplicadas.
        """
        if not _HAS_MPL or self._fig is None:
            return
        self._fs = field_slice
        self._mode_name = mode_name
        self._kind = kind
        if markers is not None:
            self._markers = markers
        self._fig.clf()                          # limpia figura + colorbars viejas
        self._ax = self._fig.add_subplot(111)   # recrea el eje
        self._render(field_slice, mode_name, kind)
        self._fig.canvas.draw_idle()

    def _render(self, fs, mode_name: str, kind: int):
        ax   = self._ax
        axis = getattr(fs, 'axis', 2)
        off  = float(fs.z)
        C1   = fs.X                      # (n1, n2) primera coord de barrido
        C2   = fs.Y                      # (n1, n2) segunda coord de barrido
        P    = fs.P.copy().astype(float)
        mask = fs.mask

        if mask is not None:
            P[~mask] = np.nan

        xl, yl, pname, fn = self._PLANE_META[axis]
        extent = [float(C1.min()), float(C1.max()),
                  float(C2.min()), float(C2.max())]

        # Fondo gris para la zona fuera del recinto
        ax.set_facecolor('#888888')

        if kind == 0:
            # ---- Forma modal: colormap divergente ----
            vmax = float(np.nanmax(np.abs(P))) if np.any(np.isfinite(P)) else 1.0
            vmax = max(vmax, 1e-9)
            im = ax.imshow(P.T, origin='lower', extent=extent,
                           cmap='RdBu_r', vmin=-vmax, vmax=vmax,
                           interpolation='bilinear', aspect='auto')
            cbar = self._fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
            cbar.set_label('Amplitud modal (normalizada)', fontsize=9)
            cbar.ax.tick_params(labelsize=8)
            grid_color = '#555555'
        else:
            # ---- Presión |p| → dB SPL ----
            with np.errstate(divide='ignore', invalid='ignore'):
                P_db = np.where(P > 0, 20.0 * np.log10(P / self._P_REF), np.nan)

            fin = P_db[np.isfinite(P_db)]
            if len(fin) == 0:
                ax.text(0.5, 0.5, 'Sin datos válidos',
                        ha='center', va='center', transform=ax.transAxes,
                        fontsize=12, color='white')
                return
            vmin_db = float(np.percentile(fin, 2))
            vmax_db = float(np.max(fin))
            im = ax.imshow(P_db.T, origin='lower', extent=extent,
                           cmap='inferno', vmin=vmin_db, vmax=vmax_db,
                           interpolation='bilinear', aspect='auto')
            cbar = self._fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
            cbar.set_label('Nivel de presión sonora  (dB SPL  re 20 µPa)',
                           fontsize=9)
            cbar.ax.tick_params(labelsize=8)
            grid_color = 'white'

        # Grilla sobre ambos ejes para leer posición de cada punto
        ax.grid(True, which='major', linestyle='--', linewidth=0.6,
                alpha=0.55, color=grid_color)
        ax.set_axisbelow(False)   # grilla encima del imshow

        # v2.16: fuentes (○) y receptores (✕) con su nombre debajo.
        self._draw_markers(ax, axis, off)

        ax.set_xlabel(xl, fontsize=10)
        ax.set_ylabel(yl, fontsize=10)
        ax.set_title(
            f'Plano {pname}   {fn} = {off:.2f} m   —   {mode_name}',
            fontsize=10, fontweight='bold', pad=8
        )
        ax.tick_params(labelsize=9)
        self._fig.tight_layout(pad=0.9)
        self.setWindowTitle(f'Plano {pname} @ {fn}={off:.2f} m — {mode_name}')

    def _draw_markers(self, ax, axis, off):
        """Sobreimprime fuentes (circulo) y receptores (X) con el nombre
        debajo, proyectados sobre el plano del corte. Blanco con borde negro
        (legible sobre inferno y RdBu). Los que estan a mas de _MARKER_TOL
        del plano (eje fijo) van semi-transparentes: estan en la sala pero
        no sobre este corte."""
        mk = self._markers or {}
        if not mk:
            return
        import matplotlib.patheffects as _pe
        stroke = [_pe.withStroke(linewidth=2.2, foreground='black')]
        c1, c2 = [i for i in (0, 1, 2) if i != axis]   # coords barridas
        for key, marker, ms, mfc in (("sources", 'o', 9, 'none'),
                                     ("receivers", 'x', 8, 'white')):
            for name, pos in mk.get(key, []):
                try:
                    p = np.asarray(pos, dtype=float)
                    a = 1.0 if abs(p[axis] - off) <= self._MARKER_TOL else 0.35
                    ax.plot([p[c1]], [p[c2]], marker, ms=ms, mew=1.8,
                            color='white', mfc=mfc, alpha=a,
                            path_effects=stroke, zorder=6)
                    ax.annotate(str(name), (p[c1], p[c2]),
                                xytext=(0, -8), textcoords='offset points',
                                ha='center', va='top', fontsize=7.5,
                                color='white', alpha=a,
                                path_effects=stroke, zorder=6)
                except Exception:
                    continue

    def _export(self, fmt: str):
        path, _ = QFileDialog.getSaveFileName(
            self, f'Exportar {fmt.upper()}',
            f'plano_corte.{fmt}', f'{fmt.upper()} (*.{fmt})'
        )
        if not path:
            return
        if fmt in ('csv', 'txt'):
            if self._fs is None:
                QMessageBox.information(self, 'Exportar',
                                        'No hay datos para exportar.')
                return
            fs = self._fs
            axis = getattr(fs, 'axis', 2)
            xl, yl, pname, fn = self._PLANE_META[axis]
            C1 = np.asarray(fs.X)
            C2 = np.asarray(fs.Y)
            P  = np.asarray(fs.P, dtype=float)
            mask = fs.mask
            n1, n2 = P.shape
            # cabecera con metadatos como comentario amigable a Excel/Python
            col1 = xl.split()[0]   # 'x', 'y' o 'z'
            col2 = yl.split()[0]
            if self._kind == 0:
                header = [col1, col2, 'amplitud_modal']
            else:
                header = [col1, col2, 'presion_pa', 'spl_db']
            rows = []
            for i in range(n1):
                for j in range(n2):
                    if mask is not None and not mask[i, j]:
                        continue
                    p = float(P[i, j])
                    if self._kind == 0:
                        rows.append((float(C1[i, j]), float(C2[i, j]), p))
                    else:
                        spl = (20.0 * np.log10(p / self._P_REF)
                               if p > 0 else float('nan'))
                        rows.append((float(C1[i, j]), float(C2[i, j]), p,
                                     float(spl)))
            _write_tabular(path, header, rows, fmt)
        elif self._fig:
            self._fig.savefig(path, dpi=300, bbox_inches='tight',
                              facecolor='white')

    def closeEvent(self, ev):
        if self._fig is not None:
            plt.close(self._fig)
            self._fig = None
        super().closeEvent(ev)


# ---------------------------------------------------------------------------
# Dialogo RT60 (curva Sabine)
# ---------------------------------------------------------------------------
class RTComparisonDialog(QDialog):
    """Tiempo de reverberacion calculado por varios metodos — multi-curva.

    Reemplaza al antiguo RT60PlotDialog (que mostraba SOLO la curva de
    Sabine).  Ahora permite:

      * 3 metodos de prediccion: **Sabine**, **Eyring**, **Fitzroy**.
      * 3 metricas de decaimiento: **T60**, **T30**, **T20**
        (matematicamente iguales para predicciones teoricas, ver nota mas
        abajo; se mantienen como alias por compatibilidad con el lenguaje
        habitual de mediciones).
      * Agregar y quitar curvas para comparar. Cada curva guarda su
        materializacion numerica (banda -> segundos), asi se pueden tener
        snapshots de distintas asignaciones de material.

    Nota fisica: los tres modelos teoricos asumen decaimiento exponencial
    puro; en ese regimen T20 = T30 = T60. La diferencia T20/T30/T60 SOLO
    aparece en mediciones reales (no en una prediccion).
    """

    # Paleta deterministica por metodo. Fitzroy queda comentado por si se
    # re-habilita en el futuro.
    _COLOR_BY_METHOD = {
        "sabine":  "#1f77b4",   # azul
        "eyring":  "#d62728",   # rojo
        # "fitzroy": "#2ca02c", # verde (oculto en UI)
    }
    _LINESTYLE_BY_METRIC = {
        "T60": "-",
    }
    _MARKER_BY_METRIC = {
        "T60": "o",
    }

    def __init__(self, panel: "AcousticPanel", parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Tiempo de reverberacion — comparativa de metodos")
        self.resize(1080, 580)
        self._panel = panel
        self._fig = None
        self._ax = None
        # Lista de curvas activas: cada elemento es un dict
        #   {label, method, metric, bands, values, color, visible, line2d}
        self._curves: list[dict] = []
        # Contador para etiquetas tipo "Sabine T60 #2" si el usuario agrega
        # la misma combinacion varias veces (por ejemplo, despues de cambiar
        # los materiales para comparar).
        self._counter: dict = {}

        if not _HAS_MPL:
            v = QVBoxLayout(self)
            v.addWidget(QLabel("matplotlib no esta disponible."))
            return

        self._build_ui()
        # Auto-agregar la curva por defecto (Sabine T60) al abrir.
        try:
            self._add_curve("sabine", "T60")
        except Exception as e:
            self._panel._log(f"Aviso RT: {e}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, 1)

        # --- Panel izquierdo: grafico ---
        left = QVBoxLayout()
        body.addLayout(left, 4)

        self._fig, self._ax = plt.subplots(figsize=(8, 4.5), dpi=96)
        self._fig.patch.set_facecolor('#f0f0f0')
        self._ax.set_facecolor('#ffffff')
        self._ax.set_xlabel('Frecuencia (Hz)', fontsize=10)
        self._ax.set_ylabel('Tiempo de reverberacion (s)', fontsize=10)
        self._ax.set_xscale('log')
        # OJO: _refresh_axes_meta() llama self._canvas.draw_idle(), asi que
        # tiene que ejecutarse DESPUES de crear self._canvas, no antes.
        self._canvas = FigureCanvas(self._fig)
        self._toolbar = NavigationToolbar(self._canvas, self)
        left.addWidget(self._toolbar)
        left.addWidget(self._canvas, 1)
        self._refresh_axes_meta()

        # --- Panel derecho: controles ---
        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 0)

        # Lista de curvas activas
        grp_curves = QGroupBox("Curvas activas")
        gv = QVBoxLayout(grp_curves)
        self.list_curves = QListWidget()
        self.list_curves.setMinimumWidth(290)
        self.list_curves.setMinimumHeight(170)
        # Clic en el checkbox -> toggle visibilidad
        self.list_curves.itemChanged.connect(self._on_curve_toggled)
        gv.addWidget(self.list_curves)
        # Boton borrar la curva seleccionada
        rowx = QHBoxLayout()
        self.btn_del_curve = QPushButton("Quitar curva seleccionada")
        self.btn_del_curve.clicked.connect(self._del_selected_curve)
        rowx.addWidget(self.btn_del_curve)
        gv.addLayout(rowx)
        right.addWidget(grp_curves)

        # Selector para agregar una curva nueva
        grp_add = QGroupBox("Agregar curva")
        fa = QFormLayout(grp_add)
        self.combo_method = QComboBox()
        for key, (display, _fn) in fm.RT_METHODS.items():
            self.combo_method.addItem(display, key)
        fa.addRow("Metodo:", self.combo_method)

        # Combo de metrica: solo se muestra si hay mas de una opcion.
        # Actualmente RT_METRICS = ("T60",) por lo que el combo queda oculto
        # y todas las curvas usan T60 implicitamente.
        self.combo_metric = QComboBox()
        for m in fm.RT_METRICS:
            self.combo_metric.addItem(m)
        self.combo_metric.setCurrentText("T60")
        if len(fm.RT_METRICS) > 1:
            fa.addRow("Metrica:", self.combo_metric)

        self.btn_add_curve = QPushButton("+ Agregar curva con la asignacion actual")
        self.btn_add_curve.setObjectName("PrimaryButton")
        self.btn_add_curve.clicked.connect(self._on_add_curve_clicked)
        fa.addRow(self.btn_add_curve)
        # Etapa 2a: RT60 T30 de la perturbacion de frontera (solo banda modal).
        # No es una fila de RT_METHODS (no sale de fn(V,groups,g2m) sino del
        # decay de los modos), por eso boton aparte. Requiere modos resueltos.
        self.btn_add_pert = QPushButton("+ Perturbación (T30, banda modal)")
        self.btn_add_pert.clicked.connect(self._on_add_perturbation_clicked)
        fa.addRow(self.btn_add_pert)
        right.addWidget(grp_add)

        # Guardar / cargar curvas: la ventana se limpia al cerrar (comodo para
        # trabajar rapido), pero el usuario puede GUARDAR una curva a un archivo
        # CSV (legible), cambiar materiales, reabrir y CARGAR el/los CSV anteriores
        # para comparar. Cada curva es un archivo -> se pueden cargar varias.
        grp_sl = QGroupBox("Guardar / cargar curvas (CSV)")
        gsl = QVBoxLayout(grp_sl)
        self.btn_save_curve = QPushButton("💾 Guardar curva seleccionada…")
        self.btn_save_curve.setToolTip(
            "Guarda la curva seleccionada en un archivo CSV (elegís carpeta y\n"
            "nombre) para leerla fácil y compararla luego con otra configuración.")
        self.btn_save_curve.clicked.connect(self._save_selected_curve)
        gsl.addWidget(self.btn_save_curve)
        self.btn_load_curve = QPushButton("📂 Cargar curva(s) desde CSV…")
        self.btn_load_curve.setToolTip(
            "Cargá uno o varios CSV guardados antes; se superponen (punteadas)\n"
            "para comparar con la configuración actual.")
        self.btn_load_curve.clicked.connect(self._load_saved_curve)
        gsl.addWidget(self.btn_load_curve)
        right.addWidget(grp_sl)

        # Acciones globales
        grp_glob = QGroupBox("Acciones")
        gg = QVBoxLayout(grp_glob)
        self.btn_clear_all = QPushButton("Borrar todas las curvas")
        self.btn_clear_all.clicked.connect(self._clear_all_curves)
        gg.addWidget(self.btn_clear_all)
        right.addWidget(grp_glob)

        # Nota fisica
        note = QLabel(
            "<b>Nota:</b> Sabine asume α &lt;&lt; 1 y sobreestima RT60 cuando "
            "la absorcion es alta. Eyring corrige ese sesgo via "
            "−S·ln(1−α). En el regimen de absorcion baja los dos coinciden; "
            "con materiales muy absorbentes Eyring da valores menores."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c6f85; font-size: 8pt; padding: 4px;")
        right.addWidget(note)
        right.addStretch(1)

        # Fila inferior: exportar + cerrar
        brow = QHBoxLayout()
        for fmt in ("PNG", "SVG", "PDF", "CSV", "TXT"):
            b = QPushButton(f"Exportar {fmt}")
            b.setMinimumWidth(140)              # texto completo, sin recortar
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, f=fmt.lower(): self._export(f))
            brow.addWidget(b)
        brow.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        brow.addWidget(btns)
        root.addLayout(brow)

    # ------------------------------------------------------------------
    # Computo
    # ------------------------------------------------------------------
    def _compute_rt(self, method: str, metric: str) -> tuple:
        """Devuelve (bands, values, label_suffix) para la asignacion actual.

        El cuerpo respeta el FaceMaterialMap actual del panel — si el
        usuario cambio materiales entre clics, las curvas nuevas reflejan
        esa modificacion (las viejas siguen con sus numeros snapshotted).
        """
        groups, verts, tris = self._panel._get_face_groups()
        V = aa.compute_mesh_volume(verts, tris)
        g2m = self._panel._group_to_material_dict(groups)
        fn = fm.RT_METHODS[method][1]
        rt60 = fn(V, groups, g2m)
        rt = fm.rt60_to_metric(rt60, metric)
        bands = sorted(rt.keys())
        vals = [rt[b] for b in bands]
        return bands, vals

    def _on_add_curve_clicked(self):
        method = self.combo_method.currentData()
        metric = self.combo_metric.currentText()
        self._add_curve(method, metric)

    def _on_add_perturbation_clicked(self):
        """Superpone el RT60 T30 de la perturbacion de frontera (banda modal)."""
        rt = None
        try:
            rt = self._panel._perturbation_rt60_by_band()
        except Exception as e:
            QMessageBox.warning(self, "Error",
                                f"No se pudo calcular la perturbación:\n{e}")
            return
        if not rt:
            QMessageBox.information(
                self, "Perturbación",
                "No hay RT60 de perturbación para mostrar.\n\n"
                "Resolvé los modos primero (la perturbación necesita las formas "
                "modales; solo cubre la banda modal, por debajo de f_Schroeder).")
            return
        bands = sorted(rt.keys())
        vals = [rt[b] for b in bands]
        base = "Perturbación T30"
        idx = self._counter.get(base, 0) + 1
        self._counter[base] = idx
        label = base if idx == 1 else f"{base} #{idx}"
        color = "#f38ba8"                      # rojo-rosado, distinto de Sabine
        line, = self._ax.plot(
            bands, vals, "-", color=color, marker="D", markersize=6,
            linewidth=1.8, label=label)
        curve = {"label": label, "method": "perturbation", "metric": "T60",
                 "bands": bands, "values": vals, "color": color,
                 "visible": True, "line2d": line}
        self._curves.append(curve)
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setForeground(QColor(color))
        item.setData(Qt.UserRole, curve)
        self.list_curves.addItem(item)
        self._refresh_axes_meta()

    def _add_curve(self, method: str, metric: str):
        try:
            bands, vals = self._compute_rt(method, metric)
        except Exception as e:
            QMessageBox.warning(self, "Error",
                                  f"No se pudo calcular {method} {metric}:\n{e}")
            return
        # Etiqueta auto con sufijo si repite combinacion. Si solo hay una
        # metrica (T60), no la mostramos en la etiqueta para no recargar.
        if len(fm.RT_METRICS) > 1:
            base = f"{fm.RT_METHODS[method][0]} {metric}"
        else:
            base = f"{fm.RT_METHODS[method][0]} RT60"
        idx = self._counter.get(base, 0) + 1
        self._counter[base] = idx
        label = base if idx == 1 else f"{base} #{idx}"

        color = self._COLOR_BY_METHOD[method]
        ls = self._LINESTYLE_BY_METRIC[metric]
        mk = self._MARKER_BY_METRIC[metric]
        line, = self._ax.plot(
            bands, vals, ls, color=color, marker=mk, markersize=6,
            linewidth=1.8, label=label,
        )
        curve = {
            "label": label,
            "method": method,
            "metric": metric,
            "bands": bands,
            "values": vals,
            "color": color,
            "visible": True,
            "line2d": line,
        }
        self._curves.append(curve)
        # Item en la lista
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setForeground(QColor(color))
        item.setData(Qt.UserRole, curve)
        self.list_curves.addItem(item)
        # Refrescar plot
        self._refresh_axes_meta()

    # ------------------------------------------------------------------
    # Guardar / cargar curvas (comparar configuraciones de material)
    # ------------------------------------------------------------------
    def _save_selected_curve(self):
        """Guarda la curva seleccionada en un archivo CSV (el usuario elige carpeta
        y nombre) para leerla facil y compararla luego con otra configuracion."""
        from PyQt5.QtWidgets import QFileDialog
        row = self.list_curves.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Guardar curva",
                "Seleccioná primero una curva de la lista «Curvas activas».")
            return
        curve = self.list_curves.item(row).data(Qt.UserRole)
        if curve is None:
            return
        # nombre de archivo sugerido a partir de la etiqueta de la curva
        rt_avg = float(np.mean(curve["values"])) if curve["values"] else 0.0
        safe = "".join(c if (c.isalnum() or c in " -_") else "_"
                       for c in curve["label"]).strip() or "rt"
        default_path = f"{safe}_RT{rt_avg:.2f}s.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar curva de RT como CSV", default_path,
            "CSV (*.csv);;Todos (*.*)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        name = curve["label"]
        method = str(curve.get("method", "sabine"))
        metric = str(curve.get("metric", "T60"))
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write("# Prototipo 1 - curva de tiempo de reverberacion\n")
                fh.write(f"nombre,{name}\n")
                fh.write(f"metodo,{method}\n")
                fh.write(f"metrica,{metric}\n")
                fh.write("banda_hz,rt_s\n")
                for b, v in zip(curve["bands"], curve["values"]):
                    fh.write(f"{float(b):.0f},{float(v):.4f}\n")
        except Exception as e:
            QMessageBox.warning(self, "Error al guardar", str(e))
            return
        self._panel._log(f"RT: curva guardada en {path}")
        QMessageBox.information(
            self, "Curva guardada",
            f"Guardada en:\n{path}\n\nCambiá materiales, reabrí esta ventana y "
            f"usá «Cargar curva guardada…» para comparar.")

    def _load_saved_curve(self):
        """Carga una o varias curvas de RT desde archivos CSV (las que guardaste
        antes) y las superpone para comparar con la configuracion actual."""
        from PyQt5.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Cargar curva(s) de RT desde CSV", "",
            "CSV (*.csv);;Todos (*.*)")
        if not paths:
            return
        n_ok = 0
        for path in paths:
            try:
                name, method, metric, bands, vals = self._parse_rt_csv(path)
            except Exception as e:
                QMessageBox.warning(self, "Error al cargar",
                                    f"{path}:\n{e}")
                continue
            if not bands:
                continue
            label = f"★ {name}"
            color = "#6b7280"                     # gris, no compite con las vivas
            line, = self._ax.plot(
                bands, vals, "--", color=color, marker="s", markersize=6,
                linewidth=1.8, label=label)
            curve = {"label": label, "method": method, "metric": metric,
                     "bands": bands, "values": vals, "color": color,
                     "visible": True, "line2d": line}
            self._curves.append(curve)
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setForeground(QColor(color))
            item.setData(Qt.UserRole, curve)
            self.list_curves.addItem(item)
            n_ok += 1
        if n_ok:
            self._refresh_axes_meta()
            self._panel._log(f"RT: {n_ok} curva(s) cargada(s) desde CSV.")

    @staticmethod
    def _parse_rt_csv(path):
        """Lee un CSV de curva de RT (formato de _save_selected_curve). Devuelve
        (nombre, metodo, metrica, bands, values). Tolerante: ignora comentarios (#)
        y lineas vacias; el nombre cae al stem del archivo si falta."""
        import os
        name = os.path.splitext(os.path.basename(path))[0]
        method, metric = "saved", "T60"
        bands, vals = [], []
        in_data = False
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                key = parts[0].lower()
                if key == "nombre" and len(parts) > 1:
                    name = parts[1] or name
                elif key == "metodo" and len(parts) > 1:
                    method = parts[1] or method
                elif key in ("metrica", "métrica") and len(parts) > 1:
                    metric = parts[1] or metric
                elif key in ("banda_hz", "banda", "freq_hz", "hz"):
                    in_data = True                # cabecera de la tabla
                else:
                    # fila de datos: dos numeros (banda, rt)
                    try:
                        b = float(parts[0]); v = float(parts[1])
                    except (ValueError, IndexError):
                        continue
                    bands.append(b); vals.append(v)
                    in_data = True
        return name, method, metric, bands, vals

    def _on_curve_toggled(self, item: QListWidgetItem):
        curve = item.data(Qt.UserRole)
        if curve is None:
            return
        visible = item.checkState() == Qt.Checked
        curve["visible"] = visible
        curve["line2d"].set_visible(visible)
        self._refresh_axes_meta()

    def _del_selected_curve(self):
        row = self.list_curves.currentRow()
        if row < 0:
            return
        item = self.list_curves.item(row)
        curve = item.data(Qt.UserRole)
        if curve is not None:
            try:
                curve["line2d"].remove()
            except Exception:
                pass
            self._curves.remove(curve)
        self.list_curves.takeItem(row)
        self._refresh_axes_meta()

    def _clear_all_curves(self):
        for c in self._curves:
            try:
                c["line2d"].remove()
            except Exception:
                pass
        self._curves.clear()
        self.list_curves.clear()
        self._counter.clear()
        self._refresh_axes_meta()

    def _refresh_axes_meta(self):
        # Titulo dinamico segun el panel
        try:
            groups, verts, tris = self._panel._get_face_groups()
            V = aa.compute_mesh_volume(verts, tris)
            n_assigned = sum(1 for g in groups
                              if self._panel._face_mat_map.get(g.signature))
            title = (f"Tiempo de reverberacion  (V={V:.1f} m³, "
                      f"{n_assigned}/{len(groups)} grupos con material)")
        except Exception:
            title = "Tiempo de reverberacion"
        self._ax.set_title(title, fontsize=10, pad=8)
        # Bandas en el eje x
        bands_std = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
        self._ax.set_xticks(bands_std)
        self._ax.get_xaxis().set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{int(x)}")
        )
        self._ax.grid(True, which='major', linestyle='-', linewidth=0.7,
                       alpha=0.6, color='#cccccc')
        self._ax.grid(True, which='minor', linestyle=':', linewidth=0.4,
                       alpha=0.4, color='#dddddd')
        # Leyenda con las curvas visibles
        visible_lines = [c["line2d"] for c in self._curves if c["visible"]]
        if visible_lines:
            self._ax.legend(visible_lines, [l.get_label() for l in visible_lines],
                            fontsize=8, loc='best', ncol=1)
        else:
            leg = self._ax.get_legend()
            if leg is not None:
                leg.remove()
        # Auto-rango Y
        if self._curves:
            ymax = max(max(c["values"]) for c in self._curves if c["visible"]) \
                    if any(c["visible"] for c in self._curves) else 1.0
            self._ax.set_ylim(0, ymax * 1.15 + 0.05)
        try:
            self._fig.tight_layout(pad=1.2)
        except Exception:
            pass
        # Defensa: si esta funcion se llama antes de que el FigureCanvas
        # exista (durante el setup inicial del UI), no falla — sera redibujado
        # cuando el canvas este listo.
        if hasattr(self, '_canvas') and self._canvas is not None:
            self._canvas.draw_idle()

    def _export(self, fmt: str):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar {fmt.upper()}", f"rt_comparison.{fmt}",
            f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        if fmt in ('csv', 'txt'):
            if not self._curves:
                QMessageBox.information(self, 'Exportar',
                                        'No hay curvas para exportar.')
                return
            # Union ordenada de bandas presentes en todas las curvas
            all_bands = sorted({b for c in self._curves for b in c['bands']})
            header = ['banda_hz'] + [c['label'] + '_s' for c in self._curves]
            rows = []
            for b in all_bands:
                row = [int(b)]
                for c in self._curves:
                    if b in c['bands']:
                        idx = c['bands'].index(b)
                        row.append(float(c['values'][idx]))
                    else:
                        row.append(None)
                rows.append(row)
            _write_tabular(path, header, rows, fmt)
        elif self._fig:
            self._fig.savefig(path, dpi=300, bbox_inches='tight',
                              facecolor='white')


# Alias retrocompatible (codigo viejo del panel y de los tests).
RT60PlotDialog = RTComparisonDialog


# ---------------------------------------------------------------------------
# Comparar puntos de escucha (v2.16): tabla FoM + FRF + SBIR multi-posicion
# ---------------------------------------------------------------------------
class CompareDialog(QDialog):
    """Comparacion de N puntos de escucha con las fuentes ACTIVAS.

    `data` (dict) trae lo pre-computado por AcousticPanel._compute_compare_data:
      names / positions / src_labels  siempre;
      fom  = {"planitud", "desvio", "VSA", "MSV", "band"}      si se pidio;
      frf  = {"freq", "spl" (lista de curvas dB SPL)}          si se pidio;
      sbir = {"freq", "curves" (lista de curvas dB)}           si se pidio.
    Cada tab tiene sus botones de export (tabla: CSV/TXT/PNG; curvas: PNG/CSV).
    """

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        from PyQt5.QtWidgets import QTabWidget
        self.setWindowTitle("Comparar puntos de escucha")
        self.resize(880, 600)
        self._data = data
        v = QVBoxLayout(self)
        head = QLabel(
            f"<b>{len(data['names'])} puntos</b> · fuentes activas: "
            f"{', '.join(data['src_labels']) or '—'}")
        head.setWordWrap(True)
        v.addWidget(head)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        if "fom" in data:
            self.tabs.addTab(self._build_fom_tab(), "Figuras de mérito")
        if "frf" in data:
            self.tabs.addTab(self._build_curves_tab(
                data["frf"]["freq"], data["frf"]["spl"],
                "SPL [dB re 20 µPa]", "frf_comparacion"),
                "Respuesta en frecuencia")
        if "sbir" in data:
            self.tabs.addTab(self._build_curves_tab(
                data["sbir"]["freq"], data["sbir"]["curves"],
                "SBIR [dB] (0 = campo directo)", "sbir_comparacion"),
                "SBIR")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        v.addWidget(bb)

    # -------------------------------- tabla FoM ---------------------------
    def _fom_rows(self):
        """Filas (nombre, planitud, desvio) + fila CONJUNTO (VSA, MSV)."""
        d = self._data["fom"]
        rows = [(n, d["planitud"][i], d["desvio"][i])
                for i, n in enumerate(self._data["names"])]
        rows.append(("CONJUNTO", d["VSA"], d["MSV"]))
        return rows

    def _build_fom_tab(self):
        from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        w = QWidget()
        v = QVBoxLayout(w)
        d = self._data["fom"]
        note = QLabel(
            f"Banda {d['band'][0]:.0f}–{d['band'][1]:.0f} Hz (validez de malla), "
            f"suavizado 1/3 oct. Por posición: <b>planitud local</b> = σ_f de su "
            f"curva; <b>desvío vs promedio</b> = RMS(curva − promedio espacial). "
            f"Fila CONJUNTO: <b>VSA</b> = σ_f del promedio espacial (planitud del "
            f"set) y <b>MSV</b> = media de σ entre posiciones (consistencia).")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c6f85; font-size: 9pt;")
        v.addWidget(note)
        rows = self._fom_rows()
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(
            ["Posición", "Planitud local [dB]", "Desvío vs promedio [dB]"])
        self.table.verticalHeader().setVisible(False)
        for r, (name, a, b) in enumerate(rows):
            for c, txt in enumerate((name, f"{a:.2f}", f"{b:.2f}")):
                it = QTableWidgetItem(txt)
                if r == len(rows) - 1:
                    f = it.font(); f.setBold(True); it.setFont(f)
                self.table.setItem(r, c, it)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        v.addWidget(self.table, 1)
        # La fila CONJUNTO usa las etiquetas VSA/MSV en el header conceptual:
        lbl = QLabel("En la fila CONJUNTO: columna planitud = <b>VSA</b>, "
                     "columna desvío = <b>MSV</b>.")
        lbl.setStyleSheet("color: #6c6f85; font-size: 9pt;")
        v.addWidget(lbl)
        row = QHBoxLayout()
        for fmt in ("csv", "txt", "png"):
            b = QPushButton(f"Exportar {fmt.upper()}")
            b.setMinimumWidth(140)
            b.clicked.connect(lambda _=False, f=fmt: self._export_table(f))
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        return w

    def _export_table(self, fmt: str):
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar tabla como {fmt.upper()}",
            f"comparacion_fom.{fmt}", f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        if fmt == "png":
            self.table.grab().save(path, "PNG")
            return
        rows = self._fom_rows()
        hdr = ["posicion", "planitud_local_dB", "desvio_vs_promedio_dB"]
        if fmt == "csv":
            lines = [",".join(hdr)] + [
                f"{n},{a:.4f},{b:.4f}" for n, a, b in rows]
        else:
            wname = max(len(hdr[0]), max(len(r[0]) for r in rows)) + 2
            lines = [f"{hdr[0]:<{wname}}{hdr[1]:>22}{hdr[2]:>26}"] + [
                f"{n:<{wname}}{a:>22.4f}{b:>26.4f}" for n, a, b in rows]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    # -------------------------------- curvas ------------------------------
    def _build_curves_tab(self, freq, curves, ylabel, base_name):
        w = QWidget()
        v = QVBoxLayout(w)
        if not _HAS_MPL:
            v.addWidget(QLabel("matplotlib no disponible."))
            return w
        # Figure directa (sin pyplot): plt.subplots registra un FigureManager
        # global con ventana Qt oculta que vive hasta plt.close() — en un
        # dialogo que se abre muchas veces eso acumula estado innecesario.
        from matplotlib.figure import Figure
        fig = Figure(figsize=(7.4, 4.2), dpi=90)
        ax = fig.add_subplot(111)
        for name, c in zip(self._data["names"], curves):
            ax.plot(freq, c, lw=1.4, label=name)
        ax.set_xlabel("Frecuencia [Hz]")
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8, ncol=2)
        fig.tight_layout()
        canvas = FigureCanvas(fig)
        v.addWidget(canvas, 1)
        row = QHBoxLayout()
        for fmt in ("png", "csv"):
            b = QPushButton(f"Exportar {fmt.upper()}")
            b.setMinimumWidth(140)
            b.clicked.connect(lambda _=False, f=fmt, fg=fig, fr=freq,
                              cs=curves, bn=base_name:
                              self._export_curves(f, fg, fr, cs, bn))
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        return w

    def _export_curves(self, fmt, fig, freq, curves, base_name):
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar como {fmt.upper()}",
            f"{base_name}.{fmt}", f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        if fmt == "png":
            fig.savefig(path, dpi=150, bbox_inches="tight")
            return
        hdr = ["freq_hz"] + [n.replace(",", "_") for n in self._data["names"]]
        arr = np.column_stack([np.asarray(freq)] +
                              [np.asarray(c) for c in curves])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(",".join(hdr) + "\n")
            for row in arr:
                fh.write(",".join(f"{x:.6g}" for x in row) + "\n")


class ModeTableDialog(QDialog):
    """Tabla por modo (Capa 0, Etapa 5c): expone EXPLICITAMENTE el corrimiento
    de frecuencia Delta f_n = f_efectiva - f_rigida (por Im(beta) de las
    construcciones) y el amortiguamiento modal xi_n que la app ya usa en la
    dinamica (FRF/campo/FoM), mas el RT60_n de decaimiento del modo aislado.

    `data` (dict) lo arma AcousticPanel._collect_mode_table:
      n, f_rig, f_eff, dfreq, xi (np.ndarray, largo = nro de modos)  siempre;
      model (str legible), constructions (bool), max_abs_shift (float).
    xi puede venir None si no se pudo calcular el amortiguamiento.
    """

    COLS = ["Modo n", "fₙ rígida [Hz]", "f efectiva [Hz]",
            "Δfₙ [Hz]", "ξₙ", "RT60ₙ [s]"]

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        self.setWindowTitle("Modos: corrimiento Δfₙ y amortiguamiento ξₙ")
        self.resize(720, 560)
        self._data = data
        v = QVBoxLayout(self)

        n_modes = len(data["f_rig"])
        has_shift = float(data.get("max_abs_shift", 0.0)) >= 1e-3
        if data["constructions"]:
            cap0 = ("<b>Capa 0 activa (construcciones)</b>: el corrimiento Δfₙ "
                    "sale de Im(β) de las construcciones asignadas.")
        elif has_shift:
            cap0 = ("<b>Z por default de los materiales</b>: los materiales "
                    "porosos aportan reactancia (Im de la Z equivalente de Miki) "
                    "→ Δfₙ ≠ 0 sin construcción manual. La absorción medida (α) no "
                    "se toca: solo se agrega la reactancia.")
        else:
            cap0 = ("Sin construcciones y materiales sin reactancia apreciable "
                    "→ Δfₙ ≈ 0 (solo amortiguamiento).")
        note = QLabel(
            f"<b>{n_modes} modos</b> · modelo de amortiguamiento: "
            f"<b>{data['model']}</b>.<br>{cap0}<br>"
            f"f efectiva = frecuencia de resonancia que usa la dinámica "
            f"(FRF/campo/FoM); la <i>forma</i> modal no cambia (perturbación "
            f"de 1er orden). RT60ₙ = 6.908/(ξₙ·2π·f) del modo aislado.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c6f85; font-size: 9pt;")
        v.addWidget(note)

        if has_shift:
            v.addWidget(self._shift_summary_label(data))

        rows = self._rows()
        self.table = QTableWidget(len(rows), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            for c, txt in enumerate(row):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3 and txt not in ("0.00", "—"):
                    fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
                self.table.setItem(r, c, it)
        hdr = self.table.horizontalHeader()
        for c in range(len(self.COLS)):
            hdr.setSectionResizeMode(c, QHeaderView.Stretch)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        for fmt in ("csv", "txt", "png"):
            b = QPushButton(f"Exportar {fmt.upper()}")
            b.setMinimumWidth(130)
            b.clicked.connect(lambda _=False, f=fmt: self._export(f))
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        v.addWidget(bb)

    def _shift_summary_label(self, data):
        d = data["dfreq"]
        i_max = int(np.argmax(np.abs(d))) if len(d) else -1
        if i_max < 0 or abs(d[i_max]) < 1e-3:
            txt = "Corrimiento máximo: Δfₙ ≈ 0 Hz (reactancia despreciable)."
        else:
            f0 = data["f_rig"][i_max]; f1 = data["f_eff"][i_max]
            txt = (f"Corrimiento máximo: modo {i_max} · "
                   f"{f0:.2f} → {f1:.2f} Hz (Δ = {d[i_max]:+.2f} Hz).")
        lbl = QLabel(txt)
        lbl.setStyleSheet("color: #179299; font-size: 10pt;")
        return lbl

    @staticmethod
    def _rt60_from_xi(f, xi):
        """RT60 del modo aislado: SPL cae 60 dB con envolvente e^{-δt},
        δ = ξ·2π·f [Np/s]; T60 = 6.908/δ (3·ln10). ξ≤0 → sin decaimiento."""
        d = xi * 2.0 * np.pi * f
        return 6.908 / d if d > 1e-12 else float("inf")

    def _rows(self):
        d = self._data
        xi = d["xi"]
        rows = []
        for i in range(len(d["f_rig"])):
            f0 = float(d["f_rig"][i]); f1 = float(d["f_eff"][i])
            df = f1 - f0
            if xi is not None:
                xv = float(xi[i])
                xi_txt = f"{xv:.5f}"
                rt = self._rt60_from_xi(f1, xv)
                rt_txt = "∞" if not np.isfinite(rt) else f"{rt:.3f}"
            else:
                xi_txt = "—"; rt_txt = "—"
            rows.append((str(i), f"{f0:.2f}", f"{f1:.2f}",
                         f"{df:+.2f}" if abs(df) >= 5e-3 else "0.00",
                         xi_txt, rt_txt))
        return rows

    def _export(self, fmt: str):
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar tabla de modos como {fmt.upper()}",
            f"modos_shift_xi.{fmt}", f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        if fmt == "png":
            self.table.grab().save(path, "PNG")
            return
        hdr = ["modo_n", "f_rigida_hz", "f_efectiva_hz",
               "delta_f_hz", "xi_n", "rt60_n_s"]
        rows = self._rows()
        # En CSV/TXT sacamos los signos unicode raros: infinito y guion largo.
        def clean(x):
            return {"∞": "inf", "—": ""}.get(x, x).replace("+", "")
        if fmt == "csv":
            lines = [",".join(hdr)]
            lines += [",".join(clean(x) for x in r) for r in rows]
        else:
            widths = [8, 14, 15, 12, 12, 12]
            lines = ["".join(h.rjust(w) for h, w in zip(hdr, widths))]
            lines += ["".join(clean(x).rjust(w)
                              for x, w in zip(r, widths)) for r in rows]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


class AbsorptionChoiceDialog(QDialog):
    """Gate de absorcion: que usar cuando NINGUNA cara tiene material asignado.

    Existe porque f_Schroeder depende de la absorcion (f_S ∝ α^-1/2) y sin
    asignaciones el `FaceMaterialMap` cae a su `default` alfabetico, que el
    usuario nunca eligio. Antes eso pasaba en silencio y ademas el auto-tuner
    de malla usaba un α=0.05 fijo, incoherente con el numero que el panel
    mostraba en pantalla.

    Tres caminos (los tres dejan el modelo en un estado explicito):
      - **alpha**: coeficiente uniforme, sin tocar el mapa de materiales.
      - **preset**: uno de los 5 `MATERIAL_PRESETS` -> asigna piso/paredes/techo.
      - **uniform**: un material del catalogo para TODAS las caras.

    Los dos ultimos ASIGNAN de verdad (via `apply_zone_materials`), asi que
    tras elegirlos el gate no vuelve a aparecer y todo lo que cuelga de los
    materiales (ξ por modo, RT60, SBIR) queda coherente con f_S.
    """

    def __init__(self, mat_names, parent=None, default_alpha: float = 0.05):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Absorción del recinto")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)

        info = QLabel(
            "Ninguna cara tiene material asignado.\n\n"
            "La frecuencia de Schroeder y la densidad de malla dependen de la "
            "absorción: f_S ∝ α^(−1/2), así que una sala viva necesita una malla "
            "mucho más fina que una tratada. Elegí de dónde sale la absorción.\n\n"
            "La elección se recuerda por esta sesión."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self._grp = QButtonGroup(self)

        # --- (a) coeficiente uniforme ---
        self.rb_alpha = QRadioButton("Coeficiente α uniforme")
        self.rb_alpha.setChecked(True)
        self._grp.addButton(self.rb_alpha)
        lay.addWidget(self.rb_alpha)
        row_a = QHBoxLayout()
        row_a.addSpacing(24)
        row_a.addWidget(QLabel("α ="))
        self.sb_alpha = QDoubleSpinBox()
        self.sb_alpha.setRange(0.01, 1.0)
        self.sb_alpha.setDecimals(3)
        self.sb_alpha.setSingleStep(0.01)
        self.sb_alpha.setValue(float(default_alpha))
        self.sb_alpha.setToolTip(
            "0.01 = superficie totalmente reflectante (piso del catálogo).\n"
            "0.05 = sala viva sin tratar.  0.20 = alfombrada.  0.40+ = tratada.\n"
            "Ojo: valores bajos disparan f_S y con él el costo del FEM."
        )
        row_a.addWidget(self.sb_alpha)
        self.lbl_alpha_hint = QLabel("")
        self.lbl_alpha_hint.setStyleSheet("color: #179299; font-size: 9pt;")
        row_a.addWidget(self.lbl_alpha_hint)
        row_a.addStretch(1)
        lay.addLayout(row_a)

        # --- (b) preset por zona ---
        self.rb_preset = QRadioButton("Preset de sala (asigna piso / paredes / techo)")
        self._grp.addButton(self.rb_preset)
        lay.addWidget(self.rb_preset)
        row_b = QHBoxLayout()
        row_b.addSpacing(24)
        self.cb_preset = QComboBox()
        self.cb_preset.addItems(ml.preset_names())
        row_b.addWidget(self.cb_preset, 1)
        lay.addLayout(row_b)

        # --- (c) un material para todas ---
        self.rb_uniform = QRadioButton("Un material del catálogo para todas las caras")
        self._grp.addButton(self.rb_uniform)
        lay.addWidget(self.rb_uniform)
        row_c = QHBoxLayout()
        row_c.addSpacing(24)
        self.cb_material = QComboBox()
        self.cb_material.addItems(list(mat_names))
        row_c.addWidget(self.cb_material, 1)
        lay.addLayout(row_c)

        note = QLabel(
            "Los dos últimos asignan materiales de verdad: después vas a poder "
            "retocarlos cara por cara en «Materiales…»."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #179299; font-size: 9pt;")
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.sb_alpha.valueChanged.connect(self._update_hint)
        self._update_hint()

    def _update_hint(self):
        a = float(self.sb_alpha.value())
        if a <= 0.015:
            self.lbl_alpha_hint.setText("(totalmente reflectante — malla muy cara)")
        elif a <= 0.06:
            self.lbl_alpha_hint.setText("(sala viva sin tratar)")
        elif a <= 0.25:
            self.lbl_alpha_hint.setText("(alfombrada / algo tratada)")
        else:
            self.lbl_alpha_hint.setText("(tratada)")

    def choice(self) -> tuple:
        """('alpha', valor) | ('preset', nombre) | ('uniform', material)."""
        if self.rb_preset.isChecked():
            return ("preset", self.cb_preset.currentText())
        if self.rb_uniform.isChecked():
            return ("uniform", self.cb_material.currentText())
        return ("alpha", float(self.sb_alpha.value()))


# ---------------------------------------------------------------------------
# Capa 0 (Etapa 5b): editor de "construccion de pared" y asignacion por cara
# ---------------------------------------------------------------------------
class ConstructionEditorDialog(QDialog):
    """Editor de una construccion de pared (Capa 0): tipo + parametros -> spec de
    impedance.build_surface, con preview de alpha(f) y la resonancia. Devuelve el
    spec en self.spec (o None si se cancela)."""

    _TYPES = [
        ("Panel perforado", "perforated"),
        ("Microperforado (MPP)", "perforated"),
        ("Membrana / panel", "membrane"),
        ("Poroso + cámara", "porous"),
    ]

    def __init__(self, spec=None, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Construcción de pared")
        self.resize(720, 460)
        self.spec = None
        root = QHBoxLayout(self)

        # --- Columna izquierda: controles ---
        left = QVBoxLayout()
        root.addLayout(left, 0)
        self.combo_type = QComboBox()
        for label, _t in self._TYPES:
            self.combo_type.addItem(label)
        frm = QFormLayout()
        frm.addRow("Tipo:", self.combo_type)
        left.addLayout(frm)

        def _spin(lo, hi, val, dec=2, step=1.0, suf=""):
            s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec)
            s.setSingleStep(step); s.setValue(val)
            if suf:
                s.setSuffix(" " + suf)
            return s

        # Perforado / MPP (mm, %, mm)
        self.grp_perf = QGroupBox("Panel perforado (Maa 1998)")
        fp = QFormLayout(self.grp_perf)
        self.p_t = _spin(0.1, 50.0, 2.0, 2, 0.1, "mm")
        self.p_d = _spin(0.05, 20.0, 1.5, 2, 0.05, "mm")
        self.p_ratio = _spin(0.1, 50.0, 2.0, 2, 0.1, "%")
        self.p_D = _spin(1.0, 1000.0, 100.0, 0, 5.0, "mm")
        fp.addRow("Espesor t:", self.p_t)
        fp.addRow("Diámetro orificio d:", self.p_d)
        fp.addRow("Perforación:", self.p_ratio)
        fp.addRow("Cámara de aire D:", self.p_D)
        left.addWidget(self.grp_perf)

        # Membrana
        self.grp_memb = QGroupBox("Membrana / panel (masa-resorte)")
        fm2 = QFormLayout(self.grp_memb)
        self.m_mass = _spin(0.2, 50.0, 3.0, 2, 0.1, "kg/m²")
        self.m_D = _spin(1.0, 1000.0, 80.0, 0, 5.0, "mm")
        self.m_damp = _spin(0.0, 0.5, 0.02, 3, 0.01, "")
        fm2.addRow("Masa superficial m:", self.m_mass)
        fm2.addRow("Cámara de aire D:", self.m_D)
        fm2.addRow("Pérdidas (rel.):", self.m_damp)
        left.addWidget(self.grp_memb)

        # Poroso + camara
        self.grp_por = QGroupBox("Poroso + cámara")
        fpo = QFormLayout(self.grp_por)
        self.po_model = QComboBox()
        self.po_model.addItems(["Miki", "Delany-Bazley", "JCA (5 parám.)"])
        self.po_sigma = _spin(1000.0, 200000.0, 15000.0, 0, 1000.0, "Pa·s/m²")
        self.po_th = _spin(5.0, 500.0, 50.0, 0, 5.0, "mm")
        self.po_gap = _spin(0.0, 1000.0, 100.0, 0, 5.0, "mm")
        fpo.addRow("Modelo:", self.po_model)
        fpo.addRow("Resistividad σ:", self.po_sigma)
        fpo.addRow("Espesor poroso:", self.po_th)
        fpo.addRow("Cámara de aire detrás:", self.po_gap)
        # JCA extra
        self.po_phi = _spin(0.1, 1.0, 0.98, 2, 0.01, "")
        self.po_ainf = _spin(1.0, 5.0, 1.0, 2, 0.05, "")
        self.po_lam = _spin(1.0, 1000.0, 60.0, 0, 5.0, "µm")
        self.po_lamp = _spin(1.0, 2000.0, 120.0, 0, 5.0, "µm")
        self.row_phi = self.po_phi; self.row_ainf = self.po_ainf
        fpo.addRow("Porosidad φ:", self.po_phi)
        fpo.addRow("Tortuosidad α∞:", self.po_ainf)
        fpo.addRow("Long. viscosa Λ:", self.po_lam)
        fpo.addRow("Long. térmica Λ':", self.po_lamp)
        self._jca_widgets = [self.po_phi, self.po_ainf, self.po_lam, self.po_lamp]
        left.addWidget(self.grp_por)
        left.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)

        # --- Columna derecha: preview ---
        right = QVBoxLayout()
        root.addLayout(right, 1)
        self.lbl_reso = QLabel("—")
        self.lbl_reso.setWordWrap(True)
        self.lbl_reso.setStyleSheet("color:#333; font-size:9pt; font-weight:600;")
        right.addWidget(self.lbl_reso)
        if _HAS_MPL:
            self._fig, self._ax = plt.subplots(figsize=(4.6, 3.4), dpi=96)
            self._canvas = FigureCanvas(self._fig)
            right.addWidget(self._canvas, 1)
        else:
            right.addWidget(QLabel("matplotlib no disponible."))
            self._canvas = None

        # Señales -> preview
        for w in (self.combo_type, self.po_model):
            w.currentIndexChanged.connect(self._sync)
        for w in (self.p_t, self.p_d, self.p_ratio, self.p_D, self.m_mass,
                  self.m_D, self.m_damp, self.po_sigma, self.po_th, self.po_gap,
                  self.po_phi, self.po_ainf, self.po_lam, self.po_lamp):
            w.valueChanged.connect(self._update_preview)

        if spec:
            self._load_spec(spec)
        self._sync()

    # ------------------------------------------------------------------
    def _kind(self):
        idx = self.combo_type.currentIndex()
        return self._TYPES[idx][0]

    def _sync(self):
        """Muestra el grupo de parametros del tipo elegido + JCA condicional."""
        kind = self._kind()
        self.grp_perf.setVisible(kind in ("Panel perforado", "Microperforado (MPP)"))
        self.grp_memb.setVisible(kind == "Membrana / panel")
        self.grp_por.setVisible(kind == "Poroso + cámara")
        is_jca = self.po_model.currentText().startswith("JCA")
        for w in self._jca_widgets:
            w.setVisible(is_jca)
        # microperforado: preset de orificio chico la primera vez
        self._update_preview()

    def _current_spec(self):
        kind = self._kind()
        if kind in ("Panel perforado", "Microperforado (MPP)"):
            return {"type": "perforated",
                    "thickness": self.p_t.value() * 1e-3,
                    "hole_diam": self.p_d.value() * 1e-3,
                    "ratio": self.p_ratio.value() / 100.0,
                    "cavity_depth": self.p_D.value() * 1e-3}
        if kind == "Membrana / panel":
            return {"type": "membrane",
                    "mass_per_area": self.m_mass.value(),
                    "cavity_depth": self.m_D.value() * 1e-3,
                    "damping": self.m_damp.value()}
        # Poroso
        model_txt = self.po_model.currentText()
        gap = self.po_gap.value() * 1e-3
        if model_txt.startswith("JCA"):
            return {"type": "porous_jca",
                    "phi": self.po_phi.value(),
                    "alpha_inf": self.po_ainf.value(),
                    "sigma": self.po_sigma.value(),
                    "Lambda": self.po_lam.value() * 1e-6,
                    "Lambda_p": self.po_lamp.value() * 1e-6,
                    "thickness": self.po_th.value() * 1e-3,
                    "air_gap": gap}
        model = "db" if model_txt.startswith("Delany") else "miki"
        return {"type": "porous", "sigma": self.po_sigma.value(),
                "thickness": self.po_th.value() * 1e-3,
                "air_gap": gap, "model": model}

    def _resonance_hint(self, spec):
        c = 343.0
        t = spec.get("type")
        if t == "perforated":
            t_eff = spec["thickness"] + 0.85 * spec["hole_diam"]
            f0 = (c / (2 * np.pi)) * np.sqrt(spec["ratio"] / (t_eff * spec["cavity_depth"]))
            return f"Resonancia (Helmholtz distribuida) ≈ {f0:.0f} Hz"
        if t == "membrane":
            f0 = 60.0 / np.sqrt(max(spec["mass_per_area"] * spec["cavity_depth"], 1e-9))
            return f"Resonancia masa-resorte f₀ ≈ {f0:.0f} Hz"
        gap = spec.get("air_gap", 0.0)
        if gap and gap > 0:
            return f"Cámara de aire: pico λ/4 ≈ {c/(4*gap):.0f} Hz"
        return "Poroso sin cámara: absorción de banda ancha (sin resonancia)"

    def _update_preview(self):
        if self._canvas is None:
            return
        try:
            spec = self._current_spec()
            surf = imp.build_surface(spec)
            fg = np.geomspace(20.0, 500.0, 160)
            a = surf.alpha_random(fg)
            self.lbl_reso.setText(self._resonance_hint(spec))
        except Exception as e:
            self.lbl_reso.setText(f"Parámetros inválidos: {e}")
            return
        ax = self._ax
        ax.clear()
        ax.plot(fg, a, color="#1f6fbf", linewidth=1.8)
        ax.set_xscale("log")
        ax.set_xlim(20, 500)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Frecuencia (Hz)", fontsize=9)
        ax.set_ylabel("α (incidencia aleatoria)", fontsize=9)
        ax.grid(True, which="both", linestyle="-", linewidth=0.5, alpha=0.3)
        ax.tick_params(labelsize=8)
        self._fig.tight_layout(pad=0.8)
        self._canvas.draw_idle()

    def _load_spec(self, spec):
        """Carga un spec existente a los controles (para editar)."""
        t = spec.get("type")
        if t == "perforated":
            self.combo_type.setCurrentIndex(0)
            self.p_t.setValue(spec["thickness"] * 1e3)
            self.p_d.setValue(spec["hole_diam"] * 1e3)
            self.p_ratio.setValue(spec["ratio"] * 100.0)
            self.p_D.setValue(spec["cavity_depth"] * 1e3)
        elif t == "membrane":
            self.combo_type.setCurrentIndex(2)
            self.m_mass.setValue(spec["mass_per_area"])
            self.m_D.setValue(spec["cavity_depth"] * 1e3)
            self.m_damp.setValue(spec.get("damping", 0.02))
        elif t in ("porous", "porous_jca"):
            self.combo_type.setCurrentIndex(3)
            self.po_sigma.setValue(spec.get("sigma", 15000.0))
            self.po_th.setValue(spec.get("thickness", 0.05) * 1e3)
            self.po_gap.setValue(spec.get("air_gap", 0.0) * 1e3)
            if t == "porous_jca":
                self.po_model.setCurrentIndex(2)
                self.po_phi.setValue(spec.get("phi", 0.98))
                self.po_ainf.setValue(spec.get("alpha_inf", 1.0))
                self.po_lam.setValue(spec.get("Lambda", 6e-5) * 1e6)
                self.po_lamp.setValue(spec.get("Lambda_p", 1.2e-4) * 1e6)
            else:
                self.po_model.setCurrentIndex(
                    1 if spec.get("model") == "db" else 0)

    def _on_accept(self):
        try:
            spec = self._current_spec()
            imp.build_surface(spec)          # valida
        except Exception as e:
            QMessageBox.warning(self, "Construcción inválida", str(e))
            return
        # microperforado: marcar el subtipo para la etiqueta
        if self._kind() == "Microperforado (MPP)":
            spec["_label"] = "microperforado"
        self.spec = spec
        self.accept()


class WallConstructionsDialog(QDialog):
    """Asigna construcciones de Capa 0 a CUALQUIER superficie (caras, parches y
    muebles). Edita una COPIA del mapa; el panel la adopta al Aceptar. Cada
    superficie puede tener una construccion (o ninguna -> cae a su material,
    alpha->beta real). Devuelve self.result_map (clave: firma de grupo, patch.key
    o __furniture_i__)."""

    def __init__(self, groups, construction_map, parent=None,
                 patches=None, furniture=None, auto_tags=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Construcciones (paredes, parches y muebles)")
        self.resize(700, 540)
        self.result_map = dict(construction_map or {})
        # Z por default del MATERIAL de cada superficie (clave -> texto): se
        # muestra read-only cuando la cara no tiene construccion explicita, para
        # que el panel refleje el material actual y su reactancia auto (poroso) o
        # su beta real (duro). Fuente de verdad = la asignacion de material.
        self._auto_tags = dict(auto_tags or {})
        # Entradas unificadas: (clave, etiqueta, tipo, area).
        self._entries = []
        for g in groups:
            self._entries.append((g.signature, g.label, "pared", g.area))
        for p in (patches or []):
            lbl = getattr(p, "label", "") or "parche"
            self._entries.append((p.key, f"⬒ {lbl}", "parche", getattr(p, "area", 0.0)))
        for i, fu in enumerate(furniture or []):
            lbl = getattr(fu, "label", "") or f"mueble {i+1}"
            self._entries.append((f"__furniture_{i}__", f"▣ {lbl}", "mueble", None))
        root = QVBoxLayout(self)

        help_lbl = QLabel(
            "Asigná una construcción (panel perforado, membrana, poroso con "
            "cámara) a una o varias superficies: paredes, parches (⬒) o muebles "
            "(▣). Da la impedancia en la banda modal (amortiguamiento + "
            "corrimiento de fₙ). Las superficies sin construcción usan la <b>Z "
            "por default de su material</b> (mostrada en gris): reactancia auto "
            "si es poroso, β real si es duro. Asignar una construcción la pisa.")
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color:#11111b; font-size:9pt;")
        root.addWidget(help_lbl)

        self.list_faces = QListWidget()
        self.list_faces.setSelectionMode(QListWidget.ExtendedSelection)
        root.addWidget(self.list_faces, 1)
        self._refresh_list()

        row = QHBoxLayout()
        self.btn_new = QPushButton("Nueva construcción y asignar…")
        self.btn_new.setToolTip("Abre el editor; al aceptar, asigna esa "
                                "construcción a las caras seleccionadas.")
        self.btn_new.clicked.connect(self._new_and_assign)
        row.addWidget(self.btn_new)
        self.btn_edit = QPushButton("Editar la de la cara…")
        self.btn_edit.clicked.connect(self._edit_selected)
        row.addWidget(self.btn_edit)
        self.btn_clear = QPushButton("Quitar de seleccionadas")
        self.btn_clear.clicked.connect(self._clear_selected)
        row.addWidget(self.btn_clear)
        root.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _refresh_list(self):
        self.list_faces.clear()
        for key, label, kind, area in self._entries:
            spec = self.result_map.get(key)
            if spec:
                tag = imp.spec_label(spec)
            else:
                # sin construccion -> Z por default del material (read-only)
                tag = self._auto_tags.get(key) or "— (usa el material)"
            area_txt = f"{area:.1f} m²   " if area is not None else ""
            it = QListWidgetItem(f"{label}   ·   {area_txt}→   {tag}")
            it.setData(Qt.UserRole, key)
            it.setForeground(QColor("#89b4fa") if spec else QColor("#8c8fa1"))
            self.list_faces.addItem(it)

    def _selected_sigs(self):
        return [it.data(Qt.UserRole) for it in self.list_faces.selectedItems()]

    def _new_and_assign(self):
        sigs = self._selected_sigs()
        if not sigs:
            QMessageBox.information(self, "Sin selección",
                                    "Seleccioná primero una o varias caras.")
            return
        dlg = ConstructionEditorDialog(parent=self)
        if dlg.exec_() and dlg.spec:
            for s in sigs:
                self.result_map[s] = dict(dlg.spec)
            self._refresh_list()

    def _edit_selected(self):
        sigs = self._selected_sigs()
        if len(sigs) != 1:
            QMessageBox.information(self, "Editar",
                                    "Seleccioná exactamente una cara para editar.")
            return
        spec = self.result_map.get(sigs[0])
        dlg = ConstructionEditorDialog(spec=spec, parent=self)
        if dlg.exec_() and dlg.spec:
            self.result_map[sigs[0]] = dict(dlg.spec)
            self._refresh_list()

    def _clear_selected(self):
        for s in self._selected_sigs():
            self.result_map.pop(s, None)
        self._refresh_list()


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------
class AcousticPanel(QWidget):
    """Panel para FEM modal sobre el recinto actual."""

    # Indica al main que el panel quiere actualizar el viewer.
    redrawRequested = pyqtSignal()
    # El usuario pidio importar CAD (boton "Importar CAD..."). El main
    # se encarga del FileDialog + diagnosis + repair dialog.
    cadImportRequested = pyqtSignal()
    cadClearRequested  = pyqtSignal()
    # Decisión de absorción del gate (α o materiales), para que Predicción la
    # herede sin volver a preguntar. Emite el estado normalizado o None.
    absorptionChoiceChanged = pyqtSignal(object)

    def __init__(self, viewer, get_surface: Callable, get_dims_hint=None):
        """
        Parameters
        ----------
        viewer : pyqtgraph.opengl.GLViewWidget (el IsoViewer)
        get_surface : callable -> (verts: ndarray, tris: ndarray)
            Funcion que devuelve la superficie actual del recinto.
        get_dims_hint : callable -> (Lx, Ly, Lz) | None
        """
        super().__init__()
        self.viewer = viewer
        # La callable original del main (devuelve la malla parametrica).
        self._get_param_surface_callable = get_surface
        self.get_dims_hint = get_dims_hint or (lambda: (10.0, 10.0, 5.0))

        # Estado
        self.sources = SourceArray()
        # Mobiliario (Fase C): lista de furniture.Furniture. Se talla en la
        # malla (obstaculo rigido) y sus caras absorben via A36. Persistido en
        # .room v7. Vacio = comportamiento historico (sin muebles).
        self.furniture = []
        # Material por mueble (indice en self.furniture -> nombre de material del
        # catalogo self._mat_lib). Sin entrada -> mueble RIGIDO (None -> alpha
        # default 0.03), que es el default fisico correcto. Lo puebla el dialogo
        # de muebles (fuera de alcance headless; ver _furniture_mat_by_index).
        self._furniture_mat_names = {}
        # Estado de geometria importada (CAD) - DEBE inicializarse antes de
        # _compute_default_receiver porque este consulta get_surface.
        self._is_imported_cad = False
        self._imported_mesh = None
        self._imported_verts = None
        self._imported_tris = None
        self._mesh_decision = None     # ultima decision del router
        self.receiver = self._compute_default_receiver()
        self.modal_result = None       # aa.ModalSolution
        self._xi_per_mode = None
        # Capa 0 (Etapa 5): corrimiento de f_n por reactancia de pared (Im(beta)).
        # None = sin construcciones -> la dinamica usa las f_n rigidas (historico).
        # Array (Nm,) = f_n corridas que usan FRF/campo/FoM (la FORMA modal sigue
        # rigida, perturbacion de 1er orden). Lo puebla _compute_xi_from_materials.
        self._freq_shift_per_mode = None
        # Modelo de amortiguamiento modal (v2.23, Etapa 1 del reemplazo):
        #   "perturbation" -> perturbacion de frontera de 1er orden (Morse&Ingard
        #                     9.4.14 / Kuttruff 3.34). Captura el spread axial/
        #                     oblicuo que Sabine no ve. DEFAULT desde v2.24 (Etapa
        #                     3): mas exacto que Sabine bajo Schroeder, validado
        #                     <1% vs impedancia exacta hasta alpha≈0.3. Toda la
        #                     app (f_S, cruce, RT60, prediccion de ubicacion) ya
        #                     habla el modelo elegido, asi que el default es coherente.
        #   "a36"          -> Sabine por modo. Alterna; es el limite de campo difuso
        #                     de la perturbacion (caso oblicuo). Los .room viejos
        #                     sin la clave cargan como "a36" (reproducibilidad).
        self._damping_model = "perturbation"
        self._slice_heatmap_dialog = None   # SliceHeatmapDialog (no-modal)

        # Timer debounce: actualiza el campo 300 ms despues del ultimo movimiento
        from PyQt5.QtCore import QTimer
        self._field_timer = QTimer()
        self._field_timer.setSingleShot(True)
        self._field_timer.setInterval(350)
        self._field_timer.timeout.connect(self._deferred_field_update)

        # Overlays sobre el viewer
        self.src_markers = av.SourceMarkers(viewer)
        self.rcv_marker = av.ReceiverMarker(viewer)
        self.slice_item = av.FieldSliceItem(viewer)
        self.furn_markers = av.FurnitureMarkers(viewer)

        self._build_ui()
        self._refresh_sources_list()
        self._refresh_receiver_marker()
        self._refresh_furniture_list()

        # Señales del visor para plano interactivo
        if hasattr(self.viewer, 'slicePlaneHovered'):
            self.viewer.slicePlaneHovered.connect(self._on_slice_hovered)
        if hasattr(self.viewer, 'slicePlaneConfirmed'):
            self.viewer.slicePlaneConfirmed.connect(self._on_slice_confirmed)

    def _compute_default_receiver(self) -> tuple:
        """Centro del AABB del recinto actual (o fallback a dims_hint/2)."""
        try:
            verts, _tris = self.get_surface()
            cx, cy, _cz = verts.mean(axis=0)
            zmin = float(verts[:, 2].min())
            zmax = float(verts[:, 2].max())
            return (float(cx), float(cy), 0.5 * (zmin + zmax))
        except Exception:
            Lx, Ly, Lz = self.get_dims_hint()
            return (0.0, 0.0, Lz / 2.0)

    def get_surface(self):
        """Devuelve (verts, tris) de la geometria activa.

        Si hay CAD importado -> esa malla; si no -> la parametrica del main.
        """
        if self._is_imported_cad and self._imported_verts is not None:
            return self._imported_verts, self._imported_tris
        return self._get_param_surface_callable()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("Análisis acústico")
        title.setObjectName("TitleLabel")
        sub = QLabel("Modos por FEM · superposición de fuentes")
        sub.setObjectName("SubtitleLabel")
        layout.addWidget(title)
        layout.addWidget(sub)

        # --- Fuentes ---
        grp_src = QGroupBox("Fuentes omnidireccionales")
        vs = QVBoxLayout(grp_src)
        self.list_src = QListWidget()
        self.list_src.setMaximumHeight(120)
        self.list_src.itemSelectionChanged.connect(self._on_src_selection)
        self.list_src.itemChanged.connect(self._on_src_check_changed)
        self.list_src.setToolTip(
            "El checkbox activa/silencia la fuente: silenciada no radia\n"
            "(FRF, SBIR, FoM, campo 3D y Comparar la excluyen) pero conserva\n"
            "posición, curva y bafle. Útil para analizar parlante por parlante.")
        vs.addWidget(self.list_src)
        row = QHBoxLayout()
        row.setSpacing(4)   # menos espacio entre botones para que entren los 4
        self.btn_add_src = QPushButton("Añadir")
        self.btn_edit_src = QPushButton("Editar")
        self.btn_del_src = QPushButton("Quitar")
        self.btn_dup_src = QPushButton("Duplicar")
        for b in (self.btn_add_src, self.btn_edit_src, self.btn_del_src,
                  self.btn_dup_src):
            # setMinimumWidth(0) impide que Qt asuma anchos minimos basados en
            # el sizeHint del texto + padding; permite que se compriman uniforme
            # cuando el panel es angosto en vez de recortar el ultimo boton.
            b.setMinimumWidth(0)
            row.addWidget(b, 1)   # stretch=1 -> reparto uniforme
        vs.addLayout(row)
        self.btn_add_src.clicked.connect(self._add_source)
        self.btn_edit_src.clicked.connect(self._edit_source)
        self.btn_del_src.clicked.connect(self._remove_source)
        self.btn_dup_src.clicked.connect(self._duplicate_source)
        layout.addWidget(grp_src)

        # --- Muebles (obstáculos en el modelo modal: carve + absorción + SBIR) ---
        grp_furn = QGroupBox("Muebles")
        vf = QVBoxLayout(grp_furn)
        self.list_furn = QListWidget()
        self.list_furn.setMaximumHeight(110)
        self.list_furn.itemSelectionChanged.connect(self._on_furn_selection)
        self.list_furn.setToolTip(
            "Muebles como obstáculos en el modelo modal: la malla se talla\n"
            "(agujero rígido) y sus caras absorben según el material asignado.\n"
            "Afecta modos, RT/ξ y SBIR. Edición numérica; se ven como wireframe\n"
            "verde-azulado en el visor 3D. El efecto se aplica al recalcular FEM.")
        vf.addWidget(self.list_furn)
        rowf = QHBoxLayout(); rowf.setSpacing(4)
        self.btn_add_furn = QPushButton("Añadir")
        self.btn_edit_furn = QPushButton("Editar")
        self.btn_del_furn = QPushButton("Quitar")
        self.btn_dup_furn = QPushButton("Duplicar")
        for b in (self.btn_add_furn, self.btn_edit_furn, self.btn_del_furn,
                  self.btn_dup_furn):
            b.setMinimumWidth(0)
            rowf.addWidget(b, 1)
        vf.addLayout(rowf)
        self.btn_add_furn.clicked.connect(self._add_furniture)
        self.btn_edit_furn.clicked.connect(self._edit_furniture)
        self.btn_del_furn.clicked.connect(self._remove_furniture)
        self.btn_dup_furn.clicked.connect(self._duplicate_furniture)
        self.btn_preset_furn = QPushButton("Insertar preset ▾")
        self.btn_preset_furn.setToolTip(
            "Muebles armados (silla, sillón, escritorio, mesa, banqueta,\n"
            "velador, biblioteca): se insertan en el centro de la sala con un\n"
            "material sugerido. Después movelos/rotalos como cualquier mueble.")
        self.btn_preset_furn.clicked.connect(self._show_preset_menu)
        vf.addWidget(self.btn_preset_furn)
        layout.addWidget(grp_furn)

        # --- Receptor ---
        grp_rcv = QGroupBox("Receptor")
        fr = QFormLayout(grp_rcv)
        self.sb_rx = QDoubleSpinBox(); self.sb_rx.setRange(-1e3, 1e3); self.sb_rx.setDecimals(3); self.sb_rx.setValue(self.receiver[0])
        self.sb_ry = QDoubleSpinBox(); self.sb_ry.setRange(-1e3, 1e3); self.sb_ry.setDecimals(3); self.sb_ry.setValue(self.receiver[1])
        self.sb_rz = QDoubleSpinBox(); self.sb_rz.setRange(-1e3, 1e3); self.sb_rz.setDecimals(3); self.sb_rz.setValue(self.receiver[2])
        for sb in (self.sb_rx, self.sb_ry, self.sb_rz):
            sb.setSingleStep(0.1)
            sb.valueChanged.connect(self._on_receiver_changed)
            # Compactar: con 3 decimales (-1000.000 a 1000.000) el sizeHint
            # default era ~90 px por spinbox; los 3 + labels + el label de la
            # row del FormLayout sumaban > 440 px y se recortaba Z.
            sb.setMinimumWidth(0)
            sb.setMaximumWidth(95)
        rrow = QHBoxLayout()
        rrow.setSpacing(3)
        rrow.addWidget(QLabel("X")); rrow.addWidget(self.sb_rx, 1)
        rrow.addWidget(QLabel("Y")); rrow.addWidget(self.sb_ry, 1)
        rrow.addWidget(QLabel("Z")); rrow.addWidget(self.sb_rz, 1)
        fr.addRow("Posición (m):", rrow)

        # --- Puntos de escucha (v2.16): lista de posiciones nombradas para
        # comparar (Sweet Spot + mics). El receptor de arriba es el "cursor";
        # "Agregar" captura su posicion actual como un punto con nombre.
        self.listen_points = []          # [{"name": str, "position": (x,y,z)}]
        self.list_pts = QListWidget()
        self.list_pts.setMaximumHeight(110)
        self.list_pts.setToolTip(
            "Puntos de escucha para «Comparar»: posicioná el receptor y\n"
            "apretá Agregar. Doble click = mover el receptor a ese punto.")
        self.list_pts.itemDoubleClicked.connect(self._goto_listen_point)
        fr.addRow(self.list_pts)
        prow = QHBoxLayout()
        prow.setSpacing(4)
        self.btn_add_pt = QPushButton("Agregar")
        self.btn_ren_pt = QPushButton("Renombrar")
        self.btn_del_pt = QPushButton("Quitar")
        for b in (self.btn_add_pt, self.btn_ren_pt, self.btn_del_pt):
            b.setMinimumWidth(0)
            prow.addWidget(b, 1)
        fr.addRow(prow)
        self.btn_add_pt.clicked.connect(self._add_listen_point)
        self.btn_ren_pt.clicked.connect(self._rename_listen_point)
        self.btn_del_pt.clicked.connect(self._remove_listen_point)
        self.btn_compare = QPushButton("Comparar…")
        self.btn_compare.setObjectName("PrimaryButton")
        self.btn_compare.setToolTip(
            "Compara los puntos de escucha con las fuentes ACTIVAS:\n"
            "tabla de figuras de mérito (MSV/VSA), curvas FRF y SBIR.")
        self.btn_compare.clicked.connect(self._open_compare_dialog)
        fr.addRow(self.btn_compare)
        layout.addWidget(grp_rcv)

        # --- Materiales de superficie ---
        _mat_folder = str(Path(__file__).parent / "materials")
        self._mat_lib = MaterialLibrary(_mat_folder)
        _names = self._mat_lib.names

        # --- Asignacion de materiales POR GRUPO DE CARAS (estilo EASE) ---
        # El esquema clasico (piso/techo/paredes con UN material cada uno) se
        # reemplaza por una ventana dedicada que detecta grupos de caras
        # planares y permite asignar un material distinto a cada uno. Las
        # asignaciones se guardan en self._face_mat_map y sobreviven el cierre
        # del dialogo y los cambios menores de geometria (firma estable por
        # normal/centroide/area).
        grp_mat = QGroupBox("Materiales de superficie")
        fmat = QFormLayout(grp_mat)

        # Default histórico explícito: antes era _names[0] (que daba
        # "Alfombra fina (pelo corto)" por orden de archivo); con la
        # biblioteca ordenada alfabéticamente _names[0] cambiaría, así que
        # se pinea por nombre (match por substring, robusto a renombres).
        _default_mat = next((n for n in _names if "alfombra fina" in n.lower()),
                            (_names[0] if _names else ""))
        self._face_mat_map = fm.FaceMaterialMap(default_material=_default_mat)
        self._face_groups_cache = None    # se calcula on-demand
        self._face_groups_for_verts_id = None  # invalidacion por identidad
        # Parches de absorcion sub-cara (.room v8). Vacio = comportamiento
        # historico (la absorcion la fija solo el material por cara / A36).
        self._patches = []                # List[absorption_patch.AbsorptionPatch]
        # Capa 0 (Etapa 5): construccion de pared por cara. {signature: spec dict}
        # (spec = impedance.build_surface). Paralelo al FaceMaterialMap: la
        # construccion da beta COMPLEJA (amortiguamiento por Re + corrimiento de
        # f_n por Im); el material sigue dando alpha para bandas > f_S (difuso).
        # Vacio = comportamiento historico (alpha->beta real, sin corrimiento).
        self._construction_map = {}       # Dict[str signature, dict spec]
        # Reactancia AUTO del material (corrimiento de f_n por Im(beta) sintetizada
        # de un poroso Miki ajustado al alpha): OPT-IN, apagada por default desde la
        # auditoria 2026-09-04 (hallazgo M1: modelo no medido + Miki extrapolado,
        # sesga f_n hasta ~9% en salas muy tratadas). El amortiguamiento (Re beta)
        # es exacto y va SIEMPRE; las construcciones explicitas aportan reactancia
        # siempre. Esto es solo para la Z auto derivada del alpha del catalogo.
        self._auto_material_reactance = False

        # --- Gate de absorcion para f_Schroeder (v2.23) ---
        # El FaceMaterialMap SIEMPRE devuelve un material (su `default`), asi
        # que "no asignaste nada" no se detecta por RT=None: se detecta contando
        # asignaciones EXPLICITAS. Sin ellas, f_S salia del default alfabetico
        # ("Alfombra fina", α=0.20) sin que el usuario lo eligiera nunca.
        # Ahora se le pregunta UNA vez por sesion y se recuerda la respuesta.
        self._abs_choice_alpha = None     # float si eligio "α fijo"; None si no
        self._abs_choice_asked = False    # ya se pregunto en esta sesion
        self._abs_choice_txt = ""         # descripcion legible de la eleccion
        # Opcion C (v2.24): resolver modos NO exige absorcion (los modos son de
        # pared rigida). Se avisa UNA vez por sesion si se resuelve sin elegirla.
        self._warned_no_absorption = False

        self.btn_open_materials = QPushButton("Materiales…")
        self.btn_open_materials.setObjectName("PrimaryButton")
        self.btn_open_materials.setToolTip(
            "Abre la ventana de asignacion de materiales por grupo de caras.\n"
            "Las asignaciones se guardan al cerrar y se restauran al abrirla de nuevo."
        )
        self.btn_open_materials.clicked.connect(self._open_materials_dialog)
        fmat.addRow(self.btn_open_materials)

        self.lbl_mat_summary = QLabel("Sin asignaciones (todos α=0.03 por defecto)")
        self.lbl_mat_summary.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        self.lbl_mat_summary.setWordWrap(True)
        fmat.addRow(self.lbl_mat_summary)

        self.lbl_rt60 = QLabel("RT60 medio: — s")
        self.lbl_rt60.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        self.lbl_rt60.setWordWrap(True)
        fmat.addRow(self.lbl_rt60)

        self.btn_open_patches = QPushButton("Parches de absorcion…")
        self.btn_open_patches.setToolTip(
            "Dibuja regiones (parches) DENTRO de una cara con su propio material.\n"
            "Da resolucion sub-cara al amortiguamiento modal (A36): un modo con\n"
            "antinodo sobre el parche se amortigua mas. Activar parches recalcula\n"
            "la absorcion con cuadratura fina (mas precisa que la malla gruesa)."
        )
        self.btn_open_patches.clicked.connect(self._open_patches_dialog)
        fmat.addRow(self.btn_open_patches)

        self.lbl_patch_summary = QLabel("Sin parches")
        self.lbl_patch_summary.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        self.lbl_patch_summary.setWordWrap(True)
        fmat.addRow(self.lbl_patch_summary)

        # Capa 0 (Etapa 5b): construccion de pared por cara (impedancia Z).
        self.btn_open_constructions = QPushButton("Construcciones de pared…")
        self.btn_open_constructions.setToolTip(
            "Asigna una construcción (panel perforado, membrana, poroso con\n"
            "cámara) a caras. Da la impedancia de pared en la banda modal:\n"
            "amortiguamiento por banda MÁS el corrimiento de las frecuencias\n"
            "modales por la reactancia (efecto que la pared rígida no ve).\n"
            "Las caras sin construcción siguen usando el α del material.")
        self.btn_open_constructions.clicked.connect(self._open_constructions_dialog)
        fmat.addRow(self.btn_open_constructions)
        self.lbl_constr_summary = QLabel("Sin construcciones")
        self.lbl_constr_summary.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        self.lbl_constr_summary.setWordWrap(True)
        fmat.addRow(self.lbl_constr_summary)

        # Reactancia auto del material (opt-in, apagada por default). Corre f_n con
        # una reactancia sintetizada del alpha (Miki extrapolado, MODELO NO MEDIDO).
        self.chk_auto_reactance = QCheckBox(
            "Reactancia por material (experimental, no medida)")
        self.chk_auto_reactance.setChecked(self._auto_material_reactance)
        self.chk_auto_reactance.setToolTip(
            "APAGADO (recomendado): las caras sin construcción usan β real (solo\n"
            "amortiguamiento exacto del α). Las frecuencias modales NO se corren.\n\n"
            "ENCENDIDO: además sintetiza una reactancia de poroso (Miki) desde el α\n"
            "y corre las fₙ. Es un MODELO NO MEDIDO y Miki queda extrapolado en la\n"
            "banda modal; puede correr las fₙ hasta ~9% en salas muy tratadas. Es\n"
            "una hipótesis a validar contra mediciones, no exactitud. Las\n"
            "construcciones explícitas aportan reactancia con o sin esto.")
        self.chk_auto_reactance.toggled.connect(self._on_auto_reactance_toggled)
        fmat.addRow(self.chk_auto_reactance)

        btn_rt60_plot  = QPushButton("Ver RT60 calculado")
        btn_reload_mat = QPushButton("Recargar materiales")
        btn_rt60_plot.clicked.connect(self._show_rt60_plot)
        btn_reload_mat.clicked.connect(self._reload_materials)
        fmat.addRow(btn_rt60_plot)
        fmat.addRow(btn_reload_mat)

        # Modelo de amortiguamiento modal. Perturbación = perturbación de frontera
        # de 1er orden (Morse&Ingard 9.4.14): capta el spread axial/oblicuo que
        # Sabine no ve. DEFAULT desde v2.24 (Etapa 3), por eso va primero (índice 0).
        # A36 = Sabine por modo, alterna (el límite de campo difuso de la perturbación).
        self.combo_damping = QComboBox()
        self.combo_damping.addItem("Perturbación de frontera", "perturbation")
        self.combo_damping.addItem("Sabine por modo (A36)", "a36")
        self.combo_damping.setToolTip(
            "Cómo se convierte la absorción en amortiguamiento modal ξ.\n"
            "• Perturbación (DEFAULT): usa la admitancia de la pared y la integral\n"
            "  de superficie de cada modo (sin pasar por RT60). Da un ξ distinto\n"
            "  para axiales/oblicuos aun con material uniforme; validado <1 %\n"
            "  contra el problema de impedancia exacto hasta α≈0.3. Más exacto que\n"
            "  Sabine bajo Schroeder.\n"
            "• Sabine (A36): RT60 de Sabine ponderado por la forma modal. Con\n"
            "  material uniforme da el mismo RT para todos los modos; es el límite\n"
            "  de campo difuso de la perturbación (caso oblicuo).\n"
            "Cambiar el modelo recalcula ξ si ya hay modos resueltos.")
        self.combo_damping.currentIndexChanged.connect(self._on_damping_model_changed)
        fmat.addRow("Amortiguamiento:", self.combo_damping)
        layout.addWidget(grp_mat)

        # --- Frecuencia de Schroeder (v2.16: movida arriba, entre Materiales
        # y FEM — es el primer numero que uno quiere ver antes de mallar) ---
        grp_fs = QGroupBox("Frecuencia de Schroeder")
        ffs = QFormLayout(grp_fs)

        self.lbl_schroeder = QLabel("f_Schroeder: —")
        self.lbl_schroeder.setStyleSheet("color: #94e2d5; font-weight: 600;")
        ffs.addRow(self.lbl_schroeder)

        # Cruce por solapamiento modal NUMERICO (2c §9): ve la forma del recinto,
        # a diferencia del f_Schroeder analitico (solo V y RT60). Requiere modos.
        self.lbl_fcross = QLabel("f_cross (M≥3, numérico): calculá los modos")
        self.lbl_fcross.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        self.lbl_fcross.setWordWrap(True)
        self.lbl_fcross.setToolTip(
            "Cruce por solapamiento modal M(f)=B_HP·n(f)≥3 con densidad modal "
            "NUMÉRICA (consciente de la forma). El f_Schroeder analítico usa la "
            "densidad de Weyl (solo volumen); este ve splay/taper/arco. "
            "Acotado a la banda válida de la malla."
        )
        ffs.addRow(self.lbl_fcross)

        # Eleccion de absorcion recordada por sesion (gate v2.23). Solo se
        # muestra cuando hay una eleccion guardada: si asignaste materiales
        # por cara, el gate no aparece y este label queda oculto.
        self.lbl_abs_choice = QLabel("")
        self.lbl_abs_choice.setStyleSheet("color: #f9e2af; font-size: 9pt;")
        self.lbl_abs_choice.setWordWrap(True)
        self.lbl_abs_choice.setVisible(False)
        ffs.addRow(self.lbl_abs_choice)

        self.btn_schroeder = QPushButton("Calcular f_Schroeder")
        self.btn_schroeder.clicked.connect(self.compute_and_show_schroeder)
        ffs.addRow(self.btn_schroeder)
        layout.addWidget(grp_fs)

        # --- FEM modal ---
        grp_fem = QGroupBox("FEM modal")
        ff = QFormLayout(grp_fem)
        self.sb_nmodes = QSpinBox(); self.sb_nmodes.setRange(2, 500); self.sb_nmodes.setValue(12)
        # Tope 30 (era 10): el peor caso REAL es la sala mas viva del catalogo
        # (alpha=0.01, "Superficie totalmente reflectante") en el recinto mas
        # chico. alpha=0 NO es cota: RT=0.161V/(alpha·S) diverge -> f_S y npm
        # infinitos. Con alpha=0.01, npm = 6·f_S/c da ~28.7 en un booth de 2 m
        # y baja con el tamano (npm ∝ S^-1/2), asi que 30 cubre todo el rango
        # fisico representable. El tope viejo de 10 clipeaba en silencio desde
        # alpha≈0.02 (hormigon) para arriba.
        self.sb_density = QDoubleSpinBox(); self.sb_density.setRange(0.5, 30.0); self.sb_density.setValue(2.5); self.sb_density.setSingleStep(0.25); self.sb_density.setDecimals(2)
        self.sb_htarget = QDoubleSpinBox(); self.sb_htarget.setRange(0.05, 5.0); self.sb_htarget.setValue(0.40); self.sb_htarget.setSingleStep(0.05); self.sb_htarget.setDecimals(2); self.sb_htarget.setSuffix(" m")
        self.sb_htarget.setToolTip("Tamaño característico de tetraedro para gmsh.\n"
                                    "Más chico = más preciso, más lento.")
        ff.addRow("Nº modos:", self.sb_nmodes)

        # Sugerencia Weyl: cuantos modos hay por debajo de f_Schroeder.
        # Se actualiza al apretar "Calcular f_Schroeder" (mas abajo) o al
        # invalidarse la geometria. El usuario decide cuantos pedir; este
        # numero es solo informativo (ley de Weyl, termino de volumen +
        # correccion de superficie).
        self.lbl_modes_weyl = QLabel("≈ ? modos hasta f_Schroeder (calculá f_S)")
        self.lbl_modes_weyl.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        self.lbl_modes_weyl.setWordWrap(True)
        ff.addRow("", self.lbl_modes_weyl)

        # Tooltip mejorado: explicar la regla npm = ppw * f / c y apuntar al
        # widget de sugerencia (mas abajo) que la materializa con f_S.
        self.sb_density.setToolTip(
            "Elementos por metro del mallado voxel.\n"
            "Mas alto = malla mas fina, mayor precision, mayor tiempo de calculo.\n"
            "Regla: npm = 6 · f_max_deseado / 343  (ppw=6 puntos por longitud de onda).\n"
            "Para cubrir hasta f_Schroeder, usá el botón 'Aplicar npm sugerido' debajo.\n"
            "Rango 0.5-30: el tope cubre la sala más viva del catálogo (α=0.01) en\n"
            "el recinto más chico. Ojo: el costo va como npm³."
        )
        ff.addRow("Densidad voxel (1/m):", self.sb_density)

        # Compromiso D4: sugerir npm derivado de f_Schroeder, pero dejar al
        # usuario en control del slider. El boton "Aplicar" carga la sugerencia
        # al spinbox de un click. Se llena al apretar "Calcular f_Schroeder".
        self.lbl_npm_suggested = QLabel("npm sugerido: calculá f_Schroeder primero")
        self.lbl_npm_suggested.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        self.lbl_npm_suggested.setWordWrap(True)
        self.btn_apply_npm_suggested = QPushButton("Aplicar")
        self.btn_apply_npm_suggested.setMaximumWidth(90)
        self.btn_apply_npm_suggested.setEnabled(False)
        self.btn_apply_npm_suggested.setToolTip(
            "Carga el npm sugerido al spinbox de densidad.\n"
            "Calculado como npm = 6 · f_Schroeder / 343."
        )
        self.btn_apply_npm_suggested.clicked.connect(self._apply_suggested_npm)
        self._suggested_npm: Optional[float] = None
        _h_npm = QWidget()
        _h_npm_lay = QHBoxLayout(_h_npm); _h_npm_lay.setContentsMargins(0, 0, 0, 0)
        _h_npm_lay.addWidget(self.lbl_npm_suggested, 1)
        _h_npm_lay.addWidget(self.btn_apply_npm_suggested, 0)
        ff.addRow("", _h_npm)

        ff.addRow("h gmsh (m):", self.sb_htarget)

        # Combo de motor de mallado + badge de estado
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(["Automático", "Voxel (escalera)", "Gmsh (boundary-fitted)"])
        # Llave interna por indice -> "auto" / "voxel" / "gmsh"
        self._ENGINE_KEYS = {0: "auto", 1: "voxel", 2: "gmsh"}
        self._ENGINE_IDX  = {v: k for k, v in self._ENGINE_KEYS.items()}
        # Cargar default desde app_settings (override global)
        try:
            import app_settings
            default_engine = app_settings.get("default_mesh_engine", "auto")
        except Exception:
            default_engine = "auto"
        self.combo_engine.setCurrentIndex(self._ENGINE_IDX.get(default_engine, 0))
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        ff.addRow("Motor de mallado:", self.combo_engine)

        self.lbl_badge = QLabel("—")
        self.lbl_badge.setAlignment(Qt.AlignCenter)
        self.lbl_badge.setStyleSheet(
            "QLabel { padding: 4px 10px; border-radius: 6px; "
            "background:#313244; color:#cdd6f4; font-weight:600; }"
        )
        self.lbl_badge.setToolTip("Motor que se usará en el próximo cálculo")
        ff.addRow("Estado:", self.lbl_badge)

        # Botones de geometria importada.
        # Antes en HBoxLayout lado-a-lado; en pantallas angostas "Volver a
        # parametrica" se recortaba contra el borde derecho del panel. Los
        # dejamos en filas separadas para que cada uno use el ancho completo.
        self.btn_import_cad = QPushButton("📂  Importar CAD...")
        self.btn_import_cad.setToolTip(
            "Importar un archivo CAD (STL, OBJ, PLY, STEP, IGES, glTF...)\n"
            "como geometria del recinto. Reemplaza la geometria parametrica."
        )
        self.btn_import_cad.setMinimumWidth(0)
        self.btn_import_cad.clicked.connect(self.cadImportRequested.emit)
        ff.addRow(self.btn_import_cad)
        # Leyenda persistente "Ultimo: X.XX s" debajo de Importar CAD.
        # El timer en si lo controla MainWindow porque la importacion la
        # hace alla (acceso al QFileDialog + reparacion + render). Exponemos
        # el _TimedButtonForm para que MainWindow lo dispare.
        from timed_button import _TimedButtonForm
        self._cad_timer = _TimedButtonForm(self.btn_import_cad, ff)

        self.btn_clear_cad = QPushButton("✕  Volver a paramétrica")
        self.btn_clear_cad.setToolTip(
            "Descarta la geometria CAD importada y vuelve a usar "
            "la geometria parametrica del panel Geometria."
        )
        self.btn_clear_cad.setMinimumWidth(0)
        self.btn_clear_cad.clicked.connect(self.cadClearRequested.emit)
        self.btn_clear_cad.setEnabled(False)
        ff.addRow(self.btn_clear_cad)

        self.lbl_xi_info = QLabel("ξ se calcula desde materiales")
        self.lbl_xi_info.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        ff.addRow(self.lbl_xi_info)
        self.btn_solve_fem = QPushButton("Calcular modos (FEM)")
        self.btn_solve_fem.setObjectName("PrimaryButton")
        ff.addRow(self.btn_solve_fem)
        # Leyenda persistente "Ultimo: X.XX s" debajo del boton FEM
        from timed_button import _TimedButtonForm
        self._fem_timer = _TimedButtonForm(self.btn_solve_fem, ff)
        self.btn_solve_fem.clicked.connect(self._solve_fem)
        layout.addWidget(grp_fem)
        # Pintar el badge inicial segun la geometria actual
        self._refresh_badge_prediction()

        # --- Visualizacion de modo ---
        grp_mode = QGroupBox("Visualización modal")
        # Nota: el nombre `fmode` (en vez de `fm`) evita sombrear al import
        # `import face_materials as fm` del modulo, que se usa antes en
        # esta misma funcion para construir el FaceMaterialMap.
        fmode = QFormLayout(grp_mode)

        # Filtro por rango de frecuencia (no toca el calculo, solo el picker).
        # Permite ver, por ejemplo, los modos en banda 60-80 Hz de un set
        # mas grande sin necesidad de buscarlos a mano en el dropdown.
        self.sb_fmin = QDoubleSpinBox()
        self.sb_fmin.setRange(0.0, 100000.0); self.sb_fmin.setDecimals(1)
        self.sb_fmin.setSingleStep(1.0); self.sb_fmin.setSuffix(" Hz")
        self.sb_fmin.setValue(0.0)
        self.sb_fmin.setToolTip("Filtro de visualizacion: oculta del picker\n"
                                 "los modos cuya frecuencia este por debajo.\n"
                                 "No afecta al calculo ni a la FRF.")
        self.sb_fmax = QDoubleSpinBox()
        self.sb_fmax.setRange(0.0, 100000.0); self.sb_fmax.setDecimals(1)
        self.sb_fmax.setSingleStep(1.0); self.sb_fmax.setSuffix(" Hz")
        self.sb_fmax.setValue(100000.0)
        self.sb_fmax.setToolTip("Filtro de visualizacion: oculta del picker\n"
                                 "los modos cuya frecuencia este por encima.\n"
                                 "No afecta al calculo ni a la FRF.")
        self.sb_fmin.valueChanged.connect(self._on_mode_filter_changed)
        self.sb_fmax.valueChanged.connect(self._on_mode_filter_changed)
        fmode.addRow("f_min visible:", self.sb_fmin)
        fmode.addRow("f_max visible:", self.sb_fmax)

        self.combo_mode = QComboBox()
        self.combo_mode.currentIndexChanged.connect(self._update_slice)
        self.combo_mode.currentIndexChanged.connect(self._update_mode_readout)
        fmode.addRow("Modo:", self.combo_mode)

        # Leyenda con conteo total y filtrado (texto reactivo).
        self.lbl_modes_count = QLabel("— sin modos calculados —")
        self.lbl_modes_count.setStyleSheet("color: #94e2d5; font-size: 10pt;")
        self.lbl_modes_count.setWordWrap(True)
        fmode.addRow("", self.lbl_modes_count)

        # Read-out por modo (Capa 0, Etapa 5c): corrimiento Δfₙ + ξₙ del modo
        # seleccionado. Vacio hasta que haya modos; se puebla al elegir uno.
        self.lbl_mode_shift = QLabel("")
        self.lbl_mode_shift.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        self.lbl_mode_shift.setWordWrap(True)
        self.lbl_mode_shift.setToolTip(
            "f efectiva = frecuencia de resonancia que usa la FRF/campo/FoM,\n"
            "corrida por Im(β) de las construcciones (Capa 0). Δfₙ = 0 si no\n"
            "hay construcciones. ξₙ = amortiguamiento modal; RT60ₙ del modo\n"
            "aislado = 6.908/(ξₙ·2π·f).")
        fmode.addRow("", self.lbl_mode_shift)

        # Tabla por modo (Δfₙ, ξₙ, RT60ₙ) con export CSV/TXT/PNG.
        self.btn_mode_table = QPushButton("Ver modos (Δfₙ, ξₙ)…")
        self.btn_mode_table.setToolTip(
            "Tabla de TODOS los modos: frecuencia rígida vs efectiva,\n"
            "corrimiento Δfₙ (Capa 0), amortiguamiento ξₙ y RT60ₙ.")
        self.btn_mode_table.clicked.connect(self._show_mode_table)
        fmode.addRow("", self.btn_mode_table)

        # Selector de plano de corte
        self.combo_plane = QComboBox()
        self.combo_plane.addItems([
            "Plano XY  (z = cte)",
            "Plano XZ  (y = cte)",
            "Plano YZ  (x = cte)",
        ])
        self.combo_plane.currentIndexChanged.connect(self._on_plane_changed)
        fmode.addRow("Plano de corte:", self.combo_plane)

        # Botón de activación interactiva
        self.btn_activate_plane = QPushButton("⊕  Activar plano interactivo")
        self.btn_activate_plane.setCheckable(True)
        self.btn_activate_plane.setToolTip(
            "Activa el cursor de plano:\n"
            "• Mové el mouse sobre el recinto → el plano sigue al cursor\n"
            "• Click izquierdo → confirma la posición\n"
            "• Click derecho / ESC → cancela"
        )
        self.btn_activate_plane.toggled.connect(self._on_activate_plane_toggled)
        fmode.addRow(self.btn_activate_plane)

        # Offset del plano (etiqueta dinámica)
        self.lbl_slice_offset = QLabel("Posición  z:")
        self.sb_slice_z = QDoubleSpinBox()
        self.sb_slice_z.setRange(-1e2, 1e2)
        self.sb_slice_z.setDecimals(2)
        self.sb_slice_z.setValue(float(self.receiver[2]))
        self.sb_slice_z.setSingleStep(0.05)
        self.sb_slice_z.valueChanged.connect(self._update_slice)
        row_off = QHBoxLayout()
        row_off.addWidget(self.lbl_slice_offset)
        row_off.addWidget(self.sb_slice_z)
        fmode.addRow(row_off)

        self.sb_slice_res = QSpinBox(); self.sb_slice_res.setRange(20, 200); self.sb_slice_res.setValue(60)
        self.sb_slice_res.valueChanged.connect(self._update_slice)
        fmode.addRow("Resolución (px/eje):", self.sb_slice_res)

        self.combo_field = QComboBox()
        self.combo_field.addItems([
            "Forma modal (independiente de fuente)",
            "Presión |p| a frec. del modo  ← depende de fuente",
        ])
        self.combo_field.currentIndexChanged.connect(self._update_slice)
        fmode.addRow("Campo:", self.combo_field)

        self.chk_slice = QCheckBox("Mostrar slice")
        self.chk_slice.setChecked(True)
        self.chk_slice.toggled.connect(self._update_slice)
        fmode.addRow(self.chk_slice)

        btn_heatmap = QPushButton("Ver mapa de calor 2D")
        btn_heatmap.setObjectName("PrimaryButton")
        btn_heatmap.setToolTip("Abre una ventana matplotlib con el heatmap del\n"
                               "plano de corte actual (con barra de color en dB SPL).")
        btn_heatmap.clicked.connect(self._show_slice_heatmap)
        fmode.addRow(btn_heatmap)

        layout.addWidget(grp_mode)

        # --- FRF ---
        grp_frf = QGroupBox("FRF (Respuesta en frecuencia)")
        fg = QFormLayout(grp_frf)
        self.sb_frf_fmin = QDoubleSpinBox(); self.sb_frf_fmin.setRange(1.0, 1e4); self.sb_frf_fmin.setValue(20.0)
        self.sb_frf_fmax = QDoubleSpinBox(); self.sb_frf_fmax.setRange(1.0, 1e4); self.sb_frf_fmax.setValue(250.0)
        self.sb_frf_n = QSpinBox(); self.sb_frf_n.setRange(10, 1000); self.sb_frf_n.setValue(500)
        fg.addRow("f mín (Hz):", self.sb_frf_fmin)
        fg.addRow("f máx (Hz):", self.sb_frf_fmax)
        fg.addRow("Nº puntos:", self.sb_frf_n)
        self.btn_frf_fem = QPushButton("Calcular FRF")
        fg.addRow(self.btn_frf_fem)
        self.btn_frf_fem.clicked.connect(lambda: self._compute_frf("fem"))

        self.btn_sbir = QPushButton("Ver SBIR (fuente-frontera)")
        self.btn_sbir.setToolTip(
            "Speaker-Boundary Interference Response: el peine de interferencia "
            "entre el directo y las reflexiones de 1er orden en las superficies "
            "cercanas, en el punto de escucha (20–500 Hz). Analitico, "
            "complementario al FEM; usa el alpha de los materiales por cara."
        )
        fg.addRow(self.btn_sbir)
        self.btn_sbir.clicked.connect(self._open_sbir)

        self.btn_dba = QPushButton("Subs enfrentados (DBA / CABS)…")
        self.btn_dba.setToolTip(
            "Analiza subs enfrentados (DBA/CABS) sobre la caja rectangular de la "
            "sala: un array frontal lanza una onda plana y el trasero la absorbe. "
            "Compara CABS off vs on (planitud, varianza espacial, decay). "
            "Motor analítico rectangular exacto (independiente del FEM).")
        fg.addRow(self.btn_dba)
        self.btn_dba.clicked.connect(self._open_dba)
        layout.addWidget(grp_frf)

        # --- Estado / log ---
        self.status = QLabel("Listo.")
        self.status.setStyleSheet("color: #94a3b8;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # --- Campo acústico 3D (mapa de calor + flechas de gradiente) ---
        # (el bloque de f_Schroeder vivia aca hasta v2.15; se movio arriba,
        # entre Materiales y FEM)
        grp_3d = QGroupBox("Campo acústico 3D")
        f3d = QFormLayout(grp_3d)

        self.btn_field_3d = QPushButton("Actualizar campo 3D  (Enter)")
        self.btn_field_3d.setObjectName("PrimaryButton")
        self.btn_field_3d.clicked.connect(self._update_field_3d)
        f3d.addRow(self.btn_field_3d)

        self.sb_field3d_res = QSpinBox()
        self.sb_field3d_res.setRange(8, 80)
        self.sb_field3d_res.setValue(20)
        self.sb_field3d_res.setToolTip(
            "Puntos por eje para el campo 3D.\n"
            "20 → ~800-2000 pts (rápido)\n"
            "40 → ~6000-8000 pts (medio)\n"
            "60 → ~15000+ pts (lento, detallado)"
        )
        f3d.addRow("Resolución campo 3D:", self.sb_field3d_res)

        self.chk_grad = QCheckBox("Mostrar flechas de gradiente (blancas)")
        self.chk_grad.setChecked(False)
        self.chk_grad.toggled.connect(self._on_grad_toggled)
        f3d.addRow(self.chk_grad)

        btn_clear_3d = QPushButton("Limpiar campo 3D")
        btn_clear_3d.clicked.connect(self._clear_field_3d_and_update)
        f3d.addRow(btn_clear_3d)

        layout.addWidget(grp_3d)
        layout.addStretch(1)
        scroll.setWidget(container)

        # Todos los botones se expanden para ocupar el ancho completo
        for btn in self.findChildren(QPushButton):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _on_grad_toggled(self, checked):
        if not checked and hasattr(self, 'grad_arrows'):
            self.grad_arrows.clear()
            self.viewer.update()

    def _clear_field_3d_and_update(self):
        self._clear_field_3d()
        self.viewer.update()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _log(self, msg: str):
        self.status.setText(msg)

    def _selected_src_idx(self) -> int:
        items = self.list_src.selectedItems()
        if not items:
            return -1
        return self.list_src.row(items[0])

    def _src_item_text(self, i, s) -> str:
        absQ = abs(s.Q)
        ph = math.degrees(np.angle(s.Q))
        active = bool(getattr(s, "active", True))
        # El ∠ sale de s.Q CRUDO, que no lleva la polaridad (vive en
        # effective_Q). Sin este tag, una fuente invertida se veria igual que
        # una normal en la lista — el mismo problema de readback que motivo
        # sacar la polaridad de la curva.
        inv = int(getattr(s, "polarity", 1) or 1) < 0
        return (f"[{i}] {s.label}  @ ({s.position[0]:.2f}, "
                f"{s.position[1]:.2f}, {s.position[2]:.2f})   "
                f"|Q|={absQ:.3g}  ∠={ph:+.1f}°"
                + ("   [180°]" if inv else "")
                + ("" if active else "   [MUTE]"))

    def _refresh_sources_list(self):
        sel = self._selected_src_idx()
        self.list_src.blockSignals(True)
        self.list_src.clear()
        for i, s in enumerate(self.sources):
            active = bool(getattr(s, "active", True))
            item = QListWidgetItem(self._src_item_text(i, s))
            # Checkbox = fuente activa (mute v2.16). Desmarcada -> no radia:
            # FRF/SBIR/FoM/campo 3D/Comparar la excluyen sin borrarla.
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if active else Qt.Unchecked)
            if not active:
                item.setForeground(QColor("#6c7086"))
            self.list_src.addItem(item)
        self.list_src.blockSignals(False)
        if 0 <= sel < self.list_src.count():
            self.list_src.setCurrentRow(sel)
        self.src_markers.update(self.sources, selected_idx=sel)
        # Sincronizar posiciones al viewer para que el picking de Shift+drag
        # (`_pick_source`) y doble-click vean la lista actualizada. Es el
        # cuello de botella historico de "no me toma la fuente" despues de
        # cargar un .room, importar CAD, o eliminar/duplicar/editar una fuente.
        self._sync_source_positions_to_viewer()
        self.viewer.update()

    # -----------------------------------------------------------------------
    # Fuentes
    # -----------------------------------------------------------------------
    def _on_src_selection(self):
        self.src_markers.update(self.sources, selected_idx=self._selected_src_idx())
        self.viewer.update()

    def _on_src_check_changed(self, item):
        """Checkbox de la lista: activa/silencia la fuente correspondiente.

        OJO: NO reconstruir la lista aca (clear() destruiria el item que Qt
        esta procesando en este mismo click -> el mouse-grab queda colgado en
        un widget muerto y toda la app deja de recibir clicks/drags bien).
        Se actualiza el item IN PLACE con señales bloqueadas.
        """
        i = self.list_src.row(item)
        if not (0 <= i < len(self.sources)):
            return
        s = self.sources[i]
        s.active = (item.checkState() == Qt.Checked)
        self.list_src.blockSignals(True)
        item.setText(self._src_item_text(i, s))
        item.setForeground(QColor("#6c7086") if not s.active
                           else self.list_src.palette().text().color())
        self.list_src.blockSignals(False)
        self._log(f"Fuente '{s.label}' "
                  f"{'activada' if s.active else 'silenciada'}.")

    def _active_sources(self):
        """SourceArray con solo las fuentes activas (mute v2.16). Los caminos
        de computo usan esto en lugar de self.sources."""
        return self.sources.active_only()

    def _get_baffle_walls(self):
        """Lista de (centroide, normal) de las paredes actuales, para el
        'Pegar a pared' del editor de fuente. Reusa los face groups; [] si falla."""
        try:
            groups, _v, _t = self._get_face_groups()
            return [(g.centroid, g.normal) for g in groups]
        except Exception:
            return []

    def _add_source(self):
        dlg = SourceEditDialog(dims_hint=self.get_dims_hint(), parent=self,
                               get_walls=self._get_baffle_walls)
        if dlg.exec_() == QDialog.Accepted:
            src = dlg.get_source()
            self.sources.add(src)
            self._refresh_sources_list()
            self._log(f"Fuente '{src.label}' añadida.")

    def _edit_source(self):
        i = self._selected_src_idx()
        if i < 0:
            return
        dlg = SourceEditDialog(self.sources[i], dims_hint=self.get_dims_hint(),
                               parent=self, get_walls=self._get_baffle_walls)
        if dlg.exec_() == QDialog.Accepted:
            self.sources.sources[i] = dlg.get_source()
            self._refresh_sources_list()
            # El campo |p| depende de la fuente (posición, Q(f), POLARIDAD): al
            # editar hay que recomputarlo, igual que al moverla. Sin esto, el
            # campo mostrado quedaba viejo tras invertir polaridad/cambiar TRF.
            self.schedule_field_update()
            self._log(f"Fuente {i} editada.")

    def _remove_source(self):
        i = self._selected_src_idx()
        if i < 0:
            return
        del self.sources.sources[i]
        self._refresh_sources_list()
        self.schedule_field_update()      # el campo |p| cambió (una fuente menos)
        self._log(f"Fuente {i} eliminada.")

    def _duplicate_source(self):
        i = self._selected_src_idx()
        if i < 0:
            return
        s = self.sources[i]
        # La copia tiene que salir IGUAL al original. Se copian todos los campos
        # a mano (no hay `replace` porque `response` se adjunta aparte); antes se
        # perdian bafle/pitch/mounted/active al duplicar — mismo tipo de bug que
        # el del drag arreglado en v2.13.
        new = OmniSource(position=s.position, Q=s.Q,
                          label=f"{s.label}_dup",
                          sensitivity_dB=s.sensitivity_dB,
                          power_W=s.power_W, f_ref=s.f_ref,
                          orientation=getattr(s, "orientation", None),
                          baffle_size=getattr(s, "baffle_size", (0.30, 0.50, 0.40)),
                          pitch=getattr(s, "pitch", 0.0),
                          mounted=getattr(s, "mounted", False),
                          active=getattr(s, "active", True),
                          polarity=getattr(s, "polarity", 1),
                          delay_s=getattr(s, "delay_s", 0.0),      # v2.25
                          phase_deg=getattr(s, "phase_deg", 0.0),
                          filter_type=getattr(s, "filter_type", "none"),  # v2.29
                          filter_order=getattr(s, "filter_order", 4),
                          filter_fc=getattr(s, "filter_fc", 100.0),
                          filter_kind=getattr(s, "filter_kind", "lowpass"),
                          filter_ripple_db=getattr(s, "filter_ripple_db", 1.0),
                          filter_atten_db=getattr(s, "filter_atten_db", 40.0))
        new.response = s.response       # Fase 2: la copia conserva la curva Q(f)
        self.sources.add(new)
        self._refresh_sources_list()
        self.schedule_field_update()      # el campo |p| cambió (una fuente más)
        self._log("Fuente duplicada.")

    # -----------------------------------------------------------------------
    # Muebles (carve rígido + absorción A36 + SBIR; ver acoustic_analysis y
    # _compute_xi_from_materials / _open_sbir, ya cableados)
    # -----------------------------------------------------------------------
    def _selected_furn_idx(self) -> int:
        return self.list_furn.currentRow()

    def _furn_item_text(self, i, m) -> str:
        kind = getattr(m, "kind", "box")
        mat = self._furniture_mat_names.get(i)
        if kind in ("compound", "mesh"):
            lo, hi = m.aabb(); d = hi - lo
            tag = "CAD" if kind == "mesh" else "preset"
            return (f"{m.label}  [{tag} {d[0]:.2f}×{d[1]:.2f}×{d[2]:.2f} m "
                    f"· {mat or 'rígido'}]")
        cyl = kind == "cylinder"
        sx, sy, sz = m.size
        dims = f"Ø{sx:.2f}×{sz:.2f}" if cyl else f"{sx:.2f}×{sy:.2f}×{sz:.2f}"
        return f"{m.label}  [{'cilindro' if cyl else 'caja'} {dims} m · {mat or 'rígido'}]"

    def _show_preset_menu(self):
        """Menú desplegable con los presets de muebles, agrupados (General / Aula /
        Estudio)."""
        import furniture as fu
        menu = QMenu(self)
        groups = getattr(fu, "FURNITURE_PRESET_GROUPS", None)
        if groups:
            for cat, names in groups.items():
                sub = menu.addMenu(cat)
                for name in names:
                    sub.addAction(name,
                                  lambda _c=False, n=name: self._insert_preset(n))
        else:
            for name in fu.FURNITURE_PRESETS:
                menu.addAction(name,
                               lambda _c=False, n=name: self._insert_preset(n))
        menu.exec_(self.btn_preset_furn.mapToGlobal(
            self.btn_preset_furn.rect().bottomLeft()))

    def _insert_preset(self, name: str):
        """Inserta un preset (compound) en el centro de la sala, apoyado en el
        piso, con su material sugerido. Respeta las colisiones (no lo agrega si
        el centro está ocupado)."""
        import furniture as fu
        furn, mat = fu.make_preset(name)
        placement = fu.preset_placement(name)
        try:
            lo_r, hi_r = self._room_bbox()
            cx = float((lo_r[0] + hi_r[0]) / 2.0)
            cy = float((lo_r[1] + hi_r[1]) / 2.0)
            floor, ceil = float(lo_r[2]), float(hi_r[2])
        except Exception:
            cx, cy, floor, ceil = 0.0, 0.0, 0.0, 3.0
        lo, hi = furn.aabb()                        # con position (0,0,0)
        if placement == "ceiling":
            z = ceil - float(hi[2]) - 0.10          # suspendido, ~10 cm bajo el techo
        else:
            z = floor - float(lo[2])                # apoyado en el piso
        furn.position = (cx, cy, z)
        conflict = self._furniture_conflict(furn)
        if conflict:
            QMessageBox.warning(
                self, "No se puede colocar",
                f"El preset «{furn.label}» {conflict}. Hacé lugar en el centro "
                f"o mové lo que estorba, y volvé a insertarlo.")
            return
        self.furniture.append(furn)
        if mat:
            self._furniture_mat_names[len(self.furniture) - 1] = mat
        self.list_furn.setCurrentRow(len(self.furniture) - 1)
        self._refresh_furniture_list()
        self._log(f"Preset «{furn.label}» insertado"
                  f"{f' (material {mat})' if mat else ' (rígido)'}. "
                  f"Movelo/rotalo y recalculá los modos para aplicarlo.")

    def _refresh_furniture_list(self):
        """Repuebla la lista de muebles y refresca el wireframe 3D."""
        sel = self._selected_furn_idx()
        self.list_furn.blockSignals(True)
        self.list_furn.clear()
        for i, m in enumerate(self.furniture):
            self.list_furn.addItem(QListWidgetItem(self._furn_item_text(i, m)))
        self.list_furn.blockSignals(False)
        if 0 <= sel < self.list_furn.count():
            self.list_furn.setCurrentRow(sel)
        self.furn_markers.update(self.furniture,
                                 selected_idx=self._selected_furn_idx())
        self._sync_furniture_positions_to_viewer()
        # Un mueble nuevo/movido puede tapar un parche -> revisar el aviso.
        if self._patches:
            self._refresh_patches_summary()
        self.viewer.update()

    def _on_furn_selection(self):
        self.furn_markers.update(self.furniture,
                                 selected_idx=self._selected_furn_idx())
        self.viewer.update()

    def _sync_furniture_positions_to_viewer(self):
        """Pasa los centros y los bounding boxes de los muebles al viewer para el
        picking (drag / doble-click). El bbox permite agarrar el mueble clickeando
        en cualquier parte de su silueta, no solo cerca del centro (clave para los
        muebles grandes)."""
        if hasattr(self.viewer, "set_furniture_positions"):
            self.viewer.set_furniture_positions(
                [tuple(m.position) for m in self.furniture])
        if hasattr(self.viewer, "set_furniture_bboxes"):
            self.viewer.set_furniture_bboxes(
                [m.aabb() for m in self.furniture])
        # Ejes locales para el gizmo de rotación: MISMA fuente de verdad que
        # contains/aabb/wireframe (`Furniture._local_axes`), así el anillo que
        # ves es el eje que realmente se va a mover.
        if hasattr(self.viewer, "set_furniture_axes"):
            self.viewer.set_furniture_axes(
                [m._local_axes() for m in self.furniture])

    @staticmethod
    def _furniture_aabb(m):
        """AABB (min, max) en coords mundo. Delega en Furniture.aabb(), que maneja
        caja/cilindro/compound con yaw+pitch (dibujo == carve == colisión)."""
        return m.aabb()

    @staticmethod
    def _source_baffle_aabb(s):
        """AABB del bafle (caja visual) de una fuente, con su yaw+pitch. Mismo
        frame que acoustic_viewer._baffle_wireframe (n=frente, ey=ancho, ez=n×ey)."""
        pos = np.array([float(v) for v in s.position])
        bsz = getattr(s, "baffle_size", None) or (0.30, 0.50, 0.40)
        w, h, d = [float(v) for v in bsz]
        yaw = getattr(s, "orientation", None)
        th = np.radians(90.0 if yaw is None else float(yaw))
        ph = np.radians(float(getattr(s, "pitch", 0.0) or 0.0))
        n = np.array([np.cos(ph) * np.cos(th), np.cos(ph) * np.sin(th), np.sin(ph)])
        ey = np.array([-np.sin(th), np.cos(th), 0.0])
        ez = np.cross(n, ey)
        hx, hy, hz = d / 2.0, w / 2.0, h / 2.0
        corners = np.array([pos + a * hx * n + b * hy * ey + e * hz * ez
                            for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)])
        return corners.min(axis=0), corners.max(axis=0)

    def _room_bbox(self):
        """(min, max) del bounding box del recinto actual (surface real)."""
        verts, _tris = self.get_surface()
        v = np.asarray(verts, dtype=float)
        return v.min(axis=0), v.max(axis=0)

    def _clamp_to_room_bbox(self, x, y, z, eps=1e-3):
        """Recorta (x,y,z) al bounding box del recinto (con un pequeño inset para
        quedar estrictamente adentro de la malla). 'Traba' el arrastre de fuentes
        y receptor en los límites: si el cursor sale, el objeto desliza pegado a
        la pared en vez de irse afuera. Sin geometría -> devuelve el punto igual."""
        try:
            lo, hi = self._room_bbox()
        except Exception:
            return (float(x), float(y), float(z))
        out = []
        for v, l, h in zip((x, y, z), lo, hi):
            l2, h2 = float(l) + eps, float(h) - eps
            out.append(float(v) if h2 < l2 else min(max(float(v), l2), h2))
        return tuple(out)

    def point_inside_furniture(self, x, y, z) -> int:
        """Indice del mueble que CONTIENE el punto, o -1. Usa el mismo
        `Furniture.contains` que el tallado, así que responde exactamente por
        el aire que el FEM removió.

        CRÍTICO: si la fuente o el receptor caen adentro de un mueble tallado,
        ahí NO hay malla y `FieldEvaluator` devuelve **NaN**, que se propaga a
        toda la FRF sin lanzar ningún error. Por eso el movimiento se bloquea."""
        import numpy as _np
        p = _np.array([[float(x), float(y), float(z)]])
        for i, m in enumerate(getattr(self, "furniture", []) or []):
            try:
                if bool(m.contains(p)[0]):
                    return i
            except Exception:
                continue
        return -1

    def source_placement_conflict(self, idx: int, x, y, z):
        """Mensaje si la fuente `idx` no puede ir a (x,y,z), o None si está OK.

        Dos reglas, de distinta naturaleza:
          1. el PUNTO (el monopolo) no puede quedar dentro de un mueble -> NaN;
          2. el BAFLE (la caja del parlante) no puede atravesar un mueble, que
             es la contraparte de la regla que ya aplican los muebles contra los
             parlantes (MANUAL §6.4). Sin esto la regla valía en un solo sentido.
        """
        i = self.point_inside_furniture(x, y, z)
        if i >= 0:
            m = self.furniture[i]
            return (f"quedaría DENTRO del mueble «{m.label}» (ahí no hay aire: "
                    f"la respuesta daría NaN)")
        if not (0 <= idx < len(self.sources)):
            return None
        try:
            import copy as _copy
            s = _copy.copy(self.sources[idx])
            s.position = (float(x), float(y), float(z))
            amin, amax = self._source_baffle_aabb(s)
            for m in getattr(self, "furniture", []) or []:
                bmin, bmax = self._furniture_aabb(m)
                if self._aabb_overlap(amin, amax, bmin, bmax):
                    return f"el bafle se superpondría con el mueble «{m.label}»"
        except Exception:
            pass
        return None

    @staticmethod
    def _aabb_overlap(amin, amax, bmin, bmax, tol=1e-4):
        return bool(np.all(amin < bmax - tol) and np.all(bmin < amax - tol))

    def _furniture_conflict(self, cand, ignore_idx: int = -1):
        """Mensaje si `cand` NO puede colocarse, o None si está OK. Chequea, por
        AABB: (1) solape con otro mueble, (2) solape con un parlante (bafle),
        (3) que no se salga de paredes/techo del recinto. Conservador para cajas
        rotadas/inclinadas (seguro para 'los objetos sólidos no se atraviesan').
        El PISO no atrapa: los muebles se apoyan ahí y al inclinarse un borde baja
        de z=0, lo cual es inofensivo para el carve (no hay tets bajo el piso)."""
        amin, amax = self._furniture_aabb(cand)
        for i, m in enumerate(self.furniture):
            if i == ignore_idx:
                continue
            bmin, bmax = self._furniture_aabb(m)
            if self._aabb_overlap(amin, amax, bmin, bmax):
                return f"se solaparía con el mueble «{m.label}»"
        try:
            for s in self.sources:
                bmin, bmax = self._source_baffle_aabb(s)
                if self._aabb_overlap(amin, amax, bmin, bmax):
                    return f"se solaparía con el parlante «{getattr(s, 'label', 'fuente')}»"
        except Exception:
            pass
        # El RECEPTOR es un punto pelado (no tiene bafle que lo proteja): si un
        # mueble lo envuelve queda sin aire alrededor y el campo evalua NaN.
        try:
            import numpy as _np
            if bool(cand.contains(_np.array([list(self.receiver)], dtype=float))[0]):
                return "dejaría al receptor adentro (ahí no hay aire: daría NaN)"
        except Exception:
            pass
        try:
            lo, hi = self._room_bbox()
            amin_c = amin.copy()
            amin_c[2] = max(float(amin_c[2]), float(lo[2]))   # el piso no atrapa
            if np.any(amin_c < lo - 1e-4) or np.any(amax > hi + 1e-4):
                return "se saldría de los límites del recinto"
        except Exception:
            pass
        return None

    def _room_center_default(self):
        """Posición por defecto de un mueble nuevo: centro de planta de la sala
        real (bbox del surface) apoyado en el piso. Robusto a origin_mode
        (auto/centro/esquina) — NO asume esquina en (0,0)."""
        try:
            verts, _tris = self.get_surface()
            v = np.asarray(verts, dtype=float)
            lo, hi = v.min(axis=0), v.max(axis=0)
            return (float((lo[0] + hi[0]) / 2.0),
                    float((lo[1] + hi[1]) / 2.0),
                    float(lo[2] + 0.45))
        except Exception:
            return None

    def _add_furniture(self):
        dlg = FurnitureEditDialog(mat_names=self._mat_lib.names,
                                  dims_hint=self.get_dims_hint(),
                                  default_pos=self._room_center_default(),
                                  parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        furn, mat = dlg.get_furniture()
        msg = self._furniture_conflict(furn)
        if msg:
            QMessageBox.warning(
                self, "No se puede colocar",
                f"El mueble «{furn.label}» {msg}. Ajustá posición o tamaño.")
            return
        self.furniture.append(furn)
        if mat:
            self._furniture_mat_names[len(self.furniture) - 1] = mat
        self.list_furn.setCurrentRow(len(self.furniture) - 1)
        self._refresh_furniture_list()
        self._log(f"Mueble '{furn.label}' añadido"
                  f"{f' (material {mat})' if mat else ' (rígido)'}. "
                  f"Recalculá los modos para aplicarlo.")

    def _edit_furniture(self):
        self._edit_furniture_by_idx(self._selected_furn_idx())

    def _edit_furniture_by_idx(self, i: int):
        """Abre el editor del mueble `i` (usado por el botón Editar y por el
        doble-click en el visor)."""
        if not (0 <= i < len(self.furniture)):
            return
        dlg = FurnitureEditDialog(self.furniture[i],
                                  mat_name=self._furniture_mat_names.get(i),
                                  mat_names=self._mat_lib.names,
                                  dims_hint=self.get_dims_hint(), parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        furn, mat = dlg.get_furniture()
        msg = self._furniture_conflict(furn, ignore_idx=i)
        if msg:
            QMessageBox.warning(
                self, "No se puede colocar",
                f"Ese cambio haría que «{furn.label}» {msg}. Ajustá posición o tamaño.")
            return
        self.furniture[i] = furn
        if mat:
            self._furniture_mat_names[i] = mat
        else:
            self._furniture_mat_names.pop(i, None)
        self.list_furn.setCurrentRow(i)
        self._refresh_furniture_list()
        self._log(f"Mueble {i} editado. Recalculá los modos para aplicarlo.")

    def apply_furniture_move(self, idx: int, x: float, y: float, z: float):
        """Mueve un mueble por drag (Shift). Colisión-stop: frena al contacto si
        el movimiento CREARÍA un solape nuevo. Si el mueble YA estaba solapado
        (p.ej. una copia recién duplicada encima), NO se bloquea -> se puede
        arrastrar para afuera (si no, quedaría trabado sin salida). Actualiza el
        wireframe IN-PLACE (sin reconstruir la lista -> sin cuelgue por frame)."""
        if not (0 <= idx < len(self.furniture)):
            return
        m = self.furniture[idx]
        was_conflicting = self._furniture_conflict(m, ignore_idx=idx) is not None
        old = m.position
        m.position = (float(x), float(y), float(z))
        if not was_conflicting and self._furniture_conflict(m, ignore_idx=idx):
            m.position = old   # frena: no atraviesa materia ni sale del recinto
            return
        self.furn_markers.set_positions(self.furniture, selected_idx=idx)
        self._sync_furniture_positions_to_viewer()
        self.viewer.update()

    def apply_furniture_rotate(self, idx: int, d_yaw: float):
        """Rota (yaw) un mueble por gesto Alt+Ctrl. Solo cajas (el cilindro es
        invariante). Colisión-stop con escape igual que el move."""
        if not (0 <= idx < len(self.furniture)):
            return
        m = self.furniture[idx]
        if getattr(m, "kind", "box") == "cylinder":
            return
        was_conflicting = self._furniture_conflict(m, ignore_idx=idx) is not None
        old = float(getattr(m, "orientation", 0.0) or 0.0)
        m.orientation = float((old + d_yaw) % 360.0)
        if not was_conflicting and self._furniture_conflict(m, ignore_idx=idx):
            m.orientation = old
            return
        self.furn_markers.set_positions(self.furniture, selected_idx=idx)
        self.viewer.update()

    def apply_furniture_tilt(self, idx: int, d_pitch: float):
        """Inclina (pitch) un mueble por gesto Alt+Ctrl (vertical). Solo cajas;
        clamp -90..90. El pitch afecta el carve. Colisión-stop con escape igual
        que rotate."""
        if not (0 <= idx < len(self.furniture)):
            return
        m = self.furniture[idx]
        if getattr(m, "kind", "box") == "cylinder":
            return
        was_conflicting = self._furniture_conflict(m, ignore_idx=idx) is not None
        old = float(getattr(m, "pitch", 0.0) or 0.0)
        m.pitch = float(max(-90.0, min(90.0, old + d_pitch)))
        if not was_conflicting and self._furniture_conflict(m, ignore_idx=idx):
            m.pitch = old
            return
        self.furn_markers.set_positions(self.furniture, selected_idx=idx)
        self.viewer.update()

    def apply_furniture_roll(self, idx: int, d_roll: float):
        """Vuelca (roll) un mueble por el anillo del gizmo. Solo cajas/compound/
        mesh; el cilindro es invariante. Colisión-stop con escape igual que los
        otros dos ejes. El roll afecta el carve (no es cosmético)."""
        if not (0 <= idx < len(self.furniture)):
            return
        m = self.furniture[idx]
        if getattr(m, "kind", "box") == "cylinder":
            return
        was_conflicting = self._furniture_conflict(m, ignore_idx=idx) is not None
        old = float(getattr(m, "roll", 0.0) or 0.0)
        m.roll = float((old + d_roll) % 360.0)
        if not was_conflicting and self._furniture_conflict(m, ignore_idx=idx):
            m.roll = old
            return
        self.furn_markers.set_positions(self.furniture, selected_idx=idx)
        self._sync_furniture_positions_to_viewer()
        self.viewer.update()

    def _remove_furniture(self):
        i = self._selected_furn_idx()
        if not (0 <= i < len(self.furniture)):
            return
        del self.furniture[i]
        # Reindexar el dict de materiales: quitar i y correr los índices > i.
        self._furniture_mat_names = {
            (k - 1 if k > i else k): v
            for k, v in self._furniture_mat_names.items() if k != i}
        self._refresh_furniture_list()
        self._log(f"Mueble {i} eliminado.")

    def _duplicate_furniture(self):
        i = self._selected_furn_idx()
        if not (0 <= i < len(self.furniture)):
            return
        from furniture import Furniture
        m = Furniture.from_dict(self.furniture[i].to_dict())
        m.label = f"{m.label}_dup"
        # Desplazar la copia para que NO caiga exactamente encima del original
        # (si no, ambos se solapan al 100% y la colisión-stop los traba). Se
        # corre por su propio ancho + un gap en +X; si eso saldría del recinto,
        # se corre en -X. La lógica de escape cubre cualquier solape residual.
        lo, hi = self._furniture_aabb(m)
        w = float(hi[0] - lo[0]) + 0.15
        px, py, pz = m.position
        nx = px + w
        try:
            rlo, rhi = self._room_bbox()
            if hi[0] + w > rhi[0] - 1e-3:
                nx = px - w
                if lo[0] - w < rlo[0] + 1e-3:      # tampoco entra en -X: cede algo
                    nx = px + 0.3
        except Exception:
            pass
        m.position = (nx, py, pz)
        self.furniture.append(m)
        mat = self._furniture_mat_names.get(i)
        if mat:
            self._furniture_mat_names[len(self.furniture) - 1] = mat
        self._refresh_furniture_list()
        self._log("Mueble duplicado.")

    # -----------------------------------------------------------------------
    # Receptor
    # -----------------------------------------------------------------------
    def _on_receiver_changed(self):
        self.receiver = (self.sb_rx.value(), self.sb_ry.value(), self.sb_rz.value())
        self._refresh_receiver_marker()

    def _refresh_receiver_marker(self):
        self.rcv_marker.update(self.receiver)
        if hasattr(self.viewer, 'set_receiver_position'):
            self.viewer.set_receiver_position(self.receiver)
        self.viewer.update()

    def move_receiver_to(self, x: float, y: float, z: float):
        """Mover receptor desde el viewer 3D via Shift+drag."""
        for sb, val in ((self.sb_rx, x), (self.sb_ry, y), (self.sb_rz, z)):
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)
        self.receiver = (x, y, z)
        self._refresh_receiver_marker()

    # ------------------------- Puntos de escucha (v2.16) -------------------
    def _refresh_listen_points(self):
        self.list_pts.blockSignals(True)
        self.list_pts.clear()
        for p in self.listen_points:
            x, y, z = p["position"]
            self.list_pts.addItem(f"{p['name']}   ({x:.2f}, {y:.2f}, {z:.2f}) m")
        self.list_pts.blockSignals(False)
        if hasattr(self.viewer, "set_listen_points"):
            try:
                self.viewer.set_listen_points(
                    [p["position"] for p in self.listen_points])
            except Exception:
                pass

    def _add_listen_point(self):
        name = ("Sweet Spot" if not self.listen_points
                else f"Mic {len(self.listen_points) + 1}")
        pos = tuple(float(v) for v in self.receiver)
        self.listen_points.append({"name": name, "position": pos})
        self._refresh_listen_points()
        self._log(f"Punto de escucha '{name}' agregado en "
                  f"({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}).")

    def _rename_listen_point(self):
        i = self.list_pts.currentRow()
        if not (0 <= i < len(self.listen_points)):
            return
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Renombrar punto", "Nombre:",
            text=self.listen_points[i]["name"])
        if ok and name.strip():
            self.listen_points[i]["name"] = name.strip()
            self._refresh_listen_points()

    def _remove_listen_point(self):
        i = self.list_pts.currentRow()
        if 0 <= i < len(self.listen_points):
            gone = self.listen_points.pop(i)
            self._refresh_listen_points()
            self._log(f"Punto '{gone['name']}' quitado.")

    def _goto_listen_point(self, item):
        i = self.list_pts.row(item)
        if 0 <= i < len(self.listen_points):
            x, y, z = self.listen_points[i]["position"]
            self.move_receiver_to(float(x), float(y), float(z))

    # ------------------------- Comparar (v2.16) ----------------------------
    def _ensure_modes_computed(self) -> bool:
        """Garantiza modal_result (calcula si hace falta). False si fallo."""
        if self.modal_result is not None:
            return True
        try:
            verts, tris = self.get_surface()
        except Exception as e:
            QMessageBox.critical(self, "Sin geometría", str(e))
            return False
        try:
            self.setEnabled(False)
            self._log("Comparar requiere modos. Calculando FEM...")
            self.modal_result = aa.run_fem_modal(
                verts, tris, n_modes=self.sb_nmodes.value(),
                n_per_meter=self.sb_density.value(), progress=self._log)
            self._clip_modes_to_mesh_validity()
            self._refresh_modes_combo()
            self._xi_per_mode = self._compute_xi_from_materials()
        except Exception as e:
            QMessageBox.critical(self, "Error FEM", str(e))
            return False
        finally:
            self.setEnabled(True)
        return True

    def _compute_compare_data(self, want_fom, want_frf, want_sbir):
        """Computa todo lo que el CompareDialog necesita, o None si falta algo."""
        import modal_metrics as mm
        act = self._active_sources()
        pts = self.listen_points
        names = [p["name"] for p in pts]
        poss = np.array([p["position"] for p in pts], dtype=float)
        damping = (self._xi_per_mode if self._xi_per_mode is not None else 0.03)
        data = {"names": names,
                "positions": [tuple(p) for p in poss],
                "src_labels": [s.label or f"S{i+1}"
                               for i, s in enumerate(act)]}

        if want_fom or want_frf:
            if not self._ensure_modes_computed():
                return None
            damping = (self._xi_per_mode if self._xi_per_mode is not None
                       else 0.03)
            mrl = self.modal_result

        if want_frf:
            self._log(f"Comparar: FRF en {len(pts)} puntos...")
            spl = []
            fa = None
            for pos in poss:
                r = aa.run_fem_frf(mrl, act, tuple(pos),
                                   f_min=self.sb_frf_fmin.value(),
                                   f_max=self.sb_frf_fmax.value(),
                                   n_freqs=self.sb_frf_n.value(),
                                   damping=damping)
                fa = r.freq_axis
                spl.append(20.0 * np.log10(
                    np.maximum(np.abs(r.H), 1e-12) / 20e-6))
            data["frf"] = {"freq": np.asarray(fa), "spl": spl}

        if want_fom:
            # Respuesta forzada en LAS POSICIONES DEL USUARIO (a diferencia
            # del FoM del dialogo FRF, que usa una grilla interna): la tabla
            # compara exactamente los puntos de escucha definidos.
            h_max = mrl.mesh_info.get("h_max", 0.0)
            f_hi = self._validity_freq(h_max) if h_max > 0 else 200.0
            fa_v = np.linspace(20.0, max(40.0, f_hi), 240)
            self._log(f"Comparar: FoM en banda 20–{fa_v[-1]:.0f} Hz "
                      f"({len(pts)} posiciones)...")
            H, _env = mm.forced_response_with_envelope(
                mrl.locator, mrl.freqs, mrl.phis, act, poss, fa_v,
                damping=damping)
            fom_set = mm.response_figures_of_merit(H, fa_v)
            # Curvas suavizadas por posicion (misma cocina que el FoM del set)
            S_hat = mm._smooth_energy_db(np.abs(H) ** 2, fa_v, 3, 20e-6)
            planitud = [float(np.std(S_hat[i])) for i in range(len(pts))]
            desvio = [float(np.sqrt(np.mean(
                (S_hat[i] - fom_set.L_mean_smooth) ** 2)))
                for i in range(len(pts))]
            data["fom"] = {"planitud": planitud, "desvio": desvio,
                           "VSA": fom_set.FoM_flat,
                           "MSV": fom_set.FoM_espacial,
                           "band": (float(fa_v[0]), float(fa_v[-1]))}

        if want_sbir:
            import sbir
            try:
                groups, _sv, _st = self._get_face_groups()
            except Exception as e:
                QMessageBox.critical(self, "Sin geometría", str(e))
                return None
            if not groups:
                QMessageBox.information(self, "Sin superficies",
                                        "No hay caras para reflejar.")
                return None
            freq = np.linspace(20.0, 500.0, 2000)
            g2m = self._group_to_material_dict(groups)
            walls = []
            for g in groups:
                mat = g2m.get(g.signature)
                alpha = (np.array([mat.alpha(float(ff)) for ff in freq])
                         if mat is not None else np.full(freq.shape, 0.03))
                walls.append(sbir.Wall(point=g.centroid, normal=g.normal,
                                       label=g.label,
                                       R=sbir.reflection_from_alpha(alpha)))
            self._log(f"Comparar: SBIR en {len(pts)} puntos...")
            curves = [sbir.sbir_from_sources(act, walls, tuple(pos), freq)
                      .total_sbir_db for pos in poss]
            data["sbir"] = {"freq": freq, "curves": curves}
        return data

    def _open_compare_dialog(self):
        """Boton «Comparar…»: elegir vista y abrir el CompareDialog."""
        act = self._active_sources()
        if len(act) == 0:
            QMessageBox.information(
                self, "Falta excitación",
                "Agregá (o activá) al menos una fuente. Para analizar un "
                "parlante solo, silenciá los demás con el checkbox.")
            return
        if len(self.listen_points) < 1:
            QMessageBox.information(
                self, "Sin puntos de escucha",
                "Agregá al menos un punto: posicioná el receptor y apretá "
                "«Agregar» en el grupo Receptor. Para las métricas de "
                "conjunto (VSA/MSV) se necesitan ≥ 2.")
            return
        # Eleccion de vista
        from PyQt5.QtWidgets import QRadioButton, QButtonGroup
        dlg = QDialog(self)
        apply_dialog_theme(dlg)  # tema claro (fondo blanco)
        dlg.setWindowTitle("Comparar — elegir vista")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            f"Comparar {len(self.listen_points)} puntos de escucha con "
            f"{len(act)} fuente(s) activa(s):"))
        grp = QButtonGroup(dlg)
        rbs = {}
        for key, txt in (("fom", "Figuras de mérito (tabla MSV/VSA)"),
                         ("frf", "Respuestas en frecuencia"),
                         ("sbir", "SBIR"),
                         ("all", "Todas")):
            rb = QRadioButton(txt)
            grp.addButton(rb)
            v.addWidget(rb)
            rbs[key] = rb
        rbs.get(getattr(self, "_compare_choice", "all"), rbs["all"]).setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            return
        choice = next(k for k, rb in rbs.items() if rb.isChecked())
        self._compare_choice = choice
        want_fom = choice in ("fom", "all")
        want_frf = choice in ("frf", "all")
        want_sbir = choice in ("sbir", "all")
        try:
            self.setEnabled(False)
            data = self._compute_compare_data(want_fom, want_frf, want_sbir)
        except Exception as e:
            QMessageBox.critical(self, "Error en la comparación", str(e))
            return
        finally:
            self.setEnabled(True)
        if data is None:
            return
        self._log("Comparación lista.")
        CompareDialog(data, parent=self).exec_()

    def _relocate_receiver_if_outside(self):
        """Si el receptor quedó FUERA del recinto tras un cambio de geometria,
        lo reubica a un punto interior (centro). Necesario porque el editor de
        forma corre el origen a la esquina inferior-izquierda: una planta
        dibujada vive en coords positivas que NO contienen el (0,0) del
        receptor por defecto -> caía fuera y disparaba el aviso al calcular
        modos. Solo actúa si efectivamente está fuera (no pisa un receptor que
        el usuario colocó dentro)."""
        try:
            verts, tris = self.get_surface()
            verts = np.asarray(verts, dtype=float)
            if verts.size == 0:
                return
            from acoustic_mesh import points_inside_surface
            if bool(points_inside_surface(np.array([self.receiver], float),
                                          verts, tris)[0]):
                return                          # ya está dentro: no tocar
            # Buscar un punto interior: centroide de vértices, luego centro del
            # AABB (el primero que el test point-in-mesh confirme dentro).
            zc = 0.5 * (float(verts[:, 2].min()) + float(verts[:, 2].max()))
            cands = np.array([
                [verts[:, 0].mean(), verts[:, 1].mean(), zc],
                [0.5 * (verts[:, 0].min() + verts[:, 0].max()),
                 0.5 * (verts[:, 1].min() + verts[:, 1].max()), zc],
            ], dtype=float)
            inside = points_inside_surface(cands, verts, tris)
            target = next((c for c, m in zip(cands, inside) if m), cands[0])
            self.move_receiver_to(float(target[0]), float(target[1]),
                                  float(target[2]))
            self._log(f"Receptor reubicado al interior del recinto "
                      f"({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f}) m "
                      f"— estaba fuera de la forma dibujada.")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # FEM modal
    # -----------------------------------------------------------------------
    @staticmethod
    def _reconcile_npm(npm_auto: float, npm_manual: float, h_auto: float):
        """Concilia el npm recomendado por el auto-tuner con el que escribió el
        usuario (D4: el npm manual es un PISO, no se baja).

          - npm_manual > npm_auto  -> se respeta el manual (malla más fina, más
            válida en frecuencia); h se escala consistente (h ~ 1/npm).
          - npm_manual <= npm_auto -> se usa el auto (cubre f_S; el manual no
            alcanzaba).

        Devuelve (npm_used, h_used, kept_manual: bool). Puro y testeable.
        """
        if npm_manual > npm_auto + 1e-9:
            npm_used = npm_manual
            h_used = h_auto * (npm_auto / npm_used) if npm_used > 0 else h_auto
            return npm_used, h_used, True
        return npm_auto, h_auto, False

    def _solve_fem(self):
        # Arrancar cronometro de la leyenda bajo el boton.
        try:
            self._fem_timer.start()
        except Exception:
            pass
        if len(self.sources) == 0:
            self._log("Necesitás al menos una fuente para superposicion modal "
                      "(los modos en si se resuelven igual, pero el slice de "
                      "presion requiere una excitacion).")
        try:
            verts, tris = self.get_surface()
        except Exception as e:
            QMessageBox.critical(self, "Sin geometría",
                                 f"No se pudo obtener la geometria actual:\n{e}")
            self._fem_timer.fail("sin geometría")
            return

        # Opción C (v2.24): resolver modos NO exige absorción (φₙ/fₙ son de pared
        # rígida). Pero si no se eligió, se avisa UNA vez: la malla se dimensiona
        # con α=0.05 conservador y f_S/RT60/FRF no se muestran hasta elegirla.
        if not self._has_absorption_choice() and not self._warned_no_absorption:
            self._warned_no_absorption = True
            QMessageBox.warning(
                self, "Absorción sin elegir",
                "Vas a resolver los modos sin haber elegido la absorción.\n\n"
                "Los modos (frecuencias y formas) son válidos: no dependen del "
                "material, son de pared rígida.\n\n"
                "Pero la malla se dimensiona con un α=0.05 conservador (sala "
                "viva), y la frecuencia de Schroeder, el RT60 y la FRF NO se "
                "van a mostrar hasta que asignes materiales o un α (botón "
                "«Materiales…» o «Calcular f_Schroeder»).")

        # Aviso de validez para fuentes y receptor.
        try:
            self._validate_inside(verts, tris)
        except ValueError as e:
            ret = QMessageBox.question(
                self, "Posiciones fuera del recinto",
                f"{e}\n\nContinuar de todas formas?\n"
                f"(las posiciones fuera del recinto se evaluaran con extrapolacion)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                self._fem_timer.fail("cancelado")
                return

        # Parametros para el router (proyecto > global)
        params_geom = self._current_params_for_router()
        override = self._ENGINE_KEYS.get(self.combo_engine.currentIndex(), "auto")
        is_cad = bool(getattr(self, "_is_imported_cad", False))

        # ---------- AUTO-DENSITY (motor=Automatico) ----------
        # Politica: SIEMPRE cobertura completa hasta f_Schroeder. La validez
        # fisica vale mas que la velocidad. Post-vectorizacion del voxel
        # mesher (G), incluso el peor caso CAD termina en pocos segundos —
        # no tiene sentido preguntarle al usuario "parcial o completa?".
        # El feedback visual va via un QProgressDialog (ver mas abajo).
        npm_used = float(self.sb_density.value())
        h_used   = float(self.sb_htarget.value())
        auto_used = None    # AutoDensityResult si se uso, None si manual
        if override == "auto":
            try:
                # v2.23: f_S sale del MISMO lugar que el label del panel (RT de
                # materiales, punto fijo), no de un α=0.05 fijo. El α fijo hacia
                # que la app se contradijera consigo misma y erraba en los dos
                # sentidos: sala tratada -> malla 2x mas fina de lo necesario
                # (8x nodos al pedo); sala viva -> malla que NO cubre el regimen
                # modal, en silencio (f_S ∝ α^-1/2).
                # Opción C (v2.24): el solve NO abre el gate. Sin absorción,
                # `_schroeder_context` usa el fallback α=0.05 para DIMENSIONAR la
                # malla (heurística conservadora, ya avisada arriba); f_S no se
                # muestra hasta elegir la absorción.
                ctx = self._schroeder_context()
                if ctx is None:
                    raise RuntimeError("sin geometría válida para el auto-tuner")
                V, S = ctx["V"], ctx["S"]
                f_schroeder = ctx["fs"]

                # El presupuesto de modos, no la malla, es el techo real. Weyl
                # dice cuantos modos hay debajo de f_S; si son mas de los que se
                # van a pedir, la suma modal se trunca antes de f_S y mallar
                # para f_S es gastar nodos en una banda que no se va a calcular.
                # Se malla para la banda que los modos SI cubren, y se dice.
                n_budget = int(self.sb_nmodes.value())
                n_weyl = self._weyl_modal_count(f_schroeder, V, S)
                f_target = f_schroeder
                trunc_txt = ""
                if n_weyl > n_budget:
                    f_target = self._weyl_freq_for_count(n_budget, V, S)
                    trunc_txt = (
                        f" · cobertura modal REAL hasta ~{f_target:.0f} Hz: "
                        f"cubrir f_S pediría ~{n_weyl} modos y pediste {n_budget}"
                    )

                # Si choose_engine forzara voxel por T-junctions (techo curvo
                # parametrico), restringimos al auto-tuner para que la densidad
                # recomendada sea coherente con voxel (no h_target inutil).
                forced_engine = None
                if (params_geom is not None
                        and mesh_router._has_subdivided_curved_roof(params_geom)
                        and not is_cad):
                    forced_engine = "voxel"
                # budget=inf -> auto_density siempre devuelve full_coverage.
                auto_used = mesh_router.auto_density(
                    volume_m3=V, f_target=f_target,
                    time_budget_s=float("inf"),
                    prefer_engine=forced_engine,
                )
                self._log(
                    f"Auto-tuner: V={V:.1f} m³, f_Schroeder={f_schroeder:.0f} Hz "
                    f"({ctx['src_txt']}){trunc_txt} -> {auto_used.message}"
                )
                if trunc_txt:
                    self._log(
                        f"   Para llegar a f_S={f_schroeder:.0f} Hz habría que "
                        f"pedir ~{n_weyl} modos (tope del spinbox: "
                        f"{self.sb_nmodes.maximum()})."
                    )

                # Aplicar densidades auto-tuneadas a los spinboxes (visible al
                # usuario). D4: el npm del usuario es un PISO, NO se baja. Si
                # pediste MAS densidad que la recomendada (malla mas fina = mas
                # valida, p.ej. para dar validez a mas modos bajo f_S, que es lo
                # que pide la advertencia de perturbacion), se respeta; el
                # auto-tuner solo SUBE cuando tu valor manual no alcanza a cubrir
                # f_S. `npm_used`/`h_used` traen aca el valor MANUAL (leido arriba).
                npm_auto = auto_used.n_per_meter
                npm_manual = npm_used
                npm_used, h_used, kept_manual = self._reconcile_npm(
                    npm_auto, npm_manual, auto_used.h_target)
                if kept_manual:
                    self._log(
                        f"Auto-tuner: mantengo tu npm manual {npm_manual:.2f} "
                        f"(mayor que el recomendado {npm_auto:.2f}); malla más "
                        f"fina, mayor validez en frecuencia."
                    )
                self.sb_density.blockSignals(True)
                self.sb_htarget.blockSignals(True)
                self.sb_density.setValue(npm_used)
                self.sb_htarget.setValue(h_used)
                self.sb_density.blockSignals(False)
                self.sb_htarget.blockSignals(False)
                # Hint al router PRESERVANDO el fallback automatico.
                # Si auto-tuner pico voxel, sí lo forzamos (override="voxel"):
                # geometria curva con gmsh seria mas "rigorosa" pero el
                # auto-tuner decidio que la VALIDEZ pesa mas y voxel cubre f_s
                # en budget. No queremos que el router cambie eso.
                # Si auto-tuner pico gmsh, dejamos override="auto": el router
                # tambien preferira gmsh para curvas, pero podra caer a voxel
                # si gmsh falla con T-junctions/PLC errors (caso comun en
                # techos curvos con subdiv_levels>0).
                if auto_used.engine == "voxel":
                    override = "voxel"
                # else: keep override = "auto"
            except Exception as e:
                self._log(f"WARN: auto-tuner fallo ({e}); usando densidades manuales.")

        # ProgressDialog pulsante (>200 ms, sin boton de cancelar). Le pasamos
        # un callback que actualiza el label al recibir cada mensaje de fase
        # de run_fem_modal_routed.
        from PyQt5.QtWidgets import QProgressDialog, QApplication
        prog = QProgressDialog("Calculando modos FEM…", "", 0, 0, self)
        apply_dialog_theme(prog)  # tema claro (fondo blanco)
        prog.setWindowTitle("FEM modal")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(200)             # solo aparece si tarda >200 ms
        prog.setCancelButton(None)               # sin cancelar (eigsh no es interrumpible)
        prog.setAutoClose(True)
        prog.setAutoReset(True)
        # Quitar boton de cerrar de la barra de titulo asi el usuario no cree
        # que puede cancelar via la X.
        prog.setWindowFlags(prog.windowFlags()
                            & ~Qt.WindowCloseButtonHint
                            & ~Qt.WindowContextHelpButtonHint)

        def _progress_cb(msg: str):
            self._log(msg)
            prog.setLabelText(msg)
            QApplication.processEvents()         # mantiene la barra pulsante

        try:
            self.setEnabled(False)
            self._log("FEM: comenzando...")
            self.modal_result, decision = aa.run_fem_modal_routed(
                verts, tris,
                params=params_geom,
                is_imported_cad=is_cad,
                user_override=override,
                n_modes=self.sb_nmodes.value(),
                n_per_meter=npm_used,
                h_target=h_used,
                muebles=self.furniture,     # Fase C: talla rigida (obstaculo)
                progress=_progress_cb,
            )
            # Auditoria de la talla de muebles (R2.2): avisar escalonado grosero.
            ci = getattr(self.modal_result, "carve_info", None)
            if ci is not None:
                for w in ci.get("warnings", []):
                    self._log(f"⚠ Muebles: {w}")
            self._mesh_decision = decision
            self._apply_badge(decision)
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, "Error FEM", str(e))
            self.modal_result = None
            self._fem_timer.fail("error")
            return
        finally:
            self.setEnabled(True)

        info = self.modal_result.mesh_info
        f_max = self._validity_freq(self.modal_result.mesh_info["h_max"])
        engine = info.get("engine", "?")
        t_m = info.get("t_mesh_seconds")
        t_str = f", t_malla={t_m:.2f} s" if t_m is not None else ""
        prefix = ""
        if decision is not None and getattr(decision, "fallback_reason", None):
            prefix = (f"⚠ Gmsh intentado pero fallo ({decision.fallback_reason[:60]}). "
                      "Cayendo a voxel.\n")
        _progress_cb(
            prefix +
            f"FEM listo ({engine}). Malla: {info['n_nodes']} nodos, "
            f"{info['n_tets']} tets, V≈{info['volume']:.2f} m³, "
            f"h̄≈{info['h_avg']:.2f} m{t_str}. Validez ≲ {f_max:.0f} Hz."
        )

        # Post-procesamiento visible: refrescar combo de modos, recomputar
        # xi por material y actualizar slice 2D si esta activo.
        _progress_cb("Post-procesando…")
        # CLIP por validez de malla: descartar modos con f > f_max_malla
        # (numericamente sucios). Ver _clip_modes_to_mesh_validity().
        n_req, n_kept, f_max_clip = self._clip_modes_to_mesh_validity()
        if n_kept < n_req:
            self._log(
                f"FEM: pediste {n_req} modos, {n_kept} son válidos. "
                f"{n_req - n_kept} excedían f_max_malla = {f_max_clip:.0f} Hz "
                f"(descartados por dispersión numérica del esquema)."
            )
        self._refresh_modes_combo()
        self._xi_per_mode = self._compute_xi_from_materials()
        # Etapa 2b (Pass 2): con la perturbacion activa, ahora que hay modos el
        # f_S se recalcula con el T30 por banda y se avisa si la malla (sizeada
        # con el estimador Sabine) quedo corta.
        self._post_solve_schroeder_coherence()
        self._update_slice()
        prog.close()

        # Detener cronometro DESPUES de todo lo visible al usuario, asi el
        # "Ultimo: X.XX s" abajo del boton mide click -> resultado completo.
        try:
            self._fem_timer.stop(f"válido hasta {f_max:.0f} Hz")
        except Exception:
            pass

    def _refresh_modes_combo(self):
        """Repuebla el picker de modos, respetando el filtro [f_min, f_max].

        Conserva el indice REAL del modo (en `modal_result.freqs`) como
        `userData` de cada entry del combo. Eso permite que el codigo de
        slice/heatmap/FRF siga accediendo al modo correcto aunque el combo
        este filtrado y la posicion en pantalla no coincida con el indice
        absoluto del modo.
        """
        self.combo_mode.blockSignals(True)
        self.combo_mode.clear()
        total = 0
        shown = 0
        if self.modal_result is not None:
            total = len(self.modal_result.freqs)
            # Recalibrar el rango maximo de f_max contra los modos disponibles
            # (sin emitir senales para evitar recursion).
            self.sb_fmax.blockSignals(True)
            if self.sb_fmax.value() >= 1e5 - 1.0 and total > 0:
                self.sb_fmax.setValue(float(self.modal_result.freqs[-1]))
            self.sb_fmax.blockSignals(False)
            f_min = self.sb_fmin.value()
            f_max = self.sb_fmax.value()
            if f_max < f_min:                       # sanity: swap
                f_min, f_max = f_max, f_min
            # Corrimiento Capa 0 (Etapa 5c): si hay f efectivas != rigidas, se
            # anota Δfₙ en la entrada. Sin construcciones f_eff == f_rig -> el
            # texto queda EXACTO como antes (sin marcador, sin regresion).
            f_eff = self._effective_modal_freqs()
            has_shift = (f_eff is not None
                         and len(f_eff) == len(self.modal_result.freqs))
            for i, f in enumerate(self.modal_result.freqs):
                if f_min <= f <= f_max:
                    label = f"{i}: f = {f:.2f} Hz"
                    if has_shift:
                        df = float(f_eff[i]) - float(f)
                        if abs(df) >= 5e-3:
                            label = (f"{i}: f = {float(f_eff[i]):.2f} Hz "
                                     f"(Δ{df:+.2f})")
                    self.combo_mode.addItem(label, userData=int(i))
                    shown += 1
        self.combo_mode.blockSignals(False)
        if self.combo_mode.count() > 0:
            self.combo_mode.setCurrentIndex(0)
        # Leyenda con conteo total + rango computado real + filtrado.
        # IMPORTANTE: el filtro [f_min, f_max] solo OCULTA modos del set
        # calculado; no genera nuevos. Si el f_max del filtro excede el
        # mayor modo computado, los modos "faltantes" son los que no
        # entraron al set (subir nº de modos para verlos).
        if total == 0:
            self.lbl_modes_count.setText("— sin modos calculados —")
        else:
            f_lo = float(self.modal_result.freqs[0])
            f_hi = float(self.modal_result.freqs[-1])
            base = (f"Total: {total} modos calculados "
                    f"(rango {f_lo:.1f} – {f_hi:.1f} Hz)")
            if shown == total:
                self.lbl_modes_count.setText(base + " · mostrando todos")
            else:
                filter_hi = self.sb_fmax.value()
                hi_clip = " — el filtro pasa por encima del rango calculado" \
                    if filter_hi > f_hi + 0.5 else ""
                self.lbl_modes_count.setText(
                    base + f" · mostrando {shown} en "
                    f"[{self.sb_fmin.value():.1f}, {filter_hi:.1f}] Hz"
                    + hi_clip)
        # Refrescar el cruce modal numerico (2c §9) con el set de modos actual.
        self._update_modal_crossover()
        # Read-out por modo (Etapa 5c): sincronizar con el modo ahora activo.
        self._update_mode_readout()

    def _on_mode_filter_changed(self, _value):
        """Slot disparado por sb_fmin / sb_fmax. Solo repinta el combo."""
        self._refresh_modes_combo()

    def _apply_suggested_npm(self):
        """Carga el npm sugerido (derivado de f_Schroeder) al spinbox.

        Compromiso D4: el usuario mantiene la palanca, pero un click le
        carga el valor que cubre exactamente hasta f_Schroeder.
        """
        if self._suggested_npm is None:
            self._log("Calculá f_Schroeder primero para tener un npm sugerido.")
            return
        self.sb_density.setValue(float(self._suggested_npm))
        self._log(
            f"Aplicado npm = {self._suggested_npm:.2f} "
            f"(malla quedará válida hasta f_Schroeder)."
        )

    def _clip_modes_to_mesh_validity(self) -> tuple:
        """Filtra los modos cuya frecuencia exceda la validez de la malla.

        La regla de la malla (ppw=6 puntos por longitud de onda) define
        un techo NUMERICO de validez:  f_max_malla = c / (ppw · h_max).
        Modos con f > f_max_malla son numéricamente sucios (dispersión
        del esquema, plegado de onda) aunque eigsh los devuelva sin
        error. Para no engañar al usuario los descartamos del set.

        Mutación in-place sobre `modal_result.freqs` y `modal_result.phis`.

        Returns:
            (n_requested, n_kept, f_max_malla)
        """
        if self.modal_result is None:
            return (0, 0, 0.0)
        h_max = self.modal_result.mesh_info.get("h_max", 0.0)
        f_max = self._validity_freq(h_max)
        n_req = int(len(self.modal_result.freqs))
        if f_max <= 0 or n_req == 0:
            return (n_req, n_req, f_max)
        mask = self.modal_result.freqs <= f_max
        n_kept = int(mask.sum())
        if n_kept < n_req:
            self.modal_result.freqs = self.modal_result.freqs[mask]
            self.modal_result.phis = self.modal_result.phis[:, mask]
        return (n_req, n_kept, f_max)

    def _current_mode_idx(self) -> int:
        """Indice REAL del modo seleccionado (en modal_result.freqs).

        Usa userData del combo (que el `_refresh_modes_combo` setea para
        soportar el filtro de frecuencia). Si no hay data (combo vacio o
        legacy), devuelve -1.
        """
        data = self.combo_mode.currentData()
        if isinstance(data, int):
            return data
        # Fallback defensivo: combo vacio o sin data.
        return self.combo_mode.currentIndex()

    @staticmethod
    def _validity_freq(h_max: float, ppw: float = 6.0) -> float:
        if h_max <= 0:
            return 0.0
        return 343.0 / (ppw * h_max)

    def _validate_inside(self, verts, tris):
        """Lanza ValueError si fuentes o receptor estan claramente fuera."""
        from acoustic_mesh import points_inside_surface
        all_pts = [self.receiver] + [s.position for s in self.sources]
        if not all_pts:
            return
        mask = points_inside_surface(np.array(all_pts), verts, tris)
        outside = []
        if not mask[0]:
            outside.append("receptor")
        for i, m in enumerate(mask[1:]):
            if not m:
                outside.append(f"fuente {i} ({self.sources[i].label!r})")
        if outside:
            raise ValueError("Fuera del recinto: " + ", ".join(outside))

    # -----------------------------------------------------------------------
    # Motor de mallado: combo + badge + geometria importada
    # -----------------------------------------------------------------------
    def _current_params_for_router(self):
        """Trae los params parametricos actuales para que el router los analice.
        Si la geometria es CAD importado, devuelve None (el router se entera
        por is_imported_cad=True).
        """
        if getattr(self, "_is_imported_cad", False):
            return None
        # Intentar conseguirlos via la callable de main.py
        try:
            getp = getattr(self.viewer.parent(), "controls", None)
            if getp is not None and hasattr(getp, "get_params"):
                return getp.get_params()
        except Exception:
            pass
        # Fallback: el main expone get_dims_hint pero no get_params -> intentamos
        # buscar la window ancestral.
        w = self.window()
        if w is not None and hasattr(w, "controls"):
            try:
                return w.controls.get_params()
            except Exception:
                return None
        return None

    def _on_engine_changed(self, idx: int):
        """Usuario cambio el combo. Persistir como default global y repintar badge."""
        engine = self._ENGINE_KEYS.get(idx, "auto")
        try:
            import app_settings
            app_settings.set("default_mesh_engine", engine)
        except Exception:
            pass
        self._refresh_badge_prediction()

    def _refresh_badge_prediction(self):
        """Pinta el badge con la PREDICCION (que motor se usaria) sin mallar."""
        try:
            import mesh_router as mr
        except ImportError:
            self.lbl_badge.setText("router no disponible")
            return
        params = self._current_params_for_router()
        override = self._ENGINE_KEYS.get(self.combo_engine.currentIndex(), "auto")
        is_cad = bool(getattr(self, "_is_imported_cad", False))
        d = mr.choose_engine(params=params, is_imported_cad=is_cad,
                              user_override=override)
        self._apply_badge(d, predicted=True)

    _BADGE_COLORS = {
        "green":  ("#a6e3a1", "#1a3a1a"),
        "blue":   ("#89dceb", "#1a2a3a"),
        "yellow": ("#f9e2af", "#3a2e1a"),
        "orange": ("#fab387", "#3a261a"),
    }

    def _apply_badge(self, decision, predicted: bool = False):
        """Aplica el estilo del badge segun la decision."""
        try:
            import mesh_router as mr
            b = mr.badge_for(decision)
        except Exception:
            return
        fg, bg = self._BADGE_COLORS.get(b["color"], ("#cdd6f4", "#313244"))
        prefix = "(previsto) " if predicted else ""
        self.lbl_badge.setText(prefix + b["text"])
        self.lbl_badge.setStyleSheet(
            "QLabel { padding: 4px 10px; border-radius: 6px; "
            f"background:{bg}; color:{fg}; font-weight:600; }}"
        )
        self.lbl_badge.setToolTip(b["tooltip"])

    def set_imported_geometry(self, mesh):
        """El main llama a esto cuando el usuario importa un CAD.
        `mesh`: trimesh.Trimesh ya limpia (post-dialogo de reparacion).
        """
        import numpy as _np
        self._is_imported_cad = True
        self._imported_mesh = mesh
        v = _np.asarray(mesh.vertices, dtype=_np.float32)
        t = _np.asarray(mesh.faces, dtype=_np.int32)
        self._imported_verts = v
        self._imported_tris = t
        # Recentrar receptor en el AABB del CAD
        try:
            cx, cy, _cz = v.mean(axis=0)
            zmin = float(v[:, 2].min()); zmax = float(v[:, 2].max())
            self.move_receiver_to(float(cx), float(cy), 0.5 * (zmin + zmax))
        except Exception:
            pass
        if hasattr(self, "btn_clear_cad"):
            self.btn_clear_cad.setEnabled(True)
        # Invalidar resultados previos (la geometria cambio).
        self.modal_result = None
        self._refresh_modes_combo()
        self._refresh_badge_prediction()
        self._log(f"Geometria CAD importada: {len(v)} vertices, {len(t)} tris. "
                  "El motor se eligio automaticamente (gmsh).")

    def clear_imported_geometry(self):
        """Vuelve a usar la geometria parametrica."""
        self._is_imported_cad = False
        self._imported_mesh = None
        self._imported_verts = None
        self._imported_tris = None
        if hasattr(self, "btn_clear_cad"):
            self.btn_clear_cad.setEnabled(False)
        self.modal_result = None
        self._refresh_modes_combo()
        self._refresh_badge_prediction()
        self._log("Geometria CAD descartada. Volviendo a la parametrica.")

    def get_engine_override(self) -> str:
        return self._ENGINE_KEYS.get(self.combo_engine.currentIndex(), "auto")

    def set_engine_override(self, engine: str):
        idx = self._ENGINE_IDX.get((engine or "auto").lower(), 0)
        self.combo_engine.blockSignals(True)
        self.combo_engine.setCurrentIndex(idx)
        self.combo_engine.blockSignals(False)
        self._refresh_badge_prediction()

    # -----------------------------------------------------------------------
    # Slice
    # -----------------------------------------------------------------------
    def _on_plane_changed(self, idx: int):
        """Actualiza la etiqueta del offset y dispara un nuevo slice."""
        labels = ["Posición  z:", "Posición  y:", "Posición  x:"]
        self.lbl_slice_offset.setText(labels[idx])
        # Sugerir el centro del recinto en ese eje como posición inicial
        try:
            if self.modal_result is not None:
                mn = self.modal_result.nodes.min(axis=0)
                mx = self.modal_result.nodes.max(axis=0)
                # eje fijo: idx=0→z(2), idx=1→y(1), idx=2→x(0)
                fixed_ax = [2, 1, 0][idx]
                center = float((mn[fixed_ax] + mx[fixed_ax]) / 2)
                self.sb_slice_z.blockSignals(True)
                self.sb_slice_z.setValue(round(center, 2))
                self.sb_slice_z.blockSignals(False)
        except Exception:
            pass
        self._update_slice()

    def _update_slice(self):
        if not self.chk_slice.isChecked() or self.modal_result is None:
            self.slice_item.clear()
            self.viewer.update()
            return

        mode_idx = self._current_mode_idx()
        if mode_idx < 0 or mode_idx >= self.modal_result.phis.shape[1]:
            self.slice_item.clear()
            self.viewer.update()
            return

        # Plano seleccionado: 0→XY(z=cte), 1→XZ(y=cte), 2→YZ(x=cte)
        plane_idx = self.combo_plane.currentIndex()
        axis      = [2, 1, 0][plane_idx]   # eje fijo
        offset    = self.sb_slice_z.value()
        res       = self.sb_slice_res.value()
        kind      = self.combo_field.currentIndex()
        damping   = self._xi_per_mode if self._xi_per_mode is not None else 0.03

        try:
            if kind == 0:
                sl = aa.slice_mode_shape_plane(
                    self.modal_result, mode_idx,
                    axis=axis, offset=offset, n1=res, n2=res)
                self.slice_item.update(sl, signed=True)
            else:
                act = self._active_sources()
                if len(act) == 0:
                    self.slice_item.clear()
                    self._log("Para ver |p|, agregá (o activá) al menos una fuente.")
                    self.viewer.update()
                    return
                f = self._effective_freq_of(mode_idx)   # 5c: resonancia efectiva
                sl = aa.slice_pressure_field_plane(
                    self.modal_result, act, f=f,
                    axis=axis, offset=offset, n1=res, n2=res,
                    damping=damping,
                )
                self.slice_item.update(sl, signed=False)
        except Exception as e:
            self.slice_item.clear()
            self._log(f"Slice falló: {e}")
        self.viewer.update()

    # -----------------------------------------------------------------------
    # SBIR (Speaker-Boundary Interference Response)
    # -----------------------------------------------------------------------
    def _open_sbir(self):
        """Calcula y muestra el SBIR (directo + reflexiones de 1er orden).

        Analitico, independiente del FEM: arma un plano reflectante por cada
        grupo de caras (centroide + normal), con R(f)=sqrt(1-alpha(f)) del
        material asignado (sin asignar -> alpha=0.03, casi rigido), y evalua
        el comb en el receptor para cada fuente + la suma.
        """
        import sbir
        act = self._active_sources()
        if len(act) == 0:
            QMessageBox.information(self, "Falta excitación",
                                     "Agregá (o activá) al menos una fuente.")
            return
        try:
            groups, verts, tris = self._get_face_groups()
        except Exception as e:
            QMessageBox.critical(self, "Sin geometría", str(e))
            return
        if not groups:
            QMessageBox.information(self, "Sin superficies",
                                     "No hay caras para reflejar.")
            return

        f_lo, f_hi = 20.0, 500.0
        freq = np.linspace(f_lo, f_hi, 2000)
        g2m = self._group_to_material_dict(groups)
        walls = []
        n_default = 0
        area_default = 0.0
        for g in groups:
            mat = g2m.get(g.signature)
            if mat is not None:
                alpha = np.array([mat.alpha(float(ff)) for ff in freq])
            else:
                alpha = np.full(freq.shape, 0.03)   # default rigido
                n_default += 1
                area_default += float(getattr(g, "area", 0.0) or 0.0)
            walls.append(sbir.Wall(
                point=g.centroid, normal=g.normal, label=g.label,
                R=sbir.reflection_from_alpha(alpha),
            ))
        # El default alpha=0.03 se dibuja con la misma autoridad visual que un
        # material real: una pared casi perfectamente reflectante que el usuario
        # nunca eligio. Se avisa en vez de rellenar en silencio.
        if n_default:
            area_tot = sum(float(getattr(g, "area", 0.0) or 0.0) for g in groups)
            frac = 100.0 * area_default / max(area_tot, 1e-9)
            self._log(
                f"SBIR: {n_default}/{len(groups)} superficies SIN material "
                f"({frac:.0f} % del área) → α=0.03 supuesto (casi rígido). "
                f"Las reflexiones de esas caras salen más fuertes de lo real; "
                f"asignales material en «Materiales…» para un SBIR fiel.")

        # SBIR-mueble (Fase C): la cara superior de cada mueble (tope del
        # escritorio, respaldo del sofa) rebota con rolloff de panel FINITO
        # (Rindel). Sin muebles no agrega nada -> SBIR historico intacto.
        n_furn = 0
        muebles = getattr(self, "furniture", None)
        if muebles:
            import furniture as fu
            walls.extend(fu.furniture_walls(
                muebles, self._furniture_mat_by_index(), freq))
            n_furn = len(muebles)

        try:
            res = sbir.sbir_from_sources(act, walls, self.receiver, freq)
        except Exception as e:
            QMessageBox.critical(self, "Error SBIR", str(e))
            return

        n_assigned = sum(1 for g in groups if g.signature in g2m)
        furn_str = f", {n_furn} mueble(s)" if n_furn else ""
        self._log(f"SBIR: {len(act)} fuente(s) activa(s), {len(walls)} superficies "
                  f"({n_assigned} con material){furn_str}, receptor {self.receiver}.")

        # Transferencia MODAL de la sala (FEM) en el MISMO receptor y banda, para
        # el hibrido modal+SBIR (pedido del profesor: ver el efecto de la sala
        # ademas del comb de imagenes). Se normaliza al DIRECTO de campo libre
        # (misma referencia 0 dB = anecoico que el SBIR). Solo si hay modos.
        modal_db = None
        f_s = None
        if self.modal_result is not None and len(self.modal_result.freqs) > 0:
            try:
                if self._xi_per_mode is None:
                    self._xi_per_mode = self._compute_xi_from_materials()
                damping = (self._xi_per_mode
                           if self._xi_per_mode is not None else 0.03)
                frf = aa.run_fem_frf(
                    self.modal_result, act, self.receiver,
                    f_min=f_lo, f_max=f_hi, n_freqs=len(freq), damping=damping,
                    modal_freqs=self._effective_modal_freqs())
                p_dir = np.abs(res.total_p_direct)
                modal_db = 20.0 * np.log10(
                    np.maximum(np.abs(frf.H), 1e-30) / np.maximum(p_dir, 1e-30))
                ctx = self._schroeder_context()
                f_s = float(ctx["fs"]) if ctx else None
                self._log(
                    f"SBIR: transferencia modal disponible (hibrido en "
                    f"f_S={f_s:.0f} Hz)." if f_s else
                    "SBIR: transferencia modal disponible.")
            except Exception as e:
                self._log(f"SBIR: sin transferencia modal ({e}).")
                modal_db = None
        dlg = SBIRDialog(res, f_lo=f_lo, f_hi=f_hi, parent=self,
                         modal_db=modal_db, f_schroeder=f_s)
        dlg.exec_()

    # -----------------------------------------------------------------------
    # FRF
    # -----------------------------------------------------------------------
    def _open_dba(self):
        """Abre la herramienta de subs enfrentados (DBA/CABS) sobre la caja
        rectangular (AABB) de la sala. El receptor se pasa relativo a la esquina
        mínima (la base modal analítica asume el recinto en [0,L])."""
        try:
            verts, _tris = self.get_surface()
        except Exception as e:
            QMessageBox.critical(self, "Sin geometría", str(e))
            return
        v = np.asarray(verts, dtype=float)
        if v.size == 0:
            QMessageBox.warning(self, "Sin geometría",
                                "No hay geometría para analizar.")
            return
        vmin = v.min(axis=0)
        dims = tuple((v.max(axis=0) - vmin).tolist())
        rec = tuple((np.asarray(self.receiver, dtype=float) - vmin).tolist())
        try:
            from dba_dialog import DBADialog
        except Exception as e:
            QMessageBox.critical(self, "DBA", f"No se pudo abrir la herramienta:\n{e}")
            return
        DBADialog(dims, rec, self,
                  apply_callback=lambda specs: self._apply_dba_to_room(specs, vmin)
                  ).exec_()

    def _apply_dba_to_room(self, specs, vmin):
        """Materializa el preset DBA como fuentes en la sala. Las posiciones
        vienen en [0,L]; se corren por `vmin` (esquina de la caja). Reemplaza las
        fuentes DBA previas (label DBA-*); conserva el resto. Si hay otras
        fuentes activas, ofrece mutearlas para un A/B limpio (solo el DBA)."""
        from sources import OmniSource
        vmin = np.asarray(vmin, dtype=float)
        # ¿Hay otras fuentes (no DBA) activas? -> ofrecer mutearlas para que el
        # DBA sea la ÚNICA excitación (si no, se suma baseline + DBA y la FRF no
        # significa nada). Se pueden reactivar con el mute por fuente.
        others_active = [
            s for s in self.sources.sources
            if not str(getattr(s, "label", "")).startswith("DBA-")
            and getattr(s, "active", True)]
        mute_others = False
        if others_active:
            mute_others = QMessageBox.question(
                self, "Aplicar DBA a la sala",
                f"Hay {len(others_active)} fuente(s) que no son del DBA activas.\n\n"
                "¿Mutearlas para medir/escuchar SOLO el DBA? (evita sumar "
                "baseline + DBA; las reactivás cuando quieras con el mute por "
                "fuente).", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        # sacar las fuentes DBA anteriores
        self.sources.sources = [
            s for s in self.sources.sources
            if not str(getattr(s, "label", "")).startswith("DBA-")]
        if mute_others:
            for s in self.sources.sources:
                s.active = False
        for sp in specs:
            pos = tuple((np.asarray(sp["pos"], dtype=float) + vmin).tolist())
            src = OmniSource(position=pos, label=sp["label"], Q=sp.get("Q", 1.0),
                             delay_s=sp.get("delay_s", 0.0),
                             polarity=sp.get("polarity", 1))
            src.response = sp.get("response")
            self.sources.add(src)
        self._refresh_sources_list()
        self.schedule_field_update()
        muted = "  (otras fuentes muteadas)" if mute_others else ""
        self._log(f"DBA aplicado: {len(specs)} fuentes creadas.{muted}")

    def _compute_frf(self, method: str = "fem"):
        act = self._active_sources()
        if len(act) == 0:
            QMessageBox.information(self, "Falta excitación",
                                     "Agregá (o activá) al menos una fuente.")
            return
        try:
            verts, tris = self.get_surface()
        except Exception as e:
            QMessageBox.critical(self, "Sin geometría", str(e))
            return
        # Opción C (v2.24): la FRF depende del amortiguamiento -> exige absorción.
        # Abre el gate; si queda sin elegir, avisa y no computa desde un default.
        if not self._ensure_absorption_choice():
            QMessageBox.warning(
                self, "Absorción sin elegir",
                "La FRF depende de la absorción (amortiguamiento de cada modo).\n\n"
                "Asigná materiales (botón «Materiales…») o un α uniforme antes de "
                "calcular la respuesta en frecuencia.")
            return
        damping = self._xi_per_mode if self._xi_per_mode is not None else 0.03
        try:
            self.setEnabled(False)
            if self.modal_result is None:
                self._log("FRF requiere modos. Calculando primero...")
                self.modal_result = aa.run_fem_modal(
                    verts, tris,
                    n_modes=self.sb_nmodes.value(),
                    n_per_meter=self.sb_density.value(),
                    muebles=self.furniture,     # Fase C: talla rigida (obstaculo)
                    progress=self._log,
                )
                # CLIP por validez de malla (idem main solve path).
                n_req, n_kept, f_max_clip = self._clip_modes_to_mesh_validity()
                if n_kept < n_req:
                    self._log(
                        f"FEM: pediste {n_req} modos, {n_kept} son válidos. "
                        f"{n_req - n_kept} excedían f_max_malla = {f_max_clip:.0f} Hz "
                        f"(descartados)."
                    )
                self._refresh_modes_combo()
                self._xi_per_mode = self._compute_xi_from_materials()
                damping = self._xi_per_mode if self._xi_per_mode is not None else 0.03
            self._log("Calculando FRF (FEM)...")
            result = aa.run_fem_frf(
                self.modal_result, act, self.receiver,
                f_min=self.sb_frf_fmin.value(),
                f_max=self.sb_frf_fmax.value(),
                n_freqs=self.sb_frf_n.value(),
                damping=damping,
                # Capa 0 (Etapa 5): resonancias corridas por reactancia de pared.
                modal_freqs=self._effective_modal_freqs(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Error FRF", str(e))
            return
        finally:
            self.setEnabled(True)
        self._log("FRF FEM listo.")

        # Figura de merito (2c §8): respuesta forzada sobre una grilla de
        # receptores, en la banda valida de la malla. Best-effort: nunca debe
        # bloquear la FRF.
        fom = None
        fom_band = None
        eqc = None
        eqc_band = None
        try:
            import modal_metrics as mm
            h_max = self.modal_result.mesh_info.get("h_max", 0.0)
            fa = np.asarray(result.freq_axis, dtype=float)
            f_max = self._validity_freq(h_max) if h_max > 0 else float(fa[-1])
            mask = fa <= f_max
            if np.count_nonzero(mask) >= 10:
                fa_valid = fa[mask]
                # locator+phis: descarta los puntos de la grilla que caen fuera
                # del recinto (el bbox no es la planta). Sin esto, en cualquier
                # sala no rectangular los puntos de afuera entraban con presion
                # 0 y el FoM espacial salia ~90 dB en vez de ~5.
                receivers = mm.default_receiver_grid(
                    self.modal_result.nodes,
                    locator=self.modal_result.locator,
                    phis=self.modal_result.phis)
                # H_real (= compute_forced_response) + H_env para corregibilidad EQ.
                H, H_env = mm.forced_response_with_envelope(
                    self.modal_result.locator,
                    self._effective_modal_freqs(), self.modal_result.phis,
                    act, receivers, fa_valid, damping=damping)
                fom = mm.response_figures_of_merit(H, fa_valid)
                fom_band = (float(fa_valid[0]), float(fa_valid[-1]),
                            int(len(receivers)))
                self._log(
                    f"FoM (banda ≤{f_max:.0f} Hz, {len(receivers)} receptores): "
                    f"planitud {fom.FoM_flat:.2f} dB · "
                    f"espacial {fom.FoM_espacial:.2f} dB")
                # Diagnostico de corregibilidad EQ (C13/C21). Necesita MAS resolucion
                # que el solver (ppw~15: signos de phi_n cerca de nodos) -> se limita
                # a su sub-banda confiable, mas angosta que la banda valida del FoM.
                f_eq_max = (343.0 / (mm.PPW_EQ_DIAGNOSIS * h_max)
                            if h_max > 0 else float(fa_valid[-1]))
                eq_mask = fa_valid <= f_eq_max
                if np.count_nonzero(eq_mask) >= 10:
                    fa_eq = fa_valid[eq_mask]
                    eqc = mm.eq_correctability(H[:, eq_mask], fa_eq,
                                               H_env=H_env[:, eq_mask])
                    eqc_band = (float(fa_eq[0]), float(fa_eq[-1]))
                    self._log(
                        f"Corregibilidad EQ (banda ≤{fa_eq[-1]:.0f} Hz): aplana "
                        f"{eqc.improvement_flat:.1f} dB, {eqc.fom_espacial:.1f} dB "
                        f"irreducible" +
                        ("" if f_eq_max >= fa_valid[-1] - 1.0
                         else " · subí npm para diagnosticar más arriba"))
                else:
                    self._log("Corregibilidad EQ: malla muy gruesa (npm bajo), omitida.")
            else:
                self._log("FoM: banda válida muy chica para la grilla, omitida.")
        except Exception as e:
            self._log(f"Aviso FoM: {e}")

        # C1 (auditoria): techo de validez de la FRF = min(f_max_malla, ultimo modo
        # calculado). Por encima, la superposicion modal es cola-suma truncada
        # (hasta 27 dB de error medido) y/o esta fuera de la validez numerica de la
        # malla. Se lo pasamos al plot para SOMBREAR esa banda, no mostrarla como valida.
        f_valid = None
        if self.modal_result is not None:
            try:
                h_max = self.modal_result.mesh_info.get("h_max", 0.0)
                f_mesh = self._validity_freq(h_max) if h_max and h_max > 0 else None
                mf = self._effective_modal_freqs()
                f_last = float(np.max(mf)) if mf is not None and len(mf) else None
                cands = [x for x in (f_mesh, f_last) if x and x > 0]
                f_valid = min(cands) if cands else None
            except Exception:
                f_valid = None

        dlg = FRFDialog(
            result,
            modal_freqs=(self._effective_modal_freqs()
                         if self.modal_result else None),
            parent=self,
            fom=fom, fom_band=fom_band, eqc=eqc, eqc_band=eqc_band,
            f_valid=f_valid,
        )
        dlg.exec_()

    # -----------------------------------------------------------------------
    # Hooks para que el main reaccione a cambios externos (e.g. reset geometria)
    # -----------------------------------------------------------------------
    def on_geometry_changed(self):
        """Llamar cuando la geometria cambio: invalida todos los resultados."""
        self.modal_result = None
        self._xi_per_mode = None
        self._clear_field_3d()
        self.slice_item.clear()
        self._refresh_modes_combo()
        # Invalidar cache de grupos de caras (la malla cambio).
        self._face_groups_cache = None
        self._face_groups_for_verts_id = None
        # Repintar badge (puede haber cambiado axis-aligned -> curva o viceversa).
        if hasattr(self, "lbl_badge"):
            self._refresh_badge_prediction()
        # Refrescar resumen de materiales (areas pueden haber cambiado)
        if hasattr(self, "lbl_mat_summary"):
            try:
                self._refresh_materials_summary()
            except Exception:
                pass
        # Si el receptor quedó fuera del nuevo recinto (típico al dibujar una
        # forma custom: su origen no es el (0,0) del receptor por defecto),
        # reubicarlo al interior.
        self._relocate_receiver_if_outside()
        self.viewer.update()

    # -----------------------------------------------------------------------
    # API PUBLICA: colocar fuentes desde la vista 3D o el canvas 2D
    # -----------------------------------------------------------------------
    def add_source_at(self, x: float, y: float, z: float = 1.0):
        """Agrega una fuente en la posicion (x,y,z). Llamado por Ctrl+Click derecho.

        z=1.0 por defecto (1 m desde el piso).
        """
        label = f"src_{len(self.sources)}"
        src = OmniSource(position=(x, y, z), label=label,
                         sensitivity_dB=90.0, power_W=1.0, f_ref=1000.0)
        self.sources.add(src)
        self._refresh_sources_list()   # ya sincroniza positions al viewer
        self._log(f"Fuente '{label}' en ({x:.2f}, {y:.2f}, {z:.2f}) m. "
                  f"Presioná Enter o 'Calcular modos' para simular.")

    def add_source_at_floor(self, x: float, y: float):
        """Convenience: agrega fuente a 1 m del piso (desde canvas 2D)."""
        self.add_source_at(x, y, z=1.0)

    def _sync_source_positions_to_viewer(self):
        """Comunica las posiciones de fuentes al IsoViewer (para picking)."""
        if hasattr(self.viewer, 'set_source_positions'):
            self.viewer.set_source_positions(
                [s.position for s in self.sources]
            )

    def trigger_compute(self):
        """Llamado por la tecla Enter: lanza FEM si no hay solucion, si hay
        solucion actualiza el campo a la frecuencia del modo seleccionado.
        """
        if self.modal_result is None:
            self._solve_fem()
        else:
            self._update_field_3d()

    # -----------------------------------------------------------------------
    # Campo 3D y flechas de gradiente
    # -----------------------------------------------------------------------
    def _ensure_3d_overlays(self):
        """Crea los overlays 3D si aun no existen."""
        if not hasattr(self, 'pressure_3d'):
            import acoustic_viewer as av_mod
            self.pressure_3d = av_mod.PressureField3D(self.viewer)
            self.grad_arrows = av_mod.GradientArrows(self.viewer)

    def _update_field_3d(self):
        """Actualiza la nube de puntos 3D segun el modo de campo seleccionado.

        - combo_field == 0: Forma modal (azul/blanco/rojo, con signo, SIN fuente)
        - combo_field == 1: Presion |p| (azul→rojo, DEPENDE de la fuente)
        """
        self._ensure_3d_overlays()
        self.pressure_3d.clear()
        self.grad_arrows.clear()

        if self.modal_result is None:
            self.viewer.update()
            return

        mode_idx = self._current_mode_idx()
        if mode_idx < 0 or mode_idx >= len(self.modal_result.freqs):
            self.viewer.update()
            return

        kind = self.combo_field.currentIndex()   # 0=modo, 1=presion
        f    = float(self.modal_result.freqs[mode_idx])
        res  = self.sb_field3d_res.value()      # controlado por el usuario

        import acoustic_analysis as aa_mod

        try:
            if kind == 0:
                # ---- Forma modal (independiente de fuente) ----
                self._log(f"Calculando forma modal {mode_idx} en 3D...")
                pts, vals, _ = aa_mod.mode_shape_field_3d(
                    self.modal_result, mode_idx, resolution=res)
                self.pressure_3d.update_signed(pts, vals, point_size=7)
                self._log(
                    f"Forma modal {mode_idx} ({f:.1f} Hz): {len(pts)} pts. "
                    f"Azul=(-), Blanco=0, Rojo=(+)."
                )

            else:
                # ---- Presion |p| (depende de fuente) ----
                act = self._active_sources()
                if len(act) == 0:
                    self._log("Para 'Presión |p|', agregá (o activá) al menos "
                              "una fuente.")
                    self.viewer.update()
                    return
                damping = self._xi_per_mode if self._xi_per_mode is not None else 0.03
                self._log(f"Calculando |p| 3D a {f:.1f} Hz...")
                pts, p_abs, _ = aa_mod.pressure_field_3d(
                    self.modal_result, act, f=f,
                    resolution=res, damping=damping)
                self.pressure_3d.update(pts, p_abs, point_size=7)

                if hasattr(self, 'chk_grad') and self.chk_grad.isChecked():
                    origs, grads = aa_mod.pressure_gradient_3d(
                        self.modal_result, self.sources, f=f,
                        resolution=max(6, res // 3), damping=damping)
                    self.grad_arrows.update(origs, grads)

                self._log(
                    f"|p| 3D listo: {len(pts)} puntos, f={f:.1f} Hz. "
                    f"Fuente en {[s.position for s in self.sources]}."
                )

        except Exception as e:
            self._log(f"Error campo 3D: {e}")

        self.viewer.update()

    def _deferred_field_update(self):
        """Ejecutado por el timer despues de mover una fuente (debounce 350ms)."""
        if self.modal_result is None:
            return
        if self.combo_field.currentIndex() == 1:   # presion depende de fuente
            self._update_slice()
            self._update_field_3d()

    def schedule_field_update(self):
        """Llamar cuando la fuente se mueve para agendar actualizacion del campo."""
        self._field_timer.start()   # reinicia el timer en cada llamada

    def _clear_field_3d(self):
        if hasattr(self, 'pressure_3d'):
            self.pressure_3d.clear()
        if hasattr(self, 'grad_arrows'):
            self.grad_arrows.clear()

    # -----------------------------------------------------------------------
    # Calcular frecuencia de Schroeder y mostrarla
    # -----------------------------------------------------------------------
    @staticmethod
    def _weyl_modal_count(f: float, V: float, S: float, c: float = 343.0) -> int:
        """Estimacion de Weyl: numero de modos por debajo de `f` en una
        cavidad acustica 3D con paredes rigidas (Neumann).

            N(f) ~= (4 pi / 3) * V * f^3 / c^3        ← termino de volumen
                    + (pi / 4) * S * f^2 / c^2         ← correccion de superficie
                    + O(f)                              ← terminos de aristas (despreciables)

        El termino dominante es el de volumen; para frecuencias bajas
        (sub-Schroeder de salas chicas) la correccion de superficie aporta
        ~10-30 %, asi que la incluimos.
        """
        if f <= 0 or V <= 0:
            return 0
        n_vol = (4.0 / 3.0) * np.pi * V * (f ** 3) / (c ** 3)
        n_surf = (np.pi / 4.0) * S * (f ** 2) / (c ** 2) if S > 0 else 0.0
        return int(round(n_vol + n_surf))

    @classmethod
    def _weyl_freq_for_count(cls, n: int, V: float, S: float,
                             c: float = 343.0) -> float:
        """Inversa de `_weyl_modal_count`: hasta que frecuencia llegan `n` modos.

        N(f) es monotona creciente, asi que basta biseccion. Sirve para decir
        la verdad cuando el presupuesto de modos NO alcanza a cubrir f_S: la
        malla puede ser valida hasta f_S, pero la suma modal se trunca antes.
        """
        if n <= 0 or V <= 0:
            return 0.0
        lo, hi = 0.0, 20.0
        while cls._weyl_modal_count(hi, V, S, c) < n and hi < 20000.0:
            hi *= 2.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if cls._weyl_modal_count(mid, V, S, c) < n:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _n_assigned_groups(self, groups) -> int:
        """Grupos con material asignado EXPLICITAMENTE (no por el default del
        mapa). Es el test correcto para "no asignaste nada": `_face_mat_map.get`
        nunca devuelve vacio porque cae a su `default`."""
        asig = self._face_mat_map.to_dict()
        return sum(1 for g in groups if asig.get(g.signature))

    def absorption_state(self):
        """Decisión de absorción normalizada para compartir con Predicción.

        None si no se eligió. `{"mode":"uniform","alpha":x}` si el gate fijó un
        α; `{"mode":"materials","names":(piso,pared,techo)}` si hay materiales
        asignados (material representativo por zona). Ver [[z-impedance-modeling]]
        no aplica acá: esto es el baseline de absorción, no la impedancia.
        """
        if self._abs_choice_alpha is not None:
            return {"mode": "uniform", "alpha": float(self._abs_choice_alpha)}
        try:
            groups, _v, _t = self._get_face_groups()
        except Exception:
            return None
        if not groups or self._n_assigned_groups(groups) == 0:
            return None
        from collections import Counter
        by_kind = {"floor": Counter(), "wall": Counter(), "ceiling": Counter()}
        for g in groups:
            nm = self._face_mat_map.get(g.signature)
            if not nm:
                continue
            k = g.kind if g.kind in ("floor", "ceiling") else "wall"
            by_kind[k][nm] += 1
        allc = Counter()
        for c in by_kind.values():
            allc += c
        default = allc.most_common(1)[0][0] if allc else None

        def _rep(k):
            c = by_kind[k]
            return c.most_common(1)[0][0] if c else default
        floor, wall, ceil = _rep("floor"), _rep("wall"), _rep("ceiling")
        if not (floor and wall and ceil):
            return None
        return {"mode": "materials", "names": (floor, wall, ceil)}

    def adopt_absorption_state(self, state):
        """Adopta una decisión venida de Predicción (puente BIDIRECCIONAL).

        Sincroniza en los DOS sentidos (decisión del usuario "bidireccional con
        override"): α uniforme -> baseline escalar; materiales (piso/pared/techo)
        -> se asignan de verdad a la sala con apply_zone_materials (el gate de
        Predicción usa el mismo modelo de 3 zonas, así que el mapeo es exacto).
        `target` no tiene equivalente acá -> se ignora. NO reemite (evita loops).
        """
        if not state:
            return
        mode = state.get("mode")
        if mode == "uniform":
            self._abs_choice_alpha = float(state.get("alpha", 0.05))
            self._abs_choice_asked = True
            self._abs_choice_txt = (f"α={self._abs_choice_alpha:.3f} uniforme "
                                    f"(heredado de Predicción)")
            self._log("Absorción: α heredado de Predicción "
                      f"(α={self._abs_choice_alpha:.3f}).")
            self._refresh_abs_choice_label()
        elif mode == "materials":
            names = state.get("names")
            if not (names and len(names) == 3 and all(names)):
                return
            if self.apply_zone_materials(*names):
                self._abs_choice_alpha = None     # ahora hay materiales reales
                self._abs_choice_asked = True
                nf, nw, nc = names
                self._abs_choice_txt = (f"materiales heredados de Predicción "
                                        f"(piso {nf} · paredes {nw} · techo {nc})")
                self._log("Absorción: materiales heredados de Predicción "
                          f"(piso {nf} · paredes {nw} · techo {nc}).")
                self._refresh_abs_choice_label()

    def _has_absorption_choice(self) -> bool:
        """True si el usuario ya definió la absorción: α uniforme elegido en el
        gate, o al menos un material asignado. Opción C (v2.24): los números que
        dependen del material (f_S, RT60, FRF, ξ) no se muestran hasta que esto
        sea True; los modos φₙ/fₙ NO lo necesitan (son de pared rígida)."""
        if self._abs_choice_alpha is not None:
            return True
        try:
            groups, _v, _t = self._get_face_groups()
            return bool(groups) and self._n_assigned_groups(groups) > 0
        except Exception:
            return False

    def _ensure_absorption_choice(self) -> bool:
        """Abre el gate de absorción si todavía no se eligió, y devuelve True si
        al final HAY una elección (α o materiales), False si no.

        Opción C (v2.24): cancelar el gate ya NO pone un α=0.05 silencioso; deja
        la absorción SIN elegir (los números dependientes de material quedan en
        "— asigná absorción") y no vuelve a preguntar solo en la sesión.
        """
        if self._has_absorption_choice():
            return True
        if self._abs_choice_asked:
            return False                # ya se preguntó y se dejó sin elegir
        try:
            groups, _v, _t = self._get_face_groups()
        except Exception:
            return False
        if not groups:
            return False

        self._abs_choice_asked = True   # se pregunta UNA vez, pase lo que pase

        # Headless: un dialogo modal bajo QT_QPA_PLATFORM=offscreen segfaultea
        # (gotcha conocido del proyecto, ver notas §13 entrada 16 Jun). Los
        # benches tienen que poder correr el camino completo sin GUI, asi que
        # ahi se resuelve con el fallback historico en vez de preguntar.
        try:
            from PyQt5.QtWidgets import QApplication as _QApp
            _app = _QApp.instance()
            if _app is not None and _app.platformName() == "offscreen":
                self._abs_choice_alpha = 0.05
                self._abs_choice_txt = "α=0.05 fijo (headless: sin gate)"
                return True
        except Exception:
            pass

        try:
            dlg = AbsorptionChoiceDialog(self._mat_lib.names, self)
            if dlg.exec_() != QDialog.Accepted:
                # Opción C: cancelar deja SIN elegir (no α=0.05 silencioso).
                self._log("Absorción: gate cancelado → sin elegir "
                          "(f_S/RT60/FRF quedan en «— asigná absorción»).")
                self._refresh_abs_choice_label()
                return False
            kind, value = dlg.choice()
        except Exception as e:
            self._log(f"Absorción: no se pudo abrir el gate ({e}).")
            return False

        if kind == "alpha":
            self._abs_choice_alpha = float(value)
            self._abs_choice_txt = f"α={value:.3f} uniforme (sin materiales asignados)"
            self._log(f"Absorción: α={value:.3f} uniforme para f_Schroeder y malla.")
        elif kind == "preset":
            mf, mw, mc = ml.preset_surface_materials(self._mat_lib, value)
            if self.apply_zone_materials(mf.name, mw.name, mc.name):
                self._abs_choice_txt = f"preset «{value}»"
                self._log(f"Absorción: preset «{value}» aplicado "
                          f"(piso {mf.name} · paredes {mw.name} · techo {mc.name}).")
            else:
                self._abs_choice_alpha = 0.05
                self._abs_choice_txt = "α=0.05 fijo (el preset no pudo aplicarse)"
        else:                            # uniform
            if self.apply_zone_materials(value, value, value):
                self._abs_choice_txt = f"«{value}» en todas las caras"
                self._log(f"Absorción: «{value}» asignado a todas las caras.")
            else:
                self._abs_choice_alpha = 0.05
                self._abs_choice_txt = "α=0.05 fijo (no se pudo asignar)"
        self._refresh_abs_choice_label()
        # Comunica la decisión a Predicción (puente bidireccional).
        self.absorptionChoiceChanged.emit(self.absorption_state())
        return True

    def _refresh_abs_choice_label(self) -> None:
        """Reescribe el label de absorcion DERIVANDOLO del estado actual.

        No guarda un texto congelado: si guardara, decir "Absorción del 1% en
        todas las caras" seguiria en pantalla despues de que el usuario cambie
        los materiales a mano, mintiendo sobre de donde sale el f_S que se
        acaba de mostrar.

        El orden de prioridad tiene que ser EL MISMO que el de
        `_schroeder_context` (materiales asignados > α elegido), porque este
        label existe justamente para decir cual de los dos se uso.
        """
        if not hasattr(self, "lbl_abs_choice"):
            return
        txt = ""
        try:
            groups, _v, _t = self._get_face_groups()
        except Exception:
            groups = []
        n_asig = self._n_assigned_groups(groups) if groups else 0

        if n_asig > 0:
            asig = self._face_mat_map.to_dict()
            names = []
            for g in groups:
                nm = asig.get(g.signature)
                if nm and nm not in names:
                    names.append(nm)
            if len(names) == 1:
                donde = ("en todas las caras" if n_asig == len(groups)
                         else f"en {n_asig} cara" + ("s" if n_asig != 1 else ""))
                txt = f"«{names[0]}» {donde}"
            elif len(names) <= 3:
                txt = f"{' · '.join(names)}  ({n_asig}/{len(groups)} grupos)"
            else:
                txt = (f"{len(names)} materiales por cara "
                       f"({n_asig}/{len(groups)} grupos)")
            if n_asig < len(groups):
                txt += f" · {len(groups) - n_asig} sin asignar"
        elif self._abs_choice_alpha is not None:
            txt = self._abs_choice_txt or f"α={self._abs_choice_alpha:.3f} uniforme"

        # Los parches restan area a su cara anfitriona y aportan su propio α:
        # tambien mueven el RT, asi que corresponde nombrarlos.
        if txt and self._patches:
            txt += f" · {len(self._patches)} parche(s)"

        self.lbl_abs_choice.setText(f"Absorción: {txt}" if txt else "")
        self.lbl_abs_choice.setVisible(bool(txt))

    def _schroeder_context(self) -> Optional[dict]:
        """f_Schroeder + contexto, en UN solo lugar (v2.23).

        Antes esto vivia duplicado: el label del panel resolvia el punto fijo
        con el RT de los materiales (v2.16) y el auto-tuner de malla usaba
        `schroeder_frequency(V, S, alpha=0.05)` fijo. Los dos numeros diferian
        hasta 2x y la app se contradecia a si misma en el mismo log.

        Devuelve dict con fs, V, S, src_txt, n_asig, n_groups, rt_src — o None
        si no hay geometria util.

        Etapa 2b (dos pasadas): el RT del punto fijo sale de
        `_effective_rt60_by_band`, NO de Sabine directo. Pre-solve (sin modos)
        eso cae a Sabine -> el auto-tuner dimensiona la malla con el estimador
        Sabine (Pass 1, no hay delta_n todavia = chicken-egg). Post-solve, con
        el modelo de perturbacion activo, usa el T30 por banda -> f_S refleja el
        amortiguamiento por modo (Pass 2). Un re-solve con la misma geometria
        aprovecha el xi de la pasada anterior (refinamiento iterativo); un
        cambio de geometria resetea modal_result -> vuelve a Sabine.
        """
        try:
            import acoustic_analysis as aa_mod
            verts, tris = self.get_surface()
            V = aa_mod.compute_mesh_volume(verts, tris)
            S = aa_mod.compute_mesh_surface_area(verts, tris)
        except Exception:
            return None
        if V <= 0:
            return None

        fs = None
        src_txt = ""
        rt_src = "sabine"
        n_asig = 0
        n_groups = 0
        try:
            groups, _gv, _gt = self._get_face_groups()
            n_groups = len(groups) if groups else 0
            n_asig = self._n_assigned_groups(groups) if groups else 0
            # Solo se usa el RT por materiales si hay asignaciones EXPLICITAS.
            # Sin ellas el mapa caeria a su default alfabetico, que el usuario
            # nunca eligio -> lo resuelve el gate (`_ensure_absorption_choice`).
            if groups and n_asig > 0:
                g2m = self._group_to_material_dict(groups)
                rt, rt_src = self._effective_rt60_by_band(V, groups, g2m)
                if rt:
                    bands = np.array(sorted(rt), dtype=float)
                    rts = np.array([rt[b] for b in sorted(rt)], dtype=float)
                    fs = 2000.0 * np.sqrt(max(float(rts[0]), 1e-3) / V)
                    rt_used = float(rts[0])
                    for _ in range(12):
                        rt_used = float(np.interp(fs, bands, rts))
                        fs_new = 2000.0 * np.sqrt(max(rt_used, 1e-3) / V)
                        if abs(fs_new - fs) < 0.5:
                            fs = fs_new
                            break
                        fs = fs_new
                    modelo = ("perturbación T30" if rt_src == "perturbacion+sabine"
                              else "RT de materiales")
                    src_txt = (f"{modelo}: RT(f_S)={rt_used:.2f} s "
                               f"({n_asig}/{n_groups} grupos asignados)")
        except Exception:
            fs = None

        if fs is None or not np.isfinite(fs) or fs <= 0:
            alpha = (self._abs_choice_alpha
                     if self._abs_choice_alpha is not None else 0.05)
            fs = aa_mod.schroeder_frequency(V, S, alpha=alpha)
            rt_src = "sabine"
            src_txt = (f"α={alpha:.3f} uniforme"
                       if self._abs_choice_alpha is not None else
                       f"α={alpha} fijo (fallback: sin materiales)")
        return {"fs": float(fs), "V": float(V), "S": float(S),
                "src_txt": src_txt, "rt_src": rt_src,
                "n_asig": n_asig, "n_groups": n_groups}

    def compute_and_show_schroeder(self):
        """Calcula y muestra la frecuencia de Schroeder del recinto actual."""
        try:
            # Opción C (v2.24): f_S depende de la absorción -> exige elegirla. Si
            # queda sin elegir, avisa y no muestra un f_S de un default silencioso.
            if not self._ensure_absorption_choice():
                if hasattr(self, "lbl_schroeder"):
                    self.lbl_schroeder.setText("f_Schroeder: — (asigná absorción)")
                QMessageBox.warning(
                    self, "Absorción sin elegir",
                    "La frecuencia de Schroeder depende de la absorción de la "
                    "sala (RT60).\n\nAsigná materiales (botón «Materiales…») o un "
                    "α uniforme y volvé a calcularla.\n\nCon eso también se "
                    "auto-carga el número de modos necesario para cubrir hasta "
                    "f_Schroeder.")
                return None
            ctx = self._schroeder_context()
            if ctx is None:
                self._log("Schroeder: no hay geometría válida.")
                return None
            fs, V, S, src_txt = ctx["fs"], ctx["V"], ctx["S"], ctx["src_txt"]
            # El label se lee justo acá (el usuario acaba de pedir f_S), asi que
            # se re-deriva aunque el cambio de material haya entrado por otra via.
            self._refresh_abs_choice_label()
            self._log(
                f"Frecuencia de Schroeder: {fs:.0f} Hz  "
                f"(V={V:.1f} m³, S={S:.1f} m², {src_txt}). "
                f"FEM aplica debajo de esta frecuencia."
            )
            if hasattr(self, 'lbl_schroeder'):
                self.lbl_schroeder.setText(f"f_Schroeder ≈ {fs:.0f} Hz")
            # Compromiso D4: calcular npm sugerido para cubrir hasta f_S.
            #   f_max_malla = c / (ppw * h),  h = 1/npm  =>  npm = ppw * f / c
            # Con ppw=6 y c=343:  npm = f_S / 57.17.
            # El usuario decide si lo aplica o sigue con su valor manual.
            if hasattr(self, 'lbl_npm_suggested') and fs > 0:
                ppw = 6.0
                c_air = 343.0
                npm_sug = ppw * fs / c_air
                npm_lo = self.sb_density.minimum()
                npm_hi = self.sb_density.maximum()
                npm_sug_clip = float(min(max(npm_sug, npm_lo), npm_hi))
                self._suggested_npm = npm_sug_clip
                if abs(npm_sug - npm_sug_clip) > 0.05:
                    msg = (f"npm sugerido: {npm_sug:.2f} "
                            f"(clip a {npm_sug_clip:.2f} por rango {npm_lo:.1f}-{npm_hi:.1f})")
                else:
                    msg = (f"npm sugerido: {npm_sug_clip:.2f}  "
                            f"(malla válida exactamente hasta f_Schroeder)")
                self.lbl_npm_suggested.setText(msg)
                self.btn_apply_npm_suggested.setEnabled(True)
            # Sugerencia Weyl: cuantos modos hay por debajo de f_S.
            # El usuario decide cuantos pedir; este numero es solo informativo.
            if hasattr(self, 'lbl_modes_weyl'):
                n_weyl = self._weyl_modal_count(fs, V, S)
                cap = self.sb_nmodes.maximum()
                # Request 2 (v2.24): auto-cargar Nº modos con el número necesario
                # para cubrir hasta f_S (Weyl, clampeado al tope). Aparece directo
                # en el spinbox; el usuario puede bajarlo si quiere menos.
                n_set = int(min(max(n_weyl, 2), cap)) if n_weyl > 0 else None
                if n_set is not None and n_set != self.sb_nmodes.value():
                    self.sb_nmodes.blockSignals(True)
                    self.sb_nmodes.setValue(n_set)
                    self.sb_nmodes.blockSignals(False)
                if n_weyl == 0:
                    self.lbl_modes_weyl.setText(
                        "≈ ? modos hasta f_Schroeder (V o f inválidos)")
                elif n_weyl > cap:
                    # Refinar la malla NO agrega modos: el techo acá es el
                    # presupuesto de modos, no la resolución espacial.
                    f_cap = self._weyl_freq_for_count(cap, V, S)
                    self.lbl_modes_weyl.setText(
                        f"≈ {n_weyl} modos hasta f_S (Weyl) · Nº modos puesto en el "
                        f"tope {cap} → llegás hasta ~{f_cap:.0f} Hz. "
                        f"Cubrir f_S entero no es alcanzable en esta sala.")
                else:
                    self.lbl_modes_weyl.setText(
                        f"≈ {n_weyl} modos hasta f_S (Weyl) · Nº modos auto-cargado "
                        f"en {n_set} para cobertura completa")
            # Si ya hay modos, mostrar tambien el cruce numerico (2c §9) al lado.
            self._update_modal_crossover()
            return fs
        except Exception as e:
            self._log(f"Error Schroeder: {e}")
            return None

    def _post_solve_schroeder_coherence(self):
        """Etapa 2b (Pass 2): tras resolver con el modelo de perturbacion, el f_S
        se recalcula con el T30 por banda (mas largo en graves -> f_S mas alto
        que el estimador Sabine con el que se dimensiono la malla). Refresca el
        label y avisa si la malla quedo corta (sub-cubre la banda modal). NO
        re-malla solo: el usuario decide (subir npm y re-resolver). No abre el
        gate (post-solve la absorcion ya esta resuelta) ni propaga excepciones."""
        if self._damping_model != "perturbation" or self.modal_result is None:
            return
        try:
            ctx = self._schroeder_context()
        except Exception:
            return
        # Solo si el f_S salio de verdad de la perturbacion (no del fallback).
        if ctx is None or ctx.get("rt_src") != "perturbacion+sabine":
            return
        fs = ctx["fs"]
        if hasattr(self, "lbl_schroeder"):
            self.lbl_schroeder.setText(f"f_Schroeder ≈ {fs:.0f} Hz")
        try:
            f_max = self._validity_freq(self.modal_result.mesh_info["h_max"])
        except Exception:
            return
        self._log(
            f"Schroeder (perturbación, post-solve): f_S={fs:.0f} Hz "
            f"({ctx['src_txt']})."
        )
        if fs > f_max * 1.02:
            npm_sug = 6.0 * fs / 343.0
            self._log(
                f"⚠ La malla se dimensionó con el estimador Sabine y es válida "
                f"hasta ~{f_max:.0f} Hz, pero con el T30 por modo f_S sube a "
                f"{fs:.0f} Hz: la banda [{f_max:.0f}, {fs:.0f}] Hz queda "
                f"sub-cubierta. Para cerrarla, subí npm a ~{npm_sug:.1f} y "
                f"volvé a resolver (la 2ª pasada ya usa este f_S)."
            )

    # -----------------------------------------------------------------------
    # Heatmap matplotlib del plano de corte
    # -----------------------------------------------------------------------
    def _compute_current_slice(self):
        """Calcula el FieldSlice actual según los parámetros del panel."""
        if self.modal_result is None:
            return None
        mode_idx = self._current_mode_idx()
        if mode_idx < 0 or mode_idx >= self.modal_result.phis.shape[1]:
            return None
        plane_idx = self.combo_plane.currentIndex()
        axis    = [2, 1, 0][plane_idx]
        offset  = self.sb_slice_z.value()
        res     = self.sb_slice_res.value()
        kind    = self.combo_field.currentIndex()
        damping = self._xi_per_mode if self._xi_per_mode is not None else 0.03
        try:
            if kind == 0:
                return aa.slice_mode_shape_plane(
                    self.modal_result, mode_idx,
                    axis=axis, offset=offset, n1=res, n2=res)
            else:
                act = self._active_sources()
                if len(act) == 0:
                    self._log("Para ver |p|, agregá (o activá) al menos una fuente.")
                    return None
                f = self._effective_freq_of(mode_idx)   # 5c: resonancia efectiva
                return aa.slice_pressure_field_plane(
                    self.modal_result, act, f=f,
                    axis=axis, offset=offset, n1=res, n2=res, damping=damping)
        except Exception as e:
            self._log(f"Error calculando slice: {e}")
            return None

    def _show_slice_heatmap(self):
        """Abre o actualiza la ventana del mapa de calor 2D."""
        if not _HAS_MPL:
            QMessageBox.information(self, "matplotlib",
                                     "Instalar: pip install matplotlib")
            return
        if self.modal_result is None:
            self._log("Calculá los modos (FEM) primero.")
            return
        sl = self._compute_current_slice()
        if sl is None:
            return
        mode_idx = self._current_mode_idx()
        if 0 <= mode_idx < len(self.modal_result.freqs):
            f = self._effective_freq_of(mode_idx)   # 5c: resonancia efectiva
            mode_name = f"Modo {mode_idx}  ({f:.1f} Hz)"
        else:
            mode_name = "—"
        kind = self.combo_field.currentIndex()
        markers = self._slice_markers()
        # Reusar ventana si está abierta; crear nueva si se cerró
        if (self._slice_heatmap_dialog is not None
                and self._slice_heatmap_dialog.isVisible()):
            self._slice_heatmap_dialog.update_slice(sl, mode_name, kind,
                                                    markers=markers)
            self._slice_heatmap_dialog.raise_()
        else:
            self._slice_heatmap_dialog = SliceHeatmapDialog(
                sl, mode_name, kind, markers=markers, parent=self
            )
            self._slice_heatmap_dialog.show()

    def _slice_markers(self):
        """Marcadores para el heatmap 2D (v2.16): fuentes ACTIVAS (con su
        label) + puntos de escucha nombrados + el receptor actual (si no
        coincide ya con un punto de la lista)."""
        srcs = [(s.label or f"S{i+1}", tuple(s.position))
                for i, s in enumerate(self._active_sources())]
        rcvs = [(p["name"], tuple(p["position"]))
                for p in self.listen_points]
        try:
            r = np.asarray(self.receiver, dtype=float)
            if not any(np.linalg.norm(r - np.asarray(p, float)) < 0.01
                       for _n, p in rcvs):
                rcvs.append(("Receptor", tuple(float(x) for x in r)))
        except Exception:
            pass
        return {"sources": srcs, "receivers": rcvs}

    # -----------------------------------------------------------------------
    # Plano de corte interactivo
    # -----------------------------------------------------------------------
    def _on_activate_plane_toggled(self, checked: bool):
        """Activa o cancela el modo de colocacion interactiva del plano."""
        if checked:
            if self.modal_result is None:
                self._log("Calculá los modos (FEM) antes de activar el plano.")
                self.btn_activate_plane.blockSignals(True)
                self.btn_activate_plane.setChecked(False)
                self.btn_activate_plane.blockSignals(False)
                return
            plane_idx = self.combo_plane.currentIndex()
            axis      = [2, 1, 0][plane_idx]
            aabb_min  = self.modal_result.nodes.min(axis=0)
            aabb_max  = self.modal_result.nodes.max(axis=0)
            self.viewer.start_slice_placement(axis, aabb_min, aabb_max)
            self.btn_activate_plane.setText("⊙  Cancelar plano  (o click derecho)")
            self._log("Mové el cursor sobre el recinto. "
                      "Click izquierdo = confirmar.  Click derecho = cancelar.")
        else:
            if hasattr(self.viewer, 'stop_slice_placement'):
                self.viewer.stop_slice_placement()
            self.btn_activate_plane.setText("⊕  Activar plano interactivo")

    def _on_slice_hovered(self, axis: int, offset: float):
        """Actualiza el spinbox mientras el plano sigue el cursor (sin recompute)."""
        self.sb_slice_z.blockSignals(True)
        self.sb_slice_z.setValue(round(offset, 2))
        self.sb_slice_z.blockSignals(False)

    def _on_slice_confirmed(self, axis: int, offset: float):
        """Confirma la posicion del plano y calcula el slice."""
        # Sincronizar combo_plane con el eje confirmado
        _ax_to_plane = {2: 0, 1: 1, 0: 2}
        plane_idx = _ax_to_plane[axis]
        self.combo_plane.blockSignals(True)
        self.combo_plane.setCurrentIndex(plane_idx)
        self.combo_plane.blockSignals(False)
        labels = ["Posición  z:", "Posición  y:", "Posición  x:"]
        self.lbl_slice_offset.setText(labels[plane_idx])
        self.sb_slice_z.setValue(round(offset, 2))
        # Desactivar botón toggle
        self.btn_activate_plane.blockSignals(True)
        self.btn_activate_plane.setChecked(False)
        self.btn_activate_plane.setText("⊕  Activar plano interactivo")
        self.btn_activate_plane.blockSignals(False)
        names = ["XY", "XZ", "YZ"]
        self._log(f"Plano {names[plane_idx]} confirmado en {offset:.2f} m — calculando...")
        self._update_slice()
        self._show_slice_heatmap()

    def _reload_materials(self):
        """Recarga los archivos JSON de la carpeta materials/."""
        folder = str(Path(__file__).parent / "materials")
        self._mat_lib = MaterialLibrary(folder)
        n = len(self._mat_lib)
        # Validar que los nombres del map siguen existiendo; los huerfanos
        # quedan pero como no estan en self._mat_lib seran tratados como α=0.03.
        self._refresh_materials_summary()
        self._log(f"Materiales recargados: {n} materiales disponibles.")

    # ------------------------------------------------------------------
    # Asignacion de materiales por grupo (nuevo sistema, estilo EASE)
    # ------------------------------------------------------------------
    def _get_face_groups(self):
        """Devuelve la lista de FaceGroup de la geometria actual, cacheada.

        Se invalida automaticamente cuando cambia la malla (id(verts) o
        len(tris)). Asi evitamos re-agrupar en cada apertura del dialogo si
        la geometria no se toco.
        """
        verts, tris = self.get_surface()
        cache_key = (id(verts), int(len(tris)))
        if (self._face_groups_cache is not None and
                self._face_groups_for_verts_id == cache_key):
            return self._face_groups_cache, verts, tris
        self._face_groups_cache = fm.group_faces_by_planar_region(verts, tris)
        self._face_groups_for_verts_id = cache_key
        return self._face_groups_cache, verts, tris

    def _open_materials_dialog(self):
        """Abre la ventana de asignacion de materiales por grupo de caras.

        El FaceMaterialMap del panel se pasa por referencia: cualquier cambio
        que el usuario haga se persiste automaticamente (no hace falta confirmar
        OK).  Al cerrar (OK o Cancel) actualizamos el resumen y el xi.
        """
        try:
            groups, verts, tris = self._get_face_groups()
        except Exception as e:
            self._log(f"Error agrupando caras: {e}")
            return
        if not groups:
            self._log("No hay caras para asignar materiales.")
            return
        try:
            V = aa.compute_mesh_volume(verts, tris)
        except Exception:
            V = 0.0
        dlg = fm.MaterialsDialog(
            groups=groups,
            material_library=self._mat_lib,
            face_mat_map=self._face_mat_map,
            volume=V,
            patches=self._patches,
            construction_keys=self._construction_keys(),
            parent=self,
        )
        # Conectar la senal applied para refrescar el panel en vivo
        dlg.applied.connect(self._on_face_materials_applied)
        # Si el usuario carga un material propio, refrescar resumen + xi (el
        # catalogo se recargo en el sitio, misma instancia de MaterialLibrary).
        dlg.materialsReloaded.connect(self._on_face_materials_applied)
        # Cambiar el material de un parche desde la tabla -> recolorear el overlay
        # en vivo (el xi se recomputa al aplicar/cerrar via _on_face_materials_applied).
        dlg.patchesChanged.connect(self._refresh_patch_overlay)
        # Hover sobre una fila -> resaltar la cara O el parche en el 3D.
        dlg.hovered.connect(self._on_materials_hovered)
        dlg.exec_()
        self._on_materials_hovered(None)   # apagar resaltados por las dudas
        # Tras cerrar (OK o Cancel) refrescamos el resumen porque el mapa
        # se actualiza en vivo desde el combo. Si el usuario cancelo, los
        # cambios se mantienen igual (decisión explícita: 'auto-save' como
        # pidió el usuario).
        self._on_face_materials_applied()

    # ------------------------------------------------------------------
    # Parches de absorcion sub-cara (v8)
    # ------------------------------------------------------------------
    def _open_patches_dialog(self):
        """Abre el editor 2D de parches de absorcion por cara."""
        try:
            groups, verts, tris = self._get_face_groups()
        except Exception as e:
            self._log(f"Error agrupando caras: {e}")
            return
        if not groups:
            self._log("No hay caras para dibujar parches.")
            return
        import patch_dialog as pdlg
        dlg = pdlg.PatchEditorDialog(
            groups=groups, verts=verts, tris=tris,
            mat_lib=self._mat_lib, patches=self._patches, parent=self)
        dlg.applied.connect(lambda: self._on_patches_applied(dlg.result_patches))
        # Preview 3D en vivo mientras se edita (sin recomputar la fisica).
        dlg.changed.connect(self._refresh_patch_overlay)
        ok = dlg.exec_()
        if ok:
            self._on_patches_applied(dlg.result_patches)
        else:
            # Cancelado: descartar el preview y volver al overlay de los parches reales.
            self._refresh_patch_overlay()

    def _on_patches_applied(self, patches):
        """Adopta la lista de parches editada y recomputa xi/RT."""
        self._patches = list(patches or [])
        # Exclusion mutua geometrica: un parche nuevo dibujado sobre una cara con
        # construccion crea un doble-spec; resolver antes de recomputar.
        self._resolve_patch_finish_conflicts(interactive=True)
        self._refresh_patches_summary()
        self._refresh_abs_choice_label()   # los parches tambien mueven el RT
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
        self._update_modal_crossover()

    # ------------------------------------------------------------------
    # Construcciones de pared (Capa 0, Etapa 5b)
    # ------------------------------------------------------------------
    def _open_constructions_dialog(self):
        """Abre el asignador de construcciones de pared (impedancia Z por cara)."""
        try:
            groups, _v, _t = self._get_face_groups()
        except Exception as e:
            self._log(f"Error agrupando caras: {e}")
            return
        if not groups:
            self._log("No hay caras para asignar construcciones.")
            return
        dlg = WallConstructionsDialog(
            groups, self._construction_map, parent=self,
            patches=self._patches, furniture=getattr(self, "furniture", None),
            auto_tags=self._material_auto_tags(groups))
        if dlg.exec_():
            self._on_constructions_applied(dlg.result_map)

    def _on_auto_reactance_toggled(self, checked):
        """Prende/apaga la reactancia auto del material (opt-in). Recomputa xi y el
        corrimiento y refresca el picker de modos. Amortiguamiento no cambia."""
        self._auto_material_reactance = bool(checked)
        estado = "ENCENDIDA (modelo no medido)" if checked else "apagada (β real)"
        self._log(f"Reactancia auto por material: {estado}.")
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
            self._refresh_modes_combo()
            self._update_mode_readout()

    def _on_constructions_applied(self, cmap):
        """Adopta el mapa de construcciones y recomputa xi (y el corrimiento)."""
        self._construction_map = dict(cmap or {})
        # Exclusion mutua geometrica: si alguna cara con construccion tiene
        # parches encima, resolver el doble-spec antes de calcular.
        self._resolve_patch_finish_conflicts(interactive=True)
        self._refresh_constructions_summary()
        if self._construction_map and self._damping_model != "perturbation":
            self._log("Aviso: las construcciones de pared solo actúan con el "
                      "modelo de amortiguamiento «Perturbación de frontera».")
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
            # Etapa 5c: al cambiar el corrimiento, repintar el picker (marcador
            # Δfₙ) y el read-out del modo. Repuebla el combo (vuelve al modo 0).
            self._refresh_modes_combo()
        else:
            self._update_modal_crossover()

    def _refresh_constructions_summary(self):
        n = len(self._construction_map)
        if n == 0:
            self.lbl_constr_summary.setText("Sin construcciones")
        else:
            self.lbl_constr_summary.setText(
                f"{n} cara(s) con construcción de pared (impedancia Z; "
                f"amortiguamiento + corrimiento de fₙ)")

    def _patches_blocked_by_furniture(self):
        """Etiquetas de los muebles que tapan algún parche (AABB del prisma del
        parche vs AABB del mueble). Lista vacía = ninguno.

        NO se bloquea: el prisma es dibujo, el α sigue estando sobre la pared, y
        el modelo no se rompe. Pero el aviso tiene contenido acústico REAL: un
        mueble delante de un absorbente lo tapa, así que el α del catálogo (que
        se midió con incidencia libre sobre la muestra) deja de ser el que
        corresponde en esa zona."""
        import numpy as _np
        out = []
        muebles = getattr(self, "furniture", []) or []
        if not muebles or not self._patches:
            return out
        cen = self._room_centroid()
        for p in self._patches:
            pv, _pf = self._patch_quad(p, cen)
            if pv is None:
                continue
            v = _np.asarray(pv, float)
            amin, amax = v.min(axis=0), v.max(axis=0)
            for m in muebles:
                bmin, bmax = self._furniture_aabb(m)
                if self._aabb_overlap(amin, amax, bmin, bmax):
                    lbl = getattr(m, "label", "mueble")
                    if lbl not in out:
                        out.append(lbl)
        return out

    def _refresh_patches_summary(self):
        n = len(self._patches)
        if n == 0:
            self.lbl_patch_summary.setText("Sin parches")
        else:
            area = sum(p.area for p in self._patches)
            txt = (f"{n} parche(s) · {area:.2f} m² · absorción con cuadratura "
                   f"fina activa")
            tapados = self._patches_blocked_by_furniture()
            if tapados:
                nombres = ", ".join(f"«{t}»" for t in tapados[:3])
                if len(tapados) > 3:
                    nombres += f" y {len(tapados)-3} más"
                txt += (f"\n⚠ Se superpone con {nombres}: un mueble delante del "
                        f"absorbente lo tapa, así que su α efectivo va a ser "
                        f"menor que el del catálogo.")
                self._log(f"Aviso: parche(s) tapado(s) por {nombres}.")
            self.lbl_patch_summary.setText(txt)
        self._refresh_patch_overlay()

    def _refresh_patch_overlay(self, patches=None):
        """Pinta los parches como quads sobre las caras en el visor 3D (v8).

        `patches` permite un PREVIEW en vivo (lista del diálogo mientras se
        edita) sin tocar `self._patches`; si es None usa los parches reales."""
        if not hasattr(self.viewer, "set_patches"):
            return
        patches = self._patches if patches is None else patches
        try:
            if not patches:
                self.viewer.set_patches(None)
                return
            import numpy as _np
            import patch_dialog as pdlg
            try:
                _v, _t = self.get_surface()
                centroid = _np.asarray(_v, float).mean(axis=0)
            except Exception:
                centroid = None
            # Un item por parche con COLOR UNIFORME: un GLMeshItem con
            # shader=None + faceColors no renderiza en esta escena (gotcha
            # documentado en acoustic_viewer.SourceMarkers).
            data = []
            for p in patches:
                pv, pf = self._patch_quad(p, centroid)
                if pv is None:
                    continue
                col = pdlg._material_color(p.material_name, alpha=255)
                rgba = (col.red() / 255.0, col.green() / 255.0,
                        col.blue() / 255.0, 0.75)
                edges = self._patch_edge_segments(pv, len(p.polygon_uv()))
                data.append((_np.array(pv), _np.array(pf), rgba, edges))
            self.viewer.set_patches(data or None)
        except Exception as e:
            self._log(f"Aviso overlay parches: {e}")

    @staticmethod
    def _patch_edge_segments(verts, n):
        """Aristas del parche como PARES de puntos para GLLinePlotItem(mode='lines').

        `verts` viene de `_patch_quad`: n puntos si es plano, 2n si es prisma
        (0..n-1 = contorno contra la pared, n..2n-1 = contorno del frente).
        Prisma -> 3n aristas: los dos contornos + los montantes que los unen.
        Sirve para que el parche se lea con CUALQUIER color de relleno."""
        import numpy as _np
        if verts is None or n < 2:
            return None
        v = _np.asarray(verts, dtype=float)
        segs = []
        rings = [0] if len(v) < 2 * n else [0, n]
        for base in rings:                      # contorno(s)
            for i in range(n):
                segs.append(v[base + i])
                segs.append(v[base + (i + 1) % n])
        if len(v) >= 2 * n:                     # montantes del prisma
            for i in range(n):
                segs.append(v[i])
                segs.append(v[i + n])
        return _np.asarray(segs, dtype=_np.float32)

    def _patch_quad(self, p, centroid):
        """Geometria 3D de UN parche: (verts (Nv,3), faces (Nf,3) locales).

        El parche se dibuja como PRISMA (paralelepipedo) de `p.depth` metros de
        espesor hacia el INTERIOR de la sala: la tapa de atras se apoya en la
        pared y la de adelante queda a `depth` del muro, como un panel real.
        Con depth<=0 degenera al quad plano de siempre.

        Triangula el poligono (ear clipping) para soportar no convexos, y arma
        las caras laterales uniendo los dos contornos."""
        import absorption_patch as _ap
        na = p.normal_axis
        # Sentido "hacia adentro" del recinto sobre el eje de la normal.
        sgn = 1.0
        if centroid is not None:
            sgn = 1.0 if centroid[na] >= p.plane_coord else -1.0
        # Separacion minima de la cara: evita quedar coplanar con la pared.
        OFF = 0.004
        depth = float(max(0.0, getattr(p, "depth", 0.0) or 0.0))
        uv = p.polygon_uv()
        tris = _ap.triangulate_uv(uv)
        if not tris:
            return None, None

        def _ring(dist):
            out = []
            for (u, v) in uv:
                c = [0.0, 0.0, 0.0]
                c[na] = p.plane_coord + sgn * dist
                c[p.u_axis] = u
                c[p.v_axis] = v
                out.append(c)
            return out

        if depth <= 1e-6:                       # sin espesor: quad plano (legacy)
            return _ring(OFF), [list(t) for t in tris]

        n = len(uv)
        verts = _ring(OFF) + _ring(OFF + depth)   # 0..n-1 = pared, n..2n-1 = frente
        faces = [list(t) for t in tris]                       # tapa contra la pared
        faces += [[int(a) + n, int(b) + n, int(c) + n] for (a, b, c) in tris]
        for i in range(n):                                     # caras laterales
            j = (i + 1) % n
            faces.append([i, j, j + n])
            faces.append([i, j + n, i + n])
        return verts, faces

    def _room_centroid(self):
        try:
            import numpy as _np
            v, _t = self.get_surface()
            return _np.asarray(v, float).mean(axis=0)
        except Exception:
            return None

    def _on_materials_hovered(self, obj):
        """Hover en la tabla de Materiales: resalta la cara (FaceGroup) o el
        parche (AbsorptionPatch) en el 3D. None = apagar ambos."""
        import numpy as _np
        # Apagar el resaltado de caras salvo que sea justamente una cara.
        is_group = obj is not None and hasattr(obj, "face_indices")
        is_patch = obj is not None and hasattr(obj, "polygon_uv")
        if hasattr(self.viewer, "set_highlight_faces"):
            self.viewer.set_highlight_faces(obj.face_indices if is_group else None)
        if hasattr(self.viewer, "set_highlight_patch"):
            if is_patch:
                pv, pf = self._patch_quad(obj, self._room_centroid())
                if pv is not None:
                    self.viewer.set_highlight_patch(_np.array(pv), _np.array(pf))
                else:
                    self.viewer.set_highlight_patch(None)
            else:
                self.viewer.set_highlight_patch(None)

    def _patch_to_material_dict(self):
        """Construye {patch.key: Material} usando el catalogo actual."""
        names = self._mat_lib.names
        d = {}
        for p in self._patches:
            if p.material_name in names:
                d[p.key] = self._mat_lib[names.index(p.material_name)]
        return d

    def _furniture_mat_by_index(self):
        """Construye {indice_mueble: Material} desde self._furniture_mat_names.

        Un mueble sin material asignado NO aparece en el dict -> los canales de
        absorcion/SBIR lo tratan como RIGIDO (alpha default 0.03), que es el
        default fisico correcto. Vacio -> {} -> todos los muebles rigidos.

        TODO (test visual en PC): el dialogo de muebles debe poblar
        self._furniture_mat_names {indice: nombre_material} al asignar material a
        un mueble; aca solo se resuelve el nombre contra el catalogo actual.
        """
        names = self._mat_lib.names
        d = {}
        for i in range(len(self.furniture)):
            nm = self._furniture_mat_names.get(i)
            if nm and nm in names:
                d[i] = self._mat_lib[names.index(nm)]
        return d

    def _on_damping_model_changed(self):
        """Cambió el modelo de amortiguamiento (Sabine A36 <-> perturbación).

        Recalcula ξ si ya hay modos y refresca lo que cuelga de él (FRF/FoM se
        recomputan al reabrir; acá se rehace el ξ vivo). El cruce modal usa el
        RT de Sabine, así que NO cambia con esto (eso es la Etapa 2: rutear los
        consumidores escalares por el modelo elegido)."""
        self._damping_model = (self.combo_damping.currentData()
                               if hasattr(self, "combo_damping") else "a36")
        self._warned_pert_patches = False
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
            nice = ("perturbación de frontera"
                    if self._damping_model == "perturbation" else "Sabine (A36)")
            self._log(f"Amortiguamiento: modelo → {nice}. ξ recalculado; "
                      f"recalculá la FRF para ver el efecto.")
            # Etapa 2a: el RT60 efectivo (label + f_cross) depende del modelo;
            # refrescar para que el cambio se vea sin re-tocar los materiales.
            self._refresh_materials_summary()
            # Etapa 5c: el corrimiento existe solo en perturbación+construcciones;
            # al togglear el modelo aparece/desaparece → repintar picker + read-out
            # (esto ya refresca el cruce modal). Vuelve al modo 0.
            self._refresh_modes_combo()

    def _on_face_materials_applied(self):
        """Refresca el resumen y recomputa xi tras editar materiales."""
        # Recalcular xi PRIMERO si los modos ya estaban resueltos: el label RT60
        # medio (Etapa 2a) lo lee para el T30 de la perturbacion; si se refresca
        # antes, el label muestra el xi de la asignacion anterior (un refresh de
        # atraso).
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
            # Etapa 5c + Z por default: cambió ξ Y el corrimiento Δfₙ (ahora los
            # materiales porosos aportan reactancia, no solo las construcciones).
            # Repuebla el combo (marcador Δfₙ por modo) y el read-out.
            self._refresh_modes_combo()
            self._update_mode_readout()
        self._refresh_materials_summary()
        # De donde sale la absorcion pudo cambiar (el usuario reasigno caras):
        # el label tiene que seguirlo o queda mintiendo sobre el f_S mostrado.
        self._refresh_abs_choice_label()
        # El material de un parche pudo cambiar desde la tabla -> recolorear overlay.
        self._refresh_patch_overlay()
        # El RT60 cambio -> B_HP cambia -> refrescar el cruce modal numerico.
        self._update_modal_crossover()
        # B27: aviso de colocacion de absorbente para control modal LF (poroso
        # ineficaz en pared/esquina; usar resonante o poroso+camara). No bloquea.
        self._emit_lf_absorption_hints()

    def apply_zone_materials(self, floor_name, walls_name, ceiling_name) -> bool:
        """Asigna 3 materiales por zona (piso/paredes/techo) a las caras del
        recinto — mismo esquema que el 'Preset piso/techo/paredes' del diálogo.
        Lo usa 'Aplicar a Acústica' desde el gate de materiales de Predicción.
        Devuelve True si asignó algo."""
        try:
            groups, _v, _t = self._get_face_groups()
        except Exception as e:
            self._log(f"No se pudieron aplicar materiales: {e}")
            return False
        if not groups:
            self._log("No hay caras para asignar materiales.")
            return False
        for g in groups:
            if g.kind == "floor":
                self._face_mat_map.assign(g.signature, floor_name)
            elif g.kind == "ceiling":
                self._face_mat_map.assign(g.signature, ceiling_name)
            else:                                  # wall / tilted
                self._face_mat_map.assign(g.signature, walls_name)
        self._on_face_materials_applied()          # refresca resumen + xi + cruce
        return True

    def _emit_lf_absorption_hints(self):
        """Loguea avisos B27 si el tratamiento poroso no sirve para los modos LF.

        Best-effort: solo informa, nunca rompe el flujo de materiales.
        """
        try:
            groups, _v, _t = self._get_face_groups()
            if not groups:
                return
            g2m = self._group_to_material_dict(groups)
            f_low = None
            if (self.modal_result is not None
                    and len(self.modal_result.freqs) > 0):
                f_low = float(self.modal_result.freqs[0])
            for hint in fm.lf_modal_absorption_hints(groups, g2m, f_low):
                self._log(hint)
        except Exception:
            pass

    def _refresh_materials_summary(self):
        """Actualiza self.lbl_mat_summary y self.lbl_rt60 segun el estado."""
        try:
            groups, verts, tris = self._get_face_groups()
            if not groups:
                self.lbl_mat_summary.setText("Sin geometria.")
                self.lbl_rt60.setText("RT60 medio: — s")
                return
            n_assigned = sum(1 for g in groups
                              if self._face_mat_map.get(g.signature))
            n_total = len(groups)
            zones = fm.summarize_zone_areas(groups)
            zones_txt = (f"Piso {zones.get('floor',0):.0f} · "
                          f"Techo {zones.get('ceiling',0):.0f} · "
                          f"Paredes {zones.get('wall',0):.0f}")
            if zones.get("tilted", 0.0) > 0:
                zones_txt += f" · Inclin. {zones['tilted']:.0f}"
            self.lbl_mat_summary.setText(
                f"{n_total} grupos · {n_assigned} con material   ({zones_txt} m²)"
            )
            # Opción C (v2.24): sin absorción elegida, el RT60 no se muestra
            # (no salir de un default silencioso).
            if not self._has_absorption_choice():
                self.lbl_rt60.setText("RT60 medio: — (asigná absorción)")
                return
            # RT60 medio (Etapa 2a: efectivo por modelo de amortiguamiento).
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
            rt, rt_src = self._effective_rt60_by_band(V, groups, g2m)
            rt_avg = float(np.mean(list(rt.values()))) if rt else 0.0
            rt500 = rt.get(500, 0.0)
            # D5: Bass Ratio (calidez por reverberacion). Solo si hay materiales
            # asignados (con el rigido default BR=1 trivial, no informa).
            br = fm.bass_ratio(rt) if rt else float("nan")
            br_txt = ""
            if np.isfinite(br):
                if br < 1.0:
                    cal = "fría/seca"
                elif br <= 1.45:
                    cal = "cálida ✓"
                else:
                    cal = "boomy"
                br_txt = f"   ·   BR: {br:.2f} ({cal})"
            src_txt = ("   ·   T30 perturbación (banda modal)"
                       if rt_src == "perturbacion+sabine" else "")
            self.lbl_rt60.setText(
                f"RT60 medio: {rt_avg:.2f} s   ·   @500 Hz: {rt500:.2f} s"
                f"{br_txt}   (V={V:.1f} m³){src_txt}"
            )
        except Exception as e:
            self.lbl_mat_summary.setText(f"(error: {e})")
            self.lbl_rt60.setText("RT60 medio: — s")

    def _group_to_material_dict(self, groups):
        """Construye {signature: Material} usando el FaceMaterialMap actual."""
        names = self._mat_lib.names
        g2m = {}
        for g in groups:
            name = self._face_mat_map.get(g.signature)
            if not name:
                continue
            if name in names:
                g2m[g.signature] = self._mat_lib[names.index(name)]
        return g2m

    @staticmethod
    def _material_surface(mat, with_reactance: bool = False):
        """SurfaceImpedance por DEFAULT del material.

        Re(beta) = beta_from_alpha_random(alpha_cat(f)) EXACTO -> preserva la
        absorcion medida, mismo amortiguamiento que el modelo alpha->beta de
        siempre (sin regresion, para TODO material). Este es SIEMPRE el default.

        `with_reactance=True` (OPT-IN, apagado por default desde la auditoria
        2026-09-04): ADEMAS injerta Im(beta) desde un poroso semi-infinito de Miki
        con sigma ajustada al alpha, si el material es poroso-compatible. Esa
        reactancia es MODELO NO MEDIDO y Miki queda extrapolado ~10-40x por debajo
        de su rango (X<0.01) en la banda modal: corre f_n hasta ~9% en salas muy
        tratadas, sin respaldo de medicion. Por eso NO va por default; es una
        hipotesis a validar contra RIRs (ver validation_protocol.md, hallazgo M1).
        Las construcciones EXPLICITAS (panel perforado, membrana, poroso+camara)
        siguen aportando reactancia siempre: esas son modelos elegidos, no
        extrapolados del alpha.

        Convencion: Z en e^{-iwt} (nativa de impedance.py); el downstream hace
        conj(Z0/Z) y hereda el signo de la reactancia de Miki."""
        if hasattr(mat, "alpha_bands"):
            bands = mat.alpha_bands()                     # {banda: alpha}
            fbands = np.array(sorted(bands), dtype=float)
            acat = np.array([bands[int(b)] for b in fbands], dtype=float)
        else:                                             # material sin tabla (fakes/muebles)
            fbands = np.array([63, 125, 250, 500, 1000, 2000, 4000, 8000], float)
            acat = np.array([float(mat.alpha(float(b))) for b in fbands], float)
        porous = False
        sigma = None
        if with_reactance:
            sigma, resid, porous = imp.sigma_from_alpha(acat, fbands)

        def zf(f, theta=0.0):
            f = np.atleast_1d(np.asarray(f, dtype=float))
            a = np.array([float(mat.alpha(float(ff))) for ff in f])
            beta_re = fm.beta_from_alpha_random(a)       # exacto (real, e^{-iwt})
            if porous:
                zc, _ = imp.miki_zc_kc(f, sigma)
                beta = beta_re + 1j * np.imag(imp.Z0 / zc)  # + reactancia Miki (opt-in)
            else:
                beta = beta_re.astype(complex)
            beta = np.where(np.abs(beta) < 1e-12, 1e-12 + 0j, beta)
            return imp.Z0 / beta

        lbl = getattr(mat, "name", "material")
        if porous:
            lbl += f" [Z auto σ={sigma:.0f}]"
        return imp.SurfaceImpedance(zf, is_locally_reacting=True, label=lbl)

    @staticmethod
    def _material_ztag(mat, with_reactance: bool = False) -> str:
        """Texto corto de la Z por default de un material (para el panel de
        construcciones). Con la reactancia auto APAGADA (default), toda cara sin
        construccion usa beta real (solo amortiguamiento). Con la reactancia auto
        encendida (opt-in), los porosos muestran su sigma equivalente."""
        name = getattr(mat, "name", "material")
        if not with_reactance:
            return f"{name} · β real (α, sin reactancia)"
        try:
            if hasattr(mat, "alpha_bands"):
                bands = mat.alpha_bands()
                fb = np.array(sorted(bands), dtype=float)
                ac = np.array([bands[int(b)] for b in fb], dtype=float)
            else:
                fb = np.array([63, 125, 250, 500, 1000, 2000, 4000, 8000], float)
                ac = np.array([float(mat.alpha(float(b))) for b in fb], float)
            sigma, _resid, porous = imp.sigma_from_alpha(ac, fb)
        except Exception:
            sigma, porous = None, False
        if porous and sigma is not None:
            return (f"{name} · Z auto (poroso equiv., "
                    f"resistividad σ≈{sigma:.2g} Pa·s/m²)")
        return f"{name} · β real (α, sin reactancia)"

    def _material_auto_tags(self, groups):
        """{clave -> texto de Z-auto} para caras (por grupo) y parches, segun su
        material actual. Lo consume WallConstructionsDialog para mostrar la Z por
        default read-only en las superficies sin construccion explicita."""
        wr = getattr(self, "_auto_material_reactance", False)
        tags = {}
        g2m = self._group_to_material_dict(groups)
        for g in groups:
            mat = g2m.get(g.signature)
            if mat is not None:
                tags[g.signature] = self._material_ztag(mat, wr)
        p2m = self._patch_to_material_dict() if self._patches else {}
        for p in (self._patches or []):
            mat = p2m.get(p.key)
            if mat is not None:
                tags[p.key] = self._material_ztag(mat, wr)
        return tags

    def _construction_keys(self):
        """Claves (firma de cara / patch.key / __furniture_i__) que YA tienen una
        construccion-Z. La UI de materiales las bloquea (un acabado por region)."""
        return set(self._construction_map.keys())

    def _patch_finish_conflicts(self):
        """Exclusion mutua GEOMETRICA: parches cuyo material-alpha pisa la
        construccion-Z de su cara anfitriona. Un parche dibujado sobre una cara
        con construccion sobrescribe esa impedancia en su huella = doble spec
        sobre la misma region fisica. Un parche que YA tiene su propia
        construccion NO entra (esa es su terminacion, no hay contradiccion).
        Devuelve la lista de parches en conflicto."""
        cmap = self._construction_map
        if not cmap or not self._patches:
            return []
        return [p for p in self._patches
                if getattr(p, "face_signature", None) in cmap
                and getattr(p, "key", None) not in cmap]

    def _resolve_patch_finish_conflicts(self, interactive=True):
        """Resuelve el conflicto parche-alpha vs cara-construccion. Ofrece
        heredar la construccion de la cara al parche (misma Z, sin override) o
        mantener el material del parche (override local explicito). Sin GUI
        (tests) hereda por defecto (coherente: un acabado por region).
        Devuelve True si modifico `_construction_map`."""
        conflicts = self._patch_finish_conflicts()
        if not conflicts:
            return False
        if not interactive:
            for p in conflicts:
                self._construction_map[p.key] = dict(
                    self._construction_map[p.face_signature])
            return True
        n = len(conflicts)
        box = QMessageBox(self)
        box.setWindowTitle("Parche sobre una construcción")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f"{n} parche(s) están sobre una cara con construcción de pared.\n\n"
            f"El material (α) del parche sobrescribe la impedancia de la "
            f"construcción en esa zona: son dos definiciones sobre la misma "
            f"superficie. ¿Qué hago?")
        b_inherit = box.addButton("Heredar la construcción al parche",
                                  QMessageBox.AcceptRole)
        box.addButton("Mantener el material del parche", QMessageBox.RejectRole)
        box.setDefaultButton(b_inherit)
        box.exec_()
        if box.clickedButton() is b_inherit:
            for p in conflicts:
                self._construction_map[p.key] = dict(
                    self._construction_map[p.face_signature])
            self._log(f"{n} parche(s) heredaron la construcción de su cara.")
            return True
        self._log(f"{n} parche(s) mantienen su material "
                  f"(override local de la construcción).")
        return False

    def _construction_surfaces(self, groups, g2m):
        """Superficies de Capa 0 por GRUPO y por PARCHE para la perturbacion
        compleja unificada. Para cada superficie (cara, parche o mueble):
          - con construccion asignada (en _construction_map) -> SurfaceImpedance.
          - sin construccion pero con material -> resistiva del alpha(f) (beta
            real, sin corrimiento) = camino alpha->beta de siempre.
        La reactancia auto del material es OPT-IN (self._auto_material_reactance,
        default OFF desde la auditoria 2026-09-04, hallazgo M1): con OFF las caras
        sin construccion usan beta real (solo amortiguamiento, sin corrimiento).
        Las construcciones explicitas SIEMPRE aportan su reactancia.
        Claves: firma de grupo (paredes + muebles __furniture_i__) y patch.key.
        Devuelve (surf_by_group, surf_by_patch)."""
        wr = getattr(self, "_auto_material_reactance", False)
        surf_g = {}
        for g in groups:
            spec = self._construction_map.get(g.signature)
            if spec:
                try:
                    surf_g[g.signature] = imp.build_surface(spec)
                    continue
                except Exception as e:
                    self._log(f"Construccion invalida ({g.signature[:8]}): {e}")
            mat = g2m.get(g.signature)
            if mat is not None:
                surf_g[g.signature] = self._material_surface(mat, wr)
        surf_p = {}
        p2m = self._patch_to_material_dict() if self._patches else {}
        for p in (self._patches or []):
            spec = self._construction_map.get(p.key)
            if spec:
                try:
                    surf_p[p.key] = imp.build_surface(spec)
                    continue
                except Exception as e:
                    self._log(f"Construccion de parche invalida: {e}")
            mat = p2m.get(p.key)
            if mat is not None:
                surf_p[p.key] = self._material_surface(mat, wr)
        return surf_g, surf_p

    def _effective_modal_freqs(self):
        """Frecuencias de RESONANCIA para la dinamica (FRF/campo/FoM): las corridas
        por Capa 0 (Im(beta)) si hay construcciones, si no las rigidas. La FORMA
        modal no cambia (perturbacion de 1er orden, D3)."""
        if self.modal_result is None:
            return None
        fs = self._freq_shift_per_mode
        if fs is not None and len(fs) == len(self.modal_result.freqs):
            return np.asarray(fs, dtype=float)
        return self.modal_result.freqs

    def _effective_freq_of(self, mode_idx: int) -> float:
        """Frecuencia EFECTIVA (corrida por Capa 0) del modo, con fallback a la
        rigida. La usan el campo |p| (slice/heatmap) y su etiqueta, para que la
        presion se evalue a la resonancia REAL, igual que la FRF (Etapa 5c)."""
        fe = self._effective_modal_freqs()
        if fe is not None and 0 <= mode_idx < len(fe):
            return float(fe[mode_idx])
        return float(self.modal_result.freqs[mode_idx])

    def _collect_mode_table(self):
        """Datos por modo para la tabla/read-out de la Etapa 5c (Capa 0 visible).

        Devuelve dict con f_rig, f_eff, dfreq, xi (np.ndarray) del MODELO ACTIVO,
        mas metadatos legibles. Si el amortiguamiento no esta cacheado lo calcula
        una vez (side-effect: puebla `_freq_shift_per_mode`, que es lo que hace
        visible el corrimiento). Devuelve None sin modos.
        """
        if self.modal_result is None:
            return None
        f_rig = np.asarray(self.modal_result.freqs, dtype=float)
        if self._xi_per_mode is None:
            # Poblar xi (y de paso el corrimiento) para el modelo activo.
            self._xi_per_mode = self._compute_xi_from_materials()
        f_eff = self._effective_modal_freqs()
        f_eff = f_rig if f_eff is None else np.asarray(f_eff, dtype=float)
        if f_eff.shape != f_rig.shape:
            f_eff = f_rig
        xi = self._xi_per_mode
        if xi is not None:
            xi = np.asarray(xi, dtype=float)
            if xi.shape != f_rig.shape:
                xi = None
        model = ("Perturbación de frontera"
                 if self._damping_model == "perturbation"
                 else "Sabine por modo (A36)")
        return {
            "f_rig": f_rig, "f_eff": f_eff, "dfreq": f_eff - f_rig, "xi": xi,
            "model": model, "constructions": bool(self._construction_map),
            "max_abs_shift": float(np.max(np.abs(f_eff - f_rig)))
                             if f_rig.size else 0.0,
        }

    def _show_mode_table(self):
        """Abre la tabla por modo (Etapa 5c): Δfₙ + ξₙ explicitos."""
        if not self._ensure_modes_computed():
            return
        data = self._collect_mode_table()
        if data is None:
            QMessageBox.information(self, "Sin modos",
                                     "Calculá los modos primero.")
            return
        ModeTableDialog(data, parent=self).exec_()

    def _update_mode_readout(self):
        """Read-out compacto del modo seleccionado: fₙ rígida → efectiva (Δfₙ),
        ξₙ y RT60ₙ. Barato: usa las caches vivas, NO recalcula la perturbación."""
        if not hasattr(self, "lbl_mode_shift"):
            return
        mr = self.modal_result
        if mr is None:
            self.lbl_mode_shift.setText("")
            return
        i = self._current_mode_idx()
        f_rig = np.asarray(mr.freqs, dtype=float)
        if i < 0 or i >= f_rig.size:
            self.lbl_mode_shift.setText("")
            return
        f0 = float(f_rig[i])
        f_eff = self._effective_modal_freqs()
        f1 = f0 if f_eff is None or len(f_eff) != f_rig.size else float(f_eff[i])
        df = f1 - f0
        parts = []
        if abs(df) >= 5e-3:
            parts.append(f"fₙ {f0:.2f} → <b>{f1:.2f}</b> Hz "
                         f"(Δfₙ = {df:+.2f} Hz)")
        else:
            parts.append(f"fₙ = {f0:.2f} Hz (sin corrimiento)")
        xi = self._xi_per_mode
        if xi is not None and len(xi) == f_rig.size:
            xv = float(xi[i])
            d = xv * 2.0 * np.pi * f1
            rt = 6.908 / d if d > 1e-12 else float("inf")
            rt_txt = "∞" if not np.isfinite(rt) else f"{rt:.2f} s"
            parts.append(f"ξₙ = {xv:.5f} · RT60ₙ ≈ {rt_txt}")
        self.lbl_mode_shift.setText(" · ".join(parts))

    def _compute_xi_from_materials(self, model=None):
        """Calcula xi_n por modo usando el mapeo POR CARA (FaceMaterialMap).

        Si no hay asignaciones (mapa vacio), todos los grupos contribuyen con
        alpha=0.03 (default rigido conservador) — el resultado es equivalente
        a una sala de hormigon sin tratar.

        `model` fuerza el modelo de amortiguamiento ("a36"|"perturbation"); por
        defecto usa `self._damping_model`. Sirve para pedir el xi de perturbacion
        sin tocar el toggle (comparacion en el diagrama Ver-RT60).
        """
        if self.modal_result is None:
            return None
        model = model or self._damping_model
        # Sin construcciones la dinamica usa las f_n rigidas: se limpia el cache de
        # corrimiento salvo que el camino de Capa 0 lo pueble abajo.
        self._freq_shift_per_mode = None
        try:
            groups, verts, tris = self._get_face_groups()
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
            # Absorcion de muebles (Fase C): las caras de la interfaz aire-mueble
            # entran como FaceGroups nuevos al MISMO A36 que las paredes. Se
            # extraen de la malla ORIGINAL (sin tallar) preservada en el solve;
            # el locator y los modos van sobre la tallada. Compone con parches:
            # se AGREGAN caras al final (no renumera las existentes), asi los
            # parches por signature siguen resolviendo. Sin muebles no toca nada
            # -> los .room sin muebles no cambian ni un digito.
            muebles = getattr(self, "furniture", None)
            nodes0 = getattr(self.modal_result, "nodes0", None)
            tets0 = getattr(self.modal_result, "tets0", None)
            if muebles and nodes0 is not None and tets0 is not None:
                import furniture as fu
                verts, tris, groups, g2m = fu.augment_surface_with_furniture(
                    verts, tris, groups, g2m, nodes0, tets0, muebles,
                    self._furniture_mat_by_index())
                # V del A36 = volumen de AIRE (el mueble se tallo del dominio);
                # normalizacion modal consistente con la malla resuelta.
                ci = getattr(self.modal_result, "carve_info", None)
                if ci is not None:
                    V = max(V - float(ci.get("V_removed_mesh", 0.0)), 1e-9)
            # Capa 0 (Etapa 5): perturbacion COMPLEJA unificada. SIEMPRE que el
            # modelo sea perturbacion se computa el CORRIMIENTO de f_n desde las
            # superficies: ahora cada MATERIAL trae su Z por default
            # (_material_surface: Re(beta) EXACTO del alpha + Im(beta) de un poroso
            # equivalente si es poroso-compatible), asi el corrimiento reactivo
            # aparece SIN construccion manual (pedido del usuario). Camino UNIFICADO
            # con el teselado fino de los parches: cada superficie (cara / parche /
            # mueble) usa su construccion, o cae a su material. Muebles ya en
            # `groups` (augment); parches como sub-slots. Incidencia normal.
            #  - CON construcciones -> el xi COMPLEJO manda (como antes).
            #  - SOLO materiales -> se guarda el corrimiento (Im de la Z default),
            #    pero el AMORTIGUAMIENTO sigue por el camino establecido (A36 crudo/
            #    parches) para NO regresionar xi (Re(beta) es identico en ambos).
            if model == "perturbation":
                import absorption_patch as ap
                surf_g, surf_p = self._construction_surfaces(groups, g2m)
                res = ap.compute_xi_shift_with_impedance(
                    self.modal_result.freqs, self.modal_result.phis,
                    self.modal_result.locator, verts, tris, groups, surf_g,
                    self._patches, surf_p, V, default_surf=None)
                if res is not None:
                    xi_c, f_new = res
                    self._freq_shift_per_mode = np.asarray(f_new, dtype=float)
                    if self._construction_map:
                        return xi_c
                # solo-materiales: amortiguamiento por el camino establecido
                if self._patches:
                    xi = ap.compute_xi_per_mode_with_patches(
                        self.modal_result.freqs, self.modal_result.phis,
                        self.modal_result.locator, verts, tris, groups, g2m,
                        self._patches, self._patch_to_material_dict(), V,
                        model="perturbation")
                    if xi is not None:
                        return xi
                else:
                    xi = fm.perturbation_xi_per_mode(
                        self.modal_result.freqs, self.modal_result.phis,
                        self.modal_result.locator, verts, tris, groups, g2m, V)
                    if xi is not None:
                        return xi
            # Parches sub-cara (v8): si hay al menos uno, la absorcion se integra
            # con cuadratura FINA (A36 refinado). Baseline sin parches queda en
            # A36 crudo -> los .room sin parches no cambian ni un digito.
            if self._patches:
                import absorption_patch as ap
                xi = ap.compute_xi_per_mode_with_patches(
                    self.modal_result.freqs, self.modal_result.phis,
                    self.modal_result.locator, verts, tris, groups, g2m,
                    self._patches, self._patch_to_material_dict(), V)
                if xi is not None:
                    return xi
            # A36: xi por modo pesado por la forma modal en cada cara (captura
            # el amortiguamiento selectivo segun DONDE esta el tratamiento). Se
            # reduce exacto a la Sabine global si los materiales son uniformes.
            xi = fm.compute_xi_per_mode_per_face(
                self.modal_result.freqs, self.modal_result.phis,
                self.modal_result.locator, verts, tris, groups, g2m, V)
            if xi is not None:
                return xi
            # Fallback: RT60 global por banda (comportamiento previo).
            rt60 = self._sabine_rt60(V, groups, g2m)
            return compute_xi_per_mode(self.modal_result.freqs, rt60)
        except Exception as e:
            self._log(f"Aviso materiales: {e}")
            return None

    def _sabine_rt60(self, V, groups, g2m):
        """RT60 de Sabine por banda, patch-aware: si hay parches, cada uno le
        resta area a su cara anfitriona y aporta su alpha. Sin parches, es la
        Sabine por cara de siempre (baseline intacto)."""
        if self._patches:
            import absorption_patch as ap
            return ap.sabine_rt60_with_patches(
                V, groups, g2m, self._patches, self._patch_to_material_dict())
        return fm.compute_sabine_rt60_per_face(V, groups, g2m)

    def _effective_rt60_by_band(self, V, groups, g2m):
        """RT60 por banda EFECTIVO segun el modelo de amortiguamiento (Etapa 2a).

        UN solo lugar para los consumidores ESCALARES post-solve (label RT60
        medio, f_cross, diagrama Ver-RT60), analogo a como `_schroeder_context`
        unifico el f_S. El f_S/auto-tuner queda FUERA (corre pre-solve, sin
        modos = chicken-egg; es la Etapa 2b).

          - Sabine (default): el {banda: RT60} de Sabine por cara (patch-aware).
            Reduce EXACTO al camino previo -> los .room con modelo Sabine no
            cambian ni un digito.
          - Perturbacion: T30 por banda del decay modal (`rt60_by_band_from_
            modal_decay`) en la banda MODAL (< f_S), y Sabine en las bandas por
            encima del modo mas alto (regimen difuso, donde Sabine SI vale). El
            cruce entre ambos regimenes es justo la frontera fisica.

        Sin modos resueltos (o sin xi) cae a Sabine entero. Usa la cache viva
        `self._xi_per_mode` (no recomputa la perturbacion).

        Devuelve (rt_dict {banda(int): RT60}, src) con src en
        {"sabine", "perturbacion+sabine"}.
        """
        sab = self._sabine_rt60(V, groups, g2m)
        if (self._damping_model != "perturbation"
                or self.modal_result is None):
            return sab, "sabine"
        xi = self._xi_per_mode
        if xi is None:
            return sab, "sabine"
        try:
            import modal_metrics as mm
            f = np.asarray(self.modal_result.freqs, dtype=float)
            xi = np.asarray(xi, dtype=float)
            if xi.size != f.size:
                return sab, "sabine"
            delta = xi * 2.0 * np.pi * f          # tasa de amplitud [Np/s]
            pert = mm.rt60_by_band_from_modal_decay(f, delta)
        except Exception as e:
            self._log(f"RT60 efectivo (perturbación): {e} -> Sabine")
            return sab, "sabine"
        if not pert:
            return sab, "sabine"
        # Blend: perturbacion donde hay modos, Sabine en el resto de las bandas.
        out = dict(sab)
        out.update(pert)
        return out, "perturbacion+sabine"

    def _perturbation_rt60_by_band(self):
        """RT60 T30 por banda de la PERTURBACION, INDEPENDIENTE del toggle de
        modelo (para superponerlo como comparacion en el diagrama Ver-RT60).

        Devuelve {banda(int): RT60} o None si no hay modos. Reusa la cache si el
        modelo activo ya es perturbacion; si no, pide el xi de perturbacion sin
        cambiar el estado (via `_compute_xi_from_materials(model=...)`).
        """
        if self.modal_result is None:
            return None
        if self._damping_model == "perturbation" and self._xi_per_mode is not None:
            xi = self._xi_per_mode
        else:
            xi = self._compute_xi_from_materials(model="perturbation")
        if xi is None:
            return None
        try:
            import modal_metrics as mm
            f = np.asarray(self.modal_result.freqs, dtype=float)
            xi = np.asarray(xi, dtype=float)
            if xi.size != f.size:
                return None
            delta = xi * 2.0 * np.pi * f
            return mm.rt60_by_band_from_modal_decay(f, delta) or None
        except Exception:
            return None

    def _rt60_callable(self):
        """Devuelve un callable f->RT60 [s] (log-interp del RT por banda), o None
        si no hay geometria/RT. Para el cruce modal numerico (2c §9).

        Etapa 2a: con el modelo de perturbacion activo y modos resueltos, el RT
        de la banda modal sale del decay T30 (no de Sabine) -> el B_HP=2.2/RT60
        y por lo tanto f_cross reflejan el amortiguamiento por modo. Con Sabine
        (default) es la log-interp de la Sabine por cara de siempre."""
        try:
            groups, verts, tris = self._get_face_groups()
            if not groups:
                return None
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
            rt, _src = self._effective_rt60_by_band(V, groups, g2m)  # {banda: RT60}
            if not rt:
                return None
            bands = np.array(sorted(rt.keys()), dtype=float)
            vals = np.array([rt[int(b)] for b in bands], dtype=float)
            log_b = np.log(bands)

            def fn(f, _lb=log_b, _v=vals):
                return float(np.interp(np.log(max(float(f), 1e-6)), _lb, _v))
            return fn
        except Exception:
            return None

    def _update_modal_crossover(self):
        """Refresca lbl_fcross con el cruce de solapamiento modal numerico (2c §9).

        Best-effort: si no hay modos o falla el calculo, deja un texto-guia y no
        propaga la excepcion (no debe romper el solve ni el filtro de modos).
        """
        if not hasattr(self, "lbl_fcross"):
            return
        if self.modal_result is None or len(self.modal_result.freqs) < 2:
            self.lbl_fcross.setText("f_cross (M≥3, numérico): calculá los modos")
            return
        try:
            import modal_metrics as mm
            rt_fn = self._rt60_callable()
            if rt_fn is None:
                self.lbl_fcross.setText(
                    "f_cross (M≥3, numérico): asigná materiales")
                return
            freqs = np.asarray(self.modal_result.freqs, dtype=float)
            h_max = self.modal_result.mesh_info.get("h_max", 0.0)
            f_max = self._validity_freq(h_max) if h_max > 0 else float(freqs[-1])
            f_hi = min(float(freqs[-1]), float(f_max))
            f_cross, _, _ = mm.modal_overlap_crossover(
                freqs, rt_fn, f_lo=20.0, f_hi=f_hi)
            if f_cross is None:
                self.lbl_fcross.setText(
                    f"f_cross (M≥3, numérico): > {f_hi:.0f} Hz "
                    f"(no cruza en banda válida)")
            else:
                self.lbl_fcross.setText(
                    f"f_cross (M≥3, numérico) ≈ {f_cross:.0f} Hz")
        except Exception as e:
            self.lbl_fcross.setText("f_cross (M≥3, numérico): —")
            self._log(f"Aviso f_cross: {e}")

    def _show_rt60_plot(self):
        """Abre el diálogo de comparación de RT (Sabine / Eyring / Fitzroy,
        con T60/T30/T20 y curvas agregables/quitables).

        El diálogo accede al panel (self) para obtener groups, volumen y
        asignaciones actuales de material; cada curva guarda un snapshot
        numérico, así el usuario puede modificar materiales entre clics y
        comparar variantes.
        """
        if not _HAS_MPL:
            QMessageBox.information(self, "matplotlib", "Instalar: pip install matplotlib")
            return
        try:
            dlg = RTComparisonDialog(self, parent=self)
            dlg.exec_()
        except Exception as e:
            self._log(f"Error RT: {e}")
