@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  Empaqueta Prototipo 1 en una carpeta auto-contenida (.exe + DLLs).
REM  Salida: dist\Prototipo1\Prototipo1.exe  -> portable, sin Python.
REM ============================================================

REM --- Buscar Anaconda Python ---
set "PYEXE="
if exist "%USERPROFILE%\anaconda3\python.exe" set "PYEXE=%USERPROFILE%\anaconda3\python.exe"
if "%PYEXE%"=="" if exist "%USERPROFILE%\miniconda3\python.exe" set "PYEXE=%USERPROFILE%\miniconda3\python.exe"
if "%PYEXE%"=="" if exist "%PROGRAMDATA%\anaconda3\python.exe" set "PYEXE=%PROGRAMDATA%\anaconda3\python.exe"

if "%PYEXE%"=="" (
    echo [ERROR] No se encontro Anaconda.
    pause
    exit /b 1
)

echo Usando Python: %PYEXE%

REM --- PATH de las DLLs nativas de conda (CRITICO) ---
REM  Anaconda NO guarda las DLLs de Qt en site-packages\PyQt5\Qt5\bin\ como un
REM  pip normal: las pone en <env>\Library\bin\ y con otro nombre
REM  (Qt5Core_conda.dll). PyInstaller las encuentra recorriendo el PATH, asi que
REM  si el .bat se lanza desde una consola SIN el entorno conda activado (un cmd
REM  pelado, doble click desde el Explorador, o un agente), no las ve y las
REM  OMITE EN SILENCIO: el build termina "OK", el .exe se genera, y recien al
REM  abrirlo muere con "DLL load failed while importing QtCore".
REM  Paso de verdad el 13-14 Ago 2026. Agregar el PATH aca hace el build
REM  reproducible desde cualquier consola.
for %%D in ("%PYEXE%") do set "PYDIR=%%~dpD"
set "PATH=%PYDIR%Library\bin;%PYDIR%Library\mingw-w64\bin;%PYDIR%DLLs;%PYDIR%;%PATH%"
echo PATH de DLLs: %PYDIR%Library\bin
echo.

REM --- Instalar PyInstaller si falta ---
"%PYEXE%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    "%PYEXE%" -m pip install --upgrade pyinstaller
)

REM --- Limpiar builds anteriores ---
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Prototipo1.spec" del /q "Prototipo1.spec"

