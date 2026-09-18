/**
 * Weekly 1:1 (pilot — Team Snoz).
 *
 * Follows the September 2026 Word template section for section. Key inputs,
 * live jobs and the meeting lists come from Mercury and are read-only;
 * everything else is typed and saved per person per week.
 */

let data = null;

(async () => {
  try {
    const info = await (await fetch("/.auth/me")).json();
    if (info?.clientPrincipal) document.getElementById("admin-link").style.display = "inline";
  } catch (_) {}

  const d = new Date();
  const monday = new Date(d.setDate(d.getDate() - ((d.getDay() + 6) % 7)));
  document.getElementById("oto-week").value = monday.toISOString().slice(0, 10);
  document.getElementById("oto-week").addEventListener("change", load);
  document.getElementById("oto-person").addEventListener("change", load);
  document.getElementById("feedback-open").addEventListener("click", showFeedback);
  load();
})();


// ── Feedback to Jason ─────────────────────────────────────────────────────────
// The sender comes from their login, not a typed field, so feedback can't be
// misattributed. Context (whose 1:1, which week) is sent with it.

function showFeedback() {
  let overlay = document.getElementById("fb-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "fb-modal";
    overlay.className = "modal-overlay";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title">Feedback to Jason</span>
        <button class="modal-close" id="fb-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body">
        <p class="mbr-note" style="margin-top:0">Anything that's wrong, missing, confusing or
          would make this more useful. It goes straight to Jason's inbox with your name on it.</p>
        <textarea id="fb-text" rows="6" class="oto-in"
          placeholder="What would you change?"></textarea>
        <div class="mbr-savebar" style="margin-top:12px">
          <button class="save-btn" id="fb-send">Send</button>
          <span class="mbr-saved-note" id="fb-note"></span>
        </div>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#fb-close").addEventListener("click",
      () => { overlay.style.display = "none"; });
    overlay.querySelector("#fb-send").addEventListener("click", sendFeedback);
  }
  overlay.querySelector("#fb-note").textContent = "";
  overlay.style.display = "flex";
  setTimeout(() => overlay.querySelector("#fb-text").focus(), 50);
}

async function sendFeedback() {
  const btn = document.getElementById("fb-send");
  const box = document.getElementById("fb-text");
  const note = document.getElementById("fb-note");
  if (!box.value.trim()) { note.textContent = "Write something first."; return; }
  btn.disabled = true; btn.textContent = "Sending…";
  try {
    const who = data?.person?.name ? `${data.person.name}, week of ${data.week_start}` : "";
    const resp = await fetch("/api/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: box.value, page: "121s", context: who }),
    });
    const d = await resp.json();
    if (!d.ok) throw new Error(d.error || "unknown error");
    note.textContent = "Sent — thank you.";
    box.value = "";
    setTimeout(() => { document.getElementById("fb-modal").style.display = "none"; }, 1200);
  } catch (e) {
    note.textContent = "Could not send: " + e.message;
  }
  btn.disabled = false; btn.textContent = "Send";
}

async function load() {
  const box = document.getElementById("oto-content");
  box.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
  const uid = document.getElementById("oto-person").value;
  const week = document.getElementById("oto-week").value;
  try {
    const qs = (uid ? `uid=${encodeURIComponent(uid)}&` : "")
      + (currentTemplate ? `template=${encodeURIComponent(currentTemplate)}&` : "")
      + `week=${encodeURIComponent(week)}`;
    const resp = await fetch(`/api/one-to-one?${qs}`);
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return; }
    const d = await resp.json();
    if (!d.ok) return showError(d.error || "unknown error");
    data = d;
    const sel = document.getElementById("oto-person");
    if (!sel.options.length) {
      sel.innerHTML = d.people.map(p =>
        `<option value="${esc(p.uid)}"${p.uid === d.person.uid ? " selected" : ""}>${esc(p.name)}</option>`).join("");
    }
    render(d);
  } catch (e) {
    showError(`Could not load: ${e.message}`);
  }
}

const S = (v) => esc(v || "");

