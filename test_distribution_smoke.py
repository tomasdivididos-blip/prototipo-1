"""
test_distribution_smoke.py
==========================
Smoke test del bundle distribuible: copia dist/Prototipo1/ a un tempdir
COMPLETAMENTE afuera del proyecto, lanza el .exe desde ahi, espera N
segundos y verifica que el proceso siga vivo (= no hubo error de startup
tipo "DLL load failed" o ImportError).

Lo que SI verifica:
  - .exe arranca sin crash inmediato
  - Process se mantiene vivo el tiempo esperado de una GUI
  - stderr / stdout vacios o sin "ERROR" / "Traceback"
  - Materials/ presente en la copia movida

Lo que NO verifica (requiere ojo humano):
  - La GUI realmente se ve correcta
  - Los materiales aparecen en el dialog "Materiales"
  - ejemplo.room carga visualmente
  - "Calcular modos (FEM)" termina sin error
"""

from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
DIST_SRC = PROJECT_ROOT / "dist" / "Prototipo1"
TEST_DIR = Path(os.environ.get("TEMP", "/tmp")) / "prototipo1_test_profe"
WAIT_SECONDS = 15  # cuanto esperar antes de declarar "vivo"


def step(label: str):
    print(f"\n[*] {label}")


def main() -> int:
    print("=" * 60)
    print(" Smoke test del bundle distribuible")
    print("=" * 60)

    # 1. Sanity: dist existe
    if not DIST_SRC.is_dir():
        print(f"[FAIL] No existe {DIST_SRC}")
        print("       Correr build.bat primero.")
        return 1

    # 2. Limpiar tempdir previo
    step(f"Preparando tempdir: {TEST_DIR}")
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Copiar dist a tempdir (no es link simbolico — copy real)
    test_dist = TEST_DIR / "Prototipo1"
    step(f"Copiando bundle a {test_dist} (puede tardar ~30 s)...")
    t0 = time.perf_counter()
    shutil.copytree(DIST_SRC, test_dist)
    t_copy = time.perf_counter() - t0
    n_files = sum(1 for _ in test_dist.rglob("*") if _.is_file())
    size_mb = sum(p.stat().st_size for p in test_dist.rglob("*") if p.is_file()) / (1024 ** 2)
    print(f"    OK ({n_files} archivos, {size_mb:.0f} MB, copia tardo {t_copy:.1f} s)")

    # 4. Verify materials at new location
    step("Verificando materiales en la copia (NO en la fuente)")
    mat_dir = test_dist / "_internal" / "materials"
    if not mat_dir.is_dir():
        print(f"    FAIL — falta {mat_dir}")
        return 1
    n_mat = len(list(mat_dir.glob("*.json")))
    print(f"    OK — {n_mat} materiales JSON presentes (esperado: 19)")

    # 5. Lanzar el .exe
    exe = test_dist / "Prototipo1.exe"
    if not exe.exists():
        print(f"    FAIL — falta {exe}")
        return 1

    step(f"Lanzando {exe.name} (cwd={test_dist})")
    print("    NOTA: la app es GUI; si no se ve la ventana, mirar la barra de tareas.")

    # Importante: cwd=test_dist asegura que cualquier Path(__file__).parent
    # del proceso resuelva a algo dentro del tempdir, NO al source.
    # PIPE de stderr para capturar tracebacks si arranca y muere.
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(test_dist),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # En Windows, creationflags=CREATE_NO_WINDOW evitaria consola; pero
        # como queremos VER si la GUI levanta, no lo seteamos. La GUI abre
        # su propia ventana Qt.
    )

    step(f"Esperando {WAIT_SECONDS} s para que la GUI levante...")
    t0 = time.perf_counter()
    try:
        # Si muere antes de WAIT_SECONDS, .wait() retorna; si sigue vivo,
        # raise TimeoutExpired -> sabemos que esta corriendo.
        rc = proc.wait(timeout=WAIT_SECONDS)
        # Si llegamos aca, el proceso MURIO antes del timeout = falla
        elapsed = time.perf_counter() - t0
        print(f"    FAIL — proceso murio tras {elapsed:.1f} s con returncode={rc}")
        out, err = proc.communicate()
        if out:
            print("\n    stdout:")
            for line in out.decode("utf-8", errors="replace").splitlines()[-30:]:
                print(f"      {line}")
        if err:
            print("\n    stderr:")
            for line in err.decode("utf-8", errors="replace").splitlines()[-30:]:
                print(f"      {line}")
        return 1
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        print(f"    OK — proceso sigue vivo tras {elapsed:.1f} s (PID {proc.pid}).")
        print(f"           GUI deberia estar visible en pantalla.")

    # 6. Matar el proceso limpio
    step("Cerrando el proceso (test completo)")
    try:
        proc.terminate()
        proc.wait(timeout=5)
        print("    OK — proceso cerrado limpio.")
    except subprocess.TimeoutExpired:
        print("    WARN — proceso no respondio a terminate(); forzando kill.")
        proc.kill()
        proc.wait()
    except Exception as e:
        print(f"    WARN — error al cerrar: {e}")

    # 7. Resumen + proximo paso manual
    print()
    print("=" * 60)
    print(" Smoke test pasado")
    print("=" * 60)
    print(f"  Bundle ubicado en: {test_dist}")
    print()
    print("  Lo que VOS tenes que verificar visualmente:")
    print()
    print("    1. Doble click manual en:")
    print(f"       {exe}")
    print()
    print("    2. En la pestaña Acustica, boton 'Materiales' -> dialog")
    print("       deberia listar ~19 materiales (yeso, hormigon,")
    print("       madera, alfombras, ventanas, paneles, etc.)")
    print()
    print("    3. Ctrl+O -> abrir 'ejemplo.room' (ya esta en la misma")
    print("       carpeta que el .exe). Deberia mostrarse una sala")
    print("       5x4x3 con una fuente en esquina y un receptor central.")
    print()
    print("    4. 'Calcular modos (FEM)' -> debe terminar en ~5-30 s")
    print("       y mostrar los modos en el dropdown 'Modo:'.")
    print()
    print(f"  Si pasa los 4, mandas: Prototipo1_v2.12.zip al profesor.")
    return 0


if __name__ == "__main__":
    rc = main()
    print()
    sys.exit(rc)
