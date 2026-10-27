/* Interactive SVG charts drawn from the embedded, artifact-derived data (no chart library).
   Fixed categorical order (dataviz reference palette): entity -> colour/shape never by rank. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var src = document.getElementById("chart-data");
  if (!src) return;
  var DATA;
  try { DATA = JSON.parse(src.textContent); } catch (e) { return; }

  var FAM = {
    free: { label: "Free (no DD)", shape: "circle" },
    cpmg: { label: "CPMG", shape: "square" },
    xy4: { label: "XY4", shape: "triUp" },
    xy8: { label: "XY8", shape: "triDown" },
    udd: { label: "UDD", shape: "diamond" },
    both: { label: "CMA-ES timing+phase", shape: "star" },
    phase: { label: "CMA-ES phase-only", shape: "plus" },
    timing: { label: "CMA-ES timing-only", shape: "cross" }
  };
  var ORDER = ["free", "cpmg", "xy4", "xy8", "udd", "both", "phase", "timing"];
  var DASH = { solid: null, dashed: "6 4", dotted: "1.5 4.5" };

  /* ---------------- formatting ---------------- */
  var SUP = { "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹" };
  function sup(s) { return String(s).split("").map(function (c) { return SUP[c] || c; }).join(""); }
  function sci(v, sig) {
    if (v === 0) return "0";
    if (!isFinite(v)) return String(v);
    sig = sig || 4;
    var e = Math.floor(Math.log10(Math.abs(v)));
    var m = v / Math.pow(10, e);
    if (Math.abs(Number(m.toFixed(sig - 1))) >= 10) { e += 1; m = v / Math.pow(10, e); }
    return m.toFixed(sig - 1) + "×10" + sup(e);
  }
  function fixed(v, d) { return Number(v).toFixed(d); }
  function plainTick(v) {
    if (v >= 1e-3 && v < 1e4) return String(Number(v.toPrecision(3)));
    return null;
  }

  /* ---------------- svg helpers ---------------- */
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, parent, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function shapeD(shape, x, y, r) {
    var s = r, t;
    switch (shape) {
      case "square": t = s * 0.86; return "M" + (x - t) + "," + (y - t) + "h" + 2 * t + "v" + 2 * t + "h" + -2 * t + "Z";
      case "triUp": return "M" + x + "," + (y - s * 1.15) + "L" + (x + s * 1.05) + "," + (y + s * 0.75) + "L" + (x - s * 1.05) + "," + (y + s * 0.75) + "Z";
      case "triDown": return "M" + x + "," + (y + s * 1.15) + "L" + (x + s * 1.05) + "," + (y - s * 0.75) + "L" + (x - s * 1.05) + "," + (y - s * 0.75) + "Z";
      case "diamond": return "M" + x + "," + (y - s * 1.2) + "L" + (x + s * 1.0) + "," + y + "L" + x + "," + (y + s * 1.2) + "L" + (x - s * 1.0) + "," + y + "Z";
      case "star": {
        var d = "", R = s * 1.35, ri = R * 0.48;
        for (var i = 0; i < 10; i++) {
          var a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? ri : R;
          d += (i ? "L" : "M") + (x + rr * Math.cos(a)).toFixed(2) + "," + (y + rr * Math.sin(a)).toFixed(2);
        }
        return d + "Z";
      }
      case "plus": t = s * 0.38; s = s * 1.15;
        return "M" + (x - t) + "," + (y - s) + "h" + 2 * t + "v" + (s - t) + "h" + (s - t) + "v" + 2 * t + "h" + -(s - t) + "v" + (s - t) + "h" + -2 * t + "v" + -(s - t) + "h" + -(s - t) + "v" + -2 * t + "h" + (s - t) + "Z";
      case "cross": {
        var k = s * 1.1, w = s * 0.36;
        var p = [[-k, -k + w], [-k + w, -k], [0, -w], [k - w, -k], [k, -k + w], [w, 0], [k, k - w], [k - w, k], [0, w], [-k + w, k], [-k, k - w], [-w, 0]];
        return "M" + p.map(function (q) { return (x + q[0]).toFixed(2) + "," + (y + q[1]).toFixed(2); }).join("L") + "Z";
      }
      default: return "M" + (x - s) + "," + y + "a" + s + "," + s + " 0 1,0 " + 2 * s + ",0a" + s + "," + s + " 0 1,0 " + -2 * s + ",0";
    }
  }

  /* ---------------- scales & ticks ---------------- */
  function logScale(d0, d1, r0, r1) {
    var l0 = Math.log10(d0), l1 = Math.log10(d1);
    var f = function (v) { return r0 + (Math.log10(v) - l0) / (l1 - l0) * (r1 - r0); };
    f.inv = function (p) { return Math.pow(10, l0 + (p - r0) / (r1 - r0) * (l1 - l0)); };
    f.ticks = function () {
      var a = Math.floor(l0), b = Math.ceil(l1), span = l1 - l0, out = [];
      var mants = span > 3.2 ? [1] : span > 1.6 ? [1, 3] : span > 0.75 ? [1, 2, 5] : span > 0.5 ? [1, 1.5, 2, 3, 4, 5, 6, 8]
        : [1, 1.2, 1.4, 1.6, 1.8, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9];
      var step = span > 9 ? 2 : 1;
      for (var k = a; k <= b; k++) {
        if (mants.length === 1 && (k - a) % step) continue;
        mants.forEach(function (m) { var v = m * Math.pow(10, k); if (v >= d0 * 0.999 && v <= d1 * 1.001) out.push(v); });
      }
      if (out.length > 7) { var keep = Math.ceil(out.length / 6); out = out.filter(function (_, i) { return i % keep === 0; }); }
      return out;
    };
    f.fmt = function (v) {
      var e = Math.round(Math.log10(v));
      if (l1 - l0 <= 3.2) { var p = plainTick(v); if (p) return { t: p }; }
      if (Math.abs(v / Math.pow(10, e) - 1) > 1e-9) e = Math.floor(Math.log10(v) + 1e-12);
      var m = v / Math.pow(10, e);
      return Math.abs(m - 1) < 1e-9 ? { t: "10", e: String(e) } : { t: Number(m.toPrecision(2)) + "×10", e: String(e) };
    };
    f.log = true;
    return f;
  }
  function linScale(d0, d1, r0, r1) {
    var f = function (v) { return r0 + (v - d0) / (d1 - d0) * (r1 - r0); };
    f.inv = function (p) { return d0 + (p - r0) / (r1 - r0) * (d1 - d0); };
    f.ticks = function (n) {
      n = n || 6;
      var raw = (d1 - d0) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).filter(function (s) { return s >= raw; })[0];
      var out = [];
      for (var v = Math.ceil(d0 / st) * st; v <= d1 + st * 1e-9; v += st) out.push(Number(v.toPrecision(10)));
      return out;
    };
    f.fmt = function (v) { return { t: String(Number(v.toPrecision(6))) }; };
    return f;
  }
  function extent(vals, pad, log) {
    var lo = Infinity, hi = -Infinity;
    vals.forEach(function (v) { if (isFinite(v) && (!log || v > 0)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    if (log) return [lo / pad, hi * pad];
    var d = (hi - lo) || Math.abs(hi) || 1;
    return [lo - d * pad, hi + d * pad];
  }
  function tickLabel(parent, x, y, f, anchor, cls) {
    var t = el("text", { x: x, y: y, "text-anchor": anchor, "class": cls || "tick" }, parent);
    t.appendChild(document.createTextNode(f.t));
    if (f.e !== undefined) {
      var s = el("tspan", { dy: "-0.45em", "font-size": "0.78em" }, t);
      s.textContent = f.e.replace("-", "−");
    }
    return t;
  }

  /* ---------------- frame ---------------- */
  function frame(panel, o) {
    var W = Math.max(260, Math.floor(panel.clientWidth || 600));
    var H = o.height || (W < 420 ? 250 : 290);
    var m = { t: 14, r: 14, b: o.xlabel ? 44 : 28, l: o.ml || 58 };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "group", "aria-label": o.aria || "" });
    panel.appendChild(svg);
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var X = o.x.type === "band" ? null : (o.x.type === "log" ? logScale : linScale)(o.x.domain[0], o.x.domain[1], m.l, m.l + pw);
    var Y = (o.y.type === "log" ? logScale : linScale)(o.y.domain[0], o.y.domain[1], m.t + ph, m.t);
    var gGrid = el("g", null, svg);
    Y.ticks().forEach(function (v) {
      var y = Math.round(Y(v)) + 0.5;
      el("line", { x1: m.l, x2: m.l + pw, y1: y, y2: y, "class": "gridline" }, gGrid);
      tickLabel(gGrid, m.l - 8, y + 4, Y.fmt(v), "end");
    });
    el("line", { x1: m.l, x2: m.l + pw, y1: m.t + ph + 0.5, y2: m.t + ph + 0.5, "class": "baseline" }, gGrid);
    if (X) {
      var xt = X.ticks(W < 420 ? 4 : 6);
      if (X.log && W < 420 && xt.length > 6) xt = xt.filter(function (_, i) { return i % 2 === 0; });
      xt.forEach(function (v) {
        var x = Math.round(X(v)) + 0.5;
        el("line", { x1: x, x2: x, y1: m.t + ph, y2: m.t + ph + 4, "class": "baseline" }, gGrid);
        tickLabel(gGrid, x, m.t + ph + 17, X.fmt(v), "middle");
      });
    }
    if (o.xlabel) el("text", { x: m.l + pw / 2, y: H - 6, "text-anchor": "middle", "class": "axis-label" }, svg).textContent = o.xlabel;
    if (o.ylabel) {
      var yl = el("text", { x: 12, y: m.t + ph / 2, "text-anchor": "middle", "class": "axis-label", transform: "rotate(-90 12 " + (m.t + ph / 2) + ")" }, svg);
      yl.textContent = o.ylabel;
    }
    var g = el("g", null, svg);
    return { svg: svg, g: g, X: X, Y: Y, W: W, H: H, m: m, pw: pw, ph: ph };
  }

  /* ---------------- tooltip ---------------- */
  function keySwatch(parent, s) {
    var sv = el("svg", { width: 18, height: 10, viewBox: "0 0 18 10", "aria-hidden": "true" }, parent);
    if (s.line !== false) el("line", { x1: 1, x2: 17, y1: 5, y2: 5, "class": "ln s-" + s.fam, "stroke-dasharray": DASH[s.dash || "solid"] }, sv);
    if (s.shape) el("path", { d: shapeD(s.shape, 9, 5, 3.4), "class": (s.open ? "mk-open s-" : "mk s-") + s.fam }, sv);
    return sv;
  }
  function Tooltip(panel) {
    var t = h("div", "tooltip", panel);
    t.hidden = true;
    t.setAttribute("aria-hidden", "true");
    return {
      show: function (head, rows, note, px, py) {
        t.textContent = "";
        h("div", "tt-head", t, head);
        rows.forEach(function (r) {
          var row = h("div", "tt-row", t);
          keySwatch(row, r);
          h("strong", null, row, r.value);
          h("span", null, row, r.label);
        });
        if (note) [].concat(note).forEach(function (n) { h("div", "tt-note", t, n); });
        t.hidden = false;
        var pw = panel.clientWidth, w = t.offsetWidth, hh = t.offsetHeight;
        var left = px + 16, top = Math.max(0, Math.min(py - hh / 2, panel.clientHeight - hh));
        if (left + w > pw) {
          left = px - w - 16;
          if (left < 0) { /* no room beside the mark: centre it above (or below) instead */
            left = Math.max(0, Math.min(px - w / 2, pw - w));
            top = py - hh - 16 >= 0 ? py - hh - 16 : py + 16;
          }
        }
        t.style.left = left + "px"; t.style.top = top + "px";
      },
      hide: function () { t.hidden = true; }
    };
  }
  function liveRegion(parent) {
    var r = h("div", "sr-only", parent);
    r.setAttribute("aria-live", "polite");
    r.style.position = "absolute"; r.style.width = "1px"; r.style.height = "1px"; r.style.overflow = "hidden"; r.style.clip = "rect(0 0 0 0)";
    return r;
  }

  /* ---------------- chart shell: legend, panels, data-table toggle ---------------- */
  var uid = 0;
  function shell(container, legendItems, tableFn) {
    container.textContent = "";
    var bar = h("div", "chart-toolbar", container);
    var ul = h("ul", "legend", bar);
    ul.setAttribute("aria-label", "Legend");
    legendItems.forEach(function (it) {
      var li = h("li", null, ul);
      keySwatch(li, it);
      h("span", null, li, it.label);
    });
    var btn = h("button", "table-toggle", bar, "View data table");
    btn.type = "button";
    var panels = h("div", "panels", container);
    var dataBox = h("div", "chart-data", container);
    dataBox.hidden = true;
    dataBox.id = "chart-table-" + (++uid);
    btn.setAttribute("aria-controls", dataBox.id);
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", function () {
      var open = dataBox.hidden;
      if (open && !dataBox.firstChild) tableFn().forEach(function (tb) { renderTable(dataBox, tb); });
      dataBox.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.textContent = open ? "Hide data table" : "View data table";
    });
    return panels;
  }
  function renderTable(parent, tb) {
    if (tb.title) h("p", "fine", parent, tb.title);
    var wrap = h("div", "table-wrap", parent);
    wrap.setAttribute("tabindex", "0");
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", tb.title || "Chart data");
    var table = h("table", null, wrap);
    var tr = h("tr", null, h("thead", null, table));
    tb.headers.forEach(function (c) { var th = h("th", null, tr, c); th.scope = "col"; });
    var body = h("tbody", null, table);
    tb.rows.forEach(function (r) {
      var row = h("tr", null, body);
      r.forEach(function (c, i) {
        var td = h(i === 0 ? "th" : "td", i === 0 ? null : "num-cell", row, c);
        if (i === 0) td.scope = "row";
      });
    });
    if (tb.note) h("p", "fine", parent, tb.note);
  }
  function responsive(panelsEl, draw) {
    var last = -1;
    function run() {
      var w = panelsEl.clientWidth;
      if (w === last || w === 0) return;
      last = w;
      draw();
    }
    run();
    if (window.ResizeObserver) new ResizeObserver(function () { window.requestAnimationFrame(run); }).observe(panelsEl);
    else window.addEventListener("resize", run);
  }
  function makePanel(parent, title) {
    var p = h("div", "panel", parent);
    if (title) h("p", "panel-title", p, title);
    return p;
  }
  function localPoint(svg, evt, f) {
    var r = svg.getBoundingClientRect();
    return { x: (evt.clientX - r.left) * (f.W / r.width), y: (evt.clientY - r.top) * (f.H / r.height), sx: r.width / f.W };
  }
  function toPanel(panel, svg, f, x, y) {
    var r = svg.getBoundingClientRect(), pr = panel.getBoundingClientRect(), s = r.width / f.W;
    return { x: r.left - pr.left + x * s, y: r.top - pr.top + y * s };
  }

  /* ---------------- dot plot with roving keyboard focus ---------------- */
  function dotInteraction(panel, f, pts, tip, live) {
    var cur = -1;
    pts.forEach(function (p, i) {
      var g = el("g", { "class": "pt", tabindex: i === 0 ? 0 : -1, role: "img", "aria-label": p.aria }, f.g);
      el("circle", { cx: p.x, cy: p.y, r: 8, "class": "focus-ring" }, g);
      el("path", { d: shapeD(p.shape, p.x, p.y, 4.6), "class": "mk s-" + p.fam }, g);
      p.node = g;
      g.addEventListener("focus", function () { activate(i, true); });
      g.addEventListener("blur", function () { tip.hide(); g.classList.remove("is-hover"); });
      g.addEventListener("keydown", function (e) {
        var k = e.key, j = i;
        if (k === "ArrowRight" || k === "ArrowDown") j = Math.min(pts.length - 1, i + 1);
        else if (k === "ArrowLeft" || k === "ArrowUp") j = Math.max(0, i - 1);
        else if (k === "Home") j = 0; else if (k === "End") j = pts.length - 1;
        else if (k === "Escape") { tip.hide(); return; } else return;
        e.preventDefault();
        pts[i].node.setAttribute("tabindex", -1);
        pts[j].node.setAttribute("tabindex", 0);
        pts[j].node.focus();
      });
    });
    function activate(i, fromKey) {
      if (cur >= 0 && pts[cur]) pts[cur].node.classList.remove("is-hover");
      cur = i;
      var p = pts[i];
      p.node.classList.add("is-hover");
      var q = toPanel(panel, f.svg, f, p.x, p.y);
      tip.show(p.head, [{ fam: p.fam, shape: p.shape, line: false, value: p.value, label: p.label }], p.note, q.x, q.y);
      if (fromKey && live) live.textContent = p.aria;
    }
    f.svg.addEventListener("pointermove", function (e) {
      var lp = localPoint(f.svg, e, f), best = -1, bd = 22 / lp.sx;
      pts.forEach(function (p, i) { var d = Math.hypot(p.x - lp.x, p.y - lp.y); if (d < bd) { bd = d; best = i; } });
      if (best >= 0) activate(best, false);
      else { tip.hide(); if (cur >= 0) pts[cur].node.classList.remove("is-hover"); cur = -1; }
    });
    f.svg.addEventListener("pointerleave", function () { tip.hide(); if (cur >= 0) pts[cur].node.classList.remove("is-hover"); cur = -1; });
  }

  /* ---------------- line chart with crosshair ---------------- */
  /* series: [{fam, dash, shape, label, pts:[{x,y,lo,hi}], band:bool}], refs: [{y, label}], extra pts (open). */
  function lineInteraction(panel, f, xs, readout, tip, live, extraPts) {
    var cross = el("line", { y1: f.m.t, y2: f.m.t + f.ph, "class": "crosshair", visibility: "hidden" }, f.svg);
    var idx = -1;
    function at(i, fromKey) {
      idx = i;
      var x = f.X(xs[i]);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      var r = readout(i);
      var q = toPanel(panel, f.svg, f, x, f.m.t + f.ph / 3);
      tip.show(r.head, r.rows, r.note, q.x, q.y);
      if (fromKey && live) live.textContent = r.head + ": " + r.rows.map(function (z) { return z.label + " " + z.value; }).join("; ");
    }
    function off() { cross.setAttribute("visibility", "hidden"); tip.hide(); }
    f.svg.addEventListener("pointermove", function (e) {
      var lp = localPoint(f.svg, e, f);
      if (extraPts) {
        var best = null, bd = 12 / lp.sx;
        extraPts.forEach(function (p) { var d = Math.hypot(p.px - lp.x, p.py - lp.y); if (d < bd) { bd = d; best = p; } });
        if (best) {
          cross.setAttribute("visibility", "hidden");
          var q = toPanel(panel, f.svg, f, best.px, best.py);
          tip.show(best.head, best.rows, best.note, q.x, q.y);
          return;
        }
      }
      if (lp.x < f.m.l - 4 || lp.x > f.m.l + f.pw + 4) { off(); return; }
      var bi = 0, bd2 = Infinity;
      xs.forEach(function (v, i) { var d = Math.abs(f.X(v) - lp.x); if (d < bd2) { bd2 = d; bi = i; } });
      at(bi, false);
    });
    f.svg.addEventListener("pointerleave", off);
    f.svg.setAttribute("tabindex", "0");
    f.svg.addEventListener("focus", function () { at(idx < 0 ? 0 : idx, true); });
    f.svg.addEventListener("blur", off);
    f.svg.addEventListener("keydown", function (e) {
      var j = idx < 0 ? 0 : idx, step = e.shiftKey ? 10 : 1;
      if (e.key === "ArrowRight") j = Math.min(xs.length - 1, j + step);
      else if (e.key === "ArrowLeft") j = Math.max(0, j - step);
      else if (e.key === "Home") j = 0; else if (e.key === "End") j = xs.length - 1;
      else if (e.key === "Escape") { off(); return; } else return;
      e.preventDefault();
      at(j, true);
    });
  }
  function path(f, pts, xk, yk) {
    return pts.filter(function (p) { return p[yk] > 0 || !f.Y.log; }).map(function (p, i) {
      return (i ? "L" : "M") + f.X(p[xk]).toFixed(2) + "," + f.Y(p[yk]).toFixed(2);
    }).join("");
  }
  function bandPath(f, xsArr, lo, hi) {
    var up = xsArr.map(function (x, i) { return (i ? "L" : "M") + f.X(x).toFixed(2) + "," + f.Y(hi[i]).toFixed(2); }).join("");
    var dn = xsArr.slice().reverse().map(function (x, k) { var i = xsArr.length - 1 - k; return "L" + f.X(x).toFixed(2) + "," + f.Y(lo[i]).toFixed(2); }).join("");
    return up + dn + "Z";
  }

  /* =========================================================================================
     (a) benchmark dot plot
     ========================================================================================= */
  function benchmark(container, d) {
    var present = {};
    d.panels.forEach(function (p) { p.groups.forEach(function (g) {
      ORDER.forEach(function (k) { if (k in g.baselines || (g.modes[k])) present[k] = true; });
    }); });
    var fams = ORDER.filter(function (k) { return present[k]; });
    var legend = fams.map(function (k) { return { fam: k, shape: FAM[k].shape, line: false, label: FAM[k].label }; });
    legend.push({ fam: "truth", line: true, dash: "dashed", label: "T₁ + white-noise floor" });
    var panelsEl = shell(container, legend, function () {
      var rows = [];
      d.panels.forEach(function (p) { p.groups.forEach(function (g) { fams.forEach(function (k) {
        var v = valueOf(g, k); if (v === null) return;
        var note = g.selected.indexOf(k) >= 0 ? "selected (training-only rule)" : "";
        if (g.modes[k]) note = "mean of " + g.modes[k].runs.length + " runs; ratio " + ratioRange(g.modes[k]);
        rows.push([p.title, String(g.n), FAM[k].label, sci(v), note]);
      }); }); rows.push([p.title, "all", "Analytic floor", sci(p.floor), "T₁ amplitude damping + white dephasing"]); });
      return [{ title: "Held-out infidelity ε (mean over test seeds 9001–9005). Runs: " + d.panels.map(function (p) { return p.run_id; }).join(", "),
        headers: ["Scenario", "n", "Sequence", "ε", "Note"], rows: rows }];
    });
    panelsEl.classList.add("two");
    function valueOf(g, k) { if (k in g.baselines) return g.baselines[k]; if (g.modes[k]) return g.modes[k].mean_eps; return null; }
    function ratioRange(md) {
      var r = md.runs.map(function (x) { return x.ratio; });
      return fixed(Math.min.apply(null, r), 3) + "–" + fixed(Math.max.apply(null, r), 3);
    }
    var all = [];
    d.panels.forEach(function (p) { all.push(p.floor); p.groups.forEach(function (g) { fams.forEach(function (k) { var v = valueOf(g, k); if (v !== null) all.push(v); }); }); });
    var dom = extent(all, 1.25, true);
    var live = liveRegion(container);
    responsive(panelsEl, function () {
      panelsEl.textContent = "";
      d.panels.forEach(function (p) {
        var panel = makePanel(panelsEl, p.title);
        var f = frame(panel, { x: { type: "band" }, y: { type: "log", domain: dom }, xlabel: "pulses n", ylabel: "held-out ε",
          aria: p.title + ": held-out infidelity by pulse number and sequence. Use arrow keys to step through points." });
        var tip = Tooltip(panel);
        var ns = p.groups.map(function (g) { return g.n; });
        var bw = f.pw / ns.length;
        var step = Math.min(13, bw * 0.84 / fams.length);
        ns.forEach(function (n, i) {
          var cx = f.m.l + bw * (i + 0.5);
          el("text", { x: cx, y: f.m.t + f.ph + 17, "text-anchor": "middle", "class": "tick" }, f.svg).textContent = "n = " + n;
          if (i) el("line", { x1: f.m.l + bw * i, x2: f.m.l + bw * i, y1: f.m.t, y2: f.m.t + f.ph, "class": "gridline" }, f.g);
        });
        var fy = f.Y(p.floor);
        el("line", { x1: f.m.l, x2: f.m.l + f.pw, y1: fy, y2: fy, "class": "ref-line" }, f.g);
        el("text", { x: f.m.l + 6, y: fy + 14, "class": "ref-label" }, f.g).textContent = "floor " + sci(p.floor, 3);
        var pts = [];
        p.groups.forEach(function (g, i) {
          var cx = f.m.l + bw * (i + 0.5);
          fams.forEach(function (k, j) {
            var v = valueOf(g, k); if (v === null) return;
            var note = [];
            if (g.selected.indexOf(k) >= 0) note.push("Selected baseline (training-only rule)");
            if (g.modes[k]) {
              note.push("Mean of " + g.modes[k].runs.length + " training runs; ratio ε_sel/ε_CMA " + ratioRange(g.modes[k]));
              g.modes[k].runs.forEach(function (r) { note.push("train seed " + r.train_seed + ": " + sci(r.eps)); });
            }
            note.push("Run " + p.run_id);
            pts.push({ x: cx + (j - (fams.length - 1) / 2) * step, y: f.Y(v), fam: k, shape: FAM[k].shape,
              head: p.title + " · n = " + g.n, value: "ε = " + sci(v), label: FAM[k].label, note: note,
              aria: p.title + ", n = " + g.n + ", " + FAM[k].label + ": held-out infidelity " + sci(v) });
          });
        });
        dotInteraction(panel, f, pts, tip, live);
      });
    });
  }

  /* =========================================================================================
     (b) convergence: training vs validation
     ========================================================================================= */
  function convergence(container, d) {
    var series = d.series.map(function (s) {
      return { fam: s.family, dash: s.split === "train" ? "dashed" : "solid", shape: FAM[s.family].shape, label: s.label, pts: s.points };
    });
    var bl = d.baseline;
    var refs = [{ fam: bl.family, dash: "dashed", label: bl.label + ": training", y: bl.train },
                { fam: bl.family, dash: "solid", label: bl.label + ": validation", y: bl.validation }];
    var legend = series.map(function (s) { return { fam: s.fam, dash: s.dash, shape: s.shape, label: s.label }; })
      .concat(refs.map(function (r) { return { fam: r.fam, dash: r.dash, label: r.label }; }));
    var budgets = d.series[0].points.map(function (p) { return p.budget; });
    var panelsEl = shell(container, legend, function () {
      var rows = budgets.map(function (b) {
        return [String(b)].concat(d.series.map(function (s) {
          var p = s.points.filter(function (q) { return q.budget === b; })[0];
          return p ? sci(p.y) + " (" + p.x + " evals)" : "—";
        }));
      });
      rows.push(["baseline"].concat(d.series.map(function (s) { return s.split === "train" ? sci(bl.train) : sci(bl.validation); })));
      return [{ title: "Best-so-far infidelity by evaluation budget (" + d.status + "). Validation seeds " + (d.validation_seeds || []).join(", ") + ". Run " + d.run_id,
        headers: ["Budget"].concat(d.series.map(function (s) { return s.label; })), rows: rows,
        note: "Last row: " + bl.label + " training and validation infidelity." }];
    });
    var xs = [], ys = [bl.train, bl.validation];
    d.series.forEach(function (s) { s.points.forEach(function (p) { xs.push(p.x); ys.push(p.y); }); });
    var live = liveRegion(container);
    responsive(panelsEl, function () {
      panelsEl.textContent = "";
      var panel = makePanel(panelsEl, null);
      var f = frame(panel, { x: { type: "log", domain: extent(xs, 1.15, true) }, y: { type: "log", domain: extent(ys, 1.12, true) },
        height: panel.clientWidth < 420 ? 270 : 320, xlabel: "CMA-ES objective evaluations", ylabel: "infidelity ε",
        aria: "Training versus validation infidelity versus evaluation budget. Use left and right arrow keys to read values." });
      var tip = Tooltip(panel);
      refs.forEach(function (r) {
        el("line", { x1: f.m.l, x2: f.m.l + f.pw, y1: f.Y(r.y), y2: f.Y(r.y), "class": "ln s-" + r.fam, "stroke-width": 1.4, "stroke-dasharray": DASH[r.dash] }, f.g);
      });
      series.forEach(function (s) {
        el("path", { d: path(f, s.pts, "x", "y"), "class": "ln s-" + s.fam, "stroke-dasharray": DASH[s.dash] }, f.g);
        s.pts.forEach(function (p) { el("path", { d: shapeD(s.shape, f.X(p.x), f.Y(p.y), 3.8), "class": "mk s-" + s.fam }, f.g); });
      });
      lineInteraction(panel, f, budgetsX(), function (i) {
        var b = budgets[i];
        var rows = series.map(function (s) {
          var p = s.pts.filter(function (q) { return q.budget === b; })[0];
          return { fam: s.fam, dash: s.dash, shape: s.shape, value: p ? sci(p.y) : "—", label: s.label + (p ? " (" + p.x + ")" : "") };
        }).concat(refs.map(function (r) { return { fam: r.fam, dash: r.dash, value: sci(r.y), label: r.label }; }));
        return { head: "Budget " + b + " evaluations", rows: rows, note: "Run " + d.run_id };
      }, tip, live);
      function budgetsX() {
        return budgets.map(function (b) {
          var p = d.series[0].points.filter(function (q) { return q.budget === b; })[0];
          return p ? p.x : b;
        });
      }
    });
  }

  /* =========================================================================================
     (c) Scenario B robustness, n = 4, all three training runs
     ========================================================================================= */
  function robustness(container, d) {
    var styleOf = function (s) {
      if (s.key === "vz") return { fam: "free", dash: "solid", shape: "circle" };
      if (s.key === "dd") return { fam: "xy4", dash: "solid", shape: "triUp" };
      return s.family === "both" ? { fam: "both", dash: "dashed", shape: "star" } : { fam: "phase", dash: "dotted", shape: "plus" };
    };
    var legend = [
      { fam: "free", dash: "solid", shape: "circle", label: "No DD + virtual-Z" },
      { fam: "xy4", dash: "solid", shape: "triUp", label: "XY4 + virtual-Z" },
      { fam: "phase", dash: "dotted", shape: "plus", label: "CMA-ES phase-only + VZ (3 runs)" },
      { fam: "both", dash: "dashed", shape: "star", label: "CMA-ES timing+phase + VZ (3 runs)" }
    ];
    var panelsEl = shell(container, legend, function () {
      return d.panels.map(function (p) {
        return { title: p.xlabel + " — held-out ε, n = " + d.n + ". Run " + d.run_id,
          headers: [p.xlabel].concat(p.series.map(function (s) { return s.label; })),
          rows: p.x.map(function (x, i) { return [String(x)].concat(p.series.map(function (s) { return sci(s.y[i]); })); }) };
      });
    });
    panelsEl.classList.add("two");
    var ys = [];
    d.panels.forEach(function (p) { p.series.forEach(function (s) { ys = ys.concat(s.y); }); });
    var dom = extent(ys, 1.12, true);
    var live = liveRegion(container);
    responsive(panelsEl, function () {
      panelsEl.textContent = "";
      d.panels.forEach(function (p) {
        var panel = makePanel(panelsEl, p.id === "amp" ? "Stark amplitude perturbed" : "Readout timing shifted");
        var f = frame(panel, { x: { type: "lin", domain: extent(p.x, 0.06, false) }, y: { type: "log", domain: dom }, xlabel: p.xlabel, ylabel: "held-out ε (n = " + d.n + ")",
          aria: "Scenario B robustness versus " + p.xlabel + ". Use left and right arrow keys to read values." });
        var tip = Tooltip(panel);
        var nominal = p.id === "amp" ? 1 : 0;
        el("line", { x1: f.X(nominal), x2: f.X(nominal), y1: f.m.t, y2: f.m.t + f.ph, "class": "gridline" }, f.g);
        el("text", { x: f.X(nominal) + 4, y: f.m.t + 10, "class": "ref-label" }, f.g).textContent = "nominal";
        p.series.forEach(function (s) {
          var st = styleOf(s), pts = p.x.map(function (x, i) { return { x: x, y: s.y[i] }; });
          el("path", { d: path(f, pts, "x", "y"), "class": "ln s-" + st.fam, "stroke-dasharray": DASH[st.dash], "stroke-width": s.key === "dd" ? 2.6 : 1.8 }, f.g);
          pts.forEach(function (q) { el("path", { d: shapeD(st.shape, f.X(q.x), f.Y(q.y), 3.6), "class": "mk s-" + st.fam }, f.g); });
        });
        lineInteraction(panel, f, p.x, function (i) {
          var rows = p.series.map(function (s) { var st = styleOf(s); return { fam: st.fam, dash: st.dash, shape: st.shape, value: sci(s.y[i]), label: s.label }; });
          return { head: p.xlabel + ": " + p.x[i], rows: rows, note: "Run " + d.run_id };
        }, tip, live);
      });
    });
  }

  /* =========================================================================================
     (d) spectroscopy: PSD with band, decays with held-out data
     ========================================================================================= */
  function spectroscopy(container, d) {
    var CUR = { ramsey: ["free", "circle", "Ramsey"], hahn: ["cpmg", "square", "Hahn"], cpmg4: ["xy4", "triUp", "CPMG-4"], cpmg16: ["udd", "diamond", "CPMG-16 (held-out n)"] };
    var keys = ["ramsey", "hahn", "cpmg4", "cpmg16"].filter(function (k) { return d.curves[k]; });
    var legend = [{ fam: "free", dash: "solid", label: "PSD fit (full model, MLE) ± 95% band" }, { fam: "truth", dash: "dashed", label: "PSD truth" }]
      .concat(keys.map(function (k) { return { fam: CUR[k][0], dash: "solid", label: CUR[k][2] + " fit ± 95% band" }; }))
      .concat([{ fam: "truth", line: false, shape: "circle", open: true, label: "held-out data" }]);
    var panelsEl = shell(container, legend, function () {
      var ps = d.psd;
      var t1 = { title: "(a) Two-sided PSD S₂ (rad²/s) versus ω/2π (Hz). Run " + d.run_id, headers: ["ω/2π (Hz)", "truth", "fit (MLE)", "95% lo", "95% hi"],
        rows: ps.f_hz.map(function (x, i) { return [sci(x, 3), sci(ps.truth[i]), sci(ps.mle[i]), sci(ps.lo[i]), sci(ps.hi[i])]; }) };
      var c0 = d.curves[keys[0]];
      var t2 = { title: "(b) Fitted P(+) (with SPAM) versus idle time T (µs): MLE [95% band]", headers: ["T (µs)"].concat(keys.map(function (k) { return CUR[k][2]; })),
        rows: c0.T_us.map(function (t, i) { return [fixed(t, 3)].concat(keys.map(function (k) { var c = d.curves[k]; return fixed(c.mle[i], 4) + " [" + fixed(c.lo[i], 4) + ", " + fixed(c.hi[i], 4) + "]"; })); }) };
      var t3 = { title: "Held-out observations (" + d.heldout.length + " of " + d.n_heldout_total + " shown in the chart; " + (d.heldout_other.join(", ") || "none") + " have no stored fitted curve)",
        headers: ["Family", "T (µs)", "P̂(+)"], rows: d.heldout.map(function (p) { return [CUR[p.label][2], fixed(p.T_us, 3), fixed(p.p_hat, 3)]; }) };
      return [t1, t2, t3];
    });
    panelsEl.classList.add("two");
    var live = liveRegion(container);
    responsive(panelsEl, function () {
      panelsEl.textContent = "";
      /* (a) PSD */
      var ps = d.psd;
      var pa = makePanel(panelsEl, "(a) Noise spectrum");
      var fa = frame(pa, { x: { type: "log", domain: [ps.f_hz[0], ps.f_hz[ps.f_hz.length - 1]] }, y: { type: "log", domain: extent(ps.lo.concat(ps.hi, ps.truth, ps.mle), 2, true) },
        xlabel: "ω/2π (Hz)", ylabel: "S₂(ω) (rad²/s)", ml: 54, aria: "True versus fitted two-sided PSD with 95% band. Use left and right arrow keys to read values." });
      var ta = Tooltip(pa);
      el("path", { d: bandPath(fa, ps.f_hz, ps.lo, ps.hi), "class": "band s-free" }, fa.g);
      el("path", { d: path(fa, ps.f_hz.map(function (x, i) { return { x: x, y: ps.mle[i] }; }), "x", "y"), "class": "ln s-free" }, fa.g);
      el("path", { d: path(fa, ps.f_hz.map(function (x, i) { return { x: x, y: ps.truth[i] }; }), "x", "y"), "class": "ln s-truth", "stroke-width": 1.4, "stroke-dasharray": DASH.dashed }, fa.g);
      lineInteraction(pa, fa, ps.f_hz, function (i) {
        return { head: "ω/2π = " + sci(ps.f_hz[i], 3) + " Hz", rows: [
          { fam: "free", value: sci(ps.mle[i]), label: "fit (MLE)" },
          { fam: "free", value: sci(ps.lo[i], 3) + "–" + sci(ps.hi[i], 3), label: "95% band" },
          { fam: "truth", dash: "dashed", value: sci(ps.truth[i]), label: "truth" }], note: "Run " + d.run_id };
      }, ta, live);
      /* (b) decays */
      var pb = makePanel(panelsEl, "(b) Decays, held-out data");
      var c0 = d.curves[keys[0]];
      var yv = [];
      keys.forEach(function (k) { yv = yv.concat(d.curves[k].lo, d.curves[k].hi); });
      d.heldout.forEach(function (p) { yv.push(p.p_hat); });
      var fb = frame(pb, { x: { type: "log", domain: [c0.T_us[0], c0.T_us[c0.T_us.length - 1]] }, y: { type: "lin", domain: extent(yv, 0.04, false) },
        xlabel: "idle time T (µs)", ylabel: "P(+) (with SPAM)", ml: 50, aria: "Fitted decay curves with 95% bands and held-out data. Use left and right arrow keys to read values." });
      var tb = Tooltip(pb);
      keys.forEach(function (k) {
        var c = d.curves[k];
        el("path", { d: bandPath(fb, c.T_us, c.lo, c.hi), "class": "band s-" + CUR[k][0] }, fb.g);
        el("path", { d: path(fb, c.T_us.map(function (x, i) { return { x: x, y: c.mle[i] }; }), "x", "y"), "class": "ln s-" + CUR[k][0] }, fb.g);
      });
      var extra = d.heldout.map(function (p) {
        var k = p.label, px = fb.X(p.T_us), py = fb.Y(p.p_hat);
        el("path", { d: shapeD("circle", px, py, 3.4), "class": "mk-open s-" + CUR[k][0] }, fb.g);
        return { px: px, py: py, head: "Held-out " + CUR[k][2], rows: [{ fam: CUR[k][0], line: false, shape: "circle", open: true, value: "P̂ = " + fixed(p.p_hat, 3), label: "T = " + fixed(p.T_us, 3) + " µs" }], note: "Never seen by the fit. Run " + d.run_id };
      });
      lineInteraction(pb, fb, c0.T_us, function (i) {
        var rows = keys.map(function (k) { var c = d.curves[k]; return { fam: CUR[k][0], value: fixed(c.mle[i], 3), label: CUR[k][2] + " [" + fixed(c.lo[i], 3) + ", " + fixed(c.hi[i], 3) + "]" }; });
        return { head: "T = " + fixed(c0.T_us[i], 3) + " µs (fit, 95% band)", rows: rows, note: "Run " + d.run_id };
      }, tb, live, extra);
    });
  }

  var CHARTS = { benchmark: benchmark, convergence: convergence, robustness: robustness, spectroscopy: spectroscopy };
  document.querySelectorAll("[data-chart]").forEach(function (c) {
    var k = c.getAttribute("data-chart");
    if (CHARTS[k] && DATA[k]) {
      try { CHARTS[k](c, DATA[k]); } catch (e) {
        c.textContent = "Chart failed to render; see the data table and the PDF figure.";
        if (window.console) console.error(e);
      }
    }
  });
})();
