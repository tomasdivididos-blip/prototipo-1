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

    def _on_rm_error(func, path, exc_info):
        # Un build anterior puede dejar archivos de solo-lectura o bloqueados por
        # OneDrive -> shutil.rmtree lanza PermissionError (WinError 5). Se limpia el
        # atributo de solo-lectura y se reintenta la operación.
        try:
            os.chmod(path, 0o777)
            func(path)
        except Exception as e:
            print(f"  (aviso) no se pudo borrar {path}: {e}")

    for folder in [DIST_DIR, BUILD_DIR, PROJECT_DIR / "build"]:
        if folder.exists():
            # onexc (Python 3.12+) reemplaza a onerror; se pasa el que exista.
            try:
                shutil.rmtree(folder, onexc=_on_rm_error)
            except TypeError:
                shutil.rmtree(folder, onerror=lambda f, p, e: _on_rm_error(f, p, e))
            print(f"  ✓ Eliminada carpeta: {folder.name}")
    
    # Paso 3: Generar ejecutable con PyInstaller
    print("\n[3/4] Compilando con PyInstaller...")

    # El PyQt5 de conda (y scipy/mkl) linkean contra DLLs renombradas con sufijo
    # `_conda` (Qt5Widgets_conda.dll, ...) y contra el runtime de Intel
    # (libmmd.dll, libifcoremd.dll) que viven en <prefix>\Library\bin. Si el build
    # NO corre dentro de `conda activate`, ese directorio NO está en el PATH y
    # PyInstaller NO puede resolver ni EMPAQUETAR esas DLLs -> el .exe congelado
    # falla al importar QtWidgets ("DLL load failed"). Se agrega al PATH para que el
    # análisis de dependencias las encuentre y las bundlee solas.
    for sub in (Path("Library") / "bin", Path("Library") / "mingw-w64" / "bin"):
        d = Path(sys.prefix) / sub
        if d.is_dir():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            print(f"  PATH += {d}")

    # PyInstaller se invoca como MÓDULO del intérprete actual (`python -m
    # PyInstaller`): el ejecutable `pyinstaller` suele NO estar en el PATH del
    # shell (sí el módulo), y así se compila con el mismo Python/entorno que se
    # está usando. sys.executable va entre comillas por si la ruta tiene espacios.
    parts = [
        f'"{sys.executable}" -m PyInstaller --noconfirm',
        '--name "Prototipo 1"',
        '--onefile',
        '--windowed',
    ]
    # Ícono y datos OPCIONALES: solo se agregan si el archivo existe (si faltan,
    # PyInstaller abortaría con FileNotFoundError). Restaurá icon.ico / recinto.room
    # en la raíz del proyecto y se incluyen solos.
    icon_file = PROJECT_DIR / "icon.ico"
    if icon_file.exists():
        parts.append(f'--icon="{icon_file}"')
    else:
        print("  (aviso) icon.ico no está: se compila con el ícono por defecto.")
    room_file = PROJECT_DIR / "recinto.room"
    if room_file.exists():
        parts.append(f'--add-data "{room_file};."')
    else:
        print("  (aviso) recinto.room no está: no se empaqueta la sala de ejemplo.")
    # PyInstaller NO soporta dos bindings de Qt en el mismo ejecutable; si el
    # entorno tiene PyQt6/PySide además de PyQt5 (el que usa la app), hay que
    # excluir los otros o aborta la compilación.
    parts += [
        '--exclude-module PyQt6',
        '--exclude-module PySide6',
        '--exclude-module PySide2',
        '--hidden-import=OpenGL',
        '--hidden-import=numpy',
        '--hidden-import=scipy',
        '--hidden-import=scipy.sparse.linalg',
        '--hidden-import=pyqtgraph',
        '--hidden-import=matplotlib',
        '--hidden-import=matplotlib.backends.backend_qt5agg',
        '--hidden-import=gmsh',
        '--hidden-import=trimesh',
        '--collect-all gmsh',
        '--collect-all trimesh',
        f'"{PROJECT_DIR}/main.py"',
    ]
    pyinstaller_cmd = " ".join(parts)

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
