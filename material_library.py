"""material_library.py
===================
Carga y gestiona materiales acusticos desde archivos JSON.

Formato JSON soportado (ambos coexisten, se autodetecta):

  (a) UN material por archivo:
      {
        "name":        "Nombre",
        "category":    "...",
        "description": "...",
        "source":      "...",
        "alpha":       { "63": 0.01, "125": 0.02, ... },     // dict por banda
        "scattering":  { "125": 0.05, ... }                  // dict por banda
      }

  (b) VARIOS materiales en un archivo (array de objetos):
      [
        { "name": "...", "category": "...", "description": "...",
          "source": "...",
          "absorption_coef": [a63, a125, a250, a500, a1k, a2k, a4k, a8k],
          "scatter_coef":    [s63, s125, s250, s500, s1k, s2k, s4k, s8k] },
        { ... },
        ...
      ]

Campos numericos aceptados (cualquiera de los dos):
  - alpha (dict)             |  absorption_coef (lista de 8 floats)
  - scattering (dict)        |  scatter_coef (lista de 8 floats o float unico)

Bandas de octava estandar (en este orden si vienen como lista):
  [63, 125, 250, 500, 1000, 2000, 4000, 8000] Hz.
"""

from __future__ import annotations

import json
import unicodedata
import numpy as np
from pathlib import Path
from typing import Dict, Optional, List

# Bandas de octava estandar
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]

C0 = 343.0   # velocidad del sonido [m/s]


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------
class Material:
    """Material acustico con alpha(f) y scattering(f) interpolados por banda."""

    def __init__(self, data: dict, filename: str = ""):
        self.filename = filename
        self.name = data.get("name", Path(filename).stem if filename else "Sin nombre")
        self.category = data.get("category", "")
        self.description = data.get("description", "")
        self.source = data.get("source", "")

        # ---- coeficiente de absorcion: dict (alpha) o lista (absorption_coef) ----
        raw_alpha = data.get("alpha", data.get("absorption", {}))
        if not raw_alpha and "absorption_coef" in data:
            coefs = data["absorption_coef"]
            if isinstance(coefs, list) and len(coefs) == len(BANDS):
                raw_alpha = {str(b): float(v) for b, v in zip(BANDS, coefs)}

        # ---- coeficiente de scattering: dict, lista, o float unico ----
        raw_scat = data.get("scattering", data.get("s", {}))
        if not raw_scat and "scatter_coef" in data:
            scat = data["scatter_coef"]
            if isinstance(scat, (int, float)):
                raw_scat = {str(b): float(scat) for b in BANDS}
            elif isinstance(scat, list) and len(scat) == len(BANDS):
                raw_scat = {str(b): float(v) for b, v in zip(BANDS, scat)}

        self._alpha = {int(k): float(v) for k, v in raw_alpha.items()} if raw_alpha else {}
        self._scat  = {int(k): float(v) for k, v in raw_scat.items()}  if raw_scat  else {}

        self._alpha_table = self._build_table(self._alpha, default=0.03)
        self._scat_table  = self._build_table(self._scat,  default=0.05)

    @staticmethod
    def _build_table(data: dict, default: float) -> Dict[int, float]:
        if not data:
            return {b: default for b in BANDS}
        freqs = sorted(data.keys())
        vals  = [data[f] for f in freqs]
        result = {}
        log_freqs = np.log(np.array(freqs, dtype=float))
        for b in BANDS:
            if b in data:
                result[b] = float(data[b])
            elif b < freqs[0]:
                result[b] = float(vals[0])
            elif b > freqs[-1]:
                result[b] = float(vals[-1])
            else:
                result[b] = float(np.interp(np.log(b), log_freqs, vals))
        return result

    def alpha(self, f: float) -> float:
        """Coeficiente de absorcion interpolado a frecuencia f (Hz).

        Usa los datos CRUDOS (`_alpha`) cuando existen, para preservar la
        resolucion original: si el material se cargo en tercios de octava
        (medicion propia), alpha(f) los honra en vez de colapsar a las 8
        octavas de `_alpha_table`. Para materiales de catalogo (octava
        completa) el resultado es identico -> sin regresion. Sin datos cae a
        la tabla por defecto."""
        return self._interp(self._alpha if self._alpha else self._alpha_table, f)

    def scattering(self, f: float) -> float:
        return self._interp(self._scat_table, f)

    def alpha_bands(self) -> Dict[int, float]:
        return dict(self._alpha_table)

    @staticmethod
    def _interp(table: dict, f: float) -> float:
        bands = sorted(table.keys())
        if f <= bands[0]:  return table[bands[0]]
        if f >= bands[-1]: return table[bands[-1]]
        lf = np.log(f)
        lbs = np.log(np.array(bands, dtype=float))
        vals = [table[b] for b in bands]
        return float(np.interp(lf, lbs, vals))

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Material({self.name!r})"


