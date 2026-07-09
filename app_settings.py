"""
app_settings.py
===============

Persistencia de preferencias globales del soft (cross-sesion, cross-proyecto).

Archivo en %APPDATA%/Prototipo1/settings.json en Windows, ~/.config/Prototipo1/
en Linux, ~/Library/Application Support/Prototipo1/ en macOS.

Llaves soportadas (todas opcionales, con defaults):
  - default_mesh_engine : "auto" | "voxel" | "gmsh"
  - default_h_target    : float (m) - tamano de elemento para gmsh
  - default_n_per_meter : float (1/m) - densidad para voxel
  - default_n_modes     : int - nro de modos a calcular en FEM
  - cad_recent_files    : list[str] - paths recientes para el importador
  - cad_last_dir        : str - ultimo directorio usado en el importador

API
---
load() -> dict          carga settings (con defaults rellenados)
save(settings)          escribe a disco
get(key, default=None)  helper directo
set(key, value)         helper directo (auto-save)
add_recent_file(path)   utilidad para historial
"""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from typing import Any


DEFAULTS = {
    "default_mesh_engine": "auto",
    "default_h_target":   0.40,
    "default_n_per_meter": 2.5,
    "default_n_modes":    12,
    "cad_recent_files":   [],
    "cad_last_dir":       "",
}

MAX_RECENT = 8


def _config_dir() -> Path:
    """Directorio donde vive settings.json, cross-OS."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Prototipo1"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Prototipo1"
    # Linux / *BSD
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Prototipo1"


def _settings_path() -> Path:
    return _config_dir() / "settings.json"


def _ensure_dir():
    d = _config_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def load() -> dict:
    """Lee settings, rellena con defaults. Nunca lanza."""
    p = _settings_path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
    # Merge con defaults (deep para listas no aplica aqui, solo top-level).
    out = dict(DEFAULTS)
    out.update(data)
    return out


def save(settings: dict) -> bool:
    """Escribe settings al disco. Devuelve True si lo logro."""
    _ensure_dir()
    p = _settings_path()
    try:
        p.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return True
    except OSError:
        return False


def get(key: str, default: Any = None) -> Any:
    s = load()
    return s.get(key, default if default is not None else DEFAULTS.get(key))


def set(key: str, value: Any) -> bool:
    s = load()
    s[key] = value
    return save(s)


def add_recent_file(path: str) -> bool:
    """Agrega un path al inicio del historial, evitando duplicados, cap a MAX_RECENT."""
    if not path:
        return False
    s = load()
    recent = list(s.get("cad_recent_files") or [])
    # Quitar duplicados (case-insensitive en Windows)
    norm = os.path.normcase(os.path.abspath(path))
    recent = [p for p in recent
              if os.path.normcase(os.path.abspath(p)) != norm]
    recent.insert(0, path)
    s["cad_recent_files"] = recent[:MAX_RECENT]
    s["cad_last_dir"] = os.path.dirname(path) or s.get("cad_last_dir", "")
    return save(s)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"settings path: {_settings_path()}")
    cur = load()
    print(f"actual: {cur}")
    ok = set("default_mesh_engine", "auto")
    print(f"set ok: {ok}")
    ok = add_recent_file(r"C:\fake\sala.step")
    print(f"add_recent ok: {ok}")
    print(f"despues: {load()}")
