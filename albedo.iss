; albedo.iss  --  Inno Setup 6 configuration for Albedo Mission Control
;
; Compile with Inno Setup 6:  iscc.exe albedo.iss
; Output: Output\Albedo-Setup-3.1.0.exe
;
; Upgrade behaviour:
;   - Detects existing install via AppId GUID — upgrades in-place
;   - Kills running Albedo processes before copying new files
;   - Fresh install  → runs full setup wizard (setup_utility.py)
;   - Upgrade        → runs setup_utility.py --upgrade (pip only, no wizard)
;   - User data preserved on both upgrade AND uninstall:
;       .env, settings.json, chroma_db, albedo_memory_db, hardware_config.json
;   - .venv, logs, __pycache__ cleaned on full uninstall only

; ── Build metadata ─────────────────────────────────────────────────────────
#define AppName      "Albedo"
#define AppFullName  "Albedo Mission Control"
#define AppVersion   "2.0.8"
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
OutputBaseFilename=Albedo-Setup-2.0.8
SetupIconFile=albedo_icon.ico
UninstallDisplayIcon={app}\albedo_icon.ico

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
; Install root — writable by all so setup_utility.py can create .venv and .env
Name: "{app}";                    Permissions: everyone-full
; Pre-create runtime dirs with full write access
Name: "{app}\logs";               Permissions: everyone-full
Name: "{app}\vosk_models";        Permissions: everyone-full
; User-data dirs: uninsneveruninstall = survived both upgrade AND full uninstall
Name: "{app}\chroma_db";          Permissions: everyone-full; Flags: uninsneveruninstall
Name: "{app}\albedo_memory_db";   Permissions: everyone-full; Flags: uninsneveruninstall
Name: "{app}\albedo-mobile";      Permissions: everyone-full; Flags: uninsneveruninstall

[Files]
; ── Python source packages ─────────────────────────────────────────────────
Source: "albedo\*";             DestDir: "{app}\albedo";            Flags: ignoreversion recursesubdirs createallsubdirs
Source: "training_data\*";      DestDir: "{app}\training_data";     Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "tests\*";              DestDir: "{app}\tests";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Root-level Python files ────────────────────────────────────────────────
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
Source: "post_install.ps1";          DestDir: "{app}"; Flags: ignoreversion
Source: "post_upgrade.ps1";          DestDir: "{app}"; Flags: ignoreversion
Source: "Albedo-Nuclear-Reset.ps1";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Albedo-Hard-Uninstall.ps1";  DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Albedo-Hard-Uninstall.bat";  DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Docs ───────────────────────────────────────────────────────────────────
Source: "docs\*";               DestDir: "{app}\docs";              Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Eel frontend ───────────────────────────────────────────────────────────
Source: "web\*";                DestDir: "{app}\web";               Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Background images ──────────────────────────────────────────────────────
Source: "Albedo-mission-control-background-1.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-2.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-3.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-4.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Branding ───────────────────────────────────────────────────────────────
Source: "albedo_logo.png";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo_icon.ico";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Piper TTS binary ───────────────────────────────────────────────────────
Source: "piper\*";              DestDir: "{app}\piper";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Piper voice models ─────────────────────────────────────────────────────
Source: "voices\*";             DestDir: "{app}\voices";            Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Vosk STT model ─────────────────────────────────────────────────────────
Source: "vosk_models\*";        DestDir: "{app}\vosk_models";       Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── OpenWakeWord models ────────────────────────────────────────────────────
Source: "wakewords\*";          DestDir: "{app}\wakewords";         Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
; Start Menu entry
Name: "{group}\{#AppFullName}"; \
  Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; \
  Comment: "Launch Albedo Spartan-Class AI"

; Desktop shortcut (task-gated) — uses common desktop to avoid per-user warning
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
; Wipe generated content only — user data (chroma_db, albedo_memory_db,
; .env, settings.json, hardware_config.json) is intentionally NOT listed here.
; Those dirs have uninsneveruninstall set in [Dirs], or were never tracked.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\vosk_models"
Type: dirifempty;     Name: "{app}"

; Desktop shortcut cleanup
Type: files; Name: "{commondesktop}\Albedo*.lnk"

; ── Code section ──────────────────────────────────────────────────────────
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
  Safe to call from InitializeSetup — reads registry, no app constant needed. }
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
      'This installer will upgrade Albedo to v2.0.8.' + #13#10 + #13#10 +
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
