"""
dba_dialog.py
=============

Herramienta de GUI para analizar SUBS ENFRENTADOS (DBA / CABS) sobre la caja
rectangular de la sala (wiring de S1+S5, ver plan_modelo_fuente.md). Es una
herramienta de análisis autónoma: usa el motor headless `dba.compute_dba`
(base modal analítica rectangular, exacta) y NO toca el solver FEM de la app
(por la decisión S1 = base rectangular, que evita la integral sobre malla
escalonada). Compara CABS off (array frontal) vs on (front + rear).

Las métricas se miden en la BANDA VÁLIDA [fmin, f_max=c/d]: arriba de f_max hay
aliasing espacial (el array no puede sintetizar la onda plana) y el DBA no aplica.
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QDialogButtonBox,
    QApplication, QFileDialog, QSizePolicy, QMessageBox)

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
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
    caja (coordenadas [0,L]). Muestra FRF antes/después + métricas de colapso,
    medidas en la banda válida [fmin, f_max=c/d].
    """

    def __init__(self, dims, receiver, parent=None, apply_callback=None):
        super().__init__(parent)
        apply_dialog_theme(self)
        self.setWindowTitle("Subs enfrentados (DBA / CABS)")
        self._dims = tuple(float(x) for x in dims)
        self._receiver = tuple(float(x) for x in receiver)
        self._apply_callback = apply_callback
        self._last = None

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
        fl.addRow("Subs por pared, transversal A:", self.sb_nx)
        fl.addRow("Subs por pared, transversal B:", self.sb_nz)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color:#555; font-size:8pt;")
        fl.addRow("", self.lbl_count)
        self.sb_nx.valueChanged.connect(self._refresh_count)
        self.sb_nz.valueChanged.connect(self._refresh_count)
        self.combo_axis.currentIndexChanged.connect(self._refresh_count)

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
        fl.addRow("f máx del análisis:", self.sb_fmax)
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
            self._fig, self._ax = plt.subplots(figsize=(6.2, 3.2), dpi=90)
            self._fig.patch.set_facecolor("#ffffff")
            self._canvas = FigureCanvas(self._fig)
            self._canvas.setMinimumHeight(240)
            lay.addWidget(NavigationToolbar(self._canvas, self))
            lay.addWidget(self._canvas)
            brow = QHBoxLayout()
            brow.addStretch(1)
            for fmt in ("PNG", "SVG", "PDF", "CSV"):
                b = QPushButton(f"Exportar {fmt}")
                b.setMinimumWidth(120)
                b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                b.clicked.connect(lambda _=False, f=fmt.lower(): self._export(f))
                brow.addWidget(b)
            lay.addLayout(brow)

        if self._apply_callback is not None:
            self.btn_apply = QPushButton("Aplicar a la sala  (crear las fuentes)")
            self.btn_apply.setToolTip(
                "Crea las fuentes puntuales front+rear del DBA en la lista de "
                "fuentes de la sala, con el drive elegido (naive = delay+inversión; "
                "LS = curva q(f) por fuente). Reemplaza las fuentes DBA previas.")
            self.btn_apply.clicked.connect(self._apply)
            lay.addWidget(self.btn_apply)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._refresh_count()

    def _apply(self):
        from dba import build_dba_sources
        axis = int(self.combo_axis.currentData())
        n = self.sb_nx.value() * self.sb_nz.value()
        drv = self.combo_drive.currentData()
        drv_txt = "LS (Santillán)" if drv == "ls" else "retardo + inversión (naive)"
        if QMessageBox.question(
                self, "Aplicar DBA a la sala",
                f"Se crearán <b>{2*n} fuentes</b> ({n} al frente + {n} atrás) "
                f"con drive <b>{drv_txt}</b>.<br><br>"
                "Reemplaza las fuentes DBA previas (las demás se conservan). "
                "¿Continuar?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            specs = build_dba_sources(
                self._dims, axis=axis, n_x=self.sb_nx.value(),
                n_z=self.sb_nz.value(), drive=drv, xi=self.sb_xi.value(),
                fmin=20.0, fmax=self.sb_fmax.value())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "DBA", f"No se pudo construir el preset:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        try:
            self._apply_callback(specs)
        except Exception as e:
            QMessageBox.warning(self, "DBA", f"No se pudo aplicar a la sala:\n{e}")
            return
        QMessageBox.information(
            self, "DBA aplicado",
            f"{len(specs)} fuentes creadas en la sala (etiquetas DBA-F*/DBA-R*).")

    # -----------------------------------------------------------------------
    def _refresh_count(self):
        from dba import alias_fmax
        n = self.sb_nx.value() * self.sb_nz.value()
        fmx = alias_fmax(self._dims, int(self.combo_axis.currentData()),
                         self.sb_nx.value(), self.sb_nz.value())
        fmx_txt = "∞" if not np.isfinite(fmx) else f"{fmx:.0f} Hz"
        self.lbl_count.setText(
            f"= {n} subs al frente + {n} atrás ({2*n} en total)  ·  "
            f"f_max = c/d ≈ {fmx_txt}")

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
                fmin=20.0, fmax=self.sb_fmax.value())
        except Exception as e:
            self.lbl_res.setText(f"<span style='color:#b00'>Error: {e}</span>")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn.setEnabled(True)
        self._last = r

        band_txt = (f"toda la banda (f_max = {r['f_max']:.0f} Hz ≥ f análisis)"
                    if r["band_hi"] >= self.sb_fmax.value() - 1e-6
                    else f"20–{r['band_hi']:.0f} Hz  (f_max = c/d = {r['f_max']:.0f} Hz)")

        def _d(a, b):
            arrow = "↓" if b < a else "↑"
            return f"{a:.1f} → <b>{b:.1f}</b> {arrow}"
        msg = (
            f"<b>Banda válida:</b> {band_txt}<br>"
            f"<b>CABS off → on</b> ({r['n_front']} front + {r['n_rear']} rear subs, "
            f"{r['n_modes']} modos):<br>"
            f"Planitud espectral σ|H(f)|: {_d(r['flat_before'], r['flat_after'])} dB<br>"
            f"Varianza espacial σ(SPL): {_d(r['spatial_before'], r['spatial_after'])} dB")
        if r["band_hi"] < self.sb_fmax.value() - 1e-6:
            msg += ("<br><span style='color:#555; font-size:8pt;'>El DBA solo "
                    "ecualiza hasta f_max; por encima hay aliasing espacial. Más "
                    "subs por pared → f_max mayor (f_max = c / espaciado).</span>")
        self.lbl_res.setText(msg)

        if self._canvas is not None:
            self._draw(r)

    def _draw(self, r):
        self._ax.clear()
        fa = r["freq"]
        self._ax.plot(fa, r["Hb_db"] - np.mean(r["Hb_db"]), "--",
                      color="#888", lw=1.0, label="CABS off")
        self._ax.plot(fa, r["Ha_db"] - np.mean(r["Ha_db"]), "-",
                      color="#1f77b4", lw=1.5, label="CABS on")
        # marca f_max y sombrea la región de aliasing
        if r["band_hi"] < fa[-1]:
            self._ax.axvspan(r["band_hi"], fa[-1], color="#f2c14e", alpha=0.15)
            self._ax.axvline(r["band_hi"], color="#b45309", ls=":", lw=1.0)
            self._ax.text(r["band_hi"], self._ax.get_ylim()[1],
                          " f_max (aliasing →)", color="#b45309",
                          fontsize=7, va="top")
        self._ax.set_xlabel("frecuencia [Hz]")
        self._ax.set_ylabel("FRF relativa [dB]")
        self._ax.set_title("Respuesta en frecuencia en el receptor")
        self._ax.grid(alpha=0.3)
        self._ax.legend(fontsize=8)
        self._fig.tight_layout()
        self._canvas.draw()

    def _export(self, fmt: str):
        if self._last is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar como {fmt.upper()}", f"dba.{fmt}",
            f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        if fmt == "csv":
            r = self._last
            import csv
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["freq_hz", "cabs_off_db", "cabs_on_db"])
                for i in range(len(r["freq"])):
                    w.writerow([f"{r['freq'][i]:.3f}", f"{r['Hb_db'][i]:.4f}",
                                f"{r['Ha_db'][i]:.4f}"])
        elif _HAS_MPL:
            self._fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
