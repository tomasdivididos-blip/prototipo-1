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
    QApplication, QFileDialog, QSizePolicy, QMessageBox, QScrollArea, QWidget)

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

    def __init__(self, dims, receiver, parent=None, apply_callback=None,
                 eval_context=None):
        super().__init__(parent)
        apply_dialog_theme(self)
        self.setWindowTitle("Subs enfrentados (DBA / CABS)")
        self._dims = tuple(float(x) for x in dims)
        self._receiver = tuple(float(x) for x in receiver)
        self._apply_callback = apply_callback
        # Contexto para "Evaluar mis fuentes cargadas" (None -> solo diseño).
        # dict: sources() -> [OmniSource], walls_fn(freq) -> [Wall],
        # receiver_world, origin, f_schroeder.
        self._eval_ctx = eval_context
        self._last = None

        # Contenido en un QScrollArea (el diálogo puede ser alto: config + gráfico
        # + export) para que Aplicar/Close queden SIEMPRE alcanzables abajo y no
        # se pase de la pantalla (evita el warning de setGeometry).
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        lay = QVBoxLayout(content)
        info = QLabel(
            "Analiza <b>subs enfrentados</b> (DBA/CABS) sobre la caja rectangular "
            f"de la sala ({self._dims[0]:.1f}×{self._dims[1]:.1f}×{self._dims[2]:.1f} m). "
            "Un array frontal lanza una onda plana; el trasero la absorbe. "
            "Compara CABS <i>off</i> (frente solo) vs <i>on</i> (frente + trasero).")
        info.setWordWrap(True)
        lay.addWidget(info)

        # Modo: diseñar el array ideal (histórico) vs evaluar las fuentes que el
        # usuario ya cargó contra el criterio CABS (respuesta total = SBIR+modos).
        self.combo_mode = None
        self.combo_criterion = None
        if self._eval_ctx is not None:
            mrow = QHBoxLayout()
            mrow.addWidget(QLabel("Modo:"))
            self.combo_mode = QComboBox()
            self.combo_mode.addItem("Diseñar array ideal", "design")
            self.combo_mode.addItem("Evaluar mis fuentes cargadas", "eval")
            self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
            mrow.addWidget(self.combo_mode, 1)
            lay.addLayout(mrow)

            # Criterio (solo modo evaluar): DBA (drive canónico fijado) vs CABS
            # (trasero manejado). El MISMO criterio se usa para evaluar Y para
            # optimizar, así concuerdan por construcción (cierra el bug del delay
            # 2x). Oculto hasta entrar en modo evaluar.
            crow = QHBoxLayout()
            self.lbl_criterion = QLabel("Criterio:")
            crow.addWidget(self.lbl_criterion)
            self.combo_criterion = QComboBox()
            self.combo_criterion.addItem("DBA (subs adelante y atrás)", "dba")
            self.combo_criterion.addItem("CABS (trasero manejado)", "cabs")
            self.combo_criterion.setToolTip(
                "DBA: el trasero reproduce el frente retardado L/c e invertido "
                "(drive canónico; al «Optimizar» se fija ese drive, "
                "no un delay libre). CABS: el trasero es manejado, su drive queda "
                "libre y se juzga por el colapso de la respuesta, no por el retardo "
                "L/c. El mismo criterio se usa para evaluar y para optimizar.")
            self.combo_criterion.currentIndexChanged.connect(
                self._on_criterion_changed)
            crow.addWidget(self.combo_criterion, 1)
            lay.addLayout(crow)
            self.lbl_criterion.setVisible(False)
            self.combo_criterion.setVisible(False)

        grp = QGroupBox("Configuración")
        fl = QFormLayout(grp)
        self.combo_axis = QComboBox()
        for i, nm in enumerate(_AXIS_NAMES):
            self.combo_axis.addItem(nm, i)
        self.combo_axis.setCurrentIndex(int(np.argmax(self._dims)))  # eje más largo
        fl.addRow("Eje de enfrentamiento:", self.combo_axis)

        self.sb_nx = QSpinBox(); self.sb_nx.setRange(1, 8); self.sb_nx.setValue(4)
        self.sb_nz = QSpinBox(); self.sb_nz.setRange(1, 8); self.sb_nz.setValue(4)
        # Rótulos dinámicos: muestran el eje real de cada dirección de la pared
        # (se actualizan al cambiar el eje de enfrentamiento, en _refresh_count).
        self.lbl_na = QLabel("Cantidad de subs en pared (dir. A):")
        self.lbl_nb = QLabel("Cantidad de subs en pared (dir. B):")
        fl.addRow(self.lbl_na, self.sb_nx)
        fl.addRow(self.lbl_nb, self.sb_nz)
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
        self.btn.clicked.connect(self._on_calc)
        lay.addWidget(self.btn)

        # Optimizar fuentes libres (item 6): solo en modo evaluar. Mueve las
        # variables liberadas (free_vars) de cada fuente para minimizar el
        # criterio CABS. Oculto hasta entrar en modo evaluar.
        self.btn_opt = None
        self.lbl_opt_vars = None
        if self._eval_ctx is not None:
            self.btn_opt = QPushButton("Optimizar")
            self.btn_opt.setToolTip(
                "Ajusta las variables que marcaste como libres en cada fuente "
                "(Optimizar: posición/delay/corte/filtro/polaridad/nivel), para "
                "minimizar la planitud + varianza espacial CABS. La posición se "
                "restringe al recinto. Las fuentes sin nada tildado quedan fijas.")
            self.btn_opt.clicked.connect(self._optimize)
            self.btn_opt.setVisible(False)
            lay.addWidget(self.btn_opt)
            # Indicacion de que se va a optimizar POR FUENTE (leido de los
            # free_vars que el usuario tildo en el panel de cada fuente).
            self.lbl_opt_vars = QLabel("")
            self.lbl_opt_vars.setWordWrap(True)
            self.lbl_opt_vars.setStyleSheet("color:#555; font-size:8pt;")
            self.lbl_opt_vars.setVisible(False)
            lay.addWidget(self.lbl_opt_vars)

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
            outer.addWidget(self.btn_apply)      # fuera del scroll: siempre visible

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)                      # fuera del scroll
        # alto inicial acotado a la pantalla (evita el warning de setGeometry)
        try:
            avail = QApplication.primaryScreen().availableGeometry().height()
        except Exception:
            avail = 900
        self.resize(600, min(720, int(avail * 0.9)))
        self._refresh_count()

    # -----------------------------------------------------------------------
    # Modo evaluación
    # -----------------------------------------------------------------------
    def _mode(self):
        return self.combo_mode.currentData() if self.combo_mode else "design"

    def _criterion(self):
        """Criterio elegido (dba|cabs); el MISMO va a evaluar y a optimizar."""
        return (self.combo_criterion.currentData()
                if self.combo_criterion is not None else "dba")

    def _on_mode_changed(self):
        """Habilita/deshabilita controles segun el modo. Los subs/pared y el drive
        son solo para DISEÑAR; en modo evaluar el array se toma de las fuentes."""
        ev = self._mode() == "eval"
        for w in (self.sb_nx, self.sb_nz, self.combo_drive):
            w.setEnabled(not ev)
        self.btn.setText("Evaluar" if ev else "Calcular")
        if hasattr(self, "btn_apply"):
            self.btn_apply.setVisible(not ev)
        if self.btn_opt is not None:
            self.btn_opt.setVisible(ev)
        if self.lbl_opt_vars is not None:
            self.lbl_opt_vars.setVisible(ev)
            if ev:
                self._refresh_opt_vars_label()
        if self.combo_criterion is not None:
            self.combo_criterion.setVisible(ev)
            self.lbl_criterion.setVisible(ev)
        if ev:
            # Auto-detectar el eje donde las fuentes se enfrentan (no depender del
            # default = eje mas largo). El usuario lo puede cambiar despues.
            try:
                import dba_evaluate as dev
                ctx = self._eval_ctx or {}
                srcs = [s for s in ctx.get("sources", lambda: [])()
                        if getattr(s, "active", True)]
                if srcs:
                    ax = dev.best_axis(srcs, self._dims,
                                       ctx.get("origin", (0.0, 0.0, 0.0)))
                    j = self.combo_axis.findData(ax)
                    if j >= 0:
                        self.combo_axis.setCurrentIndex(j)
            except Exception:
                pass
        if not ev:
            self.lbl_res.setText("Elegí la configuración y tocá «Calcular».")
            return
        self._refresh_feasibility_head()

    def _on_criterion_changed(self):
        """Al cambiar el criterio en modo evaluar, refresca el aviso (el criterio
        cambia las condiciones: DBA pide subs 2+2, CABS 2 atras + fuente adelante)."""
        if self._mode() == "eval":
            self._refresh_feasibility_head()

    def _refresh_feasibility_head(self):
        """Heads-up de factibilidad del CRITERIO elegido, apenas se entra al modo o
        se cambia de criterio (barato, sin computar respuesta)."""
        crit = self._criterion()
        head = (f"Criterio <b>{crit.upper()}</b>. Tocá «Evaluar» para analizar las "
                "fuentes cargadas, o «Optimizar» para reacomodar las "
                "que marcaste.")
        try:
            import dba_evaluate as dev
            ctx = self._eval_ctx or {}
            srcs = [s for s in ctx.get("sources", lambda: [])()
                    if getattr(s, "active", True)]
            if srcs:
                feasible, reasons, _ax = dev.cabs_feasibility(
                    srcs, self._dims, origin=ctx.get("origin", (0.0, 0.0, 0.0)),
                    axis=int(self.combo_axis.currentData()),
                    criterion=crit)
                if not feasible:
                    head = (f"<span style='color:#b45309;'><b>Aviso:</b> esta "
                            f"configuración no puede satisfacer {crit.upper()}:"
                            "</span><br>"
                            + "<br>".join(f"• {x}" for x in reasons)
                            + "<br>Podés evaluarla igual (uniformidad general) o "
                            "arreglar la config.")
        except Exception:
            pass
        self.lbl_res.setText(head)

    def _refresh_opt_vars_label(self):
        """Lista, por fuente, que variables va a tocar «Optimizar» (leidas de los
        free_vars que el usuario tildo en «Optimizar:» del panel de cada fuente).
        Asi el boton dice solo «Optimizar» y la indicacion vive debajo."""
        if self.lbl_opt_vars is None:
            return
        _names = {"pos": "posición", "delay": "delay", "fc": "corte",
                  "polarity": "polaridad", "filter": "filtro", "level": "nivel"}
        ctx = self._eval_ctx or {}
        srcs = [s for s in ctx.get("sources", lambda: [])()
                if getattr(s, "active", True)]
        libres, fijas = [], []
        for i, s in enumerate(srcs):
            label = getattr(s, "label", "") or f"S{i+1}"
            fv = [k for k in ("pos", "delay", "fc", "polarity", "filter", "level")
                  if k in (getattr(s, "free_vars", frozenset()) or frozenset())]
            if fv:
                libres.append(f"<b>{label}</b>: "
                              + ", ".join(_names[k] for k in fv))
            else:
                fijas.append(label)
        if not libres:
            self.lbl_opt_vars.setText(
                "Se optimizan los parámetros tildados en «Optimizar:» del panel "
                "de cada fuente. <b>Ninguna fuente tiene variables libres</b>: "
                "editá tus fuentes y tildá qué puede mover el optimizador.")
            return
        txt = "Se va a optimizar: " + " · ".join(libres)
        if fijas:
            txt += f"  ·  fijas: {', '.join(fijas)}"
        self.lbl_opt_vars.setText(txt)

    def _on_calc(self):
        if self._mode() == "eval":
            self._calc_eval()
        else:
            self._calc()

    def _calc_eval(self):
        """Evalua las fuentes reales del usuario contra CABS (respuesta total)."""
        import dba_evaluate as dev
        ctx = self._eval_ctx or {}
        sources = [s for s in ctx.get("sources", lambda: [])()
                   if getattr(s, "active", True)]
        if not sources:
            self.lbl_res.setText(
                "<span style='color:#b00'>No hay fuentes activas en la sala. "
                "Cargá tus subs (y asignáles Tipo Sub-Woofer/Woofer) primero."
                "</span>")
            return
        axis = int(self.combo_axis.currentData())
        self.btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = dev.evaluate_cabs(
                sources, self._dims, ctx.get("receiver_world", self._receiver),
                origin=ctx.get("origin", (0.0, 0.0, 0.0)),
                walls=ctx.get("walls_fn"), axis=axis,
                fmin=20.0, fmax=self.sb_fmax.value(), xi=self.sb_xi.value(),
                f_schroeder=ctx.get("f_schroeder"), criterion=self._criterion())
        except Exception as e:
            self.lbl_res.setText(f"<span style='color:#b00'>Error: {e}</span>")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn.setEnabled(True)
        self._last = None                    # el export CSV es del modo diseño
        self._last_eval = r
        self._show_eval(r)
        if self._canvas is not None:
            self._draw_eval(r)

    def _optimize(self):
        """Optimiza las variables libres (free_vars) de las fuentes (item 6)."""
        import cabs_optimize as copt
        ctx = self._eval_ctx or {}
        sources = list(ctx.get("sources", lambda: [])())
        if not any(getattr(s, "free_vars", None) for s in sources
                   if getattr(s, "active", True)):
            self.lbl_res.setText(
                "<span style='color:#b00'>Ninguna fuente tiene variables libres. "
                "Editá tus subs y tildá en «Optimizar:» qué puede mover el "
                "optimizador (posición/delay/corte/filtro). Sin nada tildado, la "
                "fuente queda fija.</span>")
            return
        axis = int(self.combo_axis.currentData())
        # Pre-chequeo de factibilidad CABS (barato, estructural). Estas condiciones
        # son invariantes bajo la optimizacion, asi que si fallan hay que avisar
        # ANTES de mover nada: el optimizador puede mejorar la uniformidad general
        # pero NO va a lograr la cancelacion modal del CABS.
        import dba_evaluate as _dev
        feasible, reasons, _ax = _dev.cabs_feasibility(
            sources, self._dims, origin=ctx.get("origin", (0.0, 0.0, 0.0)),
            axis=axis, criterion=self._criterion())
        if not feasible:
            msg = ("<b>Con esta configuración no se puede lograr CABS aunque "
                   "optimice:</b><br>"
                   + "<br>".join(f"• {x}" for x in reasons)
                   + "<br><br>El optimizador igual puede mejorar la <b>uniformidad "
                   "general</b> (planitud + varianza espacial), pero <b>no va a "
                   "lograr la cancelación modal del CABS</b>.<br><br>¿Optimizar "
                   "igual para uniformidad, o cancelar y arreglar la config?")
            box = QMessageBox(self)
            box.setWindowTitle("Configuración no apta para CABS")
            box.setIcon(QMessageBox.Warning)
            box.setTextFormat(Qt.RichText)
            box.setText(msg)
            b_go = box.addButton("Optimizar igual", QMessageBox.AcceptRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is not b_go:
                self.lbl_res.setText(
                    "Optimización cancelada. Revisá: " + " ".join(reasons))
                return
        self.btn_opt.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = copt.optimize_cabs(
                sources, self._dims, ctx.get("receiver_world", self._receiver),
                origin=ctx.get("origin", (0.0, 0.0, 0.0)),
                walls=ctx.get("walls_fn"), axis=axis,
                fmin=20.0, fmax=self.sb_fmax.value(), xi=self.sb_xi.value(),
                f_schroeder=ctx.get("f_schroeder"), criterion=self._criterion(),
                inside_fn=ctx.get("inside_fn"))
        except Exception as e:
            self.lbl_res.setText(f"<span style='color:#b00'>Error: {e}</span>")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_opt.setEnabled(True)
        self._last_opt = r
        c0 = r["before"]["flat"] + r["before"]["spatial"]
        c1 = r["after"]["flat"] + r["after"]["spatial"]
        lines = [f"<b>Optimización de {r['n_free']} fuente(s) libre(s)</b> "
                 f"(eje {_AXIS_NAMES[r['axis']]}):",
                 f"Planitud+varianza: {c0:.2f} → <b>{c1:.2f}</b> dB "
                 + ("(mejora)" if r["improved"] else "(sin mejora)"),
                 f"&nbsp;&nbsp;planitud {r['before']['flat']:.2f}→{r['after']['flat']:.2f}, "
                 f"varianza {r['before']['spatial']:.2f}→{r['after']['spatial']:.2f}"]
        if r["changes"]:
            lines.append("<b>Cambios propuestos:</b>")
            lines += [f"&nbsp;• {c}" for c in r["changes"]]
        self.lbl_res.setText("<br>".join(lines))
        apply_cb = ctx.get("apply_optimized")
        if r["improved"] and apply_cb is not None:
            if QMessageBox.question(
                    self, "Aplicar optimización",
                    f"El optimizador bajó el criterio CABS de {c0:.2f} a {c1:.2f} dB.\n\n"
                    "¿Aplicar los cambios a las fuentes libres de la sala? "
                    "(las fuentes fijas no se tocan).",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                try:
                    apply_cb(r["optimized"])
                    QMessageBox.information(self, "Optimización aplicada",
                                            "Fuentes libres reubicadas/ajustadas.")
                except Exception as e:
                    QMessageBox.warning(self, "Optimización",
                                        f"No se pudo aplicar:\n{e}")

    def _show_eval(self, r):
        verdict = ("<span style='color:#2e7d32;'><b>PASA</b></span>" if r["passed"]
                   else "<span style='color:#b00;'><b>NO cumple CABS</b></span>")
        na, nb = r["ideal_grid"]
        crit = str(r.get("criterion", "dba")).upper()
        lines = [f"<b>Veredicto {crit}:</b> {verdict} "
                 f"(eje {_AXIS_NAMES[r['axis']]}, {r['n_modes']} modos)"]
        # clasificacion, con la POLARIDAD de cada fuente: el calculo la usa, el
        # cartel ahora la muestra ("[180°]" = invertida, "[0°]" = normal).
        roles = r["roles"]

        def _lab(ro):
            pol = int(getattr(getattr(ro, "src", None), "polarity", 1) or 1)
            return ro.label + (" [180°]" if pol < 0 else " [0°]")

        fr = [_lab(ro) for ro in roles if ro.role == "front"]
        re = [_lab(ro) for ro in roles if ro.role == "rear"]
        ot = [_lab(ro) for ro in roles if ro.role == "other"]
        lines.append(
            f"<b>Clasificación</b> (con polaridad)<b>:</b> "
            f"front: {', '.join(fr) or '—'} · "
            f"rear: {', '.join(re) or '—'} · otras: {', '.join(ot) or '—'}")
        lines.append("<b>Condiciones:</b>")
        for it in r["checklist"]:
            mark = "✓" if it["ok"] else "✕"
            col = "#2e7d32" if it["ok"] else "#b00"
            lines.append(f"&nbsp;<span style='color:{col};'>{mark}</span> "
                         + it["text"])
        lines.append(
            f"<span style='color:#555; font-size:8pt;'>Ideal de referencia: "
            f"array LS {na}×{nb} por pared (mismo motor). El «ideal» es el techo "
            f"alcanzable para esta sala.</span>")
        self.lbl_res.setText("<br>".join(lines))

    def _draw_eval(self, r):
        self._ax.clear()
        fa = r["freq"]
        real = r["total_db_mean_real"] - np.mean(r["total_db_mean_real"])
        ideal = r["total_db_mean_ideal"] - np.mean(r["total_db_mean_ideal"])
        self._ax.plot(fa, ideal, "--", color="#888", lw=1.0,
                      label="CABS ideal (referencia)")
        self._ax.plot(fa, real, "-", color="#1f77b4", lw=1.5,
                      label="tus fuentes (total)")
        if r["band_hi"] < fa[-1] and np.isfinite(r["f_max"]):
            self._ax.axvspan(r["band_hi"], fa[-1], color="#f2c14e", alpha=0.15,
                             label=f"aliasing espacial (> f_max = {r['f_max']:.0f} Hz)")
            self._ax.axvline(r["band_hi"], color="#b45309", ls=":", lw=1.0)
        if r.get("f_schroeder"):
            self._ax.axvline(r["f_schroeder"], color="#444", ls="-.", lw=0.8,
                             label=f"f_S ≈ {r['f_schroeder']:.0f} Hz")
        # Overlay de corregibilidad EQ (C13/C21): capa VISUAL (CABS mantiene sus
        # métricas propias; el veredicto EQ es una propiedad de la sala). Lo pasa
        # el panel en el eval_context (best-effort, None si no hay modos).
        try:
            from plot_utils import draw_correctability_overlay
            draw_correctability_overlay(self._ax, (self._eval_ctx or {}).get("eqc"))
        except Exception:
            pass
        self._ax.set_xlabel("frecuencia [Hz]")
        self._ax.set_ylabel("respuesta TOTAL (SBIR+modos) [dB]")
        self._ax.set_title("Respuesta total media (zona de escucha)")
        self._ax.grid(alpha=0.3)
        self._ax.legend(fontsize=8)
        self._fig.tight_layout()
        self._canvas.draw()

    def _apply(self):
        from dba import build_dba_sources
        axis = int(self.combo_axis.currentData())
        n = self.sb_nx.value() * self.sb_nz.value()
        drv = self.combo_drive.currentData()
        drv_txt = "LS (Santillán)" if drv == "ls" else "retardo + inversión (naive)"
        warn = ("<br><br><span style='color:#b45309;'>Son muchas fuentes: el "
                "campo 3D, la FRF y los marcadores se recalculan sobre todas, así "
                "que la app va a ir más lenta. Para tantear rápido usá menos subs "
                "o bajá el nº de modos / afiná la malla.</span>"
                if 2 * n > 16 else "")
        if QMessageBox.question(
                self, "Aplicar DBA a la sala",
                f"Se crearán <b>{2*n} fuentes</b> ({n} al frente + {n} atrás) "
                f"con drive <b>{drv_txt}</b>.<br><br>"
                "Reemplaza las fuentes DBA previas (las demás se conservan). "
                f"¿Continuar?{warn}",
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
        axis = int(self.combo_axis.currentData())
        # Rótulos con el eje real de cada dirección de la pared (los dos ejes
        # transversales al de enfrentamiento). Así "dir. A/B" deja de ser opaco.
        short = ["X (ancho)", "Y (largo)", "Z (alto)"]
        a, b = tuple(k for k in (0, 1, 2) if k != axis)
        self.lbl_na.setText(f"Cantidad de subs en pared, a lo {short[a]}:")
        self.lbl_nb.setText(f"Cantidad de subs en pared, a lo {short[b]}:")
        n = self.sb_nx.value() * self.sb_nz.value()
        fmx = alias_fmax(self._dims, axis,
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
            self._ax.axvspan(r["band_hi"], fa[-1], color="#f2c14e", alpha=0.15,
                             label=f"aliasing espacial (> f_max = {r['f_max']:.0f} Hz)")
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
