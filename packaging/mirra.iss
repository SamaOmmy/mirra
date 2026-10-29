; Mirra for Windows: the installer (Inno Setup 6). Built by packaging/build-release.ps1:
;   ISCC.exe /DVersion=0.6.0 /DDist=<the PyInstaller folder> /DOut=<output folder> packaging\mirra.iss
; Installs for the current user only (no administrator rights), into %LOCALAPPDATA%\Programs\Mirra.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Dist
  #define Dist "..\dist\Mirra"
#endif
#ifndef Out
  #define Out "..\release"
#endif

[Setup]
AppId={{6E1F6B8A-3C2D-4B7A-9E51-4D2A7C0F3B11}
AppName=Mirra
AppVersion={#Version}
AppVerName=Mirra {#Version}
AppPublisher=Sama Ommy
AppPublisherURL=https://github.com/SamaOmmy/mirra
AppSupportURL=https://github.com/SamaOmmy/mirra/issues
DefaultDirName={localappdata}\Programs\Mirra
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Out}
OutputBaseFilename=Mirra-for-Windows-Setup
SetupIconFile=mirra.ico
UninstallDisplayIcon={app}\Mirra.exe
UninstallDisplayName=Mirra
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Mirra"; Filename: "{app}\Mirra.exe"; Comment: "Your PC on your phone, and your phone on your PC"
Name: "{autodesktop}\Mirra"; Filename: "{app}\Mirra.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Mirra.exe"; Description: "Open Mirra"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; remove start-at-logon (keeps the settings in %APPDATA%\SamanthaScreenMirror)
Filename: "{app}\samantha-mirror.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAutostart"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Before files are replaced: stop Mirra (the background service and the window) so nothing is locked.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssInstall then
  begin
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "SamanthaScreenMirror"', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM samantha-mirror-service.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Mirra.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
  if CurStep = ssPostInstall then
    // already set up before (an update): start it again; a first install is set up in the window
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/Run /TN "SamanthaScreenMirror"', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;
