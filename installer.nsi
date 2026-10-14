; NSIS Installer Script para Prototipo 1
; Instalar NSIS desde: https://nsis.sourceforge.io/
;
; Pre-requisitos: correr `python build_installer.py` primero (PyInstaller ONEFILE)
; para generar `dist\Prototipo 1.exe`. Despues `makensis installer.nsi`.
;
; v2.66: adaptado al build ONEFILE (un solo ejecutable "Prototipo 1.exe", con
; espacio). Antes (v2.12) esperaba el layout --onedir `dist\Prototipo1\` con exe
; "Prototipo1.exe" sin espacio, que el build onefile actual no produce.

!include "MUI2.nsh"
!include "x64.nsh"

; ---------- Definiciones ----------
Name "Prototipo 1 - Modelador 3D de Recintos"
OutFile "Prototipo1_Installer.exe"
InstallDir "$PROGRAMFILES64\Prototipo1"
InstallDirRegKey HKLM "Software\Prototipo1" "InstallDir"

; Requiere permisos de administrador (escribe en Program Files + Registry)
RequestExecutionLevel admin

; ---------- MUI Settings ----------
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "English"

; ---------- Installer Section ----------
Section "Instalar Prototipo 1"
  SetOutPath "$INSTDIR"

  ; Build ONEFILE: un solo ejecutable (con espacio) + manual + sala de ejemplo.
  File "dist\Prototipo 1.exe"
  File "MANUAL.md"
  File "ejemplo.room"

  ; Shortcuts en menu Inicio
  CreateDirectory "$SMPROGRAMS\Prototipo1"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Prototipo 1.lnk" \
                  "$INSTDIR\Prototipo 1.exe"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Manual.lnk" \
                  "$INSTDIR\MANUAL.md"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Desinstalar.lnk" \
                  "$INSTDIR\uninstall.exe"

  ; Shortcut en escritorio
  CreateShortCut "$DESKTOP\Prototipo 1.lnk" "$INSTDIR\Prototipo 1.exe"

  ; Registry: para que aparezca en "Programas y caracteristicas"
  WriteRegStr HKLM "Software\Prototipo1" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "DisplayName" "Prototipo 1 - Modelador 3D"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "DisplayVersion" "2.66"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "Publisher" "Prototipo 1"

  ; Generador del desinstalador
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ---------- Uninstaller Section ----------
Section "Uninstall"
  ; Borrar el contenido del InstallDir (recursivo)
  RMDir /r "$INSTDIR"

  ; Borrar shortcuts
  Delete "$SMPROGRAMS\Prototipo1\Prototipo 1.lnk"
  Delete "$SMPROGRAMS\Prototipo1\Manual.lnk"
  Delete "$SMPROGRAMS\Prototipo1\Desinstalar.lnk"
  RMDir  "$SMPROGRAMS\Prototipo1"
  Delete "$DESKTOP\Prototipo 1.lnk"

  ; Borrar entradas de registro
  DeleteRegKey HKLM "Software\Prototipo1"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1"
SectionEnd
