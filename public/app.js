/**
 * Saragossa Weekly Report — app.js
 * Fetches /api/report-data and renders territory tabs with team groupings.
 */

const TERRITORY_ORDER = [
  "Bristol",
  "London",
  "Chicago",
  "New York",
  "London Contract",
  "Chicago Contract",
];

const CONTRACT_TERRITORIES = new Set(["London Contract", "Chicago Contract"]);

// Highlight a consultant's NB-client count once it reaches this many
const NB_CLIENT_ALERT = 5;

// Consultants with a personal new-business target — clicking their name opens
// the drill-in (the API only allows the person themselves and admins to view)
const NB_TARGET_LINKS = { "Charlie Smith": "charlie@saragossa.io" };

// ── Boot ─────────────────────────────────────────────────────────────────────

(async () => {
  // Check if current user is admin (for settings link)
  checkAdminLink();

  // Fetch report data
  let data;
  try {
    const resp = await fetch("/api/report-data");
    if (resp.status === 401) {
      window.location.href = "/.auth/login/aad?post_login_redirect_uri=" + encodeURIComponent(window.location.pathname);
      return;
    }
    if (resp.status === 403) {
      window.location.href = "/403.html";
      return;
    }
    const text = await resp.text();
    try {
      data = JSON.parse(text);
    } catch (_) {
      showError(`API returned non-JSON (HTTP ${resp.status}): ${text.slice(0, 200)}`);
      return;
    }
  } catch (e) {
    showError(`Could not reach the API: ${e.message}`);
    return;
  }

  if (!data.ok) {
    showError(data.error || "Unknown error from API.");
    return;
  }

  renderReport(data);
})();


// ── Admin link visibility ─────────────────────────────────────────────────────

async function checkAdminLink() {
  try {
    const resp = await fetch("/.auth/me");
    const info = await resp.json();
    if (info?.clientPrincipal) {
      // We can't determine admin on the frontend alone — show a tentative link
      // and let /settings redirect non-admins with a 403 from the API
      document.getElementById("admin-link").style.display = "flex";
    }
  } catch (_) {}
}


// ── Render ────────────────────────────────────────────────────────────────────

function renderReport(data) {
  const asOf = new Date(data.as_of + "T00:00:00");
  const dateStr = asOf.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

  document.getElementById("report-date").textContent = dateStr;
  document.getElementById("footer").textContent = `Week ending ${dateStr} · Saragossa`;
  document.getElementById("data-note").textContent =
    `Live · Mercury · ${asOf.getFullYear()} FX rates`;

  const report = data.report;
  const tabsEl  = document.getElementById("tabs");
  const panelsEl = document.getElementById("panels");
  tabsEl.innerHTML  = "";
  panelsEl.innerHTML = "";

  let first = true;
  for (const territory of TERRITORY_ORDER) {
    if (!report[territory]) continue;

    const tab = document.createElement("div");
    tab.className = "tab" + (first ? " active" : "");
    tab.textContent = territory;
    tab.dataset.panel = territory;
    tabsEl.appendChild(tab);

    const panel = document.createElement("div");
    panel.className = "panel" + (first ? " active" : "");
    panel.id = "panel-" + territory;

    const isContract = CONTRACT_TERRITORIES.has(territory);
    const tdata = report[territory];

    if (isContract) {
      panel.appendChild(buildContractTable(tdata));
    } else if (tdata.type === "teams") {
      panel.appendChild(buildPermTeamTable(tdata.groups));
    } else {
      panel.appendChild(buildPermFlatTable(tdata.members));
    }

    panelsEl.appendChild(panel);
    first = false;
  }

  // Tab click handlers
  tabsEl.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      tabsEl.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      panelsEl.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById("panel-" + tab.dataset.panel).classList.add("active");
    });
  });

  // NB-clients drill-down
  panelsEl.addEventListener("click", (e) => {
    const tgt = e.target.closest(".nbt-link");
    if (tgt) { showNbTarget(tgt.dataset.who); return; }
    const sp = e.target.closest(".split-link");
    if (sp) {
      showSplit(sp.dataset.name, sp.dataset.label, sp.dataset.sym,
                parseFloat(sp.dataset.perm), parseFloat(sp.dataset.sol));
      return;
    }
    const reb = e.target.closest(".rebate-link");
    if (reb) {
      let rows = [];
      try { rows = JSON.parse(reb.dataset.rebates || "[]"); } catch (_) {}
      showRebates(reb.dataset.name, reb.dataset.sym, rows);
      return;
    }
    const el = e.target.closest(".nb-clients-link");
    if (!el) return;
    let names = [];
    try { names = JSON.parse(el.dataset.clients || "[]"); } catch (_) {}
    showNbClients(el.dataset.name, names);
  });
}