// AI Readiness score as a pill: the number, its colour band, and whether it is
// live (unsaved record) or the figure frozen when the record was first saved.
function aiReadinessHtml(ai, opts) {
  opts = opts || {};
  if (!ai || ai.score == null) {
    return `<span class="ai-pill ai-none" title="No AI Readiness score${opts.why ? " — " + esc(opts.why) : ""}">
      <span class="ai-label">AI Readiness</span><span class="ai-score">—</span></span>`;
  }
  const when = ai.live
    ? "live — captured when this is first saved"
    : "as saved" + (ai.captured ? " " + new Date(ai.captured).toLocaleDateString("en-GB",
        { day: "numeric", month: "short" }) : "");
  const delta = opts.prev && opts.prev.score != null
    ? ` <span class="ai-delta ${ai.score - opts.prev.score >= 0 ? "pos" : "neg"}">${
        ai.score - opts.prev.score >= 0 ? "+" : ""}${Math.round((ai.score - opts.prev.score) * 10) / 10}</span>`
    : "";
  return `<span class="ai-pill ai-${esc(ai.band || "none")}" title="0–100, higher is better. ${esc(when)}">
    <span class="ai-label">AI Readiness</span>
    <span class="ai-score">${Math.round(ai.score)}</span>${delta}
    <span class="ai-when">${ai.live ? "live" : "saved"}</span></span>`;
}


function rowsTable(head, rows, empty) {
  return `<div class="table-wrap"><table><thead><tr>${head.map(h =>
    `<th${h.num ? ' class="num"' : ""}>${h.label}</th>`).join("")}</tr></thead>
    <tbody>${rows || `<tr><td colspan="${head.length}" class="mbr-empty">${empty}</td></tr>`}</tbody>
  </table></div>`;
}

// Repeating free-text tables (BD actions, meetings, actions) keep their rows in
// a JSON array so next week can carry them forward.
// Column specs by table name, so "+ Add row" can build a matching blank row
// later without the render having to pass them around.
const EDIT_TABLES = {};

function editRow(name, r, cols, i) {
  return `<tr data-row="${name}">
    ${cols.map(c => c.render ? `<td>${c.render(i, r)}</td>`
      : c.fixed
      ? `<td class="oto-fixed">${S(r[c.key])}</td>`
      : `<td><textarea rows="1" class="oto-in" data-name="${name}" data-key="${c.key}"
           data-idx="${i}">${S(r[c.key])}</textarea></td>`).join("")}
  </tr>`;
}

function editRows(name, saved, cols, seed) {
  EDIT_TABLES[name] = cols;
  const rows = (saved && saved.length ? saved : seed || [{}, {}, {}]);
  return rows.map((r, i) => editRow(name, r, cols, i)).join("");
}

// Sits directly under its table; the click handler finds the tbody from there.
function addRowButton(name, label) {
  return `<button type="button" class="save-btn oto-add" data-name="${name}">+ ${label}</button>`;
}

function addRow(btn) {
  const name = btn.dataset.name;
  const cols = EDIT_TABLES[name];
  const tbody = btn.previousElementSibling && btn.previousElementSibling.querySelector("tbody");
  if (!cols || !tbody) return;
  const empty = tbody.querySelector(".mbr-empty");
  if (empty) empty.closest("tr").remove();
  const idx = tbody.querySelectorAll(`tr[data-row="${name}"]`).length;
  tbody.insertAdjacentHTML("beforeend", editRow(name, {}, cols, idx));
  const tr = tbody.lastElementChild;
  tr.querySelectorAll("textarea").forEach(t => {
    autoGrow(t);
    t.addEventListener("input", () => autoGrow(t));
  });
  const first = tr.querySelector("textarea");
  if (first) first.focus();
}

// A quarter's worth of 1:1s on one strip — click a week to open it. Shared
// by every template.
function quarterStrip(d) {
  const q = d.quarter || { weeks: [], completed: [] };
  const done = new Set(q.completed || []);
  return `
    <section class="oto-quarter">
      <button class="oto-nav" data-week="${esc(q.prev || "")}" title="Earlier weeks">‹</button>
      <span class="oto-q-label">${esc(q.label || "")}</span>
      <div class="oto-weeks">
        ${(q.weeks || []).map(w => {
          const dt = new Date(w + "T00:00:00");
          const cls = [w === d.week_start ? "current" : "", done.has(w) ? "done" : ""].join(" ").trim();
          return `<button class="oto-week ${cls}" data-week="${w}"
            title="${done.has(w) ? "1:1 saved" : "not yet completed"}">${dt.getDate()}/${dt.getMonth() + 1}</button>`;
        }).join("")}
      </div>
      <button class="oto-nav" data-week="${esc(q.next || "")}" title="Later weeks">›</button>
      ${aiReadinessHtml(d.ai_readiness, { why: "nothing captured for this person yet" })}
      <span class="oto-q-count">${(q.weeks || []).filter(w => done.has(w)).length} of ${(q.weeks || []).length} completed</span>
    </section>`;
}

