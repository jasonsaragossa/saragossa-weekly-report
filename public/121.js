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
  load();
})();

async function load() {
  const box = document.getElementById("oto-content");
  box.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading…</p></div>`;
  const uid = document.getElementById("oto-person").value;
  const week = document.getElementById("oto-week").value;
  try {
    const qs = (uid ? `uid=${encodeURIComponent(uid)}&` : "") + `week=${encodeURIComponent(week)}`;
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

function rowsTable(head, rows, empty) {
  return `<div class="table-wrap"><table><thead><tr>${head.map(h =>
    `<th${h.num ? ' class="num"' : ""}>${h.label}</th>`).join("")}</tr></thead>
    <tbody>${rows || `<tr><td colspan="${head.length}" class="mbr-empty">${empty}</td></tr>`}</tbody>
  </table></div>`;
}

// Repeating free-text tables (BD actions, meetings, actions) keep their rows in
// a JSON array so next week can carry them forward.
function editRows(name, saved, cols, seed) {
  const rows = (saved && saved.length ? saved : seed || [{}, {}, {}]);
  return rows.map((r, i) => `<tr data-row="${name}">
    ${cols.map(c => c.fixed
      ? `<td class="oto-fixed">${S(r[c.key])}</td>`
      : `<td><textarea rows="1" class="oto-in" data-name="${name}" data-key="${c.key}"
           data-idx="${i}">${S(r[c.key])}</textarea></td>`).join("")}
  </tr>`).join("");
}

function render(d) {
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

  // A quarter's worth of 1:1s on one strip — click a week to open it
  const q = d.quarter || { weeks: [], completed: [] };
  const done = new Set(q.completed || []);
  const strip = `
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
      <span class="oto-q-count">${(q.weeks || []).filter(w => done.has(w)).length} of ${(q.weeks || []).length} completed</span>
    </section>`;

  document.getElementById("oto-content").innerHTML = strip + `
    <section class="mbr-section">
      <h2>Performance vs last week's actions</h2>
      ${rowsTable([{label:"Action"},{label:"Achieved"},{label:"Commentary"}], carriedRows,
        "No actions carried forward — set some at the bottom and they'll appear here next week.")}
    </section>

    <section class="mbr-section">
      <h2>Key inputs</h2>
      ${rowsTable([{label:"Input"},{label:"Last week",num:true},{label:"Month so far",num:true}], inputRows, "")}
      <p class="mbr-note">Pulled from Mercury — read only.</p>
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
      <h3 class="perf-col-title" style="margin-top:14px">New client</h3>
      ${rowsTable([{label:"Action last week"},{label:"Outcome"}],
        editRows("bd_new", saved.bd_new, [{key:"action"},{key:"outcome"}]), "")}
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
      <p class="mbr-note">These carry forward to next week's "performance vs last week's actions".</p>
    </section>

    <div class="mbr-savebar">
      <button class="save-btn" id="oto-save">Save 1:1</button>
      <span class="mbr-saved-note" id="oto-saved"></span>
    </div>`;

  document.getElementById("oto-save").addEventListener("click", save);
  document.querySelectorAll(".oto-week, .oto-nav").forEach(b => b.addEventListener("click", () => {
    if (!b.dataset.week) return;
    document.getElementById("oto-week").value = b.dataset.week;
    load();
  }));
  wireAutoGrow(document.getElementById("oto-content"));
  document.querySelectorAll(".oto-drill").forEach(el => el.addEventListener("click", () =>
    showDetail(el.dataset.label, el.dataset.period,
               ((data.detail || {})[el.dataset.period] || {})[el.dataset.key] || [])));
}

// Every key input drills down to the records behind the count
function showDetail(label, period, rows) {
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
}

function collect(name) {
  const byIdx = {};
  document.querySelectorAll(`.oto-in[data-name="${name}"]`).forEach(el => {
    const i = el.dataset.idx;
    (byIdx[i] = byIdx[i] || {})[el.dataset.key] = el.value.trim();
  });
  return Object.keys(byIdx).sort((a, b) => a - b).map(i => byIdx[i]);
}

async function save() {
  const btn = document.getElementById("oto-save");
  btn.disabled = true; btn.textContent = "Saving…";
  const payload = {
    uid: document.getElementById("oto-person").value,
    week: document.getElementById("oto-week").value,
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
