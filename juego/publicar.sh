#!/usr/bin/env bash
# Publica el juego al repo público (GitHub Pages) → celular.
#
# Qué hace, en orden:
#   1. Valida el banco (check_banco.py) — si hay error, aborta.
#   2. Clona el repo público en una carpeta temporal (sin estado que se ensucie).
#   3. Copia los archivos del juego encima.
#   4. Sube la versión del service worker (acu-<timestamp>) para que la app
#      instalada en el celular agarre lo nuevo en la próxima apertura online.
#   5. Commit + push.
#
# Uso:  bash publicar.sh
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="https://github.com/tomasdivididos-blip/acustica-juego.git"
PAGES="https://tomasdivididos-blip.github.io/acustica-juego/"
PY="/c/Users/aceve/anaconda3/python.exe"
WORK="$(mktemp -d)"

echo "1) Validando banco…"
PYTHONIOENCODING=utf-8 "$PY" "$SRC/check_banco.py" >/dev/null || { echo "✗ banco con errores, abortado"; exit 1; }

echo "2) Clonando repo público…"
git clone -q --depth 1 "$REPO" "$WORK/repo"

echo "3) Copiando archivos del juego…"
cd "$WORK/repo"
mkdir -p banco icons
cp "$SRC/index.html" "$SRC/style.css" "$SRC/app.js" "$SRC/gen.js" "$SRC/sw.js" "$SRC/manifest.webmanifest" .
cp "$SRC/banco/"*.js banco/
cp "$SRC/icons/"*.png icons/
cp "$SRC/README.md" "$SRC/CONTENIDO.md" "$SRC/CITAS.md" . 2>/dev/null || true

echo "4) Subiendo versión del service worker…"
VER="acu-$(date -u +%Y%m%d%H%M%S)"
# Reemplaza la línea const VER = "..." por una nueva y única.
sed -i -E "s/const VER = \"[^\"]*\"/const VER = \"$VER\"/" sw.js
echo "   nueva versión de cache: $VER"

echo "5) Commit + push…"
git add -A
if git diff --cached --quiet; then
  echo "   (sin cambios que publicar)"; rm -rf "$WORK"; exit 0
fi
git -c user.name="Tomás Acevedo" -c user.email="tomasdivididos@gmail.com" \
    commit -q -m "Publicar juego ($VER)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push -q origin main

rm -rf "$WORK"
echo
echo "✓ Publicado. En ~1 min live en:"
echo "  $PAGES"
echo "  (la app instalada se actualiza sola en la próxima apertura con internet)"
