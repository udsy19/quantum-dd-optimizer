/* Apply a stored theme choice before first paint. No stored choice -> follow the OS. */
(function () {
  try {
    var t = window.localStorage.getItem("ddopt-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* storage unavailable: follow prefers-color-scheme */ }
})();
