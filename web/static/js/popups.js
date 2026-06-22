/**
 * popups.js — factory-registered popups + their event handlers.
 *
 * New tool popups go here as a small AlbedoPopup.register({...}) spec instead of
 * a hand-written modal module.
 */
(function register() {
  if (!window.AlbedoPopup) { setTimeout(register, 100); return; }

  // ── Reminders ──────────────────────────────────────────────
  AlbedoPopup.register({
    id: "reminders",
    title: "REMINDERS",
    hint: "Active reminders fire as Windows notifications. Tick to cancel.",
    trigger: "list_reminders",
    mode: "list",
    dataEndpoint: "get_reminders",
    valueKey: "id",
    selectable: true,
    lockKey: "fired",
    columns: [
      { key: "text", label: "Reminder", grow: true },
      { key: "when_human", label: "When", dim: true },
    ],
    emptyText: "No reminders set.",
    footActions: [
      { label: "CANCEL SELECTED", accent: true, endpoint: "cancel_reminders",
        confirm: (sel) => `Cancel ${sel.length} reminder(s)?` },
    ],
  });

  // ── File search ────────────────────────────────────────────
  AlbedoPopup.register({
    id: "filesearch",
    title: "FILE SEARCH",
    hint: "Matches from your file catalog / folders. Tick to reveal in Explorer.",
    trigger: "find_files",
    mode: "list",
    dataEndpoint: "get_file_search",
    valueKey: "path",
    selectable: true,
    columns: [
      { key: "name", label: "File", grow: true },
      { key: "parent", label: "Folder", dim: true },
    ],
    emptyText: "No matching files.",
    footActions: [
      { label: "REVEAL SELECTED", accent: true, endpoint: "reveal_files" },
    ],
  });
})();

// Surface a fired reminder in the chat log too (in case the OS toast is missed).
(function wireReminderFired() {
  if (!window.EventBus) { setTimeout(wireReminderFired, 300); return; }
  EventBus.on("reminder.fired", (e) => {
    try {
      const chat = document.getElementById("chat");
      if (!chat) return;
      const line = document.createElement("div");
      line.className = "chat__line chat__line--system";
      line.textContent = "[REMINDER] " + (e && e.text || "");
      chat.appendChild(line);
      chat.scrollTop = chat.scrollHeight;
    } catch (_) { /* ignore */ }
  });
})();
