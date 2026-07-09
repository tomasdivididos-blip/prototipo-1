@echo off
setlocal
cd /d "%~dp0"

REM --- Buscar Python de Anaconda ---
set "PYEXE="
if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PYEXE=%USERPROFILE%\anaconda3\python.exe"
) else if exist "%USERPROFILE%\miniconda3\python.exe" (
    set "PYEXE=%USERPROFILE%\miniconda3\python.exe"
) else if exist "%PROGRAMDATA%\anaconda3\python.exe" (
    set "PYEXE=%PROGRAMDATA%\anaconda3\python.exe"
)

if "%PYEXE%"=="" (
    echo [ERROR] No se encontro Anaconda. Instalala desde https://www.anaconda.com/
    pause
    exit /b 1
)

echo Usando Python: %PYEXE%
echo.

REM --- Asegurar dependencias (rapido si ya estan) ---
"%PYEXE%" -c "import PyQt5, pyqtgraph, OpenGL, numpy" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias faltantes...
    "%PYEXE%" -m pip install pyqtgraph PyOpenGL
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion.
        pause
        exit /b 1
    )
)

REM --- Ejecutar la app (reenvia argumentos, p.ej. una ruta a .room) ---
echo === Iniciando Prototipo 1 ===
echo.
"%PYEXE%" main.py %*
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo La app salio con codigo %EXITCODE%.
    pause
)

endlocal
