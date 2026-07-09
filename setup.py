"""
Setup script para Prototipo 1 - Modelador de Recintos 3D con Simulación
Acústica FEM.

Nota: la distribución oficial es vía PyInstaller (`build.bat` o
`build_installer.bat`). Este setup.py existe para soportar `pip install .`
en entornos de desarrollo.

Uso:
    pip install -e .          # instalación editable (desarrollo)
    pip install .             # instalación normal
"""

from setuptools import setup
from pathlib import Path

HERE = Path(__file__).parent

# Leer descripción larga desde README.md
readme = HERE / "README.md"
long_description = readme.read_text(encoding="utf-8") if readme.exists() else ""

# Leer dependencias desde requirements.txt para mantener una sola fuente de verdad
req_file = HERE / "requirements.txt"
install_requires = []
if req_file.exists():
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        install_requires.append(line)

# Lista completa de módulos de nivel raíz (proyecto con estructura plana,
# sin __init__.py). Mantener en sync si se agregan/quitan archivos .py.
PY_MODULES = [
    # Entry point + UI raíz
    "main", "style", "timed_button", "app_settings",
    # Pestaña Geometría
    "controls", "geometry", "shape_dialog", "viewer",
    # Pestaña Acústica
    "acoustic_panel", "acoustic_viewer", "audio_utils",
    # Pestaña Predicción
    "prediction", "prediction_panel",
    # Solvers
    "acoustic_analysis", "acoustic_fem", "acoustic_mesh",
    "sources",
    # Mallado y router
    "mesh_router", "mesh_gmsh",
    # Import CAD
    "geom_import", "geom_repair_dialog", "geom_scale_dialog",
    # Materiales
    "material_library", "face_materials",
    # Solvers shoebox (referencia analítica)
    "fem_modal",
    # Tools
    "benchmark_v2", "check_materials_coverage", "verify_setup",
]

setup(
    name="prototipo1",
    version="2.6.0",
    description="Modelador de recintos 3D con simulación acústica FEM "
                "(PyQt5 + OpenGL + gmsh + trimesh)",
    long_description=long_description,
    long_description_content_type="text/markdown",

    py_modules=PY_MODULES,

    install_requires=install_requires,
    python_requires=">=3.10",

    entry_points={
        "gui_scripts": [
            "prototipo1=main:main",
        ],
    },

    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Physics",
        "Topic :: Scientific/Engineering :: Visualization",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: Microsoft :: Windows",
    ],

    include_package_data=True,
    package_data={
        "": ["materials/*.json"],
    },

    keywords="acoustics fem room-modeling 3d-visualization pyqt5 opengl "
             "gmsh trimesh modal-analysis frf rt60",
)
