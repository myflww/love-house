#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\windows\LoveHouse"
#endif
#ifndef OutputDirPath
  #define OutputDirPath "..\dist\release"
#endif
[Setup]
AppId={{7F5DB656-A910-4565-BE08-262FCF043DCE}
AppName=爱之屋
AppVersion={#AppVersion}
AppPublisher=myflww
AppPublisherURL=https://github.com/myflww/love-house
AppSupportURL=https://github.com/myflww/love-house/issues
DefaultDirName={localappdata}\Programs\LoveHouse
DefaultGroupName=爱之屋
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDirPath}
OutputBaseFilename=LoveHouse-Setup-{#AppVersion}-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#BundleDir}\LoveHouse.ico
UninstallDisplayIcon={app}\LoveHouse.exe
LicenseFile={#BundleDir}\LICENSE
InfoBeforeFile={#BundleDir}\WINDOWS-README.txt
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\爱之屋"; Filename: "{app}\LoveHouse.exe"
Name: "{autodesktop}\爱之屋"; Filename: "{app}\LoveHouse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LoveHouse.exe"; Description: "Open Love House"; Flags: nowait postinstall skipifsilent unchecked

; Personal memories live outside {app}, in %LOCALAPPDATA%\LoveHouse.
; Uninstall removes installed program files only. It never deletes that directory.
