/**
 * Home: one card per section this person can open, each with what it's for
 * underneath, and a pill per team where a section has teams (Jason, Oct 2026).
 *
 * Someone who can only open the Weekly Report goes straight to it — a menu of
 * one is a click for nothing.
 */
(async () => {
  const grid = document.getElementById("home-grid");
  let sections = null;
  try {
    sections = await window.SaragossaNav.load();
  } catch (_) { /* handled below */ }
  if (!sections) {
    grid.innerHTML = `<p class="mbr-empty">Couldn't load your sections — try refreshing.</p>`;
    return;
  }
  window.SaragossaNav.render(sections);

  if (sections.length === 1 && sections[0].key === "report") {
    window.location.replace("/report");
    return;
  }

  grid.textContent = "";
  sections.forEach(s => grid.appendChild(card(s)));
})();

// Built with DOM calls and textContent: names come from Mercury, so they are
// never handed to innerHTML.
function card(s) {
  const el = document.createElement(s.href ? "a" : "section");
  el.className = "home-card";
  if (s.href) el.href = s.href;

  const h = document.createElement("h2");
  h.className = "home-card-title";
  h.textContent = s.title;
  el.appendChild(h);

  const p = document.createElement("p");
  p.className = "home-card-desc";
  p.textContent = s.description;
  el.appendChild(p);

  if (s.pills && s.pills.length) {
    const row = document.createElement("div");
    row.className = "home-pills";
    s.pills.forEach(pl => {
      const a = document.createElement("a");
      a.className = "home-pill";
      a.href = pl.href;
      a.textContent = pl.label;
      row.appendChild(a);
    });
    el.appendChild(row);
  } else if (s.href) {
    const go = document.createElement("span");
    go.className = "home-open";
    go.textContent = "Open →";
    el.appendChild(go);
  }
  return el;
}
