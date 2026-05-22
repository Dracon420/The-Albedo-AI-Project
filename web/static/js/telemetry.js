// ============================================================
// telemetry.js — poll eel.get_telemetry() at 1 Hz and update the 6 gauges.
//
// Mapping:
//   CPU   <- cpu.percent        sub: cpu.freq_ghz GHz
//   RAM   <- ram.percent        sub: used_gb / total_gb
//   GPU   <- gpu.load_percent   sub: temp °C
//   SSD   <- disk.percent_used_c   sub: VRAM used / total
//   NET   <- max(down,up) Mbps  (small dial — autoscale 0..100 Mbps for the ring)
//   DISK  <- max(r,w) MB/s      (small dial — autoscale 0..200 MB/s for the ring)
// ============================================================

const Telemetry = (() => {
  const POLL_MS = 1000;

  // Soft caps for the small dials so a 1 Gbps burst doesn't peg the ring
  // forever — adjust if your workload calls for higher headroom.
  const NET_CAP_MBPS  = 100;
  const DISK_CAP_MBS  = 200;

  let _timer = null;
  let _running = false;

  function _fmtMbps(v) {
    if (v >= 100) return v.toFixed(0);
    if (v >= 10)  return v.toFixed(1);
    return v.toFixed(2);
  }
  function _fmtMBs(v) {
    if (v >= 100) return v.toFixed(0);
    if (v >= 10)  return v.toFixed(1);
    return v.toFixed(2);
  }

  function _apply(t) {
    if (!t) return;

    // CPU
    if (t.cpu) {
      Gauges.update("cpu",
        t.cpu.percent,
        Math.round(t.cpu.percent) + "%",
        (t.cpu.freq_ghz ? t.cpu.freq_ghz.toFixed(2) : "--") + " GHz");
    }

    // RAM
    if (t.ram) {
      const sub = (t.ram.used_gb || 0).toFixed(1) + " / " +
                  (t.ram.total_gb || 0).toFixed(1) + " GB";
      Gauges.update("ram", t.ram.percent, Math.round(t.ram.percent) + "%", sub);
    }

    // GPU — sub shows temperature
    if (t.gpu) {
      const gpuPct = t.gpu.available ? t.gpu.load_percent : 0;
      const gpuVal = t.gpu.available ? Math.round(gpuPct) + "%" : "N/A";
      const gpuSub = t.gpu.available ? `${t.gpu.temp_c} °C` : "no GPU";
      Gauges.update("gpu", gpuPct, gpuVal, gpuSub);
    }

    // SSD (C: drive usage) — sub shows VRAM used/total
    if (t.disk) {
      const vramSub = (t.gpu && t.gpu.available)
        ? `VRAM ${t.gpu.vram_used_mb} / ${t.gpu.vram_total_mb} MB`
        : "VRAM -- / -- MB";
      Gauges.update("ssd", t.disk.percent_used_c,
                    Math.round(t.disk.percent_used_c) + "%", vramSub);
    }

    // Network apex — combined total in ring, breakdown in sub HTML div
    if (t.network) {
      const down  = t.network.down_mbps || 0;
      const up    = t.network.up_mbps   || 0;
      const total = down + up;
      const pct   = Math.min(100, (total / NET_CAP_MBPS) * 100);
      const breakdown = `↓${_fmtMbps(down)} ↑${_fmtMbps(up)} Mbps`;
      Gauges.update("net", pct, _fmtMbps(total), breakdown);
    }

    // Disk I/O apex — total throughput in ring, R/W split in sub HTML div
    if (t.disk) {
      const r     = t.disk.read_mb_s  || 0;
      const w     = t.disk.write_mb_s || 0;
      const total = r + w;
      const pct   = Math.min(100, (total / DISK_CAP_MBS) * 100);
      const breakdown = `R ${_fmtMBs(r)} / W ${_fmtMBs(w)} MB/s`;
      Gauges.update("disk_io", pct, _fmtMBs(total), breakdown);
    }
  }

  async function _tick() {
    try {
      const r = await eel.get_telemetry()();
      if (r && r.ok) _apply(r.data);
    } catch (err) {
      console.warn("[telemetry] poll error:", err);
    }
  }

  function start() {
    if (_running) return;
    _running = true;
    _tick();
    _timer = setInterval(_tick, POLL_MS);
  }

  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
    _running = false;
  }

  return { start, stop };
})();

window.Telemetry = Telemetry;
