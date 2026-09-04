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
        if len(faces) == 0:
            return
        self._mesh_item = gl.GLMeshItem(
            meshdata=gl.MeshData(vertexes=verts, faces=faces),
            smooth=True, color=(0.5, 0.7, 1.0, 0.30),
            shader="shaded", glOptions="translucent",
        )
        self.addItem(self._mesh_item)

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

        self._build_ui()
        self._refresh_all()

    @property
    def result_mesh(self):
        return self._mesh

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
        L.addWidget(grp_glob)
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
        # Re-diagnosticar la malla actual (puede haber cambiado tras una accion)
        self._diag = gi.diagnose(self._mesh)
        self.txt_summary.setPlainText(self._diag.summary())

        # Mensaje de estado verde/amarillo
        if self._diag.ok:
            self.lbl_status.setText(
                "<span style='color:#40a02b;font-weight:600'>"
                "✓ Malla lista para mallado volumetrico.</span>"
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
        if has_h:
            self.preview.highlight_hole(self._mesh,
                                          self._diag.holes[self._current_hole_idx])
        else:
            self.preview.clear_highlights()

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
        self._mesh = gi.fill_all_holes_auto(self._mesh)
        self._refresh_all()

    def _merge_dups(self):
        self._mesh = gi.merge_close_vertices(self._mesh, tolerance=1e-4)
        self._refresh_all()

    def _normalize(self):
        self._mesh = gi.normalize_mesh(self._mesh)
        self._refresh_all()
