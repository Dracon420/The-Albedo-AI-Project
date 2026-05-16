"""
onboarding.py  --  Albedo First-Time Configuration Wizard

Launched by AlbedoGUI._check_first_boot() when .env is absent or missing
required keys (GEMINI_API_KEY, OBSIDIAN_VAULT_PATH).

OnboardingWizard is a CTkToplevel — it shares the main application's
CTk root and event loop.  AlbedoGUI calls self.withdraw() to hide
itself, then instantiates OnboardingWizard(parent=self, on_complete=cb).
When the wizard writes .env and closes, it calls on_complete() which
triggers self.deiconify() on the main window.

This single-root design eliminates the check_dpi_scaling ghost-thread
errors that occurred when the wizard used its own CTk() mainloop().
"""
from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

ROOT     = Path(__file__).parent
ENV_FILE = ROOT / ".env"

# Developer console URLs for the [?] help buttons
_HELP_URLS = {
    "gemini":   "https://aistudio.google.com/app/apikey",
    "groq":     "https://console.groq.com/keys",
    "together": "https://api.together.xyz/settings/api-keys",
}

# Aesthetic constants (matches Albedo Mission Control palette)
_BG       = "#0a0a0f"
_PANEL    = "#0d1117"
_CYAN     = "#00FFFF"
_CYAN_DIM = "#007a99"
_GREEN    = "#39ff14"
_RED      = "#ff3131"
_FG       = "#c8d6e5"
_FONT_HUD = ("Courier New", 11, "bold")
_FONT_LBL = ("Courier New", 10)
_FONT_HDR = ("Courier New", 14, "bold")
_FONT_BTN = ("Courier New", 11, "bold")


# ---------------------------------------------------------------------------
# Wizard window  (CTkToplevel — no second CTk root, no second mainloop)
# ---------------------------------------------------------------------------

