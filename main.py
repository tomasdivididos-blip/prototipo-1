"""Prototipo 1 - Modelador de Recintos 3D en vista isometrica.

Atajos:
  Ctrl+Z          deshacer
  Ctrl+Y / Ctrl+Shift+Z   rehacer
  Ctrl+S          guardar
  Ctrl+Shift+S    guardar como
  Ctrl+O          abrir
  0               vista isometrica (reset camara)
  1               modo Rotar on/off (arrastrar con izquierdo orbita/rota;
                  para mouse sin rueda, p.ej. Magic Mouse). Esc tambien sale.

Stack: PyQt5 (Qt en C++) + pyqtgraph / PyOpenGL (OpenGL en C/C++) + NumPy.
"""

import os
import sys
import json
from pathlib import Path

os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

# Fix macOS/venv: Qt puede no encontrar su plugin de plataforma ("cocoa" en Mac,
# "windows" en Win) cuando corre desde fuente en un venv de PyQt5 -> la ruta de
# plugins queda vacia y aborta ("Could not find the Qt platform plugin ... in ''",
# Abort trap 6 / codigo 134). Se deriva la ruta de la instalacion de PyQt5 y se
# setea ANTES de importar QtWidgets. El .exe de Windows (PyInstaller) no lo
# necesita, pero setear no molesta.
try:
    import PyQt5 as _pyqt5
    _qt_base = os.path.dirname(_pyqt5.__file__)
    for _sub in ("Qt5", "Qt"):
        _plugins = os.path.join(_qt_base, _sub, "plugins")
        if os.path.isdir(os.path.join(_plugins, "platforms")):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                                  os.path.join(_plugins, "platforms"))
            os.environ.setdefault("QT_PLUGIN_PATH", _plugins)
            break
except Exception:
    pass

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QShortcut, QFileDialog, QMessageBox, QDialog, QTabWidget, QProgressDialog,
)
import time as _time

from controls import ControlPanel
from viewer import IsoViewer
from geometry import make_room, room_metrics, make_arch_ribs, build_room_geometry
from shape_dialog import ShapeDrawDialog
from style import DARK_QSS
from acoustic_panel import AcousticPanel
from prediction_panel import PredictionPanel


