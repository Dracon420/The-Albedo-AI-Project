"""
desktop_tools.py — on-device helpers: clipboard, desktop screenshot + vision,
window management, and open/reveal. Used by agent tools.
"""
from __future__ import annotations

import os
import subprocess

_CREATE_NO_WINDOW = 0x08000000


# ── Clipboard ────────────────────────────────────────────────────────────────
def read_clipboard() -> str:
    try:
        import pyperclip
        t = pyperclip.paste()
        return t if t else "(clipboard is empty)"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] clipboard read failed: {exc}"


def set_clipboard(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text or "")
        return "Copied to clipboard."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] clipboard write failed: {exc}"


# ── Desktop screenshot + Moondream vision ────────────────────────────────────
def screenshot_describe(question: str = "") -> str:
    try:
        from PIL import ImageGrab
        import numpy as np
        img = ImageGrab.grab()
        frame = np.array(img.convert("RGB"))
        from albedo.vision import vision_query
        prompt = (question or "").strip() or "Describe what is on this screen."
        return vision_query(frame, prompt)
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] screenshot failed: {exc}"


# ── Window management (pygetwindow) ──────────────────────────────────────────
def _match_windows(name: str):
    import pygetwindow as gw
    n = (name or "").lower()
    return [w for w in gw.getAllWindows() if w.title and n in w.title.lower()]


def focus_window(name: str) -> str:
    try:
        wins = _match_windows(name)
        if not wins:
            return f"No window matching '{name}'."
        w = wins[0]
        try:
            w.restore()
        except Exception:
            pass
        try:
            w.activate()
        except Exception:
            pass
        return f"Focused: {w.title}"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] focus failed: {exc}"


def minimize_window(name: str) -> str:
    try:
        wins = _match_windows(name)
        if not wins:
            return f"No window matching '{name}'."
        n = 0
        for w in wins:
            try:
                w.minimize()
                n += 1
            except Exception:
                pass
        return f"Minimized {n} window(s) matching '{name}'."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] minimize failed: {exc}"


def list_windows() -> str:
    try:
        import pygetwindow as gw
        titles = sorted({w.title for w in gw.getAllWindows() if w.title and w.visible})
        if not titles:
            return "No visible windows."
        return "Open windows:\n" + "\n".join(f"- {t}" for t in titles[:40])
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] list windows failed: {exc}"


# ── Open / reveal ────────────────────────────────────────────────────────────
def open_path(path: str) -> str:
    try:
        if not os.path.exists(path):
            return f"[tool error] not found: {path}"
        os.startfile(path)  # default app for files, Explorer for folders
        return f"Opened {path}"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] open failed: {exc}"


def reveal_in_explorer(path: str) -> str:
    try:
        if not os.path.exists(path):
            return f"[tool error] not found: {path}"
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)],
                         creationflags=_CREATE_NO_WINDOW)
        return f"Revealed {path} in Explorer"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] reveal failed: {exc}"


# ── Browser ──────────────────────────────────────────────────────────────────
def open_url(url: str) -> str:
    try:
        import webbrowser
        u = (url or "").strip()
        if not u:
            return "[tool error] no url given."
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        webbrowser.open(u)
        return f"Opened {u}"
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] open url failed: {exc}"


def web_open(query: str) -> str:
    try:
        import webbrowser
        import urllib.parse
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query or ""))
        return f"Opened a browser search for '{query}'."
    except Exception as exc:                                        # noqa: BLE001
        return f"[tool error] web open failed: {exc}"
