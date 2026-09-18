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
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QDialogButtonBox,
    QApplication, QFileDialog, QSizePolicy, QMessageBox, QScrollArea, QWidget,
    QProgressDialog)

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


class _OptimizeWorker(QThread):
    """Corre cabs_optimize.optimize_cabs en un HILO aparte, para que la GUI NO se
    congele ('tilde') durante la optimizacion (que puede tardar decenas de segundos).
    Emite progreso por generacion y soporta Cancelar (devuelve la mejor solucion
    hasta el momento). El calculo es numpy/scipy puro sobre COPIAS de las fuentes:
    no toca Qt ni estado compartido de la GUI -> seguro fuera del hilo principal."""
    progress = pyqtSignal(int, int)      # (generacion, maxiter)
    finished_ok = pyqtSignal(object)     # dict resultado de optimize_cabs
    failed = pyqtSignal(str)

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self._kwargs = kwargs
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import cabs_optimize as copt
        try:
            r = copt.optimize_cabs(
                **self._kwargs,
                progress_cb=lambda i, m: self.progress.emit(int(i), int(m)),
                should_cancel=lambda: self._cancel)
            r["cancelled"] = bool(self._cancel)
            self.finished_ok.emit(r)
        except Exception as e:               # se reporta en el hilo principal
            self.failed.emit(str(e))


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
        self.setWindowTitle("Optimización de fuentes")
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
            "<b>Optimización de fuentes</b> sobre la sala "
            f"({self._dims[0]:.1f}×{self._dims[1]:.1f}×{self._dims[2]:.1f} m). "
            "Elegí un <b>norte</b> y evaluá u optimizá las fuentes cargadas, o pasá "
            "a <b>diseñar un array</b> DBA/CABS desde cero.")
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
            # Default = "Optimizar mis fuentes" (el uso principal). "Diseñar un array"
            # queda opt-in; sus controles de construcción se ocultan fuera de él.
            self.combo_mode.addItem("Optimizar mis fuentes", "eval")
            self.combo_mode.addItem("Diseñar un array DBA/CABS", "design")
            self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
            mrow.addWidget(self.combo_mode, 1)
            lay.addLayout(mrow)

            # Criterio (solo modo evaluar): DBA (drive canónico fijado) vs CABS
            # (trasero manejado). El MISMO criterio se usa para evaluar Y para
            # optimizar, así concuerdan por construcción (cierra el bug del delay
            # 2x). Oculto hasta entrar en modo evaluar.
            crow = QHBoxLayout()
            self.lbl_criterion = QLabel("Norte (criterio):")
            crow.addWidget(self.lbl_criterion)
            self.combo_criterion = QComboBox()
            # Norte de la optimizacion (Fase A del panel unificado). Nortes PUROS
            # (objetivo) primero, luego los ESQUEMAS de array. Default = compuesta
            # plana (el norte del profesor Bidondo).
            self.combo_criterion.addItem("Transferencia compuesta plana", "flat")
            self.combo_criterion.addItem("Uniformidad espacial (asiento a asiento)", "spatial")
            self.combo_criterion.addItem("Mínimo SBIR (peine de bordes)", "sbir")
            self.combo_criterion.addItem("Combinado (por caso de uso)", "combined")
            self.combo_criterion.addItem("CABS (par de subs en una pared, manejada)", "cabs")
            self.combo_criterion.addItem("DBA (pares de subs en dos paredes opuestas)", "dba")
            self.combo_criterion.setToolTip(
                "Qué se minimiza al evaluar/optimizar:\n"
                "• Transferencia compuesta plana: aplanar la respuesta compuesta "
                "(mains + subs) en la banda; es el norte general, sin esquema de "
                "array.\n• Uniformidad espacial: minimizar la varianza asiento a "
                "asiento.\n• Mínimo SBIR: minimizar el peine de reflexiones de borde "
                "en el punto de escucha (20-200 Hz).\n• Combinado: score 0..100 que "
                "pesa planitud + espacial + SBIR según el caso de uso (música/voz/"
                "mixto), con los mismos umbrales que Predicción.\n• CABS: un par de subs en una "
                "pared (manejada) + una fuente enfrente; drive libre.\n• DBA: dos "
                "pares de subs en paredes opuestas; una reproduce a la otra retardada "
                "L/c e invertida (drive canónico, se fija al optimizar).\nEl mismo "
                "norte se usa para evaluar y optimizar (coherencia).")
            self.combo_criterion.currentIndexChanged.connect(
                self._on_criterion_changed)
            crow.addWidget(self.combo_criterion, 1)
            lay.addLayout(crow)
            self.lbl_criterion.setVisible(False)
            self.combo_criterion.setVisible(False)

            # Caso de uso (SOLO norte "Combinado"): fija los pesos flat/espacial/sbir
            # reusando los de Predicción (`default_location_weights`).
            self._use_w = QWidget()
            _urow = QHBoxLayout(self._use_w)
            _urow.setContentsMargins(0, 0, 0, 0)
            _urow.addWidget(QLabel("Caso de uso:"))
            self.combo_use = QComboBox()
            self.combo_use.addItem("Mixto / polivalente", "mixto")
            self.combo_use.addItem("Música", "musica")
            self.combo_use.addItem("Voz / conferencia", "voz")
            self.combo_use.setToolTip(
                "Pesos del norte combinado por caso de uso (mismos que Predicción):\n"
                "• Música: prioriza consistencia espacial + control del peine.\n"
                "• Voz: prioriza timbre plano + SBIR.\n• Mixto: pesos parejos.")
            self.combo_use.currentIndexChanged.connect(self._on_criterion_changed)
            _urow.addWidget(self.combo_use, 1)
            lay.addWidget(self._use_w)
            self._use_w.setVisible(False)

        # Eje de enfrentamiento: en FILA PROPIA (no dentro de un grupo) porque su
        # visibilidad es condicional: se ve al DISEÑAR un array (elegir la pared) y
        # al OPTIMIZAR solo con norte CABS/DBA (elegir el par a evaluar). Con norte
        # flat/spatial se oculta (el objetivo no depende de un eje). Ver §9 del plan.
        self._axis_w = QWidget()
        _axrow = QHBoxLayout(self._axis_w)
        _axrow.setContentsMargins(0, 0, 0, 0)
        _axrow.addWidget(QLabel("Eje de enfrentamiento:"))
        self.combo_axis = QComboBox()
        self.combo_axis.addItem("Auto (detectar par de paredes)", None)
        for i, nm in enumerate(_AXIS_NAMES):
            self.combo_axis.addItem(nm, i)
        self.combo_axis.setCurrentIndex(0)                    # Auto
        _axrow.addWidget(self.combo_axis, 1)
        lay.addWidget(self._axis_w)

        # Diseño del array (SOLO modo "Diseñar un array"): nº de subs por pared y el
        # drive del trasero. Se OCULTA entero al optimizar (pedido del usuario 18 Sep:
        # la configuración del array aparece solo si se quiere diseñar el array).
        self.grp_design = QGroupBox("Diseño del array")
        dfl = QFormLayout(self.grp_design)
        self.sb_nx = QSpinBox(); self.sb_nx.setRange(1, 8); self.sb_nx.setValue(4)
        self.sb_nz = QSpinBox(); self.sb_nz.setRange(1, 8); self.sb_nz.setValue(4)
        # Rótulos dinámicos: muestran el eje real de cada dirección de la pared
        # (se actualizan al cambiar el eje de enfrentamiento, en _refresh_count).
        self.lbl_na = QLabel("Subs por pared, dirección 1:")
        self.lbl_nb = QLabel("Subs por pared, dirección 2:")
        dfl.addRow(self.lbl_na, self.sb_nx)
        dfl.addRow(self.lbl_nb, self.sb_nz)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color:#555; font-size:8pt;")
        dfl.addRow("", self.lbl_count)
        self.combo_drive = QComboBox()
        self.combo_drive.addItem("Mínimos cuadrados (Santillán)", "ls")
        self.combo_drive.addItem("Retardo + inversión (naive)", "naive")
        dfl.addRow("Drive del array trasero:", self.combo_drive)
        lay.addWidget(self.grp_design)
        self.sb_nx.valueChanged.connect(self._refresh_count)
        self.sb_nz.valueChanged.connect(self._refresh_count)
        self.combo_axis.currentIndexChanged.connect(self._refresh_count)

        # Análisis (compartido por diseñar y optimizar): banda + amortiguamiento.
        grp_an = QGroupBox("Análisis")
        fl = QFormLayout(grp_an)
        self.sb_xi = QDoubleSpinBox()
        self.sb_xi.setRange(0.002, 0.3); self.sb_xi.setDecimals(3)
        self.sb_xi.setSingleStep(0.005); self.sb_xi.setValue(0.03)
        self.sb_xi.setToolTip(
            "Amortiguamiento modal ξ (fracción del crítico). Valores sugeridos:\n"
            "• poco amortiguado (sala viva): ~0.01\n"
            "• amortiguado (típico tratado): ~0.03\n"
            "• muy amortiguado: ~0.08\n"
            "• sobre amortiguado (seco): ~0.15")
        fl.addRow("ξ (amortiguamiento modal):", self.sb_xi)
        # Leyenda con la banda cualitativa del valor actual + los sugeridos.
        self.lbl_xi_hint = QLabel("")
        self.lbl_xi_hint.setStyleSheet("color:#555; font-size:8pt;")
        self.lbl_xi_hint.setWordWrap(True)
        fl.addRow("", self.lbl_xi_hint)
        self.sb_xi.valueChanged.connect(self._refresh_xi_hint)

        self.sb_fmax = QDoubleSpinBox()
        self.sb_fmax.setRange(50.0, 400.0); self.sb_fmax.setValue(180.0)
        self.sb_fmax.setSuffix(" Hz")
        fl.addRow("f máx del análisis:", self.sb_fmax)
        lay.addWidget(grp_an)

        self.btn = QPushButton("Calcular")
        self.btn.setObjectName("PrimaryButton")
        self.btn.clicked.connect(self._on_calc)
        lay.addWidget(self.btn)

        # Optimizar fuentes libres (item 6): solo en modo evaluar. Mueve las
        # variables liberadas (free_vars) de cada fuente para minimizar el
        # criterio CABS. Oculto hasta entrar en modo evaluar.
        self.btn_opt = None
        self.lbl_opt_vars = None
        self._opt_worker = None          # hilo de optimizacion en curso (o None)
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
        self._refresh_xi_hint()
        # Estado inicial de visibilidad segun el modo default ("Optimizar mis
        # fuentes" si hay eval_ctx; "Diseñar un array" si el diálogo es solo diseño).
        self._on_mode_changed()

    # -----------------------------------------------------------------------
    # Modo evaluación
    # -----------------------------------------------------------------------
    def _mode(self):
        return self.combo_mode.currentData() if self.combo_mode else "design"

    _CRIT_LABELS = {
        "flat": "Transferencia compuesta plana",
        "spatial": "Uniformidad espacial",
        "sbir": "Mínimo SBIR",
        "combined": "Combinado por caso de uso",
        "cabs": "CABS", "dba": "DBA",
    }

    @staticmethod
    def _xi_band(xi):
        """Etiqueta cualitativa del amortiguamiento modal ξ (fracción del crítico).
        Rangos aproximados para salas: ~0.01 viva, ~0.03 típica tratada, ~0.08
        muy amortiguada, >0.12 seca."""
        if xi <= 0.02:
            return "poco amortiguado (sala viva)"
        if xi <= 0.05:
            return "amortiguado (típico tratado)"
        if xi <= 0.12:
            return "muy amortiguado"
        return "sobre amortiguado (seco)"

    def _refresh_xi_hint(self):
        if not hasattr(self, "lbl_xi_hint"):
            return
        self.lbl_xi_hint.setText(
            f"≈ <b>{self._xi_band(self.sb_xi.value())}</b>  ·  sugeridos: poco "
            "amortiguado ~0.01 · típico ~0.03 · muy ~0.08 · sobre ~0.15")

    def _criterion_weights(self):
        """Pesos del norte combinado (por caso de uso), o None para el resto. Reusa
        `location_opt.default_location_weights` (misma escala que Predicción)."""
        if self._criterion() != "combined" or not hasattr(self, "combo_use"):
            return None
        try:
            import location_opt as _lo
            return _lo.default_location_weights(self.combo_use.currentData() or "mixto")
        except Exception:
            return None

    def _criterion(self):
        """Norte elegido (flat|spatial|cabs|dba); el MISMO va a evaluar y optimizar.
        Default 'flat' (transferencia compuesta plana, el norte del profesor)."""
        return (self.combo_criterion.currentData()
                if self.combo_criterion is not None else "flat")

    def _crit_label(self, crit=None):
        """Nombre legible del norte (para los textos, en vez de 'FLAT'/'SPATIAL')."""
        c = str(crit if crit is not None else self._criterion())
        return self._CRIT_LABELS.get(c, c.upper())

    def _is_array_crit(self, crit=None):
        c = str(crit if crit is not None else self._criterion())
        return c in ("cabs", "dba")

    def _axis_arg(self):
        """Eje para pasar al nucleo: None si el combo esta en 'Auto' (el nucleo
        detecta el par de paredes opuestas segun el criterio), o el entero elegido."""
        return self.combo_axis.currentData()   # None para 'Auto', int si manual

    def _is_rectangular(self):
        """True si la sala es un paralelepipedo (caja). CABS/DBA de libro asumen
        cuarto rectangular; si no lo es se evalua/optimiza sobre el AABB por
        planitud + transferencia total. Default True si no se sabe (no alarmar)."""
        return bool((self._eval_ctx or {}).get("is_rectangular", True))

    def _axis_concrete(self):
        """Eje CONCRETO (0/1/2) para los usos que necesitan uno si o si (diseñar el
        array, rotular las paredes). Con 'Auto' lo resuelve: best_axis de las fuentes
        activas segun el criterio, o el eje mas largo si no hay fuentes."""
        ax = self.combo_axis.currentData()
        if ax is not None:
            return int(ax)
        try:
            import dba_evaluate as dev
            ctx = self._eval_ctx or {}
            srcs = [s for s in ctx.get("sources", lambda: [])()
                    if getattr(s, "active", True)]
            if srcs:
                return int(dev.best_axis(srcs, self._dims,
                                         ctx.get("origin", (0.0, 0.0, 0.0)),
                                         criterion=self._criterion()))
        except Exception:
            pass
        return int(np.argmax(self._dims))

    def _refresh_axis_visibility(self):
        """El 'Eje de enfrentamiento' se ve al DISEÑAR (elegir la pared) y al
        OPTIMIZAR solo con norte CABS/DBA (elegir el par a evaluar). Con norte
        flat/spatial/sbir/combined se oculta: el objetivo no depende de un eje.
        El 'Caso de uso' se ve solo con el norte combinado, en modo optimizar."""
        ev = self._mode() == "eval"
        if hasattr(self, "_axis_w"):
            self._axis_w.setVisible((not ev) or self._is_array_crit())
        if hasattr(self, "_use_w"):
            self._use_w.setVisible(ev and self._criterion() == "combined")

    def _on_mode_changed(self):
        """Muestra/OCULTA los controles segun el modo (pedido del usuario 18 Sep):
        la construcción del array (nº subs/pared + drive + «Aplicar») aparece SOLO al
        'Diseñar un array'; al 'Optimizar mis fuentes' se ve el norte + «Optimizar»."""
        ev = self._mode() == "eval"
        # Grupo de construcción del array: oculto entero al optimizar.
        if hasattr(self, "grp_design"):
            self.grp_design.setVisible(not ev)
        self.btn.setText("Evaluar" if ev else "Calcular")
        if hasattr(self, "btn_apply"):
            self.btn_apply.setVisible(not ev)
        if self.btn_opt is not None:
            self.btn_opt.setVisible(ev)
        if self.lbl_opt_vars is not None:
            self.lbl_opt_vars.setVisible(ev)
            if ev:
                self._refresh_opt_vars_label()
        # El norte solo vive en modo optimizar; al diseñar, el array lo define el
        # nº de subs + el drive (decisión de UX 18 Sep).
        if self.combo_criterion is not None:
            self.combo_criterion.setVisible(ev)
            self.lbl_criterion.setVisible(ev)
        self._refresh_axis_visibility()
        if not ev:
            self.lbl_res.setText("Elegí el array y tocá «Calcular».")
            return
        self._refresh_feasibility_head()

    def _on_criterion_changed(self):
        """Al cambiar el norte en modo optimizar: refresca el aviso y la visibilidad
        del eje (CABS/DBA lo muestran; flat/spatial lo ocultan)."""
        if self._mode() == "eval":
            self._refresh_axis_visibility()
            self._refresh_feasibility_head()

    def _refresh_feasibility_head(self):
        """Heads-up de factibilidad del CRITERIO elegido, apenas se entra al modo o
        se cambia de criterio (barato, sin computar respuesta)."""
        crit = self._criterion()
        head = (f"Norte: <b>{self._crit_label(crit)}</b>. Se evalúa/optimiza por "
                "<b>planitud + transferencia total (modos + SBIR)</b>. Tocá "
                "«Evaluar» para analizar las fuentes cargadas, o «Optimizar» para "
                "reacomodar las que marcaste.")
        notes = []
        if self._is_array_crit(crit) and not self._is_rectangular():
            if (self._eval_ctx or {}).get("fem") is not None:
                notes.append(
                    "los criterios CABS/DBA son de recinto <b>rectangular</b>; esta "
                    "sala no lo es, así que se trabaja sobre el <b>volumen interior "
                    "real</b> (campo modal FEM) por planitud + transferencia total")
            else:
                notes.append(
                    "los criterios CABS/DBA son de recinto <b>rectangular</b>; esta "
                    "sala no lo es y aún no hay modos FEM, así que se trabaja sobre el "
                    "AABB por planitud + transferencia total (calculá los modos FEM "
                    "para usar el volumen real)")
        try:
            import dba_evaluate as dev
            ctx = self._eval_ctx or {}
            srcs = [s for s in ctx.get("sources", lambda: [])()
                    if getattr(s, "active", True)]
            if srcs and self._is_array_crit(crit):
                feasible, reasons, _ax = dev.cabs_feasibility(
                    srcs, self._dims, origin=ctx.get("origin", (0.0, 0.0, 0.0)),
                    axis=self._axis_arg(), criterion=crit)
                if feasible is False and self._is_rectangular():
                    notes.append(
                        f"no es un array {self._crit_label(crit)} de libro ("
                        + "; ".join(reasons)
                        + "), pero se evalúa igual por planitud")
        except Exception:
            pass
        if notes:
            head += ("<br><span style='color:#555;'>Nota: "
                     + " · ".join(notes) + ".</span>")
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
        axis = self._axis_arg()          # None = Auto -> el nucleo detecta el eje
        self.btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = dev.evaluate_cabs(
                sources, self._dims, ctx.get("receiver_world", self._receiver),
                origin=ctx.get("origin", (0.0, 0.0, 0.0)),
                walls=ctx.get("walls_fn"), axis=axis,
                fmin=20.0, fmax=self.sb_fmax.value(), xi=self.sb_xi.value(),
                f_schroeder=ctx.get("f_schroeder"), criterion=self._criterion(),
                fem=ctx.get("fem"), weights=self._criterion_weights())
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
        axis = self._axis_arg()          # None = Auto -> el nucleo detecta el eje
        # NO se bloquea la optimizacion por la estructura del array (spec del
        # profesor 16 Sep 2026): CABS/DBA se optimizan SIEMPRE por planitud +
        # transferencia total (modos + SBIR), sin importar si las fuentes forman un
        # array de libro o el recinto es rectangular. El pre-chequeo estructural
        # queda solo como NOTA informativa en el resultado.
        import dba_evaluate as _dev
        feasible, reasons, _ax = _dev.cabs_feasibility(
            sources, self._dims, origin=ctx.get("origin", (0.0, 0.0, 0.0)),
            axis=axis, criterion=self._criterion())
        _array = self._is_array_crit()
        opt_note = ""
        if _array and not self._is_rectangular():
            if ctx.get("fem") is not None:
                opt_note += ("<span style='color:#2e7d32;'>Nota: recinto no "
                             "rectangular; se optimiza sobre el <b>volumen interior "
                             "real</b> (campo modal FEM) por planitud + transferencia "
                             "total (modos + SBIR).</span><br>")
            else:
                opt_note += ("<span style='color:#b45309;'>Nota: recinto no "
                             "rectangular y sin modos FEM; se optimiza sobre la caja "
                             "AABB por planitud + transferencia total. Para usar el "
                             "volumen real, calculá los modos (FEM) primero.</span><br>")
        elif _array and not feasible:
            opt_note += ("<span style='color:#555;'>Nota: no es un array "
                         f"{self._crit_label()} de libro ("
                         + "; ".join(reasons) + "); se optimiza igual por planitud + "
                         "transferencia total.</span><br>")
        # Corre en un HILO con barra de progreso + Cancelar: la GUI queda VIVA
        # (antes corria sincrono en el hilo principal -> la app se 'tildaba' toda la
        # optimizacion, que puede tardar decenas de segundos, y el usuario la mataba).
        maxiter = 25
        self.btn_opt.setEnabled(False)
        self.lbl_res.setText(opt_note + "Optimizando… (podés cancelar)")
        prog = QProgressDialog("Optimizando posiciones/drive de las fuentes…",
                               "Cancelar", 0, maxiter, self)
        prog.setWindowTitle("Optimización de fuentes")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)
        try:
            from style import apply_dialog_theme
            apply_dialog_theme(prog)
        except Exception:
            pass

        kwargs = dict(
            sources=sources, dims=self._dims,
            receiver=ctx.get("receiver_world", self._receiver),
            origin=ctx.get("origin", (0.0, 0.0, 0.0)),
            walls=ctx.get("walls_fn"), axis=axis, fmin=20.0,
            fmax=self.sb_fmax.value(), xi=self.sb_xi.value(),
            f_schroeder=ctx.get("f_schroeder"), criterion=self._criterion(),
            inside_fn=ctx.get("inside_fn"), maxiter=maxiter, fem=ctx.get("fem"),
            weights=self._criterion_weights())
        worker = _OptimizeWorker(kwargs, self)
        self._opt_worker = worker            # ref para que no lo junte el GC

        # Countdown de tiempo restante: differential_evolution hace un nº FIJO de
        # generaciones a costo ~constante, asi que estimamos el ETA con el tiempo
        # por generacion medido (elapsed/i) * generaciones que faltan.
        import time as _time
        t0 = _time.perf_counter()

        def _on_prog(i, m):
            prog.setValue(min(i, m))
            if i >= 1:
                elapsed = _time.perf_counter() - t0
                remaining = max(0.0, (m - i) * (elapsed / i))
                if remaining >= 60:
                    eta = f"~{int(remaining // 60)} min {int(remaining % 60)} s"
                else:
                    eta = f"~{int(round(remaining))} s"
                prog.setLabelText(
                    f"Optimizando fuentes… generación {i}/{m}\n"
                    f"Tiempo restante estimado: {eta}")

        worker.progress.connect(_on_prog)
        prog.canceled.connect(worker.cancel)

        def _cleanup():
            prog.close()
            self.btn_opt.setEnabled(True)
            self._opt_worker = None

        def _ok(r):
            _cleanup()
            self._on_opt_done(r, ctx)

        def _err(msg):
            _cleanup()
            self.lbl_res.setText(f"<span style='color:#b00'>Error: {msg}</span>")

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_err)
        worker.start()

    def _on_opt_done(self, r, ctx):
        """Post-proceso de la optimizacion (en el hilo principal): mostrar el
        resultado y ofrecer aplicarlo. Si se cancelo, igual muestra lo mejor hasta
        el momento pero no auto-aplica."""
        self._last_opt = r
        import dba_evaluate as _dev
        crit = str(r.get("criterion", "flat"))
        wts = self._criterion_weights()
        b, a = r["before"], r["after"]
        c0 = _dev.composite_cost(b, crit, wts)
        c1 = _dev.composite_cost(a, crit, wts)
        # El objetivo mostrado usa la MÉTRICA real del norte y en su dirección natural
        # (menor dB mejor, mayor puntaje mejor), asi no queda contradictorio con las
        # sub-metricas. Ademas se listan TODAS las que pesan (para el combinado, el
        # SBIR explica por que el puntaje sube aunque planitud/varianza suban un poco).
        tag = " <b>(mejora)</b>" if r["improved"] else " (sin mejora)"
        _fs = lambda m: (f"{m.get('flat', float('nan')):.2f}",
                         f"{m.get('spatial', float('nan')):.2f}",
                         f"{m.get('sbir_span', float('nan')):.2f}")
        (bf, bs, bsb), (af, as_, asb) = _fs(b), _fs(a)
        if crit == "combined":
            obj = (f"Puntaje: {100.0 - c0:.0f} → <b>{100.0 - c1:.0f}</b>/100" + tag)
            detail = (f"&nbsp;&nbsp;planitud {bf}→{af} dB · varianza {bs}→{as_} dB · "
                      f"peine SBIR {bsb}→{asb} dB")
        elif crit == "sbir":
            obj = f"Peine SBIR: {c0:.2f} → <b>{c1:.2f}</b> dB" + tag
            detail = f"&nbsp;&nbsp;planitud {bf}→{af} dB · varianza {bs}→{as_} dB"
        elif crit == "flat":
            obj = f"Planitud: {c0:.2f} → <b>{c1:.2f}</b> dB" + tag
            detail = f"&nbsp;&nbsp;varianza {bs}→{as_} dB"
        elif crit == "spatial":
            obj = f"Varianza espacial: {c0:.2f} → <b>{c1:.2f}</b> dB" + tag
            detail = f"&nbsp;&nbsp;planitud {bf}→{af} dB"
        else:  # cabs / dba
            obj = f"Planitud+varianza: {c0:.2f} → <b>{c1:.2f}</b> dB" + tag
            detail = f"&nbsp;&nbsp;planitud {bf}→{af} · varianza {bs}→{as_}"
        cancelled = bool(r.get("cancelled"))
        head = ("<b>Optimización CANCELADA</b> (mejor resultado hasta el corte):"
                if cancelled else
                f"<b>Optimización de {r['n_free']} fuente(s) libre(s)</b> "
                f"({self._crit_label(crit)}):")
        lines = [head, obj, detail]
        if r["changes"]:
            lines.append("<b>Cambios propuestos:</b>")
            lines += [f"&nbsp;• {c}" for c in r["changes"]]
        self.lbl_res.setText("<br>".join(lines))
        apply_cb = ctx.get("apply_optimized")
        if r["improved"] and apply_cb is not None:
            _msg = (f"El optimizador subió el puntaje de {100.0 - c0:.0f} a "
                    f"{100.0 - c1:.0f} / 100." if crit == "combined" else
                    f"El optimizador mejoró el objetivo de {c0:.2f} a {c1:.2f} dB.")
            if QMessageBox.question(
                    self, "Aplicar optimización",
                    _msg + "\n\n"
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

    def closeEvent(self, ev):
        """Si hay una optimizacion corriendo, cancelarla y esperar antes de cerrar
        (no dejar un hilo huerfano tocando datos que ya no existen)."""
        w = getattr(self, "_opt_worker", None)
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(3000)
        super().closeEvent(ev)

    def _show_eval(self, r):
        na, nb = r["ideal_grid"]
        crit_key = str(r.get("criterion", "flat"))
        crit = self._crit_label(crit_key)
        array = self._is_array_crit(crit_key)

        # VEREDICTO PRIMARIO = planitud + transferencia total (modos + SBIR), real
        # vs el ideal de esta sala. NO se bloquea ni se rechaza por la estructura del
        # array (spec del profesor 16 Sep 2026): CABS/DBA se juzgan por el colapso de
        # la respuesta, no por si las fuentes cumplen el esquema de libro.
        fr_real, sp_real = r["flat_real"], r["spatial_real"]
        fr_id, sp_id = r["flat_ideal"], r["spatial_ideal"]
        if crit_key == "combined":
            # Veredicto sobre el score COMBINADO 0..100 (mayor=mejor), real vs ideal.
            cb_r = r.get("combined_real", float("nan"))
            cb_i = r.get("combined_ideal", float("nan"))
            ok = np.isfinite(cb_r) and np.isfinite(cb_i) and (cb_r >= cb_i - 5.0)
            badge = ("<span style='color:#2e7d32;'><b>buen puntaje</b></span>" if ok
                     else "<span style='color:#b45309;'><b>se puede mejorar</b></span>")
            _uc = (self.combo_use.currentText() if hasattr(self, "combo_use") else "")
            lines = [
                f"<b>{crit} ({_uc}):</b> {badge}",
                f"&nbsp;&nbsp;Puntaje: <b>{cb_r:.0f}</b>/100 (ideal {cb_i:.0f}) · "
                f"planitud {fr_real:.1f} dB, varianza {sp_real:.1f} dB, "
                f"peine {r.get('sbir_real', float('nan')):.1f} dB",
                f"&nbsp;&nbsp;<span style='color:#555;'>({r['n_modes']} modos)</span>"]
        elif crit_key == "sbir":
            # Veredicto sobre el PEINE SBIR (real vs el ideal de referencia).
            sb_r, sb_i = r.get("sbir_real", float("nan")), r.get("sbir_ideal", float("nan"))
            ok = np.isfinite(sb_r) and np.isfinite(sb_i) and (sb_r <= sb_i + 1.5)
            badge = ("<span style='color:#2e7d32;'><b>peine controlado</b></span>"
                     if ok else
                     "<span style='color:#b45309;'><b>se puede reducir el peine</b></span>")
            lines = [
                f"<b>{crit} — peine de reflexiones de borde:</b> {badge}",
                f"&nbsp;&nbsp;Peine SBIR pico-a-valle: <b>{sb_r:.2f}</b> dB "
                f"(ideal {sb_i:.2f}) · Planitud compuesta: {fr_real:.2f} dB",
                f"&nbsp;&nbsp;<span style='color:#555;'>(receptor, "
                f"{r['n_modes']} modos)</span>"]
        else:
            collapse_ok = (fr_real <= fr_id + 1.5) and (sp_real <= sp_id + 1.5)
            badge = ("<span style='color:#2e7d32;'><b>respuesta plana</b></span>"
                     if collapse_ok else
                     "<span style='color:#b45309;'><b>se puede aplanar más</b></span>")
            lines = [
                f"<b>{crit} — planitud + transferencia total (modos + SBIR):</b> {badge}",
                f"&nbsp;&nbsp;Planitud: <b>{fr_real:.2f}</b> dB (ideal {fr_id:.2f}) · "
                f"Varianza espacial: <b>{sp_real:.2f}</b> dB (ideal {sp_id:.2f})",
                f"&nbsp;&nbsp;<span style='color:#555;'>(eje {_AXIS_NAMES[r['axis']]}, "
                f"{r['n_modes']} modos)</span>"]
        # Uniformidad modal (Bolt): informativa (propiedad de la sala, no cambia al
        # mover fuentes). Se muestra siempre como contexto.
        _sm = r.get("smoothness", float("nan"))
        if np.isfinite(_sm):
            lines.append(
                f"&nbsp;&nbsp;<span style='color:#555;'>Uniformidad modal (Bolt): "
                f"{_sm:.0f}/100 — propiedad de la sala (no depende de las fuentes).</span>")

        # Nota de geometría irregular: los criterios son de paralelepípedo. Si hay
        # modos FEM del recinto real, la evaluación corre sobre el VOLUMEN INTERIOR
        # REAL (no el AABB); si no, cae al AABB analítico y se avisa cómo mejorarlo.
        if not self._is_rectangular():
            _crit_txt = ("los criterios CABS/DBA están" if array
                         else "el norte compuesto está")
            if str(r.get("field")) == "fem":
                lines.append(
                    f"<span style='color:#2e7d32;'>Nota: {_crit_txt} definido para "
                    "recintos <b>rectangulares (paralelepípedo)</b>. Esta sala no lo "
                    "es, así que la evaluación se hizo sobre el <b>volumen interior "
                    f"real</b> (campo modal FEM del recinto, {r['n_modes']} modos), no "
                    "sobre la caja AABB, por planitud + transferencia total.</span>")
            else:
                lines.append(
                    f"<span style='color:#b45309;'>Nota: {_crit_txt} definido para "
                    "recintos <b>rectangulares (paralelepípedo)</b>. Esta sala no lo "
                    "es y todavía no hay modos FEM resueltos, así que se evaluó sobre "
                    "la caja envolvente (AABB) por planitud + transferencia total. "
                    "Para correrlo sobre el <b>volumen interior real</b>, calculá los "
                    "modos (FEM) del recinto y volvé a evaluar.</span>")

        # Clasificacion + condiciones de esquema: SOLO para nortes de array (cabs/dba).
        # Para los nortes puros (flat/spatial) el resultado es solo el veredicto de
        # planitud/uniformidad (el checklist ya trae un unico item informativo).
        if array:
            roles = r["roles"]

            def _lab(ro):
                pol = int(getattr(getattr(ro, "src", None), "polarity", 1) or 1)
                return ro.label + (" [180°]" if pol < 0 else " [0°]")

            fr = [_lab(ro) for ro in roles if ro.role == "front"]
            re = [_lab(ro) for ro in roles if ro.role == "rear"]
            ot = [_lab(ro) for ro in roles if ro.role == "other"]
            lines.append(
                f"<b>Clasificación</b> (con polaridad)<b>:</b> "
                f"pared 1: {', '.join(fr) or '—'} · "
                f"pared 2: {', '.join(re) or '—'} · otras: {', '.join(ot) or '—'}")
            if not r["passed"]:
                lines.append(
                    "<span style='color:#555;'>Tu configuración no es un array "
                    f"{crit} de libro (ver condiciones abajo), pero igual se evaluó "
                    "por planitud + transferencia total.</span>")
            lines.append("<b>Condiciones del esquema (informativas):</b>")
        for it in r["checklist"]:
            mark = "✓" if it["ok"] else "○"
            col = "#2e7d32" if it["ok"] else "#777"
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
        axis = self._axis_concrete()     # diseñar el array necesita un eje concreto
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
                f"Se crearán <b>{2*n} fuentes</b> ({n} en una pared + {n} en la opuesta) "
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
        axis = self._axis_concrete()     # rotular las paredes necesita un eje concreto
        # Rótulos con el eje real de cada dirección de la pared (los dos ejes
        # transversales al de enfrentamiento). El array es una GRILLA por pared,
        # igual en las dos paredes enfrentadas -> las dos cajas son las dos
        # direcciones de esa grilla (no dos paredes distintas).
        short = ["X (ancho)", "Y (largo)", "Z (alto)"]
        a, b = tuple(k for k in (0, 1, 2) if k != axis)
        self.lbl_na.setText(f"Subs por pared, dirección 1 (a lo {short[a]}):")
        self.lbl_nb.setText(f"Subs por pared, dirección 2 (a lo {short[b]}):")
        n = self.sb_nx.value() * self.sb_nz.value()
        fmx = alias_fmax(self._dims, axis,
                         self.sb_nx.value(), self.sb_nz.value())
        fmx_txt = "∞" if not np.isfinite(fmx) else f"{fmx:.0f} Hz"
        self.lbl_count.setText(
            f"= {n} subs por pared × 2 paredes = {2*n} en total  ·  "
            f"f_max = c/d ≈ {fmx_txt}")

    def _calc(self):
        axis = self._axis_concrete()     # diseñar/calcular el array necesita eje concreto
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
