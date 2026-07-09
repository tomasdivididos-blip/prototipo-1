"""
pack_distribution.py
====================
Genera el ZIP final listo para enviarle al profesor / cualquier usuario.

Asume que `build.bat` corrio sin errores y que `verify_distribution.py`
paso. Comprime `dist/Prototipo1/` entera en un solo `.zip` con un
README minimal afuera.

Uso:
    python pack_distribution.py

Salida:
    Prototipo1_v2.12.zip  (en la raiz del proyecto)
"""

from __future__ import annotations
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist" / "Prototipo1"
OUT_ZIP = PROJECT_ROOT / "Prototipo1_v2.12.zip"


def main() -> int:
    if not DIST_DIR.is_dir():
        print(f"[FAIL] No existe {DIST_DIR}. Correr build.bat primero.")
        return 1

    # Borrar zip viejo si existe
    if OUT_ZIP.exists():
        print(f"[*] Borrando ZIP previo: {OUT_ZIP.name}")
        OUT_ZIP.unlink()

    print(f"[*] Comprimiendo {DIST_DIR.relative_to(PROJECT_ROOT)}/")
    print(f"    -> {OUT_ZIP.name}")
    n_files = 0
    total_bytes = 0
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED,
                          compresslevel=6) as zf:
        for p in DIST_DIR.rglob("*"):
            if p.is_file():
                # arcname: que dentro del ZIP la raiz sea "Prototipo1/"
                arcname = p.relative_to(DIST_DIR.parent)
                zf.write(p, arcname=arcname)
                n_files += 1
                total_bytes += p.stat().st_size

    zip_bytes = OUT_ZIP.stat().st_size
    compression = (1 - zip_bytes / total_bytes) * 100 if total_bytes else 0

    print()
    print("=" * 60)
    print(" ZIP listo para enviar")
    print("=" * 60)
    print(f"  Archivos comprimidos: {n_files}")
    print(f"  Tamano sin comprimir: {total_bytes / 1024**2:.1f} MB")
    print(f"  Tamano del ZIP:       {zip_bytes / 1024**2:.1f} MB "
          f"(ratio compresion: {compression:.0f}%)")
    print(f"  Ubicacion:            {OUT_ZIP}")
    print()
    print("  Lo que va adentro del ZIP, a la raiz:")
    print("    Prototipo1/Prototipo1.exe       (entry point)")
    print("    Prototipo1/MANUAL.pdf           (32 paginas)")
    print("    Prototipo1/ejemplo.room         (sala de muestra)")
    print("    Prototipo1/LEEME.txt            (instrucciones rapidas)")
    print("    Prototipo1/_internal/...        (deps + materiales JSON)")
    print()
    print("  El destinatario:")
    print("    1. Descomprime el ZIP en cualquier carpeta")
    print("    2. Doble click en Prototipo1/Prototipo1.exe")
    print("    3. Si Windows alerta -> 'Mas info' -> 'Ejecutar de todos modos'")
    return 0


if __name__ == "__main__":
    rc = main()
    print()
    try:
        input("Enter para salir...")
    except EOFError:
        pass
    sys.exit(rc)
