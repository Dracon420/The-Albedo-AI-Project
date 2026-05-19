// ============================================================
// gauges.js — SVG ring update helpers
//
// Each <svg.gauge> has:
//   - one .gauge__bg          background track
//   - one .gauge__fill        the ring whose stroke-dashoffset we animate
//   - one text[data-value]    the numeric reading at the centre
//   - optionally text[data-sub]  small secondary readout below the value
//
// The ring circumference is hard-coded per size class:
//   large (r=82): 2 * π * 82 ≈ 515.22
//   small (r=48): 2 * π * 48 ≈ 301.59
// ============================================================

// Circumference (2 * π * r) for each gauge size. All three SVGs use r=82
// (200 viewBox) or r=48 (120 viewBox); the medium dial is just the same
// 200/82 ring rendered smaller, so its stroke-dasharray base is identical
// to the large dial — only the rendered pixel size changes.
const GAUGE_CIRC = { large: 515.22, medium: 515.22, small: 301.59 };

const Gauges = (() => {
  function _ringSize(svg) {
    if (svg.classList.contains("gauge--small"))  return "small";
    if (svg.classList.contains("gauge--medium")) return "medium";
    return "large";
  }

  /**
   * Set a gauge's percentage (0–100) and update the ring + center number.
   * Optionally pass a sub-readout string to overwrite the small text below.
   *
   * @param {string} key      data-gauge attribute (e.g. "cpu", "ram")
   * @param {number} pct      0–100
   * @param {string|null} valueText  override for the big number (default: rounded pct)
   * @param {string|null} subText    override for the small secondary readout
   */
  function update(key, pct, valueText, subText) {
    const svg = document.querySelector(`svg.gauge[data-gauge="${key}"]`);
    if (!svg) return;

    pct = Math.max(0, Math.min(100, Number(pct) || 0));
    const circ = GAUGE_CIRC[_ringSize(svg)];
    const offset = circ * (1 - pct / 100);

    const fill = svg.querySelector(".gauge__fill");
    if (fill) {
      fill.style.strokeDashoffset = offset.toFixed(2);
      // Severity tint
      fill.classList.remove("is-warn", "is-crit");
      if      (pct >= 90) fill.classList.add("is-crit");
      else if (pct >= 70) fill.classList.add("is-warn");
    }

    const valueEl = svg.querySelector("text[data-value]");
    if (valueEl) {
      valueEl.textContent = (valueText !== undefined && valueText !== null)
        ? valueText
        : Math.round(pct);
    }

    const subEl = svg.querySelector("text[data-sub]");
    if (subEl && (subText !== undefined && subText !== null)) {
      subEl.textContent = subText;
    }
  }

  /** Convenience: explicit big-text-only update for non-percentage dials. */
  function setText(key, valueText, subText) {
    const svg = document.querySelector(`svg.gauge[data-gauge="${key}"]`);
    if (!svg) return;
    const v = svg.querySelector("text[data-value]");
    const s = svg.querySelector("text[data-sub]");
    if (v && valueText !== undefined) v.textContent = valueText;
    if (s && subText   !== undefined) s.textContent = subText;
  }

  return { update, setText };
})();

window.Gauges = Gauges;
