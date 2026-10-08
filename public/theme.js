/**
 * Light-mode toggle for every page of the site except the wall screen
 * (contract-screen.html), which stays dark on the TV.
 *
 * The class itself is applied by a tiny inline script in each page's <head>,
 * so the dark palette never flashes before this file loads. All this does is
 * wire the button and remember the choice.
 *
 * Every colour lives in a CSS token, so the page restyles itself the moment
 * the class flips. Anything drawn in script that has to redraw can listen for
 * the "saragossa-theme" event on document (detail: { light: true | false }).
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
    try {
      document.dispatchEvent(new CustomEvent("saragossa-theme", { detail: { light: isLight } }));
    } catch (e) {}
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