function renderPerm(d) {
  const saved = d.saved || {};
  const lw = d.last_week, mo = d.month;

  const cell = (key, label, period, value) => value
    ? `<span class="oto-drill" data-key="${esc(key)}" data-period="${period}"
         data-label="${esc(label)}">${value}</span>`
    : "0";
  const inputRows = d.input_rows.map(r => `<tr>
      <td>${esc(r.label)}</td>
      <td class="num"><strong>${cell(r.key, r.label, "last_week", lw[r.key])}</strong></td>
      <td class="num dim">${cell(r.key, r.label, "month", mo[r.key])}</td>
    </tr>`).join("");

  const jobRows = d.live_jobs.map((j, i) => `<tr>
      <td>${esc(j.client)}</td>
      <td>${esc(j.job)}<span class="oto-meta">${j.cvs_out} CVs out${j.priority !== "—" ? " · " + esc(j.priority) : ""}</span></td>
      <td><textarea rows="1" class="oto-in" data-name="live_job_notes" data-key="commentary"
        data-idx="${i}">${S((saved.live_job_notes || [])[i]?.commentary)}</textarea></td>
      <td><select class="oto-in" data-name="live_job_notes" data-key="close_out" data-idx="${i}">
        ${["", "Y", "N"].map(v => `<option${(saved.live_job_notes || [])[i]?.close_out === v ? " selected" : ""}>${v}</option>`).join("")}
      </select></td>
    </tr>`).join("");

  // Meetings read like the live-jobs row: person, job title, company, subject
  // and date all at full size rather than tucked into small grey meta text.
  const dash = "<span class='dim'>—</span>";
  const day = (w) => w ? new Date(w + "T00:00:00").toLocaleDateString("en-GB",
    { weekday: "short", day: "numeric", month: "short" }) : dash;
  const meetingCells = (m) => `
      <td>${esc(m.contact) || dash}${m.job_title ? `<div class="oto-sub">${esc(m.job_title)}</div>` : ""}</td>
      <td>${esc(m.client) || "<span class='dim'>no company on record</span>"}</td>
      <td>${esc(m.subject) || dash}</td>
      <td class="num">${day(m.when)}</td>`;

  const metRows = d.meetings_last_week.map((m, i) => `<tr>
      ${meetingCells(m)}
      <td><textarea rows="1" class="oto-in" data-name="meetings_last_outcome" data-key="outcome"
        data-idx="${i}">${S((saved.meetings_last_outcome || [])[i]?.outcome)}</textarea></td>
    </tr>`).join("");

  const thisRows = d.meetings_this_week.map((m, i) => `<tr>
      ${meetingCells(m)}
      <td><textarea rows="1" class="oto-in" data-name="meetings_this_plan" data-key="plan"
        data-idx="${i}">${S((saved.meetings_this_plan || [])[i]?.plan)}</textarea></td>
    </tr>`).join("");

  const meetingHead = (last) => [{label:"Who"}, {label:"Company"}, {label:"Subject"},
    {label:"Date", num:true}, {label: last ? "Outcome / plan" : "Plan of action"}];

  const carried = d.carried_actions || [];
  const carriedRows = carried.map((a, i) => `<tr>
      <td class="oto-fixed">${S(a.action)}</td>
      <td><select class="oto-in" data-name="carried_review" data-key="achieved" data-idx="${i}">
        ${["", "Yes", "No"].map(v => `<option${(saved.carried_review || [])[i]?.achieved === v ? " selected" : ""}>${v}</option>`).join("")}
      </select></td>
      <td><textarea rows="1" class="oto-in" data-name="carried_review" data-key="commentary"
        data-idx="${i}">${S((saved.carried_review || [])[i]?.commentary)}</textarea></td>
    </tr>`).join("");

  const mbrRows = (d.mbr_actions || []).map((a, i) => `<tr>
      <td class="oto-fixed">${S(a.text)}</td>
      <td><textarea rows="1" class="oto-in" data-name="mbr_progress" data-key="progress"
        data-idx="${i}">${S((saved.mbr_progress || [])[i]?.progress)}</textarea></td>
    </tr>`).join("");

  const strip = quarterStrip(d);

  document.getElementById("oto-content").innerHTML = strip + `
    <section class="mbr-section">
      <h2>Performance vs last week's actions</h2>
      ${rowsTable([{label:"Action"},{label:"Achieved"},{label:"Commentary"}], carriedRows,
        "No actions carried forward — set some at the bottom and they'll appear here next week.")}
    </section>

    <section class="mbr-section">
      <h2>Key inputs</h2>
      ${rowsTable([{label:"Input"}, {label:"Last week", num:true},
                   {label:`${esc(d.month_label || "Month")} so far`, num:true}], inputRows, "")}
      <p class="mbr-note">Pulled from Mercury — read only. ${esc(d.month_label || "Month")} so far runs
        1&ndash;${d.month_to ? new Date(d.month_to + "T00:00:00").toLocaleDateString("en-GB",
          { day: "numeric", month: "short" }) : ""}.</p>
    </section>

    <section class="mbr-section">
      <h2>Live jobs</h2>
      ${rowsTable([{label:"Client"},{label:"Job"},{label:"Commentary"},{label:"Close out this month?"}],
        jobRows, "No live jobs where you're the delivery owner.")}
    </section>

    <section class="mbr-section">
      <h2>Resourcing</h2>
      <label class="mbr-field">Resourcing priority this week (job / CVs committed)
        <textarea id="f-resourcing_priority" rows="2">${S(saved.resourcing_priority)}</textarea></label>
      <label class="mbr-field">Where is your next placement coming from, and what may hinder this?
        <textarea id="f-next_placement" rows="2">${S(saved.next_placement)}</textarea></label>
      <label class="mbr-field">Where is your next job coming from, and what will you do this week to move it forward?
        <textarea id="f-next_job" rows="2">${S(saved.next_job)}</textarea></label>
    </section>

    <section class="mbr-section">
      <h2>Business development</h2>
      <h3 class="perf-col-title">Existing client</h3>
      ${rowsTable([{label:"Action last week"},{label:"Outcome"}],
        editRows("bd_existing", saved.bd_existing, [{key:"action"},{key:"outcome"}]), "")}
      ${addRowButton("bd_existing", "Add row")}
      <h3 class="perf-col-title" style="margin-top:14px">New client</h3>
      ${rowsTable([{label:"Action last week"},{label:"Outcome"}],
        editRows("bd_new", saved.bd_new, [{key:"action"},{key:"outcome"}]), "")}
      ${addRowButton("bd_new", "Add row")}
    </section>

    <section class="mbr-section">
      <h2>Meetings</h2>
      <h3 class="perf-col-title">Took place last week</h3>
      ${rowsTable(meetingHead(true), metRows, "No client meetings logged last week.")}
      <h3 class="perf-col-title" style="margin-top:14px">Taking place this week</h3>
      ${rowsTable(meetingHead(false), thisRows, "Nothing in the diary yet.")}
    </section>

    <section class="mbr-section">
      <h2>MBR actions</h2>
      ${rowsTable([{label:"Action"},{label:"Progress"}], mbrRows,
        "No MBR actions — they'll appear here once an MBR is saved.")}
    </section>

    <section class="mbr-section">
      <h2>This week</h2>
      <label class="mbr-field">Priority list — resourcing (in order)
        <textarea id="f-priority_resourcing" rows="3">${S(saved.priority_resourcing)}</textarea></label>
      <label class="mbr-field">Priority list — business development (in order)
        <textarea id="f-priority_bd" rows="3">${S(saved.priority_bd)}</textarea></label>
      <label class="mbr-field">What do you need from me to achieve your goals?
        <textarea id="f-support_needed" rows="2">${S(saved.support_needed)}</textarea></label>
    </section>

    <section class="mbr-section">
      <h2>Actions from this 1:1</h2>
      ${rowsTable([{label:"Action"},{label:"Owner"}],
        editRows("actions", saved.actions, [{key:"action"},{key:"owner"}]), "")}
      ${addRowButton("actions", "Add action")}
      <p class="mbr-note">These carry forward to next week's "performance vs last week's actions".</p>
    </section>

    <div class="mbr-savebar">
      <button class="save-btn" id="oto-save">Save 1:1</button>
      <span class="mbr-saved-note" id="oto-saved"></span>
    </div>`;

  wireCommon();
  document.querySelectorAll(".oto-drill[data-key]").forEach(el => el.addEventListener("click", () =>
    showDetail(el.dataset.label, el.dataset.period,
               ((data.detail || {})[el.dataset.period] || {})[el.dataset.key] || [])));
}

