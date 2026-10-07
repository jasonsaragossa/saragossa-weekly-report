/**
 * Performance Stats (pilot) — contract desk dashboard.
 *
 * Week-over-week movement on the live-book metrics, a 12-month trend, and this
 * week's activity. All figures are USD for the Chicago Contract desk.
 */

(async () => {

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


const money = (v) => "$" + Math.round(v || 0).toLocaleString("en-US");
const num   = (v) => Number(v || 0).toLocaleString("en-US");

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
      <td class="num">${r[dateKey] ? new Date(r[dateKey] + "T00:00:00").toLocaleDateString("en-US",
        { day: "numeric", month: "short" }) : "—"}</td>
      <td class="num">${num(r.hours)}</td></tr>`).join("")}</tbody>
  </table></div>`;
}

// ── 12-month trend: one line per metric ─────────────────────────────────────
// A single series each, so no legend — the title names it. 2px line, the
// latest month marked with a ringed dot and its value, hairline guides, and a
// crosshair that snaps to the nearest month with its value in a tooltip.
// Plain SVG, no libraries; colours come from the theme tokens so light and
// dark mode both work.
const TREND = { w: 320, h: 118, l: 6, r: 50, t: 12, b: 20 };
const TRENDS = {};                         // chart id -> {points, labels, values}
let trendSeq = 0;

function trendMonth(m) {                   // "2026-09" -> "Sep"
  return new Date(m + "-01T00:00:00").toLocaleDateString("en-US", { month: "short" });
}

function trendChart(trend, key, fmt, title) {
  const vals = trend.map(t => Number(t[key] || 0));
  const max = Math.max(...vals, 1);
  const n = vals.length;
  const iw = TREND.w - TREND.l - TREND.r, ih = TREND.h - TREND.t - TREND.b;
  const x = i => TREND.l + (n > 1 ? i * iw / (n - 1) : iw / 2);
  const y = v => TREND.t + (1 - v / max) * ih;
  const pts = vals.map((v, i) => [x(i), y(v)]);
  const id = "trend-" + (++trendSeq);
  TRENDS[id] = {
    pts, values: vals.map(fmt),
    labels: trend.map(t => new Date(t.month + "-01T00:00:00")
      .toLocaleDateString("en-US", { month: "short", year: "numeric" })),
  };
  const [lx, ly] = pts[n - 1] || [0, 0];
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const ticks = trend.map((t, i) =>
    `<text class="perf-axis" x="${x(i).toFixed(1)}" y="${TREND.h - 5}" text-anchor="middle">${
      esc(trendMonth(t.month))}</text>`).join("");
  const summary = `${title}, 12 months: ${TRENDS[id].labels[0]} ${TRENDS[id].values[0]}, `
    + `${TRENDS[id].labels[n - 1]} ${TRENDS[id].values[n - 1]}`;
  return `<svg class="perf-line" id="${id}" viewBox="0 0 ${TREND.w} ${TREND.h}"
      role="img" aria-label="${esc(summary)}" tabindex="0">
    <line class="perf-grid" x1="${TREND.l}" x2="${TREND.l + iw}" y1="${y(max)}" y2="${y(max)}"/>
    <line class="perf-base" x1="${TREND.l}" x2="${TREND.l + iw}" y1="${y(0)}" y2="${y(0)}"/>
    <path class="perf-path" d="${line}"/>
    <line class="perf-cross" y1="${TREND.t}" y2="${y(0)}" x1="0" x2="0"/>
    <circle class="perf-hover-dot" r="4" cx="0" cy="0"/>
    <circle class="perf-end-dot" r="4" cx="${lx}" cy="${ly}"/>
    <text class="perf-end-label" x="${lx + 8}" y="${ly + 3.5}">${esc(TRENDS[id].values[n - 1])}</text>
    ${ticks}
  </svg>`;
}

// One tooltip for every chart; values go in with textContent, never as HTML.
function wireTrendCharts() {
  let tip = document.getElementById("perf-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "perf-tip";
    tip.className = "perf-tip";
    tip.innerHTML = '<span class="perf-tip-month"></span><span class="perf-tip-value"></span>';
    document.body.appendChild(tip);
  }
  const hide = (svg) => { svg.classList.remove("hovering"); tip.style.display = "none"; };
  const show = (svg, i) => {
    const c = TRENDS[svg.id]; if (!c) return;
    i = Math.max(0, Math.min(c.pts.length - 1, i));
    svg.dataset.i = i;
    const [px, py] = c.pts[i];
    const cross = svg.querySelector(".perf-cross"), dot = svg.querySelector(".perf-hover-dot");
    cross.setAttribute("x1", px); cross.setAttribute("x2", px);
    dot.setAttribute("cx", px); dot.setAttribute("cy", py);
    svg.classList.add("hovering");
    tip.querySelector(".perf-tip-month").textContent = c.labels[i];
    tip.querySelector(".perf-tip-value").textContent = c.values[i];
    const box = svg.getBoundingClientRect(), scale = box.width / TREND.w;
    tip.style.display = "block";
    // Centred over the point, but never past either edge of the window
    const vw = document.documentElement.clientWidth;
    const centre = box.left + px * scale - tip.offsetWidth / 2;
    tip.style.left = (window.scrollX + Math.max(8, Math.min(centre, vw - tip.offsetWidth - 8))) + "px";
    tip.style.top = (box.top + window.scrollY + py * scale - tip.offsetHeight - 10) + "px";
  };
  const nearest = (svg, clientX) => {
    const c = TRENDS[svg.id], box = svg.getBoundingClientRect();
    const vx = (clientX - box.left) / box.width * TREND.w;
    let best = 0;
    c.pts.forEach((p, i) => { if (Math.abs(p[0] - vx) < Math.abs(c.pts[best][0] - vx)) best = i; });
    return best;
  };
  document.querySelectorAll("svg.perf-line").forEach(svg => {
    svg.addEventListener("pointermove", e => show(svg, nearest(svg, e.clientX)));
    svg.addEventListener("pointerleave", () => hide(svg));
    svg.addEventListener("focus", () => show(svg, TRENDS[svg.id].pts.length - 1));
    svg.addEventListener("blur", () => hide(svg));
    svg.addEventListener("keydown", e => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      show(svg, Number(svg.dataset.i || 0) + (e.key === "ArrowRight" ? 1 : -1));
    });
  });
}

