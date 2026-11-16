; Inno Setup 6 script for the Ostium Windows x64 client.
; Build with: ISCC.exe deploy\windows\ostium.iss /DAppVersion=0.1.6
#ifndef AppVersion
  #define AppVersion "0.1.6"
#endif

[Setup]
AppId={{7A5E6D2A-9C1B-4C38-9E6D-2C0B5A9F4E11}
AppName=Ostium
AppVersion={#AppVersion}
AppPublisher=Ostium Contributors
AppPublisherURL=https://github.com/ThzxxArt/Ostium
AppSupportURL=https://github.com/ThzxxArt/Ostium/issues
DefaultDirName={autopf}\Ostium
DefaultGroupName=Ostium
SetupIconFile=..\..\assets\brand\ostium.ico
OutputDir=..\..\dist\windows
OutputBaseFilename=Ostium-{#AppVersion}-windows-x64-setup
LicenseFile=..\..\LICENSE
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Ostium
VersionInfoCompany=Ostium Contributors
VersionInfoDescription=Ostium Windows client
AppCopyright=GPL-3.0-or-later
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayIcon={app}\ostium.exe

[Files]
Source: "..\..\dist\windows\Ostium\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Code]
function IsInteractiveInstall(): Boolean;
begin
  Result := not WizardSilent;
end;

function IsSilentInstall(): Boolean;
begin
  Result := WizardSilent;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Stop the service and the UI before Inno copies the new bundle.  Both
    executables are locked while running; the UI holds ostium.exe open even
    when the service is already stopped. }
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-Service -Name OstiumCore -ErrorAction SilentlyContinue | Stop-Service -Force -ErrorAction SilentlyContinue; Get-Process ostium,ostium-service,sing-box -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  { The new UI migrates the database on first start.  Keep a quiescent copy
    (including WAL and the master key) so an operator can roll back to the
    previous release without hitting a newer-schema error.  The client
    database lives in the user-writable UI data directory, not in the
    privileged core's ProgramData\OstiumCore tree. }
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "$d=Join-Path $env:ProgramData ''Ostium''; if(Test-Path (Join-Path $d ''ostium.db'')){$s=Join-Path $d (''pre-upgrade-''+(Get-Date -Format ''yyyyMMdd-HHmmss'')); New-Item -ItemType Directory -Force -Path $s | Out-Null; foreach($f in @(''ostium.db'',''ostium.db-wal'',''ostium.db-shm'',''master.key'')){$p=Join-Path $d $f; if(Test-Path $p){Copy-Item $p $s}}}"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

[Icons]
Name: "{group}\Ostium"; Filename: "{app}\ostium.exe"; Parameters: "open"
Name: "{group}\Ostium Console"; Filename: "http://127.0.0.1:8787"
Name: "{group}\Uninstall Ostium"; Filename: "{uninstallexe}"

[Run]
; Interactive installs show the PowerShell console so service startup and the
; 8787 health check are visible in real time.  Silent installs stay hidden.
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"""; Flags: waituntilterminated; StatusMsg: "Installing Ostium services..."; Check: IsInteractiveInstall
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated; StatusMsg: "Installing Ostium services..."; Check: IsSilentInstall
Filename: "http://127.0.0.1:8787"; Description: "Open Ostium"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated
