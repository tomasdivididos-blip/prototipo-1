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
REM   --exclude-module botocore / panel / bokeh / numba / llvmlite /
REM     QtWebEngine* (v2.21): ~370 MB de peso muerto que Anaconda arrastra y el
REM     proyecto no toca (SDK de AWS, dashboards, JIT, navegador embebido).
REM     Lo que QUEDA y no se puede sacar sin romper nada: los mkl_*.dll
REM     (~370 MB, el BLAS de numpy/scipy; son variantes de despacho por CPU y
REM     sacarlas rompe en maquinas con otro juego de instrucciones) y
REM     gmsh-4.15.dll (~86 MB, el mallador boundary-fitted opcional).
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
    --exclude-module PyQt5.QtWebEngineWidgets ^
    --exclude-module PyQt5.QtWebEngineCore ^
    --exclude-module PyQt5.QtWebEngine ^
    --exclude-module PyQt5.QtWebKit ^
    --exclude-module PyQt5.QtWebKitWidgets ^
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
