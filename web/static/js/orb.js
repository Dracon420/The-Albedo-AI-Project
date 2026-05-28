/**
 * orb.js — Holographic Canvas 2D orb for Albedo's hero orb.
 *
 * Inserts a <canvas> behind the albedo_logo.png and animates:
 *   - 3D-projected particle rings rotating at different speeds/tilts
 *   - Radial glow pulse synced to voice/state
 *   - State-driven color (standby=orange, active=purple, listening=green, error=red)
 *
 * Public API (called by chat.js / app.js to reflect UI state):
 *   window._orb.setState('standby'|'active'|'listening'|'error')
 *   window._orb.setEnergy(0.0–1.0)   // mic volume for pulse intensity
 *
 * No external dependencies. Works fully offline.
 */
(function () {
  "use strict";

  const STATE_COLORS = {
    standby:  [255, 174,   0],   // orange
    active:   [208,   0, 255],   // neon purple
    listening: [ 57, 255,  20],  // neon green
    error:    [255,  42, 109],   // red
  };

  // Ring definitions: radius (px from centre of 200×200 orb),
  // angular speed (rad/s), number of particles, tilt (0=flat, 1=edge-on),
  // starting phase offset.
  const RINGS = [
    { r: 96, speed:  0.28, count: 28, tilt: 0.30, phase: 0.00 },
    { r: 80, speed: -0.45, count: 20, tilt: 0.55, phase: 1.05 },
    { r: 64, speed:  0.70, count: 14, tilt: 0.20, phase: 2.09 },
    { r: 48, speed: -1.00, count:  8, tilt: 0.75, phase: 3.14 },
  ];

  let _state  = "standby";
  let _energy = 0;          // 0–1, driven by mic amplitude
  let _t      = 0;
  let _ctx, _W, _H, _cx, _cy;

  window._orb = {
    setState(s) { _state = STATE_COLORS[s] ? s : "standby"; },
    setEnergy(e) { _energy = Math.max(0, Math.min(1, e)); },
  };

  function lerpColor(a, b, t) {
    return [
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t,
      a[2] + (b[2] - a[2]) * t,
    ];
  }

  function rgba(col, a) {
    return `rgba(${col[0]|0},${col[1]|0},${col[2]|0},${a.toFixed(3)})`;
  }

  function draw(dt) {
    _t += dt;

    _ctx.clearRect(0, 0, _W, _H);

    const col    = STATE_COLORS[_state];
    const energy = _energy;

    // ── Outer ambient glow ────────────────────────────────────────────
    const glowR = _cx * 1.05 + energy * _cx * 0.12;
    const grd   = _ctx.createRadialGradient(_cx, _cy, 0, _cx, _cy, glowR);
    grd.addColorStop(0,   rgba(col, 0.07 + energy * 0.10));
    grd.addColorStop(0.5, rgba(col, 0.03 + energy * 0.04));
    grd.addColorStop(1,   rgba(col, 0));
    _ctx.fillStyle = grd;
    _ctx.beginPath();
    _ctx.arc(_cx, _cy, glowR, 0, Math.PI * 2);
    _ctx.fill();

    // ── Rotating particle rings ───────────────────────────────────────
    for (const ring of RINGS) {
      const angle = _t * ring.speed + ring.phase;
      const ry    = ring.r * (1 - ring.tilt);   // y-radius flattened for 3D

      // faint ellipse arc
      _ctx.beginPath();
      _ctx.ellipse(_cx, _cy, ring.r, ry, 0, 0, Math.PI * 2);
      _ctx.strokeStyle = rgba(col, 0.08 + energy * 0.07);
      _ctx.lineWidth   = 0.6;
      _ctx.stroke();

      // particles along the ring
      for (let i = 0; i < ring.count; i++) {
        const a     = angle + (i / ring.count) * Math.PI * 2;
        const cosA  = Math.cos(a);
        const sinA  = Math.sin(a);
        const px    = _cx + cosA * ring.r;
        const py    = _cy + sinA * ry;

        // depth: sin(a) maps -1…1 → 0…1 (back→front)
        const depth = (sinA + 1) * 0.5;
        const alpha = (0.25 + depth * 0.55) * (0.7 + energy * 0.3);
        const pSize = 0.8 + depth * 2.0 + energy * 1.2;

        _ctx.beginPath();
        _ctx.arc(px, py, pSize, 0, Math.PI * 2);
        _ctx.fillStyle = rgba(col, alpha);
        _ctx.fill();
      }
    }

    // ── Inner pulsing ring (reacts to mic energy) ─────────────────────
    const pulseFreq = _state === "listening" ? 3.0 : 1.6;
    const pulseAmt  = Math.sin(_t * pulseFreq) * 0.5 + 0.5;
    const innerR    = _cx * 0.78 + pulseAmt * 4 + energy * _cx * 0.12;
    _ctx.beginPath();
    _ctx.arc(_cx, _cy, innerR, 0, Math.PI * 2);
    _ctx.strokeStyle = rgba(col, 0.18 + pulseAmt * 0.14 + energy * 0.22);
    _ctx.lineWidth   = 1.2 + energy * 1.5;
    _ctx.stroke();

    // ── Hard-cut scan line that sweeps around the logo ─────────────────
    if (_state === "active" || _state === "listening") {
      const scanAngle = _t * 1.8;
      const scanLen   = _cx * 0.90;
      const ex        = _cx + Math.cos(scanAngle) * scanLen;
      const ey        = _cy + Math.sin(scanAngle) * scanLen;
      const scanGrd   = _ctx.createLinearGradient(_cx, _cy, ex, ey);
      scanGrd.addColorStop(0,   rgba(col, 0));
      scanGrd.addColorStop(0.6, rgba(col, 0.25 + energy * 0.3));
      scanGrd.addColorStop(1,   rgba(col, 0));
      _ctx.strokeStyle = scanGrd;
      _ctx.lineWidth   = 1.5;
      _ctx.beginPath();
      _ctx.moveTo(_cx, _cy);
      _ctx.lineTo(ex, ey);
      _ctx.stroke();
    }
  }

  function init() {
    const orbEl = document.querySelector(".hero__orb");
    if (!orbEl) return;

    const canvas      = document.createElement("canvas");
    canvas.className  = "orb__canvas";
    Object.assign(canvas.style, {
      position: "absolute",
      inset:    "0",
      width:    "100%",
      height:   "100%",
      zIndex:   "1",
      pointerEvents: "none",
    });
    // Insert BEFORE the logo so it sits behind it in DOM stacking order.
    orbEl.insertBefore(canvas, orbEl.firstChild);

    function resize() {
      const rect = orbEl.getBoundingClientRect();
      _W = rect.width  || 200;
      _H = rect.height || 200;
      const dpr     = window.devicePixelRatio || 1;
      canvas.width  = _W * dpr;
      canvas.height = _H * dpr;
      _ctx = canvas.getContext("2d");
      _ctx.scale(dpr, dpr);
      _cx = _W / 2;
      _cy = _H / 2;
    }
    resize();
    window.addEventListener("resize", resize);

    // Animation loop
    let last = performance.now();
    function loop(now) {
      const dt = Math.min((now - last) / 1000, 0.05); // cap at 50ms
      last = now;
      draw(dt);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);

    // Hook into appState changes so the orb color tracks the state badge.
    const stateEl = document.getElementById("appState");
    if (stateEl) {
      const obs = new MutationObserver(() => {
        const s = (stateEl.dataset.state || "standby").toLowerCase();
        window._orb.setState(s);
      });
      obs.observe(stateEl, { attributes: true, attributeFilter: ["data-state"] });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
