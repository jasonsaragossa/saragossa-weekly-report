/**
 * Light-mode toggle for the pages that opt in (121s and MBRs).
 *
 * The class itself is applied by a tiny inline script at the top of the body,
 * so the dark palette never flashes before this file loads. All this does is
 * wire the button and remember the choice.
 *
 * Stored per browser, not per user — it is a reading preference, not data.
 */
(function () {
  var KEY = "saragossa-theme";

  function label(isLight) {
    return isLight ? "◐ Dark" : "◑ Light";
  }

  function apply(isLight) {
    document.documentElement.classList.toggle("theme-light", isLight);
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.textContent = label(isLight);
      btn.title = isLight ? "Switch to dark mode" : "Switch to light mode";
      btn.setAttribute("aria-pressed", String(isLight));
    }
  }

  function init() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    apply(document.documentElement.classList.contains("theme-light"));
    btn.addEventListener("click", function () {
      var isLight = !document.documentElement.classList.contains("theme-light");
      apply(isLight);
      // A browser with storage blocked still toggles for this page view.
      try { localStorage.setItem(KEY, isLight ? "light" : "dark"); } catch (e) {}
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
