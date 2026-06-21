/**
 * brain_viz.js — LIVE visualization of the Obsidian "second brain".
 *
 * Force-directed graph of the vault (nodes = notes, edges = wikilinks),
 * colored by top-level folder so each cluster is visually distinct.
 *
 * Neuron firing:
 *   - When the backend RAG fires (rag.hit), matched nodes pulse + their edges
 *     emit a TRAVELING SPARK along the link (source -> target), like a signal
 *     down an axon. Neighbor nodes briefly receive a soft secondary pulse.
 *   - Ambient idle firing: a low-rate random spark every few seconds so the
 *     brain feels alive even when nothing is happening.
 *
 * Hover: rich HTML tooltip with title, folder (color-swatch), path, connection
 * count, and last-RAG-hit timestamp.
 *
 * Uses D3.js v7 force layout (CDN with offline canvas fallback).
 */
(function () {
  "use strict";

  const D3_CDN = "https://d3js.org/d3.v7.min.js";
  // Ambient spark cadence (ms between random firings) when D3 is available.
  // Lower = busier "brain at rest" twinkle. Several sparks fire per tick.
  const AMBIENT_INTERVAL_MS = 600;
  const AMBIENT_SPARKS_PER_TICK = 3;

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  // Deterministic folder -> HSL color (stable across reloads, no clashes).
  function _folderColor(folder) {
    let h = 0;
    const s = String(folder || "_root_");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    const hue = Math.abs(h) % 360;
    return `hsl(${hue}, 80%, 62%)`;
  }
  function _folderColorDim(folder) {
    let h = 0;
    const s = String(folder || "_root_");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    const hue = Math.abs(h) % 360;
    return `hsla(${hue}, 60%, 50%, 0.22)`;
  }

  function _loadD3() {
    return new Promise((resolve) => {
      if (window.d3) return resolve(true);
      const s = document.createElement("script");
      s.src = D3_CDN;
      s.onload = () => resolve(!!window.d3);
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
      setTimeout(() => resolve(!!window.d3), 4000);
    });
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("viz", "viz--brain");

    // Top bar
    const bar = _el("div", "viz__toolbar");
    bar.appendChild(_el("div", "viz__title", "◈ OBSIDIAN BRAIN"));
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

    // Stage + tooltip
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
        // Legend swatches
        legend.innerHTML = "";
        Array.from(folders).sort().forEach((f) => {
          const item = _el("span", "brain-legend__item");
          const sw   = _el("span", "brain-legend__swatch");
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
    if (!graph || !graph.nodes.length) {
      tooltip.remove();
      return;
    }
    const haveD3 = await _loadD3();
    const ctx = { tooltip, lastHit: {}, search };
    if (haveD3) _renderD3(stage, graph, ctx);
    else        _renderCanvas(stage, graph, ctx);

    refreshBtn.addEventListener("click", async () => {
      const g2 = await load(true);
      if (!g2) return;
      stage.innerHTML = "";
      const ctx2 = { tooltip, lastHit: ctx.lastHit, search };
      if (window.d3) _renderD3(stage, g2, ctx2);
      else           _renderCanvas(stage, g2, ctx2);
    });

    // Clean up tooltip when window closes
    window.addEventListener("beforeunload", () => tooltip.remove());
  }

  // ─── D3 renderer with traveling-spark firings ───────────────────────
  function _renderD3(stage, graph, ctx) {
    const d3 = window.d3;
    const W = stage.clientWidth  || 800;
    const H = stage.clientHeight || 560;
    const nodes = graph.nodes.map((n) => ({ ...n }));
    const links = graph.edges
      .map((e) => ({ source: e.src, target: e.dst }))
      .filter((e) => nodes.some(n => n.id === e.source) &&
                     nodes.some(n => n.id === e.target));

    // Pre-compute degree for tooltip
    const degree = {};
    links.forEach((l) => {
      degree[l.source] = (degree[l.source] || 0) + 1;
      degree[l.target] = (degree[l.target] || 0) + 1;
    });

    // Neighbor index for secondary pulses
    const neighbors = {};
    links.forEach((l) => {
      (neighbors[l.source] = neighbors[l.source] || new Set()).add(l.target);
      (neighbors[l.target] = neighbors[l.target] || new Set()).add(l.source);
    });

    const svg = d3.select(stage).append("svg")
      .attr("viewBox", `0 0 ${W} ${H}`)
      .style("width", "100%").style("height", "100%");

    // <defs> for the glow filter (gives the spark its halo)
    const defs = svg.append("defs");
    const filter = defs.append("filter")
      .attr("id", "brain-glow")
      .attr("x", "-50%").attr("y", "-50%")
      .attr("width", "200%").attr("height", "200%");
    filter.append("feGaussianBlur").attr("stdDeviation", "2.5").attr("result", "b");
    const merge = filter.append("feMerge");
    merge.append("feMergeNode").attr("in", "b");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    // Stronger glow used only while a node is firing — makes the circle itself
    // bloom with light (no surrounding ring).
    const filterS = defs.append("filter")
      .attr("id", "brain-glow-strong")
      .attr("x", "-150%").attr("y", "-150%")
      .attr("width", "400%").attr("height", "400%");
    filterS.append("feGaussianBlur").attr("stdDeviation", "6").attr("result", "b");
    const mergeS = filterS.append("feMerge");
    mergeS.append("feMergeNode").attr("in", "b");
    mergeS.append("feMergeNode").attr("in", "SourceGraphic");

    // Spread the graph to fill the stage instead of clustering in the centre:
    // stronger repulsion + longer links + bigger collision radius.
    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(d => d.id).distance(95).strength(0.18))
      .force("charge", d3.forceManyBody().strength(-340))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("x", d3.forceX(W / 2).strength(0.04))
      .force("y", d3.forceY(H / 2).strength(0.04))
      .force("collide", d3.forceCollide().radius(18));

    // Quadratic-bezier control point for a link — midpoint nudged
    // perpendicular so edges curve like dendrites instead of straight wires.
    // Stored on the datum so the path renderer and the spark animator agree.
    function _computeCtrl(d) {
      const sx = d.source.x, sy = d.source.y, tx = d.target.x, ty = d.target.y;
      const mx = (sx + tx) / 2, my = (sy + ty) / 2;
      const dx = tx - sx, dy = ty - sy;
      const len = Math.hypot(dx, dy) || 1;
      // perpendicular unit vector * curvature (deterministic sign per edge)
      const sign = (d._sign ??= ((sx * 31 + sy * 17 + tx) | 0) % 2 ? 1 : -1);
      const off = len * 0.18 * sign;
      d._cx = mx + (-dy / len) * off;
      d._cy = my + ( dx / len) * off;
      return d;
    }
    // Point along the quadratic curve at parameter t∈[0,1].
    function _curvePoint(d, t) {
      const u = 1 - t;
      const x = u * u * d.source.x + 2 * u * t * d._cx + t * t * d.target.x;
      const y = u * u * d.source.y + 2 * u * t * d._cy + t * t * d.target.y;
      return [x, y];
    }

    const linkSel = svg.append("g").attr("class", "brain-edges")
      .selectAll("path").data(links).enter().append("path")
      .attr("fill", "none")
      .attr("stroke", (d) => _folderColorDim((nodes.find(n => n.id === d.source.id || n.id === d.source) || {}).folder))
      .attr("stroke-width", 1.1)
      .attr("stroke-linecap", "round");

    // Layer for traveling sparks (drawn above edges, below nodes)
    const sparkLayer = svg.append("g").attr("class", "brain-sparks");

    const _radius = (d) => 6 + Math.min(11, (degree[d.id] || 0) * 0.8);

    // Per-node radial gradient → glowing "soma": bright core, folder-colored
    // body, transparent rim. Makes nodes read as neurons, not flat dots.
    nodes.forEach((d, i) => {
      const col = _folderColor(d.folder);
      const grad = defs.append("radialGradient")
        .attr("id", `soma-${i}`).attr("cx", "38%").attr("cy", "35%").attr("r", "70%");
      grad.append("stop").attr("offset", "0%").attr("stop-color", "#fff").attr("stop-opacity", 0.95);
      grad.append("stop").attr("offset", "32%").attr("stop-color", col).attr("stop-opacity", 1);
      grad.append("stop").attr("offset", "100%").attr("stop-color", col).attr("stop-opacity", 0.35);
      d._gradId = `soma-${i}`;
    });

    const nodeSel = svg.append("g").attr("class", "brain-nodes")
      .selectAll("circle").data(nodes).enter().append("circle")
      .attr("r", _radius)
      .attr("fill", (d) => `url(#${d._gradId})`)
      .attr("stroke", (d) => _folderColor(d.folder))
      .attr("stroke-opacity", 0.9)
      .attr("stroke-width", 1)
      .attr("class", "brain-node")
      .style("filter", "url(#brain-glow)")
      .call(d3.drag()
        .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    // Keep every node inside the visible stage (viewBox coords). Clamp each
    // tick so the force layout — and dragging — can never push a node, or its
    // glow, off-screen. PAD leaves room for the node radius + its aura.
    const BOUND_PAD = 16;
    sim.on("tick", () => {
      nodes.forEach((d) => {
        const r = _radius(d) + BOUND_PAD;
        d.x = Math.max(r, Math.min(W - r, d.x));
        d.y = Math.max(r, Math.min(H - r, d.y));
      });
      linkSel.attr("d", (d) => {
        _computeCtrl(d);
        return `M${d.source.x},${d.source.y} Q${d._cx},${d._cy} ${d.target.x},${d.target.y}`;
      });
      nodeSel.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
    });

    // ── Tooltip ──────────────────────────────────────────────────────
    function showTip(evt, d) {
      const lastHit = ctx.lastHit[d.id];
      const when = lastHit
        ? new Date(lastHit).toLocaleTimeString([], { hour12: false })
        : "—";
      ctx.tooltip.innerHTML = `
        <div class="brain-tip__title">${escapeHtml(d.title)}</div>
        <div class="brain-tip__row">
          <span class="brain-tip__swatch" style="background:${_folderColor(d.folder)}"></span>
          <span>${escapeHtml(d.folder === "_root_" ? "(vault root)" : d.folder)}</span>
        </div>
        <div class="brain-tip__path">${escapeHtml(d.path || "")}</div>
        <div class="brain-tip__stats">
          <span>${degree[d.id] || 0} links</span>
          <span>·</span>
          <span>last fired: ${when}</span>
        </div>
      `;
      ctx.tooltip.style.display = "block";
      moveTip(evt);
    }
    function moveTip(evt) {
      const x = evt.clientX + 14;
      const y = evt.clientY + 14;
      // Keep on-screen
      const t = ctx.tooltip;
      const r = t.getBoundingClientRect();
      const maxX = window.innerWidth  - r.width  - 8;
      const maxY = window.innerHeight - r.height - 8;
      t.style.left = Math.min(x, maxX) + "px";
      t.style.top  = Math.min(y, maxY) + "px";
    }
    function hideTip() { ctx.tooltip.style.display = "none"; }
    nodeSel.on("mouseenter", showTip)
           .on("mousemove",  moveTip)
           .on("mouseleave", hideTip);

    // ── Firing: send a traveling spark along an edge ─────────────────
    function fireEdge(srcNode, dstNode, color) {
      if (!srcNode || !dstNode) return;
      // Build the same curved segment the edge uses, so the spark rides the
      // dendrite's arc like a real action potential.
      const seg = { source: srcNode, target: dstNode };
      _computeCtrl(seg);
      const p0 = _curvePoint(seg, 0);
      const spark = sparkLayer.append("circle")
        .attr("r", 3)
        .attr("fill", color)
        .attr("opacity", 1)
        .attr("cx", p0[0]).attr("cy", p0[1])
        .style("filter", "url(#brain-glow)");
      spark.transition()
        .duration(720)
        .ease(d3.easeQuadInOut)
        .attrTween("cx", () => (t) => _curvePoint(seg, t)[0])
        .attrTween("cy", () => (t) => _curvePoint(seg, t)[1])
        .attr("r", 4.5)
        .attr("opacity", 0)
        .on("end", function () { d3.select(this).remove(); });
    }

    // Firing = the node CIRCLE itself glowing brighter, then slowly fading
    // back. No surrounding ring — just the soma blooming with light via the
    // stronger glow filter + a brief brightening, eased out over ~2s.
    function pulseNode(node, big) {
      if (!node) return;
      const sel = nodeSel.filter((d) => d.id === node.id);
      const baseR = _radius(node);
      const dur = big ? 2400 : 1800;
      sel.interrupt()
        .style("filter", "url(#brain-glow-strong)")
        .attr("stroke", "#fff")
        .attr("stroke-opacity", 1)
        .attr("stroke-width", big ? 2.2 : 1.6)
        .attr("r", baseR * (big ? 1.35 : 1.2))
        .transition().duration(dur).ease(d3.easeSinOut)
        .attr("r", baseR)
        .attr("stroke", _folderColor(node.folder))
        .attr("stroke-opacity", 0.9)
        .attr("stroke-width", 1)
        .on("end", function () { d3.select(this).style("filter", "url(#brain-glow)"); });
    }

    // ── RAG hit subscription: primary node pulses + sparks to neighbors ──
    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => {
        const hits = new Set();
        (e.notes || []).forEach((n) => {
          const key = (n.title || "").toLowerCase();
          if (nodes.find(x => x.id === key)) hits.add(key);
        });
        const now = Date.now();
        hits.forEach((id) => {
          const node = nodes.find(n => n.id === id);
          if (!node) return;
          ctx.lastHit[id] = now;
          pulseNode(node, true);
          // Fan out a spark to each neighbor (cap at 6 so it stays readable)
          const neigh = Array.from(neighbors[id] || []).slice(0, 6);
          neigh.forEach((nid) => {
            const dst = nodes.find(n => n.id === nid);
            fireEdge(node, dst, _folderColor(node.folder));
            // Soft secondary pulse on the receiving end (delayed)
            setTimeout(() => pulseNode(dst, false), 600);
          });
        });
      });
      EventBus.replayHistory(50);
    }

    // ── Ambient idle firing — a busy "brain at rest" twinkle ─────────
    // Fire several sparks per tick and occasionally pulse the firing node so
    // the network visibly crackles with activity even when idle.
    const ambient = setInterval(() => {
      if (!links.length) return;
      for (let i = 0; i < AMBIENT_SPARKS_PER_TICK; i++) {
        const l = links[(Math.random() * links.length) | 0];
        fireEdge(l.source, l.target, _folderColor(l.source.folder || "_root_"));
        if (Math.random() < 0.35) pulseNode(l.source, false);
      }
    }, AMBIENT_INTERVAL_MS);
    window.addEventListener("beforeunload", () => clearInterval(ambient));

    // ── Search filter ────────────────────────────────────────────────
    ctx.search.addEventListener("input", () => {
      const q = ctx.search.value.trim().toLowerCase();
      nodeSel
        .classed("brain-node--match", (d) => q && d.title.toLowerCase().includes(q))
        .attr("r", (d) => {
          const base = _radius(d);
          return (q && d.title.toLowerCase().includes(q)) ? base + 4 : base;
        });
    });
  }

  // ─── Canvas fallback (offline, no D3) ────────────────────────────────
  function _renderCanvas(stage, graph, ctx) {
    const W = stage.clientWidth  || 800;
    const H = stage.clientHeight || 560;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const c2 = cv.getContext("2d");
    const golden = Math.PI * (3 - Math.sqrt(5));
    const cx = W / 2, cy = H / 2;
    const nodes = graph.nodes.map((n, i) => {
      const r = 8 * Math.sqrt(i + 1);
      const a = i * golden;
      return { ...n, x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), fire: 0 };
    });
    const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edges = graph.edges.filter(e => byId[e.src] && byId[e.dst]);

    function draw() {
      c2.clearRect(0, 0, W, H);
      edges.forEach((e) => {
        const a = byId[e.src], b = byId[e.dst];
        c2.strokeStyle = (a.fire && b.fire) ? _folderColor(a.folder) : _folderColorDim(a.folder);
        c2.lineWidth = (a.fire && b.fire) ? 1.2 : 0.4;
        c2.beginPath(); c2.moveTo(a.x, a.y); c2.lineTo(b.x, b.y); c2.stroke();
      });
      nodes.forEach((n) => {
        c2.beginPath();
        c2.arc(n.x, n.y, n.fire > 0 ? 6 : 3, 0, Math.PI * 2);
        c2.fillStyle = _folderColor(n.folder);
        c2.fill();
        if (n.fire > 0) n.fire -= 1;
      });
      requestAnimationFrame(draw);
    }
    draw();

    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => {
        (e.notes || []).forEach((nt) => {
          const k = (nt.title || "").toLowerCase();
          if (byId[k]) {
            byId[k].fire = 60;
            ctx.lastHit[k] = Date.now();
          }
        });
      });
      EventBus.replayHistory(50);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]
    ));
  }

  window.BrainViz = { mount };
})();
