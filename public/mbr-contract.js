/**
 * Contract MBR: a desk's year, laid out like the director's spreadsheet it
 * replaces (Jonny Demko, London Contract, Oct 2026).
 *
 * Measures run down the side by section; months P1–P12 run across with the
 * quarter and half-year columns between them, as in the sheet. Everything is
 * worked out from Mercury except the month's GP, which Jonny types, and the
 * budgets imported from his sheet — those rows are input boxes in the team
 * view for whoever may change them.
 */
const params = new URLSearchParams(window.location.search);
const DESK = params.get("desk") || "London Contract";
let state = { view: params.get("view") || "", year: Number(params.get("year")) || new Date().getFullYear() };
let data = null;
const dirty = {};

(function init() {
  document.getElementById("cmbr-title").textContent = `MBR — ${DESK}`;
  const ys = document.getElementById("cmbr-year");
  const now = new Date().getFullYear();
  ys.innerHTML = [now, now - 1].map(y => `<option value="${y}">${y}</option>`).join("");
  ys.value = String(state.year);
  ys.addEventListener("change", () => { state.year = Number(ys.value); load(); });
  document.getElementById("cmbr-view").addEventListener("change", (e) => { state.view = e.target.value; load(); });
  load();
})();

async function load() {
  const box = document.getElementById("cmbr-content");
  box.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Working out the year from Mercury…</p></div>`;
  const qs = new URLSearchParams({ desk: DESK, year: state.year });
  if (state.view) qs.set("view", state.view);
  try {
    const resp = await fetch(`/api/mbr-contract?${qs}`);
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return; }
    const d = await resp.json();
    if (!d.ok) return showError(d.error === "forbidden" ? "You can't open this view." : (d.error || "Something went wrong."));
    data = d;
    state.view = d.view;
    Object.keys(dirty).forEach(k => delete dirty[k]);
    history.replaceState(null, "", `/mbr-contract?${new URLSearchParams({ desk: DESK, year: state.year, view: d.view })}`);
    renderViewPicker(d);
    render(d);
  } catch (e) {
    showError(`Could not load: ${e.message}`);
  }
}

function renderViewPicker(d) {
  const sel = document.getElementById("cmbr-view");
  sel.textContent = "";
  const opts = [];
  if (d.can_team) opts.push({ value: "team", label: `Team — ${DESK}` });
  d.people.forEach(p => opts.push({ value: p.uid, label: p.name + (p.active ? "" : " (left)") }));
  opts.forEach(o => {
    const el = document.createElement("option");
    el.value = o.value; el.textContent = o.label;
    sel.appendChild(el);
  });
  sel.value = d.view;
  sel.closest(".mbr-ctl").hidden = opts.length < 2;
}

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(unit, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  switch (unit) {
    case "money": return "£" + Math.round(v).toLocaleString("en-GB");
    case "pct":   return Math.round(v * 100) + "%";
    case "ratio":
    case "weeks": return (Math.round(v * 10) / 10).toFixed(1);
    default:      return Number.isInteger(v) ? String(v) : (Math.round(v * 10) / 10).toFixed(1);
  }
}

const MONTH = { P1: 1, P2: 2, P3: 3, P4: 4, P5: 5, P6: 6, P7: 7, P8: 8, P9: 9, P10: 10, P11: 11, P12: 12 };

// ── Render ────────────────────────────────────────────────────────────────────
// Coloured as Jonny's sheet: section bands and quarter columns green, half-year
// columns pale blue, and in the top block each actual (blue) beside its budget
// (gold). The same four colours, softer, in dark mode.

const SECTION_TITLES = { Book: "Team book", Deals: "Team deals", Interviews: "Team interviews",
                         Jobs: "Team jobs", Meetings: "Team meetings", Activity: "Team activity drivers",
                         Customers: "Team customers" };

function render(d) {
  const box = document.getElementById("cmbr-content");
  box.textContent = "";
  box.appendChild(legend(d));

  const wrap = document.createElement("div");
  wrap.className = "table-wrap cmbr-wrap";
  const table = document.createElement("table");
  table.className = "cmbr-table";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(th("", "cmbr-label"));
  d.columns.forEach(c => hr.appendChild(th(MONTH[c] ? c : `${c} avg`, colClass(c))));
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let section = null;
  d.measures.forEach(m => {
    if (m.section !== section) {
      section = m.section;
      const sr = document.createElement("tr");
      sr.className = "cmbr-section";
      const td = document.createElement("td");
      td.className = "cmbr-label";
      td.textContent = d.view === "team" ? (SECTION_TITLES[section] || section) : section;
      sr.appendChild(td);
      d.columns.forEach(c => sr.appendChild(Object.assign(document.createElement("td"), { className: colClass(c) })));
      tbody.appendChild(sr);
    }
    tbody.appendChild(row(d, m));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  box.appendChild(wrap);

  if (d.view === "team" && d.can_edit) {
    const bar = document.createElement("div");
    bar.className = "mbr-savebar";
    const btn = document.createElement("button");
    btn.className = "save-btn"; btn.id = "cmbr-save"; btn.type = "button";
    btn.textContent = "Save typed figures";
    btn.addEventListener("click", save);
    const note = document.createElement("span");
    note.className = "mbr-saved-note"; note.id = "cmbr-saved";
    bar.append(btn, note);
    box.appendChild(bar);
  }
}

function colClass(c) {
  if (MONTH[c]) return "num";
  return "num " + (c.startsWith("H") ? "cmbr-half" : "cmbr-quarter");
}

// A key to the colours and marks, along the top where it's seen
function legend(d) {
  const el = document.createElement("div");
  el.className = "cmbr-legend";
  const items = [];
  if (d.view === "team") {
    items.push(["cmbr-key-actual", "Actual"], ["cmbr-key-budget", "Budget / target"]);
  }
  items.push(["cmbr-key-quarter", "Quarter average"], ["cmbr-key-half", "Half-year average"]);
  if (d.view === "team" && d.can_edit) items.push(["cmbr-key-input", "Typed: Mercury's figure shows greyed until filled"]);
  items.push(["cmbr-key-est", "Estimate"]);
  items.forEach(([cls, text]) => {
    const i = document.createElement("span");
    i.className = "cmbr-key";
    const sw = document.createElement("span");
    sw.className = "cmbr-swatch " + cls;
    if (cls === "cmbr-key-est") sw.textContent = "est";
    i.append(sw, document.createTextNode(text));
    el.appendChild(i);
  });
  const note = document.createElement("span");
  note.className = "cmbr-legend-note";
  note.textContent = "Money is weekly gross profit (WGP) in GBP. Ratios use each period's totals.";
  el.appendChild(note);
  return el;
}

function th(text, cls) {
  const el = document.createElement("th");
  el.className = cls || "";
  el.textContent = text;
  return el;
}

function row(d, m) {
  const tr = document.createElement("tr");
  tr.className = [m.tone ? `cmbr-tone-${m.tone}` : "", m.input ? "cmbr-input-row" : ""].join(" ").trim();

  const label = document.createElement("td");
  label.className = "cmbr-label";
  label.appendChild(document.createTextNode(m.label));
  if (m.estimate) {
    const est = document.createElement("span");
    est.className = "cmbr-est";
    est.textContent = "est";
    est.title = m.key === "headcount"
      ? "A leaver counts until their last activity in Mercury, which records no leaving date."
      : "Mercury records a closing date on only some closed jobs, so earlier months overstate this.";
    label.appendChild(est);
  }
  tr.appendChild(label);

  d.columns.forEach(c => {
    const td = document.createElement("td");
    td.className = colClass(c) + (m.estimate ? " cmbr-estimate" : "");
    const v = (d.values[c] || {})[m.key];
    const editable = m.input && d.can_edit;
    if (editable) {
      const input = document.createElement("input");
      input.type = "number"; input.step = "any"; input.className = "cmbr-input";
      input.id = `cmbr-${m.key}-${c}`;
      input.value = v === null || v === undefined ? "" : String(Math.round(v * 100) / 100);
      const guide = d.estimates[`${m.key}|${c}`];
      if (guide !== undefined) input.placeholder = fmt(m.unit, guide);
      input.setAttribute("aria-label", `${m.label}, ${c}`);
      input.addEventListener("input", () => {
        const when = MONTH[c] ? String(MONTH[c]).padStart(2, "0") : c;
        dirty[`${m.key}:${d.year}-${when}`] = input.value;
        document.getElementById("cmbr-saved").textContent = "Unsaved changes";
      });
      td.appendChild(input);
    } else {
      td.textContent = fmt(m.unit, v);
    }
    tr.appendChild(td);
  });
  return tr;
}

async function save() {
  const btn = document.getElementById("cmbr-save");
  const note = document.getElementById("cmbr-saved");
  if (!Object.keys(dirty).length) { note.textContent = "Nothing to save."; return; }
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const resp = await fetch("/api/mbr-contract", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ desk: DESK, year: state.year, values: dirty }),
    });
    const r = await resp.json();
    if (!r.ok) throw new Error(r.error || "unknown error");
    note.textContent = "Saved";
    await load();
  } catch (e) {
    note.textContent = "Could not save: " + e.message;
  }
  btn.disabled = false; btn.textContent = "Save typed figures";
}

function showError(msg) {
  const box = document.getElementById("cmbr-content");
  box.textContent = "";
  const p = document.createElement("p");
  p.className = "mbr-empty";
  p.textContent = msg;
  box.appendChild(p);
}
