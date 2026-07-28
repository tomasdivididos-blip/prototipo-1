#!/usr/bin/env python
"""Empaqueta el juego (modulos ES + CSS) en UN solo HTML autocontenido.

Produce dos archivos:
  - dist.html      : standalone completo (doctype+html+head+body). Se puede abrir
                     con doble clic, sin servidor. Ideal para testear.
  - artifact.html  : solo el contenido del <body> (style + secciones + script),
                     para publicar como Artifact (la plataforma envuelve el resto).

Los modulos se concatenan en orden de dependencia y se les quitan las lineas
`import` y la palabra `export`, quedando todo en un unico scope de <script>.
"""
import re, os

BASE = os.path.dirname(os.path.abspath(__file__))

# Orden de dependencia: gen -> bancos -> numericos -> index (arma BANCO) -> app.
JS_FILES = [
    "gen.js",
    "banco/numericos.js",
    "banco/geometria.js",
    "banco/fuentes.js",
    "banco/psicoacustica.js",
    "banco/numerica.js",
    "banco/index.js",
    "app.js",
]


def strip_module(src):
    # Quita lineas `import ...;` (una sola linea cada una en este proyecto).
    src = re.sub(r"^\s*import\s.*?;\s*$", "", src, flags=re.M)
    # `export const/function/...` -> quita solo la palabra export.
    src = re.sub(r"^(\s*)export\s+", r"\1", src, flags=re.M)
    # Registro del service worker: no aplica en un archivo unico.
    src = re.sub(
        r'if \("serviceWorker" in navigator\) \{.*?\}\s*$',
        "", src, flags=re.S,
    )
    return src.strip()


def read(path):
    with open(os.path.join(BASE, path), encoding="utf-8") as f:
        return f.read()


def main():
    css = read("style.css")

    js = "\n\n".join(
        f"// ===== {fn} =====\n{strip_module(read(fn))}" for fn in JS_FILES
    )

    # Cuerpo de index.html: todo lo que hay entre <body> y </body>, sin el
    # <script src=app.js> (lo reemplazamos por el bundle inline).
    html = read("index.html")
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = re.sub(r'<script[^>]*src="app\.js"[^>]*>\s*</script>', "", body)
    body = body.strip()

    inner = (
        f"<style>\n{css}\n</style>\n\n"
        f"{body}\n\n"
        f'<script type="module">\n{js}\n</script>\n'
    )

    with open(os.path.join(BASE, "artifact.html"), "w", encoding="utf-8") as f:
        f.write(inner)

    standalone = (
        "<!doctype html>\n"
        '<html lang="es">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="theme-color" content="#0f1115">\n'
        "<title>Acústica — Juego</title>\n"
        "</head>\n<body>\n"
        f"{inner}"
        "</body>\n</html>\n"
    )
    with open(os.path.join(BASE, "dist.html"), "w", encoding="utf-8") as f:
        f.write(standalone)

    kb = len(standalone.encode("utf-8")) / 1024
    print(f"OK  dist.html + artifact.html  ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
