/* Hero instrument: pulse timing of each sequence in the 2 µs idle window and its held-out infidelity.
   Data: #hero-data, written by scripts/build_site.py from the checksum-verified Scenario A benchmark run. */
(function () {
  "use strict";
  var src = document.getElementById("hero-data");
  if (!src) return;
  var D;
  try { D = JSON.parse(src.textContent); } catch (e) { return; }
  var NS = "http://www.w3.org/2000/svg";
  var NAMES = { free: "Free", cpmg: "CPMG", xy4: "XY4", xy8: "XY8", udd: "UDD", cmaes: "CMA-ES" };
  var LONG = { free: "Free evolution", cpmg: "CPMG", xy4: "XY4", xy8: "XY8", udd: "UDD", cmaes: "CMA-ES (timing+phase)" };
  var ORDER = ["free", "cpmg", "xy4", "xy8", "udd", "cmaes"];
  var NS_LIST = Object.keys(D.by_n).sort(function (a, b) { return a - b; });
  var state = { n: D.default_n, seq: D.by_n[D.default_n].selected };

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function sci(x) {
    var e = Math.floor(Math.log10(x)), m = x / Math.pow(10, e);
    if (Number(m.toFixed(2)) >= 10) { e += 1; m = x / Math.pow(10, e); }
    return { m: m.toFixed(2), e: e };
  }
  function sciHTML(x) { var s = sci(x); return s.m + "×10<sup>" + String(s.e).replace("-", "−") + "</sup>"; }
  function sciText(x) { var s = sci(x); return s.m + " × 10^" + s.e; }
  function axisName(ph) {
    var t = ((ph % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI), q = [["X", 0], ["Y", Math.PI / 2], ["−X", Math.PI], ["−Y", 1.5 * Math.PI]];
    for (var i = 0; i < q.length; i++) if (Math.abs(t - q[i][1]) < 1e-6 || Math.abs(t - q[i][1] - 2 * Math.PI) < 1e-6) return q[i][0];
    return Math.round(t * 180 / Math.PI) + "°";
  }

  function drawTrace() {
    var host = document.getElementById("trace");
    var W = Math.max(280, host.clientWidth - parseFloat(getComputedStyle(host).paddingLeft) - parseFloat(getComputedStyle(host).paddingRight));
    var narrow = W < 560, H = narrow ? 128 : 140, L = 2, R = 2, Y0 = H - 30, PH = narrow ? 56 : 66;
    host.textContent = "";
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, "aria-hidden": "true" }, host);
    var T = D.T, x = function (t) { return L + (t / T) * (W - L - R); };
    for (var i = 0; i <= 8; i++) el("line", { x1: x(T * i / 8), x2: x(T * i / 8), y1: 6, y2: Y0, class: "grid-v" }, svg);
    el("line", { x1: L, x2: W - R, y1: Y0, y2: Y0, class: "axis" }, svg);
    for (var j = 0; j <= 4; j++) {
      var tx = el("text", { x: x(T * j / 4), y: Y0 + 20, class: "tk", "text-anchor": j === 0 ? "start" : j === 4 ? "end" : "middle" }, svg);
      tx.textContent = (T * 1e6 * j / 4).toFixed(1) + (j === 4 ? " µs" : "");
    }
    var s = D.by_n[state.n].seqs[state.seq];
    var w = Math.max(narrow ? 2.5 : 3, (D.width / T) * (W - L - R));
    var showAx = W / Math.max(1, s.centers.length) > 26;
    if (!s.centers.length) {
      var t0 = el("text", { x: W / 2, y: Y0 - PH / 2, class: "none" }, svg);
      t0.textContent = "No pulses: the qubit waits for the full window";
    }
    s.centers.forEach(function (c, k) {
      el("rect", { x: (x(c) - w / 2).toFixed(2), y: Y0 - PH, width: w.toFixed(2), height: PH, class: "pulse" }, svg);
      if (showAx) { var a = el("text", { x: x(c).toFixed(2), y: Y0 - PH - 8, class: "ax" }, svg); a.textContent = axisName(s.phases[k]); }
    });
    host.setAttribute("aria-label", LONG[state.seq] + ": " + s.centers.length + " π pulses of " + (D.width * 1e9).toFixed(0) +
      " ns in a " + (T * 1e6).toFixed(1) + " µs idle window" + (showAx ? "; axes " + s.phases.map(axisName).join(", ") : ""));
  }

  function drawScale() {
    var host = document.getElementById("scale");
    var SW = Math.max(260, host.clientWidth), SH = 58, lo = Math.log10(0.008), hi = Math.log10(0.2), l = 4, r = 4;
    var x = function (v) { return l + (Math.log10(v) - lo) / (hi - lo) * (SW - l - r); };
    host.textContent = "";
    var svg = el("svg", { viewBox: "0 0 " + SW + " " + SH, width: SW, height: SH, role: "img",
      "aria-label": "All sequences at n = " + state.n + " on a logarithmic infidelity scale, with the physical floor" }, host);
    el("rect", { x: l, y: 8, width: Math.max(0, x(D.floor) - l), height: 22, class: "shade" }, svg);
    el("line", { x1: l, x2: SW - r, y1: 19, y2: 19, class: "axis" }, svg);
    el("line", { x1: x(D.floor), x2: x(D.floor), y1: 4, y2: 34, class: "floor" }, svg);
    [0.01, 0.03, 0.1].forEach(function (v) { var t = el("text", { x: x(v), y: 54, class: "tk", "text-anchor": "middle" }, svg); t.textContent = String(v); });
    var seqs = D.by_n[state.n].seqs;
    ORDER.forEach(function (k) {
      if (!seqs[k]) return;
      var on = k === state.seq;
      var c = el("circle", { cx: x(seqs[k].eps), cy: 19, r: on ? 5.5 : 3.5, class: "dot" + (on ? " on" : "") }, svg);
      var ti = el("title", {}, c); ti.textContent = LONG[k] + ": " + sciText(seqs[k].eps);
    });
    var sel = seqs[state.seq], lx = x(sel.eps);
    var lab = el("text", { x: lx, y: 54, class: "name on", "text-anchor": lx > SW - 60 ? "end" : "middle" }, svg);
    lab.textContent = NAMES[state.seq];
    svg.querySelectorAll(".tk").forEach(function (t) { if (Math.abs(Number(t.getAttribute("x")) - lx) < 34) t.setAttribute("opacity", "0"); });
  }

  function readouts() {
    var set = D.by_n[state.n], s = set.seqs[state.seq], sel = set.selected, base = set.seqs[sel].eps;
    document.getElementById("r-eps").innerHTML = sciHTML(s.eps);
    document.getElementById("r-floor").innerHTML = sciHTML(D.floor);
    var over = (s.eps / D.floor - 1) * 100;
    document.getElementById("r-over").textContent = "+" + over.toFixed(1) + "%";
    var cmp = document.getElementById("r-cmp"), ratio = base / s.eps;
    document.getElementById("r-cmp-l").textContent = "Versus " + NAMES[sel] + " (selected)";
    cmp.className = "";
    if (state.seq === sel) cmp.textContent = "baseline";
    else { cmp.textContent = "×" + ratio.toFixed(3); if (ratio < 1) cmp.className = "bad"; }
    var v;
    if (state.seq === "cmaes") {
      v = ratio >= 1
        ? "<strong>CMA-ES ties " + NAMES[sel] + "</strong> at n = " + state.n + ": ratio " + ratio.toFixed(3) + ", within the Monte Carlo uncertainty."
        : "<strong>CMA-ES is <span class=\"bad\">" + ((1 / ratio - 1) * 100).toFixed(1) + "% worse</span> than " + NAMES[sel] + "</strong>, the baseline chosen on training data before any test seed was used.";
    } else if (state.seq === sel) {
      v = "<strong>" + NAMES[sel] + " is the baseline</strong> the pre-registered rule selects at n = " + state.n + ". It sits " + over.toFixed(1) + "% above the floor that T₁ and white noise set for every sequence.";
    } else if (state.seq === "free") {
      v = "<strong>Without pulses</strong>, low-frequency noise dephases the qubit: " + (s.eps / base).toFixed(1) + "× the infidelity of " + NAMES[sel] + ".";
    } else {
      v = "<strong>" + LONG[state.seq] + "</strong> with " + state.n + " pulses: " + (s.eps / base).toFixed(2) + "× the infidelity of " + NAMES[sel] + ".";
      if (state.seq === "cpmg" || state.seq === "udd") v += " Single-axis pulses let the 2% amplitude error build up coherently.";
    }
    document.getElementById("verdict").innerHTML = v;
    document.getElementById("inst-prov").innerHTML = "Scenario A, 32 ns pulses on a 4 ns grid. Mean over test seeds " + D.test_seeds +
      ". CMA-ES shown: training run " + set.seqs.cmaes.train_seed + " (pre-specified, not the best run). Run <a href=\"" + D.run_href + "\">" + D.run_id + "</a>.";
  }

  function controls() {
    var seq = document.getElementById("seq"), np = document.getElementById("npulse");
    ORDER.forEach(function (k) {
      seq.insertAdjacentHTML("beforeend", '<input type="radio" name="seq" id="s-' + k + '" value="' + k + '"><label for="s-' + k + '">' + NAMES[k] + "</label>");
    });
    NS_LIST.forEach(function (n) { np.insertAdjacentHTML("beforeend", '<input type="radio" name="n" id="n-' + n + '" value="' + n + '"><label for="n-' + n + '">' + n + "</label>"); });
    seq.addEventListener("change", function (e) { state.seq = e.target.value; render(); });
    np.addEventListener("change", function (e) {
      state.n = e.target.value;
      if (!D.by_n[state.n].seqs[state.seq]) state.seq = D.by_n[state.n].selected;
      render();
    });
  }
  function sync() {
    ORDER.forEach(function (k) {
      var i = document.getElementById("s-" + k), ok = !!D.by_n[state.n].seqs[k];
      i.checked = k === state.seq; i.disabled = !ok;
      i.nextElementSibling.title = ok ? "" : NAMES[k] + " is not defined or not feasible at n = " + state.n;
    });
    NS_LIST.forEach(function (n) { document.getElementById("n-" + n).checked = n === state.n; });
  }
  function render() { sync(); drawTrace(); drawScale(); readouts(); }
  controls();
  render();
  var rt;
  window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { drawTrace(); drawScale(); }, 120); });
})();
