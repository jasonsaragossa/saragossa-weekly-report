/**
 * Settings page — manage user overrides (team, visibility).
 * Admin-only: API returns 403 for non-admins.
 */

const TERRITORY_ORDER = [
  "Bristol", "London", "Chicago", "New York",
  "London Contract", "Chicago Contract", "Cameron Scott",
];

const CONTRACT_TERRITORIES = new Set(["London Contract", "Chicago Contract"]);

const TEAMS_BY_TERRITORY = {
  "Bristol":          ["Team Batt", "Team Charlie", "Team Sion", "Team Harry W"],
  "London":           ["Team Data & Cyber", "Team Data and Cyber", "Team Snoz"],
  "Chicago":          ["Team JD", "Team Matty", "Team Adam", "Team Adam W"],
  "New York":         [],
  "London Contract":  [],
  "Chicago Contract": [],
};

const FINANCE_TEAM_NAME = "Bristol Finance and Compliance";

let allUsers = [];
let allActiveUsers = [];   // every enabled Mercury user (for the access picker)
let financeMemberUids = []; // uids in the Finance & Compliance team
let overrideMap = {}; // uid → override record
let nbThresholds = {}; // NB-uplift qualification thresholds
let manualNbClients = {}; // uid → [{id, name, rowid}] admin-added NB clients
let nbSelectedUid = "";   // consultant selected in the NB-client section

(async () => {
  let data;
  try {
    const resp = await fetch("/api/settings");
    if (resp.status === 401) {
      window.location.href = "/.auth/login/aad?post_login_redirect_uri=" + encodeURIComponent(window.location.pathname);
      return;
    }
    if (resp.status === 403) {
      document.getElementById("settings-content").innerHTML =
        `<div class="error-state"><p>⚠ Admin access required.</p></div>`;
      return;
    }
    data = await resp.json();
  } catch (e) {
    document.getElementById("settings-content").innerHTML =
      `<div class="error-state"><p>⚠ Could not load settings.</p></div>`;
    return;
  }

  allUsers = data.users || [];
  allActiveUsers = data.all_active_users || [];
  financeMemberUids = data.finance_member_uids || [];
  nbThresholds = data.nb_thresholds || {};
  manualNbClients = data.manual_nb_clients || {};
  (data.overrides || []).forEach(o => { overrideMap[o.crbb7_userid] = o; });

  renderSettings();
})();


function renderSettings() {
  const container = document.getElementById("settings-content");
  container.innerHTML = "";

  // Analytics access management (top of page)
  container.appendChild(buildAccessSection());

  // NB-uplift qualification thresholds
  container.appendChild(buildNbThresholdsSection());

  // Manual NB-client additions
  container.appendChild(buildNbClientSection());

  // Group users by territory
  const byTerritory = {};
  TERRITORY_ORDER.forEach(t => { byTerritory[t] = []; });
  allUsers.forEach(u => {
    if (byTerritory[u.territory]) byTerritory[u.territory].push(u);
  });

  for (const territory of TERRITORY_ORDER) {
    const users = byTerritory[territory];
    if (!users.length) continue;

    const section = document.createElement("div");
    section.className = "settings-section";
    section.innerHTML = `<h2 class="settings-territory">${territory}</h2>`;

    const isContract = CONTRACT_TERRITORIES.has(territory);
    const isUsPerm   = territory === "Chicago" || territory === "New York";
    const table = document.createElement("table");
    table.className = "settings-table";
    table.innerHTML = `<thead><tr>
      <th>Name</th>
      <th>Role (Mercury)</th>
      <th>Team</th>
      <th>Hidden</th>
      <th>Date Joined</th>
      <th>Joined Team</th>
      <th>Prev Team</th>
      <th>Prev Territory</th>
      ${isContract ? "" : "<th>Annual Target</th>"}
      ${isUsPerm ? "<th>Team Lead</th><th>Job Title (Q1–Q4)</th>" : ""}
      <th></th>
    </tr></thead>`;

    const tbody = document.createElement("tbody");
    users.forEach(u => tbody.appendChild(buildUserRow(u, territory)));
    table.appendChild(tbody);

    const wrap = document.createElement("div");
    wrap.className = "settings-table-wrap";
    wrap.appendChild(table);
    section.appendChild(wrap);
    container.appendChild(section);
  }
}