// ── NB clients drill-down modal ────────────────────────────────────────────────

function showNbClients(name, clients) {
  let overlay = document.getElementById("nb-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "nb-modal";
    overlay.className = "modal-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title" id="nb-modal-title"></span>
        <button class="modal-close" id="nb-modal-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body" id="nb-modal-body"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#nb-modal-close").addEventListener("click", () => { overlay.style.display = "none"; });
  }
  const n = clients.length;
  overlay.querySelector("#nb-modal-title").textContent = `${name} — ${n} NB ${n === 1 ? "client" : "clients"} (rolling 12m)`;
  overlay.querySelector("#nb-modal-body").innerHTML = n
    ? `<ul class="nb-client-list">${clients.map(c => {
        const nm  = typeof c === "string" ? c : c.name;
        const rec = typeof c === "object" && c.recognised;
        return `<li>${esc(nm)}${rec ? ' <span class="nb-flag">previous milestone</span>' : ""}</li>`;
      }).join("")}</ul>`
    : `<p class="nb-client-empty">No new-business clients.</p>`;
  overlay.style.display = "flex";
}


// ── Perm / Solution split drill-down ──────────────────────────────────────────

function showSplit(name, label, sym, perm, solution) {
  let overlay = document.getElementById("split-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "split-modal";
    overlay.className = "modal-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title" id="split-title"></span>
        <button class="modal-close" id="split-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body" id="split-body"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#split-close").addEventListener("click", () => { overlay.style.display = "none"; });
  }
  overlay.querySelector("#split-title").textContent = `${name} — ${label}`;
  overlay.querySelector("#split-body").innerHTML = `
    <div class="table-wrap"><table>
      <tbody>
        <tr><td>Perm Revenue</td><td class="num">${fmt(perm, sym)}</td></tr>
        <tr><td>Solution Revenue</td><td class="num">${fmt(solution, sym)}</td></tr>
        <tr class="split-total"><td><strong>Total</strong></td>
            <td class="num"><strong>${fmt(perm + solution, sym)}</strong></td></tr>
      </tbody>
    </table></div>
    <p class="nbt-note">Solution Revenue is Deploy &amp; Component work entered against this consultant.
    It counts toward their ${esc(label)} here and toward US quarterly HPB billings, but is reported
    separately on Analytics and excluded from perm written totals and budgets.</p>`;
  overlay.style.display = "flex";
}


// ── Rebate drill-down ─────────────────────────────────────────────────────────

function showRebates(name, sym, rows) {
  let overlay = document.getElementById("reb-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "reb-modal";
    overlay.className = "modal-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title" id="reb-title"></span>
        <button class="modal-close" id="reb-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body" id="reb-body"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#reb-close").addEventListener("click", () => { overlay.style.display = "none"; });
  }
  const d = (s) => new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  overlay.querySelector("#reb-title").textContent = `${name} — rebates in the rolling 12 months`;
  overlay.querySelector("#reb-body").innerHTML = rows.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Placement</th><th>Client</th><th class="num">Started</th><th class="num">Rebated on</th><th class="num">Fee back</th><th class="num">NB uplift back</th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td>${esc(r.job_title)}</td><td>${esc(r.client)}</td>
          <td class="num">${d(r.start_date)}</td><td class="num">${d(r.rebated_on)}</td>
          <td class="num">${r.amount ? "−" + fmt(r.amount, sym) : "—"}</td>
          <td class="num">${r.uplift ? "−" + fmt(r.uplift, sym) : "—"}</td>
        </tr>`).join("")}</tbody></table></div>
       <p class="nbt-note">The placement still counts — only the rebated portion of the fee (and the
       new-business uplift on that portion) is deducted, in the month it was rebated.</p>`
    : `<p class="nb-client-empty">No rebates in the window.</p>`;
  overlay.style.display = "flex";
}


