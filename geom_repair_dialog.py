"""
geom_repair_dialog.py
=====================

Dialogo Qt de reparacion guiada para una malla CAD importada.

Flujo:
  1. Se abre con la malla recien cargada + su diagnostico.
  2. Si la malla esta OK, se muestra un resumen verde y se cierra al "Aceptar".
  3. Si hay huecos / inconsistencias, navegacion 1-por-1:
      - Lista de problemas a la izquierda.
      - Preview 3D a la derecha, con el hueco actual resaltado en rojo.
      - Botones:
          * "Cerrar este hueco automaticamente"  -> fill_hole_planar
          * "Soldar a vertices cercanos (snap)" -> snap_hole_vertices
          * "Editar vertice..."  (apre dialogo para mover un vertice)
          * "Omitir este hueco" (next sin tocar)
          * "Reparar todo automaticamente"
          * "Aceptar"   -> termina y devuelve la malla actual
          * "Cancelar"  -> devuelve None
"""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from style import apply_dialog_theme
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
    QGroupBox, QFormLayout, QDoubleSpinBox, QDialogButtonBox,
    QMessageBox, QSizePolicy, QWidget, QScrollArea, QFrame,
    QSpinBox, QApplication, QFileDialog,
)

import geom_import as gi


class _MeshPreview(gl.GLViewWidget):
    """GLViewWidget compacto para preview 3D con highlight de huecos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundColor(QColor("#11111b"))
        self.opts["distance"] = 20.0
        self.opts["fov"] = 30.0
        self.setMinimumSize(420, 320)
        grid = gl.GLGridItem()
        grid.setSize(x=40, y=40)
        grid.setSpacing(x=1, y=1)
        grid.setColor((137, 180, 250, 50))
        self.addItem(grid)
        self._mesh_item = None
        self._edge_item = None
        self._highlight_items = []
        # Seleccion de caras (A+): modo picking + centroides proyectables.
        self._pick_mode = False
        self._pick_faces = None
        self._pick_centroids = None
        self.face_pick_callback = None      # def cb(face_index): ...

    # --- seleccion de caras (A+) ---
    def set_pick_mode(self, on: bool):
        self._pick_mode = bool(on)
        try:
            self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        except Exception:
            pass

    def _qmat_to_np(self, m):
        # QMatrix4x4.data() = 16 floats COLUMN-major -> reshape(4,4).T = row-major.
        if hasattr(m, "data"):
            return np.array(m.data(), dtype=float).reshape(4, 4).T
        return np.array(m, dtype=float).reshape(4, 4)

    def _face_at(self, ev):
        """Indice de la cara cuyo centroide se proyecta mas cerca del click (o None)."""
        C = self._pick_centroids
        if C is None or len(C) == 0:
            return None
        try:
            mvp = self._qmat_to_np(self.projectionMatrix()) @ \
                  self._qmat_to_np(self.viewMatrix())
        except Exception:
            return None
        ph = np.hstack([C, np.ones((len(C), 1))])
        clip = ph @ mvp.T
        w = clip[:, 3]
        with np.errstate(invalid="ignore", divide="ignore"):
            ndc = clip[:, :3] / w[:, None]
        W = float(self.width()); H = float(self.height())
        sx = (ndc[:, 0] * 0.5 + 0.5) * W
        sy = (0.5 - ndc[:, 1] * 0.5) * H
        try:
            p = ev.pos()
            px, py = float(p.x()), float(p.y())
        except Exception:
            return None
        d2 = (sx - px) ** 2 + (sy - py) ** 2
        d2[w <= 1e-6] = np.inf                 # descartar lo que esta detras
        i = int(np.argmin(d2))
        if not np.isfinite(d2[i]) or d2[i] > (26.0 ** 2):   # tolerancia ~26 px
            return None
        return i

    def mousePressEvent(self, ev):
        if self._pick_mode and self.face_pick_callback is not None:
            idx = self._face_at(ev)
            if idx is not None:
                try:
                    self.face_pick_callback(int(idx))
                except Exception:
                    pass
                return                          # consumir: no rotar la camara
        super().mousePressEvent(ev)

    def highlight_faces(self, mesh, face_indices):
        """Resalta en rojo las aristas de las caras seleccionadas (patron seguro:
        GLLinePlotItem, no faceColors, que no renderiza en esta escena)."""
        self.clear_highlights()
        if not len(face_indices):
            self.update(); return
        verts = np.asarray(mesh.vertices, dtype=np.float32)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        sel = np.asarray(list(face_indices), dtype=np.int64)
        sel = sel[(sel >= 0) & (sel < len(faces))]
        if not len(sel):
            self.update(); return
        tf = faces[sel]
        e = np.concatenate([tf[:, [0, 1]], tf[:, [1, 2]], tf[:, [2, 0]]], axis=0)
        pos = verts[e.flatten()]
        line = gl.GLLinePlotItem(pos=pos.astype(np.float32),
                                 color=(1.0, 0.18, 0.22, 1.0), width=3.0,
                                 antialias=True, mode="lines")
        self.addItem(line)
        self._highlight_items.append(line)
        self.update()

    def show_mesh(self, mesh):
        # Mesh principal en gris translucido
        if self._mesh_item is not None:
            self.removeItem(self._mesh_item)
            self._mesh_item = None
        if self._edge_item is not None:
            self.removeItem(self._edge_item)
            self._edge_item = None
        verts = np.asarray(mesh.vertices, dtype=np.float32)
        faces = np.asarray(mesh.faces, dtype=np.int32)
        # Centroides para el picking de caras (A+). Se calculan sobre TODAS las
        # caras (el indice de pick debe coincidir con mesh.faces).
        self._pick_faces = faces
        self._pick_centroids = (verts[faces].mean(axis=1)
                                if len(faces) else None)
        if len(faces) == 0:
            return
        # Robustez: vertices no finitos (NaN/inf) rompen el calculo de normales del
        # shader "shaded" -> "Error while drawing item GLMeshItem" y pantalla negra.
        # Se sanean a 0 y se descartan las caras degeneradas (area ~0) para el fill.
        if not np.all(np.isfinite(verts)):
            verts = np.nan_to_num(verts, nan=0.0, posinf=0.0, neginf=0.0)
        a = verts[faces[:, 0]]; b = verts[faces[:, 1]]; c = verts[faces[:, 2]]
        area2 = np.linalg.norm(np.cross(b - a, c - a), axis=1)
        good = faces[area2 > 1e-12]
        try:
            if len(good):
                self._mesh_item = gl.GLMeshItem(
                    meshdata=gl.MeshData(vertexes=verts, faces=good),
                    smooth=True, color=(0.5, 0.7, 1.0, 0.30),
                    shader="shaded", glOptions="translucent",
                )
                self.addItem(self._mesh_item)
        except Exception:
            # Si el relleno falla por cualquier motivo, seguimos con el wireframe
            # (mejor ver las aristas que perder todo el preview).
            self._mesh_item = None

        # Wireframe sutil
        # 3 aristas por triangulo
        e1 = faces[:, [0, 1]]
        e2 = faces[:, [1, 2]]
        e3 = faces[:, [2, 0]]
        e_all = np.concatenate([e1, e2, e3], axis=0)
        pos = verts[e_all.flatten()]
        self._edge_item = gl.GLLinePlotItem(
            pos=pos.astype(np.float32),
            color=(0.7, 0.85, 1.0, 0.35),
            width=1.0, antialias=True, mode="lines",
        )
        self.addItem(self._edge_item)

        # Centrar la camara en el bbox
        c = verts.mean(axis=0)
        diag = float(np.linalg.norm(verts.max(0) - verts.min(0)))
        self.opts["distance"] = max(3.0, diag * 2.0)
        from pyqtgraph import Vector
        self.opts["center"] = Vector(float(c[0]), float(c[1]), float(c[2]))
        self.update()

    def clear_highlights(self):
        for it in self._highlight_items:
            self.removeItem(it)
        self._highlight_items = []

    def highlight_hole(self, mesh, hole):
        """Resalta el ciclo del hueco en rojo grueso + esferita en el centroide."""
        self.clear_highlights()
        verts = np.asarray(mesh.vertices, dtype=np.float32)
        idx = hole.boundary_vertex_indices
        loop = verts[idx + [idx[0]]]  # cerrar el ciclo visualmente
        line = gl.GLLinePlotItem(
            pos=loop.astype(np.float32),
            color=(1.0, 0.18, 0.22, 1.0),
            width=4.5, antialias=True, mode="line_strip",
        )
        self.addItem(line)
        self._highlight_items.append(line)
        # Puntos en los vertices del ciclo
        sc = gl.GLScatterPlotItem(
            pos=verts[idx].astype(np.float32),
            color=(1.0, 0.45, 0.20, 1.0),
            size=10.0, pxMode=True,
        )
        self.addItem(sc)
        self._highlight_items.append(sc)
        # Centroide
        c = hole.centroid.astype(np.float32)
        cm = gl.GLScatterPlotItem(
            pos=c.reshape(1, 3),
            color=(1.0, 1.0, 0.20, 1.0), size=14.0, pxMode=True,
        )
        self.addItem(cm)
        self._highlight_items.append(cm)
        self.update()


class _VertexEditDialog(QDialog):
    """Sub-dialogo: mover un vertice del hueco a una nueva posicion."""

    def __init__(self, mesh, hole, parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Editar vertice del hueco")
        self._mesh = mesh
        self._hole = hole
        self._chosen_vertex = hole.boundary_vertex_indices[0]
        self._new_pos = np.asarray(mesh.vertices[self._chosen_vertex], dtype=float)

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Elegi el vertice del ciclo a mover y su nueva posicion:"))

        # Lista de vertices del ciclo
        self.list_v = QListWidget()
        self.list_v.setMaximumHeight(180)
        for vi in hole.boundary_vertex_indices:
            p = mesh.vertices[vi]
            self.list_v.addItem(
                f"v{vi}  @ ({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})"
            )
        self.list_v.setCurrentRow(0)
        self.list_v.currentRowChanged.connect(self._on_pick_vertex)
        v.addWidget(self.list_v)

        # Spinboxes XYZ
        f = QFormLayout()
        self.sb_x = self._spin(self._new_pos[0])
        self.sb_y = self._spin(self._new_pos[1])
        self.sb_z = self._spin(self._new_pos[2])
        for sb in (self.sb_x, self.sb_y, self.sb_z):
            sb.valueChanged.connect(self._on_pos_changed)
        row = QHBoxLayout()
        row.addWidget(QLabel("X:")); row.addWidget(self.sb_x)
        row.addWidget(QLabel("Y:")); row.addWidget(self.sb_y)
        row.addWidget(QLabel("Z:")); row.addWidget(self.sb_z)
        f.addRow("Nueva posicion (m):", row)
        v.addLayout(f)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _spin(self, val):
        sb = QDoubleSpinBox()
        sb.setRange(-1e4, 1e4); sb.setDecimals(4); sb.setSingleStep(0.01)
        sb.setValue(float(val))
        return sb

    def _on_pick_vertex(self, row):
        if row < 0:
            return
        vi = self._hole.boundary_vertex_indices[row]
        self._chosen_vertex = vi
        p = self._mesh.vertices[vi]
        for sb, val in ((self.sb_x, p[0]), (self.sb_y, p[1]), (self.sb_z, p[2])):
            sb.blockSignals(True); sb.setValue(float(val)); sb.blockSignals(False)
        self._new_pos = np.asarray(p, dtype=float).copy()

    def _on_pos_changed(self):
        self._new_pos = np.array([self.sb_x.value(),
                                   self.sb_y.value(),
                                   self.sb_z.value()], dtype=float)

    @property
    def result_data(self):
        return self._chosen_vertex, self._new_pos


class MeshImportDialog(QDialog):
    """Dialogo principal de importacion + reparacion guiada.

    Uso:
        dlg = MeshImportDialog(mesh, diagnosis, parent=...)
        if dlg.exec_() == QDialog.Accepted:
            mesh_final = dlg.result_mesh
    """

    def __init__(self, mesh, diagnosis, path: str = "", parent=None):
        super().__init__(parent)
        apply_dialog_theme(self)  # tema claro (fondo blanco)
        self.setWindowTitle("Importar CAD — Diagnostico y reparacion")
        self.resize(1180, 680)         # +100 px para acomodar el panel izq
        self._mesh = mesh.copy()
        self._diag = diagnosis
        self._current_hole_idx = 0
        self._path = path
        self._undo_stack = []          # estados de malla previos (curado)
        self._sel_faces = set()        # caras seleccionadas para borrar (A+)

        self._build_ui()
        self._refresh_all()

    @property
    def result_mesh(self):
        return self._mesh

    def reset(self, mesh, diagnosis, path: str = ""):
        """Reinicia el dialogo para una NUEVA importacion, REUSANDO la instancia
        (y su unico visor GL). Crear/destruir un GLViewWidget por importacion hace
        que en Windows el contexto OpenGL se pelee con el visor principal ->
        pantalla negra. Reusando, hay un solo contexto para toda la vida de la app."""
        self._mesh = mesh.copy()
        self._diag = diagnosis
        self._current_hole_idx = 0
        self._path = path
        self._undo_stack = []
        self._sel_faces = set()
        try:
            self.lbl_path.setText(f"<b>Archivo:</b> {path or '(en memoria)'}")
        except Exception:
            pass
        try:
            self.btn_undo.setEnabled(False)
            self.btn_pick.setChecked(False)
        except Exception:
            pass
        self._refresh_all()

    def done(self, r):
        """Al aceptar/cancelar: liberar el visor GL y romper el ciclo del callback
        de picking (preview -> dialog). Sin esto, re-abrir el importador acumula
        contextos OpenGL y en Windows congela el driver. `result_mesh` (self._mesh)
        no es GL, sigue disponible para el caller despues de exec_()."""
        try:
            self._cleanup_gl()
        except Exception:
            pass
        super().done(r)

    def _cleanup_gl(self):
        # SOLO cortar el ciclo del callback de picking (preview -> dialog). NO
        # destruir el visor GL (deleteLater/setParent): comparte el contexto
        # OpenGL con el visor principal de la app, y destruirlo lo corrompe ->
        # el panel CAD queda en PANTALLA NEGRA al reimportar ("Error while
        # drawing item GLMeshItem"). El dialogo se libera con su padre.
        p = getattr(self, "preview", None)
        if p is None:
            return
        try:
            p.face_pick_callback = None
            p.set_pick_mode(False)
        except Exception:
            pass

    def _build_ui(self):
        outer = QVBoxLayout(self)

        # Header con info del archivo
        h0 = QHBoxLayout()
        self.lbl_path = QLabel(f"<b>Archivo:</b> {self._path or '(en memoria)'}")
        self.lbl_path.setStyleSheet("color: #11111b;")
        h0.addWidget(self.lbl_path, 1)
        outer.addLayout(h0)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # === Izquierda: resumen + lista de problemas + botones ===
        left = QWidget()
        # Floor de ancho: el panel no puede comprimirse por debajo de esto,
        # asi los botones largos ("✓ Cerrar este hueco (auto)", etc.) siempre
        # tienen espacio. El icono Unicode al inicio (✓ ⛒ ✎ →) tiene metricas
        # de fuente irregulares que rompen el sizeHint() default de Qt.
        left.setMinimumWidth(440)
        L = QVBoxLayout(left)
        L.setContentsMargins(8, 8, 8, 8)

        grp_sum = QGroupBox("Resumen de la malla")
        sv = QVBoxLayout(grp_sum)
        self.txt_summary = QPlainTextEdit()
        self.txt_summary.setReadOnly(True)
        self.txt_summary.setMaximumHeight(180)
        self.txt_summary.setStyleSheet(
            "QPlainTextEdit { background:#eff1f5; color:#11111b; "
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 9pt; }"
        )
        sv.addWidget(self.txt_summary)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        sv.addWidget(self.lbl_status)
        L.addWidget(grp_sum)

        grp_holes = QGroupBox("Problemas detectados (huecos)")
        hv = QVBoxLayout(grp_holes)
        self.list_holes = QListWidget()
        # Cap el alto de la lista. Antes hv.addWidget(self.list_holes, 1) +
        # L.addWidget(grp_holes, 1) le daba stretch infinito, lo que en
        # pantallas chicas comia todo el espacio vertical y recortaba los
        # botones de "Acciones para el hueco" abajo.
        self.list_holes.setMaximumHeight(140)
        self.list_holes.currentRowChanged.connect(self._on_select_hole)
        hv.addWidget(self.list_holes)
        L.addWidget(grp_holes)

        # Botones de accion
        grp_act = QGroupBox("Acciones para el hueco seleccionado")
        av = QVBoxLayout(grp_act)
        # min width comun para todos los botones de esta seccion: alcanza
        # para el mas largo + padding QSS Catppuccin (8px+14px lateral).
        _BTN_MIN_W = 380
        # text-align:left + padding-left evita que Qt clipee el primer
        # caracter del texto cuando el icono unicode al inicio tiene
        # metricas anchas. Aplicado via styleSheet local para no impactar
        # otros botones.
        _BTN_STYLE = "QPushButton { text-align: left; padding-left: 16px; }"
        self.btn_fill = QPushButton("✓  Cerrar este hueco (auto)")
        self.btn_fill.setObjectName("PrimaryButton")
        self.btn_fill.setMinimumWidth(_BTN_MIN_W)
        self.btn_fill.setStyleSheet(_BTN_STYLE)
        self.btn_fill.clicked.connect(self._fill_current)
        av.addWidget(self.btn_fill)

        self.btn_snap = QPushButton("⛒  Soldar a vertices cercanos")
        self.btn_snap.setMinimumWidth(_BTN_MIN_W)
        self.btn_snap.setStyleSheet(_BTN_STYLE)
        self.btn_snap.setToolTip(
            "Intenta fusionar vertices del hueco con vertices cercanos\n"
            "de la malla principal (T-junctions, vertices duplicados).")
        self.btn_snap.clicked.connect(self._snap_current)
        av.addWidget(self.btn_snap)

        snap_row = QHBoxLayout()
        snap_row.addWidget(QLabel("Tolerancia snap (m):"))
        self.sb_snap_tol = QDoubleSpinBox()
        self.sb_snap_tol.setRange(1e-5, 1.0); self.sb_snap_tol.setDecimals(5)
        self.sb_snap_tol.setSingleStep(1e-3)
        self.sb_snap_tol.setValue(1e-3)
        snap_row.addWidget(self.sb_snap_tol)
        snap_row.addStretch()
        av.addLayout(snap_row)

        self.btn_edit_v = QPushButton("✎  Mover un vertice del hueco...")
        self.btn_edit_v.setMinimumWidth(_BTN_MIN_W)
        self.btn_edit_v.setStyleSheet(_BTN_STYLE)
        self.btn_edit_v.clicked.connect(self._edit_vertex_current)
        av.addWidget(self.btn_edit_v)

        self.btn_skip = QPushButton("→  Omitir este hueco")
        self.btn_skip.setMinimumWidth(_BTN_MIN_W)
        self.btn_skip.setStyleSheet(_BTN_STYLE)
        self.btn_skip.clicked.connect(self._skip_current)
        av.addWidget(self.btn_skip)

        L.addWidget(grp_act)

        # Botones globales
        grp_glob = QGroupBox("Acciones globales")
        gv = QVBoxLayout(grp_glob)
        self.btn_auto_all = QPushButton("Reparar TODO automaticamente")
        self.btn_auto_all.setMinimumWidth(_BTN_MIN_W)
        self.btn_auto_all.setStyleSheet(_BTN_STYLE)
        self.btn_auto_all.clicked.connect(self._auto_all)
        gv.addWidget(self.btn_auto_all)
        self.btn_merge_dups = QPushButton("Fusionar vertices duplicados")
        self.btn_merge_dups.setMinimumWidth(_BTN_MIN_W)
        self.btn_merge_dups.setStyleSheet(_BTN_STYLE)
        self.btn_merge_dups.clicked.connect(self._merge_dups)
        gv.addWidget(self.btn_merge_dups)
        self.btn_normalize = QPushButton("Normalizar (winding/normales)")
        self.btn_normalize.setMinimumWidth(_BTN_MIN_W)
        self.btn_normalize.setStyleSheet(_BTN_STYLE)
        self.btn_normalize.clicked.connect(self._normalize)
        gv.addWidget(self.btn_normalize)
        # Accion DESTRUCTIVA y explicita: quedarse con el cuerpo mas grande. Muestra
        # PREVIEW (rojo = lo que se descarta) y pide confirmar antes de aplicar. No
        # es automatica (nunca dentro de «Curar todo»): puede borrar objetos
        # interiores validos (una columna) y eso lo decide el usuario, viendolo.
        self.btn_keep_big = QPushButton("Quedarme con el cuerpo más grande…")
        self.btn_keep_big.setMinimumWidth(_BTN_MIN_W)
        self.btn_keep_big.setStyleSheet(_BTN_STYLE)
        self.btn_keep_big.setToolTip(
            "Descarta todos los cuerpos MENOS el más grande. Útil si el recinto es "
            "un cuerpo y el resto es basura. Te muestra en ROJO qué se borraría y "
            "pide confirmar. OJO: puede borrar objetos interiores (columnas).")
        self.btn_keep_big.clicked.connect(self._keep_largest_preview)
        gv.addWidget(self.btn_keep_big)
        L.addWidget(grp_glob)

        # === Curar CAD roto (panos sueltos / vertices duplicados / caras basura) ===
        grp_cure = QGroupBox("Curar CAD roto")
        cv = QVBoxLayout(grp_cure)
        self.lbl_cure_stats = QLabel("")
        self.lbl_cure_stats.setWordWrap(True)
        self.lbl_cure_stats.setStyleSheet("color:#11111b; font-size:9pt;")
        cv.addWidget(self.lbl_cure_stats)

        self.btn_cure_all = QPushButton("Curar todo (auto)")
        self.btn_cure_all.setObjectName("PrimaryButton")
        self.btn_cure_all.setMinimumWidth(_BTN_MIN_W)
        self.btn_cure_all.setStyleSheet(_BTN_STYLE)
        self.btn_cure_all.setToolTip(
            "Soldar por distancia + tirar cuerpos chicos + tapar huecos + "
            "normalizar. No garantiza estanco si faltan superficies.")
        self.btn_cure_all.clicked.connect(self._cure_all)
        cv.addWidget(self.btn_cure_all)

        weld_row = QHBoxLayout()
        weld_row.addWidget(QLabel("Soldar por distancia (m):"))
        self.sb_weld_tol = QDoubleSpinBox()
        self.sb_weld_tol.setRange(1e-4, 1.0); self.sb_weld_tol.setDecimals(4)
        self.sb_weld_tol.setSingleStep(5e-3); self.sb_weld_tol.setValue(0.02)
        weld_row.addWidget(self.sb_weld_tol)
        self.btn_weld = QPushButton("Soldar (unir paños)")
        self.btn_weld.setStyleSheet(_BTN_STYLE)
        self.btn_weld.setToolTip(
            "Une vertices a menos de esta distancia: junta paños con vertices "
            "duplicados (la causa nº1 de 'decenas de cuerpos' en exports de EASE).")
        self.btn_weld.clicked.connect(self._cure_weld)
        weld_row.addWidget(self.btn_weld)
        cv.addLayout(weld_row)

        small_row = QHBoxLayout()
        small_row.addWidget(QLabel("Borrar cuerpos con menos de"))
        self.sb_min_faces = QSpinBox()
        self.sb_min_faces.setRange(1, 10000); self.sb_min_faces.setValue(4)
        small_row.addWidget(self.sb_min_faces)
        small_row.addWidget(QLabel("caras"))
        self.btn_drop_small = QPushButton("Borrar")
        self.btn_drop_small.setStyleSheet(_BTN_STYLE)
        self.btn_drop_small.clicked.connect(self._cure_drop_small)
        small_row.addWidget(self.btn_drop_small)
        cv.addLayout(small_row)

        # Borrar cuerpos por VOLUMEN (umbral ajustable): saca panos degenerados
        # (volumen ~0) sin tocar el recinto ni la columna. Con preview + confirmar.
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Borrar cuerpos de volumen ≤"))
        self.sb_vol_thresh = QDoubleSpinBox()
        self.sb_vol_thresh.setRange(0.0, 100000.0)
        self.sb_vol_thresh.setDecimals(3)
        self.sb_vol_thresh.setSingleStep(0.1)
        self.sb_vol_thresh.setValue(0.01)
        self.sb_vol_thresh.setSuffix(" m³")
        vol_row.addWidget(self.sb_vol_thresh)
        self.btn_drop_vol = QPushButton("Borrar…")
        self.btn_drop_vol.setStyleSheet(_BTN_STYLE)
        self.btn_drop_vol.setToolTip(
            "Descarta los cuerpos cuyo volumen sea ≤ el umbral (paños de espesor "
            "cero, basura). Subí el umbral para incluir cuerpos más grandes. Te "
            "muestra en ROJO qué borraría y pide confirmar.")
        self.btn_drop_vol.clicked.connect(self._drop_low_volume_preview)
        vol_row.addWidget(self.btn_drop_vol)
        cv.addLayout(vol_row)

        # Seleccionar y borrar caras (A+)
        self.btn_pick = QPushButton("Seleccionar caras a borrar (click)")
        self.btn_pick.setCheckable(True)
        self.btn_pick.setMinimumWidth(_BTN_MIN_W)
        self.btn_pick.setStyleSheet(_BTN_STYLE)
        self.btn_pick.setToolTip(
            "Activá y hacé click sobre las caras basura en el preview 3D para "
            "seleccionarlas (rojo). Volvé a clickear para deseleccionar.")
        self.btn_pick.toggled.connect(self._toggle_pick)
        cv.addWidget(self.btn_pick)
        sel_row = QHBoxLayout()
        self.btn_drop_sel = QPushButton("Borrar caras seleccionadas (0)")
        self.btn_drop_sel.setStyleSheet(_BTN_STYLE)
        self.btn_drop_sel.clicked.connect(self._cure_drop_selected)
        self.btn_drop_sel.setEnabled(False)
        sel_row.addWidget(self.btn_drop_sel)
        self.btn_clear_sel = QPushButton("Limpiar")
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        sel_row.addWidget(self.btn_clear_sel)
        cv.addLayout(sel_row)

        under = QHBoxLayout()
        self.btn_undo = QPushButton("Deshacer")
        self.btn_undo.setToolTip("Deshace la última operación de curado.")
        self.btn_undo.clicked.connect(self._undo_cure)
        self.btn_undo.setEnabled(False)
        under.addWidget(self.btn_undo)
        self.btn_help_close = QPushButton("Cómo cerrar mi CAD…")
        self.btn_help_close.clicked.connect(self._show_close_help)
        under.addWidget(self.btn_help_close)
        cv.addLayout(under)

        L.addWidget(grp_cure)
        L.addStretch(1)   # empuja todo arriba; sin esto Qt estira el ultimo
                          # group para llenar y los botones se ven gigantes

        # El panel izquierdo va en un QScrollArea: si la ventana es más baja que
        # el contenido, Qt comprimía los botones y les recortaba el texto. Con
        # scroll cada widget mantiene su alto natural y aparece barra si hace falta.
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left)
        left_scroll.setMinimumWidth(465)     # left(440) + barra
        split.addWidget(left_scroll)

        # === Derecha: preview 3D ===
        right = QWidget()
        R = QVBoxLayout(right)
        R.setContentsMargins(8, 8, 8, 8)
        R.addWidget(QLabel("Preview 3D (rojo = hueco seleccionado)"))
        self.preview = _MeshPreview()
        R.addWidget(self.preview, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        # Panel izquierdo: 500 px (era 400, los botones "Reparar TODO
        # automaticamente" / "Soldar a vertices cercanos" no entraban con
        # padding del estilo Catppuccin).
        # NOTA: el panel izquierdo tiene minimumWidth=440 (ver mas arriba)
        # asi que aunque el usuario achique la ventana, los botones siguen
        # legibles. setSizes() es solo el size INICIAL.
        split.setSizes([500, 700])

        # === Footer ===
        foot = QHBoxLayout()
        self.btn_export = QPushButton("Exportar CAD curado…")
        self.btn_export.setToolTip(
            "Guarda la malla ACTUAL (ya curada) a un archivo .obj/.stl/.ply para "
            "reusarla o compartirla. Exportá recién cuando sea estanca.")
        self.btn_export.clicked.connect(self._export_cured)
        foot.addWidget(self.btn_export)
        foot.addStretch()
        self.btns_main = QDialogButtonBox(QDialogButtonBox.Ok |
                                            QDialogButtonBox.Cancel)
        self.btns_main.button(QDialogButtonBox.Ok).setText("Aceptar y usar esta malla")
        self.btns_main.button(QDialogButtonBox.Cancel).setText("Cancelar importacion")
        self.btns_main.accepted.connect(self.accept)
        self.btns_main.rejected.connect(self.reject)
        foot.addWidget(self.btns_main)
        outer.addLayout(foot)

        # Estilo de botones
        for b in self.findChildren(QPushButton):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # -----------------------------------------------------------------------
    # Refresh
    # -----------------------------------------------------------------------
    def _refresh_all(self):
        # Gate barato: si la malla esta MUY rota (miles de aristas abiertas), NO
        # correr find_holes ni armar la lista de huecos en cada refresco (congela
        # la UI). Se muestra el diagnostico numerico y se invita a «Curar todo».
        qs = gi.quick_stats(self._mesh)
        too_broken = qs["n_open_edges"] > 500 or qs["n_faces"] > 20000
        # Re-diagnosticar la malla actual (puede haber cambiado tras una accion)
        self._diag = gi.diagnose(self._mesh, skip_holes=too_broken)
        self.txt_summary.setPlainText(self._diag.summary())
        self._too_broken = too_broken

        # Mensaje de estado verde/amarillo
        if self._diag.ok:
            self.lbl_status.setText(
                "<span style='color:#40a02b;font-weight:600'>"
                "✓ Malla lista para mallado volumetrico.</span>"
            )
        elif too_broken:
            self.lbl_status.setText(
                "<span style='color:#b45309;font-weight:600'>"
                "Malla muy rota (muchos paños sueltos / aristas abiertas). El "
                "análisis hueco-por-hueco se omitió por rendimiento: usá "
                "«Curar todo (auto)» primero.</span>"
            )
        else:
            self.lbl_status.setText(
                "<span style='color:#b45309;font-weight:600'>"
                "Aún hay problemas. Reparalos o forza Aceptar bajo tu responsabilidad."
                "</span>"
            )

        # Lista de huecos
        self.list_holes.clear()
        for i, h in enumerate(self._diag.holes):
            item = QListWidgetItem(
                f"Hueco {i+1}  ·  {len(h.boundary_vertex_indices)} vertices  ·  "
                f"area {h.area:.4f} m²"
            )
            self.list_holes.addItem(item)
        if self._diag.holes:
            self._current_hole_idx = min(self._current_hole_idx,
                                           len(self._diag.holes) - 1)
            self.list_holes.setCurrentRow(self._current_hole_idx)
        else:
            self._current_hole_idx = 0

        # Habilitar/deshabilitar botones de hueco actual
        has_h = bool(self._diag.holes)
        for b in (self.btn_fill, self.btn_snap, self.btn_edit_v, self.btn_skip):
            b.setEnabled(has_h)

        # Preview 3D
        self.preview.show_mesh(self._mesh)
        if self._sel_faces:
            self.preview.highlight_faces(self._mesh, self._sel_faces)
        elif has_h:
            self.preview.highlight_hole(self._mesh,
                                          self._diag.holes[self._current_hole_idx])
        else:
            self.preview.clear_highlights()

        # Stats de curado en vivo + boton de seleccion
        if hasattr(self, "lbl_cure_stats"):
            self._refresh_cure_stats()
        if hasattr(self, "btn_drop_sel"):
            self._update_sel_button()

    def _on_select_hole(self, row):
        if 0 <= row < len(self._diag.holes):
            self._current_hole_idx = row
            self.preview.highlight_hole(self._mesh, self._diag.holes[row])

    # -----------------------------------------------------------------------
    # Acciones por hueco
    # -----------------------------------------------------------------------
    def _fill_current(self):
        if not self._diag.holes:
            return
        h = self._diag.holes[self._current_hole_idx]
        self._mesh = gi.fill_hole_planar(self._mesh, h)
        self._refresh_all()

    def _snap_current(self):
        if not self._diag.holes:
            return
        h = self._diag.holes[self._current_hole_idx]
        tol = float(self.sb_snap_tol.value())
        before = len(self._diag.holes)
        self._mesh = gi.snap_hole_vertices(self._mesh, h, snap_tolerance=tol)
        self._refresh_all()
        after = len(self._diag.holes)
        if after >= before:
            QMessageBox.information(
                self, "Sin cambios",
                f"No se encontraron vertices cercanos a < {tol:g} m. "
                "Probá con una tolerancia mayor."
            )

    def _edit_vertex_current(self):
        if not self._diag.holes:
            return
        h = self._diag.holes[self._current_hole_idx]
        dlg = _VertexEditDialog(self._mesh, h, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            vidx, new_pos = dlg.result_data
            self._mesh = gi.move_vertex(self._mesh, vidx, new_pos)
            self._refresh_all()

    def _skip_current(self):
        if self._current_hole_idx + 1 < len(self._diag.holes):
            self._current_hole_idx += 1
            self.list_holes.setCurrentRow(self._current_hole_idx)
        else:
            QMessageBox.information(self, "Fin de la lista",
                                      "No hay mas huecos para revisar.")

    # -----------------------------------------------------------------------
    # Acciones globales
    # -----------------------------------------------------------------------
    def _auto_all(self):
        # "Reparar TODO automaticamente" ahora corre el curado COMPLETO (soldar +
        # tirar cuerpos chicos + tapar + normalizar + fallback cuerpo-mas-grande),
        # no solo tapar huecos: sobre un CAD fragmentado (paños sueltos) tapar
        # huecos solo no cierra nada. Asi los dos botones auto hacen lo robusto.
        self._cure_all()

    def _merge_dups(self):
        self._mesh = gi.merge_close_vertices(self._mesh, tolerance=1e-4)
        self._refresh_all()

    def _normalize(self):
        self._mesh = gi.normalize_mesh(self._mesh)
        self._refresh_all()

    # -----------------------------------------------------------------------
    # Curar CAD roto
    # -----------------------------------------------------------------------
    def _refresh_cure_stats(self):
        try:
            s = gi.quick_stats(self._mesh)
        except Exception:
            return
        wt = ("<span style='color:#40a02b;font-weight:600'>sí</span>"
              if s["watertight"] else
              "<span style='color:#b45309;font-weight:600'>NO</span>")
        txt = (f"Cuerpos: <b>{s['n_components']}</b> · aristas abiertas: "
               f"<b>{s['n_open_edges']}</b> · no-manifold: {s['n_non_manifold']} · "
               f"estanco: {wt}")
        # Volumenes por cuerpo (para elegir el umbral de «Borrar por volumen»).
        if 2 <= s["n_components"] <= 12 and s["n_faces"] <= 20000:
            try:
                vols = sorted((v for _, v in gi.component_face_groups(self._mesh)),
                              reverse=True)
                txt += ("<br>Volúmenes por cuerpo: "
                        + ", ".join(f"{v:.3g}" for v in vols) + " m³")
            except Exception:
                pass
        self.lbl_cure_stats.setText(txt)

    def _apply_cure(self, new_mesh, note: str = ""):
        """Aplica una malla curada: apila undo, reemplaza, limpia seleccion,
        refresca. Envuelto en cursor de espera (algunas ops re-diagnostican)."""
        self._undo_stack.append(self._mesh.copy())
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)
        self._mesh = new_mesh
        self._sel_faces = set()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._refresh_all()
        finally:
            QApplication.restoreOverrideCursor()
        self.btn_undo.setEnabled(bool(self._undo_stack))

    def _undo_cure(self):
        if not self._undo_stack:
            return
        self._mesh = self._undo_stack.pop()
        self._sel_faces = set()
        self._refresh_all()
        self.btn_undo.setEnabled(bool(self._undo_stack))

    def _cure_weld(self):
        tol = float(self.sb_weld_tol.value())
        before = gi.quick_stats(self._mesh)["n_components"]
        self._apply_cure(gi.merge_close_vertices(self._mesh, tol))
        after = gi.quick_stats(self._mesh)["n_components"]
        if after >= before:
            QMessageBox.information(
                self, "Soldar",
                "No se unió ningún cuerpo con esa tolerancia. Probá una mayor "
                "(los paños pueden tener huecos reales, no solo vértices duplicados).")

    def _drop_low_volume_preview(self):
        """Preview + confirmacion para borrar cuerpos de volumen <= umbral. Resalta
        en ROJO lo que se borraria y solo aplica si el usuario confirma."""
        thr = float(self.sb_vol_thresh.value())
        keep, drop, vols = gi.low_volume_faces(self._mesh, thr)
        if len(drop) == 0:
            allvols = sorted(v for _, v in gi.component_face_groups(self._mesh))
            vt = ", ".join(f"{v:.3g}" for v in allvols)
            QMessageBox.information(
                self, "Borrar por volumen",
                f"No hay cuerpos con volumen ≤ {thr:g} m³.\n\nVolúmenes de los "
                f"cuerpos actuales: {vt} m³.\n\nElegí un umbral entre el volumen "
                "que querés borrar y el que querés conservar.")
            return
        if len(keep) == 0:
            QMessageBox.warning(
                self, "Borrar por volumen",
                "Con ese umbral se borrarían TODOS los cuerpos. Bajá el umbral.")
            return
        self.btn_pick.setChecked(False)
        self._sel_faces = set(int(i) for i in drop)
        self.preview.highlight_faces(self._mesh, self._sel_faces)
        self._update_sel_button()
        QApplication.processEvents()            # pintar el rojo ANTES del modal
        vtxt = ", ".join(f"{v:.3g}" for v in vols)
        ret = QMessageBox.question(
            self, "Borrar cuerpos por volumen",
            f"Se DESCARTAN {len(vols)} cuerpo(s) con volumen ≤ {thr:g} m³ "
            f"(volúmenes: {vtxt} m³), marcados en ROJO.\n\nSe conservan los demás "
            "(recinto, columnas, etc.).\n\n¿Aplicar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            out, _n = gi.remove_low_volume_components(self._mesh, thr)
            self._apply_cure(out)
        else:
            self._clear_selection()

    def _keep_largest_preview(self):
        """Preview + confirmacion antes de descartar cuerpos. Resalta en ROJO lo
        que se borraria (todo menos el cuerpo mas grande) y solo aplica si el
        usuario confirma viendolo. Accion destructiva -> nunca silenciosa."""
        keep, drop = gi.largest_component_faces(self._mesh)
        if len(drop) == 0:
            QMessageBox.information(
                self, "Un solo cuerpo",
                "La malla ya es un solo cuerpo: no hay nada que descartar.")
            return
        # Mostrar en rojo lo que se descartaria.
        self.btn_pick.setChecked(False)         # salir de modo picking si estaba
        self._sel_faces = set(int(i) for i in drop)
        self.preview.highlight_faces(self._mesh, self._sel_faces)
        self._update_sel_button()
        QApplication.processEvents()            # pintar el rojo ANTES del modal
        n_bodies = len(np.unique(gi.face_component_labels(self._mesh)))
        ret = QMessageBox.question(
            self, "Quedarme con el cuerpo más grande",
            f"Se CONSERVA el cuerpo más grande ({len(keep)} caras) y se "
            f"DESCARTAN {n_bodies - 1} cuerpo(s) ({len(drop)} caras), marcados en "
            "ROJO en el preview.\n\nOJO: si alguno de esos cuerpos es parte real "
            "de la sala (por ejemplo una columna interior), se va a perder.\n\n"
            "¿Aplicar?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._apply_cure(gi.keep_largest_component(self._mesh))
        else:
            self._clear_selection()

    def _cure_drop_small(self):
        out, removed = gi.remove_small_components(self._mesh,
                                                  int(self.sb_min_faces.value()))
        if removed == 0:
            QMessageBox.information(self, "Borrar cuerpos chicos",
                                    "No hay cuerpos por debajo de ese umbral.")
            return
        self._apply_cure(out)

    def _cure_all(self):
        m, rep = gi.cure_auto(self._mesh, weld_tol=float(self.sb_weld_tol.value()),
                              min_faces=int(self.sb_min_faces.value()))
        self._apply_cure(m)
        a = rep["after"]
        msg = (f"Curado: {rep['before']['n_components']} → {a['n_components']} "
               f"cuerpos; aristas abiertas {rep['before']['n_open_edges']} → "
               f"{a['n_open_edges']}.")
        if a["watertight"]:
            QMessageBox.information(self, "Curar todo",
                                    msg + "\n\nLa malla quedó ESTANCA.")
        elif a["n_components"] > 1:
            QMessageBox.warning(
                self, "Curar todo",
                msg + f"\n\nQuedaron {a['n_components']} cuerpos separados. Si el "
                "recinto es UNO de ellos y los demás son basura (paños sueltos), "
                "usá «Quedarme con el cuerpo más grande…» en Acciones globales "
                "(te muestra qué conserva y qué descarta antes de aplicar). Si "
                "faltan superficies reales, cerralas a mano o en tu 3D (mirá "
                "«Cómo cerrar mi CAD…»).")
        else:
            QMessageBox.warning(
                self, "Curar todo",
                msg + "\n\nAún NO es estanca: faltan superficies (aberturas "
                "reales) que hay que cerrar a mano o en tu 3D. Mirá «Cómo cerrar "
                "mi CAD…».")

    # --- seleccion de caras (A+) ---
    def _toggle_pick(self, on: bool):
        self.preview.face_pick_callback = self._on_face_picked if on else None
        self.preview.set_pick_mode(on)
        if on:
            QMessageBox.information(
                self, "Seleccionar caras",
                "Hacé click sobre las caras basura en el preview 3D para "
                "marcarlas (rojo). Volvé a clickear una cara para desmarcarla. "
                "Después «Borrar caras seleccionadas».")

    def _on_face_picked(self, idx: int):
        if idx in self._sel_faces:
            self._sel_faces.discard(idx)
        else:
            self._sel_faces.add(idx)
        self.preview.highlight_faces(self._mesh, self._sel_faces)
        self._update_sel_button()

    def _update_sel_button(self):
        n = len(self._sel_faces)
        self.btn_drop_sel.setText(f"Borrar caras seleccionadas ({n})")
        self.btn_drop_sel.setEnabled(n > 0)

    def _clear_selection(self):
        self._sel_faces = set()
        self.preview.highlight_faces(self._mesh, [])
        self._update_sel_button()

    def _cure_drop_selected(self):
        if not self._sel_faces:
            return
        sel = set(self._sel_faces)
        self._apply_cure(gi.drop_faces(self._mesh, sel))

    # --- guia para cerrar el CAD en un 3D externo (B) ---
    def _show_close_help(self):
        html = (
            "<h3>Cómo cerrar tu CAD para que sea un sólido</h3>"
            "<p>El interior de la sala solo está bien definido si la malla es un "
            "<b>sólido cerrado (watertight)</b>: sin aristas abiertas, un solo "
            "cuerpo, normales hacia afuera. Los export de EASE/SketchUp suelen "
            "venir como paños sueltos.</p>"
            "<p><b>Blender</b> (gratis): importá el .obj; en Modo Edición: "
            "<i>A</i> (seleccionar todo) → <i>M</i> → <i>By Distance</i> (soldar "
            "vértices); <i>Mesh → Normals → Recalculate Outside</i> "
            "(Shift+N); <i>Select → All by Trait → Non Manifold</i> para ver "
            "aberturas y <i>F</i>/<i>Grid Fill</i> para taparlas; add-on "
            "<i>3D-Print Toolbox → Make Manifold</i>. Exportá .obj o .stl.</p>"
            "<p><b>SketchUp</b>: usá <i>Solid Inspector²</i> (extensión gratis) "
            "para detectar y arreglar bordes/caras; el modelo debe quedar como "
            "un «Solid Group/Component». Exportá .stl (extensión STL).</p>"
            "<p><b>Rhino</b>: <i>Weld</i> + <i>MergeAllFaces</i>, tapá aberturas "
            "con <i>Patch</i>/<i>MeshFill</i>, revisá con <i>ShowEdges</i> "
            "(Naked Edges = 0) y <i>Check</i>. Exportá .obj/.stl.</p>"
            "<p><b>FreeCAD</b> (gratis): banco <i>Mesh Design</i> → "
            "<i>Analyze → Evaluate & repair mesh</i> (arregla no-manifold, "
            "huecos, orientación).</p>"
            "<p>La clave en cualquiera: <b>0 aristas abiertas (naked edges)</b> y "
            "<b>1 solo cuerpo</b>. Después reimportá acá.</p>")
        box = QMessageBox(self)
        box.setWindowTitle("Cómo cerrar tu CAD")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec_()

    def _export_cured(self):
        """Exporta la malla ACTUAL (ya curada) a .obj/.stl/.ply para reusarla o
        compartirla, sin tener que guardar un .room. Avisa si todavia no es
        estanca (se puede exportar igual, pero el interior no estara definido)."""
        import os
        try:
            wt = bool(self._mesh.is_watertight)
        except Exception:
            wt = False
        if not wt:
            ret = QMessageBox.question(
                self, "La malla no es estanca",
                "La malla ACTUAL todavía NO es un sólido cerrado (watertight). "
                "Podés exportarla igual, pero para simular/optimizar bien conviene "
                "curarla hasta que sea estanca.\n\n¿Exportar de todas formas?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        base = os.path.splitext(os.path.basename(self._path or "recinto"))[0]
        suggested = os.path.join(
            os.path.dirname(self._path) if self._path else "",
            f"{base}_curado.obj")
        path, _flt = QFileDialog.getSaveFileName(
            self, "Exportar CAD curado", suggested,
            "Wavefront OBJ (*.obj);;STL (*.stl);;PLY (*.ply)")
        if not path:
            return
        try:
            self._mesh.export(path)          # trimesh elige el formato por extension
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar",
                                 f"No se pudo exportar la malla:\n{e}")
            return
        QMessageBox.information(
            self, "Exportado",
            f"Malla curada exportada a:\n{path}\n\n"
            f"({len(self._mesh.vertices)} vértices, {len(self._mesh.faces)} caras, "
            f"{'estanca' if wt else 'NO estanca'})")