# ---------------------------------------------------------------------------
# Material por defecto
# ---------------------------------------------------------------------------
def _default_material() -> Material:
    return Material({
        "name": "Genérico rígido (α≈0.03)",
        "category": "default",
        "description": "Superficie rígida tipo hormigón sin revestir",
        "alpha": {
            "63": 0.02, "125": 0.02, "250": 0.03, "500": 0.03,
            "1000": 0.04, "2000": 0.04, "4000": 0.05, "8000": 0.06
        },
        "scattering": {
            "125": 0.05, "250": 0.05, "500": 0.10,
            "1000": 0.10, "2000": 0.15, "4000": 0.15
        },
    })


# ---------------------------------------------------------------------------
# Biblioteca de materiales
# ---------------------------------------------------------------------------
class MaterialLibrary:
    """Carga materiales desde una carpeta de archivos JSON.

    Cada .json puede contener UN material (dict) o VARIOS (array de objetos).
    """

    def __init__(self, folder: Optional[str] = None):
        self._materials: List[Material] = []
        self._folder: Optional[str] = None
        if folder:
            self.load_folder(folder)
        if not self._materials:
            self._materials.append(_default_material())

    def load_folder(self, folder: str) -> int:
        """Carga todos los .json de la carpeta. Devuelve la cantidad de
        materiales cargados (no de archivos)."""
        self._folder = str(folder)
        path = Path(folder)
        if not path.exists():
            return 0
        count = 0
        for fn in sorted(path.glob("*.json")):
            try:
                data = json.loads(fn.read_text(encoding="utf-8"))
            except Exception:
                continue
            # Autodeteccion: dict = 1 material, list = varios
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    mat = Material(entry, filename=str(fn))
                    self._materials.append(mat)
                    count += 1
                except Exception:
                    pass
        # Orden alfabético por nombre (sin acentos ni mayúsculas, misma
        # normalización que resolve_material). Los combos y asignaciones
        # mapean por NOMBRE, así que el reordenamiento no rompe nada.
        self._materials.sort(key=lambda m: _norm(m.name))
        return count

    def reload(self) -> int:
        """Recarga los materiales de `self._folder` EN EL SITIO (misma instancia).

        Sirve para que un material recien copiado a la carpeta aparezca sin
        recrear el objeto MaterialLibrary — cualquier referencia compartida
        (panel + dialogos) ve el material nuevo. Devuelve la cantidad cargada."""
        self._materials = []
        n = self.load_folder(self._folder) if self._folder else 0
        if not self._materials:
            self._materials.append(_default_material())
        return n

    @property
    def materials(self) -> List[Material]:
        return list(self._materials)

    @property
    def names(self) -> List[str]:
        return [m.name for m in self._materials]

    def by_category(self) -> Dict[str, List[Material]]:
        """Devuelve los materiales agrupados por categoria."""
        out: Dict[str, List[Material]] = {}
        for m in self._materials:
            out.setdefault(m.category or "(sin categoria)", []).append(m)
        return out

    def __getitem__(self, idx: int) -> Material:
        return self._materials[idx]

    def __len__(self) -> int:
        return len(self._materials)

    def get_rigid_default(self) -> Material:
        """Material rígido conservador (α≈0.03, hormigón sin revestir).

        SIEMPRE devuelve el genérico rígido de `_default_material()`, sin
        importar qué materiales tenga cargados la biblioteca. Es el default
        físico que usa el resto del flujo (caras sin asignar → α=0.03, ver
        `face_materials._alpha_for`) cuando se necesita una superficie
        "por defecto" para una cara sin material o un cálculo base de RT60.
        """
        return _default_material()

    def get_default(self) -> Material:
        """Material por defecto = el rígido conservador (α≈0.03).

        OJO: NO devuelve `_materials[0]`. Cuando la biblioteca se carga desde
        la carpeta `materials/`, `_materials[0]` es el primer JSON alfabético
        (una alfombra), que NO es un default conservador sino el material más
        absorbente posible — un footgun para cualquier caller que asuma
        "default = superficie neutra/rígida". Por eso delega en
        `get_rigid_default()`. Si lo que querés es "el primer material de la
        lista", usá `lib[0]` o `lib.materials[0]` explícitamente.
        """
        return self.get_rigid_default()


# ---------------------------------------------------------------------------
# Clasificacion de areas superficiales por zona (piso / techo / paredes)
# ---------------------------------------------------------------------------
def classify_surface_areas(surface_verts: np.ndarray,
                            surface_tris: np.ndarray) -> tuple:
    """Devuelve (S_floor, S_ceiling, S_walls) en m² a partir de la malla superficial.

    Clasificacion por normal del triangulo y posicion vertical:
      - Piso:   normal apunta hacia abajo (nz < -0.7) y centroide cerca de zmin
      - Techo:  normal apunta hacia arriba (nz > 0.7) y centroide cerca de zmax
      - Paredes: el resto
    """
    v = surface_verts.astype(float)
    a = v[surface_tris[:, 0]]
    b = v[surface_tris[:, 1]]
    c = v[surface_tris[:, 2]]
    cross   = np.cross(b - a, c - a)
    areas   = np.linalg.norm(cross, axis=1) * 0.5
    norms_n = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-12)

    z_min = float(v[:, 2].min())
    z_max = float(v[:, 2].max())
    dz    = (z_max - z_min) * 0.25        # umbral del 25 % para piso/techo
    cz    = (a[:, 2] + b[:, 2] + c[:, 2]) / 3.0

    floor_m   = (norms_n[:, 2] < -0.7) & (cz < z_min + dz)
    ceiling_m = (norms_n[:, 2] >  0.7) & (cz > z_max - dz)
    wall_m    = ~floor_m & ~ceiling_m

    return (float(areas[floor_m].sum()),
            float(areas[ceiling_m].sum()),
            float(areas[wall_m].sum()))