function render(d) {
  const n = d.now, l = d.last_week, w = d.week;
  document.getElementById("perf-sub").textContent =
    `${d.desk} · week of ${new Date(d.week_start + "T00:00:00").toLocaleDateString("en-US",
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
        <div><span class="perf-chart-title">Runners out</span>${trendChart(d.trend, "runners", num, "Runners out")}</div>
        <div><span class="perf-chart-title">GP per week</span>${trendChart(d.trend, "gp", money, "GP per week")}</div>
        <div><span class="perf-chart-title">Hours per week</span>${trendChart(d.trend, "hours", num, "Hours per week")}</div>
        <div><span class="perf-chart-title">Job orders created</span>${trendChart(d.trend, "job_orders", num, "Job orders created")}</div>
        <div><span class="perf-chart-title">Connects</span>${trendChart(d.trend, "connects", num, "Connects")}</div>
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
        ${card("Clients w/ Multiple Potential", num(d.clients_single_runner.length),
               "one runner there now")}
      </section>
      ${d.clients_single_runner.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Client</th><th>Current runner's role</th></tr></thead>
        <tbody>${d.clients_single_runner.map(c => `<tr><td>${esc(c.client)}</td>
          <td>${esc(c.role)}</td></tr>`).join("")}</tbody></table></div>` : ""}
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
  wireTrendCharts();
}

function showError(msg) {
  document.getElementById("perf-content").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
}

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
