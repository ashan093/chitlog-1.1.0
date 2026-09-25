Unicode True

!ifndef PROJECT_ROOT
  !error "PROJECT_ROOT must be supplied by packaging/build_installer.ps1"
!endif

!define APP_NAME "ChitLog"
!define APP_VERSION "1.1.0"
!define APP_PUBLISHER "Ashan Madusanka"
!define APP_EXE "ChitLog.exe"
!define APP_ID "ChitLog.AshanMadusanka"
!define APP_REG_KEY "Software\${APP_ID}"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"

; Mixed-mode installer:
; - Current user (recommended): no machine-wide install, defaults to LocalAppData.
; - All users: administrator approval is required and defaults to Program Files.
; This avoids a raw file-write failure when a user intentionally chooses Program Files.
!define MULTIUSER_EXECUTIONLEVEL Highest
!define MULTIUSER_MUI
!define MULTIUSER_INSTALLMODE_COMMANDLINE
!define MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER
!define MULTIUSER_USE_PROGRAMFILES64
!define MULTIUSER_INSTALLMODE_FUNCTION ChitLogInstallModeChanged
!define MULTIUSER_INSTALLMODEPAGE_TEXT_TOP "Choose who can use ChitLog on this computer. The current-user option is recommended and needs no machine-wide installation. The all-users option installs under Program Files and requires administrator approval."
!define MULTIUSER_INSTALLMODEPAGE_TEXT_CURRENTUSER "Install for me only (recommended)"
!define MULTIUSER_INSTALLMODEPAGE_TEXT_ALLUSERS "Install for all users (administrator required)"
!define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME

!include "LogicLib.nsh"
!include "MultiUser.nsh"
!include "MUI2.nsh"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${PROJECT_ROOT}\release\ChitLog-${APP_VERSION}-Setup.exe"
SetCompressor zlib
SetDatablockOptimize on
CRCCheck on

Icon "${PROJECT_ROOT}\assets\chit.ico"
UninstallIcon "${PROJECT_ROOT}\assets\chit.ico"

VIProductVersion "1.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "ChitLog"
VIAddVersionKey /LANG=1033 "ProductVersion" "1.1.0"
VIAddVersionKey /LANG=1033 "FileVersion" "1.1.0"
VIAddVersionKey /LANG=1033 "CompanyName" "Ashan Madusanka"
VIAddVersionKey /LANG=1033 "FileDescription" "ChitLog Installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright © 2026 Ashan Madusanka. All rights reserved."

!define MUI_ABORTWARNING
!define MUI_LICENSEPAGE_CHECKBOX
!define MUI_LICENSEPAGE_CHECKBOX_TEXT "I accept the ChitLog End-User License Agreement"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}\EULA.txt"
!insertmacro MULTIUSER_PAGE_INSTALLMODE
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
    !insertmacro MULTIUSER_INIT
FunctionEnd

Function un.onInit
    !insertmacro MULTIUSER_UNINIT
FunctionEnd

; Use ChitLog's established per-user location by default, while giving an
; all-users install a normal Program Files default. A previously chosen custom
; folder is remembered independently in HKCU/HKLM through SHCTX.
Function ChitLogInstallModeChanged
    ReadRegStr $0 SHCTX "${APP_REG_KEY}" "InstallDir"
    ${If} $0 != ""
        StrCpy $INSTDIR "$0"
        Return
    ${EndIf}

    ${If} $MultiUser.InstallMode == "AllUsers"
        StrCpy $INSTDIR "$PROGRAMFILES64\ChitLog"
    ${Else}
        StrCpy $INSTDIR "$LOCALAPPDATA\Programs\ChitLog"
    ${EndIf}
FunctionEnd

Section "ChitLog application" SEC_MAIN
    SectionIn RO
    SetOutPath "$INSTDIR"
    File /r "${PROJECT_ROOT}\dist\ChitLog\*"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    CreateDirectory "$SMPROGRAMS\ChitLog"
    CreateShortcut "$SMPROGRAMS\ChitLog\ChitLog.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
    CreateShortcut "$SMPROGRAMS\ChitLog\Uninstall ChitLog.lnk" "$INSTDIR\Uninstall.exe"

    WriteRegStr SHCTX "${APP_REG_KEY}" "InstallDir" "$INSTDIR"
    WriteRegStr SHCTX "${APP_REG_KEY}" "InstallMode" "$MultiUser.InstallMode"
    WriteRegStr SHCTX "${UNINST_KEY}" "DisplayName" "ChitLog"
    WriteRegStr SHCTX "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr SHCTX "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr SHCTX "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
    WriteRegStr SHCTX "${UNINST_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\" /$MultiUser.InstallMode'
    WriteRegStr SHCTX "${UNINST_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /$MultiUser.InstallMode /S'
    WriteRegDWORD SHCTX "${UNINST_KEY}" "NoModify" 1
    WriteRegDWORD SHCTX "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section /o "Desktop shortcut" SEC_DESKTOP
    CreateShortcut "$DESKTOP\ChitLog.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

Section "Uninstall"
    Delete "$DESKTOP\ChitLog.lnk"
    Delete "$SMPROGRAMS\ChitLog\ChitLog.lnk"
    Delete "$SMPROGRAMS\ChitLog\Uninstall ChitLog.lnk"
    RMDir "$SMPROGRAMS\ChitLog"

    ; User finance data is intentionally stored outside $INSTDIR and is not
    ; removed by the uninstaller. Only installed application files are removed.
    RMDir /r "$INSTDIR"

    DeleteRegKey SHCTX "${UNINST_KEY}"
    DeleteRegKey SHCTX "${APP_REG_KEY}"
SectionEnd