class OnboardingWizard(ctk.CTkToplevel):

    def __init__(self, parent: ctk.CTk, on_complete=None) -> None:
        super().__init__(parent)
        self._on_complete = on_complete

        self.title("ALBEDO // FIRST-TIME CONFIGURATION")
        self.geometry("780x740")
        self.minsize(700, 680)
        self.configure(fg_color=_BG)
        self.resizable(True, True)

        # Block interaction with the hidden main window until wizard closes
        self.grab_set()
        self.focus_force()

        self._vault_path:  str  = ""
        self._saved              = False
        self._entries:     dict  = {}
        self._show_states: dict  = {}
        self._location_var       = ctk.StringVar()

        self._build_ui()

        # Do NOT call self.mainloop() — we share the parent's event loop.

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 24, "pady": 6}

        # ── Header ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="▸ ALBEDO MISSION CONTROL",
            font=_FONT_HDR,
            text_color=_CYAN,
        ).pack(pady=(20, 4))

        ctk.CTkLabel(
            self,
            text="FIRST-TIME CONFIGURATION WIZARD",
            font=("Courier New", 9, "bold"),
            text_color=_CYAN_DIM,
        ).pack(pady=(0, 2))

        # ── Preflight instructions ───────────────────────────────────────
        instr = ctk.CTkTextbox(
            self,
            height=110,
            font=("Courier New", 16, "bold"),
            fg_color=_PANEL,
            text_color=_CYAN,
            border_color=_CYAN_DIM,
            border_width=1,
            wrap="word",
            state="normal",
        )
        instr.pack(fill="x", **pad)
        instr.insert("1.0",
            "Welcome to Albedo.  To initialize the Swarm Commander, input your "
            "developer API keys and select your Obsidian Markdown vault directory.  "
            "All values are saved locally to .env and never transmitted."
        )
        instr.configure(state="disabled")

        # ── Divider ─────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="─" * 72, text_color=_CYAN_DIM,
                     font=("Courier New", 8)).pack(pady=(8, 2))

        # ── API key rows ─────────────────────────────────────────────────
        self._gemini_var   = ctk.StringVar()
        self._groq_var     = ctk.StringVar()
        self._together_var = ctk.StringVar()

        self._api_row("GEMINI API KEY",   self._gemini_var,   "gemini")
        self._api_row("GROQ API KEY",     self._groq_var,     "groq")
        self._api_row("TOGETHER API KEY", self._together_var, "together")

        # ── Vault picker ─────────────────────────────────────────────────
        ctk.CTkLabel(self, text="OBSIDIAN VAULT DIRECTORY",
                     font=_FONT_HUD, text_color=_CYAN,
                     anchor="w").pack(fill="x", padx=24, pady=(12, 2))

        vault_row = ctk.CTkFrame(self, fg_color="transparent")
        vault_row.pack(fill="x", padx=24, pady=(0, 4))

        self._vault_label = ctk.CTkLabel(
            vault_row,
            text="[ no directory selected ]",
            font=_FONT_LBL,
            text_color=_CYAN_DIM,
            anchor="w",
            wraplength=430,
        )
        self._vault_label.pack(side="left", expand=True, fill="x")

        ctk.CTkButton(
            vault_row,
            text="BROWSE",
            width=90,
            font=_FONT_BTN,
            fg_color=_PANEL,
            hover_color="#1a2332",
            border_color=_CYAN,
            border_width=1,
            text_color=_CYAN,
            command=self._pick_vault,
        ).pack(side="right", padx=(8, 0))

        # ── Node location ────────────────────────────────────────────────
        ctk.CTkLabel(self, text="NODE LOCATION  (City, State, Country)",
                     font=_FONT_HUD, text_color=_CYAN,
                     anchor="w").pack(fill="x", padx=24, pady=(12, 2))

        ctk.CTkEntry(
            self,
            textvariable=self._location_var,
            placeholder_text="e.g. Seattle, Washington, United States",
            font=("Courier New", 14),
            fg_color=_PANEL,
            border_color=_CYAN_DIM,
            text_color=_CYAN,
            height=36,
        ).pack(fill="x", padx=24, pady=(0, 4))

        # ── Status label ─────────────────────────────────────────────────
        self._status = ctk.CTkLabel(
            self, text="", font=_FONT_LBL, text_color=_GREEN
        )
        self._status.pack(pady=(6, 0))

        # ── Initialize button ────────────────────────────────────────────
        ctk.CTkButton(
            self,
            text="[ INITIALIZE CORE ]",
            font=("Courier New", 13, "bold"),
            height=44,
            fg_color=_PANEL,
            hover_color="#0d2233",
            border_color=_CYAN,
            border_width=2,
            text_color=_CYAN,
            command=self._save_and_close,
        ).pack(fill="x", padx=24, pady=(14, 20))

    def _api_row(self, label: str, var: ctk.StringVar, key: str) -> None:
        """Labelled entry row with right-click paste, SHOW toggle, and [?] link."""
        ctk.CTkLabel(self, text=label, font=_FONT_HUD, text_color=_CYAN,
                     anchor="w").pack(fill="x", padx=24, pady=(10, 2))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 2))

        entry = ctk.CTkEntry(
            row,
            textvariable=var,
            placeholder_text="paste key here...",
            font=("Courier New", 14),
            fg_color=_PANEL,
            border_color=_CYAN_DIM,
            text_color=_CYAN,
            show="•",
            height=36,
        )
        entry.pack(side="left", expand=True, fill="x")

        self._entries[key]     = entry
        self._show_states[key] = False
        self._bind_paste(entry)

        url = _HELP_URLS[key]
        ctk.CTkButton(
            row, text=" ? ", width=34, font=_FONT_BTN,
            fg_color=_PANEL, hover_color="#1a2332",
            border_color=_CYAN_DIM, border_width=1, text_color=_CYAN_DIM,
            command=lambda u=url: webbrowser.open(u),
        ).pack(side="right", padx=(4, 0))

        show_btn = ctk.CTkButton(
            row, text="SHOW", width=56, font=_FONT_BTN,
            fg_color=_PANEL, hover_color="#1a2332",
            border_color=_CYAN_DIM, border_width=1, text_color=_CYAN_DIM,
        )
        show_btn.configure(command=lambda k=key, b=show_btn: self._toggle_show(k, b))
        show_btn.pack(side="right", padx=(4, 0))

    def _toggle_show(self, key: str, btn: ctk.CTkButton) -> None:
        entry   = self._entries[key]
        visible = self._show_states[key]
        entry._entry.configure(show="" if not visible else "•")
        btn.configure(text="HIDE" if not visible else "SHOW")
        self._show_states[key] = not visible

    def _bind_paste(self, entry: ctk.CTkEntry) -> None:
        menu = tk.Menu(self, tearoff=0,
                       bg=_PANEL, fg=_FG, activebackground=_CYAN_DIM,
                       activeforeground="#000000", relief="flat",
                       font=("Courier New", 10))
        menu.add_command(label="Paste", command=lambda: self._paste_into(entry))
        for widget in (entry, entry._entry):
            widget.bind("<Button-3>",
                        lambda e, m=menu: m.tk_popup(e.x_root, e.y_root),
                        add=True)

    def _paste_into(self, entry: ctk.CTkEntry) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        entry.delete(0, "end")
        entry.insert(0, text)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _pick_vault(self) -> None:
        path = filedialog.askdirectory(
            title="Select Obsidian Vault Directory",
            mustexist=True,
        )
        if path:
            self._vault_path = path
            self._vault_label.configure(text=path, text_color=_GREEN)

    def _save_and_close(self) -> None:
        gemini   = self._gemini_var.get().strip()
        groq     = self._groq_var.get().strip()
        together = self._together_var.get().strip()
        vault    = self._vault_path.strip()
        location = self._location_var.get().strip()

        if not gemini:
            self._status.configure(
                text="⚠  GEMINI API KEY is required.", text_color=_RED)
            return
        if not vault:
            self._status.configure(
                text="⚠  OBSIDIAN VAULT DIRECTORY is required.", text_color=_RED)
            return

        self._write_env(gemini, groq, together, vault, location)
        self._status.configure(
            text="✔  Core initialized. Booting Albedo...", text_color=_GREEN)
        self._saved = True
        self.after(900, self._safe_shutdown)

    def _safe_shutdown(self) -> None:
        """Destroy the toplevel, then fire the completion callback."""
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        if self._on_complete is not None:
            try:
                self._on_complete()
            except Exception:
                pass

    def _write_env(
        self,
        gemini: str,
        groq: str,
        together: str,
        vault: str,
        location: str = "",
    ) -> None:
        """Merge new values into .env, preserving unrelated keys."""
        updates = {
            "GEMINI_API_KEY":      gemini,
            "GROQ_API_KEY":        groq,
            "TOGETHER_API_KEY":    together,
            "OBSIDIAN_VAULT_PATH": vault,
            "NODE_LOCATION":       location or "an unspecified location",
        }

        existing_lines: list[str] = []
        if ENV_FILE.exists():
            existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

        seen: set[str] = set()
        merged: list[str] = []
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                merged.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                merged.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                merged.append(line)

        for key, val in updates.items():
            if key not in seen:
                merged.append(f"{key}={val}")

        ENV_FILE.write_text("\n".join(merged) + "\n", encoding="utf-8")