// ── NB-uplift qualification thresholds ─────────────────────────────────────────

function buildNbThresholdsSection() {
  const section = document.createElement("div");
  section.className = "settings-section";

  const v = (k) => (nbThresholds[k] != null ? nbThresholds[k] : "");
  section.innerHTML = `
    <h2 class="settings-territory">New-Business Uplift Thresholds</h2>
    <p class="settings-desc">A new-business placement only earns the CRO the 50% uplift if it clears these.
      Applied in the placement's own currency (£/$).</p>
    <div class="nb-threshold-grid">
      <label class="nb-th"><span>Perm — min fee %</span>
        <input type="number" step="0.5" min="0" class="contract-input" data-field="perm_fee_pct" value="${esc(v("perm_fee_pct"))}"></label>
      <label class="nb-th"><span>Perm — min deal value</span>
        <input type="number" step="500" min="0" class="contract-input" data-field="perm_min_value" value="${esc(v("perm_min_value"))}"></label>
      <label class="nb-th"><span>Contract — min margin %</span>
        <input type="number" step="0.5" min="0" class="contract-input" data-field="contract_margin_pct" value="${esc(v("contract_margin_pct"))}"></label>
      <label class="nb-th"><span>Contract — min margin value</span>
        <input type="number" step="5" min="0" class="contract-input" data-field="contract_min_margin" value="${esc(v("contract_min_margin"))}"></label>
    </div>
    <button class="save-btn" id="nb-th-save">Save thresholds</button>
  `;

  section.querySelector("#nb-th-save").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const payload = {};
    section.querySelectorAll(".nb-threshold-grid input").forEach(inp => {
      const val = inp.value.trim();
      if (val !== "") payload[inp.dataset.field] = parseFloat(val);
    });
    btn.textContent = "Saving…"; btn.disabled = true;
    try {
      const resp = await fetch("/api/nb-thresholds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (data.ok) {
        nbThresholds = data.nb_thresholds || nbThresholds;
        btn.textContent = "Saved ✓";
        setTimeout(() => { btn.textContent = "Save thresholds"; btn.disabled = false; }, 2000);
      } else {
        alert("Could not save: " + (data.error || "unknown error"));
        btn.textContent = "Save thresholds"; btn.disabled = false;
      }
    } catch (err) {
      alert("Could not save: " + err.message);
      btn.textContent = "Save thresholds"; btn.disabled = false;
    }
  });

  return section;
}


// ── Manual NB-client additions ─────────────────────────────────────────────────

function rerenderNbClient() {
  const old = document.getElementById("nbclient-section");
  if (old) old.replaceWith(buildNbClientSection());
}

