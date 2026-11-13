; Inno Setup 6 script for the Ostium Windows x64 client.
; Build with: ISCC.exe deploy\windows\ostium.iss /DAppVersion=0.1.1
#ifndef AppVersion
  #define AppVersion "0.1.1"
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

[Icons]
Name: "{group}\Ostium"; Filename: "{app}\ostium.exe"; Parameters: "open"
Name: "{group}\Uninstall Ostium"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated; StatusMsg: "Installing Ostium services..."

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated
