/**
 * MBR (beta) — monthly business review.
 *
 * Derived metrics are read-only. Judgement fields are always typed. Last
 * month's actions are carried forward with a status, which is the whole point:
 * the form opens with what you said you would do.
 */

let mbrData = null;
let people  = [];

(async () => {
  try {
    const info = await (await fetch("/.auth/me")).json();
    if (info?.clientPrincipal) document.getElementById("admin-link").style.display = "inline";
  } catch (_) {}

  const now = new Date();
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  document.getElementById("mbr-month").value =
    `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`;

  try {
    const resp = await fetch("/api/mbr-people");
    if (resp.status === 401) { window.location.href = "/.auth/login/aad"; return; }
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "unknown error");
    people = data.people || [];
  } catch (e) {
    return showError(`Could not load people: ${e.message}`);
  }

  if (!people.length) {
    return showError("You don't have an MBR yet — no Mercury consultant record is linked to your account.");
  }

  const sel = document.getElementById("mbr-person");
  sel.innerHTML = people.map(p => `<option value="${esc(p.uid)}">${esc(p.name)}</option>`).join("");
  sel.addEventListener("change", load);
  document.getElementById("mbr-month").addEventListener("change", load);
  load();
})();


async function load() {
  const uid   = document.getElementById("mbr-person").value;
  const [y, m] = document.getElementById("mbr-month").value.split("-");
  const box = document.getElementById("mbr-content");
  box.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Building the numbers…</p></div>`;
  setStatus("");
  try {
    const resp = await fetch(`/api/mbr?uid=${encodeURIComponent(uid)}&year=${y}&month=${m}`);
    if (resp.status === 403) return showError("You can't open this person's MBR.");
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "unknown error");
    mbrData = data;
    render(data);
  } catch (e) {
    showError(`Could not load the MBR: ${e.message}`);
  }
}


function fmtVal(m) {
  if (m.value === null || m.value === undefined) return "—";
  if (m.format === "money")   return "£" + Math.round(m.value).toLocaleString("en-GB");
  if (m.format === "percent") return m.value + "%";
  if (m.format === "ratio")   return m.value.toFixed(2);
  return m.value.toLocaleString("en-GB");
}

function fmtPlain(m, v) {
  if (v === null || v === undefined) return "—";
  if (m.format === "money")   return "£" + Math.round(v).toLocaleString("en-GB");
  if (m.format === "percent") return v + "%";
  if (m.format === "ratio")   return Number(v).toFixed(2);
  return Number(v).toLocaleString("en-GB");
}


function render(d) {
  const flagged = new Set(d.flagged || []);
  const promptBy = {};
  (d.prompts || []).forEach(p => { promptBy[p.key] = p; });

  // Metrics grouped by family
  const families = [...new Set(d.metrics.map(m => m.family))];
  let metricsHtml = "";
  for (const fam of families) {
    metricsHtml += `<tr class="mbr-family"><td colspan="6">${esc(fam)}</td></tr>`;
    for (const m of d.metrics.filter(x => x.family === fam)) {
      const good = m.change_pct === null ? null
        : (m.direction === "up" ? m.change_pct >= 0 : m.change_pct <= 0);
      const cls = m.change_pct === null ? "" : (good ? " pos" : " neg");
      const pct = m.target ? Math.round((m.value || 0) / m.target * 100) : null;
      const pr = promptBy[m.key];
      metricsHtml += `<tr class="${flagged.has(m.key) ? "mbr-flagged" : ""}">
        <td><span class="mbr-metric-name" title="${esc(m.definition)}">${esc(m.name)}</span>
            ${flagged.has(m.key) ? `<span class="mbr-flag">flagged</span>` : ""}</td>
        <td class="num"><strong>${fmtVal(m)}</strong></td>
        <td class="num dim">${fmtPlain(m, m.previous)}</td>
        <td class="num${cls}">${m.change_pct === null ? "—" : (m.change_pct > 0 ? "+" : "") + m.change_pct + "%"}</td>
        <td class="num dim">${fmtPlain(m, m.qtd)}</td>
        <td class="num">${m.target ? `${fmtPlain(m, m.target)} <span class="mbr-target-pct${pct >= 100 ? " pos" : pct >= 80 ? "" : " neg"}">${pct}%</span>` : "—"}</td>
      </tr>`;
      if (pr) {
        metricsHtml += `<tr class="mbr-prompt-row"><td colspan="6">
          <span class="mbr-prompt-q">${esc(pr.question)}</span>
          <span class="mbr-prompt-why">${esc(pr.flag_reason)}</span>
          <textarea class="mbr-prompt-answer" data-key="${esc(m.key)}" rows="2"
            placeholder="Your answer — this is the bit that matters">${esc((d.saved?.commentary || {})[m.key] || "")}</textarea>
        </td></tr>`;
      }
    }
  }

  const saved = d.saved || {};
  const carried = d.carried_actions || [];
  const actions = (saved.actions && saved.actions.length) ? saved.actions : [];

  const carriedHtml = carried.length ? carried.map((a, i) => `
    <tr>
      <td>${esc(a.text || "")}</td>
      <td><select class="carry-status" data-idx="${i}">
        ${["Not started", "In progress", "Done", "Dropped"].map(s =>
          `<option ${a.status === s ? "selected" : ""}>${s}</option>`).join("")}
      </select></td>
    </tr>`).join("")
    : `<tr><td colspan="2" class="mbr-empty">Nothing carried forward — this is the first MBR with actions.</td></tr>`;

  const summary = d.summary;
  const candidates = summary ? `
    <div class="mbr-candidates">
      <div><span class="mbr-cand-head">Suggested positives</span>
        <ul>${(summary.good || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
      <div><span class="mbr-cand-head">Suggested areas to impact</span>
        <ul>${(summary.improve || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
    </div>
    <p class="mbr-note">Candidates only — pick the three that are actually true and say why.</p>` : "";

  document.getElementById("mbr-content").innerHTML = `
    <section class="mbr-section">
      <h2>Last month's actions</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Action</th><th style="width:160px">Status</th></tr></thead>
        <tbody>${carriedHtml}</tbody>
      </table></div>
    </section>

    <section class="mbr-section">
      <h2>The numbers <span class="mbr-src">${d.source === "claude" ? "prompts by Claude"
        : d.source === "template" ? "template prompts — no API key set" : ""}</span></h2>
      <div class="table-wrap"><table class="mbr-metrics">
        <thead><tr><th>Metric</th><th class="num">This month</th><th class="num">Last month</th>
          <th class="num">Change</th><th class="num">QTD</th><th class="num">Target</th></tr></thead>
        <tbody>${metricsHtml}</tbody>
      </table></div>
    </section>

    <section class="mbr-section">
      <h2>Your judgement</h2>
      ${candidates}
      <label class="mbr-field">Three things that went well
        <textarea id="f-positives" rows="3">${esc(saved.positives || "")}</textarea></label>
      <label class="mbr-field">Three areas to impact
        <textarea id="f-improve" rows="3">${esc(saved.improve || "")}</textarea></label>
      <label class="mbr-field">Aspirations (quarter / year)
        <textarea id="f-aspirations" rows="2">${esc(saved.aspirations || "")}</textarea></label>
      <label class="mbr-field">Support required
        <textarea id="f-support" rows="2">${esc(saved.support || "")}</textarea></label>
    </section>

    <section class="mbr-section">
      <h2>Actions from this meeting</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Action</th><th style="width:160px">Status</th><th style="width:40px"></th></tr></thead>
        <tbody id="action-rows">
          ${actions.map((a, i) => actionRow(a, i)).join("")}
        </tbody>
      </table></div>
      <button class="save-btn" id="add-action" style="margin-top:8px">+ Add action</button>
    </section>

    <div class="mbr-savebar">
      <button class="save-btn" id="mbr-save">Save MBR</button>
      <span class="mbr-saved-note" id="mbr-saved-note"></span>
    </div>`;

  if (!actions.length) addActionRow();
  document.getElementById("add-action").addEventListener("click", (e) => { e.preventDefault(); addActionRow(); });
  document.getElementById("mbr-save").addEventListener("click", save);
  document.getElementById("mbr-content").addEventListener("click", (e) => {
    const rm = e.target.closest(".action-remove");
    if (rm) rm.closest("tr").remove();
  });
}

function actionRow(a, i) {
  return `<tr>
    <td><input type="text" class="action-text" value="${esc(a.text || "")}" placeholder="What will you do?"></td>
    <td><select class="action-status">
      ${["Not started", "In progress", "Done", "Dropped"].map(s =>
        `<option ${a.status === s ? "selected" : ""}>${s}</option>`).join("")}
    </select></td>
    <td><button class="action-remove" title="Remove">✕</button></td>
  </tr>`;
}

function addActionRow() {
  const tb = document.getElementById("action-rows");
  const tr = document.createElement("tr");
  tr.innerHTML = actionRow({}, tb.children.length).replace(/^<tr>|<\/tr>$/g, "");
  tb.appendChild(tr);
}

async function save() {
  const btn = document.getElementById("mbr-save");
  const uid = document.getElementById("mbr-person").value;
  const [y, m] = document.getElementById("mbr-month").value.split("-");

  const commentary = {};
  document.querySelectorAll(".mbr-prompt-answer").forEach(t => {
    if (t.value.trim()) commentary[t.dataset.key] = t.value.trim();
  });
  const actions = [...document.querySelectorAll("#action-rows tr")].map(tr => ({
    text:   tr.querySelector(".action-text").value.trim(),
    status: tr.querySelector(".action-status").value,
  })).filter(a => a.text);

  // Carried actions keep their updated status so next month sees the outcome
  const carried = (mbrData.carried_actions || []).map((a, i) => {
    const sel = document.querySelector(`.carry-status[data-idx="${i}"]`);
    return { ...a, status: sel ? sel.value : a.status };
  });

  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const resp = await fetch("/api/mbr", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        uid, year: Number(y), month: Number(m),
        positives:   document.getElementById("f-positives").value,
        improve:     document.getElementById("f-improve").value,
        aspirations: document.getElementById("f-aspirations").value,
        support:     document.getElementById("f-support").value,
        commentary, actions, carried_reviewed: carried,
      }),
    });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "unknown error");
    document.getElementById("mbr-saved-note").textContent =
      "Saved " + new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    alert("Could not save: " + e.message);
  }
  btn.disabled = false; btn.textContent = "Save MBR";
}

function setStatus(t) { document.getElementById("mbr-status").textContent = t; }
function showError(msg) {
  document.getElementById("mbr-content").innerHTML =
    `<div class="error-state"><p>⚠ ${esc(msg)}</p></div>`;
}
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
