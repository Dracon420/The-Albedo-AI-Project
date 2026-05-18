"""
albedo.eel_app — alpha Eel-based UI (Phase 2 of the Cyberdeck Overhaul).

Coexists with the original Tk GUI in albedo.gui — users opt in via
``ALBEDO_UI=eel`` in their .env. Defaults to Tk so v2.0.2 installs
upgrade with zero behaviour change.

Public surface:
    bridge   — Python functions exposed to JS via @eel.expose
    app      — launcher (eel.init + eel.start) — call run()
"""
