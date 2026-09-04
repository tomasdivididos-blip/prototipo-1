"""
prediction_panel.py
===================

Pestana "Prediccion" (tercer tab, a la derecha de "Acustica").

El usuario describe que necesita (uso, capacidad, restricciones del local).
El motor en `prediction.py` genera 3 candidatos de geometria (con ratios
clasicos), corre un FEM lite paralelo sobre cada uno, y este panel los
muestra como cards con metricas y un boton "Aplicar" por candidato.

Aplicar abre un menu con dos modos:
  - Como parametros (editable): mueve los sliders de la pestana Geometria.
  - Como CAD (fijo): inyecta la malla en el slot de geometria externa
    (como si hubiera sido importada por STL).
"""

from __future__ import annotations

from typing import Optional
import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QSlider,
    QScrollArea, QFrame, QMessageBox, QProgressDialog, QApplication, QMenu,
    QSizePolicy,
)

import prediction as pr
import location_opt as lo
import material_library as ml
from style import apply_dialog_theme
from material_library import MaterialLibrary
from pathlib import Path


# ---------------------------------------------------------------------------
# Card de un candidato (una alternativa de geometria)
# ---------------------------------------------------------------------------
class CandidateCard(QFrame):
    """Card visual para una Prediction agrupada por categoria acustica.

    Muestra: Modal (siempre), Voz (oculto para usos de musica), Musica
    (oculto para usos de voz), Practico (siempre), Robustez (siempre).
    """

    applyRequested = pyqtSignal(object, str)   # (Prediction, mode)

    def __init__(self, pred: 'pr.Prediction', rank: int,
                 use: str = "", parent=None):
        super().__init__(parent)
        self.pred = pred
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("CandidateCard")
        # Que la card crezca solo en horizontal hasta el ancho del scroll area.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Tres estilos de border:
        #   - Control negativo: rojo (NO usar, solo referencia)
        #   - Ganador (rank 1): verde turquesa
        #   - Resto: gris
        is_neg = bool(getattr(pred.candidate, "is_negative_control", False))
        if is_neg:
            self.setStyleSheet(
                "QFrame#CandidateCard { border: 2px dashed #f38ba8; "
                "border-radius: 6px; padding: 6px; background: #2b1d22; }"
            )
        elif rank == 1:
            self.setStyleSheet(
                "QFrame#CandidateCard { border: 2px solid #94e2d5; "
                "border-radius: 6px; padding: 6px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#CandidateCard { border: 1px solid #45475a; "
                "border-radius: 6px; padding: 6px; }"
            )

        lay = QVBoxLayout(self)
        lay.setSpacing(4)
        lay.setContentsMargins(8, 6, 8, 8)

        c = pred.candidate
        fem = pred.fem

        # Header con rank + nombre del ratio + score
        header = QHBoxLayout()
        if is_neg:
            title_text = f"<b>⚠ {c.ratio_name}</b>  <i>(control negativo)</i>"
        else:
            title_text = f"<b>{rank}. {c.ratio_name}</b>"
        title = QLabel(title_text)
        title.setStyleSheet("font-size: 11pt; color: #cdd6f4;")
        header.addWidget(title)
        header.addStretch()
        score = QLabel(f"<b>{pred.score_total:.0f}</b>/100")
        score_color = "#a6e3a1" if pred.score_total >= 80 else (
            "#f9e2af" if pred.score_total >= 60 else "#f38ba8")
        score.setStyleSheet(f"font-size: 11pt; color: {score_color};")
        header.addWidget(score)
        lay.addLayout(header)

        # Dimensiones y volumen
        dims = QLabel(
            f"{c.width:.2f} × {c.length:.2f} × {c.height:.2f} m   "
            f"·   V = {c.volume:.0f} m³"
        )
        dims.setStyleSheet("color: #cdd6f4;")
        dims.setWordWrap(True)
        lay.addWidget(dims)

        # ------ Bloques agrupados ------
        if fem.error:
            err = QLabel(f"⚠ FEM falló: {fem.error[:60]}")
            err.setStyleSheet("color: #f38ba8; font-size: 9pt;")
            err.setWordWrap(True)
            lay.addWidget(err)
        else:
            # Coloreo de sub-score (helper)
            def _color(s):
                return ("#a6e3a1" if s >= 80
                         else "#f9e2af" if s >= 50
                         else "#f38ba8")

            def _section(title: str, lines: list, scores: list):
                """Cada bloque: titulo + lineas info + chips de sub-scores."""
                hdr = QLabel(f"<b style='color:#89b4fa;'>{title}</b>")
                hdr.setStyleSheet("font-size: 8pt; margin-top: 4px;")
                lay.addWidget(hdr)
                for txt in lines:
                    if not txt:
                        continue
                    lbl = QLabel(txt)
                    lbl.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
                    lbl.setWordWrap(True)
                    lay.addWidget(lbl)
                if scores:
                    chips = "  ·  ".join(
                        f"{name}: <b style='color:{_color(s)};'>{s:.0f}</b>"
                        for name, s in scores
                    )
                    schip = QLabel(f"<span style='color:#a6adc8;'>{chips}</span>")
                    schip.setStyleSheet("font-size: 8pt;")
                    schip.setWordWrap(True)
                    lay.addWidget(schip)

            use_lower = (use or "").lower()
            is_voice = ("conferencia" in use_lower or "aula" in use_lower)
            is_music = ("musica" in use_lower or "sinfonica" in use_lower
                         or "camara" in use_lower)

            # Lectura humana del FSI (A6 — Rindel). nan (pocos modos) -> "n/d".
            # fem.fsi != fem.fsi solo cuando es nan (sin importar numpy aqui).
            if fem.fsi == fem.fsi:
                if fem.fsi <= 1.3:
                    _fsi_txt = f"<b>{fem.fsi:.2f}</b> (parejo)"
                elif fem.fsi <= 1.6:
                    _fsi_txt = f"<b>{fem.fsi:.2f}</b> (aceptable)"
                else:
                    _fsi_txt = f"<b>{fem.fsi:.2f}</b> (desparejo → coloración)"
            else:
                _fsi_txt = "<b>n/d</b> (pocos modos)"

            # MODAL — siempre visible
            _section(
                "MODAL",
                [
                    f"Modos 30-125 Hz: <b>{fem.n_modes_low}</b>  ·  "
                    f"Distribución (bins 5 Hz): <b>{fem.n_good_spacings}</b> buenos / "
                    f"<b>{fem.n_clumps}</b> grumos / <b>{fem.n_gaps}</b> huecos",
                    f"Espaciado modal (FSI ψ): {_fsi_txt}  ·  "
                    f"Densidad Bonello: <b>{fem.bonello_score:.0f}%</b> no-decrec.",
                    f"Modos audibles (Q&gt;30): <b>{fem.n_audible_modes}</b> "
                    f"de {fem.n_total_modes_eval}",
                    f"Cobertura Schroeder: <b>{fem.n_modes_below_schroeder}</b> "
                    f"modos &lt; {fem.schroeder_freq:.0f} Hz",
                    f"RT60 obj: {pred.feasibility_msg}",
                ],
                [("RT60", pred.score_rt60), ("Bolt", pred.score_uniformity),
                 ("FSI", pred.score_fsi), ("Bon", pred.score_bonello),
                 ("ModQ", pred.score_modal_q), ("Sch", pred.score_schroeder)],
            )

            # VOZ — solo para usos de voz o mixtos
            if not is_music:
                _section(
                    "VOZ",
                    [pred.sti_msg, pred.dcrit_msg],
                    [("STI", pred.score_sti),
                     ("Alc", pred.score_alcons),
                     ("d_crit", pred.score_dcrit)],
                )

            # MUSICA — solo para usos de musica o mixtos
            if not is_voice:
                _section(
                    "MÚSICA",
                    [pred.bass_msg,
                     "<i>BR depende mucho de materiales; este proxy mide "
                     "soporte geométrico de bajos.</i>"],
                    [("Bass", pred.score_bass)],
                )

            # PRACTICO — siempre
            _section(
                "PRÁCTICO",
                [f"Forma: {pred.aspect_msg}",
                 f"Planta: {pred.planta_msg}",
                 f"Construcción: {pred.constr_msg}"],
                [("Vol", pred.score_volume), ("Asp", pred.score_aspect),
                 ("Fit", pred.score_fits), ("Plt", pred.score_planta),
                 ("Cns", pred.score_constr)],
            )

            # ROBUSTEZ — siempre, una linea
            _section(
                "ROBUSTEZ",
                [pred.robustness_msg],
                [("Rob", pred.score_robustness)],
            )

        # Nota del ratio
        note = QLabel(c.ratio_note)
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c7086; font-size: 8pt; font-style: italic;")
        lay.addWidget(note)

        # Boton aplicar con dropdown — deshabilitado para control negativo
        # (esa card es solo referencia visual de lo que NO usar).
        if is_neg:
            self.btn_apply = QPushButton("No aplicable (control)")
            self.btn_apply.setEnabled(False)
            self.btn_apply.setToolTip(
                "Esta card existe solo como referencia visual. Un cubo perfecto "
                "tiene modos triplemente degenerados que causan resonancias "
                "fuertes y zonas sordas — observá los grumos y huecos arriba."
            )
            lay.addWidget(self.btn_apply)
            self.apply_timer = None
        else:
            self.btn_apply = QPushButton("Aplicar ▾")
            self.btn_apply.setObjectName("PrimaryButton")
            menu = QMenu(self.btn_apply)
            act_params = menu.addAction("Como parámetros (editable)")
            act_cad = menu.addAction("Como CAD (geometría fija)")
            act_params.triggered.connect(
                lambda: self.applyRequested.emit(self.pred, "params"))
            act_cad.triggered.connect(
                lambda: self.applyRequested.emit(self.pred, "cad"))
            self.btn_apply.setMenu(menu)
            lay.addWidget(self.btn_apply)
            # Leyenda persistente "Ultimo: X.XX s" debajo de Aplicar.
            from timed_button import TimedButton
            self.apply_timer = TimedButton(self.btn_apply, lay, prefix="Render:")


