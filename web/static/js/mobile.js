/**
 * mobile.js — MOBILE tab logic for the Albedo Mission Control drawer.
 *
 * Handles:
 *  - Polling mobile_status() to show connection state
 *  - Generating pairing QR via mobile_pair()
 *  - Rendering QR code on a canvas using a minimal built-in QR encoder
 *  - Copy token button
 *  - Unpair button
 *
 * QR encoding uses the qrcodejs library loaded from CDN if available,
 * with a canvas-text fallback showing the raw string if the library
 * can't be loaded (e.g. offline). The phone app can also accept manual
 * entry of the relay URL and token so QR is optional.
 */

(function () {
  "use strict";

  // ── DOM refs (populated after DOMContentLoaded) ───────────────────────
  let _dot, _label, _qrWrap, _qrCanvas, _tokenWrap,
      _relayUrlEl, _tokenEl, _copyBtn, _pairBtn, _unpairBtn;

  let _pollTimer  = null;
  let _qrLib      = null;   // qrcodejs lib reference once loaded
  let _qrInstance = null;   // current QRCode object

  // ── Init ──────────────────────────────────────────────────────────────
  function init() {
    _dot        = document.getElementById("mobileStatusDot");
    _label      = document.getElementById("mobileStatusLabel");
    _qrWrap     = document.getElementById("mobileQrWrap");
    _qrCanvas   = document.getElementById("mobileQrCanvas");
    _tokenWrap  = document.getElementById("mobileTokenWrap");
    _relayUrlEl = document.getElementById("mobileRelayUrl");
    _tokenEl    = document.getElementById("mobileToken");
    _copyBtn    = document.getElementById("mobileCopyBtn");
    _pairBtn    = document.getElementById("mobilePairBtn");
    _unpairBtn  = document.getElementById("mobileUnpairBtn");

    if (!_pairBtn) return;   // tab not in DOM

    _pairBtn.addEventListener("click", _onPair);
    _unpairBtn.addEventListener("click", _onUnpair);
    _copyBtn  && _copyBtn.addEventListener("click", _onCopy);

    // Poll status whenever the MOBILE tab is open
    document.querySelectorAll(".drawer__tab[data-tab='mobile']").forEach(btn => {
      btn.addEventListener("click", () => {
        _refreshStatus();
        _startPoll();
      });
    });

    // Stop polling when another tab opens
    document.querySelectorAll(".drawer__tab:not([data-tab='mobile'])").forEach(btn => {
      btn.addEventListener("click", _stopPoll);
    });

    // Load QR lib async (doesn't block anything)
    _loadQrLib();
  }

  // ── Polling ───────────────────────────────────────────────────────────
  function _startPoll() {
    _stopPoll();
    _pollTimer = setInterval(_refreshStatus, 5000);
  }
  function _stopPoll() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  async function _refreshStatus() {
    try {
      const r = await eel.mobile_status()();
      if (r && r.ok) _applyStatus(r);
    } catch { /* ignore */ }
  }

  // ── Status rendering ──────────────────────────────────────────────────
  function _applyStatus(s) {
    if (!_dot) return;

    if (!s.paired) {
      _dot.className   = "mobile-status__dot mobile-status__dot--off";
      _label.textContent = "NOT PAIRED";
      _qrWrap.style.display    = "none";
      _tokenWrap.style.display = "none";
      _pairBtn.style.display   = "";
      _unpairBtn.style.display = "none";
      return;
    }

    // Paired
    _relayUrlEl.textContent = s.relay_url || "";
    _tokenEl.textContent    = s.token || "";
    _tokenWrap.style.display = "";
    _pairBtn.style.display   = "none";
    _unpairBtn.style.display = "";

    if (s.connected) {
      _dot.className   = "mobile-status__dot mobile-status__dot--on";
      _label.textContent = "PHONE CONNECTED";
    } else {
      _dot.className   = "mobile-status__dot mobile-status__dot--standby";
      _label.textContent = "WAITING FOR PHONE";
    }

    // Render QR if we have qr_data
    if (s.qr_data) {
      _qrWrap.style.display = "";
      _renderQr(s.qr_data);
    }
  }

  // ── Pairing ───────────────────────────────────────────────────────────
  async function _onPair() {
    _pairBtn.disabled    = true;
    _pairBtn.textContent = "CONNECTING...";
    try {
      const r = await eel.mobile_pair()();
      if (r && r.ok) {
        _applyStatus({ paired: true, connected: false,
                       token: r.token, relay_url: r.relay_url, qr_data: r.qr_data });
      } else {
        alert("Pair failed: " + (r ? r.error : "unknown error"));
      }
    } catch (e) {
      alert("Pair error: " + e);
    } finally {
      _pairBtn.disabled    = false;
      _pairBtn.textContent = "GENERATE CODE";
    }
  }

  async function _onUnpair() {
    if (!confirm("Remove pairing? The phone app will need to be set up again.")) return;
    try {
      await eel.mobile_unpair()();
    } catch { /* ignore */ }
    _applyStatus({ paired: false });
  }

  // ── Copy token ────────────────────────────────────────────────────────
  function _onCopy() {
    const text = (_relayUrlEl.textContent || "") + "|" + (_tokenEl.textContent || "");
    navigator.clipboard.writeText(text).then(() => {
      const old = _copyBtn.textContent;
      _copyBtn.textContent = "✓";
      setTimeout(() => { _copyBtn.textContent = old; }, 1500);
    }).catch(() => { alert("Copy failed — select the token manually."); });
  }

  // ── QR rendering ──────────────────────────────────────────────────────
  function _loadQrLib() {
    // Try to load qrcode.min.js from CDN
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
    s.onload  = () => { _qrLib = window.QRCode; };
    s.onerror = () => { _qrLib = null; };
    document.head.appendChild(s);
  }

  function _renderQr(data) {
    if (!_qrCanvas) return;
    const ctx = _qrCanvas.getContext("2d");

    if (_qrLib) {
      // qrcodejs renders to a <div>; we grab its canvas/img and copy it
      const tmp = document.createElement("div");
      tmp.style.display = "none";
      document.body.appendChild(tmp);
      try {
        const qr = new _qrLib(tmp, {
          text:          data,
          width:         180,
          height:        180,
          colorDark:     "#00d4ff",
          colorLight:    "#060e16",
          correctLevel:  _qrLib.CorrectLevel.M,
        });
        // qrcodejs inserts a canvas or img — copy it
        setTimeout(() => {
          const child = tmp.querySelector("canvas") || tmp.querySelector("img");
          if (child) {
            ctx.clearRect(0, 0, 180, 180);
            if (child.tagName === "CANVAS") {
              ctx.drawImage(child, 0, 0, 180, 180);
            } else {
              const img = new Image();
              img.onload = () => ctx.drawImage(img, 0, 0, 180, 180);
              img.src = child.src;
            }
          }
          document.body.removeChild(tmp);
        }, 50);
      } catch (e) {
        document.body.removeChild(tmp);
        _renderQrFallback(ctx, data);
      }
    } else {
      _renderQrFallback(ctx, data);
    }
  }

  function _renderQrFallback(ctx, data) {
    // Fallback: show the raw string on the canvas so the user can read it
    ctx.fillStyle = "#060e16";
    ctx.fillRect(0, 0, 180, 180);
    ctx.fillStyle = "#00d4ff";
    ctx.font = "10px monospace";
    ctx.fillText("QR lib offline.", 10, 20);
    ctx.fillText("Use manual entry:", 10, 36);
    const parts = data.split("|");
    ctx.font = "8px monospace";
    let y = 60;
    (parts[0] || data).match(/.{1,22}/g)?.forEach(line => {
      ctx.fillText(line, 6, y); y += 12;
    });
    if (parts[1]) {
      y += 4;
      ctx.fillStyle = "#ff9500";
      parts[1].match(/.{1,22}/g)?.forEach(line => {
        ctx.fillText(line, 6, y); y += 12;
      });
    }
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
