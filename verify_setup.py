"""
Script de verificación de dependencias y archivos para Prototipo 1.
Uso:  python verify_setup.py

Chequea:
  - Versión de Python (3.10+)
  - Sistema operativo (recomendado Windows)
  - Dependencias Python (las listadas en requirements.txt)
  - Soporte OpenGL
  - Archivos críticos del proyecto
  - Espacio en disco
"""

import sys
import platform
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependencias requeridas: (nombre_visible, nombre_import)
# ---------------------------------------------------------------------------
REQUIRED_DEPS = [
    ("PyQt5",       "PyQt5"),
    ("pyqtgraph",   "pyqtgraph"),
    ("PyOpenGL",    "OpenGL"),
    ("NumPy",       "numpy"),
    ("SciPy",       "scipy"),
    ("matplotlib",  "matplotlib"),
    ("gmsh",        "gmsh"),
    ("trimesh",     "trimesh"),
]

# ---------------------------------------------------------------------------
# Archivos críticos: el proyecto no arranca si falta alguno
# ---------------------------------------------------------------------------
CRITICAL_FILES = [
    # Entry point + UI raíz
    "main.py", "style.py", "app_settings.py", "timed_button.py",
    # Pestaña Geometría
    "controls.py", "geometry.py", "shape_dialog.py", "viewer.py",
    # Pestaña Acústica
    "acoustic_panel.py", "acoustic_viewer.py", "audio_utils.py",
    # Pestaña Predicción
    "prediction.py", "prediction_panel.py",
    # Solvers
    "acoustic_analysis.py", "acoustic_fem.py", "acoustic_mesh.py",
    "sources.py",
    # Mallado y router
    "mesh_router.py", "mesh_gmsh.py",
    # Import CAD
    "geom_import.py", "geom_repair_dialog.py", "geom_scale_dialog.py",
    # Materiales
    "material_library.py", "face_materials.py",
    # Config
    "requirements.txt", "run.bat",
]

CRITICAL_DIRS = [
    "materials",
]


def check_python_version():
    """Verifica versión de Python."""
    v = sys.version_info
    print(f"\n[*] Versión de Python: {v.major}.{v.minor}.{v.micro}")
    if v.major == 3 and v.minor >= 10:
        print("    OK — versión compatible (>= 3.10)")
        return True
    elif v.major == 3 and v.minor >= 8:
        print("    WARN — Python 3.10+ recomendado; 3.8/3.9 podría funcionar con warnings")
        return True
    else:
        print("    FAIL — Se requiere Python 3.10 o superior")
        print("    Instalar Anaconda desde: https://www.anaconda.com/download")
        return False


def check_os():
    """Verifica el sistema operativo."""
    name = platform.system()
    print(f"\n[*] Sistema operativo: {name} ({platform.release()})")
    if name == "Windows":
        print("    OK — Windows detectado")
        return True
    else:
        print("    WARN — Optimizado para Windows; el audio (winsound) "
              "no funciona en Linux/macOS")
        return True


def check_package(display_name, import_name):
    """Verifica si un paquete está instalado y reporta su versión."""
    try:
        mod = __import__(import_name)
        ver = getattr(mod, "__version__", "?")
        print(f"    OK  {display_name:<14} {ver}")
        return True
    except ImportError:
        print(f"    --  {display_name:<14} NO instalado")
        return False


def check_dependencies():
    """Verifica todas las dependencias listadas en REQUIRED_DEPS."""
    print("\n[*] Dependencias Python:")
    missing = []
    for display, import_name in REQUIRED_DEPS:
        if not check_package(display, import_name):
            missing.append(display)
    if missing:
        print(f"\n    FAIL — Faltan: {', '.join(missing)}")
        print("    Instalar con:  pip install -r requirements.txt")
        return False
    print("\n    OK — Todas las dependencias instaladas")
    return True


def check_gpu_support():
    """Verifica soporte OpenGL básico."""
    print("\n[*] Soporte gráfico (OpenGL):")
    try:
        from OpenGL import GL  # noqa
        print("    OK — PyOpenGL importable")
        # No instanciamos contexto (requiere ventana Qt); con que importe
        # alcanza para el chequeo de smoke.
        return True
    except Exception as e:
        print(f"    FAIL — {e}")
        print("    Actualizar drivers de GPU; reinstalar: "
              "pip install --upgrade PyOpenGL")
        return False


def check_files():
    """Verifica archivos y carpetas críticos del proyecto."""
    print("\n[*] Archivos del proyecto:")
    project_dir = Path(__file__).parent
    missing = []
    for filename in CRITICAL_FILES:
        if (project_dir / filename).exists():
            pass  # silencio para no inundar; solo reportamos faltantes
        else:
            print(f"    --  FALTA: {filename}")
            missing.append(filename)
    for dirname in CRITICAL_DIRS:
        d = project_dir / dirname
        if d.is_dir():
            n_json = len(list(d.glob("*.json")))
            print(f"    OK  {dirname}/  ({n_json} archivos .json)")
        else:
            print(f"    --  FALTA carpeta: {dirname}/")
            missing.append(dirname + "/")
    if missing:
        print(f"\n    FAIL — Faltan {len(missing)} elemento(s)")
        return False
    print(f"    OK — {len(CRITICAL_FILES)} archivos críticos presentes")
    return True


def check_audio():
    """Verifica backend de audio (Windows: winsound)."""
    print("\n[*] Backend de audio:")
    if sys.platform.startswith("win"):
        try:
            import winsound  # noqa
            print("    OK — winsound (built-in Windows)")
            return True
        except ImportError:
            print("    FAIL — winsound no disponible (raro en Windows)")
            return False
    else:
        print("    WARN — winsound es Windows-only; la escucha FRF no funcionará")
        return True


def check_disk_space():
    """Verifica espacio en disco."""
    print("\n[*] Espacio en disco:")
    try:
        import shutil
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024 ** 3)
        print(f"    Libre: {free_gb:.2f} GB")
        if free_gb >= 0.5:
            print("    OK — Espacio suficiente (>= 500 MB)")
            return True
        else:
            print("    WARN — Espacio limitado (recomendado >= 500 MB)")
            return True
    except Exception as e:
        print(f"    WARN — No se pudo verificar: {e}")
        return True


def main():
    print("=" * 60)
    print(" Verificación de setup - Prototipo 1 v2.6")
    print("=" * 60)

    results = {
        "Python version": check_python_version(),
        "OS":             check_os(),
        "Dependencies":   check_dependencies(),
        "GPU/OpenGL":     check_gpu_support(),
        "Project files":  check_files(),
        "Audio":          check_audio(),
        "Disk space":     check_disk_space(),
    }

    print("\n" + "=" * 60)
    print(" Resumen")
    print("=" * 60)
    for k, ok in results.items():
        print(f" [{'OK' if ok else '--'}] {k}")

    # Bloqueantes para arrancar la app
    critical_ok = all([
        results["Python version"],
        results["Dependencies"],
        results["Project files"],
    ])

    print("=" * 60)
    if critical_ok:
        print(" Sistema listo para ejecutar Prototipo 1.")
        print()
        print(" Para arrancar:  run.bat   (o:  python main.py)")
        print(" Para empaquetar: build.bat")
        return 0
    else:
        print(" Sistema NO listo - revisar errores marcados con '--'.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    print()
    try:
        input("Presioná ENTER para salir...")
    except EOFError:
        pass
    sys.exit(exit_code)
