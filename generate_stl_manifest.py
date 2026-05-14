"""
generate_stl_manifest.py

Scans a directory for 3D model files (.stl, .3mf, .obj) and writes a
Markdown inventory that ChromaDB can index as plain text.

Usage:
    python generate_stl_manifest.py
    python generate_stl_manifest.py "D:\\My 3D Files"
"""

import os
import sys
from datetime import datetime
from pathlib import Path

EXTENSIONS = {".stl", ".3mf", ".obj"}
OUTPUT_FILE = Path(__file__).parent / "3D_Print_Inventory.md"

DEFAULT_ENV_PATH = Path(__file__).parent / ".env"


def load_env_default() -> str:
    """Pull CHAOTIC_3D_PATH from .env without requiring python-dotenv."""
    if not DEFAULT_ENV_PATH.exists():
        return ""
    for line in DEFAULT_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("CHAOTIC_3D_PATH"):
            _, _, value = line.partition("=")
            return value.strip().strip('"').strip("'")
    return ""


def format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


def scan_directory(root: Path) -> list[dict]:
    entries = []
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames, key=str.lower):
            if Path(filename).suffix.lower() in EXTENSIONS:
                full = Path(dirpath) / filename
                try:
                    size = full.stat().st_size
                except OSError:
                    size = 0
                rel = full.relative_to(root)
                entries.append({
                    "name": filename,
                    "rel_path": str(rel),
                    "size_bytes": size,
                    "ext": full.suffix.lower(),
                    "folder": str(rel.parent) if rel.parent != Path(".") else "(root)",
                })
    return entries


def group_by_folder(entries: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(e["folder"], []).append(e)
    return dict(sorted(groups.items(), key=str.lower))


def ext_label(ext: str) -> str:
    return {".stl": "STL", ".3mf": "3MF", ".obj": "OBJ"}.get(ext, ext.upper())


def write_markdown(root: Path, entries: list[dict]) -> None:
    groups = group_by_folder(entries)
    counts = {".stl": 0, ".3mf": 0, ".obj": 0}
    for e in entries:
        counts[e["ext"]] = counts.get(e["ext"], 0) + 1
    total_bytes = sum(e["size_bytes"] for e in entries)

    lines = [
        "# 3D Print Inventory",
        "",
        f"**Source directory:** `{root}`  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Total models:** {len(entries)}  ",
        (
            f"**Breakdown:** "
            f"{counts['.stl']} STL · "
            f"{counts['.3mf']} 3MF · "
            f"{counts['.obj']} OBJ  "
        ),
        f"**Total size:** {format_size(total_bytes)}",
        "",
        "---",
        "",
    ]

    for folder, items in groups.items():
        lines.append(f"## {folder}")
        lines.append("")
        lines.append("| File | Type | Size |")
        lines.append("|------|------|------|")
        for item in items:
            lines.append(
                f"| `{item['name']}` | {ext_label(item['ext'])} | {format_size(item['size_bytes'])} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "<!-- ChromaDB index target: plain-text model names and paths for semantic retrieval -->",
        "",
        "## Flat name list (for keyword retrieval)",
        "",
    ]
    for e in entries:
        lines.append(f"- {e['name']}  →  {e['rel_path']}")

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    env_default = load_env_default()

    if len(sys.argv) > 1:
        scan_root = Path(sys.argv[1])
    else:
        prompt = f"3D model directory [{env_default or 'enter path'}]: "
        answer = input(prompt).strip()
        scan_root = Path(answer) if answer else Path(env_default)

    if not scan_root.is_dir():
        print(f"[X] Directory not found: {scan_root}")
        sys.exit(1)

    print(f"\n  Scanning: {scan_root}")
    entries = scan_directory(scan_root)

    if not entries:
        print("  No .stl / .3mf / .obj files found.")
        sys.exit(0)

    write_markdown(scan_root, entries)

    stl = sum(1 for e in entries if e["ext"] == ".stl")
    tmf = sum(1 for e in entries if e["ext"] == ".3mf")
    obj = sum(1 for e in entries if e["ext"] == ".obj")
    print(f"  Found: {len(entries)} files  ({stl} STL · {tmf} 3MF · {obj} OBJ)")
    print(f"  Written: {OUTPUT_FILE}")
    print()
    print("  Run the following to index the manifest into ChromaDB:")
    print("    python main.py --index")


if __name__ == "__main__":
    main()
