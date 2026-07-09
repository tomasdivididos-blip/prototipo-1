; NSIS Installer Script para Prototipo 1
; Instalar NSIS desde: https://nsis.sourceforge.io/
;
; Pre-requisitos: correr build.bat primero para generar dist\Prototipo1\
; Despues correr build_installer.bat (o makensis installer.nsi).
;
; Arreglado v2.12: usa File /r para bundlear el dist/ entero (PyInstaller
; --onedir produce muchos archivos, no solo el .exe). El installer.nsi
; viejo apuntaba a "dist\Prototipo 1.exe" (con espacio) y "recinto.room"
; que nunca existieron en este build.

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

  ; Bundle recursivo del dist/Prototipo1/ entero:
  ;   Prototipo1.exe + _internal\* (DLLs, Python embebido, materiales)
  ;   + MANUAL.pdf + ejemplo.room + LEEME.txt (copiados por build.bat)
  File /r "dist\Prototipo1\*"

  ; Shortcuts en menu Inicio
  CreateDirectory "$SMPROGRAMS\Prototipo1"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Prototipo 1.lnk" \
                  "$INSTDIR\Prototipo1.exe"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Manual.lnk" \
                  "$INSTDIR\MANUAL.pdf"
  CreateShortCut "$SMPROGRAMS\Prototipo1\Desinstalar.lnk" \
                  "$INSTDIR\uninstall.exe"

  ; Shortcut en escritorio
  CreateShortCut "$DESKTOP\Prototipo 1.lnk" "$INSTDIR\Prototipo1.exe"

  ; Registry: para que aparezca en "Programas y caracteristicas"
  WriteRegStr HKLM "Software\Prototipo1" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "DisplayName" "Prototipo 1 - Modelador 3D"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Prototipo1" \
                    "DisplayVersion" "2.12"
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
