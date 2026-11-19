; 로컬 AI 작업실 — 개인 PC용 설치 파일 (Inno Setup 6)
; build_desktop_installer.py 가 {#AppVer}, {#Stage}, {#OutDir} 를 넘겨 컴파일한다.
#ifndef AppVer
  #define AppVer "0.0.0"
#endif

[Setup]
AppId={{6F3C2A91-7B4E-4D2A-9C1F-3E8B5A7D2C40}
AppName=로컬 AI 작업실
AppVersion={#AppVer}
AppVerName=로컬 AI 작업실 {#AppVer}
AppPublisher=로컬 AI 작업실
DefaultDirName={sd}\LocalAIWorkspace
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=LocalAIWorkspace-Setup-{#AppVer}
SetupIconFile={#Stage}\app.ico
UninstallDisplayIcon={app}\app.ico
UninstallDisplayName=로컬 AI 작업실
Compression=lzma2/normal
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
CloseApplications=no
RestartIfNeededByRun=no

[Languages]
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
ko.WelcomeLabel2=내 PC 안에서만 동작하는 AI 업무 도구를 설치합니다.%n%n설치 중 인터넷으로 Ollama(언어 모델 실행기)와 언어 모델(PC 메모리에 맞춰 5~17GB)을 받습니다. 인터넷 속도에 따라 수십 분 걸릴 수 있습니다.%n%n필요한 것: Windows 10/11 64비트, 메모리 16GB 이상(32GB 권장), 디스크 여유 30GB 이상.
ko.FinishedLabel=설치가 끝났습니다. 바탕화면의 '로컬 AI 작업실' 아이콘을 누르면 브라우저에서 열립니다.

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userdesktop}\로컬 AI 작업실"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\start.vbs"""; IconFilename: "{app}\app.ico"; Comment: "로컬 AI 작업실 열기"
Name: "{userprograms}\로컬 AI 작업실\로컬 AI 작업실"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\start.vbs"""; IconFilename: "{app}\app.ico"
Name: "{userprograms}\로컬 AI 작업실\작업실 종료"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\stop.vbs"""; IconFilename: "{app}\app.ico"
Name: "{userprograms}\로컬 AI 작업실\설치 다시 시도"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\install-desktop.ps1"" -InstallDir ""{app}"""; IconFilename: "{app}\app.ico"
Name: "{userprograms}\로컬 AI 작업실\사용 가이드"; Filename: "{app}\docs\사용_가이드.md"
Name: "{userprograms}\로컬 AI 작업실\로컬 AI 작업실 제거"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\install-desktop.ps1"" -InstallDir ""{app}"""; StatusMsg: "Ollama와 언어 모델을 받는 중입니다. 새로 뜬 창에서 진행 상황을 확인하세요(창을 닫지 마세요)…"; Flags: waituntilterminated
Filename: "{sys}\wscript.exe"; Parameters: """{app}\setup\start.vbs"""; Description: "지금 로컬 AI 작업실 열기"; Flags: postinstall nowait skipifsilent; Check: InstallOk

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\stop.ps1"" -Quiet"; Flags: runhidden waituntilterminated; RunOnceId: "StopWorkspace"

[UninstallDelete]
; 설치 후 생긴 캐시·기록. 내가 만든 결과물(app\outputs)과 지식보관함(app\chroma_db)은 남겨 둔다.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\hf"
Type: filesandordirs; Name: "{app}\setup"
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.log.err"
Type: files; Name: "{app}\app\model.json"
Type: files; Name: "{app}\app\last_metrics.json"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: dirifempty; Name: "{app}\app"
Type: dirifempty; Name: "{app}"

[Code]
function InstallOk: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\setup\install_ok'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  StopScript: String;
begin
  { 업데이트 설치: 실행 중인 작업실을 먼저 꺼야 파일을 덮어쓸 수 있음 }
  if CurStep = ssInstall then
  begin
    StopScript := ExpandConstant('{app}\setup\stop.ps1');
    if FileExists(StopScript) then
      Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + StopScript + '" -Quiet', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
