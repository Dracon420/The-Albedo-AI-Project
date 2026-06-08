"""
tools.py — Albedo Agent Tool Catalog.

The structured tool registry the agent brain (providers.py / agent.py) uses to
achieve OS + knowledge control. Each tool is a clean, PARAMETERIZED Python
function (NOT a regex-on-raw-query parser) plus a JSON-schema description an
LLM can use for native function-calling.

Design
------
- Every tool wraps EXISTING Albedo logic (pipeline handlers, memory, search,
  telemetry, diagnostics). We do NOT reimplement behaviour — we provide clean
  programmatic entry points so an LLM can call them with explicit arguments.
- The original regex handlers in albedo/pipeline.py STAY UNTOUCHED. This module
  is purely additive. Voice/text fast-paths keep working exactly as before.
- Each ToolSpec carries `destructive: bool`. The agent loop routes destructive
  calls through safety_catch's approval modal before executing. (User setting
  "approve everything" can gate non-destructive calls too — that decision lives
  in agent.py, not here.)

Public API
----------
    TOOLS                       -> dict[str, ToolSpec]   (name -> spec)
    get_tool_schemas()          -> list[dict]            (for LLM function-calling)
    get_tool(name)              -> ToolSpec | None
    run_tool(name, **kwargs)    -> str                   (execute, never raises)

Each ToolSpec:
    .name        str
    .description str
    .parameters  dict   (JSON-schema "properties" + "required")
    .destructive bool
    .fn          Callable[..., str]

Tool functions ALWAYS return a human/LLM-readable string and NEVER raise —
errors come back as "[tool error] ..." so the agent can read and react.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # {"properties": {...}, "required": [...]}
    fn: Callable[..., str]
    destructive: bool = False

    def to_schema(self) -> dict:
        """Provider-neutral JSON-schema form (OpenAI/Anthropic both accept this shape)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters.get("properties", {}),
                "required": self.parameters.get("required", []),
            },
        }


# Internal helper for the no-window subprocess flags (suppress CMD flash).
def _no_window_startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


# ---------------------------------------------------------------------------
# Tool implementations — clean parameterized wrappers
# ---------------------------------------------------------------------------

# --- App / process control (reuses pipeline maps + psutil) ------------------