REM --- Empaquetar ---
echo === Empaquetando (puede tardar 2-3 minutos) ===
echo.
REM Empaquetar:
REM   --add-data "materials;materials" bundlea los 19 JSON al lado de los .pyc
REM     en _internal/, donde Path(__file__).parent los encuentra. SIN esto,
REM     MaterialLibrary arranca con un solo material default y la UI queda
REM     invalida (RT60 sin material realista).
REM   --exclude-module PyQt6 / PySide6: PyInstaller falla con "attempt to
REM     collect multiple Qt bindings" si Anaconda tiene varios. PyQt5 only.
REM   --exclude-module pandas / IPython / sphinx / ...: deps transitivas que
REM     scipy/matplotlib/trimesh arrastran pero el proyecto no usa. Sin
REM     estos excludes el bundle pesa 1.9 GB en lugar de ~400-600 MB.
REM   --collect-all trimesh / gmsh (v2.21): los dos se importan DENTRO de
REM     funciones (import perezoso) y ademas cargan cosas en runtime que el
REM     analisis estatico no ve: trimesh resuelve sus handlers de formato de
REM     forma dinamica y trae archivos de datos; gmsh es un wrapper sobre una
REM     DLL nativa. Sin --collect-all el .exe arranca igual pero "Importar CAD
REM     (OBJ)" y el import de recinto CAD fallan recien al usarlos.
REM   *** NO EXCLUIR SUBMODULOS DE PyQt5 ***  (probado y roto, 13 Ago 2026)
REM     Poner --exclude-module PyQt5.QtWebEngineCore / QtWebEngine / QtWebKit
REM     ahorraba 107 MB PERO envenena el hook de PyQt5: PyInstaller deja de
REM     copiar PyQt5\Qt5\bin\ ENTERO, o sea TODAS las Qt5*.dll, no solo las del
REM     navegador. El .exe se genera igual y arranca hasta el import, y ahi
REM     muere con "DLL load failed while importing QtCore". Peor todavia: el
REM     smoke test daba OK porque el dialogo de error ES un proceso vivo.
REM     Si hace falta bajar esos 107 MB, hay que borrar la DLL del dist DESPUES
REM     del build, nunca excluir el modulo.
REM   --exclude-module botocore / panel / bokeh / numba / llvmlite: ~350 MB de
REM     peso muerto que Anaconda arrastra y el proyecto no toca (SDK de AWS,
REM     dashboards, JIT). Estos son seguros: no los toca Qt.
REM     Lo que QUEDA y no se puede sacar sin romper nada: los mkl_*.dll
REM     (~370 MB, el BLAS de numpy/scipy; son variantes de despacho por CPU y
REM     sacarlas rompe en maquinas con otro juego de instrucciones) y
REM     gmsh-4.15.dll (~86 MB, el mallador boundary-fitted opcional).
REM   --hidden-import=filters: filters.py (crossover/EQ por fuente, v2.29) se
REM     importa LAZY dentro de funciones (acoustic_panel/sources: `import filters`),
REM     asi que el analisis estatico de PyInstaller NO lo ve y el .exe crashea con
REM     ModuleNotFoundError al usar el filtro. scipy.signal (que filters usa) va por
REM     las dudas aunque el collect de scipy ya lo trae.
"%PYEXE%" -m PyInstaller ^
    --onedir ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --name "Prototipo1" ^
    --collect-all pyqtgraph ^
    --collect-submodules OpenGL ^
    --hidden-import=pyqtgraph.opengl ^
    --collect-all trimesh ^
    --collect-all gmsh ^
    --hidden-import=networkx ^
    --hidden-import=filters ^
    --hidden-import=scipy.signal ^
    --add-data "materials;materials" ^
    --exclude-module PyQt6 ^
    --exclude-module PySide6 ^
    --exclude-module PySide2 ^
    --exclude-module pandas ^
    --exclude-module IPython ^
    --exclude-module ipykernel ^
    --exclude-module jupyter ^
    --exclude-module jupyter_client ^
    --exclude-module jupyter_core ^
    --exclude-module notebook ^
    --exclude-module sphinx ^
    --exclude-module sphinxcontrib ^
    --exclude-module docutils ^
    --exclude-module jedi ^
    --exclude-module parso ^
    --exclude-module pytest ^
    --exclude-module black ^
    --exclude-module nacl ^
    --exclude-module bcrypt ^
    --exclude-module cryptography ^
    --exclude-module openpyxl ^
    --exclude-module pyarrow ^
    --exclude-module tables ^
    --exclude-module sqlalchemy ^
    --exclude-module lxml ^
    --exclude-module pygments ^
    --exclude-module tkinter ^
    --exclude-module _tkinter ^
    --exclude-module botocore ^
    --exclude-module boto3 ^
    --exclude-module numba ^
    --exclude-module llvmlite ^
    --exclude-module panel ^
    --exclude-module bokeh ^
    --exclude-module holoviews ^
    --exclude-module datashader ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] El empaquetado fallo. Mira los mensajes arriba.
    pause
    exit /b 1
)

REM --- Post-build: copiar archivos user-facing AL LADO del .exe ---
REM    (no a _internal/, asi el usuario los ve en el Explorer)
echo Copiando archivos user-facing al dist/Prototipo1/...
if exist "MANUAL.pdf"   copy /Y "MANUAL.pdf"   "dist\Prototipo1\MANUAL.pdf"   >nul
if exist "ejemplo.room" copy /Y "ejemplo.room" "dist\Prototipo1\ejemplo.room" >nul
if exist "LEEME.txt"    copy /Y "LEEME.txt"    "dist\Prototipo1\LEEME.txt"    >nul

echo.
echo ========================================================
echo  BUILD OK
echo ========================================================
echo.
echo Carpeta lista para copiar al pendrive:
echo   %CD%\dist\Prototipo1\
echo.
echo Contenido user-facing (al lado del .exe):
echo   - Prototipo1.exe        (entry point)
echo   - MANUAL.pdf            (manual completo, 32 paginas)
echo   - ejemplo.room          (sala de muestra)
echo   - LEEME.txt             (instrucciones rapidas)
echo   - _internal\materials\  (19 materiales JSON bundleados)
echo.
echo En cualquier otra PC con Windows:
echo   - Copiar la carpeta "Prototipo1" entera al disco / pendrive
echo   - Doble click en Prototipo1.exe (no hace falta Python)
echo.
pause
endlocal
