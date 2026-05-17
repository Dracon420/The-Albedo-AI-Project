; albedo.iss  --  Inno Setup 6 configuration for Albedo Mission Control
;
; Compile with Inno Setup 6 (free):  https://jrsoftware.org/isinfo.php
;   iscc.exe albedo.iss
;
; Output: Output\Albedo-Setup.exe  (~50 MB compressed)
;
; What this installer does:
;   1. Verifies Python 3.12 is installed (required pre-condition)
;   2. Copies all project source files to the chosen directory
;   3. Runs setup_utility.py post-install (pip, .env, shortcut, Ollama pull)
;   4. Creates an Albedo Mission Control shortcut on the Desktop

; ── Build metadata ─────────────────────────────────────────────────────────
#define AppName      "Albedo"
#define AppFullName  "Albedo Mission Control"
#define AppVersion   "1.3.0"
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

; Force 64-bit install path (C:\Program Files\Albedo, not the x86 folder)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppFullName}
AllowNoIcons=yes

; Require admin so we can write to Program Files and create a global shortcut
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Output
OutputDir=Output
OutputBaseFilename=Albedo-Setup
SetupIconFile=albedo_icon.ico
UninstallDisplayIcon={app}\albedo_icon.ico

; Compression (lzma2 ultra = smallest .exe, slower compile)
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
Name: "desktopicon";  Description: "Create a &Desktop shortcut"; \
  GroupDescription: "Additional icons:"; Flags: checkedonce

[Dirs]
; Ensure the install directory is writable
Name: "{app}"; Permissions: everyone-full

[Files]
; ── Python source ──────────────────────────────────────────────────────────
Source: "albedo\*";             DestDir: "{app}\albedo";            Flags: ignoreversion recursesubdirs createallsubdirs
Source: "albedo-mobile\*";      DestDir: "{app}\albedo-mobile";     Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "node_modules\*,.expo\*"
Source: "tests\*";              DestDir: "{app}\tests";             Flags: ignoreversion recursesubdirs createallsubdirs

; ── Root-level files ───────────────────────────────────────────────────────
Source: "main.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "gui.py";               DestDir: "{app}"; Flags: ignoreversion
Source: "server.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "setup_utility.py";     DestDir: "{app}"; Flags: ignoreversion
Source: "generate_stl_manifest.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "diagnostics.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "swarm.py";                DestDir: "{app}"; Flags: ignoreversion
Source: "memory.py";               DestDir: "{app}"; Flags: ignoreversion
Source: "telemetry.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "operative_dream.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "onboarding.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "system_stats.py";         DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "install.ps1";             DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "logs\*";                  DestDir: "{app}\logs"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "requirements.txt";        DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example";            DestDir: "{app}"; Flags: ignoreversion
Source: "Launch-Albedo.ps1";       DestDir: "{app}"; Flags: ignoreversion
Source: "Albedo-Maintenance.ps1";  DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";               DestDir: "{app}"; Flags: ignoreversion
Source: "CLAUDE.md";               DestDir: "{app}"; Flags: ignoreversion

; ── Docs folder ────────────────────────────────────────────────────────────
Source: "docs\*";               DestDir: "{app}\docs";              Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Background images (user-selectable in Settings) ───────────────────────
Source: "Albedo-mission-control-background-1.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-2.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-3.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "albedo-mission-control-background-4.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Branding assets ────────────────────────────────────────────────────────
Source: "albedo_logo.png";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Piper TTS binary (bundled in repo under piper/) ───────────────────────
Source: "piper\*";              DestDir: "{app}\piper";             Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Piper voice models (downloaded by setup_utility.py; include if present) ─
Source: "voices\*";             DestDir: "{app}\voices";            Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Vosk STT model (downloaded by setup_utility.py; bundle if cached) ────
Source: "vosk_models\*";        DestDir: "{app}\vosk_models";       Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── OpenWakeWord models ────────────────────────────────────────────────────
Source: "wakewords\*";          DestDir: "{app}\wakewords";         Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; ── Icon (optional -- installer skips gracefully if absent) ───────────────
Source: "albedo_icon.ico";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Exactly ONE Start Menu entry — launch only.
Name: "{group}\{#AppFullName}";         Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; Comment: "Launch Albedo Spartan-Class AI"

; Exactly ONE Desktop shortcut (task-gated — only when user selects the option).
Name: "{userdesktop}\{#AppFullName}";   Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Launch-Albedo.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\albedo_icon.ico"; IconIndex: 0; Tasks: desktopicon; Comment: "Launch Albedo Spartan-Class AI"

[Run]
; Run the setup wizard after files are copied.
;
; Key flags:
;   postinstall     -- shows as a checkbox on the Finish page (pre-checked)
;   runasoriginaluser -- runs as the logged-in user, not the elevated admin
;                        context, so py.exe is found on the user's PATH
;   NOT nowait      -- installer waits for the wizard to exit before closing;
;                      nowait was the original bug (wizard was killed on exit)
; pyw -3.12 uses pythonw.exe (windowless) — no console window or taskbar
; entry appears. PowerShell is no longer needed as the intermediary.
Filename: "pyw.exe"; \
  Parameters: "-3.12 ""{app}\setup_utility.py"""; \
  WorkingDir: "{app}"; \
  Description: "Run Albedo Setup Wizard (install Python packages, configure .env, pull AI model)"; \
  Flags: postinstall runasoriginaluser; \
  StatusMsg: "Launching Albedo Setup Wizard..."

[UninstallRun]
; On uninstall: kill the GUI window, then remove the .lnk
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM pythonw.exe"; \
  Flags: runhidden skipifdoesntexist

[UninstallDelete]
; Scorch protocol: wipe all runtime-generated content then the directory itself.
; filesandordirs on {app}\* removes everything the installer did not track
; (chroma_db, .venv, __pycache__, .env, voices, logs, etc.).
; dirifempty on {app} then removes the now-empty installation folder.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\chroma_db"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files;          Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty;     Name: "{app}"

; Desktop shortcut scorch — destroys both the Inno-managed shortcut and the
; rogue 'Albedo Mission Control.lnk' written by setup_utility.py, regardless
; of which user profile received it (admin install vs. per-user install).
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