# ---------------------------------------------------------------------------
# Calculo de RT60 y amortiguamiento modal
# ---------------------------------------------------------------------------
def compute_sabine_rt60(V: float,
                         S_floor: float,   mat_floor: Material,
                         S_ceiling: float, mat_ceiling: Material,
                         S_walls: float,   mat_walls: Material,
                         bands: Optional[List[int]] = None) -> Dict[int, float]:
    """RT60(f) por bandas de octava usando la formula de Sabine.

    Devuelve {banda_Hz: RT60_segundos}.
    """
    if bands is None:
        bands = BANDS
    rt60 = {}
    for b in bands:
        A = (mat_floor.alpha(b)   * S_floor +
             mat_ceiling.alpha(b) * S_ceiling +
             mat_walls.alpha(b)   * S_walls)
        A = max(A, 1e-6)
        rt60[b] = 0.161 * V / A
    return rt60


# ---------------------------------------------------------------------------
# Presets de materiales por superficie (piso / paredes / techo)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    """Normaliza para matchear nombres del catalogo sin depender de acentos
    ni mayusculas (ej. 'panel acustico' matchea 'Panel acústico (...)')."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


# Cada preset mapea piso/paredes/techo a una CLAVE de busqueda (substring
# normalizado) que matchea un material real del catalogo `materials/`. Si una
# clave no matchea (catalogo distinto), cae al rigido por defecto.
MATERIAL_PRESETS: Dict[str, Dict[str, str]] = {
    "Reflectante / viva": {
        "floor": "piso de madera", "walls": "ladrillo visto", "ceiling": "madera",
    },
    "Estudio tratado": {
        "floor": "alfombra fina", "walls": "panel acustico",
        "ceiling": "cielorraso acustico (lana de vidrio), 40 mm, 70 kg",
    },
    "Home theatre": {
        "floor": "alfombra gruesa", "walls": "terciopelo pesado drapeado",
        "ceiling": "cielorraso acustico (lana de vidrio), 40 mm, 70 kg",
    },
    "Aula / conferencia": {
        "floor": "piso de madera", "walls": "yeso pintado", "ceiling": "panel acustico",
    },
    "Neutra / generica": {
        "floor": "yeso pintado", "walls": "yeso pintado", "ceiling": "yeso pintado",
    },
}


def preset_names() -> List[str]:
    return list(MATERIAL_PRESETS.keys())


def resolve_material(lib: "MaterialLibrary", key: str) -> Material:
    """Primer material del catalogo cuyo nombre CONTIENE `key` (normalizado).
    Si no hay match, devuelve el rigido por defecto (α≈0.03)."""
    nk = _norm(key)
    if nk:
        for m in lib.materials:
            if nk in _norm(m.name):
                return m
    return lib.get_rigid_default()


def preset_surface_materials(lib: "MaterialLibrary",
                             preset_name: str) -> tuple:
    """(mat_floor, mat_walls, mat_ceiling) para un preset con nombre."""
    spec = MATERIAL_PRESETS.get(preset_name)
    if spec is None:
        d = lib.get_rigid_default()
        return d, d, d
    return (resolve_material(lib, spec["floor"]),
            resolve_material(lib, spec["walls"]),
            resolve_material(lib, spec["ceiling"]))


def compute_xi_per_mode(freqs: np.ndarray,
                         rt60_bands: Dict[int, float]) -> np.ndarray:
    """Calcula xi_n = 1.1 / (f_n * RT60(f_n)) para cada modo.

    Interpola RT60 en escala logaritmica a la frecuencia de cada modo.
    El factor 1.1 viene de: xi = ln(1000) / (2*pi*f_n*T60).
    """
    bands     = sorted(rt60_bands.keys())
    rt60_vals = [rt60_bands[b] for b in bands]
    log_bands = np.log(np.array(bands, dtype=float))

    xi = np.empty(len(freqs))
    for i, fn in enumerate(freqs):
        fn_c = float(np.clip(fn, bands[0], bands[-1]))
        rt60_fn = float(np.interp(np.log(fn_c), log_bands, rt60_vals))
        xi[i] = 1.1 / max(fn * rt60_fn, 1e-9)
    return xi
