#!/bin/bash
# ============================================================
# Prototipo 1 - Lanzador para macOS (corre desde codigo fuente)
# ============================================================
# Como usar (ver tambien LEEME_MAC.txt):
#   1) Abri la app "Terminal" (Aplicaciones > Utilidades > Terminal).
#   2) Escribi:  bash      (la palabra bash y un espacio)
#   3) Arrastra ESTE archivo (run.command) a la ventana de Terminal.
#   4) Presiona Enter.
# La primera vez instala las dependencias (tarda unos minutos).
# Las siguientes veces abre directo.
# ============================================================

# Ir a la carpeta donde esta este script
cd "$(dirname "$0")" || exit 1

echo "==> Prototipo 1 (macOS)"

# 1) Buscar Python 3
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "*** No se encontro Python 3. ***"
  echo "Instala Python 3.12 desde:  https://www.python.org/downloads/macos/"
  echo "Despues volve a correr este archivo."
  echo ""
  read -p "Presiona Enter para cerrar..."
  exit 1
fi
echo "==> Usando: $("$PY" --version)"

# 2) Crear entorno virtual la primera vez e instalar dependencias
if [ ! -d ".venv_mac" ]; then
  echo "==> Primera ejecucion: preparando entorno (esto tarda unos minutos)..."
  "$PY" -m venv .venv_mac || { echo "Error creando el entorno."; read -p "Enter para cerrar..."; exit 1; }
  ./.venv_mac/bin/python -m pip install --upgrade pip
  echo "==> Instalando librerias principales..."
  ./.venv_mac/bin/python -m pip install "PyQt5>=5.15" "pyqtgraph>=0.13.3" "PyOpenGL>=3.1.6" "numpy>=1.24" "scipy>=1.10" "matplotlib>=3.7" \
    || { echo "Error instalando librerias principales."; read -p "Enter para cerrar..."; exit 1; }
  echo "==> Instalando soporte CAD (opcional)..."
  ./.venv_mac/bin/python -m pip install "gmsh>=4.13" "trimesh>=4.0" \
    || echo "Aviso: no se pudo instalar gmsh/trimesh (importar CAD no estara disponible; el resto de la app funciona)."
fi

# 3) Lanzar la app
echo "==> Abriendo Prototipo 1..."
./.venv_mac/bin/python main.py
status=$?
if [ $status -ne 0 ]; then
  echo ""
  echo "La app se cerro con un error (codigo $status)."
  read -p "Presiona Enter para cerrar..."
fi
