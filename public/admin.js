/**
 * Saragossa Admin Analytics — admin.js
 * Monthly GP breakdown per consultant + territory vs budget summary.
 * Admin-only: API returns 403 for non-admins.
 */

const TERRITORY_ORDER = [
  "Bristol", "London", "Chicago", "New York",
  "London Contract", "Chicago Contract",
];

const MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

let reportData  = null;
let currentYear = new Date().getFullYear();
let currentMonth = new Date().getMonth() + 1; // 1-indexed

// ── Boot ──────────────────────────────────────────────────────────────────────

(async () => {
  let resp, text, data;
  try {
    resp = await fetch("/api/analytics-report");
    if (resp.status === 401) {
      window.location.href = "/.auth/login/aad?post_login_redirect_uri=" + encodeURIComponent(window.location.pathname);
      return;
    }
    if (resp.status === 403) {
      document.getElementById("content").innerHTML =
        '<div class="error-state"><p>⚠ Admin access required.</p></div>';
      return;
    }
    text = await resp.text();
    try {
      data = JSON.parse(text);
    } catch (_) {
      document.getElementById("content").innerHTML =
        `<div class="error-state"><p>⚠ API returned non-JSON (HTTP ${resp.status}): ${esc(text.slice(0, 400))}</p></div>`;
      return;
    }
    if (!data.ok) {
      document.getElementById("content").innerHTML =
        `<div class="error-state"><p>⚠ ${esc(data.error || "Unknown error from API")}</p></div>`;
      return;
    }
    reportData   = data;
    currentYear  = data.year;
    render();
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="error-state"><p>⚠ Could not reach API: ${esc(e.message)}</p></div>`;
  }
})();


// ── Render ────────────────────────────────────────────────────────────────────

function render() {
  const container = document.getElementById("content");
  container.innerHTML = "";

  const heading = document.createElement("div");
  heading.className = "admin-page-header";
  heading.innerHTML = `<h1>${currentYear} Performance Analytics</h1>
    <p class="settings-desc">Monthly perm GP by consultant · admin only</p>`;
  container.appendChild(heading);

  // 1. Territory summary + budget
  container.appendChild(buildSummarySection());

  // 2. Monthly breakdown (tabbed per territory)
  const breakdownHeading = document.createElement("h2");
  breakdownHeading.className = "admin-section-title";
  breakdownHeading.textContent = "Monthly Breakdown";
  container.appendChild(breakdownHeading);

  container.appendChild(buildBreakdownTabs());
}


// ── Territory Summary ─────────────────────────────────────────────────────────

function buildSummarySection() {
  const section = document.createElement("div");
  section.id = "summary-section";
  section.className = "admin-section";

  const h = document.createElement("h2");
  h.className = "admin-section-title";
  h.textContent = "Territory Summary";
  section.appendChild(h);

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";

  const table = document.createElement("table");
  table.innerHTML = `<thead><tr>
    <th>Territory</th>
    <th class="num">Written YTD</th>
    <th class="num">Last Year YTD</th>
    <th class="num">YTD YoY</th>
    <th class="num">YTD Budget</th>
    <th class="num">vs Budget</th>
    <th class="num">Full Year Written</th>
    <th class="num">Last Year Full</th>
    <th class="num">Full Year YoY</th>
    <th class="num">Annual Budget</th>
    <th>Set Budget</th>
  </tr></thead>`;

  const tbody = document.createElement("tbody");
  const territories = reportData.territories;

  for (const territory of TERRITORY_ORDER) {
    const tdata = territories[territory];
    if (!tdata) continue;

    const sym          = tdata.sym;
    const months       = tdata.territory_months;
    const lastMonths   = tdata.territory_last_year_months || {};
    const annualBudget = (tdata.budget && tdata.budget.amount) || 0;

    // YTD = months 1..currentMonth for this year and last year
    let ytd = 0, lastYtd = 0;
    for (let m = 1; m <= currentMonth; m++) {
      ytd     += months[String(m)]     || 0;
      lastYtd += lastMonths[String(m)] || 0;
    }

    const fullYear     = tdata.territory_total;
    const lastYear     = tdata.territory_last_year;
    const ytdBudget    = annualBudget > 0 ? annualBudget * (currentMonth / 12) : 0;
    const vsBudget     = ytdBudget > 0 ? ytd - ytdBudget : null;
    const ytdYoyPct    = lastYtd   > 0 ? (ytd      - lastYtd)  / lastYtd  * 100 : null;
    const fullYoyPct   = lastYear  > 0 ? (fullYear  - lastYear) / lastYear * 100 : null;

    const vsCls        = vsBudget    !== null ? (vsBudget    >= 0 ? " pos" : " neg") : "";
    const ytdYoyCls    = ytdYoyPct   !== null ? (ytdYoyPct   >= 0 ? " pos" : " neg") : "";
    const fullYoyCls   = fullYoyPct  !== null ? (fullYoyPct  >= 0 ? " pos" : " neg") : "";

    const tr = document.createElement("tr");
    tr.dataset.territory = territory;
    tr.innerHTML = `
      <td><strong>${esc(territory)}</strong></td>
      <td class="num">${fmt(ytd, sym)}</td>
      <td class="num dim">${lastYtd > 0 ? fmt(lastYtd, sym) : "—"}</td>
      <td class="num${ytdYoyCls}">${ytdYoyPct !== null ? fmtPct(ytdYoyPct) : "—"}</td>
      <td class="num">${ytdBudget > 0 ? fmt(ytdBudget, sym) : "—"}</td>
      <td class="num${vsCls}">${vsBudget !== null ? fmtDelta(vsBudget, sym) : "—"}</td>
      <td class="num">${fmt(fullYear, sym)}</td>
      <td class="num dim">${lastYear > 0 ? fmt(lastYear, sym) : "—"}</td>
      <td class="num${fullYoyCls}">${fullYoyPct !== null ? fmtPct(fullYoyPct) : "—"}</td>
      <td class="num">${annualBudget > 0 ? fmt(annualBudget, sym) : "—"}</td>
      <td class="budget-edit-cell">
        <input type="number" class="contract-input budget-input"
               placeholder="Annual target"
               value="${annualBudget > 0 ? Math.round(annualBudget) : ""}">
        <button class="save-btn budget-save-btn">Save</button>
      </td>
    `;

    tr.querySelector(".budget-save-btn").addEventListener("click", async (e) => {
      const input  = tr.querySelector(".budget-input");
      const val    = parseFloat(input.value);
      if (isNaN(val)) return;
      await saveBudget(territory, val, e.currentTarget);
    });

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

async function saveBudget(territory, amount, btn) {
  btn.textContent = "Saving…";
  btn.disabled = true;
  try {
    const resp = await fetch("/api/analytics-budget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year: currentYear, territory, amount }),

    });
    const data = await resp.json();
    if (data.ok) {
      // Update in-memory data and re-render summary
      reportData.territories[territory].budget = {
        amount: data.budget.amount ?? amount,
        id:     data.budget.id,
      };
      // Replace summary section in-place
      const old = document.getElementById("summary-section");
      old.replaceWith(buildSummarySection());
    } else {
      alert("Save failed: " + data.error);
      btn.textContent = "Save";
      btn.disabled = false;
    }
  } catch (e) {
    alert("Network error");
    btn.textContent = "Save";
    btn.disabled = false;
  }
}


// ── Monthly Breakdown Tabs ────────────────────────────────────────────────────

function buildBreakdownTabs() {
  const wrapper = document.createElement("div");

  const tabsEl  = document.createElement("nav");
  tabsEl.className = "tabs";

  const panelsEl = document.createElement("div");
  panelsEl.className = "panels";

  let first = true;
  for (const territory of TERRITORY_ORDER) {
    const tdata = reportData.territories[territory];
    if (!tdata) continue;

    const panelId = "admin-panel-" + territory.replace(/\s+/g, "-").replace(/&/g, "and");

    const tab = document.createElement("div");
    tab.className = "tab" + (first ? " active" : "");
    tab.textContent = territory;
    tab.dataset.panel = panelId;
    tabsEl.appendChild(tab);

    const panel = document.createElement("div");
    panel.className = "panel" + (first ? " active" : "");
    panel.id = panelId;
    panel.appendChild(buildMonthlyTable(tdata));
    panelsEl.appendChild(panel);

    first = false;
  }

  tabsEl.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      tabsEl.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      panelsEl.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(tab.dataset.panel).classList.add("active");
    });
  });

  wrapper.appendChild(tabsEl);
  wrapper.appendChild(panelsEl);
  return wrapper;
}


// ── Monthly Table ─────────────────────────────────────────────────────────────

function buildMonthlyTable(tdata) {
  const sym    = tdata.sym;
  const groups = tdata.type === "teams"
    ? tdata.groups
    : [{ team: null, members: tdata.members }];

  // Header row
  const monthHeaders = MONTH_ABBR.map((m, i) =>
    `<th class="num${i + 1 > currentMonth ? " future-col" : ""}">${m}</th>`
  ).join("");

  const colCount = 2 + 12 + 3; // name+role + 12 months + total+last+yoy

  let html = `<table class="monthly-table">
    <thead>
      <tr>
        <th>Consultant</th>
        <th>Role</th>
        ${monthHeaders}
        <th class="num">Total</th>
        <th class="num">Last Year</th>
        <th class="num">YoY</th>
      </tr>
    </thead>
    <tbody>`;

  for (const g of groups) {
    if (g.team) {
      html += `<tr class="team-header"><td colspan="${colCount}">${esc(g.team)}</td></tr>`;
    }
    for (const m of g.members) {
      const monthCells = MONTH_ABBR.map((_, i) => {
        const v   = m.months[String(i + 1)] || 0;
        const cls = i + 1 > currentMonth ? " future-col" : "";
        return `<td class="num${cls}">${v > 0 ? fmt(v, sym) : ""}</td>`;
      }).join("");

      const yoy    = m.last_year_total > 0
        ? (m.total - m.last_year_total) / m.last_year_total * 100
        : null;
      const yoyCls = yoy !== null ? (yoy >= 0 ? " pos" : " neg") : "";

      html += `<tr>
        <td>${esc(m.name)}</td>
        <td class="role-cell">${esc(m.role)}</td>
        ${monthCells}
        <td class="num"><strong>${m.total > 0 ? fmt(m.total, sym) : ""}</strong></td>
        <td class="num dim">${m.last_year_total > 0 ? fmt(m.last_year_total, sym) : "—"}</td>
        <td class="num${yoyCls}">${yoy !== null ? fmtPct(yoy) : "—"}</td>
      </tr>`;
    }
  }

  // Territory total footer
  const tm = tdata.territory_months;
  const totalCells = MONTH_ABBR.map((_, i) => {
    const v   = tm[String(i + 1)] || 0;
    const cls = i + 1 > currentMonth ? " future-col" : "";
    return `<td class="num${cls}"><strong>${v > 0 ? fmt(v, sym) : ""}</strong></td>`;
  }).join("");

  const tYoy    = tdata.territory_last_year > 0
    ? (tdata.territory_total - tdata.territory_last_year) / tdata.territory_last_year * 100
    : null;
  const tYoyCls = tYoy !== null ? (tYoy >= 0 ? " pos" : " neg") : "";

  html += `</tbody>
    <tfoot>
      <tr class="territory-total-row">
        <td colspan="2"><strong>Territory Total</strong></td>
        ${totalCells}
        <td class="num"><strong>${fmt(tdata.territory_total, sym)}</strong></td>
        <td class="num dim"><strong>${tdata.territory_last_year > 0 ? fmt(tdata.territory_last_year, sym) : "—"}</strong></td>
        <td class="num${tYoyCls}"><strong>${tYoy !== null ? fmtPct(tYoy) : "—"}</strong></td>
      </tr>
    </tfoot>
  </table>`;

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.innerHTML = html;
  return wrap;
}


// ── Utilities ─────────────────────────────────────────────────────────────────

function fmt(n, sym) {
  if (!n || n === 0) return "";
  return sym + Math.round(n).toLocaleString("en-GB");
}

function fmtDelta(n, sym) {
  if (n === 0) return "—";
  const sign = n > 0 ? "+" : "−";
  return sign + sym + Math.round(Math.abs(n)).toLocaleString("en-GB");
}

function fmtPct(pct) {
  const sign = pct >= 0 ? "+" : "";
  return sign + pct.toFixed(1) + "%";
}

function esc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
