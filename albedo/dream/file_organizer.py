r"""
dream/file_organizer.py — Dream-cycle file organization (SUGGEST-FIRST).

Scans configured directories and categorizes files by extension (fast,
deterministic) with an optional Ollama AI pass for ambiguous types.

⚠ BEHAVIOUR CHANGE (Session 9): the dream cycle NO LONGER moves files
autonomously. Past runs over-organized and relocated files that shouldn't have
been touched, eroding trust. Now organize() defaults to SUGGEST-ONLY: it
proposes moves and writes them to a pending-suggestions file. Nothing on disk
changes until the user explicitly approves at the start of the next session via
apply_suggestions(). The user decides — not the dream cycle.

  - SUGGEST by default — no filesystem changes during the dream cycle
  - IN-PLACE by default — a loose file is foldered into a category subfolder
    WITHIN its own area (Downloads/photo.jpg -> Downloads/Images/photo.jpg).
    Files never leave their top-level area. (Past versions relocated everything
    into one central tree, which over-organized and was painful to undo.)
  - NEVER deletes anything — moves only happen on explicit user approval
  - NEVER touches system dirs, .git, .venv, or Program Files
  - Skips files already in an organized location
  - Handles name collisions by appending _1, _2, etc.
  - Every approved move is recorded in a reversible manifest

Workflow
--------
    1. Dream cycle calls organize()                  -> writes pending suggestions
    2. Next session start surfaces get_pending_suggestions() to the user
    3. User approves -> apply_suggestions()          -> moves happen
       User declines -> discard_suggestions()        -> nothing moved, cleared

Configuration (.env)
--------------------
    DREAM_SCAN_DIRS      Semicolon-separated list of dirs to scan
                         Default: %USERPROFILE%\Desktop;%USERPROFILE%\Downloads
    DREAM_TARGET_ROOT    Where organized folders are created
                         Default: %USERPROFILE%\Documents\Albedo-Organized
    DREAM_AI_CLASSIFY    1 = use Ollama for ambiguous files, 0 = skip (default 0)
    DREAM_AUTO_APPLY     1 = legacy behaviour (move during dream, NO approval).
                         Default 0 (suggest-only). Opt-in escape hatch only.
"""
from __future__ import annotations

import json
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
    # Opt-in central-tree mode only (set DREAM_TARGET_ROOT). The DEFAULT behaviour
    # is in-place foldering — files stay inside their own scan area.
    return Path.home() / "Documents" / "Albedo-Organized"


def _category_subpath(category: str, scan_dir: Path) -> str:
    """
    Strip a leading category segment that duplicates the scan area's own name so
    in-place foldering doesn't produce ugly doubled nesting.

    e.g. a loose .pdf inside 'Documents' has category 'Documents/PDFs'. In-place,
    the destination would be 'Documents/Documents/PDFs/...'. We strip the leading
    'Documents' so it becomes 'Documents/PDFs/...'. A .pdf in 'Downloads' keeps the
    full 'Documents/PDFs' (-> 'Downloads/Documents/PDFs/...'), which reads sensibly.
    """
    parts = category.split("/")
    if parts and parts[0].lower() == scan_dir.name.lower():
        parts = parts[1:]
    return "/".join(parts)


def _in_place_dest(src: Path, category: str, scan_dir: Path) -> Path:
    """
    Compute an IN-PLACE destination: a category subfolder WITHIN the file's own
    scan area. The file never leaves its top-level area (Downloads stays in
    Downloads, Documents in Documents). If stripping leaves an empty subpath
    (file already belongs at the area root), keep it where it is by returning the
    same parent (caller treats src==dest.parent as a no-op skip).
    """
    sub = _category_subpath(category, scan_dir)
    base = scan_dir / sub if sub else scan_dir
    return base / src.name


# Pending move suggestions live in the project root so the next session can
# find and surface them. JSON list of {src, dest, category, timestamp}.
_PENDING_FILE = Path(__file__).resolve().parent.parent.parent / "dream_pending_moves.json"


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