def launch_app(app_name: str) -> str:
    """Launch a program or Windows tool by name."""
    if not app_name or not app_name.strip():
        return "[tool error] launch_app needs a non-empty app_name."
    target = app_name.strip()
    try:
        from albedo.pipeline import _APP_MAP  # canonical name->exe map
        exe = _APP_MAP.get(target.lower(), target)
    except Exception:
        exe = target
    try:
        si = _no_window_startupinfo()
        if exe.endswith(".msc"):
            subprocess.Popen(["mmc", exe], shell=False, startupinfo=si,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", exe], shell=False,
                             startupinfo=si,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Launched {target}."
    except Exception as exc:
        return f"[tool error] Could not launch {target}: {exc}"


def kill_process(name: str) -> str:
    """Terminate all running processes whose name contains the given string."""
    if not name or not name.strip():
        return "[tool error] kill_process needs a non-empty name."
    target = name.strip()
    try:
        import psutil
        killed = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if target.lower() in (proc.info["name"] or "").lower():
                    proc.kill()
                    killed.append(proc.info["name"])
            except Exception:
                pass
        if killed:
            return f"Terminated: {', '.join(sorted(set(killed)))}."
        return f"No running process found matching '{target}'."
    except ImportError:
        return "[tool error] psutil not installed — cannot kill processes."
    except Exception as exc:
        return f"[tool error] Could not terminate '{target}': {exc}"


def list_top_processes(count: int = 8) -> str:
    """List the top N processes by RAM usage."""
    try:
        import psutil
        n = max(1, min(int(count or 8), 30))
        procs = []
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            try:
                mb = p.info["memory_info"].rss / (1024 ** 2)
                cpu = p.info["cpu_percent"] or 0.0
                procs.append((mb, cpu, p.info["name"]))
            except Exception:
                pass
        procs.sort(reverse=True)
        lines = [f"Top {n} processes by RAM:"]
        for mb, cpu, nm in procs[:n]:
            lines.append(f"  {nm:<32} {mb:>7.1f} MB  CPU {cpu:.1f}%")
        return "\n".join(lines)
    except ImportError:
        return "[tool error] psutil not installed — cannot list processes."
    except Exception as exc:
        return f"[tool error] Process list error: {exc}"


# --- Software install (winget, reuses pipeline _WINGET_MAP) ------------------

def download_install(package: str) -> str:
    """Install a program silently via winget by friendly name or winget ID."""
    if not package or len(package.strip()) < 2:
        return "[tool error] download_install needs a package name."
    app_name = package.strip().lower().rstrip(".")
    try:
        from albedo.pipeline import _WINGET_MAP
        pkg_id = _WINGET_MAP.get(app_name, package.strip())
    except Exception:
        pkg_id = package.strip()
    display = package.strip()
    try:
        result = subprocess.run(
            ["winget", "install", "--id", pkg_id, "--exact", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return f"{display} installed successfully."
        if "already installed" in (result.stdout + result.stderr).lower():
            return f"{display} is already installed."
        # Fallback: name search
        result2 = subprocess.run(
            ["winget", "install", display, "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=300,
        )
        if result2.returncode == 0:
            return f"{display} installed successfully."
        return (f"[tool error] winget returned exit {result.returncode} for "
                f"{display}. Package name may be wrong.")
    except FileNotFoundError:
        return ("[tool error] winget not available. Install 'App Installer' "
                "from the Microsoft Store.")
    except subprocess.TimeoutExpired:
        return f"[tool error] Installation of {display} timed out (5 min)."
    except Exception as exc:
        return f"[tool error] Install error: {exc}"


# --- System maintenance (reuses diagnostics._clear_temp) --------------------

def disk_cleanup() -> str:
    """Purge temp files and report freed space."""
    try:
        import sys as _sys
        if str(_ROOT) not in _sys.path:
            _sys.path.insert(0, str(_ROOT))
        from diagnostics import _clear_temp
        mb, skipped = _clear_temp()
        return f"Temp cleanup complete — freed {mb:.1f} MB ({skipped} locked skipped)."
    except Exception as exc:
        return f"[tool error] Cleanup error: {exc}"


def optimize_system(include_registry: bool = False) -> str:
    """Full optimization: temp purge + Windows Disk Cleanup + prefetch clear
    (+ optional CCleaner registry scan if installed)."""
    results: list[str] = []
    # 1. temp
    try:
        import sys as _sys
        if str(_ROOT) not in _sys.path:
            _sys.path.insert(0, str(_ROOT))
        from diagnostics import _clear_temp
        mb, skipped = _clear_temp()
        results.append(f"Temp: freed {mb:.1f} MB ({skipped} locked skipped)")
    except Exception as exc:
        results.append(f"Temp: {exc}")
    # 2. cleanmgr
    try:
        si = _no_window_startupinfo()
        subprocess.run(["cleanmgr.exe", "/sagerun:1"], timeout=120,
                       capture_output=True, startupinfo=si,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        results.append("Disk Cleanup: complete")
    except Exception as exc:
        results.append(f"Disk Cleanup: {exc}")
    # 3. prefetch
    try:
        pf = Path(r"C:\Windows\Prefetch")
        cleared = 0
        for f in pf.glob("*.pf"):
            try:
                f.unlink(); cleared += 1
            except Exception:
                pass
        results.append(f"Prefetch: cleared {cleared} entries")
    except Exception as exc:
        results.append(f"Prefetch: {exc}")
    # 4. registry (optional, CCleaner)
    if include_registry:
        cc = next((p for p in [
            Path(r"C:\Program Files\CCleaner\CCleaner64.exe"),
            Path(r"C:\Program Files (x86)\CCleaner\CCleaner.exe"),
        ] if p.exists()), None)
        if cc:
            try:
                subprocess.run([str(cc), "/AUTO"], timeout=120, capture_output=True)
                results.append("Registry: CCleaner AUTO complete")
            except Exception as exc:
                results.append(f"Registry: {exc}")
        else:
            results.append("Registry: CCleaner not installed (skipped)")
    return "Optimization complete. " + " | ".join(results) + "."


# --- Knowledge / info (reuses memory, search, telemetry) --------------------

def search_web(query: str, max_results: int = 3) -> str:
    """Search the web and return the top result snippets."""
    if not query or not query.strip():
        return "[tool error] search_web needs a query."
    try:
        from albedo.web.search import web_search, format_web_results
        results = web_search(query.strip(), max_results=max(1, min(int(max_results or 3), 8)))
        if results:
            return format_web_results(results)
    except Exception as exc:
        # Fall back to swarm's DDG scraper
        try:
            from swarm import native_web_search
            return native_web_search(query.strip(), max_results=max_results)
        except Exception:
            return f"[tool error] Web search failed: {exc}"
    return "No web results found."


def rag_search(query: str, n_results: int = 3) -> str:
    """Search the local Obsidian/ChromaDB knowledge vault for relevant notes."""
    if not query or not query.strip():
        return "[tool error] rag_search needs a query."
    try:
        from memory import search_memory
        chunks = search_memory(query.strip(), n_results=max(1, min(int(n_results or 3), 8)))
        if chunks:
            return "\n\n".join(f"[{i+1}] {c.strip()}" for i, c in enumerate(chunks))
        return "No relevant local knowledge found."
    except Exception as exc:
        return f"[tool error] RAG search failed: {exc}"


def get_system_telemetry() -> str:
    """Report live CPU/GPU/RAM/disk/temperature telemetry."""
    try:
        from albedo.telemetry import get_full_telemetry
        t = get_full_telemetry()
        cpu = t.get("cpu", {}); gpu = t.get("gpu", {})
        ram = t.get("ram", {}); disk = t.get("disk", {})
        return (
            f"CPU {cpu.get('percent', 0):.0f}% @ {cpu.get('freq_ghz', 0):.1f}GHz | "
            f"GPU {gpu.get('load_percent', 0):.0f}% {gpu.get('temp_c', 0)}°C "
            f"VRAM {gpu.get('vram_used_mb', 0)}/{gpu.get('vram_total_mb', 0)}MB | "
            f"RAM {ram.get('percent', 0):.0f}% "
            f"({ram.get('used_gb', 0):.1f}/{ram.get('total_gb', 0):.1f}GB) | "
            f"Disk C: {disk.get('percent_used_c', 0):.0f}% used"
        )
    except Exception as exc:
        return f"[tool error] Telemetry error: {exc}"


# --- File system (read-only listing + reading; safe by default) -------------

def list_directory(path: str) -> str:
    """List files and folders in a directory."""
    if not path or not path.strip():
        return "[tool error] list_directory needs a path."
    try:
        p = Path(path.strip()).expanduser()
        if not p.exists():
            return f"[tool error] Path does not exist: {p}"
        if not p.is_dir():
            return f"[tool error] Not a directory: {p}"
        entries = []
        for child in sorted(p.iterdir()):
            tag = "DIR " if child.is_dir() else "FILE"
            try:
                size = child.stat().st_size if child.is_file() else 0
            except Exception:
                size = 0
            entries.append(f"  [{tag}] {child.name}" + (f"  ({size} B)" if size else ""))
        if not entries:
            return f"{p} is empty."
        return f"Contents of {p}:\n" + "\n".join(entries[:200])
    except Exception as exc:
        return f"[tool error] list_directory failed: {exc}"


def read_text_file(path: str, max_chars: int = 4000) -> str:
    """Read the text contents of a file (truncated to max_chars)."""
    if not path or not path.strip():
        return "[tool error] read_text_file needs a path."
    try:
        p = Path(path.strip()).expanduser()
        if not p.exists() or not p.is_file():
            return f"[tool error] Not a readable file: {p}"
        data = p.read_text(encoding="utf-8", errors="replace")
        cap = max(200, min(int(max_chars or 4000), 20000))
        if len(data) > cap:
            return data[:cap] + f"\n...[truncated, {len(data)} chars total]"
        return data or "(file is empty)"
    except Exception as exc:
        return f"[tool error] read_text_file failed: {exc}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    TOOLS[spec.name] = spec


_register(ToolSpec(
    name="launch_app",
    description="Launch a program or Windows tool by name (e.g. 'notepad', "
                "'chrome', 'device manager', 'task manager').",
    parameters={"properties": {
        "app_name": {"type": "string", "description": "Program or tool name to launch."}
    }, "required": ["app_name"]},
    fn=launch_app,
    destructive=False,
))

_register(ToolSpec(
    name="kill_process",
    description="Forcibly terminate all running processes whose name contains "
                "the given string. Destructive — closes apps and may lose data.",
    parameters={"properties": {
        "name": {"type": "string", "description": "Process/app name to terminate."}
    }, "required": ["name"]},
    fn=kill_process,
    destructive=True,
))

_register(ToolSpec(
    name="list_top_processes",
    description="List the top N running processes by RAM usage.",
    parameters={"properties": {
        "count": {"type": "integer", "description": "How many to list (default 8, max 30)."}
    }, "required": []},
    fn=list_top_processes,
    destructive=False,
))

_register(ToolSpec(
    name="download_install",
    description="Install a program silently via Windows winget, by friendly "
                "name (e.g. 'vlc', 'firefox') or winget ID. Destructive — "
                "modifies the system by installing software.",
    parameters={"properties": {
        "package": {"type": "string", "description": "Program name or winget package ID."}
    }, "required": ["package"]},
    fn=download_install,
    destructive=True,
))

_register(ToolSpec(
    name="disk_cleanup",
    description="Purge temporary files and report how much space was freed.",
    parameters={"properties": {}, "required": []},
    fn=disk_cleanup,
    destructive=True,
))

_register(ToolSpec(
    name="optimize_system",
    description="Run a full system optimization: temp purge + Windows Disk "
                "Cleanup + prefetch clear, optionally a CCleaner registry scan. "
                "Destructive — deletes temp/prefetch and may touch the registry.",
    parameters={"properties": {
        "include_registry": {"type": "boolean",
                             "description": "Also run CCleaner registry scan if installed."}
    }, "required": []},
    fn=optimize_system,
    destructive=True,
))

_register(ToolSpec(
    name="search_web",
    description="Search the web for current information and return top snippets.",
    parameters={"properties": {
        "query": {"type": "string", "description": "The search query."},
        "max_results": {"type": "integer", "description": "Results to return (default 3, max 8)."}
    }, "required": ["query"]},
    fn=search_web,
    destructive=False,
))

_register(ToolSpec(
    name="rag_search",
    description="Search the user's local Obsidian/ChromaDB knowledge vault for "
                "relevant notes. Use for personal projects, configs, past work.",
    parameters={"properties": {
        "query": {"type": "string", "description": "What to look up in local knowledge."},
        "n_results": {"type": "integer", "description": "Chunks to return (default 3, max 8)."}
    }, "required": ["query"]},
    fn=rag_search,
    destructive=False,
))

_register(ToolSpec(
    name="get_system_telemetry",
    description="Report live hardware telemetry: CPU/GPU/RAM load, temperatures, "
                "VRAM, and disk usage.",
    parameters={"properties": {}, "required": []},
    fn=get_system_telemetry,
    destructive=False,
))

_register(ToolSpec(
    name="list_directory",
    description="List the files and folders inside a directory path.",
    parameters={"properties": {
        "path": {"type": "string", "description": "Absolute or ~ directory path."}
    }, "required": ["path"]},
    fn=list_directory,
    destructive=False,
))

_register(ToolSpec(
    name="read_text_file",
    description="Read the text contents of a file (truncated for safety).",
    parameters={"properties": {
        "path": {"type": "string", "description": "Absolute or ~ file path."},
        "max_chars": {"type": "integer", "description": "Max chars to return (default 4000)."}
    }, "required": ["path"]},
    fn=read_text_file,
    destructive=False,
))


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------

def get_tool(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def get_tool_schemas() -> list[dict]:
    """Return all tool schemas in provider-neutral form for function-calling."""
    return [spec.to_schema() for spec in TOOLS.values()]


def run_tool(_tool_name: str, /, _args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """
    Execute a tool by name. Never raises — returns a readable string the agent
    can interpret. Does NOT enforce approval; the agent loop is responsible for
    routing destructive tools through safety_catch first.

    Tool arguments may be passed either as a dict (``run_tool("kill_process",
    {"name": "chrome"})`` — the form the agent loop uses with LLM-provided
    JSON args) or as keyword args (``run_tool("launch_app", app_name="notepad")``).

    The tool name parameter is positional-only (``/``) so it can never collide
    with a tool's own parameter named ``name`` (e.g. kill_process(name=...)).
    """
    spec = TOOLS.get(_tool_name)
    if spec is None:
        return f"[tool error] Unknown tool: {_tool_name!r}. Available: {', '.join(TOOLS)}"
    call_args: dict[str, Any] = dict(_args) if _args else {}
    call_args.update(kwargs)
    try:
        return spec.fn(**call_args)
    except TypeError as exc:
        return f"[tool error] Bad arguments for {_tool_name}: {exc}"
    except Exception as exc:
        return f"[tool error] {_tool_name} failed: {exc}"


if __name__ == "__main__":
    # Smoke test — list catalog and run the safe read-only tools.
    print(f"Registered {len(TOOLS)} tools:")
    for n, s in TOOLS.items():
        flag = " (destructive)" if s.destructive else ""
        print(f"  - {n}{flag}: {s.description[:60]}")
    print("\n--- get_system_telemetry ---")
    print(run_tool("get_system_telemetry"))
    print("\n--- list_top_processes (count=3) ---")
    print(run_tool("list_top_processes", count=3))