function buildNbClientSection() {
  const section = document.createElement("div");
  section.className = "settings-section";
  section.id = "nbclient-section";

  const consultantOpts = [...allUsers]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(u => `<option value="${esc(u.uid)}" ${u.uid === nbSelectedUid ? "selected" : ""}>${esc(u.name)}</option>`)
    .join("");

  const current = manualNbClients[nbSelectedUid] || [];
  const listHtml = !nbSelectedUid
    ? `<p class="access-empty">Select a consultant to manage their added clients.</p>`
    : (current.length
        ? `<ul class="access-list">${current.map(c => `<li class="access-row">
             <span>${esc(c.name)}</span>
             <button class="clear-btn nbclient-remove" data-rowid="${esc(c.rowid)}">Remove</button>
           </li>`).join("")}</ul>`
        : `<p class="access-empty">No manually added clients.</p>`);

  section.innerHTML = `
    <h2 class="settings-territory">NB Client Additions</h2>
    <p class="settings-desc">Manually credit a consultant with a new-business client (e.g. a contract that won't auto-count).
      Added to their NB-client count and drill-down.</p>
    <div class="nbclient-controls">
      <select class="team-select" id="nbclient-consultant"><option value="">— Select consultant —</option>${consultantOpts}</select>
    </div>
    <div id="nbclient-current">${listHtml}</div>
    ${nbSelectedUid ? `<div class="nbclient-add">
      <input type="text" class="contract-input" id="nbclient-search" placeholder="Search client name…">
      <button class="save-btn" id="nbclient-searchbtn">Search</button>
      <select class="team-select" id="nbclient-results"><option value="">— search results —</option></select>
      <button class="save-btn" id="nbclient-addbtn">Add client</button>
    </div>
    <div id="nbclient-alertstate"><p class="access-empty">Loading NB clients…</p></div>` : ""}
  `;

  section.querySelector("#nbclient-consultant").addEventListener("change", (e) => {
    nbSelectedUid = e.target.value;
    rerenderNbClient();
  });

  const searchBtn = section.querySelector("#nbclient-searchbtn");
  if (searchBtn) searchBtn.addEventListener("click", async () => {
    const q = section.querySelector("#nbclient-search").value.trim();
    const results = section.querySelector("#nbclient-results");
    if (q.length < 2) { results.innerHTML = `<option value="">type at least 2 characters</option>`; return; }
    searchBtn.textContent = "…"; searchBtn.disabled = true;
    try {
      const resp = await fetch("/api/clients?q=" + encodeURIComponent(q));
      const data = await resp.json();
      const rs = (data.results || []);
      results.innerHTML = rs.length
        ? rs.map(r => `<option value="${esc(r.id)}" data-name="${esc(r.name)}">${esc(r.name)}</option>`).join("")
        : `<option value="">No matches</option>`;
    } catch (_) {
      results.innerHTML = `<option value="">search failed</option>`;
    }
    searchBtn.textContent = "Search"; searchBtn.disabled = false;
  });

  const addBtn = section.querySelector("#nbclient-addbtn");
  if (addBtn) addBtn.addEventListener("click", async () => {
    const sel = section.querySelector("#nbclient-results");
    const opt = sel.options[sel.selectedIndex];
    if (!opt || !opt.value) return;
    addBtn.textContent = "Adding…"; addBtn.disabled = true;
    try {
      const resp = await fetch("/api/nb-clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userid: nbSelectedUid, client_id: opt.value, client_name: opt.dataset.name }),
      });
      const data = await resp.json();
      if (data.ok) { manualNbClients = data.manual_nb_clients || manualNbClients; rerenderNbClient(); }
      else { alert("Could not add: " + (data.error || "unknown error")); addBtn.textContent = "Add client"; addBtn.disabled = false; }
    } catch (e) { alert("Could not add: " + e.message); addBtn.textContent = "Add client"; addBtn.disabled = false; }
  });

  section.querySelectorAll(".nbclient-remove").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const resp = await fetch("/api/nb-clients/" + btn.dataset.rowid, { method: "DELETE" });
      const data = await resp.json();
      if (data.ok) { manualNbClients = data.manual_nb_clients || {}; rerenderNbClient(); }
      else { alert("Could not remove: " + (data.error || "unknown error")); btn.disabled = false; }
    } catch (e) { alert("Could not remove: " + e.message); btn.disabled = false; }
  }));

  if (nbSelectedUid) loadNbAlertState(section);

  return section;
}

async function loadNbAlertState(section) {
  const box = section.querySelector("#nbclient-alertstate");
  if (!box) return;
  try {
    const resp = await fetch("/api/nb-alert-clients?uid=" + encodeURIComponent(nbSelectedUid));
    const data = await resp.json();
    if (!data.ok) { box.innerHTML = `<p class="access-empty">Could not load alert status.</p>`; return; }
    const clients = data.clients || [];
    if (!clients.length) {
      box.innerHTML = `<p class="access-empty">No NB clients in the rolling 12 months.</p>`;
      return;
    }
    box.innerHTML = `
      <h3 class="access-subhead">Alert status — already counted</h3>
      <p class="settings-desc">Tick any client that was part of a previous 5-client alert (or recognised before
        the alerts existed). Ticked clients don't count toward the consultant's next alert.</p>
      <ul class="access-list">` + clients.map(c => `
        <li class="access-row"><span>${esc(c.name)}</span>
          <label class="toggle">
            <input type="checkbox" class="nbalert-consumed" data-id="${esc(c.id)}" ${c.consumed ? "checked" : ""}>
            <span class="toggle-label">Already counted</span>
          </label></li>`).join("") + `
      </ul>
      <button class="save-btn" id="nbalert-save">Save alert status</button>`;
    box.querySelector("#nbalert-save").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const ids = [...box.querySelectorAll(".nbalert-consumed:checked")].map(cb => cb.dataset.id);
      btn.textContent = "Saving…"; btn.disabled = true;
      try {
        const r2 = await fetch("/api/nb-alert-clients", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userid: nbSelectedUid, consumed_client_ids: ids }),
        });
        const d2 = await r2.json();
        if (d2.ok) {
          btn.textContent = "Saved ✓";
          setTimeout(() => { btn.textContent = "Save alert status"; btn.disabled = false; }, 2000);
        } else {
          alert("Could not save: " + (d2.error || "unknown error"));
          btn.textContent = "Save alert status"; btn.disabled = false;
        }
      } catch (err) {
        alert("Could not save: " + err.message);
        btn.textContent = "Save alert status"; btn.disabled = false;
      }
    });
  } catch (_) {
    box.innerHTML = `<p class="access-empty">Could not load alert status.</p>`;
  }
}