// ── New-business target drill-in ──────────────────────────────────────────────

async function showNbTarget(who, asOf) {
  let overlay = document.getElementById("nbt-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "nbt-modal";
    overlay.className = "modal-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title" id="nbt-title"></span>
        <button class="modal-close" id="nbt-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body" id="nbt-body"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#nbt-close").addEventListener("click", () => { overlay.style.display = "none"; });
  }
  overlay.querySelector("#nbt-title").textContent = "New Business Clients";
  overlay.querySelector("#nbt-body").innerHTML = `<p class="nb-client-empty">Loading…</p>`;
  overlay.style.display = "flex";

  let data;
  try {
    const qs = `who=${encodeURIComponent(who)}` + (asOf ? `&as_of=${encodeURIComponent(asOf)}` : "");
    const resp = await fetch(`/api/nb-target?${qs}`);
    if (resp.status === 403) {
      overlay.querySelector("#nbt-body").innerHTML =
        `<p class="nb-client-empty">Only this consultant and admins can view this.</p>`;
      return;
    }
    data = await resp.json();
    if (!data.ok) throw new Error(data.error || "unknown error");
  } catch (e) {
    overlay.querySelector("#nbt-body").innerHTML =
      `<p class="nb-client-empty">Could not load: ${esc(e.message)}</p>`;
    return;
  }

  overlay.querySelector("#nbt-title").textContent = `${data.name} — New Business Clients`;

  const render = (includeContract) => {
    const total = data.perm_total + (includeContract ? data.contract_total : 0);
    const pct = Math.min(100, (total / data.target) * 100);
    const rows = data.clients.map((c, i) => {
      const t = c.perm12 + (includeContract ? c.contract12 : 0);
      const pls = (c.placements || []).filter(p => includeContract || p.kind === "Perm");
      const detail = pls.map(p => `<tr class="nbt-pl${p.counts ? "" : " nbt-pl-out"}">
          <td>${esc(p.job_title)}</td>
          <td>${esc(p.candidate)}</td>
          <td class="num">${new Date(p.start_date + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</td>
          <td class="num">${esc(p.currency)} ${Math.round(p.fee).toLocaleString("en-GB")}</td>
          <td class="num">${p.counts ? fmt(p.fee_gbp, "£") : `<span class="nbt-out-tag">${p.kind === "Extension" ? "extension" : "outside 12M"}</span>`}</td>
        </tr>`).join("");
      return `<tr class="nbt-client-row" data-idx="${i}">
        <td><span class="nbt-caret">▶</span> ${esc(c.name)}</td>
        <td class="num">${new Date(c.first_date + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</td>
        <td class="num">${fmt(c.perm12, "£")}</td>
        <td class="num">${includeContract ? fmt(c.contract12, "£") : "—"}</td>
        <td class="num"><strong>${fmt(t, "£")}</strong></td>
      </tr>
      <tr class="nbt-detail-row" id="nbt-detail-${i}" style="display:none"><td colspan="5">
        <table class="nbt-detail">
          <thead><tr><th>Job title</th><th>Candidate</th><th class="num">Start date</th><th class="num">Fee</th><th class="num">Counts (GBP)</th></tr></thead>
          <tbody>${detail || `<tr><td colspan="5" class="nb-client-empty">No placements.</td></tr>`}</tbody>
        </table>
      </td></tr>`;
    }).join("");
    overlay.querySelector("#nbt-body").innerHTML = `
      <div class="nbt-summary">
        <div class="nbt-total">${fmt(total, "£")} <span class="nbt-of">of ${fmt(data.target, "£")} target · ${pct.toFixed(1)}%</span></div>
        ${asOf ? `<div class="nbt-projected">Projected position at ${new Date(data.as_of + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })} — includes placements already booked to start by then</div>` : ""}
        <div class="nbt-bar"><div class="nbt-bar-fill${total >= data.target ? " nbt-bar-hit" : ""}" style="width:${pct}%"></div></div>
        <div class="nbt-controls">
          <label class="nbt-toggle"><input type="checkbox" id="nbt-contract" ${includeContract ? "checked" : ""}> Include contract</label>
          <label class="nbt-toggle">Position as at
            <input type="date" id="nbt-date" value="${esc(data.as_of)}">
          </label>
          ${asOf ? `<button class="nbt-today" id="nbt-today">Back to today</button>` : ""}
        </div>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Client</th><th class="num">First placement</th><th class="num">Perm 12M</th><th class="num">Contract 12M</th><th class="num">Total 12M</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5" class="nb-client-empty">No new clients yet.</td></tr>`}</tbody>
      </table></div>
      <p class="nbt-note">New clients = first-ever placement on/after 1 Jan 2025 with ${esc(data.name)} as CRO ·
        all placements at those clients count · full placement GP, rolling 12 months by start date
        (${new Date(data.roll12_start + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} – today) ·
        contract = initial contracts only, extensions excluded · all figures GBP</p>`;
    overlay.querySelectorAll(".nbt-client-row").forEach(row => {
      row.addEventListener("click", () => {
        const det = overlay.querySelector("#nbt-detail-" + row.dataset.idx);
        const open = det.style.display !== "none";
        det.style.display = open ? "none" : "table-row";
        row.querySelector(".nbt-caret").textContent = open ? "▶" : "▼";
      });
    });
    overlay.querySelector("#nbt-contract").addEventListener("change", (e) => render(e.target.checked));
    overlay.querySelector("#nbt-date").addEventListener("change", (e) => {
      if (e.target.value) showNbTarget(who, e.target.value);
    });
    const todayBtn = overlay.querySelector("#nbt-today");
    if (todayBtn) todayBtn.addEventListener("click", () => showNbTarget(who));
  };
  render(true);
}


// ── Table builders ────────────────────────────────────────────────────────────

function permHeaders() {
  return `<thead><tr>
    <th>Consultant</th>
    <th>Role</th>
    <th class="num">YTD Perm</th>
    <th class="num">Written Perm</th>
    <th class="num">Year Prediction</th>
    <th class="num">Rolling 12M</th>
    <th class="num">NB Uplift</th>
    <th class="num">12M Total</th>
  </tr></thead>`;
}

function nameCell(name) {
  const who = NB_TARGET_LINKS[name];
  if (!who) return esc(name);
  return `<span class="nbt-link" data-who="${esc(who)}" title="New business target">${esc(name)}</span>`;
}

// YTD and Rolling 12M include Deploy & Component revenue when there is any —
// shown as a total, clickable for the Perm / Solution split.
function splitCell(m, total, permKey, solKey, label) {
  const sol = m[solKey] || 0;
  if (!sol) return fmt(total, m.sym);
  return `<span class="split-link" data-name="${esc(m.name)}" data-label="${esc(label)}"
      data-sym="${esc(m.sym)}" data-perm="${m[permKey] || 0}" data-sol="${sol}"
      >${fmt(total, m.sym)}</span>`;
}

function permRow(m) {
  return `<tr>
    <td>${nameCell(m.name)}</td>
    <td class="role-cell">${esc(m.role)}</td>
    <td class="num">${splitCell(m, m.ytd, "perm_ytd", "solution_ytd", "YTD")}</td>
    <td class="num">${fmt(m.written, m.sym)}</td>
    <td class="num">${fmt(m.year_pred, m.sym)}</td>
    <td class="num">${splitCell(m, m.roll12, "perm_roll12", "solution_roll12", "Rolling 12M")}${rebateHtml(m)}</td>
    <td class="num">${fmt(m.roll12_uplift, m.sym)}${nbClientsHtml(m)}</td>
    <td class="num">${fmt(m.roll12_total, m.sym)}</td>
  </tr>`;
}

// A rebate has already been netted off the figures — this shows what came off.
function rebateHtml(m) {
  if (!m.rebate_total) return "";
  return `<span class="rebate-note rebate-link" data-name="${esc(m.name)}" data-sym="${esc(m.sym)}"
      data-rebates="${esc(JSON.stringify(m.rebate_detail || []))}"
      >−${fmt(m.rebate_total, m.sym)} rebate</span>`;
}

function nbClientsHtml(m) {
  const total = m.nb_clients || 0;
  if (total === 0) return "";
  const nu = m.nb_new_count != null ? m.nb_new_count : total;
  const recognised = total - nu;                 // clients already in a milestone
  const pending = nu >= NB_CLIENT_ALERT;         // unrecognised milestone waiting
  let html = `<span class="nb-clients nb-clients-link${pending ? " nb-clients-hit" : ""}"
      data-name="${esc(m.name)}" data-clients="${esc(JSON.stringify(m.nb_client_detail || []))}">${total} NB ${total === 1 ? "client" : "clients"}</span>`;
  if (recognised > 0 && !pending) {
    html += `<span class="nb-clients nb-recognised">✓ milestone recognised${nu > 0 ? ` · ${nu} new` : ""}</span>`;
  }
  return html;
}

function buildPermTeamTable(groups) {
  let body = "";
  for (const g of groups) {
    body += `<tr class="team-header"><td colspan="8">${esc(g.team)}</td></tr>`;
    body += g.members.map(permRow).join("");
  }
  return tableWrap(`<table>${permHeaders()}<tbody>${body}</tbody></table>`);
}

function buildPermFlatTable(members) {
  const body = members.map(permRow).join("");
  return tableWrap(`<table>${permHeaders()}<tbody>${body}</tbody></table>`);
}

function buildContractTable(tdata) {
  const members = tdata.type === "flat" ? tdata.members : tdata.groups.flatMap(g => g.members);
  const headers = `<thead><tr>
    <th>Consultant</th>
    <th>Role</th>
    <th class="num">Total Margin YTD</th>
    <th class="num">Contract Last 12M</th>
    <th class="num">Rolling 3M</th>
    <th class="num">Current WNF</th>
    <th class="num">Year Billing</th>
  </tr></thead>`;

  const body = members.map(m => {
    const yearBilling = m.wnf > 0
      ? m.sym + Math.round(m.wnf * 48).toLocaleString("en-GB")
      : "—";
    return `<tr>
      <td>${esc(m.name)}</td>
      <td class="role-cell">${esc(m.role)}</td>
      <td class="num">${m.margin_ytd       != null ? fmt(m.margin_ytd,       m.sym) : "—"}</td>
      <td class="num">${m.contract_last12m != null ? fmt(m.contract_last12m, m.sym) : "—"}</td>
      <td class="num">${m.rolling_3m       != null ? fmt(m.rolling_3m,       m.sym) : "—"}</td>
      <td class="num">${fmt(m.wnf, m.sym)}</td>
      <td class="num year-billing-cell">${yearBilling}</td>
    </tr>`;
  }).join("");

  return tableWrap(`<table class="contract-table">${headers}<tbody>${body}</tbody></table>`);
}


// ── Utilities ─────────────────────────────────────────────────────────────────

function tableWrap(inner) {
  const div = document.createElement("div");
  div.className = "table-wrap";
  div.innerHTML = inner;
  return div;
}

function fmt(n, sym) {
  if (!n || n === 0) return `${sym}0`;
  return sym + Math.round(n).toLocaleString("en-GB");
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function showError(msg) {
  document.getElementById("panels").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
  document.getElementById("data-note").textContent = "Error";
}
