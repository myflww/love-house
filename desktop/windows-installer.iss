#ifndef AppVersion
  #define AppVersion "0.5.1rc1"
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
function RuntimeCommand(Arguments: String): Boolean;
var
  ResultCode: Integer;
begin
  { The same packaged x64 Loader probe is used by setup and the application.
    A registry key alone cannot establish whether the Runtime can be loaded. }
  ResultCode := -1;
  Result := Exec(ExpandConstant('{app}\LoveHouse.exe'), Arguments,
                 ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not RuntimeCommand('--runtime-status')) then
  begin
    { Setup's prerequisite is disclosed in WINDOWS-README before installation.
      Portable repair always requires the explicit --repair-runtime action.
      This process remains per-user: never elevate the Microsoft installer. }
    if not WizardSilent then
      if MsgBox('爱之屋未能加载微软 WebView2 运行时，界面需要此组件。' + #13#10 + #13#10 +
                '是否安装随包提供、经过微软签名和 SHA256 验证的 Evergreen x64 运行时？' + #13#10 +
                '组件遵守微软许可，无需管理员权限。现有记忆数据不会被删除。',
                mbConfirmation, MB_YESNO) <> IDYES then
        RaiseException('WebView2 修复已取消。安装尚未完成，可重新运行安装器继续，记忆数据已保留。');
    if not RuntimeCommand('--repair-runtime') then
      RaiseException('微软 WebView2 修复失败。请运行 LoveHouse.exe --diagnose 检查安全诊断，记忆数据已保留。');
    { Never treat an installer exit code alone as proof of runtime availability. }
    if not RuntimeCommand('--runtime-status') then
      RaiseException('修复后仍无法加载 WebView2。安装尚未完成，请查看安全诊断；记忆数据已保留。');
  end;
end;