FILE_FORMAT = "prototipo1.room"
FILE_VERSION = 8  # v8: absorption_patches (parches sub-cara); v7: furniture; v6: wall_profiles; v5: response Q(f); v4: face_materials
FILE_FILTER = "Recinto Prototipo 1 (*.room *.json)"
DEFAULT_DIR = str(Path.home() / "Desktop")
UNDO_LIMIT = 10   # cantidad de acciones reversibles (ctrl+z / ctrl+y)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prototipo 1 - Modelador de Recintos 3D")
        self.resize(1320, 820)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Panel izquierdo: pestañas (Geometría / Acústica)
        self.controls = ControlPanel()

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(380)
        self.tabs.setMaximumWidth(500)
        self.tabs.addTab(self.controls, "Geometría")
        root.addWidget(self.tabs)

        # Visor + barra de metricas
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        self.viewer = IsoViewer()
        rl.addWidget(self.viewer, 1)

        # Geometria actual (verts, tris) cacheada para el panel acustico.
        self._surface_verts = None
        self._surface_tris = None

        # Panel acustico (segunda pestaña).
        self.acoustic = AcousticPanel(
            viewer=self.viewer,
            get_surface=self._get_current_surface,
            get_dims_hint=self._get_dims_hint,
        )
        self.tabs.addTab(self.acoustic, "Acústica")

        # Panel de prediccion (tercera pestaña): describe el uso del
        # recinto y el motor sugiere dimensiones optimas. Al aplicar puede
        # modificar los sliders de Geometria o inyectar la malla como CAD.
        # Le pasamos dos callbacks para "Evaluar mi diseño actual": uno lee los
        # params del ControlPanel (geometria) y otro las fuentes reales del
        # recinto, para que el boton respete el eje elegido (geometry/location/
        # combined) y evalue TU layout de fuentes, no uno generado.
        self.prediction = PredictionPanel(
            get_design_params=self.controls.get_params,
            get_sources=lambda: self.acoustic.sources,
            get_surface=self._get_current_surface,
            # Etapa 2c: el FEM de ubicacion usa el modelo de amortiguamiento
            # elegido en Acustica (perturbacion -> xi por modo con materiales).
            get_damping_model=lambda: getattr(self.acoustic, "_damping_model", "a36"),
        )
        self.tabs.addTab(self.prediction, "Predicción")
        self.prediction.applyAsParamsRequested.connect(
            self._on_prediction_apply_params)
        self.prediction.applyAsCadRequested.connect(
            self._on_prediction_apply_cad)
        self.prediction.applySourcesRequested.connect(
            self._on_prediction_apply_sources)
        self.prediction.applyMaterialsRequested.connect(
            self._on_prediction_apply_materials)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")
        self.status.setAlignment(Qt.AlignCenter)
        # Word-wrap: un mensaje largo (p.ej. nombres de materiales) NO debe
        # estirar el label y apretar el panel izquierdo (que se cortaba).
        self.status.setWordWrap(True)
        rl.addWidget(self.status)

        root.addWidget(right, 1)
        self.setCentralWidget(central)

        # ----- Estado Undo/Redo GLOBAL y archivo actual -----
        # Undo/redo por SNAPSHOT del estado completo (params + acustica +
        # materiales + CAD), no por accion individual: garantiza que TODO sea
        # reversible sin instrumentar cada mutacion del panel. Limite UNDO_LIMIT.
        # Un timer de polling (dirty-check) detecta cualquier cambio; un check
        # de "settle" colapsa un drag continuo en una sola accion.
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._last_state: dict | None = None
        self._restoring = False          # guard de re-entrancia durante restore
        self._last_change_t = 0.0        # marca de actividad (gestos en vivo)
        self._cad_cache = None           # serializacion CAD (refrescada al cambiar)
        self._current_file: str | None = None

        # ----- Conexiones -----
        self.controls.parametersChanged.connect(self._on_params)
        self.controls.parametersChanged.connect(lambda *_: self._note_activity())
        self.controls.parametersCommitted.connect(self._on_commit)
        self.controls.cameraResetRequested.connect(self.viewer.reset_camera)
        self.controls.drawShapeRequested.connect(self._open_shape_dialog)
        self.controls.showLabelsToggled.connect(self.viewer.set_show_labels)
        self.controls.viewModeChanged.connect(self.viewer.set_view_mode)

        # Right-click drag sobre pared -> ajusta el slider de esa pared
        self.viewer.wallDragStarted.connect(self.controls.begin_wall_drag)
        self.viewer.wallDragMoved.connect(self.controls.update_wall_drag)
        self.viewer.wallDragEnded.connect(self.controls.end_wall_drag)

        # Import CAD desde el panel acustico
        self.acoustic.cadImportRequested.connect(self._open_cad_import)
        self.acoustic.cadClearRequested.connect(self._clear_cad_import)

        # Ctrl+Click derecho en el viewer 3D -> colocar fuente acustica
        self.viewer.sourceAddRequested.connect(self._on_source_add_from_viewer)
        # Doble-click sobre esfera de fuente -> editar
        self.viewer.sourceEditRequested.connect(self._on_source_edit_from_viewer)
        # Shift+Click izquierdo arrastrado -> mover fuente o receptor
        self.viewer.sourceMoveRequested.connect(self._on_source_moved_from_viewer)
        self.viewer.receiverMoveRequested.connect(self._on_receiver_moved_from_viewer)
        # Alt+Ctrl: gestos de orientacion del bafle (rotar / inclinar) en vivo.
        self.viewer.sourceRotateRequested.connect(self._on_source_rotate_from_viewer)
        self.viewer.sourceTiltRequested.connect(self._on_source_tilt_from_viewer)
        # Muebles: mismos gestos que las fuentes (mover / doble-click editar /
        # Alt+Ctrl rotar yaw). Las fuentes tienen prioridad de picking.
        self.viewer.furnitureMoveRequested.connect(self._on_furniture_moved_from_viewer)
        self.viewer.furnitureEditRequested.connect(self._on_furniture_edit_from_viewer)
        self.viewer.furnitureRotateRequested.connect(self._on_furniture_rotate_from_viewer)
        self.viewer.furnitureTiltRequested.connect(self._on_furniture_tilt_from_viewer)
        self.viewer.furnitureRollRequested.connect(self._on_furniture_roll_from_viewer)

        self._on_params(self.controls.get_params())
        self._setup_shortcuts()
        self._update_title()

        # Snapshot inicial (baseline) + timer de polling para el undo global.
        self._last_state = self._capture_state()
        self._snap_timer = QTimer(self)
        self._snap_timer.setInterval(400)
        self._snap_timer.timeout.connect(lambda: self._maybe_snapshot(False))
        self._snap_timer.start()

    # ---------- Render + metricas ----------
    def _only_origin_changed(self, params: dict) -> bool:
        """True si el UNICO param que cambio vs el render anterior es
        origin_mode (=> la malla nueva es una traslacion pura de la vieja)."""
        lp = self._last_params if hasattr(self, "_last_params") else None
        if not lp or params.get("origin_mode") == lp.get("origin_mode"):
            return False
        a = {k: vv for k, vv in params.items() if k != "origin_mode"}
        b = {k: vv for k, vv in lp.items() if k != "origin_mode"}
        return a == b

    def _shift_scene_objects(self, delta):
        """Traslada TODO lo anclado al recinto por `delta` (cambio de convencion
        de origen: el recinto se movio, los objetos deben moverse CON el para
        que nada cambie fisicamente): fuentes, receptor, puntos de escucha,
        MUEBLES y PARCHES de absorcion. Refresca los markers al final para que
        el visor muestre las posiciones nuevas sin depender del caller.

        OJO: muebles (v2.18) y parches (v2.17) se agregaron DESPUES del origen
        configurable (v2.16) y no estaban contemplados aca -> se quedaban en el
        lugar viejo mientras el recinto se movia. Si sumas un objeto nuevo
        anclado al recinto, agregalo tambien a esta lista."""
        import numpy as _np
        d = _np.asarray(delta, dtype=float)
        ap = self.acoustic
        try:
            for s in ap.sources:
                p = _np.asarray(s.position, dtype=float) + d
                s.position = (float(p[0]), float(p[1]), float(p[2]))
            ap._refresh_sources_list()
        except Exception:
            pass
        try:
            r = _np.asarray(ap.receiver, dtype=float) + d
            ap.move_receiver_to(float(r[0]), float(r[1]), float(r[2]))
        except Exception:
            pass
        try:
            for p in getattr(ap, "listen_points", []):
                p["position"] = tuple(
                    (_np.asarray(p["position"], dtype=float) + d).tolist())
            ap._refresh_listen_points()
        except Exception:
            pass
        try:
            for m in getattr(ap, "furniture", []):
                q = _np.asarray(m.position, dtype=float) + d
                m.position = (float(q[0]), float(q[1]), float(q[2]))
            if getattr(ap, "furniture", None):
                ap._refresh_furniture_list()
        except Exception:
            pass
        try:
            for pt in getattr(ap, "_patches", []):
                pt.translate(d)
            if getattr(ap, "_patches", None):
                ap._refresh_patches_summary()
        except Exception:
            pass

    def _on_params(self, params: dict):
        import numpy as _np
        from geometry import origin_offset

        # CAD activo: los sliders no gobiernan la malla; el unico param que
        # aplica es la convencion de origen -> re-anclar la malla importada.
        if getattr(self.acoustic, "_is_imported_cad", False):
            self._reanchor_cad(params.get("origin_mode", "auto"))
            self._last_params = dict(params)
            return

        origin_only = self._only_origin_changed(params)
        old_v = self._surface_verts

        # Construir en el frame natural y anclar aca (no dentro de
        # build_room_geometry) para reusar el MISMO offset con las costillas
        # del arco, que se generan en el frame sin anclar.
        raw_params = dict(params)
        raw_params["origin_mode"] = "auto"
        v, t, e, n_actual = build_room_geometry(raw_params)
        off = origin_offset(v, params.get("origin_mode", "auto"))
        if abs(off[0]) > 1e-12 or abs(off[1]) > 1e-12:
            v = (v - off).astype(v.dtype)
        arch_ribs = make_arch_ribs(**params) if params.get("arch_height", 0) > 0 else []
        if arch_ribs and (abs(off[0]) > 1e-12 or abs(off[1]) > 1e-12):
            arch_ribs = [_np.asarray(r) - off for r in arch_ribs]
        self.viewer.update_geometry(v, t, e, n_walls=n_actual, arch_ribs=arch_ribs)

        # Si SOLO cambio la convencion de origen, la malla nueva es la vieja
        # trasladada: mover fuentes y receptor con ella (nada cambia
        # fisicamente, solo el sistema de coordenadas). No aplica durante un
        # restore (las posiciones vienen del snapshot, ya en su frame).
        if (origin_only and old_v is not None and len(old_v) == len(v)
                and not getattr(self, "_restoring", False)):
            delta = v.min(axis=0) - _np.asarray(old_v).min(axis=0)
            if float(_np.linalg.norm(delta)) > 1e-9:
                self._shift_scene_objects(delta)

        # Cachear superficie actual para el panel acustico.
        self._surface_verts = v
        self._surface_tris = t
        self._last_params = dict(params)
        if hasattr(self, "acoustic") and self.acoustic is not None:
            self.acoustic.on_geometry_changed()
            # Re-agregar esferas y cruz DESPUES del mesh para que sean visibles
            self.acoustic._refresh_sources_list()
            self.acoustic._refresh_receiver_marker()

        volume, surface = room_metrics(v, t)
        self.status.setText(
            f"Volumen ≈ {volume:,.2f} m³    ·    "
            f"Superficie ≈ {surface:,.2f} m²    ·    "
            f"Vértices: {len(v)}    ·    "
            f"Caras: {params['n_walls'] + 2}"
        )

    # ---------- Importacion de CAD ----------
    def _open_cad_import(self):
        """Slot: usuario pidio importar CAD desde el panel acustico.

        Flujo con feedback en vivo via QProgressDialog (el usuario veia
        antes una congelacion silenciosa de varios segundos al cargar
        archivos grandes). Tambien:
          - Saltea el QMessageBox de confirmacion para mallas limpias
            (siempre se aceptaban con "Si" → ruido inutil).
          - Reporta cuanto tarda cada fase en el panel de estado, para
            que el usuario sepa donde se va el tiempo.
        """
        try:
            import geom_import as gi
            from geom_repair_dialog import MeshImportDialog
            import app_settings
        except ImportError as e:
            QMessageBox.critical(self, "Falta dependencia",
                                  f"No se pudo importar el modulo: {e}")
            return

        last_dir = app_settings.get("cad_last_dir", DEFAULT_DIR) or DEFAULT_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar geometria CAD",
            last_dir, gi.file_filter(),
        )
        if not path:
            return

        # Arrancar cronometro de la leyenda bajo el boton "Importar CAD".
        try:
            self.acoustic._cad_timer.start()
        except Exception:
            pass

        # Diccionario de tiempos por fase para reporte final.
        timings: dict = {}
        # ProgressDialog: visible solo si la importacion tarda > 200 ms.
        prog = QProgressDialog(
            "Cargando geometria CAD...", "Cancelar", 0, 0, self
        )
        prog.setWindowTitle("Importacion CAD")
        prog.setMinimumDuration(200)   # solo aparece si tarda
        prog.setWindowModality(Qt.WindowModal)
        prog.setAutoClose(False)
        prog.setAutoReset(False)

        def _set_progress(msg: str):
            prog.setLabelText(msg)
            QApplication.processEvents()

        # --- Paso 0: cargar archivo ---
        try:
            _set_progress(f"Cargando {Path(path).name}...")
            t0 = _time.time()
            mesh = gi.load_geometry(path, progress=_set_progress)
            timings["load"] = _time.time() - t0
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, "Error al cargar",
                                  f"No se pudo cargar el archivo:\n{e}")
            return
        if prog.wasCanceled():
            prog.close()
            self.status.setText("Importacion cancelada.")
            try: self.acoustic._cad_timer.fail("cancelado")
            except Exception: pass
            return

        # --- Paso 1: escala + orientacion ---
        try:
            t0 = _time.time()
            suggestion = gi.suggest_scale_factor(mesh)
            ext = Path(path).suffix.lower()
            Y_UP_FORMATS = {".obj", ".gltf", ".glb", ".dae", ".fbx", ".3mf"}
            suggested_up = "Y+" if ext in Y_UP_FORMATS else "Z+"

            from geom_scale_dialog import ImportScaleDialog
            # IMPORTANTE: close() (no solo hide()) cancela el forceTimer
            # interno de QProgressDialog. Si solo hicieramos hide() y el
            # load fue < minimumDuration (caso usual con archivos chicos),
            # el timer seguiria pendiente y dispararia prog.show() ENCIMA
            # del modal de escala unos segundos despues, dando la falsa
            # impresion de que la app se cuelga.
            prog.close()
            sdlg = ImportScaleDialog(mesh, suggestion,
                                      suggested_up=suggested_up, parent=self)
            if sdlg.exec_() == QDialog.Accepted:
                # Aceptado: aplicar escala (factor 1.0 si eligio "No escalar"
                # -> apply_scale se saltea por el chequeo abs(... -1) > 1e-9).
                if sdlg.chosen_up_axis != "Z+":
                    mesh = gi.apply_up_axis(mesh, sdlg.chosen_up_axis)
                if abs(sdlg.chosen_factor - 1.0) > 1e-9:
                    mesh = gi.apply_scale(mesh, sdlg.chosen_factor)
            else:
                # Usuario cancelo el import (boton "Cancelar import" / Esc / X)
                self.status.setText("Importacion cancelada.")
                try: self.acoustic._cad_timer.fail("cancelado")
                except Exception: pass
                return
            timings["scale"] = _time.time() - t0
        except Exception as e:
            QMessageBox.warning(self, "Aviso",
                f"No se pudo evaluar escala/orientacion:\n{e}")

        # Re-crear el progress dialog para las fases siguientes (diagnose
        # + repair). El anterior quedo cerrado para evitar reaparicion
        # espontanea. _set_progress() captura `prog` por nombre, asi que
        # apunta automaticamente a la nueva instancia.
        prog = QProgressDialog(
            "Diagnosticando malla...", "Cancelar", 0, 0, self
        )
        prog.setWindowTitle("Importacion CAD")
        prog.setMinimumDuration(200)
        prog.setWindowModality(Qt.WindowModal)
        prog.setAutoClose(False)
        prog.setAutoReset(False)

        # --- Paso 2: diagnostico (huecos, watertight, etc.) ---
        # Truco de performance: para mallas grandes la diagnosis es la fase
        # mas pesada (SVDs para huecos, np.unique para no-manifold). Para
        # mallas pequenas es instantanea. Reportamos progreso lo mejor que
        # podemos pero la funcion gi.diagnose es atomica.
        n_tris = int(len(mesh.faces))
        _set_progress(
            f"Diagnosticando malla ({len(mesh.vertices)} verts, "
            f"{n_tris} tris)..."
        )
        try:
            t0 = _time.time()
            diag = gi.diagnose(mesh)
            timings["diagnose"] = _time.time() - t0
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, "Error al diagnosticar",
                                  f"No se pudo diagnosticar la malla:\n{e}")
            return
        if prog.wasCanceled():
            prog.close()
            self.status.setText("Importacion cancelada.")
            try: self.acoustic._cad_timer.fail("cancelado")
            except Exception: pass
            return

        # --- Paso 3: reparacion (solo si hace falta) ---
        # Cambio respecto a la version anterior: si la malla esta limpia,
        # se IMPORTA DIRECTAMENTE sin pedir confirmacion. Antes salia un
        # QMessageBox "Yes/No" que el usuario siempre aceptaba.
        if diag.ok:
            # Cerramos el prog del diagnostico — no hay mas fases con
            # progress feedback (el centrado/poblado del visor es <50ms).
            prog.close()
            timings["repair"] = 0.0
            final_mesh = mesh
        else:
            # Mismo cuidado que con el dialogo de escala: cerrar prog para
            # cancelar su forceTimer y que no reaparezca encima del modal
            # de reparacion.
            prog.close()
            dlg = MeshImportDialog(mesh, diag, path=path, parent=self)
            t0 = _time.time()
            if dlg.exec_() != QDialog.Accepted:
                self.status.setText("Importacion cancelada.")
                try: self.acoustic._cad_timer.fail("cancelado")
                except Exception: pass
                return
            timings["repair"] = _time.time() - t0
            final_mesh = dlg.result_mesh

        # --- Paso 4: centrar la malla sobre la grilla ---
        # El CAD viene en sus coordenadas originales (que pueden estar muy
        # lejos del origen si el archivo se exporto desde un BIM con
        # coordenadas globales). Lo trasladamos para que:
        #   - el centroide XY caiga en (0, 0)
        #   - el zmin (piso del recinto) quede sobre el plano de la grilla z=0
        # Asi la geometria aparece centrada en el visor y "apoyada" en la grilla.
        try:
            import numpy as _np
            verts = _np.asarray(final_mesh.vertices, dtype=float)
            cx = float(0.5 * (verts[:, 0].min() + verts[:, 0].max()))
            cy = float(0.5 * (verts[:, 1].min() + verts[:, 1].max()))
            zmin = float(verts[:, 2].min())
            offset = _np.array([cx, cy, zmin])
            if _np.linalg.norm(offset) > 1e-6:
                import trimesh as _tm
                centered_verts = verts - offset
                final_mesh = _tm.Trimesh(
                    vertices=centered_verts, faces=final_mesh.faces,
                    process=False,
                )
        except Exception:
            # Si el centrado falla, seguimos con la malla original
            pass

        # --- Paso 5: render + carga al panel acustico ---
        _set_progress("Renderizando geometria en el visor 3D...")
        t0 = _time.time()
        self.acoustic.set_imported_geometry(final_mesh)
        self.tabs.setCurrentIndex(1)
        self._render_imported_geometry(final_mesh)
        self._cad_cache = self._serialize_external_geometry()
        self._maybe_snapshot(force=True)
        # Ajustar el tamano de la grilla al AABB del CAD recien centrado
        try:
            verts = _np.asarray(final_mesh.vertices, dtype=float)
            if hasattr(self.viewer, 'fit_grid_to_aabb'):
                self.viewer.fit_grid_to_aabb(verts.min(axis=0), verts.max(axis=0))
        except Exception:
            pass
        timings["render"] = _time.time() - t0

        # Guardar path como reciente.
        try:
            app_settings.add_recent_file(path)
        except Exception:
            pass

        prog.close()

        # Resumen de tiempos en la barra de estado (uno se entera de donde
        # se va el tiempo de importacion, util para diagnosticar lentitud).
        t_total = sum(timings.values())
        phases = "  ·  ".join(
            f"{k} {v*1000:.0f} ms" for k, v in timings.items() if v > 0.005
        )
        self.status.setText(
            f"CAD importado: {Path(path).name}  ·  "
            f"{len(final_mesh.vertices)} verts, {len(final_mesh.faces)} tris  "
            f"·  total {t_total*1000:.0f} ms   ({phases})"
        )
        # Detener cronometro de la leyenda
        try:
            self.acoustic._cad_timer.stop(
                f"{len(final_mesh.vertices)} verts"
            )
        except Exception:
            pass

    def _clear_cad_import(self):
        """Slot: usuario pidio volver a geometria parametrica."""
        self.acoustic.clear_imported_geometry()
        # Re-renderizar la geom parametrica
        self._on_params(self.controls.get_params())
        self._cad_cache = None
        self._maybe_snapshot(force=True)
        self.status.setText("Volviendo a geometria parametrica.")

    def _render_imported_geometry(self, mesh):
        """Renderiza una malla trimesh en el viewer 3D, ajustando la grilla
        del piso al AABB del recinto. La malla SE ASUME ya centrada (el flujo
        de _open_cad_import / load_from_path la centra antes de llamar a esta
        funcion)."""
        import numpy as _np
        v = _np.asarray(mesh.vertices, dtype=_np.float32)
        t = _np.asarray(mesh.faces, dtype=_np.int32)
        # Aristas: 3 por triangulo (mismo formato que la geometria parametrica).
        e1 = t[:, [0, 1]]; e2 = t[:, [1, 2]]; e3 = t[:, [2, 0]]
        edges = _np.concatenate([e1, e2, e3], axis=0).astype(_np.int32)
        # n_walls no aplica a CAD; lo dejamos en 0 para deshabilitar el picking.
        self.viewer.update_geometry(v, t, edges, n_walls=0, arch_ribs=[])
        # Ajustar grilla del piso al AABB del CAD para que la geometria no
        # quede flotando en una grilla minuscula.
        if len(v) > 0 and hasattr(self.viewer, 'fit_grid_to_aabb'):
            try:
                self.viewer.fit_grid_to_aabb(
                    _np.asarray(v.min(axis=0), dtype=float),
                    _np.asarray(v.max(axis=0), dtype=float),
                )
            except Exception:
                pass
        # Refrescar sources y receptor en el visor para que sigan visibles.
        if hasattr(self, "acoustic") and self.acoustic is not None:
            self.acoustic._refresh_sources_list()
            self.acoustic._refresh_receiver_marker()

    def _reanchor_cad(self, origin_mode: str):
        """Re-ancla la malla CAD importada segun la convencion de origen y
        traslada fuentes/receptor con ella. Para CAD, "auto" == "center"
        (la convencion del import: centroide XY en (0,0), piso en z=0), asi
        volver a Auto desde Esquina restaura el centrado."""
        import numpy as _np
        from geometry import origin_offset
        ap = self.acoustic
        mesh = getattr(ap, "_imported_mesh", None)
        if mesh is None:
            return
        mode = (origin_mode or "auto").lower()
        if mode == "auto":
            mode = "center"
        verts = _np.asarray(mesh.vertices, dtype=float)
        off = origin_offset(verts, mode)
        if float(_np.linalg.norm(off)) < 1e-9:
            return                                  # ya esta en ese frame
        import trimesh as _tm
        new_mesh = _tm.Trimesh(vertices=verts - off, faces=mesh.faces,
                               process=False)
        # Orden critico: (1) trasladar fuentes/receptor con la malla vieja aun
        # instalada; (2) set_imported_geometry, que RECENTRA el receptor al
        # AABB (pensado para un import fresco, no para re-anclar); (3) restaurar
        # el receptor al destino trasladado. Los markers se refrescan al final.
        rcv_target = None
        if not getattr(self, "_restoring", False):
            self._shift_scene_objects(-off)
            rcv_target = tuple(float(x) for x in ap.receiver)
        ap.set_imported_geometry(new_mesh)
        if rcv_target is not None:
            ap.move_receiver_to(*rcv_target)
        ap.on_geometry_changed()      # invalida modos/caches (la malla cambio)
        self._render_imported_geometry(new_mesh)
        self._cad_cache = self._serialize_external_geometry()
        self.status.setText(
            f"Origen re-anclado ({mode}): recinto CAD, fuentes y receptor "
            f"trasladados juntos.")

    # ---------- Acceso a geometria para el panel acustico ----------
    def _get_current_surface(self):
        if self._surface_verts is None:
            v, t, _e, _n = build_room_geometry(self.controls.get_params())
            self._surface_verts, self._surface_tris = v, t
        return self._surface_verts, self._surface_tris

    def _get_dims_hint(self):
        p = getattr(self, "_last_params", None) or self.controls.get_params()
        return (float(p.get("width", 6.0)),
                float(p.get("length", 8.0)),
                float(p.get("height", 3.0)))

    # ---------- Undo / Redo (snapshot global) ----------
    def _capture_state(self) -> dict:
        """Snapshot del estado completo (mismo shape que el .room). Reusa la
        serializacion de guardado; el CAD sale del cache para no re-serializar
        la malla en cada poll."""
        data = {
            "format": FILE_FORMAT,
            "version": FILE_VERSION,
            "params": self.controls.get_params(),
            "acoustic": self._serialize_acoustic_state(),
        }
        if self._cad_cache is not None:
            data["external_geometry"] = self._cad_cache
        return data

    def _note_activity(self):
        """Marca actividad de un gesto en vivo (drag/rotate/tilt). El polling
        espera a que se asiente antes de snapshotear -> un drag = 1 accion."""
        if not self._restoring:
            self._last_change_t = _time.monotonic()

    def _maybe_snapshot(self, force: bool = False):
        """Apila un snapshot si el estado cambio. force=True salta el check de
        'settle' (eventos discretos: commit, alta de fuente, aplicar, etc.)."""
        if self._restoring or self._last_state is None:
            return
        if (not force) and self._last_change_t:
            if (_time.monotonic() - self._last_change_t) < 0.4:
                return                      # gesto todavia activo: esperar
        new = self._capture_state()
        if new == self._last_state:
            return                          # nada cambio
        self._undo.append(self._last_state)
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self._last_state = new
        self._last_change_t = 0.0           # consumido: no demorar el proximo

    def _on_commit(self, params: dict):
        # Commit de geometria (release de slider/drag de pared): snapshot ya.
        self._maybe_snapshot(force=True)

    def undo(self):
        if not self._undo:
            self.status.setText("Nada para deshacer")
            return
        self._redo.append(self._last_state)
        prev = self._undo.pop()
        self._restore_state(prev)
        self._last_state = prev
        self.status.setText(f"Deshacer · {len(self._undo)} pasos disponibles")

    def redo(self):
        if not self._redo:
            self.status.setText("Nada para rehacer")
            return
        self._undo.append(self._last_state)
        nxt = self._redo.pop()
        self._restore_state(nxt)
        self._last_state = nxt
        self.status.setText(f"Rehacer · {len(self._redo)} pasos disponibles")

    def _restore_state(self, data: dict):
        """Restaura un snapshot completo. _restoring evita que los signals que
        se disparan al setear (parametersChanged/Committed, etc.) apilen
        snapshots nuevos."""
        self._restoring = True
        try:
            params = data.get("params")
            if isinstance(params, dict):
                self.controls.set_params(params)
            # CAD embebido: restaurar la malla del snapshot o limpiar si no hay.
            ext = data.get("external_geometry")
            if ext and isinstance(ext, dict) and ext.get("kind") == "embedded_mesh":
                try:
                    import numpy as _np
                    import trimesh as _tm
                    verts = _np.asarray(ext.get("vertices") or [], dtype=float)
                    faces = _np.asarray(ext.get("faces") or [], dtype=int)
                    if len(verts) and len(faces):
                        mesh = _tm.Trimesh(vertices=verts, faces=faces,
                                            process=False)
                        self.acoustic.set_imported_geometry(mesh)
                        self._render_imported_geometry(mesh)
                        self._cad_cache = ext
                except Exception:
                    pass
            else:
                if getattr(self.acoustic, "_is_imported_cad", False):
                    self.acoustic.clear_imported_geometry()
                    self._on_params(self.controls.get_params())
                self._cad_cache = None
            # Estado acustico: fuentes, receptor, materiales, motor.
            ac = data.get("acoustic") or {}
            if ac:
                self._restore_acoustic_state(ac)
        finally:
            self._restoring = False
            self._last_change_t = 0.0

    # ---------- Fuentes acusticas desde el viewer 3D ----------
    def _on_source_add_from_viewer(self, x: float, y: float, z: float):
        """Ctrl+Click derecho en el viewer: colocar fuente en (x,y,z)."""
        self.tabs.setCurrentIndex(1)      # cambiar a pestaña Acústica
        self.acoustic.add_source_at(x, y, z)
        self._maybe_snapshot(force=True)

    def _on_source_moved_from_viewer(self, idx: int, x: float, y: float, z: float):
        """Shift+drag en el viewer 3D: mover fuente acustica (actualiza en-lugar).
        Se traba en los limites del recinto (clamp al bbox)."""
        x, y, z = self.acoustic._clamp_to_room_bbox(x, y, z)
        # Colision-stop contra muebles: frena al contacto en vez de atravesarlos.
        # Si YA estaba en conflicto (p.ej. se agrego un mueble encima), se deja
        # mover para que pueda salir -- mismo criterio de escape que los muebles.
        srcs = self.acoustic.sources
        if 0 <= idx < len(srcs):
            was = self.acoustic.source_placement_conflict(
                idx, *srcs.sources[idx].position) is not None
            if (not was) and self.acoustic.source_placement_conflict(idx, x, y, z):
                return
        if 0 <= idx < len(srcs):
            # Mutar SOLO la posicion en-lugar: preserva orientacion/pitch/bafle/
            # respuesta/sensibilidad/mounted (antes reconstruia y los perdia).
            srcs.sources[idx].position = (float(x), float(y), float(z))
            # Actualizar marcador en-lugar (sin re-crear el GL item) para drag suave
            self.acoustic.src_markers.set_positions(srcs, selected_idx=idx)
            self.acoustic._sync_source_positions_to_viewer()
            self.viewer.update()
            # Agendar actualizacion del campo (debounce 350 ms)
            self.acoustic.schedule_field_update()
            self._note_activity()           # drag -> 1 sola accion al asentarse

    def _on_source_rotate_from_viewer(self, idx: int, d_az: float):
        """Alt+Ctrl+Left drag: gira el bafle (azimut) en vivo. Solo visual + T8;
        no toca posicion ni acustica."""
        srcs = self.acoustic.sources
        if not (0 <= idx < len(srcs)):
            return
        s = srcs[idx]
        base = s.orientation if getattr(s, "orientation", None) is not None else 90.0
        s.orientation = float((base + d_az) % 360.0)
        self.acoustic.src_markers.set_positions(srcs, selected_idx=idx)
        self.viewer.update()
        self._note_activity()

    def _on_source_tilt_from_viewer(self, idx: int, d_pitch: float):
        """Alt+Ctrl+rueda: inclina el bafle (pitch) en vivo. Solo visual + T8."""
        srcs = self.acoustic.sources
        if not (0 <= idx < len(srcs)):
            return
        s = srcs[idx]
        cur = float(getattr(s, "pitch", 0.0) or 0.0)
        s.pitch = float(max(-90.0, min(90.0, cur + d_pitch)))
        self.acoustic.src_markers.set_positions(srcs, selected_idx=idx)
        self.viewer.update()
        self._note_activity()

    def _on_receiver_moved_from_viewer(self, x: float, y: float, z: float):
        """Shift+drag sobre la cruz del receptor: moverlo a nueva posicion.
        Se traba en los limites del recinto (clamp al bbox)."""
        x, y, z = self.acoustic._clamp_to_room_bbox(x, y, z)
        # El receptor tampoco puede entrar en un mueble: ahi no hay malla y el
        # campo evalua NaN. Escape permitido si ya estaba adentro.
        ap = self.acoustic
        if ap.point_inside_furniture(x, y, z) >= 0 and \
                ap.point_inside_furniture(*ap.receiver) < 0:
            return
        ap.move_receiver_to(x, y, z)
        self._note_activity()

    def _on_furniture_moved_from_viewer(self, idx: int, x: float, y: float, z: float):
        """Shift+drag sobre un mueble: moverlo (colisión-stop en el panel)."""
        self.acoustic.apply_furniture_move(idx, x, y, z)
        self._note_activity()

    def _on_furniture_edit_from_viewer(self, idx: int):
        """Doble-click sobre un mueble: abrir su editor."""
        self.acoustic._edit_furniture_by_idx(idx)

    def _on_furniture_rotate_from_viewer(self, idx: int, d_yaw: float):
        """Alt+Ctrl+Left drag horizontal sobre un mueble: rotar yaw (solo cajas)."""
        self.acoustic.apply_furniture_rotate(idx, d_yaw)
        self._note_activity()

    def _on_furniture_tilt_from_viewer(self, idx: int, d_pitch: float):
        """Alt+Ctrl+Left drag vertical sobre un mueble: inclinar pitch (solo cajas)."""
        self.acoustic.apply_furniture_tilt(idx, d_pitch)
        self._note_activity()

    def _on_furniture_roll_from_viewer(self, idx: int, d_roll: float):
        """Anillo de roll del gizmo: vuelca el mueble de costado (solo cajas)."""
        self.acoustic.apply_furniture_roll(idx, d_roll)
        self._note_activity()

    def _on_source_edit_from_viewer(self, idx: int):
        """Doble-click sobre esfera: abrir dialogo de edicion."""
        self.tabs.setCurrentIndex(1)
        if 0 <= idx < len(self.acoustic.sources):
            from acoustic_panel import SourceEditDialog
            dlg = SourceEditDialog(
                self.acoustic.sources[idx],
                dims_hint=self._get_dims_hint(),
                parent=self,
                get_walls=self.acoustic._get_baffle_walls,
            )
            if dlg.exec_():
                self.acoustic.sources.sources[idx] = dlg.get_source()
                self.acoustic._refresh_sources_list()   # ya sincroniza al viewer
                self._maybe_snapshot(force=True)

    # ---------- Dialogo de forma ----------
    def _open_shape_dialog(self):
        dialog = ShapeDrawDialog(
            initial_polygon=self.controls.get_custom_polygon(),
            parent=self,
        )
        # Conectar Ctrl+Right-click del canvas 2D -> fuente acustica
        dialog.canvas.sourceAddedAtFloor.connect(
            lambda x, y: self._on_source_add_from_viewer(x, y, 1.0)
        )
        if dialog.exec_() == QDialog.Accepted:
            polygon = dialog.get_polygon()
            if polygon:
                self.controls.set_custom_polygon(polygon)
                # T7: si el wizard definió cortes laterales, aplicarlos.
                self.controls.set_wall_profiles(dialog.get_wall_profiles())

    # ---------- Atajos ----------
    def _setup_shortcuts(self):
        self._add_shortcut("Ctrl+Z", self.undo)
        self._add_shortcut("Ctrl+Shift+Z", self.redo)
        self._add_shortcut("Ctrl+Y", self.redo)
        self._add_shortcut("Ctrl+S", self.save_file)
        self._add_shortcut("Ctrl+Shift+S", self.save_file_as)
        self._add_shortcut("Ctrl+O", self.load_file)
        self._add_shortcut("0", self.viewer.reset_camera)
        self._add_shortcut("Ctrl+I", self._open_cad_import)
        # Fijar / liberar eje mundial para rotacion restringida (toggle).
        # Atajos: Ctrl+Shift+Alt + X / Y / Z.
        self._add_shortcut("Ctrl+Shift+Alt+X",
                            lambda: self._toggle_locked_axis("x"))
        self._add_shortcut("Ctrl+Shift+Alt+Y",
                            lambda: self._toggle_locked_axis("y"))
        self._add_shortcut("Ctrl+Shift+Alt+Z",
                            lambda: self._toggle_locked_axis("z"))
        # Enter -> calcular campo acustico
        self._add_shortcut("Return", self._acoustic_compute_enter)
        # Modo Rotar (mouse sin rueda / Magic Mouse): "1" alterna, Esc sale.
        self._add_shortcut("1", self._toggle_rotate_mode)
        self._add_shortcut("Escape", self._exit_rotate_mode)

    def _add_shortcut(self, seq: str, slot):
        sc = QShortcut(QKeySequence(seq), self)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(slot)

    def _toggle_rotate_mode(self):
        """Alterna el modo Rotar del visor. Guard: si se esta escribiendo en un
        campo (QLineEdit/spinbox), no robar el '1'."""
        from PyQt5.QtWidgets import QLineEdit, QAbstractSpinBox
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QAbstractSpinBox)):
            return
        self.viewer.toggle_rotate_mode()

    def _exit_rotate_mode(self):
        if getattr(self.viewer, "_rotate_mode", False):
            self.viewer.set_rotate_mode(False)

    def _acoustic_compute_enter(self):
        """Enter -> dispatch segun la pestaña activa:
        - Acústica: lanzar calculo modal.
        - Predicción: lanzar Predecir.
        """
        idx = self.tabs.currentIndex()
        if idx == 1:
            self.acoustic.trigger_compute()
        elif idx == 2 and hasattr(self, "prediction"):
            self.prediction.trigger_predict()

    # ---------- Aplicar sugerencia de la pestaña Predicción ----------
    def _on_prediction_apply_params(self, params: dict):
        """Aplicar como parametros: setea sliders + render + va a Geometria."""
        # Si habia CAD importado, limpiarlo para que los sliders vuelvan a
        # gobernar la geometria.
        if getattr(self.acoustic, "_is_imported_cad", False):
            self.acoustic.clear_imported_geometry()
            self._cad_cache = None
        self.controls.set_params(params)
        self.tabs.setCurrentIndex(0)
        self._maybe_snapshot(force=True)
        self.status.setText(
            f"Predicción aplicada como parámetros: "
            f"{params['width']:.2f} × {params['length']:.2f} × "
            f"{params['height']:.2f} m"
        )

    def _on_prediction_apply_sources(self, source_array):
        """Aplicar una prediccion de ubicacion (T8): coloca las fuentes
        recomendadas en la pestaña Acústica y va a ella."""
        ap = self.acoustic
        try:
            ap.sources.sources.clear()
            for s in source_array:
                ap.sources.add(s)
            ap._refresh_sources_list()      # actualiza markers + viewer
        except Exception as e:
            QMessageBox.critical(self, "Error al aplicar fuentes",
                                  f"No se pudieron colocar las fuentes:\n{e}")
            return
        self._maybe_snapshot(force=True)
        self.tabs.setCurrentIndex(1)        # Acústica
        self.status.setText(
            f"{len(source_array)} fuente(s) colocadas desde Predicción. "
            f"Presioná «Calcular modos» para simular."
        )

    def _on_prediction_apply_materials(self, names):
        """Aplica los materiales del preset de Predicción a las caras de Acústica
        (piso/paredes/techo) y va a la pestaña Acústica."""
        try:
            floor, walls, ceiling = names
        except Exception:
            return
        ok = self.acoustic.apply_zone_materials(floor, walls, ceiling)
        if ok:
            self.tabs.setCurrentIndex(1)
            self.status.setText(
                "Materiales del preset aplicados a Acústica (piso/paredes/techo).")
        else:
            self.status.setText(
                "No se pudieron aplicar los materiales (¿hay geometría con caras?).")

    def _on_prediction_apply_cad(self, verts, tris):
        """Aplicar como CAD: inyectar la malla como geometria externa."""
        try:
            import trimesh as _tm
            mesh = _tm.Trimesh(vertices=verts, faces=tris, process=False)
        except Exception as e:
            QMessageBox.critical(self, "Error al aplicar CAD",
                                  f"No se pudo construir la malla:\n{e}")
            return
        self.acoustic.set_imported_geometry(mesh)
        self._render_imported_geometry(mesh)
        self._cad_cache = self._serialize_external_geometry()
        self._maybe_snapshot(force=True)
        self.tabs.setCurrentIndex(1)
        self.status.setText(
            f"Predicción aplicada como CAD: "
            f"{len(verts)} verts, {len(tris)} tris"
        )

    def _toggle_locked_axis(self, axis: str):
        """Fija o libera el eje mundial para rotacion restringida.
        El propio IsoViewer maneja el toggle (apretar dos veces el mismo
        eje libera).
        """
        self.viewer.set_locked_axis(axis)
        active = self.viewer.get_locked_axis()
        if active is None:
            self.status.setText("Eje liberado: rotación libre.")
        else:
            self.status.setText(
                f"Eje {active.upper()} fijado. "
                "Rueda del mouse (presionada) gira alrededor de ese eje. "
                f"Volvé a apretar Ctrl+Shift+Alt+{active.upper()} para liberar."
            )

    # ---------- Guardar / Abrir ----------
    def save_file(self):
        if self._current_file is None:
            return self.save_file_as()
        self._save_to(self._current_file)

    def save_file_as(self):
        suggested = str(Path(DEFAULT_DIR) / "recinto.room")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar recinto", suggested, FILE_FILTER,
        )
        if not path:
            return
        if not path.lower().endswith((".room", ".json")):
            path += ".room"
        self._save_to(path)

    def _save_to(self, path: str):
        data = {
            "format": FILE_FORMAT,
            "version": FILE_VERSION,
            "params": self.controls.get_params(),
            "acoustic": self._serialize_acoustic_state(),
        }
        # Geometria CAD embebida (si la hay)
        ext = self._serialize_external_geometry()
        if ext is not None:
            data["external_geometry"] = ext

        try:
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            QMessageBox.critical(self, "Error al guardar", str(e))
            return
        self._current_file = path
        self._update_title()
        self.status.setText(f"Guardado: {Path(path).name}")

    def _serialize_acoustic_state(self) -> dict:
        """Empaqueta fuentes, receptor, override de motor para guardar."""
        ap = self.acoustic
        srcs = []
        for s in ap.sources:
            srcs.append({
                "label": s.label,
                "position": [float(s.position[0]),
                              float(s.position[1]),
                              float(s.position[2])],
                "Q_real": float(s.Q.real),
                "Q_imag": float(s.Q.imag),
                "sensitivity_dB": (float(s.sensitivity_dB)
                                    if getattr(s, "sensitivity_dB", None) is not None
                                    else None),
                # v5: curva de respuesta Q(f) por fuente (None si no tiene).
                "response": (s.response.to_dict()
                              if getattr(s, "response", None) is not None
                              else None),
                # v6: bafle (orientacion + dimensiones, T4) + inclinacion +
                # montaje en pared (campos nuevos; loader usa .get() -> compat).
                "orientation": (float(s.orientation)
                                if getattr(s, "orientation", None) is not None
                                else None),
                "baffle_size": [float(x) for x in getattr(
                    s, "baffle_size", (0.30, 0.50, 0.40))],
                "pitch": float(getattr(s, "pitch", 0.0) or 0.0),
                "mounted": bool(getattr(s, "mounted", False)),
                "active": bool(getattr(s, "active", True)),
                # v2.23: polaridad del cableado (+1 / -1). Aditivo, sin bump de
                # version: un .room viejo carga con +1 = comportamiento previo.
                "polarity": int(getattr(s, "polarity", 1) or 1),
                # v2.25: delay y offset de fase como campos (antes se horneaban en
                # la curva). Aditivo, sin bump: un .room viejo carga con 0.
                "delay_s": float(getattr(s, "delay_s", 0.0) or 0.0),
                "phase_deg": float(getattr(s, "phase_deg", 0.0) or 0.0),
            })
        # v4: asignacion de materiales por grupo de caras (estilo EASE).
        # Se guarda el mapeo {signature: material_name}. La firma es estable
        # frente a re-agrupaciones porque depende de normal+centroide+area
        # redondeados.
        face_mat = {}
        try:
            fm_map = getattr(ap, "_face_mat_map", None)
            if fm_map is not None:
                face_mat = {
                    "default": fm_map.default,
                    "assignments": fm_map.to_dict(),
                }
        except Exception:
            face_mat = {}
        return {
            "mesh_engine": ap.get_engine_override(),
            "h_target":    float(ap.sb_htarget.value()),
            "n_per_meter": float(ap.sb_density.value()),
            "n_modes":     int(ap.sb_nmodes.value()),
            "sources":     srcs,
            "receiver":    [float(x) for x in ap.receiver],
            # v2.16: puntos de escucha nombrados (Sweet Spot + mics) para
            # el Comparar. Lista vacia si no se usaron.
            "listen_points": [
                {"name": str(p.get("name", "")),
                 "position": [float(x) for x in p.get("position", (0, 0, 0))]}
                for p in getattr(ap, "listen_points", [])
            ],
            "face_materials": face_mat,
            # v7: mobiliario (obstaculos rigidos con absorcion por cara).
            "furniture": [m.to_dict() for m in getattr(ap, "furniture", [])],
            # Material por mueble (paralelo a "furniture"; null = rigido). Aditivo:
            # v7 sin la clave -> todos rigidos al cargar. Ver _furniture_mat_names.
            "furniture_materials": [
                (getattr(ap, "_furniture_mat_names", {}) or {}).get(i)
                for i in range(len(getattr(ap, "furniture", [])))
            ],
            # v8: parches de absorcion sub-cara (region + material dentro de una cara).
            "absorption_patches": [p.to_dict() for p in getattr(ap, "_patches", [])],
            # v2.23: modelo de amortiguamiento ("a36" | "perturbation"). Se guarda
            # el estado REAL. Default de sesion nueva = "perturbation" (Etapa 3),
            # pero un .room viejo SIN la clave carga como "a36" (reproducibilidad).
            "damping_model": getattr(ap, "_damping_model", "perturbation"),
        }

    def _serialize_external_geometry(self):
        """Si hay CAD importado, lo embebe en el .room (verts + tris)."""
        ap = self.acoustic
        if not getattr(ap, "_is_imported_cad", False):
            return None
        mesh = getattr(ap, "_imported_mesh", None)
        if mesh is None:
            return None
        import numpy as _np
        v = _np.asarray(mesh.vertices, dtype=float)
        t = _np.asarray(mesh.faces, dtype=int)
        return {
            "kind": "embedded_mesh",
            "format": "trimesh-json-v1",
            "vertices": v.round(6).tolist(),  # ronda a 1 micra
            "faces":    t.tolist(),
        }

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir recinto", DEFAULT_DIR, FILE_FILTER,
        )
        if path:
            self.load_from_path(path)

    def load_from_path(self, path: str) -> bool:
        """Carga un .room desde una ruta concreta (sin dialog).

        Devuelve True si se aplico correctamente.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Error al abrir", f"No se pudo leer:\n{e}")
            return False

        if data.get("format") != FILE_FORMAT:
            QMessageBox.warning(
                self, "Formato incompatible",
                "Este archivo no parece ser un recinto Prototipo 1.",
            )
            return False
        params = data.get("params")
        if not isinstance(params, dict):
            QMessageBox.warning(self, "Archivo invalido",
                                "Faltan los parametros del recinto.")
            return False
        try:
            self.controls.set_params(params)
        except (KeyError, ValueError, TypeError) as e:
            QMessageBox.critical(self, "Error al aplicar parametros", str(e))
            return False

        # v3: geometria externa embebida (CAD)
        ext = data.get("external_geometry") or None
        if ext and isinstance(ext, dict) and ext.get("kind") == "embedded_mesh":
            try:
                import numpy as _np
                import trimesh as _tm
                verts = _np.asarray(ext.get("vertices") or [], dtype=float)
                faces = _np.asarray(ext.get("faces") or [], dtype=int)
                if len(verts) > 0 and len(faces) > 0:
                    # Re-anclar segun el origin_mode GUARDADO (v2.16). El
                    # recentrado incondicional viejo ("compat v3") pisaba el
                    # frame elegido: un CAD guardado con origen en la esquina
                    # volvia centrado y las fuentes (guardadas en el frame
                    # esquina) quedaban fuera del recinto. Regla:
                    #   - "auto" (o .room viejo sin clave) -> centrado XY +
                    #     zmin->0, identico al comportamiento historico.
                    #   - "corner"/"center" -> anclar a ese frame; si la malla
                    #     ya se guardo asi, el offset es ~0 y no se toca nada.
                    from geometry import origin_offset
                    mode = "auto"
                    if isinstance(params, dict):
                        mode = (params.get("origin_mode") or "auto").lower()
                    mode_eff = "center" if mode == "auto" else mode
                    off_xy = origin_offset(verts, mode_eff)
                    off = _np.array([off_xy[0], off_xy[1],
                                     float(verts[:, 2].min())])
                    if float(_np.linalg.norm(off)) > 1e-9:
                        verts = verts - off
                    mesh = _tm.Trimesh(vertices=verts, faces=faces, process=False)
                    self.acoustic.set_imported_geometry(mesh)
                    self._render_imported_geometry(mesh)
            except Exception as e:
                QMessageBox.warning(self, "Geometria CAD",
                                      f"No se pudo cargar la geometria CAD embebida:\n{e}")

        # v3: estado acustico
        ac = data.get("acoustic") or {}
        if ac:
            try:
                self._restore_acoustic_state(ac)
            except Exception as e:
                QMessageBox.warning(self, "Estado acustico",
                                      f"No se pudo restaurar:\n{e}")

        # Empezamos limpios al abrir un archivo
        self._undo.clear()
        self._redo.clear()
        self._cad_cache = self._serialize_external_geometry()
        self._last_state = self._capture_state()
        self._last_change_t = 0.0
        self._current_file = path
        self._update_title()
        self.status.setText(f"Abierto: {Path(path).name}")
        return True

    def _restore_acoustic_state(self, ac: dict):
        """Restaura fuentes, receptor, override de motor desde un .room v3."""
        from sources import OmniSource
        ap = self.acoustic
        # Override de motor (combo del panel)
        engine = (ac.get("mesh_engine") or "auto").lower()
        ap.set_engine_override(engine)
        # Parametros numericos
        if "h_target" in ac:    ap.sb_htarget.setValue(float(ac["h_target"]))
        if "n_per_meter" in ac: ap.sb_density.setValue(float(ac["n_per_meter"]))
        if "n_modes" in ac:     ap.sb_nmodes.setValue(int(ac["n_modes"]))
        # Receptor
        r = ac.get("receiver") or []
        if len(r) == 3:
            ap.move_receiver_to(float(r[0]), float(r[1]), float(r[2]))
        # Puntos de escucha (v2.16; .room viejos no traen la clave)
        ap.listen_points = [
            {"name": str(p.get("name", f"Punto {i+1}")),
             "position": tuple(float(x) for x in p.get("position", (0, 0, 0)))}
            for i, p in enumerate(ac.get("listen_points") or [])
            if len(p.get("position", [])) == 3
        ]
        ap._refresh_listen_points()
        # Mobiliario (v7). v4/v5/v6 sin "furniture" -> lista vacia (compat).
        try:
            from furniture import Furniture
            ap.furniture = [Furniture.from_dict(m)
                            for m in (ac.get("furniture") or [])]
        except Exception:
            ap.furniture = []
        # Material por mueble (paralelo a furniture; sin la clave -> rigidos).
        try:
            fmats = ac.get("furniture_materials") or []
            ap._furniture_mat_names = {i: str(nm)
                                       for i, nm in enumerate(fmats) if nm}
        except Exception:
            ap._furniture_mat_names = {}
        # Fuentes
        ap.sources.sources.clear()
        for s in ac.get("sources") or []:
            pos = tuple(float(x) for x in s.get("position") or (0,0,0))
            Q = complex(float(s.get("Q_real", 1.0)), float(s.get("Q_imag", 0.0)))
            sens = s.get("sensitivity_dB")
            kwargs = {"position": pos, "Q": Q, "label": s.get("label", "src")}
            if sens is not None:
                kwargs["sensitivity_dB"] = float(sens)
            # v6: bafle (T4)
            ori = s.get("orientation")
            if ori is not None:
                kwargs["orientation"] = float(ori)
            bsz = s.get("baffle_size")
            if bsz and len(bsz) == 3:
                kwargs["baffle_size"] = tuple(float(x) for x in bsz)
            # pitch + mounted (campos nuevos; default si el .room es viejo).
            kwargs["pitch"] = float(s.get("pitch", 0.0) or 0.0)
            kwargs["mounted"] = bool(s.get("mounted", False))
            kwargs["active"] = bool(s.get("active", True))
            kwargs["polarity"] = int(s.get("polarity", 1) or 1)
            kwargs["delay_s"] = float(s.get("delay_s", 0.0) or 0.0)   # v2.25
            kwargs["phase_deg"] = float(s.get("phase_deg", 0.0) or 0.0)
            src = OmniSource(**kwargs)
            # v5: reconstruir la curva de respuesta Q(f) si el .room la trae.
            resp = s.get("response")
            if resp:
                from sources import SourceResponse
                try:
                    src.response = SourceResponse.from_dict(resp)
                except Exception as e:
                    self.status.setText(f"Aviso: respuesta de fuente ignorada ({e})")
            ap.sources.add(src)
        ap._refresh_sources_list()
        if hasattr(ap, "_refresh_furniture_list"):
            ap._refresh_furniture_list()
        # Si el receptor del archivo quedó fuera del recinto (p.ej. una forma
        # custom guardada con el receptor en el (0,0) por defecto), reubicarlo
        # al interior — el move_receiver_to de arriba pisó la reubicación que
        # hizo on_geometry_changed durante set_params.
        ap._relocate_receiver_if_outside()
        # v4: asignaciones de materiales por grupo
        fm_data = ac.get("face_materials") or {}
        if isinstance(fm_data, dict) and hasattr(ap, "_face_mat_map"):
            try:
                ap._face_mat_map.default = str(fm_data.get("default", "") or "")
                ap._face_mat_map.from_dict(fm_data.get("assignments") or {})
                if hasattr(ap, "_refresh_materials_summary"):
                    ap._refresh_materials_summary()
            except Exception:
                pass
        # v8: parches de absorcion sub-cara. v4-v7 sin la clave -> lista vacia.
        try:
            from absorption_patch import AbsorptionPatch
            ap._patches = [AbsorptionPatch.from_dict(d)
                           for d in (ac.get("absorption_patches") or [])]
            if hasattr(ap, "_refresh_patches_summary"):
                ap._refresh_patches_summary()
        except Exception:
            ap._patches = []

        # v2.23: modelo de amortiguamiento. Sin la clave (.room pre-v2.24) -> "a36"
        # a proposito: el archivo se guardo bajo Sabine, se preserva su numero.
        # El default de sesion nueva es "perturbation" (Etapa 3), pero eso NO pisa
        # un archivo viejo. Con la clave presente se respeta lo guardado.
        try:
            dm = str(ac.get("damping_model", "a36")).lower()
            ap._damping_model = "perturbation" if dm == "perturbation" else "a36"
            if hasattr(ap, "combo_damping"):
                idx = ap.combo_damping.findData(ap._damping_model)
                if idx >= 0:
                    ap.combo_damping.blockSignals(True)
                    ap.combo_damping.setCurrentIndex(idx)
                    ap.combo_damping.blockSignals(False)
        except Exception:
            ap._damping_model = "a36"

    def _update_title(self):
        base = "Prototipo 1 - Modelador de Recintos 3D"
        if self._current_file:
            self.setWindowTitle(f"{base}  —  {Path(self._current_file).name}")
        else:
            self.setWindowTitle(base)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    app.setApplicationName("Prototipo 1")

    # Watchdog de diagnostico (opcional): correr con PROTO1_WATCHDOG=1 para
    # que, si la GUI queda COLGADA >20 s, se impriman en la consola los stacks
    # de todos los threads (donde exactamente quedo trabada). Mientras el
    # event loop vive, un QTimer re-arma el deadline y no imprime nada.
    import os
    if os.environ.get("PROTO1_WATCHDOG"):
        import faulthandler
        faulthandler.enable()
        faulthandler.dump_traceback_later(20.0, repeat=True)
        _wd = QTimer()
        _wd.setInterval(5000)
        _wd.timeout.connect(
            lambda: faulthandler.dump_traceback_later(20.0, repeat=True))
        _wd.start()
        app._watchdog_timer = _wd    # mantener referencia viva
        print("[watchdog] activo: si la GUI se cuelga >20 s, "
              "el stack aparece aca.")

    win = MainWindow()
    win.show()

    # Si nos pasaron un .room por linea de comando (p.ej. doble click en
    # Windows con la asociacion de archivos), lo cargamos al arrancar.
    if len(sys.argv) > 1 and sys.argv[1]:
        path = sys.argv[1]
        if Path(path).is_file():
            win.load_from_path(path)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
