# Prototipo 1 — Modelador de Recintos 3D con Simulación Acústica FEM

App de escritorio para diseñar recintos acústicos, calcular sus modos por el
Método de Elementos Finitos (FEM), visualizar el campo y oír cómo suenan.

> **Manual completo de usuario**: [MANUAL.md](MANUAL.md) (v2.12, master).
> **Explicación técnica para ingenieros de sonido**: [EXPLICACION_TECNICA.md](EXPLICACION_TECNICA.md).
> **Benchmarks y rendimiento**: [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md).

---

## Inicio rápido

### Opción A — Código fuente (recomendado para desarrollo)

Requiere **Anaconda Python 3.12** en Windows 10/11. No usar el Python de
Microsoft Store.

1. Instalar [Anaconda](https://www.anaconda.com/download).
2. Desde Anaconda Prompt:
   ```
   pip install -r requirements.txt
   ```
3. Doble clic en **`run.bat`** (detecta Anaconda automáticamente).

### Opción B — Ejecutable portable (sin Python)

1. Doble clic en **`build.bat`** (una sola vez, 2–3 min).
2. Copiar `dist\Prototipo1\` al pendrive o a la otra PC.
3. Doble clic en `Prototipo1.exe`.

### Opción C — Instalador NSIS

1. Instalar [NSIS](https://nsis.sourceforge.io/) y PyInstaller.
2. Ejecutar `build_installer.bat` → genera `Prototipo1_Installer.exe`.

---

## Pestañas de la app

| Pestaña | Para qué |
|---|---|
| **Geometría** | Modelar paramétricamente (sliders) o dibujar polígono custom; techo plano/arco/dos aguas/inclinado |
| **Acústica** | Fuentes, receptor, materiales por cara (estilo EASE), FEM modal, campo 3D, cortes 2D, FRF, escucha con ruido rosa filtrado |
| **Predicción** | Flujo inverso: describe el uso (sala de conferencias, estudio, sala sinfónica…) y el motor propone 3 candidatos scoreados por 13 criterios |

Además: import CAD (`Ctrl+I`) con loaders STL/OBJ/PLY/glTF/STEP/IGES/BREP,
diálogo de escala y reparación guiada, badge de motor de mallado
(voxel/gmsh) con fallback best-effort.

---

## Estructura del código

| Capa | Archivos |
|---|---|
| Entry point + UI raíz | [main.py](main.py), [style.py](style.py), [timed_button.py](timed_button.py), [app_settings.py](app_settings.py) |
| Pestaña Geometría | [controls.py](controls.py), [geometry.py](geometry.py), [shape_dialog.py](shape_dialog.py), [viewer.py](viewer.py) |
| Pestaña Acústica | [acoustic_panel.py](acoustic_panel.py), [acoustic_viewer.py](acoustic_viewer.py), [audio_utils.py](audio_utils.py) |
| Pestaña Predicción | [prediction.py](prediction.py), [prediction_panel.py](prediction_panel.py) |
| Solver FEM | [acoustic_analysis.py](acoustic_analysis.py), [acoustic_fem.py](acoustic_fem.py), [acoustic_mesh.py](acoustic_mesh.py), [sources.py](sources.py) |
| Mallado y router | [mesh_router.py](mesh_router.py), [mesh_gmsh.py](mesh_gmsh.py) |
| Import CAD | [geom_import.py](geom_import.py), [geom_repair_dialog.py](geom_repair_dialog.py), [geom_scale_dialog.py](geom_scale_dialog.py) |
| Materiales | [material_library.py](material_library.py), [face_materials.py](face_materials.py), `materials/*.json` |
| Solver shoebox (referencia analítica) | [fem_modal.py](fem_modal.py) |
| Benchmarks | [benchmark_v2.py](benchmark_v2.py) |
| Empaquetado | `run.bat`, `build.bat`, `build_installer.bat`, [build_installer.py](build_installer.py), `installer.nsi`, [setup.py](setup.py), `Prototipo 1.spec` |

---

## Stack técnico

| Capa | Librería |
|---|---|
| GUI | PyQt5 |
| Visor 3D | pyqtgraph + PyOpenGL |
| Álgebra y mallado | NumPy, SciPy (eigsh, cKDTree, fftconvolve) |
| Geometría CAD | trimesh + gmsh (kernel OpenCASCADE) |
| Gráficos 2D | matplotlib |
| Audio | winsound (Win) / afplay (Mac) / aplay·paplay·ffplay (Linux) + scipy.io.wavfile |

Versión de Python: **3.12 (Anaconda)**. PyQt6 / PySide6 descartados
(incompatibilidad DLL MSVC con Anaconda en Windows).

---

## Atajos principales

| Atajo | Acción |
|---|---|
| `Ctrl+Z` / `Ctrl+Y` | Deshacer / Rehacer |
| `Ctrl+S` / `Ctrl+Shift+S` | Guardar / Guardar como |
| `Ctrl+O` | Abrir `.room` |
| `Ctrl+I` | Importar CAD |
| `0` | Reset vista isométrica |
| `Enter` (pestaña Acústica) | Actualizar campo 3D |
| `Ctrl + clic derecho` (visor) | Colocar fuente en el piso |
| `Shift + clic izquierdo + arrastrar` | Mover fuente o receptor |

Lista completa en [MANUAL.md](MANUAL.md) sección 12.

---

## Formato de archivo

`.room` v4 — JSON portable. Embebe la malla CAD si se importó una, así un
recinto se puede compartir por mail sin adjuntar el STEP/STL original.
Los `.room` v2/v3 antiguos siguen abriendo sin problema.

---

## Verificar instalación

```
python verify_setup.py
```

Reporta versión de Python, dependencias, OpenGL, y archivos del proyecto.

---

## Troubleshooting

Ver [INSTALACION.md](INSTALACION.md) y [MANUAL.md](MANUAL.md) sección 13.

---

## Licencia

MIT.

---

*Última actualización: re-sincronizado a v2.12 el 16 de junio de 2026.*
