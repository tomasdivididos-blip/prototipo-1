"""
pack_mac_distribution.py
========================
Genera `Prototipo1_Mac.zip`: el paquete "correr desde codigo fuente" para
macOS. NO es un .app de doble clic (PyInstaller no compila cruzado desde
Windows); el destinatario corre la app con `bash run.command` en Terminal,
que crea `.venv_mac` e instala las dependencias la primera vez.

Por que este script y no `pack_distribution.py`: ese comprime `dist/Prototipo1/`
(el .exe de Windows). Este junta el CODIGO FUENTE + materiales + launcher.

Que mete adentro (raiz del zip = `Prototipo1_Mac/`):
  - Los modulos .py de runtime, calculados por CIERRE DE IMPORTS desde main.py
    (asi nunca falta uno ni se cuela un bench/test). + verify_setup.py opcional.
  - materials/*.json (base de materiales)
  - run.command       (launcher bash; se escribe con permiso 0755 y saltos LF)
  - LEEME_MAC.txt     (instrucciones)
  - requirements.txt, ejemplo.room
  - MANUAL.pdf y MANUAL.md (el .pdf esta congelado en v2.22; el .md es la
    fuente de verdad actual)

Gotchas respetados (memoria mac-distribution):
  - Se arma con zipfile de Python -> separadores '/' (Compress-Archive de
    PowerShell escribe '\' y rompe en macOS).
  - run.command se guarda con saltos LF y bit ejecutable (external_attr).

Uso:
    python pack_mac_distribution.py
Salida:
    Prototipo1_Mac.zip  (en la raiz del proyecto)
"""

from __future__ import annotations
import ast
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
ARCROOT = "Prototipo1_Mac"  # carpeta raiz dentro del zip
OUT_ZIP = PROJECT_ROOT / "Prototipo1_Mac.zip"

# Archivos sueltos (no-modulos) que van si existen.
EXTRA_FILES = [
    "run.command",
    "LEEME_MAC.txt",
    "requirements.txt",
    "ejemplo.room",
    "MANUAL.pdf",
    "MANUAL.md",
]
# Modulos utiles que NO estan en el cierre de imports pero conviene incluir.
EXTRA_MODULES = ["verify_setup.py"]


def runtime_modules(entry: str = "main") -> set[str]:
    """Cierre de imports LOCALES desde `entry` (sin benches/tests/dev)."""
    local = {p.stem for p in PROJECT_ROOT.glob("*.py")}

    def imports_of(mod: str) -> set[str]:
        f = PROJECT_ROOT / f"{mod}.py"
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            return set()
        out: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    out.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                out.add(n.module.split(".")[0])
        return {m for m in out if m in local}

    seen: set[str] = set()
    stack = [entry]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(d for d in imports_of(m) if d not in seen)
    return seen


def main() -> int:
    mods = runtime_modules("main")
    for extra in EXTRA_MODULES:
        if (PROJECT_ROOT / extra).exists():
            mods.add(extra[:-3])

    py_files = sorted(f"{m}.py" for m in mods)

    # Chequeo de disponibilidad de los sueltos.
    missing_extra = [f for f in EXTRA_FILES if not (PROJECT_ROOT / f).exists()]
    if "run.command" in missing_extra or "LEEME_MAC.txt" in missing_extra:
        print("[FAIL] Falta run.command o LEEME_MAC.txt en la raiz del proyecto.")
        print("       Deberian estar versionados; extraelos del zip viejo si no.")
        return 1

    materials = sorted((PROJECT_ROOT / "materials").glob("*.json"))
    if not materials:
        print("[FAIL] No hay materials/*.json.")
        return 1

    if OUT_ZIP.exists():
        print(f"[*] Borrando zip previo: {OUT_ZIP.name}")
        OUT_ZIP.unlink()

    n = 0
    total = 0
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Modulos .py
        for name in py_files:
            src = PROJECT_ROOT / name
            zf.write(src, arcname=f"{ARCROOT}/{name}")
            n += 1
            total += src.stat().st_size
        # materials/
        for m in materials:
            zf.write(m, arcname=f"{ARCROOT}/materials/{m.name}")
            n += 1
            total += m.stat().st_size
        # Sueltos
        for name in EXTRA_FILES:
            src = PROJECT_ROOT / name
            if not src.exists():
                print(f"[warn] no existe (se omite): {name}")
                continue
            data = src.read_bytes()
            if name in ("run.command", "LEEME_MAC.txt", "requirements.txt"):
                data = data.replace(b"\r\n", b"\n")  # LF para macOS
            info = zipfile.ZipInfo(f"{ARCROOT}/{name}")
            info.compress_type = zipfile.ZIP_DEFLATED
            # run.command ejecutable (rwxr-xr-x); resto rw-r--r--
            perm = 0o755 if name == "run.command" else 0o644
            info.external_attr = perm << 16
            zf.writestr(info, data)
            n += 1
            total += len(data)

    zip_bytes = OUT_ZIP.stat().st_size
    comp = (1 - zip_bytes / total) * 100 if total else 0

    print("=" * 60)
    print(" Prototipo1_Mac.zip listo")
    print("=" * 60)
    print(f"  Modulos runtime (cierre desde main.py): {len(py_files)}")
    print(f"  Materiales JSON:                        {len(materials)}")
    print(f"  Archivos totales:                       {n}")
    print(f"  Sin comprimir:                          {total / 1024**2:.2f} MB")
    print(f"  ZIP:                                    {zip_bytes / 1024**2:.2f} MB "
          f"(compresion {comp:.0f}%)")
    print(f"  Ubicacion:                              {OUT_ZIP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