// Every key input drills down to the records behind the count
function showModal(title, html) {
  const overlay = otoModal();
  overlay.querySelector("#oto-modal-title").textContent = title;
  overlay.querySelector("#oto-modal-body").innerHTML = html;
  overlay.style.display = "flex";
}

function otoModal() {
  let overlay = document.getElementById("oto-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "oto-modal";
    overlay.className = "modal-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-header">
        <span class="modal-title" id="oto-modal-title"></span>
        <button class="modal-close" id="oto-modal-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body" id="oto-modal-body"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.style.display = "none"; });
    overlay.querySelector("#oto-modal-close").addEventListener("click",
      () => { overlay.style.display = "none"; });
  }
  return overlay;
}

function showDetail(label, period, rows) {
  const overlay = otoModal();
  const when = period === "last_week" ? "last week" : "month to date";
  overlay.querySelector("#oto-modal-title").textContent = `${label} — ${when} (${rows.length})`;
  overlay.querySelector("#oto-modal-body").innerHTML = rows.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>Contact</th><th>Company</th><th>Subject</th><th class="num">Date</th></tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td>${esc(r.contact) || "<span class='dim'>—</span>"}${
          r.job_title ? `<div class="oto-sub">${esc(r.job_title)}</div>` : ""}</td>
        <td>${esc(r.client) || "<span class='dim'>—</span>"}</td>
        <td>${esc(r.subject) || "<span class='dim'>—</span>"}</td>
        <td class="num dim">${r.when ? new Date(r.when + "T00:00:00").toLocaleDateString("en-GB",
          { day: "numeric", month: "short" }) : "—"}</td>
      </tr>`).join("")}</tbody>
    </table></div>` : `<p class="mbr-empty">Nothing recorded.</p>`;
  overlay.style.display = "flex";
}

