/**
 * brain_viz.js — LIVE 3D visualization of the Obsidian "second brain".
 *
 * A rotating 3D node network of the vault (nodes = notes, edges = wikilinks),
 * colored by top-level folder — the "Brain Atlas" look, rendered entirely in
 * Canvas 2D so it works offline with no Three.js / WebGL / CDN dependency.
 *
 *   - 3D force-ish layout: notes are spread over a sphere volume, ordered by
 *     folder so each cluster occupies its own region, then relaxed along
 *     wikilink springs so connected notes pull together into lobes.
 *   - Auto-rotates; drag to spin, wheel to zoom. Perspective projection with
 *     depth cueing (near nodes bigger/brighter, far ones smaller/dimmer).
 *   - Neuron firing: rag.hit pulses matched nodes and sends a traveling spark
 *     down each axon to neighbors; a low ambient twinkle keeps it alive at rest.
 *   - Hover a node for an HTML tooltip (title, folder, path, links, last fired).
 */
(function () {
  "use strict";

  const AMBIENT_INTERVAL_MS = 600;
  const AMBIENT_SPARKS_PER_TICK = 3;
  const MAX_NODES = 700;            // cap for smooth rotation on modest GPUs

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function _hashHue(folder) {
    let h = 0;
    const s = String(folder || "_root_");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return Math.abs(h) % 360;
  }
  function _folderColor(folder)    { return `hsl(${_hashHue(folder)}, 80%, 62%)`; }
  function _folderColorDim(folder) { return `hsla(${_hashHue(folder)}, 60%, 50%, 0.22)`; }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("viz", "viz--brain");

    const bar = _el("div", "viz__toolbar");
    bar.appendChild(_el("div", "viz__title", "◈ OBSIDIAN BRAIN — 3D"));
    const status = _el("div", "viz__status", "loading vault…");
    bar.appendChild(status);
    const search = document.createElement("input");
    search.type = "text";
    search.placeholder = "highlight note…";
    search.className = "viz__search";
    bar.appendChild(search);
    const refreshBtn = _el("button", "cmd-btn", "REFRESH");
    bar.appendChild(refreshBtn);
    root.appendChild(bar);

    const stage = _el("div", "viz__stage");
    root.appendChild(stage);
    const legend = _el("div", "brain-legend");
    root.appendChild(legend);

    const tooltip = _el("div", "brain-tip");
    tooltip.style.display = "none";
    document.body.appendChild(tooltip);

    async function load(refresh) {
      status.textContent = refresh ? "rebuilding vault graph…" : "loading vault…";
      try {
        const g = await eel.get_vault_graph(!!refresh)();
        if (!g || !g.ok) {
          status.textContent = "vault unavailable: " + (g && g.error || "unknown");
          return null;
        }
        const folders = new Set((g.nodes || []).map(n => n.folder || "_root_"));
        status.textContent = `${g.nodes.length} notes · ${g.edges.length} links · ${folders.size} clusters`;
        legend.innerHTML = "";
        Array.from(folders).sort().forEach((f) => {
          const item = _el("span", "brain-legend__item");
          const sw = _el("span", "brain-legend__swatch");
          sw.style.background = _folderColor(f);
          item.appendChild(sw);
          item.appendChild(_el("span", "brain-legend__label", f === "_root_" ? "(root)" : f));
          legend.appendChild(item);
        });
        return g;
      } catch (e) {
        status.textContent = "bridge error: " + e;
        return null;
      }
    }

    const graph = await load(false);
    if (!graph || !graph.nodes.length) { tooltip.remove(); return; }

    let scene = _render3D(stage, graph, { tooltip, lastHit: {}, search });

    refreshBtn.addEventListener("click", async () => {
      const g2 = await load(true);
      if (!g2 || !g2.nodes.length) return;
      if (scene && scene.destroy) scene.destroy();
      stage.innerHTML = "";
      scene = _render3D(stage, g2, { tooltip, lastHit: (scene && scene.lastHit) || {}, search });
    });

    window.addEventListener("beforeunload", () => tooltip.remove());
  }

  // ─── 3D canvas renderer ──────────────────────────────────────────────
  function _render3D(stage, graph, ctx) {
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    let W = stage.clientWidth || 800, H = stage.clientHeight || 560;
    const cv = document.createElement("canvas");
    cv.style.width = "100%"; cv.style.height = "100%";
    cv.style.cursor = "grab";
    stage.appendChild(cv);
    const g = cv.getContext("2d");

    function resize() {
      W = stage.clientWidth || 800; H = stage.clientHeight || 560;
      cv.width = W * DPR; cv.height = H * DPR;
      g.setTransform(DPR, 0, 0, DPR, 0, 0);
    }
    resize();
    const onResize = () => resize();
    window.addEventListener("resize", onResize);

    // ---- node set (capped to highest-degree) ----
    const deg = {};
    graph.edges.forEach(e => { deg[e.src] = (deg[e.src] || 0) + 1; deg[e.dst] = (deg[e.dst] || 0) + 1; });
    let src = graph.nodes.slice();
    if (src.length > MAX_NODES) {
      src = src.slice().sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0)).slice(0, MAX_NODES);
    }
    // Order by (folder, -degree) so same-folder notes land in one region → clusters.
    src.sort((a, b) => {
      const fa = a.folder || "_root_", fb = b.folder || "_root_";
      if (fa < fb) return -1; if (fa > fb) return 1;
      return (deg[b.id] || 0) - (deg[a.id] || 0);
    });

    const R = Math.min(W, H) * 0.42;       // world radius
    const nodes = src.map((n, i) => {
      // Fibonacci sphere over a volume → even spread, ordered placement.
      const t = (i + 0.5) / src.length;
      const phi = Math.acos(1 - 2 * t);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const rad = R * (0.5 + 0.5 * Math.cbrt(t));
      return {
        ...n, deg: deg[n.id] || 0,
        x: rad * Math.sin(phi) * Math.cos(theta),
        y: rad * Math.sin(phi) * Math.sin(theta),
        z: rad * Math.cos(phi),
        fire: 0, _sx: 0, _sy: 0, _sr: 0, _depth: 0,
      };
    });
    const byId = {}; nodes.forEach(n => byId[n.id] = n);
    const edges = graph.edges
      .filter(e => byId[e.src] && byId[e.dst])
      .map(e => ({ a: byId[e.src], b: byId[e.dst] }));

    const neighbors = {};
    edges.forEach(e => {
      (neighbors[e.a.id] = neighbors[e.a.id] || []).push(e.b);
      (neighbors[e.b.id] = neighbors[e.b.id] || []).push(e.a);
    });

    // ---- relax along wikilink springs so linked notes cluster into lobes ----
    (function relax() {
      const REST = R * 0.16, K = 0.08, CENTER = 0.006, STEP = 0.5;
      const iters = nodes.length > 400 ? 40 : 70;
      for (let it = 0; it < iters; it++) {
        for (const n of nodes) { n._fx = -n.x * CENTER; n._fy = -n.y * CENTER; n._fz = -n.z * CENTER; }
        for (const e of edges) {
          const a = e.a, b = e.b;
          let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
          const d = Math.hypot(dx, dy, dz) || 1;
          const f = K * (d - REST) / d;
          a._fx += dx * f; a._fy += dy * f; a._fz += dz * f;
          b._fx -= dx * f; b._fy -= dy * f; b._fz -= dz * f;
        }
        for (const n of nodes) {
          n.x += Math.max(-8, Math.min(8, n._fx * STEP));
          n.y += Math.max(-8, Math.min(8, n._fy * STEP));
          n.z += Math.max(-8, Math.min(8, n._fz * STEP));
        }
      }
    })();

    // ---- camera ----
    let rotY = 0.4, rotX = -0.25, zoom = 1, autoSpin = true;
    const FOCAL = R * 2.6;

    function project(p, ry, rx, cy, sy, cx2, sx2) {
      // rotate Y then X
      const x1 = p.x * cy + p.z * sy;
      const z1 = -p.x * sy + p.z * cy;
      const y1 = p.y * cx2 - z1 * sx2;
      const z2 = p.y * sx2 + z1 * cx2;
      const scale = (FOCAL * zoom) / (FOCAL + z2);
      return { sx: W / 2 + x1 * scale, sy: H / 2 + y1 * scale, depth: z2, scale };
    }

    // cached local radial-gradient glow (keyed by color + radius bucket)
    const gradCache = new Map();
    function glow(color, r) {
      const key = color + "|" + (r | 0);
      let grd = gradCache.get(key);
      if (!grd) {
        grd = g.createRadialGradient(0, 0, 0, 0, 0, r);
        grd.addColorStop(0, "rgba(255,255,255,0.95)");
        grd.addColorStop(0.35, color);
        grd.addColorStop(1, "rgba(0,0,0,0)");
        gradCache.set(key, grd);
      }
      return grd;
    }

    const sparks = [];   // {a,b,t,dur,color}
    function fireEdge(a, b, color) { if (a && b) sparks.push({ a, b, t: 0, color }); }
    function pulseNode(n, big) { if (n) n.fire = Math.max(n.fire, big ? 1 : 0.6); }

    let q = "";
    ctx.search.addEventListener("input", () => { q = ctx.search.value.trim().toLowerCase(); });

    function draw() {
      const cy = Math.cos(rotY), sy = Math.sin(rotY);
      const cx2 = Math.cos(rotX), sx2 = Math.sin(rotX);
      g.clearRect(0, 0, W, H);

      // project all
      for (const n of nodes) {
        const pr = project(n, rotY, rotX, cy, sy, cx2, sx2);
        n._sx = pr.sx; n._sy = pr.sy; n._depth = pr.depth; n._scale = pr.scale;
      }

      // edges (depth-faded), behind nodes
      g.lineWidth = 1;
      for (const e of edges) {
        const a = e.a, b = e.b;
        const fade = Math.max(0.05, Math.min(0.5, 0.6 - (a._depth + b._depth) / (R * 8)));
        g.strokeStyle = (a.fire > 0.05 && b.fire > 0.05)
          ? _folderColor(a.folder) : _folderColorDim(a.folder);
        g.globalAlpha = fade;
        g.beginPath(); g.moveTo(a._sx, a._sy); g.lineTo(b._sx, b._sy); g.stroke();
      }
      g.globalAlpha = 1;

      // sparks (ride the axon in 3D)
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i];
        s.t += 0.02;
        if (s.t >= 1) { sparks.splice(i, 1); continue; }
        const a = s.a, b = s.b;
        const px = a.x + (b.x - a.x) * s.t, py = a.y + (b.y - a.y) * s.t, pz = a.z + (b.z - a.z) * s.t;
        const pr = project({ x: px, y: py, z: pz }, rotY, rotX, cy, sy, cx2, sx2);
        g.globalAlpha = Math.sin(s.t * Math.PI);
        g.fillStyle = s.color;
        g.shadowBlur = 10; g.shadowColor = s.color;
        g.beginPath(); g.arc(pr.sx, pr.sy, 2.6 * pr.scale, 0, Math.PI * 2); g.fill();
        g.shadowBlur = 0;
      }
      g.globalAlpha = 1;

      // nodes — far first (painter's algorithm)
      const order = nodes.slice().sort((a, b) => b._depth - a._depth);
      for (const n of order) {
        const base = (4 + Math.min(9, n.deg * 0.7)) * n._scale;
        const fireBoost = n.fire > 0 ? (1 + n.fire * 0.5) : 1;
        const match = q && (n.title || "").toLowerCase().includes(q);
        const r = (match ? base + 4 : base) * fireBoost;
        const col = _folderColor(n.folder);
        // depth alpha: nearer = brighter
        const da = Math.max(0.35, Math.min(1, 0.7 + n._depth / (R * 6)));
        g.globalAlpha = da;
        g.save();
        g.translate(n._sx, n._sy);
        if (n.fire > 0 || match) { g.shadowBlur = 16; g.shadowColor = col; }
        g.fillStyle = glow(col, Math.max(3, r * 1.7));
        g.beginPath(); g.arc(0, 0, Math.max(3, r * 1.7), 0, Math.PI * 2); g.fill();
        g.restore();
        if (n.fire > 0) n.fire = Math.max(0, n.fire - 0.012);
      }
      g.globalAlpha = 1; g.shadowBlur = 0;

      if (autoSpin && !dragging) rotY += 0.0016;
      raf = requestAnimationFrame(draw);
    }
    let raf = requestAnimationFrame(draw);

    // ---- interaction ----
    let dragging = false, lx = 0, ly = 0, moved = 0;
    cv.addEventListener("mousedown", (e) => { dragging = true; lx = e.clientX; ly = e.clientY; moved = 0; cv.style.cursor = "grabbing"; });
    window.addEventListener("mouseup", () => { dragging = false; cv.style.cursor = "grab"; });
    window.addEventListener("mousemove", (e) => {
      if (dragging) {
        const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
        moved += Math.abs(dx) + Math.abs(dy);
        rotY += dx * 0.005; rotX = Math.max(-1.3, Math.min(1.3, rotX + dy * 0.005));
      }
    });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      zoom = Math.max(0.4, Math.min(3, zoom * (e.deltaY < 0 ? 1.1 : 0.9)));
    }, { passive: false });

    // hover tooltip (hit-test nearest projected node)
    cv.addEventListener("mousemove", (e) => {
      if (dragging) { ctx.tooltip.style.display = "none"; return; }
      const rect = cv.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      let best = null, bestD = 16;
      for (const n of nodes) {
        const d = Math.hypot(n._sx - mx, n._sy - my);
        if (d < bestD && n._depth > -R) { bestD = d; best = n; }
      }
      if (!best) { ctx.tooltip.style.display = "none"; return; }
      const last = ctx.lastHit[best.id];
      const when = last ? new Date(last).toLocaleTimeString([], { hour12: false }) : "—";
      ctx.tooltip.innerHTML =
        `<div class="brain-tip__title">${escapeHtml(best.title)}</div>` +
        `<div class="brain-tip__row"><span class="brain-tip__swatch" style="background:${_folderColor(best.folder)}"></span>` +
        `<span>${escapeHtml(best.folder === "_root_" ? "(vault root)" : best.folder)}</span></div>` +
        `<div class="brain-tip__path">${escapeHtml(best.path || "")}</div>` +
        `<div class="brain-tip__stats"><span>${best.deg} links</span><span>·</span><span>last fired: ${when}</span></div>`;
      ctx.tooltip.style.display = "block";
      ctx.tooltip.style.left = Math.min(e.clientX + 14, window.innerWidth - ctx.tooltip.offsetWidth - 8) + "px";
      ctx.tooltip.style.top = Math.min(e.clientY + 14, window.innerHeight - ctx.tooltip.offsetHeight - 8) + "px";
    });
    cv.addEventListener("mouseleave", () => { ctx.tooltip.style.display = "none"; });

    // ---- firing: RAG hits + ambient ----
    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => {
        const now = Date.now();
        (e.notes || []).forEach((nt) => {
          const id = (nt.title || "").toLowerCase();
          const node = byId[id];
          if (!node) return;
          ctx.lastHit[id] = now;
          pulseNode(node, true);
          (neighbors[id] || []).slice(0, 6).forEach((dst) => {
            fireEdge(node, dst, _folderColor(node.folder));
            setTimeout(() => pulseNode(dst, false), 600);
          });
        });
      });
      EventBus.replayHistory(50);
    }
    const ambient = setInterval(() => {
      if (!edges.length) return;
      for (let i = 0; i < AMBIENT_SPARKS_PER_TICK; i++) {
        const e = edges[(Math.random() * edges.length) | 0];
        fireEdge(e.a, e.b, _folderColor(e.a.folder));
        if (Math.random() < 0.3) pulseNode(e.a, false);
      }
    }, AMBIENT_INTERVAL_MS);

    function destroy() {
      cancelAnimationFrame(raf);
      clearInterval(ambient);
      window.removeEventListener("resize", onResize);
    }
    return { destroy, lastHit: ctx.lastHit };
  }

  window.BrainViz = { mount };
})();
