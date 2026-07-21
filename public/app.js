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

  // "Created this month" tab — placements created per region this month
  const mc = data.month_created;
  if (mc && Object.keys(mc.territories || {}).length) {
    const tab = document.createElement("div");
    tab.className = "tab";
    tab.textContent = mc.label;
    tab.dataset.panel = "month";
    tabsEl.appendChild(tab);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.id = "panel-month";
    panel.appendChild(buildMonthPanel(mc));
    panelsEl.appendChild(panel);
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


// ── "Created this month" panel ────────────────────────────────────────────────

function buildMonthPanel(mc) {
  const container = document.createElement("div");
  const order = [...TERRITORY_ORDER, "Cameron Scott", "Other"];
  for (const t of order) {
    const td = mc.territories[t];
    if (!td) continue;
    const h = document.createElement("h3");
    h.className = "hpb-territory-heading";
    h.textContent = `${t} — ${td.count} placement${td.count === 1 ? "" : "s"} · ` +
      `${td.nb_count} new business · ${fmt(td.revenue, td.sym) || td.sym + "0"}`;
    container.appendChild(h);

    const rows = td.placements.map(p => `<tr>
      <td>${esc(p.client)}${p.nb ? ` <span class="gbp-tag">NB</span>` : ""}</td>
      <td class="role-cell">${esc(p.title)}</td>
      <td>${esc(p.owner)}</td>
      <td class="role-cell">${esc(p.type)}</td>
      <td class="num">${fmt(p.fee, td.sym) || td.sym + "0"}</td>
      <td class="role-cell">${esc(p.created)}</td>
    </tr>`).join("");
    container.appendChild(tableWrap(`<table>
      <thead><tr>
        <th>Client</th><th>Job Title</th><th>Owner</th><th>Type</th>
        <th class="num">Revenue</th><th>Created</th>
      </tr></thead>
      <tbody>${rows}</tbody></table>`));
  }
  return container;
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

function permRow(m) {
  return `<tr>
    <td>${esc(m.name)}</td>
    <td class="role-cell">${esc(m.role)}</td>
    <td class="num">${fmt(m.ytd, m.sym)}</td>
    <td class="num">${fmt(m.written, m.sym)}</td>
    <td class="num">${fmt(m.year_pred, m.sym)}</td>
    <td class="num">${fmt(m.roll12, m.sym)}</td>
    <td class="num">${fmt(m.roll12_uplift, m.sym)}${nbClientsHtml(m)}</td>
    <td class="num">${fmt(m.roll12_total, m.sym)}</td>
  </tr>`;
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
