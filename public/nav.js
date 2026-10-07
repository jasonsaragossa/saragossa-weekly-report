/**
 * The header menu, shared by every page.
 *
 * Shows only the sections this person can actually open — the same list the
 * home page shows, from /api/home, which runs each section's own access check.
 * It used to be six hand-copied link rows that showed everyone everything
 * (Analytics included), leaving most people to click into a 403.
 *
 * The list takes a few seconds to work out, so it's remembered for the session
 * for ten minutes; the home page refreshes it whenever it loads.
 */
(function () {
  const KEY = "saragossa-home-v1";
  const TTL_MS = 10 * 60 * 1000;

  // Section -> the menu entries it contributes
  const MENU = {
    report: [{ id: "report", label: "Weekly Report", href: "/report" }],
    "121":  [{ id: "121", label: "121s", href: "/121" }],
    mbr:    [{ id: "mbr", label: "MBRs", href: "/mbr" }],
    perf:   [{ id: "perf", label: "Performance Stats", href: "/performance" }],
    admin:  [{ id: "admin", label: "Analytics", href: "/admin" },
             { id: "settings", label: "⚙ Settings", href: "/settings" }],
  };

  function cached() {
    try {
      const c = JSON.parse(sessionStorage.getItem(KEY) || "null");
      return c && Date.now() - c.at < TTL_MS ? c.sections : null;
    } catch (_) { return null; }
  }

  function remember(sections) {
    try { sessionStorage.setItem(KEY, JSON.stringify({ at: Date.now(), sections })); } catch (_) {}
  }

  function render(host, sections) {
    const active = host.dataset.active || "";
    host.textContent = "";
    const items = [{ id: "home", label: "Home", href: "/" }];
    (sections || []).forEach(s => items.push(...(MENU[s.key] || [])));
    items.forEach(it => {
      const a = document.createElement("a");
      a.href = it.href;
      a.className = "menu-link" + (it.id === active ? " active" : "");
      a.textContent = it.label;
      host.appendChild(a);
    });
  }

  async function load() {
    const resp = await fetch("/api/home");
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return null; }
    const d = await resp.json();
    if (!d.ok) return null;
    remember(d.sections);
    return d.sections;
  }

  // Exposed so the home page can reuse one fetch for both its cards and the menu
  window.SaragossaNav = {
    load, remember, cached,
    render(sections) {
      const host = document.getElementById("main-menu");
      if (host) render(host, sections);
    },
  };

  const host = document.getElementById("main-menu");
  if (!host || host.dataset.manual === "1") return;
  const have = cached();
  if (have) { render(host, have); return; }
  render(host, [{ key: "report" }]);           // something useful straight away
  load().then(s => { if (s) render(host, s); }).catch(() => {});
})();
