"""
Script para generar el instalador .exe de Prototipo 1 usando PyInstaller y NSIS
Ejecuta: python build_installer.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def run_command(cmd, description):
    """Ejecuta un comando y maneja errores."""
    print(f"\n{'='*60}")
    print(f"📦 {description}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(cmd, shell=True, check=True)
        print(f"✓ {description} - OK")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Error en {description}: {e}")
        return False

def main():
    # Directorio base del proyecto
    PROJECT_DIR = Path(__file__).parent
    DIST_DIR = PROJECT_DIR / "dist"
    BUILD_DIR = PROJECT_DIR / "build"
    
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║   Generador de Instalador - Prototipo 1 (Modelador 3D)   ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    # Paso 1: Verificar dependencias
    print("\n[1/4] Verificando dependencias...")
    try:
        import PyInstaller
        import PyQt5
        import pyqtgraph
        import OpenGL
        import numpy
        import scipy
        import matplotlib
        import gmsh
        import trimesh
        print("✓ Todas las dependencias están instaladas")
    except ImportError as e:
        print(f"✗ Falta instalar: {e}")
        print("\nInstala con: pip install -r requirements.txt")
        return False
    
    # Paso 2: Limpiar compilaciones previas
    print("\n[2/4] Limpiando compilaciones previas...")
    for folder in [DIST_DIR, BUILD_DIR, PROJECT_DIR / "build"]:
        if folder.exists():
            shutil.rmtree(folder)
            print(f"  ✓ Eliminada carpeta: {folder.name}")
    
    # Paso 3: Generar ejecutable con PyInstaller
    print("\n[3/4] Compilando con PyInstaller...")
    
    pyinstaller_cmd = (
        f'pyinstaller '
        f'--name "Prototipo 1" '
        f'--onefile '
        f'--windowed '
        f'--icon=icon.ico '
        f'--add-data "recinto.room;." '
        f'--hidden-import=OpenGL '
        f'--hidden-import=numpy '
        f'--hidden-import=scipy '
        f'--hidden-import=scipy.sparse.linalg '
        f'--hidden-import=pyqtgraph '
        f'--hidden-import=matplotlib '
        f'--hidden-import=matplotlib.backends.backend_qt5agg '
        f'--hidden-import=gmsh '
        f'--hidden-import=trimesh '
        f'--collect-all gmsh '
        f'--collect-all trimesh '
        f'"{PROJECT_DIR}/main.py"'
    )
    
    if not run_command(pyinstaller_cmd, "Compilación con PyInstaller"):
        return False
    
    # Paso 4: Crear instalador NSIS (si está disponible)
    print("\n[4/4] Creando instalador NSIS...")
    
    installer_script = PROJECT_DIR / "installer.nsi"
    if installer_script.exists():
        nsis_cmd = f'makensis "{installer_script}"'
        if run_command(nsis_cmd, "Generación del instalador NSIS"):
            print("\n" + "="*60)
            print("✓ ¡Instalador generado exitosamente!")
            print("="*60)
            print(f"\n📍 Ubicación: {PROJECT_DIR / 'Prototipo1_Installer.exe'}")
        else:
            print("\n⚠️  PyInstaller funcionó pero NSIS no está disponible.")
            print(f"   El ejecutable está en: {DIST_DIR / 'Prototipo 1.exe'}")
    else:
        print("\n⚠️  archivo installer.nsi no encontrado.")
        print(f"   El ejecutable está en: {DIST_DIR / 'Prototipo 1.exe'}")
    
    print("\n" + "="*60)
    print("✓ Proceso completado")
    print("="*60)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
