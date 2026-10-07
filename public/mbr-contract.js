/**
 * Contract MBR — a desk's month, then its year (London Contract, Oct 2026).
 *
 * Built for the review itself: Jonny sits down once a month, with the team or
 * one consultant, and asks how the month went against budget, where the book
 * is heading, and what's driving it. So the page leads with a scorecard for
 * the month being reviewed — each figure against its budget, its change on
 * last month, and its trend — and keeps the full month-by-month table beneath
 * for the detail.
 *
 * Colour carries meaning only: blue/gold markers pair each actual with its
 * budget (Jonny's sheet's colour coding), status colours say ahead or behind,
 * and a light tint marks summary columns. Typed figures read like any other
 * until "Edit typed figures" turns them into boxes.
 */
const params = new URLSearchParams(window.location.search);
const DESK = params.get("desk") || "London Contract";
const state = {
  view: params.get("view") || "",
  year: Number(params.get("year")) || new Date().getFullYear(),
  focus: params.get("month") || "",
  editing: false,
  showPeriods: true,
  collapsed: new Set(),
};
let data = null;
const dirty = {};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"];
const monthOf = (c) => /^P\d+$/.test(c) ? Number(c.slice(1)) : null;
const SECTION_TITLES = { Targets: "Targets", Book: "Book", "WGP prediction": "WGP prediction",
  Deals: "Deals", Interviews: "Interviews", Jobs: "Jobs", Meetings: "Meetings",
  Activity: "Activity drivers", Customers: "Customers" };

try {
  const saved = JSON.parse(localStorage.getItem("cmbr-prefs") || "{}");
  if (typeof saved.showPeriods === "boolean") state.showPeriods = saved.showPeriods;
  (saved.collapsed || []).forEach(s => state.collapsed.add(s));
} catch (_) {}
function savePrefs() {
  try {
    localStorage.setItem("cmbr-prefs", JSON.stringify({
      showPeriods: state.showPeriods, collapsed: [...state.collapsed] }));
  } catch (_) {}
}

window.addEventListener("beforeunload", (e) => {
  if (Object.keys(dirty).length) { e.preventDefault(); e.returnValue = ""; }
});

(function init() {
  document.getElementById("cmbr-desk").textContent = DESK;
  const ys = document.getElementById("cmbr-year");
  const now = new Date().getFullYear();
  [now, now - 1].forEach(y => ys.appendChild(new Option(String(y), String(y))));
  ys.value = String(state.year);
  ys.addEventListener("change", () => { state.year = Number(ys.value); state.focus = ""; load(); });
  document.getElementById("cmbr-view").addEventListener("change", (e) => { state.view = e.target.value; load(); });
  document.getElementById("cmbr-month").addEventListener("change", (e) => {
    state.focus = e.target.value; syncUrl(); renderAll();
  });
  load();
})();

function syncUrl() {
  const q = new URLSearchParams({ desk: DESK, year: state.year, view: state.view });
  if (state.focus) q.set("month", state.focus);
  history.replaceState(null, "", `/mbr-contract?${q}`);
}

async function load() {
  if (Object.keys(dirty).length && !window.confirm("Discard the changes you haven't saved?")) return;
  setBody(`<div class="loading-state"><div class="spinner"></div><p>Working out the year from Mercury…</p></div>`);
  const q = new URLSearchParams({ desk: DESK, year: state.year });
  if (state.view) q.set("view", state.view);
  try {
    const resp = await fetch(`/api/mbr-contract?${q}`);
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return; }
    const d = await resp.json();
    if (!d.ok) return showError(d.error === "forbidden" ? "You can't open this view." : (d.error || "Something went wrong."));
    data = d;
    state.view = d.view;
    if (!state.focus || !d.values[state.focus]) state.focus = d.focus;
    state.editing = false;
    Object.keys(dirty).forEach(k => delete dirty[k]);
    syncUrl();
    renderControls();
    renderAll();
  } catch (e) {
    showError(`Could not load: ${e.message}`);
  }
}

