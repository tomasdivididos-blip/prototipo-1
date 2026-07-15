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
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QSlider, QFileDialog, QMessageBox, QDialog,
    QDialogButtonBox, QLineEdit, QProgressBar, QSizePolicy, QFrame,
    QScrollArea,
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
import face_materials as fm


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
        self.setWindowTitle("Fuente acústica")
        # Callback opcional -> lista de (centroide(3,), normal(3,)) de las paredes
        # (para "Pegar a pared más cercana"). El panel lo arma con los face groups.
        self._get_walls = get_walls
        # Bandera de montaje (one-shot informativa); se prende al pegar a pared.
        self._mounted = bool(getattr(source, "mounted", False)) if source else False
        layout = QFormLayout(self)
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
        note.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        layout.addRow("", note)

        self.lbl_q = QLabel()
        self.lbl_q.setStyleSheet("color: #94e2d5; font-size: 9pt;")
        layout.addRow("→ Q equivalente:", self.lbl_q)
        self._update_q_label()
        self.sb_sens.valueChanged.connect(self._update_q_label)

        # --- Respuesta en frecuencia Q(f) (Fase 2 — plan_fuentes) -----------
        # La curva es una ganancia compleja g(f) relativa al Q baseline
        # (opcion 1). "Sin curva" = Q constante (comportamiento historico).
        self._response = (source.response
                          if (source is not None and getattr(source, "response", None))
                          else None)
        self._frd_raw = None    # (freq, spl_db, phase_rad, name) si se cargo aca

        grp_resp = QGroupBox("Respuesta en frecuencia  Q(f)   (opcional)")
        gl = QVBoxLayout(grp_resp)

        self.lbl_resp = QLabel()
        self.lbl_resp.setWordWrap(True)
        self.lbl_resp.setStyleSheet("font-size: 8pt;")
        gl.addWidget(self.lbl_resp)

        brow = QHBoxLayout()
        btn_load = QPushButton("Cargar FRD/TRF…")
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
        mrow.addWidget(self.sb_delay)
        self.chk_invert = QCheckBox("Invertir polaridad")
        mrow.addWidget(self.chk_invert)
        mrow.addWidget(QLabel("Fase (°):"))
        self.sb_phase = QDoubleSpinBox()
        self.sb_phase.setRange(-180.0, 180.0)
        self.sb_phase.setDecimals(0)
        self.sb_phase.setSingleStep(15.0)
        mrow.addWidget(self.sb_phase)
        btn_manual = QPushButton("Aplicar")
        btn_manual.clicked.connect(self._apply_manual)
        mrow.addWidget(btn_manual)
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
        self.lbl_mounted.setStyleSheet("color: #94e2d5; font-size: 8pt;")
        fb.addRow("", self.lbl_mounted)
        layout.addRow(grp_baf)

        if dims_hint:
            hint = QLabel(f"Recinto: {dims_hint[0]:.1f} × "
                          f"{dims_hint[1]:.1f} × {dims_hint[2]:.1f} m")
            hint.setStyleSheet("color: #585b70; font-size: 8pt;")
            layout.addRow("", hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _update_q_label(self):
        from sources import q_from_sensitivity
        q = q_from_sensitivity(self.sb_sens.value(), power_W=1.0,
                                f_ref=self._F_REF)
        self.lbl_q.setText(f"|Q| = {abs(q):.3e} m³/s  "
                           f"(monopolo @ {self._F_REF:.0f} Hz, 1 W)")

    # ------------------------------------------------------------------
    # Respuesta en frecuencia Q(f) (Fase 2)
    # ------------------------------------------------------------------
    def _q_base(self) -> float:
        from sources import q_from_sensitivity
        return abs(q_from_sensitivity(self.sb_sens.value(), power_W=1.0,
                                      f_ref=self._F_REF))

    def _load_frd(self):
        from frd import load_frd, load_trf, minimum_phase, _TRF_MAGIC
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar respuesta FRD / TRF", "",
            "Respuesta (*.frd *.trf *.txt *.dat);;Todos los archivos (*)")
        if not path:
            return
        # Sniff por contenido (no por extension): TRF binario = magic JACKREF!
        try:
            with open(path, "rb") as fh:
                is_trf = fh.read(8) == _TRF_MAGIC
        except Exception as e:
            QMessageBox.warning(self, "FRD/TRF", f"No se pudo abrir:\n{e}")
            return
        coh = None
        try:
            if is_trf:
                freq, spl, phase_deg, coh = load_trf(path)
            else:
                freq, spl, phase_deg = load_frd(path)
        except Exception as e:
            QMessageBox.warning(self, "FRD/TRF",
                                f"No se pudo leer el archivo:\n{e}")
            return
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

    def _apply_manual(self):
        """Atajo sin archivo: g(f) = ±e^{-i2πfτ} (delay + polaridad)."""
        from sources import SourceResponse
        tau = self.sb_delay.value() / 1000.0
        invert = self.chk_invert.isChecked()
        phi0 = np.radians(self.sb_phase.value())     # offset de fase constante (T5)
        if tau <= 0.0 and not invert and abs(self.sb_phase.value()) < 1e-9:
            QMessageBox.information(self, "Q(f)",
                "Poné un delay > 0 ms, una fase ≠ 0, o tildá invertir polaridad.")
            return
        f = np.linspace(1.0, 1000.0, 1500)
        gain_db = np.zeros_like(f)
        phase = -2.0 * np.pi * f * tau + (np.pi if invert else 0.0) + phi0
        parts = []
        if tau > 0.0:
            parts.append(f"delay {self.sb_delay.value():.2f} ms")
        if invert:
            parts.append("polaridad −")
        if abs(self.sb_phase.value()) > 1e-9:
            parts.append(f"fase {self.sb_phase.value():.0f}°")
        self._frd_raw = None    # el atajo manual reemplaza cualquier FRD
        self._response = SourceResponse(f, gain_db, phase,
                                        name=" + ".join(parts) or "manual")
        self._refresh_resp_ui()

    def _clear_resp(self):
        self._response = None
        self._frd_raw = None
        self.sb_delay.setValue(0.0)
        self.chk_invert.setChecked(False)
        self.sb_phase.setValue(0.0)
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

    def _draw_resp_preview(self):
        if self._resp_canvas is None:
            return
        try:
            # set_xscale('linear') antes de clear() evita el warning de xlim
            # no-positivo cuando el eje venía en log y no hay datos nuevos.
            for ax in (self._resp_ax_m, self._resp_ax_p):
                ax.set_xscale('linear')
                ax.clear()
            if self._response is not None:
                fmin, fmax, _ = self._response.coverage()
                fa = np.linspace(max(fmin, 1.0), fmax, 400)
                g = self._response.gain_spectrum(fa)
                self._resp_ax_m.semilogx(
                    fa, 20 * np.log10(np.maximum(np.abs(g), 1e-9)),
                    color='#1f6fbf', lw=1.4)
                self._resp_ax_p.semilogx(
                    fa, np.degrees(np.angle(g)), color='#e07000', lw=1.4)
            else:
                # Sin curva cargada: dibujar la default explícita (g≡1 =
                # Q constante), para que el preview nunca quede vacío.
                fa = np.geomspace(20.0, 500.0, 50)
                z = np.zeros_like(fa)
                self._resp_ax_m.semilogx(fa, z, color='#888888',
                                         lw=1.2, ls='--')
                self._resp_ax_p.semilogx(fa, z, color='#888888',
                                         lw=1.2, ls='--')
                self._resp_ax_m.set_ylim(-12, 12)
                self._resp_ax_p.set_ylim(-180, 180)
                self._resp_ax_m.set_title("default: plana (Q constante)",
                                          fontsize=7, color='#666666')
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


