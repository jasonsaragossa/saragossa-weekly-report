/**
 * Performance Stats (pilot) — contract desk dashboard.
 *
 * Week-over-week movement on the live-book metrics, a 12-month trend, and this
 * week's activity. All figures are USD for the Chicago Contract desk.
 */

(async () => {
  try {
    const info = await (await fetch("/.auth/me")).json();
    if (info?.clientPrincipal) document.getElementById("admin-link").style.display = "inline";
  } catch (_) {}

  try {
    const resp = await fetch("/api/performance-stats");
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return; }
    const data = await resp.json();
    if (!data.ok) return showError(data.error || "unknown error");
    render(data);
  } catch (e) {
    showError(`Could not load: ${e.message}`);
  }
})();


const money = (v) => "$" + Math.round(v || 0).toLocaleString("en-GB");
const num   = (v) => Number(v || 0).toLocaleString("en-GB");

function delta(now, was, fmt) {
  if (was === null || was === undefined) return "";
  const d = now - was;
  if (!d) return `<span class="perf-delta dim">no change</span>`;
  const cls = d > 0 ? "pos" : "neg";
  return `<span class="perf-delta ${cls}">${d > 0 ? "+" : "−"}${fmt(Math.abs(d))} on last week</span>`;
}

function card(label, value, sub) {
  return `<div class="mbr-card">
    <span class="mbr-card-label">${label}</span>
    <span class="mbr-card-value">${value}</span>
    <span class="mbr-card-sub">${sub || ""}</span>
  </div>`;
}

function runnerTable(rows, dateLabel, dateKey) {
  if (!rows.length) return `<p class="mbr-empty">None.</p>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Role</th><th>Client</th><th class="num">${dateLabel}</th><th class="num">Hrs/wk</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${esc(r.role)}</td><td>${esc(r.client)}</td>
      <td class="num">${r[dateKey] ? new Date(r[dateKey] + "T00:00:00").toLocaleDateString("en-GB",
        { day: "numeric", month: "short" }) : "—"}</td>
      <td class="num">${num(r.hours)}</td></tr>`).join("")}</tbody>
  </table></div>`;
}

// Simple inline bar chart — no libraries, renders in the dark theme
function trendChart(trend, key, fmt) {
  const max = Math.max(...trend.map(t => t[key] || 0), 1);
  return `<div class="perf-chart">${trend.map(t => `
    <div class="perf-bar-col" title="${t.month}: ${fmt(t[key])}">
      <span class="perf-bar" style="height:${Math.max(2, (t[key] || 0) / max * 100)}%"></span>
      <span class="perf-bar-label">${t.month.slice(5)}</span>
    </div>`).join("")}</div>`;
}

function render(d) {
  const n = d.now, l = d.last_week, w = d.week;
  document.getElementById("perf-sub").textContent =
    `${d.desk} · week of ${new Date(d.week_start + "T00:00:00").toLocaleDateString("en-GB",
      { day: "numeric", month: "long", year: "numeric" })} · all figures USD`;

  const blended = n.revenue ? Math.round(n.gp / n.revenue * 100) : null;

  document.getElementById("perf-content").innerHTML = `
    <section class="mbr-headline">
      ${card("Revenue — weekly run rate", money(n.revenue), delta(n.revenue, l.revenue, money))}
      ${card("GP — weekly run rate", money(n.gp),
             delta(n.gp, l.gp, money) + (blended ? ` <span class="dim">· ${blended}% margin</span>` : ""))}
      ${card("Runners out", num(n.runners), delta(n.runners, l.runners, num))}
      ${card("Hours per week", num(n.hours), delta(n.hours, l.hours, num))}
    </section>

    <section class="mbr-section">
      <h2>12-month trend</h2>
      <div class="perf-trends">
        <div><span class="perf-chart-title">Runners out</span>${trendChart(d.trend, "runners", num)}</div>
        <div><span class="perf-chart-title">GP per week</span>${trendChart(d.trend, "gp", money)}</div>
        <div><span class="perf-chart-title">Hours per week</span>${trendChart(d.trend, "hours", num)}</div>
        <div><span class="perf-chart-title">Job orders created</span>${trendChart(d.trend, "job_orders", num)}</div>
        <div><span class="perf-chart-title">Connects</span>${trendChart(d.trend, "connects", num)}</div>
      </div>
    </section>

    <section class="mbr-section">
      <h2>This week</h2>
      <section class="mbr-headline">
        ${card("Interviews", num(w.interviews), "")}
        ${card("CVs submitted", num(w.cvs), "")}
        ${card("Client visits", num(w.client_visits), "")}
        ${card("Connects", num(w.connects),
               `${num(w.connects_recruiting)} recruiting · ${num(w.connects_sales)} sales`)}
      </section>
    </section>

    <section class="mbr-section">
      <h2>Clients</h2>
      <section class="mbr-headline">
        ${card("Billed clients", num(d.billed_clients_12m), "rolling 12 months")}
        ${card("Clients with multiple runners", num(d.clients_multi_runners.length), "live now")}
      </section>
      ${d.clients_multi_runners.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Client</th><th class="num">Runners</th></tr></thead>
        <tbody>${d.clients_multi_runners.map(c => `<tr><td>${esc(c.client)}</td>
          <td class="num">${num(c.runners)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    </section>

    <section class="mbr-section">
      <h2>Starts and ends</h2>
      <div class="perf-cols">
        <div><h3 class="perf-col-title">Starting this week (${w.starting.length})</h3>
          ${runnerTable(w.starting, "Starts", "start")}</div>
        <div><h3 class="perf-col-title">Ending this week (${w.ending.length})</h3>
          ${runnerTable(w.ending, "Ends", "end")}</div>
        <div><h3 class="perf-col-title">Future starts (${d.future_starts.length})</h3>
          ${runnerTable(d.future_starts, "Starts", "start")}</div>
        <div><h3 class="perf-col-title">Ends in the next 30 days (${d.future_ends_30d.length})</h3>
          ${runnerTable(d.future_ends_30d, "Ends", "end")}</div>
      </div>
    </section>`;
}

function showError(msg) {
  document.getElementById("perf-content").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
}

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
