"""
dba_dialog.py
=============

Herramienta de GUI para analizar SUBS ENFRENTADOS (DBA / CABS) sobre la caja
rectangular de la sala (wiring de S1+S5, ver plan_modelo_fuente.md). Es una
herramienta de análisis autónoma: usa el motor headless `dba.compute_dba`
(base modal analítica rectangular, exacta) y NO toca el solver FEM de la app
(por la decisión S1 = base rectangular, que evita la integral sobre malla
escalonada). Compara CABS off (array frontal) vs on (front + rear).
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QDialogButtonBox,
    QApplication)

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    import matplotlib.pyplot as plt
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False

try:
    from style import apply_dialog_theme
except Exception:
    def apply_dialog_theme(w):
        pass

from dba import compute_dba

_AXIS_NAMES = ["X (ancho)", "Y (largo)", "Z (alto)"]


class DBADialog(QDialog):
    """Analiza subs enfrentados sobre una sala rectangular (dims = caja AABB).

    Recibe dims=(Lx,Ly,Lz) y el receptor YA relativo a la esquina mínima de la
    caja (coordenadas [0,L]). Muestra FRF antes/después + métricas de colapso.
    """

    def __init__(self, dims, receiver, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)
        self.setWindowTitle("Subs enfrentados (DBA / CABS)")
        self._dims = tuple(float(x) for x in dims)
        self._receiver = tuple(float(x) for x in receiver)

        lay = QVBoxLayout(self)
        info = QLabel(
            "Analiza <b>subs enfrentados</b> (DBA/CABS) sobre la caja rectangular "
            f"de la sala ({self._dims[0]:.1f}×{self._dims[1]:.1f}×{self._dims[2]:.1f} m). "
            "Un array frontal lanza una onda plana; el trasero la absorbe. "
            "Compara CABS <i>off</i> (frente solo) vs <i>on</i> (frente + trasero).")
        info.setWordWrap(True)
        lay.addWidget(info)

        grp = QGroupBox("Configuración")
        fl = QFormLayout(grp)
        self.combo_axis = QComboBox()
        for i, nm in enumerate(_AXIS_NAMES):
            self.combo_axis.addItem(nm, i)
        self.combo_axis.setCurrentIndex(int(np.argmax(self._dims)))  # eje más largo
        fl.addRow("Eje de enfrentamiento:", self.combo_axis)

        self.sb_nx = QSpinBox(); self.sb_nx.setRange(1, 8); self.sb_nx.setValue(4)
        self.sb_nz = QSpinBox(); self.sb_nz.setRange(1, 8); self.sb_nz.setValue(4)
        fl.addRow("Subs por pared (transversal A):", self.sb_nx)
        fl.addRow("Subs por pared (transversal B):", self.sb_nz)

        self.combo_drive = QComboBox()
        self.combo_drive.addItem("Mínimos cuadrados (Santillán)", "ls")
        self.combo_drive.addItem("Retardo + inversión (naive)", "naive")
        fl.addRow("Drive del array trasero:", self.combo_drive)

        self.sb_xi = QDoubleSpinBox()
        self.sb_xi.setRange(0.002, 0.3); self.sb_xi.setDecimals(3)
        self.sb_xi.setSingleStep(0.005); self.sb_xi.setValue(0.03)
        fl.addRow("ξ (amortiguamiento modal):", self.sb_xi)

        self.sb_fmax = QDoubleSpinBox()
        self.sb_fmax.setRange(50.0, 400.0); self.sb_fmax.setValue(180.0)
        self.sb_fmax.setSuffix(" Hz")
        fl.addRow("f máx:", self.sb_fmax)
        lay.addWidget(grp)

        self.btn = QPushButton("Calcular")
        self.btn.setObjectName("PrimaryButton")
        self.btn.clicked.connect(self._calc)
        lay.addWidget(self.btn)

        self.lbl_res = QLabel("Elegí la configuración y tocá «Calcular».")
        self.lbl_res.setWordWrap(True)
        lay.addWidget(self.lbl_res)

        self._canvas = None
        if _HAS_MPL:
            self._fig, self._ax = plt.subplots(figsize=(6.0, 3.2), dpi=90)
            self._fig.patch.set_facecolor("#ffffff")
            self._canvas = FigureCanvas(self._fig)
            self._canvas.setMinimumHeight(240)
            lay.addWidget(self._canvas)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # -----------------------------------------------------------------------
    def _calc(self):
        axis = int(self.combo_axis.currentData())
        rec = [min(max(self._receiver[k], 0.05), self._dims[k] - 0.05)
               for k in range(3)]
        self.btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = compute_dba(
                self._dims, rec, axis=axis,
                n_x=self.sb_nx.value(), n_z=self.sb_nz.value(),
                drive=self.combo_drive.currentData(), xi=self.sb_xi.value(),
                fmin=20.0, fmax=self.sb_fmax.value(), n_freq=250)
        except Exception as e:
            self.lbl_res.setText(f"<span style='color:#b00'>Error: {e}</span>")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn.setEnabled(True)

        def _d(a, b):
            return f"{a:.1f} → <b>{b:.1f}</b>"
        self.lbl_res.setText(
            f"<b>CABS off → on</b> ({r['n_sources']} subs, {r['n_modes']} modos):<br>"
            f"Planitud espectral σ|H(f)|: {_d(r['flat_before'], r['flat_after'])} dB<br>"
            f"Varianza espacial σ(SPL): {_d(r['spatial_before'], r['spatial_after'])} dB<br>"
            f"Decay t(−15 dB): {r['decay_before']*1e3:.0f} → "
            f"<b>{r['decay_after']*1e3:.0f}</b> ms")

        if self._canvas is not None:
            self._ax.clear()
            fa = r["freq"]
            self._ax.plot(fa, r["Hb_db"] - np.mean(r["Hb_db"]), "--",
                          color="#888", lw=1.0, label="CABS off")
            self._ax.plot(fa, r["Ha_db"] - np.mean(r["Ha_db"]), "-",
                          color="#1f77b4", lw=1.5, label="CABS on")
            self._ax.set_xlabel("frecuencia [Hz]")
            self._ax.set_ylabel("FRF relativa [dB]")
            self._ax.set_title("Respuesta en frecuencia en el receptor")
            self._ax.grid(alpha=0.3)
            self._ax.legend(fontsize=8)
            self._fig.tight_layout()
            self._canvas.draw()
