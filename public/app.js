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

// ── Boot ─────────────────────────────────────────────────────────────────────

(async () => {
  // Check if current user is admin (for settings link)
  checkAdminLink();

  // Fetch report data
  let data;
  try {
    const resp = await fetch("/api/report-data");
    data = await resp.json();
  } catch (e) {
    showError("Could not reach the API. Please refresh.");
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
  </tr>`;
}

function buildPermTeamTable(groups) {
  let body = "";
  for (const g of groups) {
    body += `<tr class="team-header"><td colspan="6">${esc(g.team)}</td></tr>`;
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
    <th class="num">Total Contract Margin YTD</th>
    <th class="num">Year Billing (WNF×52)</th>
    <th class="num">Perm Last 12M</th>
    <th class="num">Contract Last 12M</th>
    <th class="num">Rolling 3M Contract</th>
    <th class="num">Current WNF</th>
  </tr></thead>`;
  const body = members.map(m => `<tr>
    <td>${esc(m.name)}</td>
    <td class="role-cell">${esc(m.role)}</td>
    <td class="num manual-cell" contenteditable="true" data-field="margin_ytd">—</td>
    <td class="num year-billing-cell">—</td>
    <td class="num manual-cell" contenteditable="true" data-field="perm_12">—</td>
    <td class="num manual-cell" contenteditable="true" data-field="contract_12">—</td>
    <td class="num manual-cell" contenteditable="true" data-field="rolling_3m">—</td>
    <td class="num wnf-cell" contenteditable="true" data-sym="${m.sym}" data-field="wnf">—</td>
  </tr>`).join("");

  const wrap = tableWrap(`<table class="contract-table">${headers}<tbody>${body}</tbody></table>`);

  // Wire up WNF → Year Billing
  wrap.querySelectorAll(".contract-table tbody tr").forEach(row => {
    const wnf = row.querySelector(".wnf-cell");
    const yb  = row.querySelector(".year-billing-cell");
    if (!wnf || !yb) return;
    const sym = wnf.dataset.sym || "£";
    wnf.addEventListener("input", () => {
      const v = parseFloat(wnf.textContent.replace(/[^0-9.]/g, ""));
      yb.textContent = !isNaN(v) && v > 0
        ? sym + (v * 52).toLocaleString("en-GB", { maximumFractionDigits: 0 })
        : "—";
    });
  });

  return wrap;
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
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function showError(msg) {
  document.getElementById("panels").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
  document.getElementById("data-note").textContent = "Error";
}
