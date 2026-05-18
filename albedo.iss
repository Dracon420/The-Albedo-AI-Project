; albedo.iss  --  Inno Setup 6 configuration for Albedo Mission Control
;
; Compile with Inno Setup 6 (free):  https://jrsoftware.org/isinfo.php
;   iscc.exe albedo.iss
;
; Output: Output\Albedo-Setup.exe
;
; What this installer does:
;   1. Verifies Python 3.12 is installed (required pre-condition)
;   2. Copies all project source files to the chosen directory
;   3. Runs setup_utility.py post-install (pip, .env, shortcut, model download)
;   4. Creates an Albedo Mission Control shortcut on the Desktop

; ── Build metadata ─────────────────────────────────────────────────────────
#define AppName      "Albedo"
#define AppFullName  "Albedo Mission Control"
#define AppVersion   "2.0.2"
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
OutputBaseFilename=Albedo-Setup
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
Name: "{app}";               Permissions: everyone-full
; Pre-create runtime directories with write access so setup wizard can populate them
Name: "{app}\logs";          Permissions: everyone-full
Name: "{app}\vosk_models";   Permissions: everyone-full
Name: "{app}\chroma_db";     Permissions: everyone-full
Name: "{app}\albedo-mobile"; Permissions: everyone-full; Flags: uninsneveruninstall

[Files]
; ── Python source packages ─────────────────────────────────────────────────
Source: "albedo\*";             DestDir: "{app}\albedo";            Flags: ignoreversion recursesubdirs createallsubdirs
Source: "albedo-mobile\*";      DestDir: "{app}\albedo-mobile";     Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Excludes: "node_modules\*,.expo\*"
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

; ── Docs ───────────────────────────────────────────────────────────────────
Source: "docs\*";               DestDir: "{app}\docs";              Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Eel frontend (Phase 2 alpha — HTML/CSS/JS) ─────────────────────────────
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

; ── Vosk STT model (bundled; setup_utility.py validates and re-downloads if bad)
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

; Desktop shortcut (task-gated)
Name: "{userdesktop}\{#AppFullName}"; \
  Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; \
  Tasks: desktopicon; \
  Comment: "Launch Albedo Spartan-Class AI"

[Run]
; Add Windows Defender exclusion for the install dir (runs as admin, before setup wizard).
; Prevents Defender from quarantining vosk model files during install and on first boot.
Filename: "powershell.exe"; \
  Parameters: "-NonInteractive -Command ""Add-MpPreference -ExclusionPath '{app}' -ErrorAction SilentlyContinue"""; \
  Flags: runhidden; \
  StatusMsg: "Configuring Windows Defender exclusion..."

; Run setup wizard after files are copied.
;
;   postinstall     -- checkbox on Finish page (pre-checked)
;   runasoriginaluser -- runs as the logged-in user (not elevated admin)
;                        so py.exe resolves on the user's PATH and the venv
;                        is created with user-accessible permissions
;   pyw -3.12 uses pythonw.exe (windowless) — no console, no taskbar entry
Filename: "pyw.exe"; \
  Parameters: "-3.12 ""{app}\setup_utility.py"""; \
  WorkingDir: "{app}"; \
  Description: "Run Albedo Setup Wizard (install Python packages, configure .env, download AI model)"; \
  Flags: postinstall runasoriginaluser; \
  StatusMsg: "Launching Albedo Setup Wizard..."

[UninstallRun]
; Kill any running Albedo window before uninstalling
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM pythonw.exe"; \
  Flags: runhidden skipifdoesntexist

[UninstallDelete]
; Wipe all runtime-generated content not tracked by the installer.
; Preserves the user's .env if they want to reinstall later — remove
; the .env line below if you want a fully clean uninstall instead.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\chroma_db"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\vosk_models"
Type: filesandordirs; Name: "{app}\logs"
Type: dirifempty;     Name: "{app}"

; Desktop shortcut cleanup (covers both Inno-managed and wizard-written .lnk)
Type: files; Name: "{commondesktop}\Albedo*.lnk"
Type: files; Name: "{userdesktop}\Albedo*.lnk"

; ── Pre-install Python check ───────────────────────────────────────────────
[Code]
var
  PythonFound: Boolean;

function CheckPython312(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('py.exe', '-3.12 -c "import sys; exit(0)"',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
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
  end
  else
    Result := True;
end;

