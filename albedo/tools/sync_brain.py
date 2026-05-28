"""
albedo/tools/sync_brain.py - Sync live project state to Claude's Brain vault.

IMPORTANT: This writes to CLAUDE_BRAIN_PATH (Claude's personal memory vault),
NOT to OBSIDIAN_VAULT_PATH (Albedo's RAG vault). They are separate:

  CLAUDE_BRAIN_PATH   = C:/Users/demon/Desktop/Claudes Brain/Claude_Brain
                        Claude Code reads/writes here to stay coherent across
                        compacted sessions. Never used by Albedo's RAG.

  OBSIDIAN_VAULT_PATH = C:/Users/demon/Desktop/Albedo Project Brain
                        Albedo's working vault. ChromaDB RAG, dream cycle
                        output. Claude does NOT write here.

Writes / overwrites two files in CLAUDE_BRAIN_PATH/Albedo/:
  08_Live_State.md    -- runtime state (Ollama models, keys, packages, chroma)
  10_Code_Snapshot.md -- public API snapshot of key files for cross-referencing

Run manually: python -m albedo.tools.sync_brain
"""
from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent

# Files whose public API is captured in 10_Code_Snapshot.md
_KEY_FILES = [
    "albedo/audio/tts.py",
    "albedo/audio/stt.py",
    "albedo/audio/azure_speech.py",
    "albedo/audio/xtts_engine.py",
    "albedo/audio/capture.py",
    "albedo/audio/wakeword.py",
    "albedo/web/azure_openai_client.py",
    "swarm.py",
    "albedo/pipeline.py",
    "albedo/eel_app/bridge.py",
    "albedo/eel_app/app.py",
    "albedo/config.py",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(cwd or _ROOT), timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


_CLAUDE_BRAIN = Path(r"C:/Users/demon/Desktop/Claudes Brain/Claude_Brain")


def _vault_path() -> Path | None:
    """
    Returns the path to CLAUDE'S BRAIN vault -- NOT OBSIDIAN_VAULT_PATH.
    OBSIDIAN_VAULT_PATH is Albedo's RAG vault and must not be written to here.
    """
    # Explicit override via CLAUDE_BRAIN_PATH env var
    override = os.environ.get("CLAUDE_BRAIN_PATH", "").strip()
    if override:
        p = Path(override)
        return p if p.exists() else None
    # Fixed location the user set up
    return _CLAUDE_BRAIN if _CLAUDE_BRAIN.exists() else None


# ---------------------------------------------------------------------------
# 08_Live_State.md generators
# ---------------------------------------------------------------------------

def _ollama_models() -> str:
    raw = _run(["ollama", "list"])
    return raw if raw else "Ollama not reachable or not installed"


def _key_status() -> str:
    keys = [
        ("GEMINI_API_KEY",        "Gemini"),
        ("GROQ_API_KEY",          "Groq"),
        ("TOGETHER_API_KEY",      "Together AI"),
        ("TAVILY_API_KEY",        "Tavily search"),
        ("WOLFRAM_API_KEY",       "Wolfram Alpha"),
        ("AZURE_SPEECH_KEY",      "Azure Speech TTS+STT"),
        ("AZURE_OPENAI_KEY",      "Azure OpenAI"),
        ("XTTS_VOICE_SAMPLE",     "XTTS voice sample"),
        ("DEEPGRAM_API_KEY",      "Deepgram STT"),
        ("OBSIDIAN_VAULT_PATH",   "Obsidian vault RAG"),
    ]
    rows = []
    for env_key, label in keys:
        val = os.environ.get(env_key, "").strip()
        status = "[SET]" if val else "[ ]"
        rows.append(f"| {label} | {status} |")
    return "\n".join(rows)


def _optional_packages() -> str:
    packages = [
        ("azure.cognitiveservices.speech",
         "Azure Speech SDK (`pip install azure-cognitiveservices-speech`)"),
        ("TTS",
         "XTTS-v2 / Coqui TTS (`pip install TTS`)"),
        ("openai",
         "Azure OpenAI / OpenAI (`pip install openai`)"),
        ("groq",
         "Groq SDK (`pip install groq`)"),
        ("edge_tts",
         "Edge-TTS (`pip install edge-tts`)"),
        ("vosk",
         "Vosk STT (`pip install vosk`)"),
        ("kokoro_onnx",
         "Kokoro ONNX (`pip install kokoro-onnx`)"),
        ("together",
         "Together AI (`pip install together`)"),
        ("google.genai",
         "Google GenAI (`pip install google-genai`)"),
    ]
    rows = []
    for mod, label in packages:
        try:
            __import__(mod)
            status = "[installed]"
        except ImportError:
            status = "[ ]"
        rows.append(f"| {label} | {status} |")
    return "\n".join(rows)


def _chroma_info() -> str:
    try:
        import chromadb
        db_path = os.environ.get(
            "CHROMA_DB_PATH",
            str(_ROOT / "chroma_db"),
        )
        client = chromadb.PersistentClient(path=db_path)
        collections = client.list_collections()
        if not collections:
            return "ChromaDB: no collections yet"
        lines = [f"  - {c.name}: {c.count()} documents" for c in collections]
        return "\n".join(lines)
    except Exception as exc:
        return f"ChromaDB not available: {exc}"


def _git_log() -> str:
    raw = _run(["git", "log", "--oneline", "-8"])
    return raw if raw else "(git log unavailable)"


def _env_selectors() -> str:
    selectors = [
        ("AUDIO_TTS",    "piper"),
        ("AUDIO_STT",    "vosk"),
        ("ALBEDO_UI",    "eel"),
        ("OLLAMA_MODEL", "albedo-cortana-8b"),
    ]
    rows = [
        f"| {key} | `{os.environ.get(key, default)}` |"
        for key, default in selectors
    ]
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# 10_Code_Snapshot.md generators
# ---------------------------------------------------------------------------

def _extract_signatures(filepath: Path) -> str:
    """
    Parse a Python file with AST and extract all top-level and class-level
    function/method definitions with their signatures and first-line docstring.
    Returns a markdown code block per function.
    """
    if not filepath.exists():
        return f"  (file not found: {filepath})\n"

    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"  (syntax error: {exc})\n"

    lines = []

    def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Reconstruct a compact signature string from the AST node."""
        args = node.args
        parts = []
        # positional args (with defaults right-aligned)
        n_defaults = len(args.defaults)
        n_args     = len(args.args)
        for i, arg in enumerate(args.args):
            default_idx = i - (n_args - n_defaults)
            annotation = (
                ast.unparse(arg.annotation) if arg.annotation else ""
            )
            a = arg.arg
            if annotation:
                a += f": {annotation}"
            if default_idx >= 0:
                a += f" = {ast.unparse(args.defaults[default_idx])}"
            parts.append(a)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        for kw in args.kwonlyargs:
            parts.append(kw.arg)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        ret = ""
        if node.returns:
            ret = f" -> {ast.unparse(node.returns)}"
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(parts)}){ret}"

    def _docline(node) -> str:
        """Return first line of docstring or empty string."""
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            first = node.body[0].value.value.strip().split("\n")[0]
            return f"  # {first}"
        return ""

    # Only top-level and class-level functions (direct children of module/class body)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not node.name.startswith("_w_"):
                continue
            lines.append(f"  {_sig(node)}{_docline(node)}")
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("__") and item.name != "__init__":
                        continue
                    lines.append(f"  {node.name}.{_sig(item)}{_docline(item)}")

    return "\n".join(lines) if lines else "  (no public functions found)"


def _code_snapshot() -> str:
    """
    Generate a compact snapshot of every key file's public API.
    Claude compares this snapshot against what it sees in the file before
    making edits -- if something that was here is now gone, it's a regression.
    """
    sections = []
    for rel in _KEY_FILES:
        path = _ROOT / rel
        sigs = _extract_signatures(path)
        mtime = ""
        if path.exists():
            import datetime as _dt
            mt = _dt.datetime.fromtimestamp(path.stat().st_mtime)
            mtime = mt.strftime("%Y-%m-%d %H:%M")
        sections.append(
            f"### {rel}  _(modified {mtime})_\n\n"
            f"```python\n{sigs}\n```"
        )
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Write both vault files
# ---------------------------------------------------------------------------

def sync(verbose: bool = True) -> bool:
    vault = _vault_path()
    if vault is None:
        if verbose:
            print("[brain] OBSIDIAN_VAULT_PATH not set or not found -- skipping sync")
        return False

    out_dir = vault / "Albedo"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 08_Live_State.md ────────────────────────────────────────────────────
    live_state = f"""# Albedo -- Live State Snapshot

*Auto-generated by albedo/tools/sync_brain.py*
*Last sync: {now}*

---

## Ollama Models

```
{_ollama_models()}
```

## Engine Selectors (.env)

| Key | Current value |
|-----|--------------|
{_env_selectors()}

## API Keys (set/not-set only -- no values stored)

| Service | Status |
|---------|--------|
{_key_status()}

## Optional Packages

| Package | Status |
|---------|--------|
{_optional_packages()}

## ChromaDB Collections

{_chroma_info()}

## Recent Git Log

```
{_git_log()}
```

---
*Read at the start of each Claude Code session for accurate runtime state.*
"""

    # ── 10_Code_Snapshot.md ─────────────────────────────────────────────────
    code_snap = f"""# Albedo -- Public API Snapshot

*Auto-generated by albedo/tools/sync_brain.py*
*Last sync: {now}*

> CROSS-REFERENCE PROTOCOL
> Before editing any file listed below:
>   1. Read the section for that file here
>   2. Read the section for every file that DEPENDS on it (see 09_File_Dependency_Map.md)
>   3. After editing, run sync_brain again and verify no functions disappeared
>
> If a function is in this snapshot but not in the file after your edit = REGRESSION.
> Fix it before moving on.

---

{_code_snapshot()}

---
*Run `python -m albedo.tools.sync_brain` after any edit to refresh this snapshot.*
"""

    ok = True
    for filename, content in [
        ("08_Live_State.md",   live_state),
        ("10_Code_Snapshot.md", code_snap),
    ]:
        try:
            (out_dir / filename).write_text(content, encoding="utf-8", errors="replace")
            if verbose:
                print(f"[brain] Written -> {out_dir / filename}")
        except Exception as exc:
            if verbose:
                print(f"[brain] Failed to write {filename}: {exc}")
            ok = False

    return ok


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    success = sync(verbose=True)
    sys.exit(0 if success else 1)