function setBody(html) { document.getElementById("cmbr-body").innerHTML = html; }

function showError(msg) {
  const box = document.getElementById("cmbr-body");
  box.textContent = "";
  const p = document.createElement("p");
  p.className = "mbr-empty";
  p.textContent = msg;
  box.appendChild(p);
}

// ── Controls ──────────────────────────────────────────────────────────────────

function renderControls() {
  const d = data;
  const view = document.getElementById("cmbr-view");
  view.textContent = "";
  if (d.can_team) view.appendChild(new Option("Whole team", "team"));
  d.people.forEach(p => view.appendChild(new Option(p.name + (p.active ? "" : " (left)"), p.uid)));
  view.value = d.view;
  view.closest(".cmbr-ctl").hidden = view.options.length < 2;

  const month = document.getElementById("cmbr-month");
  month.textContent = "";
  d.columns.filter(monthOf).forEach(c => {
    const m = monthOf(c);
    month.appendChild(new Option(`${LONG[m - 1]}${c === d.partial ? " (so far)" : ""}`, c));
  });
  month.value = state.focus;

  const who = d.view === "team" ? "Whole team" : (d.people.find(p => p.uid === d.view) || {}).name || "";
  document.getElementById("cmbr-who").textContent = who;
}

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(unit, v, compact) {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  switch (unit) {
    case "money":
      if (compact && Math.abs(v) >= 1000000) {
        return "£" + (Math.round(v / 10000) / 100).toFixed(2) + "m";
      }
      if (compact && Math.abs(v) >= 10000) {
        const k = v / 1000;
        return "£" + (Math.abs(k) >= 100 ? Math.round(k) : (Math.round(k * 10) / 10).toFixed(1)) + "k";
      }
      return "£" + Math.round(v).toLocaleString("en-GB");
    case "pct":   return Math.round(v * 100) + "%";
    case "ratio":
    case "weeks": return (Math.round(v * 10) / 10).toFixed(1);
    default:      return Number.isInteger(v) ? v.toLocaleString("en-GB") : (Math.round(v * 10) / 10).toFixed(1);
  }
}

function status(ach) {
  if (ach === null || ach === undefined) return null;
  if (ach >= 1) return { cls: "good", icon: "▲", text: "Ahead" };
  if (ach >= 0.9) return { cls: "warn", icon: "●", text: "Close" };
  return { cls: "bad", icon: "▼", text: "Behind" };
}

const val = (c, k) => ((data.values[c] || {})[k]);
const measure = (k) => data.measures.find(m => m.key === k);

