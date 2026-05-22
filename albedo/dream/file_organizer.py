"""
dream/file_organizer.py — Autonomous file organization during dream cycle.

Scans configured directories, categorizes files by extension (fast, deterministic)
with an optional Ollama AI pass for ambiguous types, then moves them into an
organized folder structure.  Safety rules:
  - NEVER deletes anything — only moves
  - NEVER touches system dirs, .git, .venv, or Program Files
  - Skips files that are already in an organized location
  - Handles name collisions by appending _1, _2, etc.
  - Writes a move manifest so every action is reversible

Configuration (.env)
--------------------
    DREAM_SCAN_DIRS      Semicolon-separated list of dirs to scan
                         Default: %USERPROFILE%\Desktop;%USERPROFILE%\Downloads
    DREAM_TARGET_ROOT    Where organized folders are created
                         Default: %USERPROFILE%\Documents\Albedo-Organized
    DREAM_AI_CLASSIFY    1 = use Ollama for ambiguous files, 0 = skip (default 0)
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Extension → folder mapping  (deterministic, zero model calls)
# ---------------------------------------------------------------------------

_EXT_MAP: dict[str, str] = {
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".webp": "Images", ".tiff": "Images", ".tif": "Images",
    ".svg": "Images", ".ico": "Images", ".heic": "Images", ".raw": "Images",
    ".cr2": "Images", ".nef": "Images",
    # Documents
    ".pdf": "Documents/PDFs",
    ".docx": "Documents", ".doc": "Documents", ".odt": "Documents",
    ".rtf": "Documents", ".pages": "Documents",
    ".xlsx": "Documents/Spreadsheets", ".xls": "Documents/Spreadsheets",
    ".csv": "Documents/Spreadsheets", ".ods": "Documents/Spreadsheets",
    ".pptx": "Documents/Presentations", ".ppt": "Documents/Presentations",
    ".key": "Documents/Presentations",
    ".txt": "Documents/Text", ".md": "Documents/Notes",
    ".rst": "Documents/Notes", ".log": "Documents/Logs",
    # Video
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos", ".mov": "Videos",
    ".wmv": "Videos", ".flv": "Videos", ".webm": "Videos", ".m4v": "Videos",
    ".mpg": "Videos", ".mpeg": "Videos",
    # Audio
    ".mp3": "Audio/Music", ".flac": "Audio/Music", ".aac": "Audio/Music",
    ".ogg": "Audio/Music", ".wma": "Audio/Music", ".m4a": "Audio/Music",
    ".wav": "Audio/Recordings", ".opus": "Audio",
    # Code
    ".py": "Code/Python", ".pyw": "Code/Python", ".ipynb": "Code/Python",
    ".js": "Code/Web", ".ts": "Code/Web", ".jsx": "Code/Web",
    ".tsx": "Code/Web", ".html": "Code/Web", ".htm": "Code/Web",
    ".css": "Code/Web", ".scss": "Code/Web",
    ".cpp": "Code", ".c": "Code", ".h": "Code", ".hpp": "Code",
    ".cs": "Code", ".java": "Code", ".go": "Code", ".rs": "Code",
    ".rb": "Code", ".php": "Code", ".lua": "Code",
    ".sh": "Code/Scripts", ".ps1": "Code/Scripts", ".bat": "Code/Scripts",
    ".json": "Code/Config", ".yaml": "Code/Config", ".yml": "Code/Config",
    ".toml": "Code/Config", ".ini": "Code/Config", ".cfg": "Code/Config",
    ".xml": "Code/Config",
    # 3D Printing
    ".stl": "3D_Printing/STLs", ".3mf": "3D_Printing/Models",
    ".obj": "3D_Printing/Models", ".gcode": "3D_Printing/GCode",
    ".step": "3D_Printing/CAD", ".stp": "3D_Printing/CAD",
    ".f3d": "3D_Printing/CAD", ".blend": "3D_Printing/CAD",
    # Archives
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
    ".tar": "Archives", ".gz": "Archives", ".bz2": "Archives",
    ".xz": "Archives", ".zst": "Archives",
    # Installers / disk images
    ".exe": "Installers", ".msi": "Installers", ".iso": "Installers",
    ".img": "Installers", ".dmg": "Installers",
    # Data / ML
    ".onnx": "AI_Models", ".gguf": "AI_Models", ".bin": "AI_Models",
    ".safetensors": "AI_Models", ".pkl": "Data", ".parquet": "Data",
    ".db": "Data", ".sqlite": "Data", ".sql": "Data",
    # Fonts
    ".ttf": "Fonts", ".otf": "Fonts", ".woff": "Fonts", ".woff2": "Fonts",
    # Shortcuts / metadata — skip these
    ".lnk": "_SKIP", ".url": "_SKIP", ".desktop": "_SKIP",
    ".tmp": "_SKIP", ".bak": "_SKIP",
}

# Directories that must never be touched regardless of config
_PROTECTED = {
    "windows", "program files", "program files (x86)",
    "programdata", "system32", ".venv", "venv", ".git",
    "node_modules", "__pycache__", "appdata",
    "albedo-organized",   # don't re-organize our own output
}


def _is_protected(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return bool(parts & _PROTECTED)


def _safe_dest(dest_dir: Path, filename: str) -> Path:
    """Return a non-colliding destination path, appending _1, _2, ... as needed."""
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _default_scan_dirs() -> list[Path]:
    home = Path.home()
    return [home / "Desktop", home / "Downloads"]


def _default_target_root() -> Path:
    return Path.home() / "Documents" / "Albedo-Organized"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class MoveRecord:
    __slots__ = ("src", "dest", "category", "timestamp")

    def __init__(self, src: Path, dest: Path, category: str) -> None:
        self.src       = src
        self.dest      = dest
        self.category  = category
        self.timestamp = datetime.now().isoformat(timespec="seconds")

    def as_dict(self) -> dict:
        return {
            "src":       str(self.src),
            "dest":      str(self.dest),
            "category":  self.category,
            "timestamp": self.timestamp,
        }


def organize(
    scan_dirs:   Optional[list[str]] = None,
    target_root: Optional[str]       = None,
    interrupt:   Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> list[MoveRecord]:
    """
    Scan directories, categorize, and move files into organized sub-folders.

    Parameters
    ----------
    scan_dirs   : directories to scan (reads DREAM_SCAN_DIRS env var, or defaults)
    target_root : root for organized output (reads DREAM_TARGET_ROOT, or default)
    interrupt   : callable returning True when the dream cycle should stop early
    progress_cb : called with (status_message, fraction_0_to_1) during processing

    Returns a list of MoveRecord (the move manifest).
    """
    def _prog(msg: str, frac: float) -> None:
        if progress_cb:
            progress_cb(msg, frac)
        print(f"[file_organizer] {msg} ({frac*100:.0f}%)")

    def _interrupted() -> bool:
        return interrupt is not None and interrupt()

    # Resolve directories
    raw_scan = os.environ.get("DREAM_SCAN_DIRS", "")
    resolved_scan: list[Path] = (
        [Path(p.strip()) for p in raw_scan.split(";") if p.strip()]
        if raw_scan else
        (([Path(d) for d in scan_dirs] if scan_dirs else _default_scan_dirs()))
    )
    resolved_scan = [p for p in resolved_scan if p.exists() and not _is_protected(p)]

    raw_target = os.environ.get("DREAM_TARGET_ROOT", "")
    target = Path(raw_target) if raw_target else (
        Path(target_root) if target_root else _default_target_root()
    )

    _prog(f"Recon pass — scanning {len(resolved_scan)} director(ies)", 0.0)

    # Collect all files
    all_files: list[Path] = []
    for d in resolved_scan:
        try:
            for f in d.iterdir():
                if f.is_file() and not _is_protected(f):
                    all_files.append(f)
        except PermissionError:
            print(f"[file_organizer] Permission denied: {d}")

    if not all_files:
        _prog("No files found in scan directories.", 1.0)
        return []

    _prog(f"Located {len(all_files)} file(s). Beginning organization.", 0.05)

    moves: list[MoveRecord] = []
    ai_classify = os.environ.get("DREAM_AI_CLASSIFY", "0").strip() == "1"

    for i, src in enumerate(all_files):
        if _interrupted():
            _prog(f"Dream interrupted at {i}/{len(all_files)} files.", i / len(all_files))
            break

        frac = 0.05 + 0.90 * (i / len(all_files))
        ext  = src.suffix.lower()
        cat  = _EXT_MAP.get(ext)

        if cat == "_SKIP" or cat is None and not ai_classify:
            # Unknown extension and AI assist disabled — move to Misc
            cat = "Misc" if cat is None else None

        if cat == "_SKIP" or cat is None:
            continue

        # AI classification for truly unknown types
        if cat is None and ai_classify:
            cat = _ai_classify(src) or "Misc"

        dest_dir = target / cat
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = _safe_dest(dest_dir, src.name)
            shutil.move(str(src), str(dest))
            moves.append(MoveRecord(src, dest, cat))
        except (PermissionError, OSError) as exc:
            print(f"[file_organizer] Skipped {src.name}: {exc}")

        if i % 20 == 0:
            _prog(f"Organizing… {i}/{len(all_files)}", frac)

    _prog(f"Organization complete — {len(moves)} file(s) moved.", 1.0)
    return moves


def _ai_classify(path: Path) -> Optional[str]:
    """Ask local Ollama to classify a file by name/extension. Best-effort."""
    try:
        import httpx
        base  = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
        prompt = (
            f"You are a file classifier. Given only the filename below, "
            f"reply with exactly ONE category from this list: "
            f"Documents, Images, Videos, Audio, Code, Archives, "
            f"3D_Printing, Installers, Data, Misc. "
            f"Reply with only the category name, nothing else.\n\n"
            f"Filename: {path.name}"
        )
        r = httpx.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=10,
        )
        if r.status_code == 200:
            cat = r.json().get("response", "").strip().split()[0]
            if cat in ("Documents", "Images", "Videos", "Audio", "Code",
                       "Archives", "3D_Printing", "Installers", "Data", "Misc"):
                return cat
    except Exception:
        pass
    return None
