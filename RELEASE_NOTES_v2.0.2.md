## Highlights

**Vosk speech engine now loads reliably on a clean install.** This release fixes the cascade of path, Defender, and config-loading bugs that prevented the bundled STT model from being recognized by Vosk's Kaldi backend on first launch.

**Install location changed: `C:\Program Files\Albedo` → `C:\Albedo`** (no spaces — required for Kaldi compatibility). Existing 2.0.x installs should uninstall the old location before installing this build.

## What's Fixed

### Vosk model loading
- Install path moved to `C:\Albedo` so the Kaldi C++ backend can read the model directory (spaces in paths broke it silently)
- Windows Defender exclusion for `C:\Albedo` is added automatically by the installer **before** the setup wizard runs, so the bundled and downloaded model files are no longer quarantined
- `.env` is now loaded from an absolute path derived from `config.py`'s own file location instead of the current working directory — so paths resolve correctly no matter how the app is launched (shortcut, terminal, installer post-step)
- `.env` is written with forward-slash paths so python-dotenv stops interpreting `\v`, `\n`, `\t` etc. inside Windows backslash paths (this silently corrupted `VOSK_MODEL_PATH` and made the downloader try to save to the root of C:\)
- `.env.example`'s empty `VOSK_MODEL_PATH=` no longer overrides the config default with an empty string
- `setup_utility.py` writes `.env` before vosk download so a vosk hiccup never leaves the install without a working config
- Setup wizard validates `python.exe` existence in `.venv`, not just the directory, so a half-created venv gets recreated instead of being skipped

### GUI
- HUD polling (CPU/RAM/disk/GPU) moved off the main tkinter thread — eliminates 200ms freezes when switching windows
- GPUtil replaced with a direct `nvidia-smi` subprocess using `CREATE_NO_WINDOW` so there are no more ghost terminal flashes
- `_bg_pil` access guarded — fixes an `AttributeError` when a `<Configure>` event fires before `__init__` completes
- In-app UPDATE button now downloads the GitHub release zip and replaces files in-place instead of opening the browser

### Setup wizard
- `customtkinter` package assets are verified after pip install and force-reinstalled if the icon file is missing
- Right-click paste menu added to the Node Location field

### Uninstaller
- `{app}\*` wildcard removed from `[UninstallDelete]` so the running `unins000.exe` is no longer competing with its own deletion list during uninstall

## Install

1. Download `Albedo-Setup.exe` below
2. Run as administrator (you'll see a SmartScreen warning — click **More info** → **Run anyway**)
3. The installer creates a Defender exclusion, copies files, and launches the setup wizard
4. The wizard installs Python dependencies, downloads voice models, configures `.env`, and pulls the Ollama LLM
5. Launch Albedo from the desktop shortcut

## Upgrading from 2.0.1

The install location moved from `C:\Program Files\Albedo` to `C:\Albedo`. Uninstall the previous version from Settings → Apps before running this installer. Your `.env` and downloaded models will need to be reconfigured (or use the bundled Defender-safe defaults).