// Commentary boxes grow with the text — a 1:1 comment is rarely one line
function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = (el.scrollHeight + 2) + "px";
}

function wireAutoGrow(root) {
  root.querySelectorAll("textarea").forEach(t => {
    autoGrow(t);
    t.addEventListener("input", () => autoGrow(t));
  });
  root.querySelectorAll(".oto-add").forEach(b => b.addEventListener("click", () => addRow(b)));
}

function collect(name) {
  const byIdx = {};
  document.querySelectorAll(`.oto-in[data-name="${name}"]`).forEach(el => {
    const i = el.dataset.idx;
    (byIdx[i] = byIdx[i] || {})[el.dataset.key] = el.value.trim();
  });
  return Object.keys(byIdx).sort((a, b) => a - b).map(i => byIdx[i]);
}

async function savePerm() {
  const btn = document.getElementById("oto-save");
  btn.disabled = true; btn.textContent = "Saving…";
  const payload = {
    uid: document.getElementById("oto-person").value,
    week: document.getElementById("oto-week").value,
    template: currentTemplate,
    carried_review: collect("carried_review"),
    live_job_notes: collect("live_job_notes"),
    bd_existing: collect("bd_existing").filter(r => r.action || r.outcome),
    bd_new: collect("bd_new").filter(r => r.action || r.outcome),
    meetings_last_outcome: collect("meetings_last_outcome"),
    meetings_this_plan: collect("meetings_this_plan"),
    mbr_progress: collect("mbr_progress"),
    actions: collect("actions").filter(r => r.action),
  };
  ["resourcing_priority", "next_placement", "next_job",
   "priority_resourcing", "priority_bd", "support_needed"].forEach(k => {
    payload[k] = document.getElementById("f-" + k).value;
  });
  try {
    const resp = await fetch("/api/one-to-one", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await resp.json();
    if (!d.ok) throw new Error(d.error || "unknown error");
    document.getElementById("oto-saved").textContent =
      "Saved " + new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    alert("Could not save: " + e.message);
  }
  btn.disabled = false; btn.textContent = "Save 1:1";
}

function showError(msg) {
  document.getElementById("oto-content").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
}
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Templates ────────────────────────────────────────────────────────────────
// Which questions a team gets is decided server-side (shared/oto_templates.py);
// the page just renders the kind it is handed. Someone who can see more than
// one template — an admin — gets a switch in the toolbar.

let currentTemplate = "";

function templateSwitch(d) {
  const host = document.getElementById("oto-template-host");
  if (!host) return;
  currentTemplate = d.template.id;
  if ((d.templates || []).length < 2) { host.innerHTML = ""; return; }
  host.innerHTML = `<label class="mbr-ctl">Team <select id="oto-template">${
    d.templates.map(t => `<option value="${esc(t.id)}"${t.id === d.template.id ? " selected" : ""}>${esc(t.name)}</option>`).join("")
  }</select></label>`;
  document.getElementById("oto-template").addEventListener("change", (e) => {
    currentTemplate = e.target.value;
    // A different team means a different roster — rebuild the person list.
    document.getElementById("oto-person").innerHTML = "";
    load();
  });
}

function render(d) {
  templateSwitch(d);
  if (d.template && d.template.kind === "contract") renderContract(d);
  else renderPerm(d);
}

function wireCommon() {
  document.getElementById("oto-save").addEventListener("click", save);
  document.querySelectorAll(".oto-week, .oto-nav").forEach(b => b.addEventListener("click", () => {
    if (!b.dataset.week) return;
    document.getElementById("oto-week").value = b.dataset.week;
    load();
  }));
  // wireAutoGrow also binds the "+ Add row" buttons.
  wireAutoGrow(document.getElementById("oto-content"));
}

function save() {
  return (data && data.template && data.template.kind === "contract") ? saveContract() : savePerm();
}

// ── Contract USA ─────────────────────────────────────────────────────────────
// Jim Jeffers' desk (Sep 2026). Measured on contractors rather than deals:
// placements and the weekly margin they added, starters and finishers with
// attrition, current WNFI, then the judgement calls — committed business,
// placement chances, blocked roles and this week's client meetings.

const usd = (n) => "$" + Math.round(n || 0).toLocaleString("en-GB");
const num = (n) => (n == null ? "—" : (Number.isInteger(n) ? n : n.toFixed(2)));
const pct = (n) => (n == null ? "—" : n + "%");

function contractDrill(f, period) {
  const rows = f["detail_" + period] || [];
  return rows.length
    ? `<span class="oto-drill" data-fig="${esc(f.key)}" data-period="${period}">${
        f.money ? usd(f[period]) : num(f[period])}</span>`
    : (f.money ? usd(f[period]) : num(f[period]));
}

function showContractDetail(f, period) {
  const rows = f["detail_" + period] || [];
  const body = rows.map(r => `<tr>
      <td>${esc(r.client)}</td><td>${esc(r.role)}</td>
      <td class="num">${esc(r.start)}</td><td class="num">${esc(r.end)}</td>
      <td class="num">${usd(r.wnfi)}</td><td class="num dim">${r.share}</td></tr>`).join("");
  showModal(`${f.label} — ${period === "week" ? "this week" : "this month"}`,
    `<div class="table-wrap"><table>
      <thead><tr><th>Client</th><th>Role</th><th class="num">Start</th><th class="num">End</th>
        <th class="num">WNFI (share)</th><th class="num">Split</th></tr></thead>
      <tbody>${body}</tbody></table></div>`);
}

function renderContract(d) {
  const saved = d.saved || {};
  const byId = (name) => Object.fromEntries((saved[name] || []).map(r => [r.id, r]));
  const committed = byId("committed"), chances = byId("chances_week"), plans = byId("meeting_plans");

  const figRows = d.figures.map(f => `<tr>
      <td>${esc(f.label)}${f.note ? `<span class="oto-meta">${esc(f.note)}</span>` : ""}</td>
      <td class="num"><strong>${contractDrill(f, "week")}</strong></td>
      <td class="num dim">${contractDrill(f, "month")}</td>
    </tr>`).join("");

  const a = d.attrition || {};
  const jobs = d.live_jobs || [];
  const jobRow = (j, i, extra) => `<tr data-row="${extra.name}">
      <td>${esc(j.client)}${j.client_via_contact
        ? `<span class="oto-meta" title="The vacancy has a contact but no client account in Mercury — company taken from the contact">via contact · fix in Mercury</span>` : ""}</td>
      <td>${esc(j.job)}<span class="oto-meta">${j.grade ? "Grade " + esc(j.grade) + " · " : ""}${j.cvs_out} CVs out</span>
        <input type="hidden" class="oto-in" data-name="${extra.name}" data-key="id" data-idx="${i}" value="${esc(j.id)}"></td>
      ${extra.cells(i, j)}
    </tr>`;
  const ta = (name, key, i, val, ph) =>
    `<textarea rows="1" class="oto-in" data-name="${name}" data-key="${key}" data-idx="${i}"
       placeholder="${esc(ph || "")}">${S(val)}</textarea>`;
  const nin = (name, key, i, val, w) =>
    `<input type="number" class="oto-in oto-num" data-name="${name}" data-key="${key}" data-idx="${i}"
       value="${S(val)}" min="0" style="width:${w || 64}px">`;

  const committedRows = jobs.map((j, i) => jobRow(j, i, { name: "committed",
    cells: (i) => `<td>${ta("committed", "note", i, (committed[j.id] || {}).note, "What is committed, and where it stands")}</td>` })).join("");
  const chanceRows = jobs.map((j, i) => jobRow(j, i, { name: "chances_week",
    cells: (i) => {
      const c = chances[j.id] || {};
      return `<td class="num">${nin("chances_week", "week", i, c.week)}</td>
        <td class="num">${nin("chances_week", "month", i, c.month)}</td>
        <td class="num">${nin("chances_week", "pct", i, c.pct, 58)}<span class="dim"> %</span></td>
        <td>${ta("chances_week", "note", i, c.note, "Why, and what needs to happen")}</td>`;
    } })).join("");

  const jobOptions = (sel) => `<option value="">— pick a role —</option>` + jobs.map(j =>
    `<option value="${esc(j.id)}"${j.id === sel ? " selected" : ""}>${esc(j.client)} — ${esc(j.job)}${j.grade ? " (" + esc(j.grade) + ")" : ""}</option>`).join("");
  // Registered so "+ Add role" can build a matching row later.
  EDIT_TABLES["blocks"] = [
    { key: "role_id", render: (i, r) => `<select class="oto-in" data-name="blocks" data-key="role_id"
        data-idx="${i}">${jobOptions((r || {}).role_id)}</select>` },
    { key: "block", render: (i, r) => ta("blocks", "block", i, (r || {}).block, "What is blocking it") },
    { key: "steps", render: (i, r) => ta("blocks", "steps", i, (r || {}).steps, "Steps taken so far") },
  ];
  const blockRows = ((saved.blocks && saved.blocks.length) ? saved.blocks : [{}])
    .map((r, i) => editRow("blocks", r, EDIT_TABLES["blocks"], i)).join("");

  const meetingRows = (d.meetings || []).map((m, i) => `<tr>
      <td>${esc(m.contact || "")}<span class="oto-meta">${esc(m.job_title || "")}</span></td>
      <td>${esc(m.client || "")}</td>
      <td>${esc(m.subject || "")}<span class="oto-meta">${esc(m.when || "")}</span></td>
      <td><span class="oto-kind ${m.kind === "New business" ? "nb" : ""}">${esc(m.kind)}</span></td>
      <td>${ta("meeting_plans", "plan", i, (plans[m.id] || {}).plan, "Actions / expectations")}
        <input type="hidden" class="oto-in" data-name="meeting_plans" data-key="id" data-idx="${i}" value="${esc(m.id)}"></td>
    </tr>`).join("");

  const carried = d.carried_actions || [];
  const carriedRows = carried.map((a, i) => `<tr>
      <td class="oto-fixed">${S(a.action)}</td>
      <td class="oto-fixed dim">${S(a.owner)}</td>
    </tr>`).join("");

  document.getElementById("oto-content").innerHTML = quarterStrip(d) + `
    <section class="mbr-section">
      <h2>Key figures</h2>
      <div class="oto-two">
        <div>
          ${rowsTable([{label:""}, {label:"This week", num:true}, {label:esc(d.month_label), num:true}], figRows, "")}
          <p class="mbr-note">Click a figure to see the contractors behind it. Placements and WNFI are split-credited; starters and finishers count whole, and include anyone due to start or finish later this month.</p>
        </div>
        <div class="oto-cards">
          <div class="mbr-card"><span class="mbr-card-label">Current WNFI</span>
            <span class="mbr-card-value">${usd(d.current_wnfi)}</span>
            <span class="mbr-card-sub dim">${(d.live_contracts || []).length} live contractors, your share per week</span></div>
          <div class="mbr-card"><span class="mbr-card-label">Attrition — ${esc(d.month_label)}</span>
            <span class="mbr-card-value">${pct(a.month)}</span>
            <span class="mbr-card-sub dim">${a.month_finishers} finished of ${a.month_base} live at the start</span></div>
          <div class="mbr-card"><span class="mbr-card-label">Attrition — rolling 12 months</span>
            <span class="mbr-card-value">${pct(a.rolling_12m)}</span>
            <span class="mbr-card-sub dim">${a.rolling_finishers} finished of ${a.rolling_base} live at any point in the year</span></div>
        </div>
      </div>
    </section>

    <section class="mbr-section">
      <h2>Committed business being worked this week</h2>
      ${rowsTable([{label:"Client"}, {label:"Role"}, {label:"What is committed"}], committedRows,
        "No live vacancies — nothing to commit against.")}
    </section>

    <section class="mbr-section">
      <h2>Placement chances</h2>
      ${rowsTable([{label:"Client"}, {label:"Role"}, {label:"This week", num:true}, {label:"This month", num:true},
        {label:"Confidence", num:true}, {label:"Notes"}], chanceRows, "No live vacancies.")}
      <h3 class="perf-col-title" style="margin-top:14px">Other placement predictions</h3>
      <textarea rows="1" class="oto-in" id="f-chances_other" placeholder="Anything not tied to a live role above">${S(saved.chances_other)}</textarea>
    </section>

    <section class="mbr-section">
      <h2>Roles with potential blocks</h2>
      ${rowsTable([{label:"Role"}, {label:"The block"}, {label:"Steps taken so far"}], blockRows, "")}
      ${addRowButton("blocks", "Add role")}
    </section>

    <section class="mbr-section">
      <h2>Client meetings scheduled this week</h2>
      ${rowsTable([{label:"Who"}, {label:"Client"}, {label:"Meeting"}, {label:"Type"}, {label:"Actions / expectations"}],
        meetingRows, "No client meetings in Mercury for this week.")}
    </section>

    <section class="mbr-section">
      <h2>Last week's actions</h2>
      ${rowsTable([{label:"Action"}, {label:"Owner"}], carriedRows, "No actions carried forward.")}
    </section>

    <section class="mbr-section">
      <h2>Actions from this 1:1</h2>
      ${rowsTable([{label:"Action"}, {label:"Owner"}],
        editRows("actions", saved.actions, [{key:"action"}, {key:"owner"}]), "")}
      ${addRowButton("actions", "Add action")}
      <p class="mbr-note">These carry forward to next week.</p>
    </section>

    <div class="mbr-savebar">
      <button class="save-btn" id="oto-save">Save 1:1</button>
      <span class="mbr-saved-note" id="oto-saved"></span>
    </div>`;

  wireCommon();
  const figs = Object.fromEntries(d.figures.map(f => [f.key, f]));
  document.querySelectorAll(".oto-drill[data-fig]").forEach(el => el.addEventListener("click", () =>
    showContractDetail(figs[el.dataset.fig], el.dataset.period)));
}

async function saveContract() {
  const btn = document.getElementById("oto-save");
  btn.disabled = true; btn.textContent = "Saving…";
  const payload = {
    uid: document.getElementById("oto-person").value,
    week: document.getElementById("oto-week").value,
    template: currentTemplate,
    committed: collect("committed").filter(r => r.note),
    chances_week: collect("chances_week").filter(r => r.week || r.month || r.pct || r.note),
    chances_other: document.getElementById("f-chances_other").value,
    blocks: collect("blocks").filter(r => r.role_id || r.block || r.steps),
    meeting_plans: collect("meeting_plans").filter(r => r.plan),
    actions: collect("actions").filter(r => r.action),
  };
  try {
    const resp = await fetch("/api/one-to-one", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await resp.json();
    if (!d.ok) throw new Error(d.error || "unknown error");
    document.getElementById("oto-saved").textContent =
      "Saved " + new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    load();
  } catch (e) {
    alert("Could not save: " + e.message);
  }
  btn.disabled = false; btn.textContent = "Save 1:1";
}
