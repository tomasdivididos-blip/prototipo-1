#!/usr/bin/env python
"""Scraper barato de PDFs para minar criterios sin renderizar imagenes.

Usa `pdftotext` (Poppler, ya instalado en /mingw64/bin) para sacar la capa de
texto y filtrar SOLO las paginas que matchean un regex de keywords. ~10x mas
barato en tokens que el Read de PDF (que renderiza cada pagina como imagen).

Uso:
    python _scrape.py "<glob del archivo>" "<regex keywords>" [pag_ini] [pag_fin]

Ejemplos:
    python _scrape.py "Master Handbook*.pdf" "bonello|axial|coloration"
    python _scrape.py "Recording Studio*.pdf" "soffit|flush|LEDE|RFZ|monitor" 1 200

Notas:
  - El numero de pagina impreso es el de PDF (para pasarselo al Read si hay que
    VER una figura/tabla/ecuacion puntual que el texto no captura).
  - Si no devuelve nada, el PDF puede ser escaneado (sin capa de texto) -> ahi si
    hace falta Read (imagen) u OCR.
"""
import sys, re, subprocess, glob

if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)

fn = glob.glob(sys.argv[1])
if not fn:
    print(f"No file matches: {sys.argv[1]}"); sys.exit(1)
fn = fn[0]
kw = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
p_ini = int(sys.argv[3]) if len(sys.argv) > 3 else None
p_fin = int(sys.argv[4]) if len(sys.argv) > 4 else None

args = ["pdftotext", "-layout"]
if p_ini: args += ["-f", str(p_ini)]
if p_fin: args += ["-l", str(p_fin)]
args += [fn, "-"]

txt = subprocess.run(args, capture_output=True, text=True,
                     encoding="utf-8", errors="ignore").stdout
pages = txt.split("\f")
base = (p_ini or 1)
hits = 0
for i, p in enumerate(pages):
    if not p.strip():
        continue
    if kw is None or kw.search(p):
        hits += 1
        clean = re.sub(r"\n\s*\n+", "\n", p).strip()
        print(f"===== PDF page {base + i} =====")
        print(clean[:1400])
        print()
print(f"### {hits} paginas con match en {fn}")
