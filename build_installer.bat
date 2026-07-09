@echo off
REM Script para generar el instalador de Prototipo 1
REM Ejecuta: build_installer.bat

echo.
echo ========================================
echo   Generador de Instalador
echo   Prototipo 1 - Modelador 3D
echo ========================================
echo.

REM Verificar si Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no está instalado o no está en el PATH
    echo.
    echo Descarga Python desde: https://www.python.org/downloads/
    echo Asegúrate de marcar "Add Python to PATH" durante la instalación
    pause
    exit /b 1
)

echo [OK] Python encontrado
echo.

REM Instalar PyInstaller si no está disponible
echo [1/3] Verificando PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo     Instalando PyInstaller...
    pip install pyinstaller
)
echo [OK] PyInstaller listo
echo.

REM Ejecutar el script Python
echo [2/3] Generando ejecutable...
python build_installer.py
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la generación del ejecutable
    pause
    exit /b 1
)
echo.

REM Verificar si NSIS está instalado
echo [3/3] Verificando NSIS para el instalador...
where makensis >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ADVERTENCIA] NSIS no está instalado
    echo              El ejecutable fue creado correctamente
    echo.
    echo Para crear un instalador profesional, instala NSIS desde:
    echo   https://nsis.sourceforge.io/Download
    echo.
    echo Luego ejecuta este script nuevamente
) else (
    echo [OK] NSIS encontrado
    echo     Generando instalador...
    makensis installer.nsi
)

echo.
echo ========================================
echo   ✓ Proceso completado
echo ========================================
echo.
echo El ejecutable está en: dist\Prototipo 1.exe
echo.
pause