// ── Analytics access management ────────────────────────────────────────────────

function buildAccessSection() {
  const section = document.createElement("div");
  section.className = "settings-section";
  section.id = "access-section";

  const usersById = {};
  allActiveUsers.forEach(u => { usersById[u.uid] = u; });
  const nameOf = (uid) => (usersById[uid] || {}).name || uid;
  const financeSet = new Set(financeMemberUids);

  // Finance team — allowed by default, individually revocable.
  // Only active users are shown; disabled accounts can't have access anyway.
  const financeRows = financeMemberUids
    .filter(uid => usersById[uid])
    .map(uid => ({ uid, name: nameOf(uid), allowed: (overrideMap[uid] || {}).crbb7_canaccessanalytics !== false }))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(m => `<li class="access-row" data-uid="${esc(m.uid)}">
        <span>${esc(m.name)}</span>
        <label class="toggle">
          <input type="checkbox" class="access-finance-toggle" data-uid="${esc(m.uid)}" ${m.allowed ? "checked" : ""}>
          <span class="toggle-label">Can see Analytics</span>
        </label>
      </li>`).join("");

  // Others explicitly granted (not in the finance team).
  const granted = Object.values(overrideMap)
    .filter(o => o.crbb7_canaccessanalytics === true && !financeSet.has(o.crbb7_userid))
    .map(o => ({ uid: o.crbb7_userid, name: nameOf(o.crbb7_userid) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const grantedSet = new Set(granted.map(g => g.uid));

  const grantedHtml = granted.length
    ? granted.map(g => `<li class="access-row" data-uid="${esc(g.uid)}">
         <span>${esc(g.name)}</span>
         <button class="clear-btn access-remove" data-uid="${esc(g.uid)}">Remove</button>
       </li>`).join("")
    : `<li class="access-empty">No extra users granted yet.</li>`;

  const addOptions = allActiveUsers
    .filter(u => !financeSet.has(u.uid) && !grantedSet.has(u.uid))
    .map(u => `<option value="${esc(u.uid)}" data-name="${esc(u.name)}">${esc(u.name)}</option>`)
    .join("");

  section.innerHTML = `
    <h2 class="settings-territory">Analytics Access</h2>
    <p class="settings-desc">Directors always have access. Toggle individual “${esc(FINANCE_TEAM_NAME)}” members below, and grant access to anyone else.</p>
    <h3 class="access-subhead">${esc(FINANCE_TEAM_NAME)}</h3>
    <ul class="access-list">${financeRows || `<li class="access-empty">No team members found.</li>`}</ul>
    <h3 class="access-subhead">Others with access</h3>
    <ul class="access-list">${grantedHtml}</ul>
    <div class="access-add">
      <select class="team-select" id="access-add-select">${addOptions}</select>
      <button class="save-btn" id="access-add-btn">Grant access</button>
    </div>
  `;

  section.querySelector("#access-add-btn").addEventListener("click", () => {
    const sel = section.querySelector("#access-add-select");
    const uid = sel.value;
    if (!uid) return;
    const name = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].dataset.name : "";
    setAnalyticsAccess(uid, name, true);
  });
  section.querySelectorAll(".access-remove").forEach(btn => {
    btn.addEventListener("click", () => setAnalyticsAccess(btn.dataset.uid, "", false));
  });
  section.querySelectorAll(".access-finance-toggle").forEach(cb => {
    cb.addEventListener("change", () => setAnalyticsAccess(cb.dataset.uid, "", cb.checked));
  });

  return section;
}

async function setAnalyticsAccess(uid, name, grant) {
  const section = document.getElementById("access-section");
  const addBtn = section ? section.querySelector("#access-add-btn") : null;
  if (addBtn) { addBtn.textContent = "Saving…"; addBtn.disabled = true; }
  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userid: uid, name, can_access_analytics: grant }),
    });
    const data = await resp.json();
    if (data.ok) {
      overrideMap[uid] = { ...(overrideMap[uid] || {}), ...data.override };
      if (section) section.replaceWith(buildAccessSection());
    } else {
      alert("Could not update access: " + (data.error || "unknown error"));
      if (addBtn) { addBtn.textContent = "Grant access"; addBtn.disabled = false; }
    }
  } catch (e) {
    alert("Could not update access: " + e.message);
    if (addBtn) { addBtn.textContent = "Grant access"; addBtn.disabled = false; }
  }
}

