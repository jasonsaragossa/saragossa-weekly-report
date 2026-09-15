/**
 * Contract desks on a wall screen — Contract UK in GBP, Contract USA in USD.
 *
 * Meant to be framed by OneUp, which cannot sign in, so the page carries its
 * key in the URL (?key=…) and passes it to the API. The figures are the weekly
 * report's own; the API caches them for a few minutes, and this page re-reads
 * every five so a screen left on all day stays current without hammering it.
 */
(function () {
  var REFRESH_MS = 5 * 60 * 1000;
  var params = new URLSearchParams(location.search);
  var key = params.get("key") || "";
  // ?desk=uk or ?desk=usa shows one desk full-width; nothing shows both.
  var only = { uk: "Contract UK", usa: "Contract USA" }[(params.get("desk") || "").toLowerCase()];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Whole units only — a wall screen is read from across a room.
  function money(n, sym) {
    n = Math.round(n || 0);
    var s = Math.abs(n).toLocaleString("en-GB");
    return (n < 0 ? "-" : "") + sym + s;
  }

  function desk(d) {
    var rows = d.rows.map(function (r) {
      return "<tr><td>" + esc(r.name) + "</td>" +
        '<td class="num">' + money(r.wnf, d.sym) + "</td>" +
        '<td class="num">' + money(r.ytd, d.sym) + "</td>" +
        '<td class="num">' + money(r.l12, d.sym) + "</td></tr>";
    }).join("");
    if (!rows) rows = '<tr><td class="empty" colspan="4">Nothing to show yet.</td></tr>';
    // No team total on the wall — it is the individuals that are being shown.
    return '<section class="desk"><h2>' + esc(d.label) +
      '<span class="ccy">' + esc(d.currency) + "</span></h2>" +
      '<div class="scaler"><table><thead><tr><th>Consultant</th>' +
      '<th class="num">WNF</th><th class="num">Actual YTD Billing</th>' +
      '<th class="num">Actual Last 12M</th></tr></thead><tbody>' + rows +
      "</tbody></table></div></section>";
  }

  // A long team must not spill off the bottom of a fixed screen: if the table
  // is taller than its panel, shrink it uniformly to fit rather than scroll.
  function fit() {
    document.querySelectorAll(".scaler").forEach(function (box) {
      var table = box.querySelector("table");
      if (!table) return;
      table.style.transform = "";
      table.style.width = "";
      var avail = box.clientHeight, need = table.scrollHeight;
      if (need > avail && avail > 0) {
        var scale = Math.max(0.45, avail / need);
        table.style.transform = "scale(" + scale + ")";
        table.style.width = (100 / scale) + "%";
      }
    });
  }

  function render(data) {
    var desks = only ? data.desks.filter(function (d) { return d.label === only; }) : data.desks;
    var el = document.getElementById("desks");
    el.classList.toggle("single", desks.length === 1);
    el.innerHTML = desks.map(desk).join("");
    var asOf = new Date(data.as_of + "T00:00:00");
    document.getElementById("asof").textContent =
      asOf.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    document.getElementById("updated").textContent =
      "Updated " + new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    document.getElementById("err").classList.remove("show");
    fit();
  }

  function fail(msg) {
    var el = document.getElementById("err");
    el.textContent = msg;
    el.classList.add("show");
  }

  async function load() {
    if (!key) { fail("This screen needs its key in the address (?key=…)."); return; }
    try {
      var resp = await fetch("/api/contract-screen?key=" + encodeURIComponent(key) +
                             "&t=" + Date.now(), { cache: "no-store" });
      if (resp.status === 403) { fail("The key in this screen's address is not valid."); return; }
      var data = await resp.json();
      if (!data.ok) throw new Error(data.error || "unknown error");
      render(data);
    } catch (e) {
      // Keep whatever is already on screen; only say so if there is nothing.
      if (!document.getElementById("desks").children.length) fail("Could not load: " + e.message);
    }
  }

  load();
  setInterval(load, REFRESH_MS);
  window.addEventListener("resize", fit);
})();
