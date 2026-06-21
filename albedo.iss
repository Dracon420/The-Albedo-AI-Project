; albedo.iss  --  Inno Setup 6 configuration for Albedo Mission Control
;
; Compile with Inno Setup 6:  iscc.exe albedo.iss
; Output: Output\Albedo-Setup-3.2.2.exe
;
; What's new in 3.2.2 (patch on top of 3.2.1)
;   - 3D Brain visualization fix: crisp lit-sphere nodes + a Fruchterman-Reingold
;     spread layout, so it reads as a Brain-Atlas node cloud instead of the
;     blurry collapsed ball 3.2.1 shipped
;
; What's new in 3.2.1 (feature release on top of 3.2.0)
;   - BRAIN model picker is now a dropdown of known-good models per provider
;     (plus a Custom option) - no more typing exact provider model ids
;   - 3D rotating "Brain Atlas" vault visualization (offline Canvas, no WebGL)
;   - Running-process popup with STOP buttons (critical processes locked);
;     app-usage tracking now matches by install path so far more apps are credited
;   - Apps popup no longer re-opens after you dismiss it; the agent makes one
;     short offer instead of repeating it every turn
;
; What's new in 3.2.0 (feature release on top of 3.1.1)
;   - Performance: parallel specialist team, Ollama keep_alive (model stays
;     resident), tool-result TTL caching, semantic answer cache, and a RAG
;     cross-encoder reranker
;   - Token streaming end-to-end with reading-pace typewriter reveal in chat
;   - Free-provider failover chain (Groq -> Gemini -> Together -> Ollama);
;     paid providers (Azure/OpenAI/Anthropic) are opt-in, never auto-failover
;   - Cyber-HUD overhaul: brain viz (curved dendrites, glowing soma, neuron
;     sparks), enhanced team window, neural-link ACTIVE/READY labels,
;     NET/DISK throughput breakdown gauges, distinct per-window taskbar icons,
;     and an installed-apps inventory popup
;   - Stability: UTF-8 stdout (fixes the cp1252 print crash), cooperative
;     gevent wait (chat no longer freezes the UI), conversation continuity,
;     and incremental dream-cycle indexing (only new/changed files)
;   - New tool: installed-apps inventory + uninstall
;
; Carried over from 3.1.1 (bug-fix release on top of 3.1.0)
;   - Widget telemetry fixed (named-function expose, not inline eel.expose)
;   - FULL screen mode fixed (native Win32 borderless, not requestFullscreen)
;   - Chrome disk-cache disabled so UI updates load after restart
;   - STT keeps ~240ms pre-roll so first syllable is not dropped
;   - "open app" no longer mis-fires the hardware audit
;   - Phone relay responses now delivered (sync websockets send)
;   - Ghost terminal flashes removed (CREATE_NO_WINDOW on subprocess)
;
; Carried over from 3.1.0
;   - R4 fine-tuned models: albedo-cortana-8b + albedo-jarvis-8b
;     (QLoRA rank 64, 15 epochs, Azure T4 â€” replaces R3 baselines)
;   - Mobile companion app: Albedo.apk bundled in mobile\
;   - Fly.io WebSocket relay server bundled in relay\
;   - Safety-catch approval modal wired to Eel UI
;   - Mission Control MOBILE tab (QR pairing, status, unpair)
;   - ChromaDB auto-index fix (auto-populates on first search)
;
; Upgrade behaviour:
;   - Detects existing install via AppId GUID â€” upgrades in-place
;   - Kills running Albedo processes before copying new files
;   - Fresh install  â†’ runs full setup wizard (post_install.ps1)
;   - Upgrade        â†’ runs post_upgrade.ps1 (pip only, no wizard)
;   - User data preserved on both upgrade AND uninstall:
;       .env, settings.json, chroma_db, albedo_memory_db, hardware_config.json

; â”€â”€ Build metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#define AppName      "Albedo"
#define AppFullName  "Albedo Mission Control"
#define AppVersion   "3.2.2"
#define AppPublisher "Chaotic 3D Solutions"
#define AppURL       "https://github.com/Dracon420/The-Albedo-AI-Project"
#define AppExeName   "Launch-Albedo.ps1"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppFullName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Force 64-bit install path
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