class FRFDialog(QDialog):
    """Diálogo de FRF con gráfico matplotlib, exportación y escucha con ruido rosa."""

    def __init__(self, frf_result, modal_freqs=None, parent=None,
                 fom=None, fom_band=None, eqc=None, eqc_band=None):
        super().__init__(parent)
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
            fom_lbl.setStyleSheet("color:#ffffff; font-size:9pt; font-weight:600;")
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
            eq_lbl.setStyleSheet("color:#ffffff; font-size:9pt; font-weight:600;")
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
        self.lbl_audio_status.setStyleSheet("color:#94a3b8; font-size:8pt;")
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
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("SBIR — interferencia fuente-frontera")
        self.resize(980, 600)
        self._fig = None
        self._res = result
        self._flo, self._fhi = float(f_lo), float(f_hi)
        v = QVBoxLayout(self)

        if not _HAS_MPL:
            v.addWidget(QLabel("matplotlib no disponible. pip install matplotlib"))
            return

        res = result
        f = res.freq_axis
        self._fig, ax = plt.subplots(figsize=(9.5, 4.4), dpi=96)
        self._fig.patch.set_facecolor('#f0f0f0')
        ax.set_facecolor('#ffffff')

        multi = len(res.per_source) > 1
        for i, src in enumerate(res.per_source):
            ax.plot(f, src.sbir_db, linewidth=1.3,
                    alpha=0.65 if multi else 1.0,
                    color=self._COLORS[i % len(self._COLORS)],
                    label=src.label)
        if multi:
            ax.plot(f, res.total_sbir_db, color='#1f6fbf', linewidth=2.4,
                    label='Total (suma)')

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
        ax.set_ylabel('SBIR (dB re directo)', fontsize=10)
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

        canvas = FigureCanvas(self._fig)
        toolbar = NavigationToolbar(canvas, self)
        v.addWidget(toolbar)
        v.addWidget(canvas, 1)

        # --- Lectura: realce/atenuacion + distancias fuente-pared ---
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
            rows = []
            for i in range(len(f)):
                row = [float(f[i])] + [float(s.sbir_db[i]) for s in res.per_source]
                if len(res.per_source) > 1:
                    row.append(float(res.total_sbir_db[i]))
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
        right.addWidget(grp_add)

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
        note.setStyleSheet("color: #94a3b8; font-size: 8pt; padding: 4px;")
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
        note.setStyleSheet("color: #94a3b8; font-size: 9pt;")
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
        lbl.setStyleSheet("color: #94a3b8; font-size: 9pt;")
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

        self._build_ui()
        self._refresh_sources_list()
        self._refresh_receiver_marker()

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

        btn_rt60_plot  = QPushButton("Ver RT60 calculado")
        btn_reload_mat = QPushButton("Recargar materiales")
        btn_rt60_plot.clicked.connect(self._show_rt60_plot)
        btn_reload_mat.clicked.connect(self._reload_materials)
        fmat.addRow(btn_rt60_plot)
        fmat.addRow(btn_reload_mat)
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

        self.btn_schroeder = QPushButton("Calcular f_Schroeder")
        self.btn_schroeder.clicked.connect(self.compute_and_show_schroeder)
        ffs.addRow(self.btn_schroeder)
        layout.addWidget(grp_fs)

        # --- FEM modal ---
        grp_fem = QGroupBox("FEM modal")
        ff = QFormLayout(grp_fem)
        self.sb_nmodes = QSpinBox(); self.sb_nmodes.setRange(2, 500); self.sb_nmodes.setValue(12)
        self.sb_density = QDoubleSpinBox(); self.sb_density.setRange(0.5, 10.0); self.sb_density.setValue(2.5); self.sb_density.setSingleStep(0.25); self.sb_density.setDecimals(2)
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
            "Para cubrir hasta f_Schroeder, usá el botón 'Aplicar npm sugerido' debajo."
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
        fmode.addRow("Modo:", self.combo_mode)

        # Leyenda con conteo total y filtrado (texto reactivo).
        self.lbl_modes_count = QLabel("— sin modos calculados —")
        self.lbl_modes_count.setStyleSheet("color: #94e2d5; font-size: 10pt;")
        self.lbl_modes_count.setWordWrap(True)
        fmode.addRow("", self.lbl_modes_count)

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
        return (f"[{i}] {s.label}  @ ({s.position[0]:.2f}, "
                f"{s.position[1]:.2f}, {s.position[2]:.2f})   "
                f"|Q|={absQ:.3g}  ∠={ph:+.1f}°"
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
            self._log(f"Fuente {i} editada.")

    def _remove_source(self):
        i = self._selected_src_idx()
        if i < 0:
            return
        del self.sources.sources[i]
        self._refresh_sources_list()
        self._log(f"Fuente {i} eliminada.")

    def _duplicate_source(self):
        i = self._selected_src_idx()
        if i < 0:
            return
        s = self.sources[i]
        new = OmniSource(position=s.position, Q=s.Q,
                          label=f"{s.label}_dup",
                          sensitivity_dB=s.sensitivity_dB,
                          power_W=s.power_W, f_ref=s.f_ref)
        new.response = s.response       # Fase 2: la copia conserva la curva Q(f)
        self.sources.add(new)
        self._refresh_sources_list()
        self._log("Fuente duplicada.")

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
                V = aa.compute_mesh_volume(verts, tris)
                S = aa.compute_mesh_surface_area(verts, tris)
                f_target = aa.schroeder_frequency(V, S, alpha=0.05)
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
                    f"Auto-tuner: V={V:.1f} m³, f_Schroeder={f_target:.0f} Hz, "
                    f"cobertura completa -> {auto_used.message}"
                )

                # Aplicar densidades auto-tuneadas a los spinboxes (visible al usuario)
                npm_used = auto_used.n_per_meter
                h_used = auto_used.h_target
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
                progress=_progress_cb,
            )
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
            for i, f in enumerate(self.modal_result.freqs):
                if f_min <= f <= f_max:
                    self.combo_mode.addItem(f"{i}: f = {f:.2f} Hz", userData=int(i))
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
                f = float(self.modal_result.freqs[mode_idx])
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
        for g in groups:
            mat = g2m.get(g.signature)
            if mat is not None:
                alpha = np.array([mat.alpha(float(ff)) for ff in freq])
            else:
                alpha = np.full(freq.shape, 0.03)   # default rigido
            walls.append(sbir.Wall(
                point=g.centroid, normal=g.normal, label=g.label,
                R=sbir.reflection_from_alpha(alpha),
            ))

        try:
            res = sbir.sbir_from_sources(act, walls, self.receiver, freq)
        except Exception as e:
            QMessageBox.critical(self, "Error SBIR", str(e))
            return

        n_assigned = sum(1 for g in groups if g.signature in g2m)
        self._log(f"SBIR: {len(act)} fuente(s) activa(s), {len(walls)} superficies "
                  f"({n_assigned} con material), receptor {self.receiver}.")
        dlg = SBIRDialog(res, f_lo=f_lo, f_hi=f_hi, parent=self)
        dlg.exec_()

    # -----------------------------------------------------------------------
    # FRF
    # -----------------------------------------------------------------------
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
        damping = self._xi_per_mode if self._xi_per_mode is not None else 0.03
        try:
            self.setEnabled(False)
            if self.modal_result is None:
                self._log("FRF requiere modos. Calculando primero...")
                self.modal_result = aa.run_fem_modal(
                    verts, tris,
                    n_modes=self.sb_nmodes.value(),
                    n_per_meter=self.sb_density.value(),
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
                receivers = mm.default_receiver_grid(self.modal_result.nodes)
                # H_real (= compute_forced_response) + H_env para corregibilidad EQ.
                H, H_env = mm.forced_response_with_envelope(
                    self.modal_result.locator,
                    self.modal_result.freqs, self.modal_result.phis,
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

        dlg = FRFDialog(
            result,
            modal_freqs=self.modal_result.freqs if self.modal_result else None,
            parent=self,
            fom=fom, fom_band=fom_band, eqc=eqc, eqc_band=eqc_band,
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

    def compute_and_show_schroeder(self):
        """Calcula y muestra la frecuencia de Schroeder del recinto actual."""
        try:
            import acoustic_analysis as aa_mod
            verts, tris = self.get_surface()
            V = aa_mod.compute_mesh_volume(verts, tris)
            S = aa_mod.compute_mesh_surface_area(verts, tris)
            # v2.16: el RT sale de los MATERIALES asignados (o del default del
            # mapa), no de un α=0.05 fijo. Como el RT es por banda, se resuelve
            # el punto fijo f_S = 2000·sqrt(RT(f_S)/V): la transicion modal->
            # estadistica ocurre donde el solapamiento con el RT LOCAL en esa
            # frecuencia llega a M≈3, no con el RT de una banda arbitraria.
            # np.interp clampea fuera de banda (RT(f<125)=RT(125)).
            fs = None
            rt_used = None
            src_txt = ""
            try:
                groups, _gv, _gt = self._get_face_groups()
                if groups and V > 0:
                    g2m = self._group_to_material_dict(groups)
                    rt = self._sabine_rt60(V, groups, g2m)
                    if rt:
                        bands = np.array(sorted(rt), dtype=float)
                        rts = np.array([rt[b] for b in sorted(rt)], dtype=float)
                        fs = 2000.0 * np.sqrt(max(float(rts[0]), 1e-3) / V)
                        for _ in range(12):
                            rt_used = float(np.interp(fs, bands, rts))
                            fs_new = 2000.0 * np.sqrt(max(rt_used, 1e-3) / V)
                            if abs(fs_new - fs) < 0.5:
                                fs = fs_new
                                break
                            fs = fs_new
                        asig = self._face_mat_map.to_dict()
                        n_asig = sum(1 for g in groups
                                     if asig.get(g.signature))
                        det = (f"{n_asig}/{len(groups)} grupos asignados"
                               if n_asig else
                               f"sin asignar: default "
                               f"'{self._face_mat_map.default}'")
                        src_txt = (f"RT de materiales: RT(f_S)={rt_used:.2f} s "
                                   f"({det})")
            except Exception:
                fs = None
            if fs is None or not np.isfinite(fs) or fs <= 0:
                alpha = 0.05  # fallback: paredes rigidas tipicas
                fs = aa_mod.schroeder_frequency(V, S, alpha=alpha)
                src_txt = f"α={alpha} fijo (fallback: sin materiales)"
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
                if n_weyl == 0:
                    self.lbl_modes_weyl.setText(
                        "≈ ? modos hasta f_Schroeder (V o f inválidos)")
                elif n_weyl > cap:
                    self.lbl_modes_weyl.setText(
                        f"≈ {n_weyl} modos hasta f_S (Weyl) · "
                        f"cap actual del spinbox: {cap}. "
                        f"Considerá refinar la malla o aceptar cobertura parcial.")
                else:
                    self.lbl_modes_weyl.setText(
                        f"≈ {n_weyl} modos hasta f_S (Weyl) · "
                        f"si querés cobertura completa, pedí ese N")
            # Si ya hay modos, mostrar tambien el cruce numerico (2c §9) al lado.
            self._update_modal_crossover()
            return fs
        except Exception as e:
            self._log(f"Error Schroeder: {e}")
            return None

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
                f = float(self.modal_result.freqs[mode_idx])
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
            f = float(self.modal_result.freqs[mode_idx])
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
        self._refresh_patches_summary()
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
        self._update_modal_crossover()

    def _refresh_patches_summary(self):
        n = len(self._patches)
        if n == 0:
            self.lbl_patch_summary.setText("Sin parches")
        else:
            area = sum(p.area for p in self._patches)
            self.lbl_patch_summary.setText(
                f"{n} parche(s) · {area:.2f} m² · absorción con cuadratura fina activa")
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
            verts, faces, colors = [], [], []
            for p in patches:
                pv, pf = self._patch_quad(p, centroid)
                if pv is None:
                    continue
                base = len(verts)
                verts.extend(pv)
                col = pdlg._material_color(p.material_name, alpha=180)
                rgba = (col.red() / 255.0, col.green() / 255.0,
                        col.blue() / 255.0, 0.85)
                for (i, j, k) in pf:
                    faces.append([base + i, base + j, base + k])
                    colors.append(rgba)
            if not faces:
                self.viewer.set_patches(None)
                return
            self.viewer.set_patches(_np.array(verts), _np.array(faces),
                                    _np.array(colors))
        except Exception as e:
            self._log(f"Aviso overlay parches: {e}")

    def _patch_quad(self, p, centroid):
        """Geometria 3D de UN parche: (verts (Nv,3), faces (Nf,3) locales).

        Offset chico hacia el interior para no quedar exactamente sobre la cara.
        Triangula el poligono (ear clipping) para soportar no convexos."""
        import absorption_patch as _ap
        na = p.normal_axis
        off = 0.01
        if centroid is not None:
            off = 0.01 if centroid[na] >= p.plane_coord else -0.01
        uv = p.polygon_uv()
        tris = _ap.triangulate_uv(uv)
        if not tris:
            return None, None
        verts = []
        for (u, v) in uv:
            c = [0.0, 0.0, 0.0]
            c[na] = p.plane_coord + off
            c[p.u_axis] = u
            c[p.v_axis] = v
            verts.append(c)
        return verts, [list(t) for t in tris]

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

    def _on_face_materials_applied(self):
        """Refresca el resumen y recomputa xi tras editar materiales."""
        self._refresh_materials_summary()
        # El material de un parche pudo cambiar desde la tabla -> recolorear overlay.
        self._refresh_patch_overlay()
        # Recalcular xi si los modos ya estaban resueltos
        if self.modal_result is not None:
            self._xi_per_mode = self._compute_xi_from_materials()
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
            # RT60 medio
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
            rt = self._sabine_rt60(V, groups, g2m)
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
            self.lbl_rt60.setText(
                f"RT60 medio: {rt_avg:.2f} s   ·   @500 Hz: {rt500:.2f} s"
                f"{br_txt}   (V={V:.1f} m³)"
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

    def _compute_xi_from_materials(self):
        """Calcula xi_n por modo usando el mapeo POR CARA (FaceMaterialMap).

        Si no hay asignaciones (mapa vacio), todos los grupos contribuyen con
        alpha=0.03 (default rigido conservador) — el resultado es equivalente
        a una sala de hormigon sin tratar.
        """
        if self.modal_result is None:
            return None
        try:
            groups, verts, tris = self._get_face_groups()
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
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

    def _rt60_callable(self):
        """Devuelve un callable f->RT60 [s] (log-interp de la Sabine por cara),
        o None si no hay geometria/RT. Para el cruce modal numerico (2c §9)."""
        try:
            groups, verts, tris = self._get_face_groups()
            if not groups:
                return None
            V = aa.compute_mesh_volume(verts, tris)
            g2m = self._group_to_material_dict(groups)
            rt = self._sabine_rt60(V, groups, g2m)   # {banda: RT60}
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
