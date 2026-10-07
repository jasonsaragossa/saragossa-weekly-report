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

function render(d) {
  const box = document.getElementById("cmbr-content");
  box.textContent = "";

  const intro = document.createElement("p");
  intro.className = "mbr-note cmbr-intro";
  intro.textContent = d.view === "team"
    ? "The desk's year from Mercury, laid out as the director's sheet. Quarter and half-year columns are monthly averages; ratios are worked from the period's totals. Money is weekly gross profit (WGP) in GBP."
    : "Your year from Mercury. Quarter and half-year columns are monthly averages; ratios are worked from the period's totals. Money is weekly gross profit (WGP) in GBP.";
  box.appendChild(intro);

  const wrap = document.createElement("div");
  wrap.className = "table-wrap cmbr-wrap";
  const table = document.createElement("table");
  table.className = "cmbr-table";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(th("", "cmbr-label"));
  d.columns.forEach(c => hr.appendChild(th(c, MONTH[c] ? "num" : "num cmbr-period")));
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
      td.colSpan = d.columns.length + 1;
      td.textContent = section;
      sr.appendChild(td);
      tbody.appendChild(sr);
    }
    tbody.appendChild(row(d, m));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  box.appendChild(wrap);

  const notes = document.createElement("p");
  notes.className = "mbr-note";
  notes.textContent = "† Estimate. Jobs carried in: Mercury records a closing date on only some closed jobs, so for earlier months a closed job counts as open until it was last changed. Headcount: a leaver counts until their last activity in Mercury.";
  box.appendChild(notes);

  if (d.view === "team" && d.can_edit) {
    const bar = document.createElement("div");
    bar.className = "mbr-savebar";
    const btn = document.createElement("button");
    btn.className = "save-btn"; btn.id = "cmbr-save"; btn.type = "button";
    btn.textContent = "Save GP and budgets";
    btn.addEventListener("click", save);
    const note = document.createElement("span");
    note.className = "mbr-saved-note"; note.id = "cmbr-saved";
    bar.append(btn, note);
    box.appendChild(bar);
  }
}

function th(text, cls) {
  const el = document.createElement("th");
  el.className = cls || "";
  el.textContent = text;
  return el;
}

function row(d, m) {
  const tr = document.createElement("tr");
  if (m.typed || m.imported) tr.className = "cmbr-input-row";
  const label = document.createElement("td");
  label.className = "cmbr-label";
  label.textContent = m.label + (m.estimate ? " †" : "");
  if (m.typed) label.title = "Typed in each month by the desk's director";
  if (m.imported) label.title = "Budget, imported from the director's sheet";
  tr.appendChild(label);

  d.columns.forEach(c => {
    const td = document.createElement("td");
    td.className = "num" + (MONTH[c] ? "" : " cmbr-period");
    const v = (d.values[c] || {})[m.key];
    const editable = (m.typed || m.imported) && MONTH[c] && d.view === "team" && d.can_edit;
    if (editable) {
      const input = document.createElement("input");
      input.type = "number"; input.step = "any"; input.className = "cmbr-input";
      input.id = `cmbr-${m.key}-${c}`;
      input.value = v === null || v === undefined ? "" : String(Math.round(v * 100) / 100);
      input.setAttribute("aria-label", `${m.label}, ${c}`);
      input.addEventListener("input", () => {
        dirty[`${m.key}:${d.year}-${String(MONTH[c]).padStart(2, "0")}`] = input.value;
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
  btn.disabled = false; btn.textContent = "Save GP and budgets";
}

function showError(msg) {
  const box = document.getElementById("cmbr-content");
  box.textContent = "";
  const p = document.createElement("p");
  p.className = "mbr-empty";
  p.textContent = msg;
  box.appendChild(p);
}