DefaultDirName=C:\{#AppName}
DefaultGroupName={#AppFullName}
AllowNoIcons=yes

; Require admin so we can write to C:\Albedo and create a global shortcut
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Output
OutputDir=Output
OutputBaseFilename=Albedo-Setup-3.2.2
SetupIconFile=albedo_icon.ico
UninstallDisplayIcon={app}\albedo_icon.ico
VersionInfoVersion=3.2.2.0
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppFullName}
VersionInfoProductVersion=3.2.2.0

; Compression
Compression=lzma2/max
SolidCompression=yes
InternalCompressLevel=max

; Appearance
WizardStyle=modern
WizardSizePercent=120

; Minimum OS: Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; \
  GroupDescription: "Additional icons:"; Flags: checkedonce

[Dirs]
; Install root â€” writable by all so setup_utility.py can create .venv and .env
Name: "{app}";                    Permissions: everyone-full
; Pre-create runtime dirs with full write access
Name: "{app}\logs";               Permissions: everyone-full
Name: "{app}\vosk_models";        Permissions: everyone-full
Name: "{app}\relay";              Permissions: everyone-full
Name: "{app}\mobile";             Permissions: everyone-full
; User-data dirs: uninsneveruninstall = survived both upgrade AND full uninstall
Name: "{app}\chroma_db";          Permissions: everyone-full; Flags: uninsneveruninstall
Name: "{app}\albedo_memory_db";   Permissions: everyone-full; Flags: uninsneveruninstall

[Files]
; â”€â”€ Python source packages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "albedo\*";             DestDir: "{app}\albedo";            Flags: ignoreversion recursesubdirs createallsubdirs
Source: "training_data\*";      DestDir: "{app}\training_data";     Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "tests\*";              DestDir: "{app}\tests";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Root-level Python files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "main.py";                  DestDir: "{app}"; Flags: ignoreversion
Source: "gui.py";                   DestDir: "{app}"; Flags: ignoreversion
Source: "server.py";                DestDir: "{app}"; Flags: ignoreversion
Source: "setup_utility.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "generate_stl_manifest.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "diagnostics.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "swarm.py";                 DestDir: "{app}"; Flags: ignoreversion
Source: "memory.py";                DestDir: "{app}"; Flags: ignoreversion
Source: "telemetry.py";             DestDir: "{app}"; Flags: ignoreversion
Source: "operative_dream.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "onboarding.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "system_stats.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";         DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example";             DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Launch-Albedo.ps1";        DestDir: "{app}"; Flags: ignoreversion
Source: "Albedo-Maintenance.ps1";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "install.ps1";              DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "VERSION";                  DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";                DestDir: "{app}"; Flags: ignoreversion
Source: "CLAUDE.md";                DestDir: "{app}"; Flags: ignoreversion
Source: "post_install.ps1";         DestDir: "{app}"; Flags: ignoreversion
Source: "post_upgrade.ps1";         DestDir: "{app}"; Flags: ignoreversion
Source: "Albedo-Nuclear-Reset.ps1";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Albedo-Hard-Uninstall.ps1";  DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Albedo-Hard-Uninstall.bat";  DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; â”€â”€ Docs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "docs\*";               DestDir: "{app}\docs";              Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Eel frontend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "web\*";                DestDir: "{app}\web";               Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Fly.io WebSocket relay server â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
; Self-hostable relay for the Albedo mobile app (no Tailscale needed).
; Deploy with: cd C:\Albedo\relay && fly deploy
Source: "relay\*";              DestDir: "{app}\relay";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Mobile companion APK â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
; Sideload Albedo.apk onto an Android phone to use voice/chat remotely.
Source: "mobile\Albedo.apk";   DestDir: "{app}\mobile";            Flags: ignoreversion skipifsourcedoesntexist

; â”€â”€ Background images â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "Albedo-mission-control-background-1.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-2.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-3.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-4.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; â”€â”€ Branding â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "albedo_logo.png";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo_icon.ico";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; â”€â”€ Piper TTS binary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "piper\*";              DestDir: "{app}\piper";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Piper voice models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "voices\*";             DestDir: "{app}\voices";            Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ Vosk STT model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "vosk_models\*";        DestDir: "{app}\vosk_models";       Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; â”€â”€ OpenWakeWord models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Source: "wakewords\*";          DestDir: "{app}\wakewords";         Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
; Start Menu entry
Name: "{group}\{#AppFullName}"; \
  Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; \
  Comment: "Launch Albedo Spartan-Class AI"

; Desktop shortcut (task-gated) â€” uses common desktop to avoid per-user warning
Name: "{commondesktop}\{#AppFullName}"; \
  Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; \
  Tasks: desktopicon; \
  Comment: "Launch Albedo Spartan-Class AI"

[Run]
; Add Windows Defender exclusion for the install dir
Filename: "powershell.exe"; \
  Parameters: "-NonInteractive -Command ""Add-MpPreference -ExclusionPath '{app}' -ErrorAction SilentlyContinue"""; \
  Flags: runhidden; \
  StatusMsg: "Configuring Windows Defender exclusion..."

; FRESH INSTALL: Run full setup wizard (only when no existing .env found)
Filename: "powershell.exe"; \
  Parameters: "-NonInteractive -ExecutionPolicy Bypass -File ""{app}\post_install.ps1"" -AppDir ""{app}"""; \
  WorkingDir: "{app}"; \
  Flags: runasoriginaluser; \
  StatusMsg: "Launching Albedo Setup Wizard..."; \
  Check: not IsUpgrade

; UPGRADE: Just refresh pip deps silently, skip the wizard
Filename: "powershell.exe"; \
  Parameters: "-NonInteractive -ExecutionPolicy Bypass -File ""{app}\post_upgrade.ps1"" -AppDir ""{app}"""; \
  WorkingDir: "{app}"; \
  Flags: runasoriginaluser; \
  StatusMsg: "Updating Albedo dependencies..."; \
  Check: IsUpgrade

[UninstallRun]
; Kill any running Albedo process before uninstalling
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM pythonw.exe /T"; \
  Flags: runhidden skipifdoesntexist; RunOnceId: "KillPythonw"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM python.exe /T"; \
  Flags: runhidden skipifdoesntexist; RunOnceId: "KillPython"

[UninstallDelete]
; Wipe generated content only â€” user data (chroma_db, albedo_memory_db,
; .env, settings.json, hardware_config.json) is intentionally NOT listed here.
; Those dirs have uninsneveruninstall set in [Dirs], or were never tracked.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\vosk_models"
Type: dirifempty;     Name: "{app}"

; Desktop shortcut cleanup
Type: files; Name: "{commondesktop}\Albedo*.lnk"

; â”€â”€ Code section â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
[Code]
var
  PythonFound: Boolean;

{ Returns the previous install path from registry, or '' if not found }
function GetPreviousInstallPath(): String;
var
  Path: String;
begin
  Path := '';
  { Inno Setup writes InstallLocation to the uninstall key using AppId + '_is1' }
  RegQueryStringValue(HKLM,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1',
    'InstallLocation', Path);
  if Path = '' then
    { Fallback: check the default install dir directly }
    Path := 'C:\Albedo';
  Result := Path;
end;

{ Returns True when an existing Albedo install is detected (.env present).
  Safe to call from InitializeSetup â€” reads registry, no app constant needed. }
function IsUpgrade(): Boolean;
var
  PrevPath: String;
begin
  PrevPath := GetPreviousInstallPath();
  { Remove trailing backslash if present }
  if (Length(PrevPath) > 0) and (PrevPath[Length(PrevPath)] = '\') then
    PrevPath := Copy(PrevPath, 1, Length(PrevPath) - 1);
  Result := FileExists(PrevPath + '\.env');
end;

{ Kill running Albedo processes before files are replaced }
procedure KillRunningAlbedo();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'),
       '/F /IM pythonw.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'),
       '/F /IM python.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    KillRunningAlbedo();
end;

function CheckPython312(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('py.exe', '-3.12 -c "import sys; exit(0)"',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  UpgradeMsg: String;
begin
  PythonFound := CheckPython312();
  if not PythonFound then
  begin
    MsgBox(
      'Python 3.12 is required but was not found on this system.' + #13#10 + #13#10 +
      'Please install Python 3.12 before running this installer:' + #13#10 +
      '  winget install Python.Python.3.12' + #13#10 + #13#10 +
      'Or download from: https://www.python.org/downloads/release/python-3120/' + #13#10 + #13#10 +
      'The installer will now exit.',
      mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

  { Show upgrade notice so the user knows their data is safe }
  if IsUpgrade() then
  begin
    UpgradeMsg :=
      'An existing Albedo installation was detected.' + #13#10 + #13#10 +
      'This installer will upgrade Albedo to v3.2.2.' + #13#10 + #13#10 +
      'What''s new in 3.2.2:' + #13#10 +
      '  - 3D Brain fix: crisp lit-sphere nodes + spread layout' + #13#10 +
      '    (no longer a blurry collapsed ball)' + #13#10 + #13#10 +
      'From 3.2.1:' + #13#10 +
      '  - BRAIN model dropdown, 3D Brain Atlas, process popup' + #13#10 +
      '  - Smarter app-usage tracking; apps popup stops nagging' + #13#10 + #13#10 +
      'Your data will be preserved:' + #13#10 +
      '  - API keys and settings (.env)' + #13#10 +
      '  - Persona settings (settings.json)' + #13#10 +
      '  - Memory database (albedo_memory_db)' + #13#10 +
      '  - File catalog (chroma_db)' + #13#10 + #13#10 +
      'Continue with the upgrade?';
    if MsgBox(UpgradeMsg, mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  Result := True;
end;

