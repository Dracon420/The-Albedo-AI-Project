/**
 * event_bus_client.js — JS-side subscriber for Albedo's backend event bus.
 *
 * Python side (albedo/event_bus.py) publishes events that the Eel app pumps
 * out via eel._albedo_event(evt). Many windows (Brain viz, Team viz, chat
 * panel) want to listen, so this module multiplexes a single Eel exposure
 * into a local pub/sub.
 *
 * Usage:
 *   EventBus.on("rag.hit", (e) => { ... });   // subscribe to one type
 *   EventBus.on("*",       (e) => { ... });   // subscribe to all
 *   EventBus.replayHistory();                  // optional: pull recent events
 *                                              //          via eel.get_event_history()
 *                                              // and dispatch them locally
 */
(function () {
  "use strict";

  const subs = {};   // type -> [cb, cb, ...]; "*" matches all

  function on(type, cb) {
    if (typeof cb !== "function") return;
    (subs[type] = subs[type] || []).push(cb);
  }

  function _dispatch(evt) {
    if (!evt || !evt.type) return;
    (subs[evt.type] || []).forEach((cb) => { try { cb(evt); } catch (_) {} });
    (subs["*"]      || []).forEach((cb) => { try { cb(evt); } catch (_) {} });
  }

  // Backend pushes here.
  window._albedo_event = function (evt) { _dispatch(evt); };
  if (window.eel && eel.expose) {
    try { eel.expose(window._albedo_event, "_albedo_event"); } catch (_) {}
  }

  async function replayHistory(limit) {
    try {
      const r = await eel.get_event_history(limit || 200)();
      if (r && r.ok && Array.isArray(r.events)) {
        r.events.forEach(_dispatch);
      }
    } catch (_) { /* bridge not ready or no history */ }
  }

  window.EventBus = { on, replayHistory };
})();
