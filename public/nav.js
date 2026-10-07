/**
 * The header's way around, shared by every page.
 *
 * The home page is the menu: a card per section with pills per team. So inside
 * a section the header carries only a way back to it — no copy of the menu in
 * the corner (Jason, Oct 2026). The home page itself shows nothing here.
 *
 * SaragossaNav.load() is kept for the home page: it fetches the sections this
 * person can open from /api/home, which runs each section's own access check.
 */
(function () {
  // Remembered between visits so the home page can draw at once while it
  // checks for changes. Only which sections to show — every section still
  // checks access itself — and cleared on sign-out for shared computers.
  const KEY = "saragossa-home-v2";
  const TTL_MS = 7 * 24 * 60 * 60 * 1000;

  function cached() {
    try {
      const c = JSON.parse(localStorage.getItem(KEY) || "null");
      return c && Date.now() - c.at < TTL_MS ? c.sections : null;
    } catch (_) { return null; }
  }

  function remember(sections) {
    try { localStorage.setItem(KEY, JSON.stringify({ at: Date.now(), sections })); } catch (_) {}
  }

  function forget() {
    try { localStorage.removeItem(KEY); sessionStorage.removeItem("saragossa-home-v1"); } catch (_) {}
  }

  // Signing out forgets them, so the next person on this computer starts clean
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest('a[href^="/.auth/logout"]');
    if (a) forget();
  });

  async function load() {
    const resp = await fetch("/api/home");
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return null; }
    const d = await resp.json();
    if (!d.ok) return null;
    remember(d.sections);
    return d.sections;
  }

  function renderBackLink(host) {
    host.textContent = "";
    if (host.dataset.active === "home") return;      // the home page is the menu
    const a = document.createElement("a");
    a.href = "/";
    a.className = "menu-link home-back";
    a.textContent = "← Home";
    host.appendChild(a);
  }

  window.SaragossaNav = { load, remember, cached, forget, render() {} };

  const host = document.getElementById("main-menu");
  if (host) renderBackLink(host);
})();
