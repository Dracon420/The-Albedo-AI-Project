/**
 * brain_viz.js — LIVE 3D "Brain Atlas" of the Obsidian second brain.
 *
 * The vault (nodes = notes, edges = wikilinks) is laid out as an anatomical
 * brain: each top-level folder becomes a lobe REGION pinned to a fixed point in
 * a brain-shaped ellipsoid (frontal/parietal/temporal/occipital/cerebellum/
 * brain-stem…). Notes cluster tightly around their region anchor, a faint
 * "brain shell" point cloud fills the silhouette, and region labels float in 3D.
 *
 * Pure Canvas 2D — rotates, drag to spin, wheel to zoom. No Three.js / WebGL /
 * CDN, so it works fully offline. RAG hits pulse nodes + fire axon sparks.
 */
(function () {
  "use strict";

  const AMBIENT_INTERVAL_MS = 650;
  const AMBIENT_SPARKS_PER_TICK = 3;
  const MAX_NODES = 700;
  const SHELL_POINTS = 420;

  // Anatomical lobes (unit-ellipsoid anchors + palette), in display order.
  const REGION_DEFS = [
    { key: "PARIETAL",   sub: "Concepts · Tools",     color: "#4ee1ff", a: [ 0.00,  0.92, -0.05] },
    { key: "FRONTAL",    sub: "Projects · Decisions", color: "#ffb14e", a: [ 0.00,  0.34,  0.95] },
    { key: "TEMPORAL",   sub: "People · Orgs",        color: "#b988ff", a: [-0.95, -0.08,  0.18] },
    { key: "OCCIPITAL",  sub: "Sources · Repos",      color: "#5dff9b", a: [ 0.00,  0.24, -0.98] },
    { key: "CEREBELLUM", sub: "Daily · Incidents",    color: "#ff77ad", a: [ 0.00, -0.58, -0.72] },
    { key: "BRAIN STEM", sub: "Index · Routing",      color: "#ffd24e", a: [ 0.00, -0.94, -0.08] },
    { key: "LIMBIC",     sub: "Memory · Links",       color: "#7fd0ff", a: [ 0.92, -0.05,  0.20] },
    { key: "INSULA",     sub: "Salience",             color: "#ff9d5c", a: [-0.48,  0.42,  0.55] },
  ];

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }
  function _hashHue(s) {
    let h = 0; s = String(s || "_root_");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return Math.abs(h) % 360;
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("viz", "viz--brain");

    const bar = _el("div", "viz__toolbar");
    bar.appendChild(_el("div", "viz__title", "◈ OBSIDIAN BRAIN — ATLAS"));
    const status = _el("div", "viz__status", "loading vault…");
    bar.appendChild(status);
    const search = document.createElement("input");
    search.type = "text"; search.placeholder = "highlight note…"; search.className = "viz__search";
    bar.appendChild(search);
    const refreshBtn = _el("button", "cmd-btn", "REFRESH");
    bar.appendChild(refreshBtn);
    root.appendChild(bar);

    const stage = _el("div", "viz__stage");
    root.appendChild(stage);
    const legend = _el("div", "brain-legend brain-legend--regions");
    root.appendChild(legend);

    const tooltip = _el("div", "brain-tip");
    tooltip.style.display = "none";
    document.body.appendChild(tooltip);

    async function load(refresh) {
      status.textContent = refresh ? "rebuilding vault graph…" : "loading vault…";
      try {
        const g = await eel.get_vault_graph(!!refresh)();
        if (!g || !g.ok) { status.textContent = "vault unavailable: " + (g && g.error || "unknown"); return null; }
        return g;
      } catch (e) { status.textContent = "bridge error: " + e; return null; }
    }

    const graph = await load(false);
    if (!graph || !graph.nodes.length) { tooltip.remove(); return; }

    let scene = _render3D(stage, graph, { tooltip, lastHit: {}, search, status, legend });
    refreshBtn.addEventListener("click", async () => {
      const g2 = await load(true);
      if (!g2 || !g2.nodes.length) return;
      if (scene && scene.destroy) scene.destroy();
      stage.innerHTML = "";
      scene = _render3D(stage, g2, { tooltip, lastHit: (scene && scene.lastHit) || {}, search, status, legend });
    });
    window.addEventListener("beforeunload", () => tooltip.remove());
  }

  function _render3D(stage, graph, ctx) {
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    let W = stage.clientWidth || 800, H = stage.clientHeight || 560;
    const cv = document.createElement("canvas");
    cv.style.width = "100%"; cv.style.height = "100%"; cv.style.cursor = "grab";
    stage.appendChild(cv);
    const g = cv.getContext("2d");
    function resize() { W = stage.clientWidth || 800; H = stage.clientHeight || 560; cv.width = W * DPR; cv.height = H * DPR; g.setTransform(DPR, 0, 0, DPR, 0, 0); }
    resize();
    const onResize = () => resize();
    window.addEventListener("resize", onResize);

    const R = Math.min(W, H) * 0.40;
    // Brain ellipsoid: widest L-R-ish and front-back, shorter top-bottom.
    // Lobes spread to fill the frame (like the reference) yet stay linked by
    // the edge web into one connected brain.
    const EX = R * 0.92, EY = R * 0.70, EZ = R * 1.02;

    // ---- nodes (capped to highest-degree) ----
    const deg = {};
    graph.edges.forEach(e => { deg[e.src] = (deg[e.src] || 0) + 1; deg[e.dst] = (deg[e.dst] || 0) + 1; });
    let src = graph.nodes.slice();
    if (src.length > MAX_NODES) src = src.sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0)).slice(0, MAX_NODES);

    // ---- folders -> anatomical regions ----
    const counts = {};
    src.forEach(n => { const f = n.folder || "_root_"; counts[f] = (counts[f] || 0) + 1; });
    const folders = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    const regionOf = {};
    const regions = folders.map((f, i) => {
      let d;
      if (i < REGION_DEFS.length) d = REGION_DEFS[i];
      else {
        const t = (i + 0.5) / folders.length, phi = Math.acos(1 - 2 * t), th = Math.PI * (1 + Math.sqrt(5)) * i;
        d = { key: "REGION " + (i + 1), sub: f === "_root_" ? "(root)" : f,
              color: `hsl(${_hashHue(f)},80%,62%)`, a: [Math.sin(phi) * Math.cos(th), Math.cos(phi), Math.sin(phi) * Math.sin(th)] };
      }
      const reg = { key: d.key, sub: d.sub, color: d.color, folder: f, count: counts[f],
                    wx: d.a[0] * EX, wy: d.a[1] * EY, wz: d.a[2] * EZ, _sx: 0, _sy: 0, _depth: 0 };
      regionOf[f] = reg;
      return reg;
    });

    // sidebar: anatomical regions
    if (ctx.legend) {
      ctx.legend.innerHTML = "";
      const head = _el("div", "brain-legend__head", "ANATOMICAL REGIONS");
      ctx.legend.appendChild(head);
      regions.forEach(r => {
        const item = _el("div", "brain-legend__region");
        const sw = _el("span", "brain-legend__swatch"); sw.style.background = r.color;
        const tx = _el("span", "brain-legend__rlabel");
        tx.appendChild(_el("b", null, r.key));
        tx.appendChild(_el("span", "brain-legend__rsub", "  " + (r.folder === "_root_" ? "(root)" : r.folder)));
        const ct = _el("span", "brain-legend__count", String(r.count));
        item.appendChild(sw); item.appendChild(tx); item.appendChild(ct);
        ctx.legend.appendChild(item);
      });
    }
    if (ctx.status) ctx.status.textContent = `${src.length} notes · ${graph.edges.length} links · ${regions.length} regions`;

    const nodes = src.map(n => {
      const reg = regionOf[n.folder || "_root_"];
      return { ...n, deg: deg[n.id] || 0, reg,
        x: reg.wx + (Math.random() - 0.5) * R * 0.3,
        y: reg.wy + (Math.random() - 0.5) * R * 0.3,
        z: reg.wz + (Math.random() - 0.5) * R * 0.3,
        fire: 0, _sx: 0, _sy: 0, _depth: 0, _scale: 1 };
    });
    const byId = {}; nodes.forEach(n => byId[n.id] = n);
    const edges = graph.edges.filter(e => byId[e.src] && byId[e.dst]).map(e => ({ a: byId[e.src], b: byId[e.dst] }));
    // Small vaults get bigger nodes so the few notes still fill the brain
    // (a 24-note vault shouldn't render as specks like a 700-note one).
    const densityK = Math.min(1.6, Math.max(1, Math.sqrt(90 / Math.max(8, nodes.length))));
    const neighbors = {};
    edges.forEach(e => { (neighbors[e.a.id] = neighbors[e.a.id] || []).push(e.b); (neighbors[e.b.id] = neighbors[e.b.id] || []).push(e.a); });

    // ---- layout: strong pull to region anchor (tight clusters) + gentle local
    //      repulsion (spread within a lobe) + mild link attraction ----
    (function layout() {
      const ANCHOR = 0.14, REP = R * R * 0.12, LINK = 0.012, SEP = R * 0.16;
      const iters = nodes.length > 400 ? 70 : 110;
      for (let it = 0; it < iters; it++) {
        for (const a of nodes) {
          a._dx = (a.reg.wx - a.x) * ANCHOR;
          a._dy = (a.reg.wy - a.y) * ANCHOR;
          a._dz = (a.reg.wz - a.z) * ANCHOR;
        }
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
            const d2 = dx * dx + dy * dy + dz * dz + 1;
            if (d2 > SEP * SEP * 9) continue;          // only push near pairs apart
            const f = REP / d2, d = Math.sqrt(d2);
            dx /= d; dy /= d; dz /= d;
            a._dx += dx * f; a._dy += dy * f; a._dz += dz * f;
            b._dx -= dx * f; b._dy -= dy * f; b._dz -= dz * f;
          }
        }
        for (const e of edges) {
          const a = e.a, b = e.b;
          a._dx += (b.x - a.x) * LINK; a._dy += (b.y - a.y) * LINK; a._dz += (b.z - a.z) * LINK;
          b._dx += (a.x - b.x) * LINK; b._dy += (a.y - b.y) * LINK; b._dz += (a.z - b.z) * LINK;
        }
        const cap = R * 0.08;
        for (const a of nodes) {
          a.x += Math.max(-cap, Math.min(cap, a._dx));
          a.y += Math.max(-cap, Math.min(cap, a._dy));
          a.z += Math.max(-cap, Math.min(cap, a._dz));
        }
      }
    })();

    // ---- decorative brain-shell point cloud (fills the silhouette) ----
    const shell = [];
    for (let i = 0; i < SHELL_POINTS; i++) {
      const t = (i + 0.5) / SHELL_POINTS, phi = Math.acos(1 - 2 * t), th = Math.PI * (1 + Math.sqrt(5)) * i;
      const j = 0.94 + Math.random() * 0.08;
      shell.push({ x: Math.sin(phi) * Math.cos(th) * EX * j, y: Math.cos(phi) * EY * j, z: Math.sin(phi) * Math.sin(th) * EZ * j });
    }

    // ---- camera ----
    let rotY = 0.5, rotX = -0.22, zoom = 1, dragging = false;
    const FOCAL = R * 2.7;
    function proj(p, cy, sy, cx, sx) {
      const x1 = p.x * cy + p.z * sy, z1 = -p.x * sy + p.z * cy;
      const y1 = p.y * cx - z1 * sx, z2 = p.y * sx + z1 * cx;
      const scale = (FOCAL * zoom) / (FOCAL + z2);
      return { sx: W / 2 + x1 * scale, sy: H / 2 + y1 * scale, depth: z2, scale };
    }

    const sparks = [];
    function fireEdge(a, b, color) { if (a && b) sparks.push({ a, b, t: 0, color }); }
    function pulseNode(n, big) { if (n) n.fire = Math.max(n.fire, big ? 1 : 0.6); }
    let q = "";
    ctx.search.addEventListener("input", () => { q = ctx.search.value.trim().toLowerCase(); });

    let showLabels = true;

    function draw() {
      const cy = Math.cos(rotY), sy = Math.sin(rotY), cx = Math.cos(rotX), sx = Math.sin(rotX);
      g.clearRect(0, 0, W, H);

      // brain shell (faint, behind everything)
      g.fillStyle = "rgba(150,180,255,0.05)";
      for (const p of shell) {
        const pr = proj(p, cy, sy, cx, sx);
        const a = Math.max(0.02, 0.10 + pr.depth / (R * 10));
        g.globalAlpha = a;
        g.beginPath(); g.arc(pr.sx, pr.sy, 0.9 * pr.scale, 0, Math.PI * 2); g.fill();
      }
      g.globalAlpha = 1;

      for (const n of nodes) { const pr = proj(n, cy, sy, cx, sx); n._sx = pr.sx; n._sy = pr.sy; n._depth = pr.depth; n._scale = pr.scale; }
      for (const r of regions) { const pr = proj({ x: r.wx, y: r.wy, z: r.wz }, cy, sy, cx, sx); r._sx = pr.sx; r._sy = pr.sy; r._depth = pr.depth; }

      // edges
      g.lineWidth = 1;
      for (const e of edges) {
        const a = e.a, b = e.b;
        const lit = a.fire > 0.05 && b.fire > 0.05;
        g.strokeStyle = lit ? a.reg.color : "rgba(180,200,245,1)";
        g.lineWidth = lit ? 1.5 : 1;
        g.globalAlpha = lit ? 0.6 : Math.max(0.12, 0.32 + (a._depth + b._depth) / (R * 14));
        g.beginPath(); g.moveTo(a._sx, a._sy); g.lineTo(b._sx, b._sy); g.stroke();
      }
      g.globalAlpha = 1;

      // sparks
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i]; s.t += 0.02;
        if (s.t >= 1) { sparks.splice(i, 1); continue; }
        const px = s.a.x + (s.b.x - s.a.x) * s.t, py = s.a.y + (s.b.y - s.a.y) * s.t, pz = s.a.z + (s.b.z - s.a.z) * s.t;
        const pr = proj({ x: px, y: py, z: pz }, cy, sy, cx, sx);
        g.globalAlpha = Math.sin(s.t * Math.PI); g.fillStyle = s.color;
        g.shadowBlur = 10; g.shadowColor = s.color;
        g.beginPath(); g.arc(pr.sx, pr.sy, 2.4 * pr.scale, 0, Math.PI * 2); g.fill();
        g.shadowBlur = 0;
      }
      g.globalAlpha = 1;

      // nodes (far first) — crisp lit spheres tinted by region
      const order = nodes.slice().sort((a, b) => b._depth - a._depth);
      for (const n of order) {
        const base = (1.8 + Math.min(6, n.deg * 0.45)) * densityK * n._scale;
        const match = q && (n.title || "").toLowerCase().includes(q);
        const fb = n.fire > 0 ? (1 + n.fire * 0.7) : 1;
        const r = Math.max(1.2, (match ? base + 3 : base) * fb);
        const col = n.reg.color;
        const da = Math.max(0.4, Math.min(1, 0.8 + n._depth / (R * 6)));
        const sX = n._sx, sY = n._sy;
        g.globalAlpha = da * 0.13; g.fillStyle = col;
        g.beginPath(); g.arc(sX, sY, r * 1.8, 0, Math.PI * 2); g.fill();
        if (n.fire > 0 || match) { g.shadowBlur = 13; g.shadowColor = col; }
        g.globalAlpha = da; g.fillStyle = col;
        g.beginPath(); g.arc(sX, sY, r, 0, Math.PI * 2); g.fill();
        g.shadowBlur = 0;
        g.globalAlpha = da * 0.85; g.fillStyle = "rgba(255,255,255,0.85)";
        g.beginPath(); g.arc(sX - r * 0.2, sY - r * 0.2, r * 0.42, 0, Math.PI * 2); g.fill();
        if (n.fire > 0) n.fire = Math.max(0, n.fire - 0.012);
      }
      g.globalAlpha = 1; g.shadowBlur = 0;

      // region labels (in 3D)
      if (showLabels) {
        // de-collide labels vertically so small/empty regions don't overlap
        const sortedR = regions.slice().sort((a, b) => a._sy - b._sy);
        let prevY = -1e9;
        for (const r of sortedR) {
          r._ly = (r._sy - prevY < 26) ? prevY + 26 : r._sy;
          prevY = r._ly;
        }
        g.textAlign = "left"; g.textBaseline = "middle";
        for (const r of regions) {
          // anchor dot at the true 3D position
          g.globalAlpha = 0.9; g.fillStyle = r.color;
          g.beginPath(); g.arc(r._sx, r._sy, 2.6, 0, Math.PI * 2); g.fill();
          // faint leader from anchor to de-collided label
          if (Math.abs(r._ly - r._sy) > 2) {
            g.globalAlpha = 0.3; g.strokeStyle = r.color; g.lineWidth = 1;
            g.beginPath(); g.moveTo(r._sx + 4, r._sy); g.lineTo(r._sx + 8, r._ly); g.stroke();
          }
          g.globalAlpha = 1;
          g.font = "700 12px 'Courier New', monospace"; g.fillStyle = r.color;
          g.fillText(r.key, r._sx + 10, r._ly - 5);
          g.font = "10px 'Courier New', monospace"; g.fillStyle = "rgba(190,205,235,0.7)";
          g.fillText(`${r.sub} · ${r.count} notes`, r._sx + 10, r._ly + 7);
        }
        g.textAlign = "start"; g.textBaseline = "alphabetic";
      }

      if (!dragging) rotY += 0.0014;
      raf = requestAnimationFrame(draw);
    }
    let raf = requestAnimationFrame(draw);

    // ---- interaction ----
    let lx = 0, ly = 0;
    cv.addEventListener("mousedown", (e) => { dragging = true; lx = e.clientX; ly = e.clientY; cv.style.cursor = "grabbing"; });
    window.addEventListener("mouseup", () => { dragging = false; cv.style.cursor = "grab"; });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
      rotY += dx * 0.005; rotX = Math.max(-1.3, Math.min(1.3, rotX + dy * 0.005));
    });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); zoom = Math.max(0.4, Math.min(3.5, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); }, { passive: false });
    cv.addEventListener("dblclick", () => { showLabels = !showLabels; });

    cv.addEventListener("mousemove", (e) => {
      if (dragging) { ctx.tooltip.style.display = "none"; return; }
      const rect = cv.getBoundingClientRect(); const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      let best = null, bestD = 14;
      for (const n of nodes) { const d = Math.hypot(n._sx - mx, n._sy - my); if (d < bestD) { bestD = d; best = n; } }
      if (!best) { ctx.tooltip.style.display = "none"; return; }
      const last = ctx.lastHit[best.id]; const when = last ? new Date(last).toLocaleTimeString([], { hour12: false }) : "—";
      ctx.tooltip.innerHTML =
        `<div class="brain-tip__title">${escapeHtml(best.title)}</div>` +
        `<div class="brain-tip__row"><span class="brain-tip__swatch" style="background:${best.reg.color}"></span>` +
        `<span>${escapeHtml(best.reg.key)} · ${escapeHtml(best.folder === "_root_" ? "(root)" : best.folder)}</span></div>` +
        `<div class="brain-tip__path">${escapeHtml(best.path || "")}</div>` +
        `<div class="brain-tip__stats"><span>${best.deg} links</span><span>·</span><span>last fired: ${when}</span></div>`;
      ctx.tooltip.style.display = "block";
      ctx.tooltip.style.left = Math.min(e.clientX + 14, window.innerWidth - ctx.tooltip.offsetWidth - 8) + "px";
      ctx.tooltip.style.top = Math.min(e.clientY + 14, window.innerHeight - ctx.tooltip.offsetHeight - 8) + "px";
    });
    cv.addEventListener("mouseleave", () => { ctx.tooltip.style.display = "none"; });

    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => {
        const now = Date.now();
        (e.notes || []).forEach((nt) => {
          const id = (nt.title || "").toLowerCase(); const node = byId[id]; if (!node) return;
          ctx.lastHit[id] = now; pulseNode(node, true);
          (neighbors[id] || []).slice(0, 6).forEach((dst) => { fireEdge(node, dst, node.reg.color); setTimeout(() => pulseNode(dst, false), 600); });
        });
      });
      EventBus.replayHistory(50);
    }
    const ambient = setInterval(() => {
      if (!edges.length) return;
      for (let i = 0; i < AMBIENT_SPARKS_PER_TICK; i++) { const e = edges[(Math.random() * edges.length) | 0]; fireEdge(e.a, e.b, e.a.reg.color); if (Math.random() < 0.3) pulseNode(e.a, false); }
    }, AMBIENT_INTERVAL_MS);

    function destroy() { cancelAnimationFrame(raf); clearInterval(ambient); window.removeEventListener("resize", onResize); }
    return { destroy, lastHit: ctx.lastHit };
  }

  window.BrainViz = { mount };
})();
