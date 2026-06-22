/**
 * Saragossa Admin Analytics — admin.js
 * Monthly GP breakdown per consultant + territory vs budget summary.
 * Admin-only: API returns 403 for non-admins.
 */

const TERRITORY_ORDER = [
  "Bristol", "London", "Chicago", "New York",
  "London Contract", "Chicago Contract", "Cameron Scott",
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

  // 1. Territory summary
  container.appendChild(buildSummarySection());

  // 1b. Retained Business
  container.appendChild(buildRetainedSection());

  // 2. Monthly budget entry grid
  container.appendChild(buildBudgetSection());

  // 3. Monthly breakdown (tabbed per territory)
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
    <th class="num">Full Year Written</th>
    <th class="num">YoY %</th>
    <th class="num">Full Year Written Last YTD</th>
    <th class="num">Budget YTD</th>
    <th class="num">vs Budget</th>
    <th class="num">Last Year Full</th>
    <th class="num">Full Year YoY</th>
    <th class="num">Annual Budget</th>
  </tr></thead>`;

  const tbody = document.createElement("tbody");
  const territories = reportData.territories;

  for (const territory of TERRITORY_ORDER) {
    const tdata = territories[territory];
    if (!tdata) continue;

    const sym        = tdata.sym;
    const months     = tdata.territory_months;
    const budget     = tdata.budget || {};
    const budgetMths = budget.months || {};
    const annualBudget = budget.total || 0;

    // Written YTD (this year, by start date) — kept internally for vs-Budget
    let ytd = 0, ytdBudget = 0;
    for (let m = 1; m <= currentMonth; m++) {
      ytd        += months[String(m)]     || 0;
      ytdBudget  += budgetMths[String(m)] || 0;
    }

    const fullYear     = tdata.territory_total;
    const lastYearYtd  = tdata.territory_last_year_ytd || 0;
    const lastYear     = tdata.territory_last_year;
    const vsBudget     = ytdBudget > 0 ? ytd - ytdBudget : null;
    const ytdYoyPct    = lastYearYtd > 0 ? (fullYear - lastYearYtd) / lastYearYtd * 100 : null;
    const fullYoyPct   = lastYear > 0 ? (fullYear - lastYear) / lastYear * 100 : null;

    const vsCls      = vsBudget    !== null ? (vsBudget    >= 0 ? " pos" : " neg") : "";
    const ytdYoyCls  = ytdYoyPct   !== null ? (ytdYoyPct   >= 0 ? " pos" : " neg") : "";
    const fullYoyCls = fullYoyPct  !== null ? (fullYoyPct  >= 0 ? " pos" : " neg") : "";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${esc(territory)}</strong></td>
      <td class="num">${fmt(fullYear, sym)}</td>
      <td class="num${ytdYoyCls}">${ytdYoyPct !== null ? fmtPct(ytdYoyPct) : "—"}</td>
      <td class="num dim">${lastYearYtd > 0 ? fmt(lastYearYtd, sym) : "—"}</td>
      <td class="num">${ytdBudget > 0 ? fmt(ytdBudget, sym) : "—"}</td>
      <td class="num${vsCls}">${vsBudget !== null ? fmtDelta(vsBudget, sym) : "—"}</td>
      <td class="num dim">${lastYear > 0 ? fmt(lastYear, sym) : "—"}</td>
      <td class="num${fullYoyCls}">${fullYoyPct !== null ? fmtPct(fullYoyPct) : "—"}</td>
      <td class="num">${annualBudget > 0 ? fmt(annualBudget, sym) : "—"}</td>
    `;

    tbody.appendChild(tr);
  }

  // ── Other row (GBP) — placements not attributed to any territory consultant ──
  const otherData    = reportData.other || {};
  const oFullYear    = otherData.total_gbp         || 0;
  const oLastYear    = otherData.last_year_gbp     || 0;
  const oLastYearYtd = otherData.last_year_ytd_gbp || 0;

  const oYtdYoyPct  = oLastYearYtd > 0 ? (oFullYear - oLastYearYtd) / oLastYearYtd * 100 : null;
  const oYtdYoyCls  = oYtdYoyPct  !== null ? (oYtdYoyPct  >= 0 ? " pos" : " neg") : "";
  const oFullYoyPct = oLastYear > 0 ? (oFullYear - oLastYear) / oLastYear * 100 : null;
  const oFullYoyCls = oFullYoyPct !== null ? (oFullYoyPct >= 0 ? " pos" : " neg") : "";

  const otherTr = document.createElement("tr");
  otherTr.className = "territory-total-row other-row";
  otherTr.style.cursor = "pointer";
  otherTr.innerHTML = `
    <td><strong><span class="other-toggle-arrow">▶</span> Other (GBP)</strong></td>
    <td class="num"><strong>${fmt(oFullYear, "£") || "£0"}</strong></td>
    <td class="num${oYtdYoyCls}"><strong>${oYtdYoyPct !== null ? fmtPct(oYtdYoyPct) : "—"}</strong></td>
    <td class="num dim"><strong>${oLastYearYtd > 0 ? fmt(oLastYearYtd, "£") : "—"}</strong></td>
    <td class="num">—</td>
    <td class="num">—</td>
    <td class="num dim"><strong>${oLastYear > 0 ? fmt(oLastYear, "£") : "—"}</strong></td>
    <td class="num${oFullYoyCls}"><strong>${oFullYoyPct !== null ? fmtPct(oFullYoyPct) : "—"}</strong></td>
    <td class="num">—</td>
  `;
  tbody.appendChild(otherTr);

  // ── Overall row (GBP) — includes all territories + Other ──────────────────
  const gMonthly     = reportData.grand_monthly_gbp       || {};
  const gBudgetMths  = reportData.grand_budget_monthly_gbp || {};
  const gBudgetTotal = reportData.grand_budget_total_gbp  || 0;
  const gFullYear    = reportData.grand_total_gbp          || 0;
  const gLastYear    = reportData.grand_total_last_gbp     || 0;
  const gLastYearYtd = reportData.grand_total_last_ytd_gbp || 0;

  let gYtd = 0, gYtdBudget = 0;
  for (let m = 1; m <= currentMonth; m++) {
    gYtd       += gMonthly[String(m)]     || 0;
    gYtdBudget += gBudgetMths[String(m)]  || 0;
  }

  const gVsBudget   = gYtdBudget > 0 ? gYtd - gYtdBudget : null;
  const gYtdYoyPct  = gLastYearYtd > 0 ? (gFullYear - gLastYearYtd) / gLastYearYtd * 100 : null;
  const gFullYoyPct = gLastYear > 0  ? (gFullYear - gLastYear) / gLastYear * 100 : null;

  const gVsCls      = gVsBudget   !== null ? (gVsBudget   >= 0 ? " pos" : " neg") : "";
  const gYtdYoyCls  = gYtdYoyPct  !== null ? (gYtdYoyPct  >= 0 ? " pos" : " neg") : "";
  const gFullYoyCls = gFullYoyPct !== null ? (gFullYoyPct >= 0 ? " pos" : " neg") : "";

  const overallTr = document.createElement("tr");
  overallTr.className = "territory-total-row";
  overallTr.innerHTML = `
    <td><strong>Overall (GBP)</strong></td>
    <td class="num"><strong>${fmt(gFullYear, "£")}</strong></td>
    <td class="num${gYtdYoyCls}"><strong>${gYtdYoyPct !== null ? fmtPct(gYtdYoyPct) : "—"}</strong></td>
    <td class="num dim"><strong>${gLastYearYtd > 0 ? fmt(gLastYearYtd, "£") : "—"}</strong></td>
    <td class="num"><strong>${gYtdBudget > 0 ? fmt(gYtdBudget, "£") : "—"}</strong></td>
    <td class="num${gVsCls}"><strong>${gVsBudget !== null ? fmtDelta(gVsBudget, "£") : "—"}</strong></td>
    <td class="num dim"><strong>${gLastYear > 0 ? fmt(gLastYear, "£") : "—"}</strong></td>
    <td class="num${gFullYoyCls}"><strong>${gFullYoyPct !== null ? fmtPct(gFullYoyPct) : "—"}</strong></td>
    <td class="num"><strong>${gBudgetTotal > 0 ? fmt(gBudgetTotal, "£") : "—"}</strong></td>
  `;
  tbody.appendChild(overallTr);

  table.appendChild(tbody);
  wrap.appendChild(table);

  // ── Other drilldown panel (hidden by default) ──────────────────────────────
  const otherPlacements = otherData.placements || [];
  const drillWrap = document.createElement("div");
  drillWrap.id = "other-drilldown";
  drillWrap.className = "other-drilldown-wrap";
  drillWrap.style.display = "none";

  if (otherPlacements.length === 0) {
    drillWrap.innerHTML = `<p class="other-empty">No unattributed placements found.</p>`;
  } else {
    const dtable = document.createElement("table");
    dtable.className = "other-drilldown-table";
    dtable.innerHTML = `
      <thead><tr>
        <th>Start Date</th>
        <th>Job Title</th>
        <th>Client</th>
        <th class="num">Fee</th>
        <th>Ccy</th>
        <th class="num">GBP</th>
        <th>CRO</th>
        <th>Consultant</th>
        <th>Assignment Owner</th>
      </tr></thead>`;
    const dtbody = document.createElement("tbody");
    for (const p of otherPlacements) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="dim">${p.start_date || "—"}</td>
        <td>${esc(p.title || "—")}</td>
        <td>${esc(p.client || "—")}</td>
        <td class="num">${fmt(p.fee || 0, p.currency === "GBP" ? "£" : p.currency === "USD" ? "$" : "")}</td>
        <td class="dim">${esc(p.currency || "")}</td>
        <td class="num">${p.currency !== "GBP" ? fmt(p.fee_gbp || 0, "£") : "—"}</td>
        <td>${esc(p.cro || "—")}</td>
        <td>${esc(p.consultant || "—")}</td>
        <td>${esc(p.assignment_owner || "—")}</td>
      `;
      dtbody.appendChild(tr);
    }
    dtable.appendChild(dtbody);
    drillWrap.appendChild(dtable);
  }
  wrap.appendChild(drillWrap);

  // Toggle drilldown on Other row click
  otherTr.addEventListener("click", () => {
    const open = drillWrap.style.display !== "none";
    drillWrap.style.display = open ? "none" : "block";
    const arrow = otherTr.querySelector(".other-toggle-arrow");
    if (arrow) arrow.textContent = open ? "▶" : "▼";
  });

  section.appendChild(wrap);
  return section;
}

// ── Retained Business ─────────────────────────────────────────────────────────

function buildRetainedSection() {
  const section = document.createElement("div");
  section.className = "admin-section retained-section";

  const h = document.createElement("h2");
  h.className = "admin-section-title";
  h.textContent = "Retained Business";
  section.appendChild(h);

  const ret      = reportData.retained || {};
  const count    = ret.count      || 0;
  const total    = ret.total_gbp  || 0;
  const cLast    = ret.count_last || 0;
  const tLast    = ret.last_gbp   || 0;

  const countYoy = cLast > 0 ? ((count - cLast) / cLast * 100) : null;
  const valYoy   = tLast > 0 ? ((total - tLast) / tLast * 100) : null;
  const countYoyCls = countYoy !== null ? (countYoy >= 0 ? "pos" : "neg") : "dim";
  const valYoyCls   = valYoy   !== null ? (valYoy   >= 0 ? "pos" : "neg") : "dim";

  const cards = document.createElement("div");
  cards.className = "retained-cards";
  cards.innerHTML = `
    <div class="retained-card">
      <div class="retained-card-label">Retainers Sold (${currentYear})</div>
      <div class="retained-card-value">${count}</div>
      <div class="retained-card-sub dim">${cLast > 0 ? `${cLast} last year` : "—"}</div>
      <div class="retained-card-yoy ${countYoyCls}">${countYoy !== null ? fmtPct(countYoy) : "—"}</div>
    </div>
    <div class="retained-card">
      <div class="retained-card-label">Total Value (GBP, ${currentYear})</div>
      <div class="retained-card-value">${total > 0 ? fmt(total, "£") : "£0"}</div>
      <div class="retained-card-sub dim">${tLast > 0 ? fmt(tLast, "£") + " last year" : "—"}</div>
      <div class="retained-card-yoy ${valYoyCls}">${valYoy !== null ? fmtPct(valYoy) : "—"}</div>
    </div>
  `;
  section.appendChild(cards);
  return section;
}


// ── Monthly Budget Grid ───────────────────────────────────────────────────────

function buildBudgetSection() {
  const section = document.createElement("div");
  section.id = "budget-section";
  section.className = "admin-section";

  const h = document.createElement("h2");
  h.className = "admin-section-title";
  h.textContent = `${currentYear} Monthly Budgets`;
  section.appendChild(h);

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";

  const monthHeaders = MONTH_ABBR.map(m => `<th class="num">${m}</th>`).join("");
  const table = document.createElement("table");
  table.className = "monthly-table budget-grid-table";
  table.innerHTML = `<thead><tr>
    <th>Territory</th>
    ${monthHeaders}
    <th class="num">Annual Total</th>
    <th></th>
  </tr></thead>`;

  const tbody = document.createElement("tbody");

  for (const territory of TERRITORY_ORDER) {
    const tdata = reportData.territories[territory];
    if (!tdata) continue;

    const sym        = tdata.sym;
    const budgetMths = (tdata.budget && tdata.budget.months) || {};

    const tr = document.createElement("tr");
    tr.dataset.territory = territory;

    const monthCells = MONTH_ABBR.map((_, i) => {
      const m   = i + 1;
      const val = budgetMths[String(m)];
      return `<td><input type="number" class="budget-month-input contract-input"
               data-month="${m}" placeholder="0" step="1000"
               value="${val != null ? Math.round(val) : ""}"></td>`;
    }).join("");

    const annualTotal = Object.values(budgetMths).reduce((s, v) => s + (v || 0), 0);

    tr.innerHTML = `
      <td><strong>${esc(territory)}</strong></td>
      ${monthCells}
      <td class="num annual-total">${annualTotal > 0 ? fmt(annualTotal, sym) : "—"}</td>
      <td><button class="save-btn budget-row-save">Save</button></td>
    `;

    tr.querySelectorAll(".budget-month-input").forEach(inp => {
      inp.addEventListener("input", () => updateAnnualTotal(tr, sym));
    });

    tr.querySelector(".budget-row-save").addEventListener("click", async (e) => {
      await saveBudgetRow(territory, tr, e.currentTarget);
    });

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

function updateAnnualTotal(tr, sym) {
  let total = 0;
  tr.querySelectorAll(".budget-month-input").forEach(inp => {
    const v = parseFloat(inp.value);
    if (!isNaN(v)) total += v;
  });
  tr.querySelector(".annual-total").textContent = total > 0 ? fmt(total, sym) : "—";
}

async function saveBudgetRow(territory, tr, btn) {
  const months = {};
  tr.querySelectorAll(".budget-month-input").forEach(inp => {
    const v = inp.value.trim();
    if (v !== "") months[inp.dataset.month] = parseFloat(v);
  });

  btn.textContent = "Saving…";
  btn.disabled = true;

  try {
    const resp = await fetch("/api/analytics-budget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year: currentYear, territory, months }),
    });
    const data = await resp.json();
    if (data.ok) {
      const total = Object.values(months).reduce((s, v) => s + v, 0);
      reportData.territories[territory].budget = { months, total };
      // Re-render summary so YTD budget and vs-budget figures update
      document.getElementById("summary-section").replaceWith(buildSummarySection());
      btn.textContent = "Saved ✓";
      setTimeout(() => { btn.textContent = "Save"; btn.disabled = false; }, 2000);
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

function round2(n) { return Math.round(n * 100) / 100; }


// ── Monthly Breakdown Tabs ────────────────────────────────────────────────────

function buildBreakdownTabs() {
  const wrapper = document.createElement("div");

  // Year toggle
  let showLastYear = false;
  const toggleBar = document.createElement("div");
  toggleBar.className = "breakdown-toggle";
  toggleBar.innerHTML = `
    <button class="year-toggle-btn active" data-year="this">${currentYear}</button>
    <button class="year-toggle-btn" data-year="last">${currentYear - 1}</button>
  `;
  wrapper.appendChild(toggleBar);

  const tabsEl  = document.createElement("nav");
  tabsEl.className = "tabs";

  const panelsEl = document.createElement("div");
  panelsEl.className = "panels";

  // ── Overall tab (first, active by default) ────────────────────────────────
  const overallTab = document.createElement("div");
  overallTab.className = "tab active";
  overallTab.textContent = "Overall";
  overallTab.dataset.panel = "admin-panel-overall";
  tabsEl.appendChild(overallTab);

  const overallPanel = document.createElement("div");
  overallPanel.className = "panel active";
  overallPanel.id = "admin-panel-overall";
  overallPanel.dataset.territory = "__overall__";
  overallPanel.appendChild(buildOverallTable(false));
  panelsEl.appendChild(overallPanel);

  // ── Per-territory tabs ────────────────────────────────────────────────────
  for (const territory of TERRITORY_ORDER) {
    const tdata = reportData.territories[territory];
    if (!tdata) continue;

    const panelId = "admin-panel-" + territory.replace(/\s+/g, "-").replace(/&/g, "and");

    const tab = document.createElement("div");
    tab.className = "tab";
    tab.textContent = territory;
    tab.dataset.panel = panelId;
    tabsEl.appendChild(tab);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.id = panelId;
    panel.dataset.territory = territory;
    panel.appendChild(buildMonthlyTable(tdata, false));
    panelsEl.appendChild(panel);
  }

  tabsEl.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      tabsEl.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      panelsEl.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(tab.dataset.panel).classList.add("active");
    });
  });

  // Year toggle handler — re-render all panels
  toggleBar.querySelectorAll(".year-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      showLastYear = btn.dataset.year === "last";
      toggleBar.querySelectorAll(".year-toggle-btn").forEach(b =>
        b.classList.toggle("active", b === btn)
      );
      panelsEl.querySelectorAll(".panel").forEach(panel => {
        if (panel.dataset.territory === "__overall__") {
          panel.innerHTML = "";
          panel.appendChild(buildOverallTable(showLastYear));
        } else {
          const tdata = reportData.territories[panel.dataset.territory];
          if (!tdata) return;
          panel.innerHTML = "";
          panel.appendChild(buildMonthlyTable(tdata, showLastYear));
        }
      });
    });
  });

  wrapper.appendChild(tabsEl);
  wrapper.appendChild(panelsEl);
  return wrapper;
}


// ── Overall Table (all territories combined) ──────────────────────────────────

function buildOverallTable(showLastYear = false) {
  const compareLabel = showLastYear ? `${currentYear}` : `${currentYear - 1}`;
  const yoyLabel     = showLastYear ? "vs This Year" : "YoY";

  // ── Summary totals bar ────────────────────────────────────────────────────
  const GBP_TERRITORIES = ["Bristol", "London", "London Contract"];
  const USD_TERRITORIES = ["Chicago", "New York", "Chicago Contract"];

  function sumTerritories(terrs) {
    let total = 0, compare = 0;
    for (const t of terrs) {
      const td = reportData.territories[t];
      if (!td) continue;
      total   += showLastYear ? td.territory_last_year  : td.territory_total;
      compare += showLastYear ? td.territory_total       : td.territory_last_year;
    }
    return { total, compare };
  }

  const gbp = sumTerritories(GBP_TERRITORIES);
  const usd = sumTerritories(USD_TERRITORIES);

  function summaryBlock(label, sym, { total, compare }) {
    const yoy    = compare > 0 ? (total - compare) / compare * 100 : null;
    const yoyCls = yoy !== null ? (yoy >= 0 ? "pos" : "neg") : "dim";
    const yoyStr = yoy !== null ? fmtPct(yoy) : "—";
    return `
      <div class="overall-summary-block">
        <span class="overall-summary-label">${label}</span>
        <span class="overall-summary-total">${fmt(total, sym)}</span>
        <span class="overall-summary-cmp dim">${compare > 0 ? fmt(compare, sym) : "—"}</span>
        <span class="overall-summary-yoy ${yoyCls}">${yoyStr}</span>
      </div>`;
  }

  const grandTotal  = showLastYear ? reportData.grand_total_last_gbp  : reportData.grand_total_gbp;
  const grandCompare = showLastYear ? reportData.grand_total_gbp       : reportData.grand_total_last_gbp;

  const summaryBar = document.createElement("div");
  summaryBar.className = "overall-summary-bar";
  summaryBar.innerHTML =
    summaryBlock("Total (GBP)", "£", { total: grandTotal, compare: grandCompare }) +
    `<div class="overall-summary-divider"></div>` +
    summaryBlock("GBP Territories", "£", gbp) +
    `<div class="overall-summary-divider"></div>` +
    summaryBlock("USD Territories", "$", usd);

  // ── Main table ────────────────────────────────────────────────────────────
  const monthHeaders = MONTH_ABBR.map(m => `<th class="num">${m}</th>`).join("");

  const colCount = 2 + 12 + 5;

  // Build overall member lookup for click handlers
  const overallMemberLookup = {};
  for (const territory of TERRITORY_ORDER) {
    const td2 = reportData.territories[territory];
    if (!td2) continue;
    const mbs = td2.type === "teams" ? td2.groups.flatMap(g => g.members) : (td2.members || []);
    for (const m of mbs) overallMemberLookup[m.uid] = { member: m, sym: td2.sym };
  }

  let html = `<table class="monthly-table">
    <thead>
      <tr>
        <th>Consultant</th>
        <th>Role</th>
        ${monthHeaders}
        <th class="num">Total</th>
        <th class="num">vs Target</th>
        <th class="num">% Target</th>
        <th class="num">${esc(compareLabel)}</th>
        <th class="num">${esc(yoyLabel)}</th>
      </tr>
    </thead>
    <tbody>`;

  for (const territory of TERRITORY_ORDER) {
    const tdata = reportData.territories[territory];
    if (!tdata) continue;

    // Flatten all members regardless of team grouping
    const members = tdata.type === "teams"
      ? tdata.groups.flatMap(g => g.members)
      : (tdata.members || []);

    if (!members.length) continue;

    const sym           = tdata.sym;
    const territoryMths = showLastYear ? tdata.territory_last_year_months : tdata.territory_months;
    const territoryTot  = showLastYear ? tdata.territory_last_year        : tdata.territory_total;
    const territoryCmp  = showLastYear ? tdata.territory_total            : tdata.territory_last_year;

    // Territory header row
    html += `<tr class="team-header"><td colspan="${colCount}">${esc(territory)}</td></tr>`;

    for (const m of members) {
      const mMonths = showLastYear ? (m.last_year_months || {}) : m.months;
      const mTotal  = showLastYear ? m.last_year_total : m.total;
      const mCmp    = showLastYear ? m.total : m.last_year_total;
      const mSym    = m.sym || sym;

      const monthCells = MONTH_ABBR.map((_, i) => {
        const v = mMonths[String(i + 1)] || 0;
        if (v > 0) {
          return `<td class="num clickable-cell" data-uid="${m.uid}" data-month="${i+1}" data-lastyear="${showLastYear?1:0}">${fmt(v, mSym)}</td>`;
        }
        return `<td class="num"></td>`;
      }).join("");

      const yoy    = mCmp > 0 ? (mTotal - mCmp) / mCmp * 100 : null;
      const yoyCls = yoy !== null ? (yoy >= 0 ? " pos" : " neg") : "";

      const target    = m.target != null ? m.target : null;
      const vsTgt     = target != null ? mTotal - target : null;
      const tgtPct    = target != null && target > 0 ? (mTotal - target) / target * 100 : null;
      const vsTgtCls  = vsTgt  !== null ? (vsTgt  >= 0 ? " pos" : " neg") : "";
      const tgtPctCls = tgtPct !== null ? (tgtPct >= 0 ? " pos" : " neg") : "";

      const inactiveCls = m.active === false ? " inactive-consultant" : "";
      const badgeText   = m.note ? m.note : (m.active === false ? "left" : null);
      const nameCell    = badgeText
        ? `${esc(m.name)} <span class="inactive-badge">${esc(badgeText)}</span>`
        : esc(m.name);

      html += `<tr class="${inactiveCls}">
        <td>${nameCell}</td>
        <td class="role-cell">${esc(m.role)}</td>
        ${monthCells}
        <td class="num"><strong>${mTotal > 0 ? fmt(mTotal, mSym) : ""}</strong></td>
        <td class="num${vsTgtCls}">${vsTgt !== null ? fmtDelta(vsTgt, mSym) : "—"}</td>
        <td class="num${tgtPctCls}">${tgtPct !== null ? fmtPct(tgtPct) : "—"}</td>
        <td class="num dim">${mCmp > 0 ? fmt(mCmp, mSym) : "—"}</td>
        <td class="num${yoyCls}">${yoy !== null ? fmtPct(yoy) : "—"}</td>
      </tr>`;
    }

    // Territory subtotal row — sum targets across members
    const tgtSum     = members.some(m => m.target != null)
      ? members.reduce((s, m) => s + (m.target != null ? m.target : 0), 0)
      : null;
    const tVsTgt     = tgtSum != null ? territoryTot - tgtSum : null;
    const tTgtPct    = tgtSum != null && tgtSum > 0 ? (territoryTot - tgtSum) / tgtSum * 100 : null;
    const tVsTgtCls  = tVsTgt  !== null ? (tVsTgt  >= 0 ? " pos" : " neg") : "";
    const tTgtPctCls = tTgtPct !== null ? (tTgtPct >= 0 ? " pos" : " neg") : "";

    const subtotalCells = MONTH_ABBR.map((_, i) => {
      const v = (territoryMths || {})[String(i + 1)] || 0;
      return `<td class="num"><strong>${v > 0 ? fmt(v, sym) : ""}</strong></td>`;
    }).join("");

    const tYoy    = territoryCmp > 0 ? (territoryTot - territoryCmp) / territoryCmp * 100 : null;
    const tYoyCls = tYoy !== null ? (tYoy >= 0 ? " pos" : " neg") : "";

    html += `<tr class="territory-total-row">
      <td colspan="2"><strong>${esc(territory)} Total</strong></td>
      ${subtotalCells}
      <td class="num"><strong>${fmt(territoryTot, sym)}</strong></td>
      <td class="num${tVsTgtCls}"><strong>${tVsTgt !== null ? fmtDelta(tVsTgt, sym) : "—"}</strong></td>
      <td class="num${tTgtPctCls}"><strong>${tTgtPct !== null ? fmtPct(tTgtPct) : "—"}</strong></td>
      <td class="num dim"><strong>${territoryCmp > 0 ? fmt(territoryCmp, sym) : "—"}</strong></td>
      <td class="num${tYoyCls}"><strong>${tYoy !== null ? fmtPct(tYoy) : "—"}</strong></td>
    </tr>`;
  }

  // GBP grand total footer
  const grandMonthly    = showLastYear ? reportData.grand_monthly_last_gbp : reportData.grand_monthly_gbp;
  const grandMonthlyCmp = showLastYear ? reportData.grand_monthly_gbp      : reportData.grand_monthly_last_gbp;
  const grandTotFull    = showLastYear ? reportData.grand_total_last_gbp   : reportData.grand_total_gbp;
  const grandCmpFull    = showLastYear ? reportData.grand_total_gbp        : reportData.grand_total_last_gbp;

  const grandCells = MONTH_ABBR.map((_, i) => {
    const v = (grandMonthly || {})[String(i + 1)] || 0;
    return `<td class="num"><strong>${v > 0 ? fmt(v, "£") : ""}</strong></td>`;
  }).join("");

  const grandYoy    = grandCmpFull > 0 ? (grandTotFull - grandCmpFull) / grandCmpFull * 100 : null;
  const grandYoyCls = grandYoy !== null ? (grandYoy >= 0 ? " pos" : " neg") : "";

  html += `</tbody>
    <tfoot>
      <tr class="territory-total-row grand-total-row">
        <td colspan="2"><strong>Grand Total (GBP)</strong></td>
        ${grandCells}
        <td class="num"><strong>${fmt(grandTotFull, "£")}</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num dim"><strong>${grandCmpFull > 0 ? fmt(grandCmpFull, "£") : "—"}</strong></td>
        <td class="num${grandYoyCls}"><strong>${grandYoy !== null ? fmtPct(grandYoy) : "—"}</strong></td>
      </tr>
    </tfoot>
  </table>`;

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.innerHTML = html;

  // Attach click handlers for the overall table
  wrap.querySelectorAll(".clickable-cell").forEach(td => {
    td.addEventListener("click", () => {
      const uid    = td.dataset.uid;
      const month  = parseInt(td.dataset.month);
      const isLast = td.dataset.lastyear === "1";
      const entry  = overallMemberLookup[uid];
      if (!entry) return;
      const { member, sym: tSym } = entry;
      const pls = ((isLast ? member.last_placements : member.placements) || [])
        .filter(p => p.month === month);
      showPlacementModal(member.name, month, isLast ? currentYear - 1 : currentYear, pls, member.sym || tSym);
    });
  });

  const container = document.createElement("div");
  container.appendChild(summaryBar);
  container.appendChild(wrap);
  return container;
}


// ── Monthly Table ─────────────────────────────────────────────────────────────

function buildMonthlyTable(tdata, showLastYear = false) {
  const sym    = tdata.sym;
  const groups = tdata.type === "teams"
    ? tdata.groups
    : [{ team: null, members: tdata.members }];

  // Which year's data to show as primary
  const primaryMonths   = m => showLastYear ? (m.last_year_months || {}) : m.months;
  const primaryTotal    = m => showLastYear ? m.last_year_total : m.total;
  const compareTotal    = m => showLastYear ? m.total : m.last_year_total;
  const territoryMonths = showLastYear ? tdata.territory_last_year_months : tdata.territory_months;

  // Build uid → member lookup for click handlers (scoped to this table render)
  const memberLookup = {};
  for (const g of groups) {
    for (const m of g.members) memberLookup[m.uid] = m;
  }
  const territoryTotal  = showLastYear ? tdata.territory_last_year : tdata.territory_total;
  const territoryCompare = showLastYear ? tdata.territory_total : tdata.territory_last_year;
  const compareLabel    = showLastYear ? `${currentYear}` : `${currentYear - 1}`;
  const yoyLabel        = showLastYear ? "vs This Year" : "YoY";

  const monthHeaders = MONTH_ABBR.map(m => `<th class="num">${m}</th>`).join("");

  const colCount = 2 + 12 + 5;

  let html = `<table class="monthly-table">
    <thead>
      <tr>
        <th>Consultant</th>
        <th>Role</th>
        ${monthHeaders}
        <th class="num">Total</th>
        <th class="num">vs Target</th>
        <th class="num">% Target</th>
        <th class="num">${esc(compareLabel)}</th>
        <th class="num">${esc(yoyLabel)}</th>
      </tr>
    </thead>
    <tbody>`;

  for (const g of groups) {
    if (g.team) {
      html += `<tr class="team-header"><td colspan="${colCount}">${esc(g.team)}</td></tr>`;
    }
    for (const m of g.members) {
      const mMonths = primaryMonths(m);
      const mTotal  = primaryTotal(m);
      const mCmp    = compareTotal(m);
      const mSym    = m.sym || sym;

      const monthCells = MONTH_ABBR.map((_, i) => {
        const v = mMonths[String(i + 1)] || 0;
        if (v > 0) {
          return `<td class="num clickable-cell" data-uid="${m.uid}" data-month="${i+1}" data-lastyear="${showLastYear?1:0}">${fmt(v, mSym)}</td>`;
        }
        return `<td class="num"></td>`;
      }).join("");

      const yoy    = mCmp > 0 ? (mTotal - mCmp) / mCmp * 100 : null;
      const yoyCls = yoy !== null ? (yoy >= 0 ? " pos" : " neg") : "";

      const target    = m.target != null ? m.target : null;
      const vsTgt     = target != null ? mTotal - target : null;
      const tgtPct    = target != null && target > 0 ? (mTotal - target) / target * 100 : null;
      const vsTgtCls  = vsTgt  !== null ? (vsTgt  >= 0 ? " pos" : " neg") : "";
      const tgtPctCls = tgtPct !== null ? (tgtPct >= 0 ? " pos" : " neg") : "";

      const inactiveCls = m.active === false ? " inactive-consultant" : "";
      const badgeText   = m.note ? m.note : (m.active === false ? "left" : null);
      const nameCell    = badgeText
        ? `${esc(m.name)} <span class="inactive-badge">${esc(badgeText)}</span>`
        : esc(m.name);

      html += `<tr class="${inactiveCls}">
        <td>${nameCell}</td>
        <td class="role-cell">${esc(m.role)}</td>
        ${monthCells}
        <td class="num"><strong>${mTotal > 0 ? fmt(mTotal, mSym) : ""}</strong></td>
        <td class="num${vsTgtCls}">${vsTgt !== null ? fmtDelta(vsTgt, mSym) : "—"}</td>
        <td class="num${tgtPctCls}">${tgtPct !== null ? fmtPct(tgtPct) : "—"}</td>
        <td class="num dim">${mCmp > 0 ? fmt(mCmp, mSym) : "—"}</td>
        <td class="num${yoyCls}">${yoy !== null ? fmtPct(yoy) : "—"}</td>
      </tr>`;
    }
  }

  // Territory total footer — sum targets across all members for territory-level vs target
  const allMembers  = groups.flatMap(g => g.members);
  const tgtSum      = allMembers.some(m => m.target != null)
    ? allMembers.reduce((s, m) => s + (m.target != null ? m.target : 0), 0)
    : null;
  const tVsTgt      = tgtSum != null ? territoryTotal - tgtSum : null;
  const tTgtPct     = tgtSum != null && tgtSum > 0 ? (territoryTotal - tgtSum) / tgtSum * 100 : null;
  const tVsTgtCls   = tVsTgt  !== null ? (tVsTgt  >= 0 ? " pos" : " neg") : "";
  const tTgtPctCls  = tTgtPct !== null ? (tTgtPct >= 0 ? " pos" : " neg") : "";

  const totalCells = MONTH_ABBR.map((_, i) => {
    const v = (territoryMonths || {})[String(i + 1)] || 0;
    return `<td class="num"><strong>${v > 0 ? fmt(v, sym) : ""}</strong></td>`;
  }).join("");

  const tYoy    = territoryCompare > 0
    ? (territoryTotal - territoryCompare) / territoryCompare * 100
    : null;
  const tYoyCls = tYoy !== null ? (tYoy >= 0 ? " pos" : " neg") : "";

  html += `</tbody>
    <tfoot>
      <tr class="territory-total-row">
        <td colspan="2"><strong>Territory Total</strong></td>
        ${totalCells}
        <td class="num"><strong>${fmt(territoryTotal, sym)}</strong></td>
        <td class="num${tVsTgtCls}"><strong>${tVsTgt !== null ? fmtDelta(tVsTgt, sym) : "—"}</strong></td>
        <td class="num${tTgtPctCls}"><strong>${tTgtPct !== null ? fmtPct(tTgtPct) : "—"}</strong></td>
        <td class="num dim"><strong>${territoryCompare > 0 ? fmt(territoryCompare, sym) : "—"}</strong></td>
        <td class="num${tYoyCls}"><strong>${tYoy !== null ? fmtPct(tYoy) : "—"}</strong></td>
      </tr>
    </tfoot>
  </table>`;

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.innerHTML = html;

  // Attach click handlers to non-zero month cells
  wrap.querySelectorAll(".clickable-cell").forEach(td => {
    td.addEventListener("click", () => {
      const uid      = td.dataset.uid;
      const month    = parseInt(td.dataset.month);
      const isLast   = td.dataset.lastyear === "1";
      const member   = memberLookup[uid];
      if (!member) return;
      const pls = ((isLast ? member.last_placements : member.placements) || [])
        .filter(p => p.month === month);
      showPlacementModal(member.name, month, isLast ? currentYear - 1 : currentYear, pls, member.sym || sym);
    });
  });

  return wrap;
}


// ── Placement drilldown modal ─────────────────────────────────────────────────

function showPlacementModal(consultantName, month, year, placements, sym) {
  // Create modal DOM once and reuse
  let modal = document.getElementById("placement-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "placement-modal";
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-box">
        <div class="modal-header">
          <span class="modal-title" id="modal-title"></span>
          <button class="modal-close" id="modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body" id="modal-body"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener("click", e => { if (e.target === modal) modal.style.display = "none"; });
    document.getElementById("modal-close").addEventListener("click", () => { modal.style.display = "none"; });
    document.addEventListener("keydown", e => { if (e.key === "Escape") modal.style.display = "none"; });
  }

  document.getElementById("modal-title").textContent =
    `${consultantName} — ${MONTH_ABBR[month - 1]} ${year}`;

  const body = document.getElementById("modal-body");

  if (!placements.length) {
    body.innerHTML = `<p class="modal-empty">No placements found for this month.</p>`;
  } else {
    let html = `<table class="modal-table">
      <thead><tr>
        <th>Job Title</th>
        <th>Client</th>
        <th class="num">Your Share</th>
        <th class="num">Full Fee</th>
        <th class="num">Share</th>
        <th>Start Date</th>
      </tr></thead><tbody>`;
    for (const p of placements) {
      const sharePct = p.full_fee > 0 ? Math.round(p.own_fee / p.full_fee * 100) : 0;
      const origNote = p.currency !== (sym === "£" ? "GBP" : "USD")
        ? ` <span class="dim">${p.currency}</span>` : "";
      html += `<tr>
        <td>${esc(p.title || "—")}</td>
        <td>${esc(p.client || "—")}</td>
        <td class="num"><strong>${fmt(p.own_fee, sym) || (sym + "0")}</strong></td>
        <td class="num dim">${fmt(p.full_fee, sym) || (sym + "0")}${origNote}</td>
        <td class="num dim">${sharePct}%</td>
        <td class="dim">${p.start_date || "—"}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    body.innerHTML = html;
  }

  modal.style.display = "flex";
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