function buildUserRow(u, territory) {
  const ov = overrideMap[u.uid] || {};
  const isHidden     = ov.crbb7_ishidden || false;
  const currentTeam  = ov.crbb7_team || "";
  const teams        = TEAMS_BY_TERRITORY[territory] || [];
  const isContract   = CONTRACT_TERRITORIES.has(territory);
  const isUsPerm     = territory === "Chicago" || territory === "New York";

  // Date / history fields — Dataverse Date Only comes back as "2024-10-01" or "2024-10-01T00:00:00Z"
  const dateJoined     = ov.crbb7_datejoined     ? ov.crbb7_datejoined.split("T")[0]     : "";
  const dateJoinedTeam = ov.crbb7_datejoinedteam ? ov.crbb7_datejoinedteam.split("T")[0] : "";
  const prevTeam       = ov.crbb7_previousteam       || "";
  const prevTerritory  = ov.crbb7_previousterritory  || "";

  const tr = document.createElement("tr");
  if (isHidden) tr.classList.add("hidden-user");

  const teamOptions = ["", ...teams]
    .map(t => `<option value="${esc(t)}" ${t === currentTeam ? "selected" : ""}>${t || "— Mercury default —"}</option>`)
    .join("");

  const prevTerritoryOptions = ["", "Bristol", "London", "Chicago", "New York", "London Contract", "Chicago Contract"]
    .map(t => `<option value="${esc(t)}" ${t === prevTerritory ? "selected" : ""}>${t || "—"}</option>`)
    .join("");

  const historyFields = `
    <td><input type="date" class="date-input" data-field="date_joined"
         value="${esc(dateJoined)}"></td>
    <td><input type="date" class="date-input" data-field="date_joined_team"
         value="${esc(dateJoinedTeam)}"></td>
    <td><input type="text" class="contract-input prev-team-input" data-field="previous_team"
         placeholder="e.g. Team Batt" value="${esc(prevTeam)}"></td>
    <td><select class="team-select" data-field="previous_territory">
         ${prevTerritoryOptions}
        </select></td>
  `;

  // Contract figures moved to the Analytics "Contract Entry" monthly ledger
  const targetVal = ov.crbb7_target != null ? ov.crbb7_target : "";
  const sym = (territory === "Chicago" || territory === "New York" || territory === "Chicago Contract") ? "$" : "£";

  // HPB controls (US perm only): Team Lead toggle + grade selector.
  // Team Lead defaults to the title when never explicitly set.
  const tlOv       = ov.crbb7_isteamlead;
  const isTeamLead = tlOv === true || (tlOv == null && /team lead/i.test(u.role || ""));
  const HPB_GRADE_CHOICES = [
    ["", "Auto (Bob)"],
    ["none", "Doesn't qualify"],
    ["associate", "Associate Consultant"],
    ["consultant", "Consultant"],
    ["senior", "Senior Consultant"],
    ["principal", "Principal Consultant"],
    ["eic", "EIC"],
    ["sales_leader", "Sales Leader"],
    ["team_lead", "Team Lead"],
  ];
  const quarterGradeSelect = (q) => {
    const val = ov["crbb7_hpbgradeq" + q] || "";
    const opts = HPB_GRADE_CHOICES
      .map(([v, l]) => `<option value="${v}" ${val === v ? "selected" : ""}>${l}</option>`)
      .join("");
    return `<label class="hpb-q"><span>Q${q}</span>
      <select class="hpb-grade-select" data-field="hpb_grade_q${q}">${opts}</select></label>`;
  };
  const hpbFields = isUsPerm ? `
    <td style="text-align:center">
      <input type="checkbox" class="hpb-teamlead-toggle" data-field="is_team_lead" ${isTeamLead ? "checked" : ""}>
    </td>
    <td><div class="hpb-grade-grid">${["1","2","3","4"].map(quarterGradeSelect).join("")}</div></td>
  ` : "";

  tr.innerHTML = `
    <td>${esc(u.name)}</td>
    <td class="role-cell">${esc(u.role)}</td>
    <td>
      <select class="team-select" data-uid="${esc(u.uid)}">
        ${teamOptions}
      </select>
    </td>
    <td>
      <label class="toggle">
        <input type="checkbox" class="hidden-toggle" data-uid="${esc(u.uid)}" ${isHidden ? "checked" : ""}>
        <span class="toggle-label">Hide</span>
      </label>
    </td>
    ${historyFields}
    ${isContract ? "" : `<td>
      <input type="number" class="contract-input target-input" data-field="target"
             placeholder="${sym}0" step="1000" min="0"
             value="${targetVal}">
    </td>`}
    ${hpbFields}
    <td>
      <button class="save-btn" data-uid="${esc(u.uid)}"
              data-name="${esc(u.name)}"
              data-territory="${esc(territory)}">
        Save
      </button>
      ${ov.crbb7_useroverrideid
        ? `<button class="clear-btn" data-id="${esc(ov.crbb7_useroverrideid)}" data-uid="${esc(u.uid)}">Clear</button>`
        : ""}
    </td>
  `;

  // Save
  tr.querySelector(".save-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const uid = btn.dataset.uid;
    const team = tr.querySelector(".team-select").value;
    const hidden = tr.querySelector(".hidden-toggle").checked;
    const contractData = {};
    tr.querySelectorAll(".contract-input:not(.prev-team-input)").forEach(inp => {
      const v = inp.value.trim();
      contractData[inp.dataset.field] = v !== "" ? parseFloat(v) : null;
    });
    const moveData = {
      date_joined:        tr.querySelector("[data-field=date_joined]").value        || null,
      date_joined_team:   tr.querySelector("[data-field=date_joined_team]").value   || null,
      previous_team:      tr.querySelector("[data-field=previous_team]").value      || null,
      previous_territory: tr.querySelector("[data-field=previous_territory]").value || null,
    };
    const hpbData = {};
    const tlToggle = tr.querySelector(".hpb-teamlead-toggle");
    if (tlToggle) hpbData.is_team_lead = tlToggle.checked;
    tr.querySelectorAll(".hpb-grade-select").forEach(sel => {
      hpbData[sel.dataset.field] = sel.value || null;   // hpb_grade_q1 … q4
    });
    await saveOverride(uid, btn.dataset.name, btn.dataset.territory, team, hidden, contractData, moveData, hpbData, tr);
  });

  // Clear override
  const clearBtn = tr.querySelector(".clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      await clearOverride(btn.dataset.id, btn.dataset.uid, tr);
    });
  }

  return tr;
}

async function saveOverride(uid, name, territory, team, isHidden, contractData, moveData, hpbData, tr) {
  const btn = tr.querySelector(".save-btn");
  btn.textContent = "Saving…";
  btn.disabled = true;

  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userid: uid, name, territory, team, is_hidden: isHidden, ...contractData, ...moveData, ...hpbData }),
    });
    const data = await resp.json();
    if (data.ok) {
      overrideMap[uid] = data.override;
      btn.textContent = "Saved ✓";
      tr.classList.toggle("hidden-user", isHidden);
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

async function clearOverride(overrideId, uid, tr) {
  if (!confirm("Remove override for this user? They'll revert to Mercury defaults.")) return;

  try {
    const resp = await fetch(`/api/settings/${overrideId}`, { method: "DELETE" });
    const data = await resp.json();
    if (data.ok) {
      delete overrideMap[uid];
      renderSettings(); // re-render to remove Clear button
    } else {
      alert("Delete failed: " + data.error);
    }
  } catch (e) {
    alert("Network error");
  }
}

function esc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
