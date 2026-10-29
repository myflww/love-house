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

[Code]
const
  WebView2Client = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Page = 'https://developer.microsoft.com/microsoft-edge/webview2/';

function WebView2Present(): Boolean;
begin
  { Same per-user and per-machine registrations the app itself checks. }
  Result :=
    RegKeyExists(HKEY_CURRENT_USER, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2Client) or
    RegKeyExists(HKEY_LOCAL_MACHINE, 'Software\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2Client) or
    RegKeyExists(HKEY_LOCAL_MACHINE, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2Client);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { Nothing is downloaded or installed silently: the user decides, then we only
    open Microsoft's official page. }
  if (CurStep = ssPostInstall) and (not WebView2Present()) then
  begin
    if MsgBox('这台电脑还没有微软 WebView2 运行时，爱之屋需要它才能显示界面。' + #13#10 + #13#10 +
              '是否现在打开微软官方下载页？安装后重新打开爱之屋即可，记忆数据不受影响。',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', WebView2Page, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;