def _plan_moves(
    scan_dirs:   Optional[list[str]] = None,
    target_root: Optional[str]       = None,
    interrupt:   Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> list[MoveRecord]:
    """
    Scan + categorize files and build a list of PROPOSED moves. Pure planning —
    touches nothing on disk (no mkdir, no move). Returns proposed MoveRecords.
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

    # Destination mode:
    #   - DEFAULT (in-place): files are foldered into a category subfolder WITHIN
    #     their own scan area. Nothing leaves Downloads/Documents/etc.
    #   - OPT-IN (central tree): if DREAM_TARGET_ROOT env or target_root arg is set,
    #     fall back to the legacy behaviour of moving everything under one root.
    raw_target = os.environ.get("DREAM_TARGET_ROOT", "")
    central_target: Optional[Path] = (
        Path(raw_target) if raw_target
        else (Path(target_root) if target_root else None)
    )
    in_place = central_target is None

    mode_label = "in-place" if in_place else f"central -> {central_target}"
    _prog(f"Recon pass - scanning {len(resolved_scan)} director(ies) [{mode_label}]", 0.0)

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

    _prog(f"Located {len(all_files)} file(s). Planning organization.", 0.05)

    proposed: list[MoveRecord] = []
    ai_classify = os.environ.get("DREAM_AI_CLASSIFY", "0").strip() == "1"

    for i, src in enumerate(all_files):
        if _interrupted():
            _prog(f"Planning interrupted at {i}/{len(all_files)} files.", i / len(all_files))
            break

        frac = 0.05 + 0.90 * (i / len(all_files))
        ext  = src.suffix.lower()
        cat  = _EXT_MAP.get(ext)

        if cat == "_SKIP" or cat is None and not ai_classify:
            cat = "Misc" if cat is None else None

        if cat == "_SKIP" or cat is None:
            continue

        if cat is None and ai_classify:
            cat = _ai_classify(src) or "Misc"

        # Plan only — do NOT mkdir or move. Note the intended destination;
        # collision-safe naming is resolved at apply time against the live FS.
        if in_place:
            # src.parent IS the scan area (scan is non-recursive via iterdir()).
            dest = _in_place_dest(src, cat, src.parent)
            # Already at the right place (no category subpath) — skip, no move.
            if dest.parent == src.parent:
                continue
            # Already inside its own category subfolder — skip defensively.
            if src.parent == dest.parent and src.parent.name.lower() == cat.split("/")[-1].lower():
                continue
        else:
            dest = (central_target / cat) / src.name

        proposed.append(MoveRecord(src, dest, cat))

        if i % 20 == 0:
            _prog(f"Planning… {i}/{len(all_files)}", frac)

    _prog(f"Planning complete — {len(proposed)} suggestion(s).", 1.0)
    return proposed


def organize(
    scan_dirs:   Optional[list[str]] = None,
    target_root: Optional[str]       = None,
    interrupt:   Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> list[MoveRecord]:
    """
    Dream-cycle entry point. SUGGEST-ONLY by default.

    Plans proposed moves and writes them to the pending-suggestions file for the
    user to approve next session. Returns the proposed MoveRecords WITHOUT
    moving anything.

    Legacy auto-move is gated behind DREAM_AUTO_APPLY=1 (opt-in escape hatch) —
    when set, it plans then immediately applies, preserving old behaviour for
    anyone who explicitly wants it.
    """
    proposed = _plan_moves(scan_dirs, target_root, interrupt, progress_cb)

    if not proposed:
        save_suggestions([])
        return []

    if os.environ.get("DREAM_AUTO_APPLY", "0").strip() == "1":
        print("[file_organizer] DREAM_AUTO_APPLY=1 — applying moves immediately.")
        applied = apply_suggestions(proposed)
        save_suggestions([])
        return applied

    save_suggestions(proposed)
    print(f"[file_organizer] {len(proposed)} move(s) SUGGESTED — awaiting user "
          f"approval next session (nothing moved). See {_PENDING_FILE.name}.")
    return proposed


# ---------------------------------------------------------------------------
# Suggestion persistence + apply/discard (user-controlled)
# ---------------------------------------------------------------------------

def save_suggestions(records: list[MoveRecord]) -> None:
    """Write pending move suggestions to disk for next-session review."""
    try:
        payload = {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "count": len(records),
            "moves": [r.as_dict() for r in records],
        }
        _PENDING_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[file_organizer] Could not write suggestions: {exc}")


def get_pending_suggestions() -> list[dict]:
    """Return the pending move suggestions (list of dicts), or [] if none."""
    try:
        if not _PENDING_FILE.exists():
            return []
        data = json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
        return data.get("moves", [])
    except Exception:
        return []


def has_pending_suggestions() -> bool:
    return bool(get_pending_suggestions())


def discard_suggestions() -> int:
    """User declined. Clear pending suggestions without moving anything.
    Returns how many were discarded."""
    pending = get_pending_suggestions()
    try:
        if _PENDING_FILE.exists():
            _PENDING_FILE.unlink()
    except Exception as exc:
        print(f"[file_organizer] Could not clear suggestions: {exc}")
    print(f"[file_organizer] Discarded {len(pending)} suggestion(s) — nothing moved.")
    return len(pending)


def apply_suggestions(records: Optional[list] = None) -> list[MoveRecord]:
    """
    Execute moves the user approved. Accepts either a list of MoveRecord (from a
    fresh plan) or, if None, loads the pending suggestions from disk.

    This is the ONLY place files actually move. Collision-safe destination names
    are resolved here against the live filesystem. Clears the pending file when
    done. Returns the MoveRecords actually applied.
    """
    # Normalize input to (src, dest_dir/category, name) tuples
    if records is None:
        raw = get_pending_suggestions()
        items = [(Path(r["src"]), Path(r["dest"]), r.get("category", "Misc")) for r in raw]
    else:
        items = [(r.src, r.dest, r.category) for r in records]

    applied: list[MoveRecord] = []
    for src, dest, cat in items:
        if not src.exists():
            print(f"[file_organizer] Skipped (gone): {src}")
            continue
        if _is_protected(src):
            continue
        try:
            dest_dir = dest.parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dest = _safe_dest(dest_dir, src.name)
            shutil.move(str(src), str(final_dest))
            applied.append(MoveRecord(src, final_dest, cat))
        except (PermissionError, OSError) as exc:
            print(f"[file_organizer] Skipped {src.name}: {exc}")

    print(f"[file_organizer] Applied {len(applied)} approved move(s).")
    # Clear pending now that they're handled
    try:
        if _PENDING_FILE.exists():
            _PENDING_FILE.unlink()
    except Exception:
        pass
    return applied


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