function prevMonth(c) {
  const m = monthOf(c);
  return m && m > 1 ? `P${m - 1}` : null;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderAll() {
  const box = document.getElementById("cmbr-body");
  box.textContent = "";
  box.appendChild(scorecard());
  box.appendChild(gridCard());
}

// Scorecard: the month being reviewed, each figure against what it should be
function scorecard() {
  const d = data, c = state.focus, p = prevMonth(c);
  const wrap = document.createElement("section");
  wrap.className = "cmbr-score";
  wrap.setAttribute("aria-label", `${LONG[monthOf(c) - 1]} at a glance`);

  const tiles = d.view === "team" ? [
    { key: "gp_month", label: "GP", budget: "gp_budget", ach: "gp_achievement" },
    { key: "runners_split", label: "Runners out", budget: "runners_budget", unit: "count" },
    { key: "wgp_running", label: "Running WGP", sub: "runners", subLabel: "contractors" },
    { key: "wgp_predicted", label: "Next month's WGP", forecast: true },
    { key: "deals", label: "Deals", sub: "deals_wgp", subLabel: "new WGP" },
    { key: "interviews", label: "Interviews", sub: "cvs", subLabel: "CVs sent" },
  ] : [
    { key: "wgp_running", label: "Running WGP", sub: "runners", subLabel: "contractors" },
    { key: "wgp_predicted", label: "Next month's WGP", forecast: true },
    { key: "deals", label: "Deals", sub: "deals_wgp", subLabel: "new WGP" },
    { key: "interviews", label: "Interviews", sub: "interviews_first", subLabel: "first interviews" },
    { key: "cvs", label: "CVs sent", sub: "jobs_with_iv", subLabel: "jobs with interviews" },
    { key: "client_meetings", label: "Client meetings", sub: "bd_calls", subLabel: "BD calls" },
  ];
  tiles.forEach(t => {
    const m = measure(t.key);
    if (!m) return;
    wrap.appendChild(tile(t, m, c, p));
  });
  return wrap;
}

function tile(t, m, c, p) {
  const el = document.createElement("article");
  el.className = "cmbr-tile";
  const v = val(c, t.key);

  const label = document.createElement("h3");
  label.className = "cmbr-tile-label";
  label.textContent = t.label;
  el.appendChild(label);

  const big = document.createElement("div");
  big.className = "cmbr-tile-value";
  big.textContent = v === null || v === undefined ? "—" : fmt(m.unit, v, true);
  if (v === null || v === undefined) big.classList.add("is-empty");
  el.appendChild(big);

  const lines = document.createElement("div");
  lines.className = "cmbr-tile-lines";

  if (t.budget) {
    const b = val(c, t.budget);
    const ach = t.ach ? val(c, t.ach) : (b ? (v || 0) / b : null);
    const line = document.createElement("div");
    line.className = "cmbr-tile-line";
    if (b !== null && b !== undefined) {
      line.textContent = `of ${fmt(m.unit, b, true)} budget`;
      const st = status(ach);
      if (st && v !== null && v !== undefined) {
        const chip = document.createElement("span");
        chip.className = `cmbr-status cmbr-status-${st.cls}`;
        chip.textContent = `${st.icon} ${Math.round(ach * 100)}% · ${st.text}`;
        line.appendChild(chip);
      }
    } else {
      line.textContent = "No budget set";
    }
    lines.appendChild(line);
  }
  if (t.forecast) {
    const s = val(c, "starters_next_wgp"), f = val(c, "expected_finishers_wgp");
    const line = document.createElement("div");
    line.className = "cmbr-tile-line";
    line.textContent = `+${fmt("money", s || 0, true)} starting · −${fmt("money", f || 0, true)} finishing`;
    lines.appendChild(line);
  }
  if (t.sub) {
    const sm = measure(t.sub);
    const line = document.createElement("div");
    line.className = "cmbr-tile-line";
    line.textContent = `${fmt(sm ? sm.unit : "count", val(c, t.sub), true) || "—"} ${t.subLabel}`;
    lines.appendChild(line);
  }
  if (p && !t.forecast) {
    const was = val(p, t.key);
    if (v !== null && v !== undefined && was !== null && was !== undefined) {
      const diff = v - was;
      const line = document.createElement("div");
      line.className = "cmbr-tile-line cmbr-delta " + (diff > 0 ? "up" : diff < 0 ? "down" : "");
      line.textContent = diff === 0 ? `Same as ${MONTHS[monthOf(p) - 1]}`
        : `${diff > 0 ? "▲" : "▼"} ${fmt(m.unit, Math.abs(diff), true)} on ${MONTHS[monthOf(p) - 1]}`;
      lines.appendChild(line);
    }
  }
  el.appendChild(lines);
  el.appendChild(spark(t.key, t.budget));
  return el;
}

// Twelve-point trend for the year so far: the focus month marked, the month
// still running left out (it isn't finished), the budget as a faint step.
function spark(key, budgetKey) {
  const months = data.columns.filter(c => monthOf(c) && c !== data.partial);
  const pts = months.map(c => val(c, key));
  const W = 200, H = 34, PAD = 3;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "cmbr-spark");
  svg.setAttribute("aria-hidden", "true");
  const nums = pts.filter(v => v !== null && v !== undefined);
  const bud = budgetKey ? months.map(c => val(c, budgetKey)) : [];
  const all = nums.concat(bud.filter(v => v !== null && v !== undefined));
  if (nums.length < 2) return svg;
  const lo = Math.min(0, ...all), hi = Math.max(...all) || 1;
  const x = i => PAD + i * (W - PAD * 2) / Math.max(1, months.length - 1);
  const y = v => H - PAD - (v - lo) / (hi - lo || 1) * (H - PAD * 2);
  const path = (series, cls) => {
    let dAttr = "", pen = false;
    series.forEach((v, i) => {
      if (v === null || v === undefined) { pen = false; return; }
      dAttr += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    const el = document.createElementNS(svg.namespaceURI, "path");
    el.setAttribute("d", dAttr); el.setAttribute("class", cls);
    svg.appendChild(el);
  };
  if (bud.some(v => v !== null && v !== undefined)) path(bud, "cmbr-spark-budget");
  path(pts, "cmbr-spark-line");
  const fi = months.indexOf(state.focus);
  if (fi >= 0 && pts[fi] !== null && pts[fi] !== undefined) {
    const dot = document.createElementNS(svg.namespaceURI, "circle");
    dot.setAttribute("cx", x(fi)); dot.setAttribute("cy", y(pts[fi])); dot.setAttribute("r", 3.5);
    dot.setAttribute("class", "cmbr-spark-dot");
    svg.appendChild(dot);
  }
  return svg;
}

// ── The table ─────────────────────────────────────────────────────────────────

function gridCard() {
  const d = data;
  const card = document.createElement("section");
  card.className = "cmbr-card";

  const head = document.createElement("div");
  head.className = "cmbr-card-head";
  const h = document.createElement("h2");
  h.textContent = "Month by month";
  head.appendChild(h);

  const tools = document.createElement("div");
  tools.className = "cmbr-tools";
  const toggle = document.createElement("label");
  toggle.className = "cmbr-switch";
  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.id = "cmbr-periods"; cb.checked = state.showPeriods;
  cb.addEventListener("change", () => { state.showPeriods = cb.checked; savePrefs(); renderAll(); });
  toggle.append(cb, document.createTextNode(" Quarters & half-years"));
  tools.appendChild(toggle);

  const all = document.createElement("button");
  all.type = "button"; all.className = "cmbr-btn-quiet";
  const sections = [...new Set(d.measures.map(m => m.section))];
  const allClosed = sections.every(s => state.collapsed.has(s));
  all.textContent = allClosed ? "Expand all" : "Collapse all";
  all.addEventListener("click", () => {
    if (allClosed) state.collapsed.clear(); else sections.forEach(s => state.collapsed.add(s));
    savePrefs(); renderAll();
  });
  tools.appendChild(all);

  if (d.view === "team" && d.can_edit) {
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = state.editing ? "cmbr-btn-quiet" : "save-btn";
    edit.textContent = state.editing ? "Stop editing" : "Edit typed figures";
    edit.addEventListener("click", () => {
      if (state.editing && Object.keys(dirty).length &&
          !window.confirm("Discard the changes you haven't saved?")) return;
      state.editing = !state.editing;
      Object.keys(dirty).forEach(k => delete dirty[k]);
      renderAll();
    });
    tools.appendChild(edit);
  }
  head.appendChild(tools);
  card.appendChild(head);
  card.appendChild(legend());

  const cols = d.columns.filter(c => monthOf(c) || c === "YTD" || state.showPeriods);
  const months = cols.filter(monthOf), summary = cols.filter(c => !monthOf(c));
  const order = months.concat(summary.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)));

  const wrap = document.createElement("div");
  wrap.className = "cmbr-scroll";
  const table = document.createElement("table");
  table.className = "cmbr-grid" + (state.editing ? " is-editing" : "");

  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  const corner = document.createElement("th");
  corner.className = "cmbr-name"; corner.scope = "col";
  corner.textContent = "Measure";
  tr.appendChild(corner);
  order.forEach((c, i) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = colClass(c, i, order);
    if (monthOf(c)) {
      th.textContent = MONTHS[monthOf(c) - 1];
      if (c === d.partial) {
        const so = document.createElement("span");
        so.className = "cmbr-sofar"; so.textContent = "so far";
        th.appendChild(so);
      }
    } else {
      th.textContent = c === "YTD" ? "Year to date" : `${c} avg`;
    }
    tr.appendChild(th);
  });
  thead.appendChild(tr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let section = null;
  d.measures.forEach(m => {
    if (m.section !== section) {
      section = m.section;
      tbody.appendChild(sectionRow(section, order.length + 1));
    }
    if (state.collapsed.has(m.section)) return;
    tbody.appendChild(dataRow(m, order));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  card.appendChild(wrap);

  if (state.editing) card.appendChild(editBar());
  return card;
}

// Year to date first: it's the summary people look for
const ORDER = ["YTD", "Q1", "Q2", "Q3", "Q4", "H1", "H2"];

function colClass(c, i, order) {
  const cls = ["num"];
  if (!monthOf(c)) cls.push("cmbr-sum");
  if (!monthOf(c) && (i === 0 || monthOf(order[i - 1]))) cls.push("cmbr-sum-first");
  if (c === "YTD") cls.push("cmbr-ytd");
  if (c === state.focus) cls.push("cmbr-focus");
  if (c === data.partial) cls.push("cmbr-partial");
  return cls.join(" ");
}

function legend() {
  const el = document.createElement("div");
  el.className = "cmbr-legend";
  const add = (cls, text) => {
    const i = document.createElement("span");
    i.className = "cmbr-key";
    const sw = document.createElement("span");
    sw.className = "cmbr-key-mark " + cls;
    i.append(sw, document.createTextNode(text));
    el.appendChild(i);
  };
  if (data.view === "team") { add("is-actual", "Actual"); add("is-budget", "Budget"); }
  if (data.view === "team") add("is-typed", "Typed by the director");
  add("is-est", "Estimate");
  add("is-focus", `${LONG[monthOf(state.focus) - 1]} (reviewing)`);
  const note = document.createElement("span");
  note.className = "cmbr-legend-note";
  note.textContent = "Money is weekly gross profit (WGP) in GBP. Quarter and half-year columns are monthly averages; ratios use each period's totals.";
  el.appendChild(note);
  return el;
}

function sectionRow(section, span) {
  const tr = document.createElement("tr");
  tr.className = "cmbr-sec";
  const td = document.createElement("td");
  td.colSpan = span;
  const btn = document.createElement("button");
  btn.type = "button";
  const open = !state.collapsed.has(section);
  btn.setAttribute("aria-expanded", String(open));
  btn.className = "cmbr-sec-btn";
  const chev = document.createElement("span");
  chev.className = "cmbr-chev"; chev.textContent = open ? "▾" : "▸";
  const n = data.measures.filter(m => m.section === section).length;
  const count = document.createElement("span");
  count.className = "cmbr-sec-count"; count.textContent = `${n}`;
  btn.append(chev, document.createTextNode(SECTION_TITLES[section] || section), count);
  btn.addEventListener("click", () => {
    if (state.collapsed.has(section)) state.collapsed.delete(section); else state.collapsed.add(section);
    savePrefs(); renderAll();
  });
  td.appendChild(btn);
  tr.appendChild(td);
  return tr;
}

function dataRow(m, order) {
  const tr = document.createElement("tr");
  if (m.tone) tr.classList.add(`is-${m.tone}`);

  const name = document.createElement("th");
  name.scope = "row";
  name.className = "cmbr-name";
  const text = document.createElement("span");
  text.textContent = m.label;
  name.appendChild(text);
  if (m.input) {
    const tag = document.createElement("span");
    tag.className = "cmbr-tag cmbr-tag-typed"; tag.textContent = "typed";
    tag.title = "Typed by the desk's director; Mercury's own figure shows greyed where none is typed";
    name.appendChild(tag);
  }
  if (m.estimate) {
    const tag = document.createElement("span");
    tag.className = "cmbr-tag cmbr-tag-est"; tag.textContent = "est";
    tag.title = m.key === "headcount"
      ? "A leaver counts until their last activity in Mercury, which records no leaving date."
      : "Mercury records a closing date on only some closed jobs, so earlier months overstate this.";
    name.appendChild(tag);
  }
  tr.appendChild(name);

  order.forEach((c, i) => {
    const td = document.createElement("td");
    td.className = colClass(c, i, order);
    const v = val(c, m.key);
    const guide = (data.estimates || {})[`${m.key}|${c}`];
    const canType = m.input && data.can_edit && c !== "YTD";

    if (state.editing && canType) {
      const input = document.createElement("input");
      input.type = "number"; input.step = "any"; input.className = "cmbr-input";
      input.id = `cmbr-${m.key}-${c}`;
      input.value = v === null || v === undefined ? "" : String(Math.round(v * 100) / 100);
      if (guide !== undefined) input.placeholder = String(Math.round(guide * 100) / 100);
      input.setAttribute("aria-label", `${m.label}, ${monthOf(c) ? LONG[monthOf(c) - 1] : c}`);
      input.addEventListener("input", () => {
        const when = monthOf(c) ? String(monthOf(c)).padStart(2, "0") : c;
        dirty[`${m.key}:${data.year}-${when}`] = input.value;
        const n = document.getElementById("cmbr-dirty");
        if (n) n.textContent = `${Object.keys(dirty).length} unsaved change${Object.keys(dirty).length === 1 ? "" : "s"}`;
      });
      td.appendChild(input);
    } else if ((v === null || v === undefined) && m.input && guide !== undefined) {
      // Nothing typed: show Mercury's figure, clearly as a stand-in
      td.textContent = fmt(m.unit, guide, true);
      td.classList.add("is-guide");
      td.title = "Nothing typed yet. This is Mercury's own figure.";
    } else {
      td.textContent = fmt(m.unit, v, true);
      if (m.unit === "money" && v !== null && v !== undefined && Math.abs(v) >= 10000) {
        td.title = fmt("money", v, false);
      }
      if (m.key === "gp_achievement" || m.key === "runners_budget_pct") {
        const st = status(v);
        if (st) td.classList.add(`is-${st.cls}`);
      }
      if (m.estimate) td.classList.add("is-est");
    }
    tr.appendChild(td);
  });
  return tr;
}

function editBar() {
  const bar = document.createElement("div");
  bar.className = "cmbr-editbar";
  const msg = document.createElement("span");
  msg.className = "cmbr-editbar-msg";
  msg.textContent = "Editing typed figures. Empty boxes show Mercury's figure as a guide.";
  const n = document.createElement("span");
  n.id = "cmbr-dirty"; n.className = "cmbr-editbar-dirty";
  const cancel = document.createElement("button");
  cancel.type = "button"; cancel.className = "cmbr-btn-quiet"; cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => {
    Object.keys(dirty).forEach(k => delete dirty[k]);
    state.editing = false; renderAll();
  });
  const save = document.createElement("button");
  save.type = "button"; save.className = "save-btn"; save.id = "cmbr-save"; save.textContent = "Save";
  save.addEventListener("click", saveTyped);
  bar.append(msg, n, cancel, save);
  return bar;
}

async function saveTyped() {
  const btn = document.getElementById("cmbr-save");
  const n = document.getElementById("cmbr-dirty");
  if (!Object.keys(dirty).length) { n.textContent = "Nothing to save."; return; }
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const resp = await fetch("/api/mbr-contract", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ desk: DESK, year: state.year, values: dirty }),
    });
    const r = await resp.json();
    if (!r.ok) throw new Error(r.error || "unknown error");
    Object.keys(dirty).forEach(k => delete dirty[k]);
    await load();
  } catch (e) {
    n.textContent = "Could not save: " + e.message;
    btn.disabled = false; btn.textContent = "Save";
  }
}
