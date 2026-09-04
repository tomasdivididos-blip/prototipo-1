# -*- coding: utf-8 -*-
"""render_manual_pdf.py -- renderiza MANUAL.md -> MANUAL.pdf (pandoc + xelatex).

Workflow del usuario: el master es MANUAL.md (se actualiza en cada recap). El PDF
se renderiza SOLO cuando la diferencia acumulada es notable (exportar tarda). Este
script hace ese render de un comando.

Que hace:
  1. Lee MANUAL.md (NO lo modifica).
  2. SACA TODOS LOS EMOJI (pedido del usuario: "sin emojis de ningun tipo") en una
     COPIA temporal. En lineas de tablas ASCII (con │) el emoji se reemplaza por un
     espacio para no romper la alineacion monoespaciada; en el resto se borra junto
     con un espacio contiguo. Se conservan los simbolos tecnicos/geometricos que SI
     son texto (α, ξₙ, →, ○, ●, ✓, ✕, ▾, ⟨⟩ ...) y las ecuaciones $$...$$.
  3. Fuentes de cobertura amplia (DejaVu de matplotlib) via header fontspec.
  4. pandoc --pdf-engine=xelatex -> MANUAL.pdf en la raiz + copia a dist/Prototipo1/.

Requisitos (maquina del usuario, ver notas §6): pandoc (anaconda Library\\bin),
MiKTeX (xelatex), matplotlib (trae las fuentes DejaVu).

Uso:  /c/Users/aceve/anaconda3/python.exe render_manual_pdf.py
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "MANUAL.md"
OUT = ROOT / "MANUAL.pdf"
DIST_OUT = ROOT / "dist" / "Prototipo1" / "MANUAL.pdf"

# --- rangos de EMOJI a eliminar (pictogramas / simbolos de color) -----------
# Se ELIMINAN: pictogramas y simbolos de color (🟢🔊💾📂🎨🟡 ⛒ ⏹ ⬒ ✅ ❌ ...).
# NO se tocan: dingbats de marca de texto (✓ U+2713, ✗ U+2717, ✕ U+2715) ni las
# formas geometricas (○ ● ■ ▾ U+25xx) ni la matematica, que son UI/notacion real
# y rinden bien en DejaVu.
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictogramas, emoticons, transporte, simbolos suplementarios, cuadrados/circulos de color
    "\U00002600-\U000026FF"   # misc symbols (⛒ ⚠ ☰ ...)
    "\U00002700-\U00002705"   # dingbats iniciales + ✅ (deja ✓✗✕ intactos, que son >U+2705)
    "\U0000274C\U0000274C"    # ❌
    "\U00002B00-\U00002BFF"   # ⬒ (2B12), estrellas, flechas gordas
    "\U000023E9-\U000023FA"   # ⏹ (23F9) y controles de reproduccion
    "\U0000FE0F\U0000200D"    # variation selector + ZWJ
    "\U0001F3FB-\U0001F3FF"   # skin tones (por si acaso; ya en el rango de arriba)
    "]"
)


def strip_emoji(text: str) -> str:
    out_lines = []
    for line in text.split("\n"):
        if "│" in line or "|" in line and line.count("|") >= 3:
            # tabla (ASCII box o pipe-table): emoji -> espacio (preserva ancho/columnas)
            out_lines.append(_EMOJI.sub(" ", line))
        else:
            # prosa: emoji + un espacio contiguo -> nada ("🔊 Escuchar" -> "Escuchar")
            line = re.sub(_EMOJI.pattern + r"\s?", "", line)
            out_lines.append(line)
    return "\n".join(out_lines)


FONT_HEADER = r"""\usepackage{fontspec}
\setmainfont{DejaVuSans.ttf}[
  Path=%(ttf)s/,
  BoldFont=DejaVuSans-Bold.ttf,
  ItalicFont=DejaVuSans-Oblique.ttf,
  BoldItalicFont=DejaVuSans-BoldOblique.ttf]
\setmonofont{DejaVuSansMono.ttf}[
  Path=%(ttf)s/,
  BoldFont=DejaVuSansMono-Bold.ttf,
  ItalicFont=DejaVuSansMono-Oblique.ttf,
  BoldItalicFont=DejaVuSansMono-BoldOblique.ttf,
  Scale=MatchLowercase]
"""


def matplotlib_ttf_dir() -> str:
    import matplotlib
    d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    if not (d / "DejaVuSans.ttf").exists():
        raise SystemExit(f"[ERROR] No encuentro DejaVuSans.ttf en {d}")
    return d.as_posix()


def build_env() -> dict:
    env = dict(os.environ)
    miktex = r"C:\Users\aceve\AppData\Local\Programs\MiKTeX\miktex\bin\x64"
    conda_lib = str(Path(sys.executable).parent / "Library" / "bin")
    env["PATH"] = miktex + os.pathsep + conda_lib + os.pathsep + env.get("PATH", "")
    return env


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"[ERROR] No existe {SRC}")
    md = SRC.read_text(encoding="utf-8")
    md_clean = strip_emoji(md)
    n_removed = sum(len(_EMOJI.findall(l)) for l in md.split("\n"))
    print(f"[*] MANUAL.md: {len(md.splitlines())} lineas; emoji eliminados: {n_removed}")

    ttf = matplotlib_ttf_dir()
    env = build_env()

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        md_path = tdp / "MANUAL_render.md"
        md_path.write_text(md_clean, encoding="utf-8")
        hdr_path = tdp / "fonts.tex"
        hdr_path.write_text(FONT_HEADER % {"ttf": ttf}, encoding="utf-8")
        log_path = tdp / "pandoc.log"

        pandoc = shutil.which("pandoc", path=env["PATH"]) or str(
            Path(sys.executable).parent / "Library" / "bin" / "pandoc.exe")
        cmd = [
            pandoc, str(md_path), "-o", str(OUT),
            "--pdf-engine=xelatex", "--pdf-engine-opt=--enable-installer",
            "-H", str(hdr_path), "--toc",
            "-V", "geometry:margin=2.3cm", "-V", "colorlinks=true",
            "-V", "linkcolor=blue", "-V", "toccolor=black",
            "--metadata", "title=Prototipo 1 - Manual de usuario",
        ]
        print("[*] pandoc + xelatex ...")
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        log = (r.stdout or "") + (r.stderr or "")
        log_path.write_text(log, encoding="utf-8")
        missing = sorted(set(re.findall(r"U\+[0-9A-F]+", log)))
        if r.returncode != 0:
            print("[ERROR] pandoc/xelatex fallo:")
            print("\n".join(log.splitlines()[-25:]))
            return 1
        if missing:
            print(f"[WARN] glyphs sin cubrir ({len(missing)}): {', '.join(missing)}")
        else:
            print("[OK] sin glyphs faltantes.")

    size_mb = OUT.stat().st_size / 1e6
    print(f"[OK] {OUT.name} generado ({size_mb:.2f} MB).")
    if DIST_OUT.parent.exists():
        shutil.copy2(OUT, DIST_OUT)
        print(f"[OK] copiado a {DIST_OUT}")
    else:
        print(f"[i] {DIST_OUT.parent} no existe (sin build); no se copia al dist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