# ---------------------------------------------------------------------------
# Card de una recomendacion de UBICACION (T8: eje de ubicacion de fuentes)
# ---------------------------------------------------------------------------
class LocationCard(QFrame):
    """Card para una LocationPrediction: recinto + layout de fuentes + métricas."""

    applySourcesRequested = pyqtSignal(object)    # SourceArray
    applyAsParamsRequested = pyqtSignal(dict)     # solo modo combinado

    def __init__(self, pred: 'pr.LocationPrediction', rank: int, parent=None):
        super().__init__(parent)
        self.pred = pred
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("CandidateCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        border = ("2px solid #94e2d5" if rank == 1 else "1px solid #45475a")
        self.setStyleSheet(
            f"QFrame#CandidateCard {{ border: {border}; border-radius: 6px; "
            f"padding: 6px; }}")

        lay = QVBoxLayout(self)
        lay.setSpacing(4)
        lay.setContentsMargins(8, 6, 8, 8)
        c = pred.candidate

        # Header: rank + modo + score
        header = QHBoxLayout()
        mode_txt = "Combinado" if pred.mode == "combined" else "Ubicación"
        title = QLabel(f"<b>{rank}. {mode_txt}</b>")
        title.setStyleSheet("font-size: 11pt; color: #cdd6f4;")
        header.addWidget(title)
        header.addStretch()
        score = QLabel(f"<b>{pred.score_total:.0f}</b>/100")
        col = ("#a6e3a1" if pred.score_total >= 80
               else "#f9e2af" if pred.score_total >= 60 else "#f38ba8")
        score.setStyleSheet(f"font-size: 11pt; color: {col};")
        header.addWidget(score)
        lay.addLayout(header)

        def _info(txt, color="#cdd6f4", size=9):
            l = QLabel(txt)
            l.setStyleSheet(f"color:{color}; font-size:{size}pt;")
            l.setWordWrap(True)
            lay.addWidget(l)

        # En combinado la geometria es parte de la recomendacion.
        if pred.mode == "combined":
            _info(f"Recinto: {c.width:.2f} × {c.length:.2f} × {c.height:.2f} m  ·  "
                  f"V={c.volume:.0f} m³  ·  geometría {pred.geom_score:.0f}/100")

        _info(f"<b style='color:#89b4fa;'>FUENTES</b>   {pred.layout_msg}")
        _info(f"Posiciones: {pred.positions_msg}", color="#a6adc8", size=8)
        _info(f"<b style='color:#89b4fa;'>RESPUESTA</b>   {pred.fom_msg}")
        _info(f"SBIR: {pred.sbir_msg}", color="#a6adc8", size=8)

        # Chips de sub-scores
        def _cc(s):
            return "#a6e3a1" if s >= 80 else "#f9e2af" if s >= 50 else "#f38ba8"
        sub = pred.sub_scores
        chips = "  ·  ".join(
            f"{n}: <b style='color:{_cc(sub.get(k, 0))};'>{sub.get(k, 0):.0f}</b>"
            for k, n in (("flat", "Planitud"), ("espacial", "Espacial"),
                         ("sbir", "SBIR"), ("smoothness", "Suavidad")))
        chip = QLabel(f"<span style='color:#a6adc8;'>{chips}</span>")
        chip.setStyleSheet("font-size: 8pt;")
        chip.setWordWrap(True)
        lay.addWidget(chip)

        # Boton aplicar
        self.btn_apply = QPushButton("Aplicar ▾")
        self.btn_apply.setObjectName("PrimaryButton")
        menu = QMenu(self.btn_apply)
        act_src = menu.addAction("Colocar fuentes en Acústica")
        act_src.triggered.connect(
            lambda: self.applySourcesRequested.emit(
                self.pred.layout.to_source_array()))
        if pred.mode == "combined":
            act_geom = menu.addAction("Aplicar geometría (parámetros)")
            act_geom.setToolTip("Aplicá la geometría primero y después las fuentes: "
                                "el layout fue optimizado para este recinto.")
            act_geom.triggered.connect(
                lambda: self.applyAsParamsRequested.emit(
                    pr.candidate_to_params(self.pred.candidate)))
        self.btn_apply.setMenu(menu)
        lay.addWidget(self.btn_apply)


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------
class PredictionPanel(QWidget):
    """Panel completo de la pestana Prediccion."""

    # Emitido cuando el usuario elige "Aplicar como parametros".
    applyAsParamsRequested = pyqtSignal(dict)
    # Emitido cuando elige "Aplicar como CAD".
    applyAsCadRequested = pyqtSignal(object, object)
    # Emitido cuando elige colocar las fuentes de una prediccion de ubicacion (T8).
    applySourcesRequested = pyqtSignal(object)    # SourceArray
    # Emitido al pedir aplicar los materiales del preset a las caras de Acustica.
    applyMaterialsRequested = pyqtSignal(object)  # (floor_name, walls_name, ceiling_name)

    absorptionChoiceChanged = pyqtSignal(object)  # decisión normalizada o None

    def __init__(self, get_design_params=None, get_sources=None,
                 get_surface=None, get_damping_model=None,
                 get_absorption=None, parent=None):
        """get_design_params: callable que devuelve los params del ControlPanel
        actuales (lo que el usuario haya diseñado en la pestaña Geometría).
        Si es None, el botón 'Evaluar mi diseño actual' queda deshabilitado.

        get_sources: callable que devuelve el SourceArray actual del recinto
        (fuentes de la pestaña Acústica). Lo usa 'Evaluar mi diseño actual'
        cuando el criterio es Ubicación o Combinado, para scorear TU layout
        real. Si es None, esos criterios avisan que no hay fuentes.

        get_surface: callable que devuelve la malla real renderizada (v, t) del
        recinto. Lo usa 'Evaluar mi diseño actual' cuando la forma es irregular
        (planta dibujada / cortes laterales) para correr el FEM sobre la forma
        real, no sobre una caja reconstruida.
        """
        super().__init__(parent)
        self._get_design_params = get_design_params
        self._get_sources = get_sources
        self._get_surface = get_surface
        # Etapa 2c: modelo de amortiguamiento de la Acustica ("a36"|"perturbation").
        # Con "perturbation" y materiales por superficie, el FEM de ubicacion usa
        # xi POR MODO en vez del 1.1/(f_n·RT) uniforme. None -> "sabine" (default).
        self._get_damping_model = get_damping_model
        # Callback -> decisión de absorción actual de la Acústica (para heredarla
        # sin volver a preguntar; ver `_seed_absorption_from_acoustic`).
        self._get_absorption = get_absorption
        # Eleccion de como ponderar una forma irregular: None | "aabb" | "none".
        self._shape_choice = None
        # Eleccion de absorcion de superficies (gate de materiales). None hasta
        # que el usuario decida -> Predecir abre el dialogo de eleccion.
        self._abs_choice = None
        self._abs_inherited_notified = False   # aviso "heredada" una vez/sesión
        # Biblioteca de materiales para el preset/armar-el-tuyo (mismo catalogo
        # que Acustica -> los nombres coinciden al "aplicar a Acustica").
        try:
            self._mat_lib = MaterialLibrary(str(Path(__file__).resolve().parent
                                                / "materials"))
        except Exception:
            self._mat_lib = MaterialLibrary()

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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        scroll.setWidget(container)

        title = QLabel("Predicción de geometría")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Describe el uso y el soft sugiere dimensiones óptimas")
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # ---------- 1. Uso del recinto ----------
        g_use = QGroupBox("1. Uso del recinto")
        f_use = QFormLayout(g_use)
        self.combo_use = QComboBox()
        self.combo_use.addItems(list(pr.USE_PRESETS.keys()))
        self.combo_use.setCurrentText(pr.DEFAULT_USE)
        self.combo_use.wheelEvent = lambda ev: ev.ignore()
        self.combo_use.currentTextChanged.connect(self._on_use_changed)
        f_use.addRow("Uso:", self.combo_use)

        self.combo_program = QComboBox()
        self.combo_program.wheelEvent = lambda ev: ev.ignore()
        f_use.addRow("Programa:", self.combo_program)

        # Slider Inteligibilidad <-> Envoltura. Labels cortos para que entren
        # con el slider en una fila del FormLayout (~330 px utiles).
        prio_row = QWidget()
        prh = QHBoxLayout(prio_row)
        prh.setContentsMargins(0, 0, 0, 0)
        prh.setSpacing(4)
        lbl_int = QLabel("Intelig.")
        lbl_int.setToolTip("Inteligibilidad (voz clara)")
        prh.addWidget(lbl_int)
        self.sl_priority = QSlider(Qt.Horizontal)
        self.sl_priority.setMinimum(0)
        self.sl_priority.setMaximum(100)
        self.sl_priority.setValue(50)
        self.sl_priority.setMinimumWidth(0)
        self.sl_priority.wheelEvent = lambda ev: ev.ignore()
        prh.addWidget(self.sl_priority, 1)
        lbl_env = QLabel("Envolv.")
        lbl_env.setToolTip("Envoltura (sensacion de reverberancia musical)")
        prh.addWidget(lbl_env)
        f_use.addRow("Prioridad:", prio_row)

        layout.addWidget(g_use)

        # ---------- 2. Audiencia ----------
        g_aud = QGroupBox("2. Audiencia")
        f_aud = QFormLayout(g_aud)
        self.sp_capacity = QSpinBox()
        self.sp_capacity.setRange(1, 5000)
        self.sp_capacity.setValue(30)
        self.sp_capacity.setSuffix(" personas")
        self.sp_capacity.wheelEvent = lambda ev: ev.ignore()
        self.sp_capacity.valueChanged.connect(self._update_area_total)
        f_aud.addRow("Capacidad:", self.sp_capacity)

        m2_row = QWidget()
        m2h = QHBoxLayout(m2_row)
        m2h.setContentsMargins(0, 0, 0, 0)
        m2h.setSpacing(4)
        self.sp_m2pp = QDoubleSpinBox()
        self.sp_m2pp.setRange(0.30, 5.00)
        self.sp_m2pp.setDecimals(2)
        self.sp_m2pp.setSingleStep(0.05)
        self.sp_m2pp.setValue(0.80)
        self.sp_m2pp.setSuffix(" m²")
        self.sp_m2pp.setMinimumWidth(0)
        self.sp_m2pp.wheelEvent = lambda ev: ev.ignore()
        self.sp_m2pp.valueChanged.connect(self._update_area_total)
        m2h.addWidget(self.sp_m2pp, 1)
        self.cb_m2_auto = QCheckBox("auto")
        self.cb_m2_auto.setChecked(True)
        self.cb_m2_auto.toggled.connect(self._on_m2_auto_toggled)
        m2h.addWidget(self.cb_m2_auto)
        f_aud.addRow("m² por persona:", m2_row)

        self.lbl_area_total = QLabel("0 m²")
        self.lbl_area_total.setStyleSheet("color: #94e2d5;")
        f_aud.addRow("Área total:", self.lbl_area_total)

        layout.addWidget(g_aud)

        # ---------- 3. Restricciones (opcional) ----------
        # Layout en QFormLayout (etiqueta-izquierda, control-derecha) como
        # Geometria. El esquema anterior metia checkbox + 2 spinboxes con
        # suffix largo (" m ancho max") en HBoxLayout y se desbordaba.
        g_res = QGroupBox("3. Restricciones del local (opcional)")
        f_res = QFormLayout(g_res)
        f_res.setLabelAlignment(Qt.AlignRight)

        self.cb_limit_plant = QCheckBox("Activar")
        self.cb_limit_plant.toggled.connect(self._on_plant_limit_toggled)
        f_res.addRow("Limitar planta:", self.cb_limit_plant)

        self.sp_w_max = QDoubleSpinBox()
        self.sp_w_max.setRange(2.0, 100.0); self.sp_w_max.setValue(10.0)
        self.sp_w_max.setSuffix(" m")
        self.sp_w_max.setEnabled(False)
        self.sp_w_max.setMinimumWidth(0)
        self.sp_w_max.wheelEvent = lambda ev: ev.ignore()
        f_res.addRow("  Ancho máx:", self.sp_w_max)

        self.sp_l_max = QDoubleSpinBox()
        self.sp_l_max.setRange(2.0, 100.0); self.sp_l_max.setValue(15.0)
        self.sp_l_max.setSuffix(" m")
        self.sp_l_max.setEnabled(False)
        self.sp_l_max.setMinimumWidth(0)
        self.sp_l_max.wheelEvent = lambda ev: ev.ignore()
        f_res.addRow("  Largo máx:", self.sp_l_max)

        self.cb_limit_height = QCheckBox("Activar")
        self.cb_limit_height.toggled.connect(self._on_height_limit_toggled)
        self.cb_limit_height.setToolTip(
            "Por defecto los candidatos tienen muros de 2.5 a 4 m\n"
            "(razon constructiva: ~13 hiladas de ladrillo / jornada).\n"
            "Activar para forzar otra altura maxima (mayor o menor)."
        )
        f_res.addRow("Override altura:", self.cb_limit_height)

        self.sp_h_max = QDoubleSpinBox()
        self.sp_h_max.setRange(2.0, 30.0); self.sp_h_max.setValue(6.0)
        self.sp_h_max.setSuffix(" m")
        self.sp_h_max.setEnabled(False)
        self.sp_h_max.setMinimumWidth(0)
        self.sp_h_max.wheelEvent = lambda ev: ev.ignore()
        self.sp_h_max.setToolTip(
            "Techo maximo para los candidatos. Sobreescribe el default "
            "constructivo de 4 m."
        )
        f_res.addRow("  Altura máx:", self.sp_h_max)

        self.combo_parallel = QComboBox()
        self.combo_parallel.addItems(["Permitir", "Evitar"])
        self.combo_parallel.wheelEvent = lambda ev: ev.ignore()
        f_res.addRow("Paredes paralelas:", self.combo_parallel)

        self.combo_roof = QComboBox()
        self.combo_roof.addItems(["Plano", "Inclinado", "Abovedado"])
        self.combo_roof.wheelEvent = lambda ev: ev.ignore()
        f_res.addRow("Forma de techo:", self.combo_roof)

        layout.addWidget(g_res)

        # ---------- 4. Objetivos acusticos ----------
        g_obj = QGroupBox("4. Objetivos acústicos (auto-llenado por uso)")
        f_obj = QFormLayout(g_obj)
        self.sp_rt60 = QDoubleSpinBox()
        self.sp_rt60.setRange(0.10, 3.00); self.sp_rt60.setDecimals(2)
        self.sp_rt60.setSingleStep(0.05); self.sp_rt60.setSuffix(" s")
        self.sp_rt60.wheelEvent = lambda ev: ev.ignore()
        f_obj.addRow("RT60 @ 500 Hz:", self.sp_rt60)
        self.sp_v_pp = QDoubleSpinBox()
        self.sp_v_pp.setRange(1.0, 30.0); self.sp_v_pp.setDecimals(1)
        self.sp_v_pp.setSingleStep(0.5); self.sp_v_pp.setSuffix(" m³/p")
        self.sp_v_pp.wheelEvent = lambda ev: ev.ignore()
        f_obj.addRow("V por persona:", self.sp_v_pp)
        # Absorcion de superficies (gate de materiales). Sin elegir hasta que el
        # usuario decida; Predecir abre el dialogo si sigue "(sin elegir)".
        mat_row = QHBoxLayout()
        mat_row.setContentsMargins(0, 0, 0, 0)
        self.btn_absorption = QPushButton("(sin elegir)")
        self.btn_absorption.setToolTip(
            "Cómo se estima la absorción de las superficies para el RT60.\n"
            "Clic para elegir: que elija el programa · materiales por superficie "
            "(preset o armá el tuyo) · coeficiente uniforme.")
        self.btn_absorption.clicked.connect(lambda: self._ask_absorption())
        mat_row.addWidget(self.btn_absorption, 1)
        self.btn_apply_mat = QPushButton("Aplicar a Acústica")
        self.btn_apply_mat.setToolTip(
            "Asigna estos materiales a las caras del recinto en la pestaña "
            "Acústica (piso/paredes/techo según el preset elegido).")
        self.btn_apply_mat.clicked.connect(self._on_apply_materials_to_acoustic)
        self.btn_apply_mat.setVisible(False)
        mat_row.addWidget(self.btn_apply_mat)
        mat_w = QWidget()
        mat_w.setLayout(mat_row)
        f_obj.addRow("Materiales:", mat_w)
        layout.addWidget(g_obj)

        # ---------- 5. Modo de predicción (T8: eje de ubicación) ----------
        g_mode = QGroupBox("5. Modo de predicción")
        f_mode = QFormLayout(g_mode)
        self.combo_pred_mode = QComboBox()
        self.combo_pred_mode.addItems(
            ["Geometría", "Ubicación de fuentes", "Combinado"])
        self.combo_pred_mode.wheelEvent = lambda ev: ev.ignore()
        self.combo_pred_mode.setToolTip(
            "Geometría: sugiere la forma del recinto.\n"
            "Ubicación de fuentes: sobre el diseño actual de Geometría, sugiere "
            "dónde poner las fuentes (FoM + SBIR + suavidad modal).\n"
            "Combinado: optimiza forma y ubicación juntas."
        )
        self.combo_pred_mode.currentTextChanged.connect(self._on_pred_mode_changed)
        f_mode.addRow("Optimizar:", self.combo_pred_mode)
        layout.addWidget(g_mode)

        # Pesos del objetivo de ubicación (visibles en Ubicación/Combinado).
        self.g_weights = QGroupBox("Pesos del objetivo de ubicación")
        fw = QFormLayout(self.g_weights)
        self._weight_sliders = {}
        self._weight_labels = {}
        for key, lbl in (("flat", "Planitud"), ("espacial", "Espacial"),
                         ("sbir", "SBIR"), ("smoothness", "Suavidad modal")):
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(4)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(25)
            sl.setMinimumWidth(0)
            sl.wheelEvent = lambda ev: ev.ignore()
            val = QLabel("25")
            val.setMinimumWidth(26)
            sl.valueChanged.connect(
                lambda v, k=key: self._weight_labels[k].setText(str(v)))
            rh.addWidget(sl, 1)
            rh.addWidget(val)
            self._weight_sliders[key] = sl
            self._weight_labels[key] = val
            fw.addRow(lbl + ":", row)
        wnote = QLabel("Default por uso; ajustables. Se normalizan al combinar.")
        wnote.setStyleSheet("color:#6c7086; font-size:8pt;")
        wnote.setWordWrap(True)
        fw.addRow(wnote)
        self.g_weights.setVisible(False)
        layout.addWidget(self.g_weights)

        # ---------- Boton Predict ----------
        self.btn_predict = QPushButton("Predecir  (Enter)")
        self.btn_predict.setObjectName("PrimaryButton")
        self.btn_predict.setMinimumHeight(36)
        self.btn_predict.clicked.connect(self._on_predict)
        layout.addWidget(self.btn_predict)
        # Leyenda persistente "Ultimo: X.XX s" debajo del boton Predecir
        from timed_button import TimedButton
        self._predict_timer = TimedButton(self.btn_predict, layout)

        # ---------- Boton "Evaluar mi diseño actual" ----------
        # Toma la geometria de la pestana Geometria (lo que el usuario diseno
        # con sliders o importo como CAD) y la corre por el mismo pipeline de
        # scoring que las predicciones. Util para validar un diseno propio
        # contra los criterios objetivos (Bolt-spacing, RT60 feas, etc.).
        self.btn_eval_design = QPushButton("Evaluar mi diseño actual")
        self.btn_eval_design.setToolTip(
            "Aplica los mismos sub-scores (Bolt, RT60 feas, aspecto, ...) "
            "sobre la geometría que tenés diseñada en la pestaña Geometría."
        )
        self.btn_eval_design.setMinimumHeight(28)
        self.btn_eval_design.setEnabled(self._get_design_params is not None)
        self.btn_eval_design.clicked.connect(self._on_eval_design)
        layout.addWidget(self.btn_eval_design)
        self._eval_timer = TimedButton(self.btn_eval_design, layout)

        # ---------- Resultados ----------
        self.results_group = QGroupBox("Sugerencias")
        self.results_layout = QVBoxLayout(self.results_group)
        self.results_layout.setSpacing(8)
        self._placeholder = QLabel("Las sugerencias aparecerán aquí "
                                    "después de apretar «Predecir».")
        self._placeholder.setStyleSheet("color: #6c7086; font-style: italic;")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self.results_layout.addWidget(self._placeholder)
        layout.addWidget(self.results_group)

        layout.addStretch(1)

        # Inicializar campos derivados del preset por defecto
        self._on_use_changed(self.combo_use.currentText())
        self._update_area_total()

    # ----------------------------- Slots -----------------------------
    def _on_use_changed(self, name: str):
        preset = pr.USE_PRESETS.get(name)
        if not preset:
            return
        # Programa
        self.combo_program.blockSignals(True)
        self.combo_program.clear()
        self.combo_program.addItems(preset["programs"])
        self.combo_program.setCurrentText(preset["default_program"])
        self.combo_program.blockSignals(False)
        # Objetivos acusticos
        self.sp_rt60.setValue(preset["rt60_500"])
        self.sp_v_pp.setValue(preset["v_per_person"])
        # T3: altura default del uso (reemplaza el cap duro de 4 m). Se muestra
        # en el spinbox de "Override altura"; queda editable si se tilda.
        self.sp_h_max.blockSignals(True)
        self.sp_h_max.setValue(float(preset.get("h_default", 3.0)))
        self.sp_h_max.blockSignals(False)
        # m2/persona auto: para conferencia/aula 0.8, para musica 1.0, theater 1.2
        if self.cb_m2_auto.isChecked():
            m2 = 0.80
            if "musica" in name.lower() or "sinfonica" in name.lower():
                m2 = 1.00
            elif "theater" in name.lower() or "cine" in name.lower():
                m2 = 1.20
            self.sp_m2pp.blockSignals(True)
            self.sp_m2pp.setValue(m2)
            self.sp_m2pp.blockSignals(False)
            self._update_area_total()
        # Refrescar los pesos de ubicación al default del uso (si ya existen y
        # están visibles). Guardado: _on_use_changed corre en __init__ antes de
        # crear el grupo de pesos.
        if getattr(self, "g_weights", None) is not None and self.g_weights.isVisible():
            self._load_weight_defaults()

    def _on_m2_auto_toggled(self, checked: bool):
        self.sp_m2pp.setEnabled(not checked)
        if checked:
            self._on_use_changed(self.combo_use.currentText())

    def _on_plant_limit_toggled(self, checked: bool):
        self.sp_w_max.setEnabled(checked)
        self.sp_l_max.setEnabled(checked)

    def _on_height_limit_toggled(self, checked: bool):
        self.sp_h_max.setEnabled(checked)

    def _update_area_total(self):
        total = self.sp_capacity.value() * self.sp_m2pp.value()
        self.lbl_area_total.setText(f"{total:.1f} m²")

    # --------------------------- Modo / pesos (T8) ---------------------------
    _PRED_MODE_KEYS = {"Geometría": "geometry",
                       "Ubicación de fuentes": "location",
                       "Combinado": "combined"}

    def _pred_mode_key(self) -> str:
        return self._PRED_MODE_KEYS.get(self.combo_pred_mode.currentText(),
                                        "geometry")

    def _on_pred_mode_changed(self, text: str):
        is_loc = (text != "Geometría")
        self.g_weights.setVisible(is_loc)
        if is_loc:
            self._load_weight_defaults()

    def _load_weight_defaults(self):
        """Carga los pesos default del uso actual en los sliders (0-100)."""
        w = lo.default_location_weights(self.combo_use.currentText())
        for k, sl in self._weight_sliders.items():
            sl.blockSignals(True)
            sl.setValue(int(round(100.0 * float(w.get(k, 0.25)))))
            sl.blockSignals(False)
            self._weight_labels[k].setText(str(sl.value()))

    def _collect_weights(self) -> dict:
        return {k: float(sl.value()) for k, sl in self._weight_sliders.items()}

    def _collect_inputs(self) -> pr.PredictInputs:
        parallel = "evitar" if self.combo_parallel.currentText() == "Evitar" else "permitir"
        roof_map = {"Plano": "plano", "Inclinado": "inclinado", "Abovedado": "abovedado"}
        roof = roof_map.get(self.combo_roof.currentText(), "plano")
        return pr.PredictInputs(
            use=self.combo_use.currentText(),
            program=self.combo_program.currentText(),
            priority=self.sl_priority.value() / 100.0,
            capacity=self.sp_capacity.value(),
            m2_per_person=self.sp_m2pp.value(),
            rt60_target=self.sp_rt60.value(),
            v_per_person=self.sp_v_pp.value(),
            width_max=(self.sp_w_max.value()
                       if self.cb_limit_plant.isChecked() else None),
            length_max=(self.sp_l_max.value()
                        if self.cb_limit_plant.isChecked() else None),
            height_max=(self.sp_h_max.value()
                        if self.cb_limit_height.isChecked() else None),
            parallel_walls=parallel,
            roof_shape=roof,
            alpha_mode=(self._abs_choice or {}).get("mode", "target"),
            alpha_uniform=float((self._abs_choice or {}).get("alpha", 0.31)),
            surface_alpha=(self._abs_choice or {}).get("surface_alpha"),
        )

    def _material_by_name(self, name: str):
        """Material del catalogo por nombre exacto (o el rigido por defecto)."""
        names = self._mat_lib.names
        if name in names:
            return self._mat_lib[names.index(name)]
        return self._mat_lib.get_rigid_default()

    # ---- Puente de absorción con la Acústica (bidireccional) ---------------
    @staticmethod
    def _is_offscreen() -> bool:
        """True bajo QT_QPA_PLATFORM=offscreen: los diálogos modales segfaultean
        ahí (gotcha del proyecto), así que los benches no deben abrirlos."""
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            return app is not None and app.platformName() == "offscreen"
        except Exception:
            return False

    def absorption_state(self):
        """Decisión de absorción normalizada para compartir con la Acústica.

        None si no se eligió. Formatos:
          {"mode":"uniform","alpha":x} · {"mode":"materials","names":(p,par,t)}
          · {"mode":"target"}.  Se omite `surface_alpha` (se reconstruye por
        nombre en el otro extremo).
        """
        ch = self._abs_choice
        if not ch:
            return None
        mode = ch.get("mode", "target")
        if mode == "uniform":
            return {"mode": "uniform", "alpha": float(ch.get("alpha", 0.31))}
        if mode == "materials":
            return {"mode": "materials", "names": tuple(ch.get("names", ()))}
        return {"mode": "target"}

    def adopt_absorption_state(self, state):
        """Adopta una decisión de absorción venida de la Acústica.

        Bidireccional: α uniforme se sincroniza en ambos sentidos; materiales
        se mapean a piso/pared/techo (Acústica->Predicción). NO reemite (evita
        loops de señal); actualiza el botón/tooltip.
        """
        if not state:
            return
        mode = state.get("mode")
        if mode == "uniform":
            self._abs_choice = {"mode": "uniform", "alpha": float(state.get("alpha", 0.31))}
        elif mode == "materials":
            names = tuple(state.get("names", ()))
            if len(names) != 3 or not all(names):
                return
            nf, nw, nc = names
            mf, mw, mc = (self._material_by_name(nf), self._material_by_name(nw),
                          self._material_by_name(nc))
            self._abs_choice = {
                "mode": "materials",
                "surface_alpha": (mf.alpha_bands(), mw.alpha_bands(),
                                  mc.alpha_bands()),
                "names": (nf, nw, nc),
            }
        elif mode == "target":
            self._abs_choice = {"mode": "target"}
        else:
            return
        self._update_abs_label()

    def _seed_absorption_from_acoustic(self) -> bool:
        """Si Predicción no tiene absorción propia, la hereda de la Acústica en
        vez de volver a preguntar. Devuelve True si heredó algo."""
        if self._abs_choice is not None or self._get_absorption is None:
            return False
        try:
            state = self._get_absorption()
        except Exception:
            state = None
        if not state:
            return False
        self.adopt_absorption_state(state)
        if self._abs_choice is None:
            return False
        print(f"[Prediccion] absorción heredada de la Acústica: {state}")
        if not self._abs_inherited_notified and not self._is_offscreen():
            self._abs_inherited_notified = True
            try:
                from PyQt5.QtWidgets import QMessageBox
                txt = self.btn_absorption.text()
                QMessageBox.information(
                    self, "Absorción heredada de la Acústica",
                    f"Se usó la absorción que definiste en la pestaña Acústica "
                    f"({txt}).\n\nPodés cambiarla acá con el botón «Materiales…» "
                    f"sin afectar tu sala real.")
            except Exception:
                pass
        return True

    def _update_abs_label(self):
        """Refresca el boton de Materiales y la visibilidad de 'Aplicar a Acústica'."""
        ch = self._abs_choice
        is_mat = bool(ch and ch.get("mode") == "materials")
        self.btn_apply_mat.setVisible(is_mat)
        if not ch:
            self.btn_absorption.setText("(sin elegir)")
            self.btn_absorption.setToolTip("")
            return
        mode = ch.get("mode", "target")
        if mode == "materials":
            nf, nw, nc = ch.get("names", ("?", "?", "?"))
            self.btn_absorption.setText("materiales por superficie")
            self.btn_absorption.setToolTip(
                f"Piso: {nf}\nParedes: {nw}\nTecho: {nc}")
        elif mode == "uniform":
            self.btn_absorption.setText(f"α uniforme = {ch.get('alpha', 0.31):.2f}")
            self.btn_absorption.setToolTip("")
        else:
            self.btn_absorption.setText("automática (RT por uso)")
            self.btn_absorption.setToolTip("")

    def _on_apply_materials_to_acoustic(self):
        """Pide aplicar los materiales elegidos a las caras de Acústica."""
        ch = self._abs_choice
        if not ch or ch.get("mode") != "materials":
            return
        names = ch.get("names")
        if names:
            self.applyMaterialsRequested.emit(tuple(names))

    def _ask_absorption(self) -> bool:
        """Warning + eleccion de absorcion de las superficies. 3 caminos:
        que elija el programa / materiales por superficie (preset o armado) /
        coeficiente uniforme. Devuelve True si eligio, False si cancelo."""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                     QLabel, QRadioButton, QButtonGroup,
                                     QDoubleSpinBox, QComboBox, QDialogButtonBox)
        dlg = QDialog(self)
        apply_dialog_theme(dlg)  # tema claro (fondo blanco)
        dlg.setWindowTitle("Absorción de las superficies")
        v = QVBoxLayout(dlg)
        msg = QLabel(
            "La predicción necesita saber cuánta absorción tendrá la sala para "
            "estimar el RT60 (y de ahí modos audibles, Schroeder, etc.).\n\n"
            "¿Cómo querés definirla?")
        msg.setWordWrap(True)
        v.addWidget(msg)
        grp = QButtonGroup(dlg)
        rb_auto = QRadioButton("Que elija el programa (RT60 típico para el uso)")
        rb_unif = QRadioButton("Coeficiente de absorción uniforme (todas las caras):")
        rb_mat = QRadioButton("Materiales por superficie (preset o armá el tuyo):")
        for rb in (rb_auto, rb_unif, rb_mat):
            grp.addButton(rb)

        v.addWidget(rb_auto)
        urow = QHBoxLayout()
        urow.addWidget(rb_unif)
        sp = QDoubleSpinBox()
        sp.setRange(0.01, 0.99); sp.setSingleStep(0.01); sp.setDecimals(2)
        sp.setValue(float((self._abs_choice or {}).get("alpha", 0.31)))
        sp.setPrefix("α = ")
        urow.addWidget(sp); urow.addStretch(1)
        v.addLayout(urow)

        v.addWidget(rb_mat)
        names = self._mat_lib.names
        combo_preset = QComboBox()
        combo_preset.addItems(["(preset…)"] + ml.preset_names())
        combo_floor = QComboBox(); combo_floor.addItems(names)
        combo_walls = QComboBox(); combo_walls.addItems(names)
        combo_ceil = QComboBox(); combo_ceil.addItems(names)
        grid = QGridLayout()
        grid.setContentsMargins(22, 0, 0, 0)
        for r, (lbl, cb) in enumerate(
                (("Preset:", combo_preset), ("Piso:", combo_floor),
                 ("Paredes:", combo_walls), ("Techo:", combo_ceil))):
            grid.addWidget(QLabel(lbl), r, 0)
            grid.addWidget(cb, r, 1)
        v.addLayout(grid)

        def _load_preset(idx):
            if idx <= 0:
                return
            mf, mw, mc = ml.preset_surface_materials(
                self._mat_lib, combo_preset.currentText())
            for cb, mat in ((combo_floor, mf), (combo_walls, mw),
                            (combo_ceil, mc)):
                j = cb.findText(mat.name)
                if j >= 0:
                    cb.setCurrentIndex(j)
        combo_preset.currentIndexChanged.connect(_load_preset)

        def _sync():
            sp.setEnabled(rb_unif.isChecked())
            for w in (combo_preset, combo_floor, combo_walls, combo_ceil):
                w.setEnabled(rb_mat.isChecked())
        for rb in (rb_auto, rb_unif, rb_mat):
            rb.toggled.connect(lambda *_: _sync())

        prev = (self._abs_choice or {}).get("mode", "target")
        {"target": rb_auto, "uniform": rb_unif,
         "materials": rb_mat}.get(prev, rb_auto).setChecked(True)
        prev_names = (self._abs_choice or {}).get("names")
        if prev_names:
            for cb, nm in zip((combo_floor, combo_walls, combo_ceil), prev_names):
                j = cb.findText(nm)
                if j >= 0:
                    cb.setCurrentIndex(j)
        else:
            combo_preset.setCurrentIndex(1)      # primer preset como default
            _load_preset(1)
        _sync()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            return False
        if rb_mat.isChecked():
            nf, nw, nc = (combo_floor.currentText(), combo_walls.currentText(),
                          combo_ceil.currentText())
            mf = self._material_by_name(nf)
            mw = self._material_by_name(nw)
            mc = self._material_by_name(nc)
            self._abs_choice = {
                "mode": "materials",
                "surface_alpha": (mf.alpha_bands(), mw.alpha_bands(),
                                  mc.alpha_bands()),
                "names": (nf, nw, nc),
            }
        elif rb_unif.isChecked():
            self._abs_choice = {"mode": "uniform", "alpha": float(sp.value())}
        else:
            self._abs_choice = {"mode": "target"}
        self._update_abs_label()
        # Propaga a la Acústica (α uniforme se sincroniza; materiales van por el
        # botón explícito «Aplicar a Acústica» para no pisar la sala real).
        self.absorptionChoiceChanged.emit(self.absorption_state())
        return True

    def _damping_model_now(self) -> str:
        """Modelo de amortiguamiento a usar en el FEM de ubicacion (Etapa 2c).
        Lee el toggle de la Acustica via callback; "perturbation" activa el xi
        POR MODO (si hay materiales por superficie). Cualquier otra cosa -> el
        xi uniforme de siempre (no regresivo)."""
        if self._get_damping_model is None:
            return "sabine"
        try:
            return self._get_damping_model() or "sabine"
        except Exception:
            return "sabine"

    def _on_predict(self):
        # Gate de materiales: si no eligio absorcion, primero HEREDAR la de la
        # Acustica (puente bidireccional); solo si no hay, preguntar.
        if self._abs_choice is None and not self._seed_absorption_from_acoustic():
            if not self._ask_absorption():
                return                      # el usuario cancelo
        self._predict_timer.start()
        inputs = self._collect_inputs()
        mode = self._pred_mode_key()
        weights = self._collect_weights() if mode != "geometry" else None
        fixed = None
        surface = None
        if mode == "location" and self._get_design_params is not None:
            try:
                params = self._get_design_params()
                # Forma irregular -> el FEM de ubicacion corre sobre la malla
                # REAL renderizada (Camino B, como "Evaluar mi diseño"): mismos
                # modos y mismo sistema de coordenadas que la pestaña Geometria.
                # El candidato aporta ademas el volumen/areas (AABB) para el RT60.
                if pr.is_irregular_shape(params) and self._get_surface is not None:
                    surface = self._get_surface()
                    print(f"[Prediccion] forma irregular: FEM de ubicacion "
                          f"sobre la malla real ({len(surface[0])} vertices)")
                fixed = pr.fixed_room_from_design(params, surface=surface)
            except Exception:
                import traceback
                print("[Prediccion] fallo armando el recinto fijo; "
                      "se generan candidatos:")
                traceback.print_exc()
                fixed = None
                surface = None

        # ProgressDialog mientras corre el FEM lite paralelo
        prog = QProgressDialog("Generando candidatos...", "Cancelar", 0, 0, self)
        apply_dialog_theme(prog)  # tema claro (fondo blanco)
        prog.setWindowTitle("Prediccion")
        prog.setMinimumDuration(150)
        prog.setWindowModality(Qt.WindowModal)
        prog.setAutoClose(False)
        prog.setAutoReset(False)

        def _prog(msg: str):
            prog.setLabelText(msg)
            QApplication.processEvents()

        try:
            preds = pr.predict_axis(inputs, mode=mode, fixed_candidate=fixed,
                                    weights=weights, progress=_prog,
                                    surface=surface,
                                    damping_model=self._damping_model_now())
        except Exception as e:
            prog.close()
            QMessageBox.critical(
                self, "Error en la prediccion",
                f"No se pudo completar la prediccion:\n{e}"
            )
            self._predict_timer.fail("error")
            return
        prog.close()

        self._render_results(preds)
        # Leyenda con score del ganador. En ubicacion con forma irregular
        # agrega "malla real": marcador persistente de que el FEM corrio
        # sobre la forma dibujada (el dialogo de progreso puede no llegar a
        # mostrarse si la prediccion es rapida).
        if preds:
            kind = {"geometry": "candidatos", "location": "ubicaciones",
                    "combined": "combinadas"}.get(mode, "sugerencias")
            extra = " · malla real" if surface is not None else ""
            self._predict_timer.stop(
                f"{len(preds)} {kind} · top score {preds[0].score_total:.0f}"
                f"{extra}"
            )
        else:
            self._predict_timer.stop()

    def _ask_irregular_shape(self) -> bool:
        """Diálogo para una forma irregular: aproximar por caja envolvente
        (AABB) o no ponderar la forma. Guarda la elección en
        `self._shape_choice` y devuelve True si aceptó, False si canceló."""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QRadioButton,
                                     QButtonGroup, QDialogButtonBox)
        dlg = QDialog(self)
        apply_dialog_theme(dlg)  # tema claro (fondo blanco)
        dlg.setWindowTitle("Forma irregular")
        v = QVBoxLayout(dlg)
        msg = QLabel(
            "El recinto tiene una forma personalizada (planta dibujada o cortes "
            "laterales). El score de geometría (proporciones, Bolt, ratios) está "
            "definido para cajas.\n\n¿Cómo querés ponderar la forma?")
        msg.setWordWrap(True)
        v.addWidget(msg)

        grp = QButtonGroup(dlg)
        rb_aabb = QRadioButton("Aproximar con la caja envolvente (AABB)")
        rb_none = QRadioButton("No ponderar la forma")
        for rb in (rb_aabb, rb_none):
            grp.addButton(rb)
        v.addWidget(rb_aabb)
        v.addWidget(rb_none)

        leyenda = QLabel(
            "Con «No ponderar la forma» no será posible predecir por geometría: "
            "elegí el enfoque Ubicación o Combinado, o aproximá con la caja "
            "envolvente.")
        leyenda.setWordWrap(True)
        leyenda.setStyleSheet("color: #b45309; font-size: 9pt; margin-left: 22px;")
        v.addWidget(leyenda)

        {"aabb": rb_aabb, "none": rb_none}.get(
            self._shape_choice, rb_aabb).setChecked(True)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            return False
        self._shape_choice = "none" if rb_none.isChecked() else "aabb"
        return True

    def _on_eval_design(self):
        """Evalua el diseño ACTUAL por el eje elegido en el combo de criterio.

        - Geometría  -> scorea la forma del recinto (como siempre).
        - Ubicación  -> scorea TU layout real de fuentes en tu recinto.
        - Combinado  -> geometría + tu layout real.

        Lee las fuentes reales del recinto (callback `_get_sources`) cuando el
        criterio las necesita; sin fuentes avisa (location) o cae a solo
        geometría (combined).
        """
        if self._get_design_params is None:
            QMessageBox.warning(self, "Sin diseño",
                                 "No hay callback para obtener la geometría actual.")
            return
        try:
            params = self._get_design_params()
        except Exception as e:
            QMessageBox.critical(self, "Error",
                                  f"No se pudo obtener los params del diseño:\n{e}")
            return

        mode = self._pred_mode_key()
        inputs = self._collect_inputs()

        # --- Fuentes: Ubicación/Combinado evalúan TUS fuentes reales ---
        # (puede degradar Combinado -> Geometría si no hay ninguna).
        sources = None
        if mode in ("location", "combined"):
            sources = self._get_sources() if self._get_sources is not None else None
            n_src = len(sources) if sources is not None else 0
            if n_src == 0:
                if mode == "location":
                    QMessageBox.information(
                        self, "Sin fuentes",
                        "El criterio «Ubicación de fuentes» evalúa dónde "
                        "colocaste las fuentes, pero no hay ninguna en el "
                        "recinto.\n\nPoné al menos una fuente en la pestaña "
                        "Acústica, o usá «Predecir» para que el optimizador "
                        "sugiera ubicaciones.")
                    return
                # Combinado sin fuentes: evaluar solo la geometría, con aviso.
                QMessageBox.information(
                    self, "Sin fuentes",
                    "No hay fuentes en el recinto: evalúo solo la geometría. "
                    "Agregá fuentes en Acústica para incluir la ubicación.")
                mode, sources = "geometry", None

        weights = self._collect_weights() if mode != "geometry" else None

        # --- Forma irregular: FEM sobre la malla REAL renderizada ---
        surface = None
        shape_mode = "exact"
        if pr.is_irregular_shape(params):
            surface = (self._get_surface()
                       if self._get_surface is not None else None)
            if surface is None:
                QMessageBox.warning(
                    self, "Sin malla",
                    "El diseño tiene una forma personalizada pero no puedo "
                    "obtener la malla renderizada para evaluarla.")
                return
            if mode in ("geometry", "combined"):
                # La geometría se pondera -> que el usuario elija cómo.
                if not self._ask_irregular_shape():
                    return                      # canceló
                shape_mode = self._shape_choice
                if mode == "geometry" and shape_mode == "none":
                    QMessageBox.information(
                        self, "Forma no ponderable",
                        "Elegiste no ponderar la forma irregular: no se puede "
                        "predecir por geometría.\n\nElegí el enfoque Ubicación "
                        "o Combinado, o volvé a evaluar aproximando con la caja "
                        "envolvente.")
                    return
            else:
                shape_mode = "none"             # location: la forma no se pondera

        self._eval_timer.start()
        prog = QProgressDialog("Evaluando tu diseño actual...",
                                "Cancelar", 0, 0, self)
        apply_dialog_theme(prog)  # tema claro (fondo blanco)
        prog.setWindowTitle("Evaluar diseño")
        prog.setMinimumDuration(150)
        prog.setWindowModality(Qt.WindowModal)
        prog.setAutoClose(False)
        prog.setAutoReset(False)

        def _prog(msg: str):
            prog.setLabelText(msg)
            QApplication.processEvents()
        QApplication.processEvents()

        try:
            pred = pr.evaluate_design(params, inputs, mode=mode,
                                      sources=sources, weights=weights,
                                      surface=surface, shape_mode=shape_mode,
                                      progress=_prog,
                                      damping_model=self._damping_model_now())
        except Exception as e:
            prog.close()
            self._eval_timer.fail("error")
            QMessageBox.critical(self, "Error en evaluación", str(e))
            return
        prog.close()

        # Renderizar SOLO esta card (limpia las cards previas)
        self._render_results([pred])

        # Leyenda del timer según el eje evaluado.
        if isinstance(pred, pr.LocationPrediction):
            ns = pred.layout.n_sources
            eje = "combinado" if pred.mode == "combined" else "ubicación"
            self._eval_timer.stop(
                f"{eje} · {ns} fuente{'s' if ns != 1 else ''} · "
                f"score {pred.score_total:.0f}")
        else:
            c = pred.candidate
            self._eval_timer.stop(
                f"{c.width:.1f}×{c.length:.1f}×{c.height:.1f} m · "
                f"score {pred.score_total:.0f}")

    def _render_results(self, preds: list):
        # Limpiar resultados previos
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if not preds:
            lbl = QLabel("No se pudo generar ninguna sugerencia.")
            lbl.setStyleSheet("color: #f38ba8;")
            self.results_layout.addWidget(lbl)
            return

        # El "use" se pasa a las cards de geometria para condicionar VOZ vs
        # MUSICA visible. Las predicciones de ubicacion usan LocationCard.
        current_use = self.combo_use.currentText()
        for i, p in enumerate(preds, start=1):
            if isinstance(p, pr.LocationPrediction):
                card = LocationCard(p, rank=i, parent=self)
                card.applySourcesRequested.connect(self.applySourcesRequested)
                card.applyAsParamsRequested.connect(self.applyAsParamsRequested)
            else:
                card = CandidateCard(p, rank=i, use=current_use, parent=self)
                card.applyRequested.connect(self._on_apply_requested)
            self.results_layout.addWidget(card)

    def _on_apply_requested(self, pred: 'pr.Prediction', mode: str):
        # Identificar la card que origino el pedido para actualizar SU timer
        sender_card = self.sender()    # CandidateCard que emitio applyRequested
        timer = getattr(sender_card, "apply_timer", None) if sender_card else None
        if timer is not None:
            timer.start()

        cand = pred.candidate
        try:
            if mode == "params":
                params = pr.candidate_to_params(cand)
                self.applyAsParamsRequested.emit(params)
                if timer: timer.stop(f"{cand.width:.1f}×{cand.length:.1f}×{cand.height:.1f} m")
            elif mode == "cad":
                # Construir la malla superficial del candidato
                from geometry import make_room
                v, t, _e, _n = make_room(
                    width=cand.width, length=cand.length, height=cand.height,
                    n_walls=cand.n_walls, taper=cand.taper, twist=cand.twist,
                    arch_height=cand.arch_height, roof_type=cand.roof_type,
                    subdiv_levels=0,
                )
                self.applyAsCadRequested.emit(np.asarray(v), np.asarray(t))
                if timer: timer.stop(f"CAD · {len(v)} verts")
        except Exception as e:
            if timer: timer.fail("error")
            QMessageBox.critical(self, "Error al aplicar",
                                  f"No se pudo aplicar el candidato:\n{e}")
            return

    # Atajo Enter -> Predecir (consumido desde MainWindow)
    def trigger_predict(self):
        self._on_predict()
