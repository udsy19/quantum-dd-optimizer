/* Page behaviour: nav, math, table of contents, provenance popovers, copy buttons. */
(function () {
  "use strict";
  /* ---- nav: hairline once the page scrolls ---- */
  var nav = document.getElementById("nav");
  function navLine() { if (nav) nav.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", navLine, { passive: true });
  navLine();

  /* ---- math ---- */
  function renderMath() {
    if (!window.katex) return;
    /* .math.inline / .math.display: pandoc --katex output rendered from report/; .tex: site text */
    document.querySelectorAll(".math.inline, .math.display, .tex, .tex-display").forEach(function (el) {
      var src = el.textContent;
      var display = el.classList.contains("display") || el.classList.contains("tex-display");
      try {
        window.katex.render(src, el, { displayMode: display, throwOnError: false, output: "htmlAndMathml" });
        el.classList.add("katex-rendered");
      } catch (e) { el.textContent = src; }
    });
  }
  renderMath();

  /* ---- table of contents: collapsed on small screens, scroll-spy everywhere ---- */
  var toc = document.querySelector("details.toc");
  var wide = window.matchMedia("(min-width: 1100px)");
  function syncToc() { if (toc) { if (wide.matches) toc.setAttribute("open", ""); else toc.removeAttribute("open"); } }
  syncToc();
  if (wide.addEventListener) wide.addEventListener("change", syncToc);
  if (toc) {
    toc.addEventListener("click", function (e) {
      if (e.target.closest("a") && !wide.matches) toc.removeAttribute("open");
    });
  }
  var links = Array.prototype.slice.call(document.querySelectorAll(".toc a[href^='#']"));
  var targets = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); }).filter(Boolean);
  function spy() {
    var y = window.scrollY + 120, active = null;
    for (var i = 0; i < targets.length; i++) if (targets[i].getBoundingClientRect().top + window.scrollY <= y) active = targets[i];
    links.forEach(function (a) {
      if (active && a.getAttribute("href") === "#" + active.id) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(function () { spy(); ticking = false; }); }
  }, { passive: true });
  spy();

  /* ---- provenance popovers on numbers ---- */
  var pop = document.getElementById("prov-pop");
  var current = null, hideTimer = null, shownAt = 0;
  function row(dl, k, v, isCode, href) {
    var dt = document.createElement("dt"); dt.textContent = k;
    var dd = document.createElement("dd");
    var node = document.createElement(isCode ? "code" : "span");
    node.textContent = v;
    if (href) { var a = document.createElement("a"); a.href = href; a.appendChild(node); dd.appendChild(a); } else dd.appendChild(node);
    dl.appendChild(dt); dl.appendChild(dd);
  }
  function show(el) {
    if (!pop) return;
    clearTimeout(hideTimer);
    if (current !== el || pop.hidden) shownAt = Date.now();
    current = el;
    pop.textContent = "";
    var t = document.createElement("div"); t.className = "pv-title"; t.textContent = el.getAttribute("data-claim") || "Recorded value";
    var dl = document.createElement("dl");
    row(dl, "Macro", "\\" + el.getAttribute("data-macro"), true);
    row(dl, "Run", el.getAttribute("data-provenance"), true, el.getAttribute("data-href"));
    row(dl, "Command", el.getAttribute("data-cmd"), true);
    row(dl, "Code", el.getAttribute("data-commit") || "unknown", true);
    pop.appendChild(t); pop.appendChild(dl);
    pop.hidden = false;
    var r = el.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left + window.scrollX + r.width / 2 - pw / 2), window.scrollX + document.documentElement.clientWidth - pw - 8);
    var top = r.bottom + window.scrollY + 8;
    if (r.bottom + ph + 16 > window.innerHeight && r.top > ph + 16) top = r.top + window.scrollY - ph - 8;
    pop.style.left = left + "px"; pop.style.top = top + "px";
    el.setAttribute("aria-describedby", "prov-pop");
  }
  function hide(delay) {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () {
      if (pop) pop.hidden = true;
      if (current) current.removeAttribute("aria-describedby");
      current = null;
    }, delay || 0);
  }
  document.querySelectorAll(".num").forEach(function (el) {
    el.addEventListener("pointerenter", function (e) { if (e.pointerType === "mouse") show(el); });
    el.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") hide(250); });
    el.addEventListener("focus", function () { show(el); });
    el.addEventListener("blur", function () { hide(150); });
    el.addEventListener("click", function (e) { e.stopPropagation(); if (current === el && !pop.hidden && Date.now() - shownAt > 400) hide(); else show(el); });
  });
  if (pop) {
    pop.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    pop.addEventListener("mouseleave", function () { hide(150); });
  }
  document.addEventListener("click", function (e) { if (pop && !pop.hidden && !pop.contains(e.target)) hide(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });

  /* ---- copy buttons ---- */
  document.querySelectorAll("button.copy").forEach(function (b) {
    b.addEventListener("click", function () {
      var src = document.getElementById(b.getAttribute("data-copy"));
      if (!src) return;
      var text = src.textContent, label = b.textContent;
      function done(ok) { b.textContent = ok ? "Copied" : "Press Ctrl+C"; setTimeout(function () { b.textContent = label; }, 1600); }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { selectText(src); done(false); });
      } else { selectText(src); done(false); }
    });
  });
  function selectText(node) {
    var r = document.createRange(); r.selectNodeContents(node);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  }
})();
