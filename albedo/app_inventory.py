"""
app_inventory.py — enumerate installed Windows apps with real usage data so
Albedo can answer "what can I uninstall to free space?" with a concrete,
usage-ranked list (least-used / largest first), and uninstall on confirmation.

Sources (all local, read-only):
  • Registry Uninstall keys (HKLM + HKCU, 32- & 64-bit) → name, size, publisher,
    install date, uninstall command.
  • UserAssist (HKCU Explorer/UserAssist) -> per-program run count + last-used
    timestamp (ROT13-encoded keys, binary value). Best-effort.

Public API:
    list_installed_apps(limit=40) -> list[dict]
    uninstall_app(name) -> str            (DESTRUCTIVE — gate via approval)
"""
from __future__ import annotations

import codecs
import datetime as _dt
import struct
import subprocess

try:
    import winreg
except Exception:                                                    # noqa: BLE001
    winreg = None  # non-Windows / import failure → tools degrade gracefully


# ---------------------------------------------------------------------------
# UserAssist — program run counts + last-used time
# ---------------------------------------------------------------------------

def _read_userassist() -> dict:
    """Map lowercased exe/app basename -> {'count': int, 'last': epoch|None}."""
    usage: dict[str, dict] = {}
    if winreg is None:
        return usage
    base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
    except Exception:
        return usage
    i = 0
    while True:
        try:
            guid = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            countkey = winreg.OpenKey(root, guid + r"\Count")
        except Exception:
            continue
        j = 0
        while True:
            try:
                name, data, _typ = winreg.EnumValue(countkey, j)
            except OSError:
                break
            j += 1
            try:
                decoded = codecs.decode(name, "rot_13")
            except Exception:
                continue
            # value blob: run count at offset 4 (uint32); last-used FILETIME at
            # offset 60 (8 bytes) in modern Win formats.
            count = 0
            last = None
            try:
                if len(data) >= 8:
                    count = struct.unpack_from("<I", data, 4)[0]
                if len(data) >= 68:
                    ft = struct.unpack_from("<Q", data, 60)[0]
                    if ft:
                        # FILETIME (100ns since 1601) -> epoch seconds
                        last = ft / 1e7 - 11644473600
            except Exception:
                pass
            key = decoded.replace("/", "\\").rsplit("\\", 1)[-1].lower()
            if not key:
                continue
            prev = usage.get(key)
            if prev is None or count > prev["count"]:
                usage[key] = {"count": count, "last": last}
    return usage


# ---------------------------------------------------------------------------
# Registry uninstall inventory
# ---------------------------------------------------------------------------

_UNINSTALL_PATHS = [
    (None, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (None, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def _iter_uninstall_entries():
    if winreg is None:
        return
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_PATHS[0][1]),
        (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_PATHS[1][1]),
        (winreg.HKEY_CURRENT_USER,  _UNINSTALL_PATHS[0][1]),
    ]
    for hive, path in hives:
        try:
            key = winreg.OpenKey(hive, path)
        except Exception:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            try:
                sk = winreg.OpenKey(key, sub)
                yield sk
            except Exception:
                continue


def _val(key, name):
    try:
        v, _ = winreg.QueryValueEx(key, name)
        return v
    except Exception:
        return None


def list_installed_apps(limit: int = 40) -> list[dict]:
    """
    Return installed apps as dicts: name, size_mb, publisher, install_date,
    last_used (ISO date or None), run_count, uninstall. Sorted least-used /
    largest first — i.e. the best candidates to remove appear first.
    """
    if winreg is None:
        return []
    usage = _read_userassist()
    apps: list[dict] = []
    seen = set()
    for sk in _iter_uninstall_entries():
        name = _val(sk, "DisplayName")
        if not name or _val(sk, "SystemComponent") == 1:
            continue
        if _val(sk, "ParentKeyName") or _val(sk, "ReleaseType") == "Security Update":
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        size_kb = _val(sk, "EstimatedSize") or 0
        uninstall = _val(sk, "QuietUninstallString") or _val(sk, "UninstallString") or ""
        idate = _val(sk, "InstallDate") or ""
        # Match usage: an exe basename appears as a whole word in the app name,
        # OR the app's first significant word matches an exe basename.
        nl = name.lower()
        nwords = set(w for w in nl.replace("(", " ").replace(")", " ").split() if len(w) > 2)
        u = None
        for k, info in usage.items():
            if not k.endswith(".exe"):
                continue
            stem = k[:-4]
            if len(stem) < 3:
                continue
            if stem in nwords or stem in nl.replace(" ", ""):
                u = info if (u is None or info["count"] > u["count"]) else u
        last = None
        if u and u.get("last"):
            try:
                last = _dt.datetime.fromtimestamp(u["last"]).strftime("%Y-%m-%d")
            except Exception:
                last = None
        apps.append({
            "name": name,
            "size_mb": round(size_kb / 1024, 1) if size_kb else 0.0,
            "publisher": _val(sk, "Publisher") or "",
            "install_date": idate,
            # None = no usage record (NOT "never used" — UserAssist only tracks
            # some launches). Only a real match yields a count/date.
            "last_used": last,
            "run_count": (u["count"] if u else None),
            "uninstall": uninstall,
        })

    # Rank by size (reliable space-saving signal) so the biggest reclaimable
    # apps surface first; usage is reported per-app for the agent to weigh.
    apps.sort(key=lambda a: -a["size_mb"])
    return apps[:limit]


# ---------------------------------------------------------------------------
# Uninstall (DESTRUCTIVE)
# ---------------------------------------------------------------------------

def uninstall_app(name: str) -> str:
    """
    Uninstall an app by (partial) display name. Tries winget --silent first,
    then the registry QuietUninstallString. DESTRUCTIVE — callers must gate this
    behind user approval.
    """
    if not name or not name.strip():
        return "[uninstall] no app name given."
    name = name.strip()

    # 1) winget silent uninstall (cleanest when the app is in winget)
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(
            ["winget", "uninstall", "--name", name, "--silent",
             "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True, text=True, timeout=300, startupinfo=si,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "No installed package" not in out:
            return f"Uninstalled '{name}' via winget."
    except Exception as exc:                                          # noqa: BLE001
        out = f"(winget failed: {exc})"

    # 2) Fall back to the registry QuietUninstallString
    target = None
    for a in list_installed_apps(limit=500):
        if name.lower() in a["name"].lower() and a["uninstall"]:
            target = a
            break
    if not target:
        return f"Could not find an uninstall entry for '{name}'. {out}".strip()
    try:
        subprocess.Popen(target["uninstall"], shell=True)
        return (f"Launched the uninstaller for '{target['name']}'. Follow any "
                f"prompts it shows to finish removal.")
    except Exception as exc:                                          # noqa: BLE001
        return f"[uninstall] failed to start uninstaller for '{target['name']}': {exc}"
