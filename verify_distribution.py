"""
verify_distribution.py
======================
Verifica que el output de `build.bat` contiene todo lo necesario para
correr en una PC sin Python ni el codigo fuente.

Uso:
    python verify_distribution.py

Chequea (en `dist/Prototipo1/`):
  - Existe el .exe
  - Existe _internal/ con los DLLs y modulos Python
  - Los 19 archivos JSON de materiales estan en _internal/materials/
  - MANUAL.pdf, ejemplo.room, LEEME.txt al lado del .exe
  - Tamano total razonable (~150-400 MB)

NO verifica que ARRANQUE el programa (eso requiere doble click manual).
Para test funcional completo:
  1. Mover dist/Prototipo1/ a otra ubicacion (ej. D:\test_profesor\)
  2. Renombrar la carpeta fuente
  3. Doble click en Prototipo1.exe
  4. Comprobar: abre, materiales (19), ejemplo.room carga, FEM corre.
"""

from __future__ import annotations
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist" / "Prototipo1"
INTERNAL_DIR = DIST_DIR / "_internal"

# Archivos esperados al lado del .exe (user-facing)
USER_FACING = [
    "Prototipo1.exe",
    "MANUAL.pdf",
    "ejemplo.room",
    "LEEME.txt",
]

# Carpetas/archivos esperados en _internal/
INTERNAL_EXPECTED = [
    "_internal/python3*.dll",     # Python runtime
    "_internal/base_library.zip",  # Modulos Python embebidos
    "_internal/materials",         # Carpeta de materiales bundleada
    "_internal/PyQt5",             # Qt5 bindings
]


def check(label: str, condition: bool, hint: str = "") -> bool:
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition and hint:
        print(f"         {hint}")
    return condition


def main() -> int:
    print("=" * 60)
    print(" Verificacion de distribucion (dist/Prototipo1/)")
    print("=" * 60)

    if not DIST_DIR.is_dir():
        print(f"\n[FAIL] No existe {DIST_DIR}")
        print("       Correr build.bat primero.")
        return 1

    all_ok = True

    # 1. Archivos user-facing en la raiz
    print("\n[*] Archivos user-facing al lado del .exe:")
    for name in USER_FACING:
        p = DIST_DIR / name
        all_ok &= check(
            f"{name}",
            p.exists(),
            hint=f"Falta {name}. build.bat deberia copiarlo "
                  "(seccion 'Post-build').",
        )

    # 2. _internal/ existe
    print("\n[*] _internal/ y dependencias:")
    all_ok &= check(
        "_internal/ existe",
        INTERNAL_DIR.is_dir(),
        hint="PyInstaller no genero la carpeta. Revisar log del build.",
    )

    # 3. Materiales bundleados
    materials_dir = INTERNAL_DIR / "materials"
    print(f"\n[*] Materiales JSON en {materials_dir.relative_to(PROJECT_ROOT)}:")
    if materials_dir.is_dir():
        json_files = list(materials_dir.glob("*.json"))
        n = len(json_files)
        ok = n >= 15  # esperamos 19, dejamos margen
        all_ok &= check(
            f"{n} archivos JSON bundleados (esperado: ~19)",
            ok,
            hint="Faltan materiales. Revisar que build.bat tenga "
                  "--add-data 'materials;materials'.",
        )
        if ok and n > 0:
            sample = sorted(p.name for p in json_files)[:5]
            print(f"         Muestra: {', '.join(sample)}…")
    else:
        all_ok &= check("carpeta materials/ existe", False,
                        hint="--add-data 'materials;materials' falto en build.bat")

    # 4. PyQt5 bundleado
    pyqt5_dir = INTERNAL_DIR / "PyQt5"
    print(f"\n[*] PyQt5 bindings:")
    all_ok &= check(
        f"_internal/PyQt5/ existe",
        pyqt5_dir.is_dir(),
        hint="PyInstaller no detecto PyQt5. La GUI no va a arrancar.",
    )

    # 5. Python DLL
    print(f"\n[*] Python runtime DLL:")
    py_dlls = list(INTERNAL_DIR.glob("python*.dll"))
    all_ok &= check(
        f"{len(py_dlls)} python*.dll encontrado(s)",
        len(py_dlls) >= 1,
        hint="Sin python.dll el .exe no arranca.",
    )

    # 6. Tamano total
    print(f"\n[*] Tamano total:")
    total_bytes = sum(p.stat().st_size for p in DIST_DIR.rglob("*") if p.is_file())
    total_mb = total_bytes / (1024 ** 2)
    # Rango realista medido en v2.21: ~1030 MB. El piso lo ponen los mkl_*.dll
    # (~370 MB, el BLAS de numpy/scipy; son variantes de despacho por CPU y
    # sacarlas rompe en maquinas con otro juego de instrucciones) mas
    # gmsh-4.15.dll (~86 MB) y PyQt5 (~81 MB). Si sube muy por encima, volvio a
    # colarse peso muerto (botocore / panel / bokeh / llvmlite / QtWebEngine):
    # comparar con `du -sm dist/Prototipo1/_internal/* | sort -rn | head`.
    in_range = 700 < total_mb < 1400
    all_ok &= check(
        f"dist/Prototipo1/ ocupa {total_mb:.0f} MB (rango esperado 700-1400 MB)",
        in_range,
        hint="Tamano fuera de rango. Si <700 MB faltan dependencias; si "
              ">1400 MB se colo peso muerto (revisar los excludes de build.bat).",
    )

    # 7. Resumen
    print("\n" + "=" * 60)
    if all_ok:
        print(" Distribucion lista para zipear y enviar.")
        print("")
        print(" Proximo paso (test funcional, recomendado):")
        print("   1. Mover dist/Prototipo1/ a, por ejemplo, D:\\test\\")
        print("   2. Renombrar (temporariamente) esta carpeta fuente")
        print("   3. Doble click en D:\\test\\Prototipo1\\Prototipo1.exe")
        print("   4. En la app: pestaña Acustica -> Materiales -> verificar")
        print("      que aparezcan los ~19 materiales (no solo 'default')")
        print("   5. Ctrl+O -> abrir ejemplo.room")
        print("   6. Calcular f_Schroeder + Calcular modos (FEM)")
        return 0
    else:
        print(" Distribucion INCOMPLETA - revisar errores marcados [FAIL].")
        return 1


if __name__ == "__main__":
    rc = main()
    print()
    try:
        input("Enter para salir...")
    except EOFError:
        pass
    sys.exit(rc)
