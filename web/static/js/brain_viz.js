/**
 * brain_viz.js — LIVE visualization of the Obsidian "second brain".
 *
 * Renders a force-directed graph of the vault: nodes = notes, edges = wikilinks.
 * When the backend RAG fires (event "rag.hit"), the matched nodes pulse and
 * any edges between them briefly light up — the "synapse firing" effect.
 *
 * Uses D3.js force layout (CDN with offline fallback). The fallback is a
 * lightweight built-in canvas renderer that still shows nodes/edges and
 * highlights firing nodes, just without smooth physics.
 *
 * Usage: BrainViz.mount(rootEl)
 */
(function () {
  "use strict";

  const D3_CDN = "https://d3js.org/d3.v7.min.js";

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function _loadD3() {
    return new Promise((resolve) => {
      if (window.d3) return resolve(true);
      const s = document.createElement("script");
      s.src = D3_CDN;
      s.onload = () => resolve(!!window.d3);
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
      // Hard timeout: if it doesn't load in 4s, give up and use fallback.
      setTimeout(() => resolve(!!window.d3), 4000);
    });
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("viz", "viz--brain");

    // Top bar: title + status + controls
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

    // Stage
    const stage = _el("div", "viz__stage");
    root.appendChild(stage);

    // Fetch the vault graph
    async function load(refresh) {
      status.textContent = refresh ? "rebuilding vault graph…" : "loading vault…";
      try {
        const g = await eel.get_vault_graph(!!refresh)();
        if (!g || !g.ok) {
          status.textContent = "vault unavailable: " + (g && g.error || "unknown");
          return null;
        }
        status.textContent = `${g.nodes.length} notes · ${g.edges.length} links`;
        return g;
      } catch (e) {
        status.textContent = "bridge error: " + e;
        return null;
      }
    }

    const graph = await load(false);
    if (!graph || !graph.nodes.length) return;

    // Try D3; fall back to a minimal canvas renderer.
    const haveD3 = await _loadD3();

    if (haveD3) {
      _renderD3(stage, graph, search);
    } else {
      _renderCanvas(stage, graph, search);
    }

    refreshBtn.addEventListener("click", async () => {
      const g2 = await load(true);
      if (!g2) return;
      stage.innerHTML = "";
      if (window.d3) _renderD3(stage, g2, search);
      else _renderCanvas(stage, g2, search);
    });
  }

  // ─── D3 force-directed renderer ──────────────────────────────────────
  function _renderD3(stage, graph, search) {
    const d3 = window.d3;
    const W = stage.clientWidth  || 800;
    const H = stage.clientHeight || 560;
    const nodes = graph.nodes.map((n) => ({ ...n }));
    const links = graph.edges
      .map((e) => ({ source: e.src, target: e.dst }))
      .filter((e) => nodes.some(n => n.id === e.source) &&
                     nodes.some(n => n.id === e.target));

    const svg = d3.select(stage).append("svg")
      .attr("viewBox", `0 0 ${W} ${H}`)
      .style("width", "100%").style("height", "100%");

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(d => d.id).distance(50).strength(0.25))
      .force("charge", d3.forceManyBody().strength(-110))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide().radius(8));

    const link = svg.append("g").attr("class", "brain-edges")
      .selectAll("line").data(links).enter().append("line");
    const node = svg.append("g").attr("class", "brain-nodes")
      .selectAll("circle").data(nodes).enter().append("circle")
      .attr("r", 4)
      .attr("class", "brain-node")
      .call(d3.drag()
        .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    node.append("title").text((d) => d.title);

    sim.on("tick", () => {
      link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
    });

    // RAG firing: pulse matched nodes + connecting edges
    function pulse(noteList) {
      const ids = new Set();
      noteList.forEach((n) => {
        const key = (n.title || "").toLowerCase();
        if (nodes.find(x => x.id === key)) ids.add(key);
      });
      if (!ids.size) return;
      node.filter((d) => ids.has(d.id))
        .classed("brain-node--fire", true)
        .transition().duration(1600)
        .on("end", function () { d3.select(this).classed("brain-node--fire", false); });
      link.filter((d) => ids.has(d.source.id) && ids.has(d.target.id))
        .classed("brain-edge--fire", true)
        .transition().duration(1600)
        .on("end", function () { d3.select(this).classed("brain-edge--fire", false); });
    }
    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => pulse(e.notes || []));
      EventBus.replayHistory(50);
    }

    // Search filter
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      node.classed("brain-node--match", (d) => q && d.title.toLowerCase().includes(q));
    });
  }

  // ─── Minimal canvas fallback (no physics; static circle pack) ────────
  function _renderCanvas(stage, graph, search) {
    const W = stage.clientWidth  || 800;
    const H = stage.clientHeight || 560;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    stage.appendChild(cv);
    const ctx = cv.getContext("2d");

    // Lay nodes on a phyllotaxis spiral — simple, dense, deterministic.
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
      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(0,217,255,0.08)";
      ctx.lineWidth = 0.5;
      edges.forEach((e) => {
        const a = byId[e.src], b = byId[e.dst];
        const fire = (a.fire > 0 && b.fire > 0);
        ctx.strokeStyle = fire ? "rgba(255,174,0,0.9)" : "rgba(0,217,255,0.10)";
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      });
      nodes.forEach((n) => {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.fire > 0 ? 6 : 3, 0, Math.PI * 2);
        ctx.fillStyle = n.fire > 0 ? "rgba(255,174,0,0.95)" : "rgba(0,217,255,0.75)";
        ctx.fill();
        if (n.fire > 0) n.fire -= 1;
      });
      requestAnimationFrame(draw);
    }
    draw();

    if (window.EventBus) {
      EventBus.on("rag.hit", (e) => {
        (e.notes || []).forEach((nt) => {
          const k = (nt.title || "").toLowerCase();
          if (byId[k]) byId[k].fire = 60;   // ~1s @ 60fps
        });
      });
      EventBus.replayHistory(50);
    }

    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      nodes.forEach((n) => { n.fire = q && n.title.toLowerCase().includes(q) ? 30 : n.fire; });
    });
  }

  window.BrainViz = { mount };
})();
