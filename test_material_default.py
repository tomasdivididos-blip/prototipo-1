"""
test_material_default.py
========================
Test del fix B27: `MaterialLibrary.get_default()` debe devolver SIEMPRE el
genérico rígido conservador (α≈0.03), nunca `_materials[0]`.

Quirk original (detectado 2026-06-20 validando el advisory B27):
  Al cargar la carpeta `materials/` (428 materiales), `_materials[0]` era el
  primer JSON alfabético (`alfombra_fina.json` → una alfombra, el material
  MÁS absorbente). `get_default()` devolvía esa alfombra en vez del rígido,
  haciendo misfire a un test que asumía "default = superficie neutra".

Se corre directo (`python test_material_default.py`) o con pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path

from material_library import MaterialLibrary, _default_material

PROJECT_ROOT = Path(__file__).parent
MATERIALS_DIR = PROJECT_ROOT / "materials"


def test_get_default_is_rigid_when_loaded_from_folder():
    """Con la carpeta cargada, get_default() sigue siendo el rígido α≈0.03,
    NO la primera alfombra alfabética."""
    lib = MaterialLibrary(str(MATERIALS_DIR))
    # Sanidad: la carpeta cargó muchos materiales y el primero NO es rígido.
    assert len(lib) > 1, "se esperaban varios materiales cargados de materials/"
    first = lib[0]

    default = lib.get_default()
    rigid = _default_material()

    # get_default() == rígido conservador, sin importar _materials[0].
    assert default.name == rigid.name == "Genérico rígido (α≈0.03)"
    assert abs(default.alpha(500) - 0.03) < 1e-9
    # Y de hecho NO es el primer material (que es una alfombra absorbente).
    assert default.name != first.name, (
        f"get_default() volvió a caer en _materials[0] ({first.name!r})"
    )
    # La alfombra de _materials[0] es mucho más absorbente que el default.
    assert first.alpha(500) > default.alpha(500)


def test_get_default_is_rigid_when_library_empty():
    """Sin carpeta, la lib se autocompleta con el rígido y get_default() lo
    devuelve igual (regresión del caso ya correcto)."""
    lib = MaterialLibrary()
    assert lib.get_default().name == "Genérico rígido (α≈0.03)"


def test_get_rigid_default_alias():
    """get_rigid_default() es el nombre explícito y coincide con get_default()."""
    lib = MaterialLibrary(str(MATERIALS_DIR))
    assert lib.get_rigid_default().name == lib.get_default().name
    assert abs(lib.get_rigid_default().alpha(500) - 0.03) < 1e-9


def test_indexing_still_returns_first_material():
    """El acceso explícito por índice sigue devolviendo el primer material
    (alfombra) — el fix NO cambió la semántica de lib[0]."""
    lib = MaterialLibrary(str(MATERIALS_DIR))
    assert lib[0].name == lib.materials[0].name
    # lib[0] NO es el rígido (es lo que confundía a get_default()).
    assert lib[0].name != "Genérico rígido (α≈0.03)"


if __name__ == "__main__":
    tests = [
        test_get_default_is_rigid_when_loaded_from_folder,
        test_get_default_is_rigid_when_library_empty,
        test_get_rigid_default_alias,
        test_indexing_still_returns_first_material,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"[ERR]  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} OK")
    sys.exit(1 if failed else 0)
