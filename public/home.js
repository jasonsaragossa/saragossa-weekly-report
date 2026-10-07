/**
 * Home: one card per section this person can open, each with what it's for
 * underneath, and a pill per team where a section has teams (Jason, Oct 2026).
 *
 * Someone who can only open the Weekly Report goes straight to it — a menu of
 * one is a click for nothing.
 */
(async () => {
  const grid = document.getElementById("home-grid");
  const nav = window.SaragossaNav;
  let shown = null;

  function draw(sections) {
    const sig = JSON.stringify(sections);
    if (sig === shown) return;               // nothing changed — don't redraw
    shown = sig;
    if (sections.length === 1 && sections[0].key === "report") {
      window.location.replace("/report");
      return;
    }
    grid.textContent = "";
    sections.forEach(s => grid.appendChild(card(s)));
  }

  // Draw at once from last time, then check for changes. Working out a
  // person's sections takes the server a couple of seconds; there's no
  // reason to make them watch a spinner for it on every visit.
  const remembered = nav.cached();
  if (remembered) draw(remembered);

  let fresh = null;
  try { fresh = await nav.load(); } catch (_) { /* handled below */ }
  if (fresh) draw(fresh);
  else if (!remembered) {
    grid.innerHTML = `<p class="mbr-empty">Couldn't load your sections. Try refreshing.</p>`;
  }
})();

// Built with DOM calls and textContent: names come from Mercury, so they are
// never handed to innerHTML.
//
// Every card works the same way: the card itself is not a link, and every
// destination is a pill. A one-place section gets a single "Open" pill, so it
// is never a case of "click anywhere here, but only the tabs there" (Jason,
// Oct 2026).
function card(s) {
  const el = document.createElement("section");
  el.className = "home-card";

  const h = document.createElement("h2");
  h.className = "home-card-title";
  h.textContent = s.title;
  el.appendChild(h);

  const p = document.createElement("p");
  p.className = "home-card-desc";
  p.textContent = s.description;
  el.appendChild(p);

  const pills = (s.pills && s.pills.length) ? s.pills
    : (s.href ? [{ label: "Open", href: s.href, primary: true }] : []);
  if (pills.length) {
    const row = document.createElement("div");
    row.className = "home-pills";
    pills.forEach(pl => {
      const a = document.createElement("a");
      a.className = "home-pill" + (pl.primary ? " home-pill-open" : "");
      a.href = pl.href;
      a.textContent = pl.label;
      if (pl.primary) a.setAttribute("aria-label", `Open ${s.title}`);
      row.appendChild(a);
    });
    el.appendChild(row);
  }
  return el;
}
