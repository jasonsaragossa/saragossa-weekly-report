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
let overrideMap = {}; // uid → override record

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
  (data.overrides || []).forEach(o => { overrideMap[o.crbb7_userid] = o; });

  renderSettings();
})();


function renderSettings() {
  const container = document.getElementById("settings-content");
  container.innerHTML = "";

  // Analytics access management (top of page)
  container.appendChild(buildAccessSection());

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
      ${isContract ? "<th>Total Margin YTD</th><th>Contract Last 12M</th><th>Rolling 3M</th>" : "<th>Annual Target</th>"}
      ${isUsPerm ? "<th>Team Lead</th><th>HPB Grade (Q1–Q4)</th>" : ""}
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


// ── Analytics access management ────────────────────────────────────────────────

function buildAccessSection() {
  const section = document.createElement("div");
  section.className = "settings-section";
  section.id = "access-section";

  const usersById = {};
  allActiveUsers.forEach(u => { usersById[u.uid] = u; });

  const granted = Object.values(overrideMap)
    .filter(o => o.crbb7_canaccessanalytics === true)
    .map(o => ({ uid: o.crbb7_userid, name: (usersById[o.crbb7_userid] || {}).name || o.crbb7_userid }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const grantedSet = new Set(granted.map(g => g.uid));
  const addOptions = allActiveUsers
    .filter(u => !grantedSet.has(u.uid))
    .map(u => `<option value="${esc(u.uid)}" data-name="${esc(u.name)}">${esc(u.name)}</option>`)
    .join("");

  const grantedHtml = granted.length
    ? granted.map(g => `<li class="access-row" data-uid="${esc(g.uid)}">
         <span>${esc(g.name)}</span>
         <button class="clear-btn access-remove" data-uid="${esc(g.uid)}">Remove</button>
       </li>`).join("")
    : `<li class="access-empty">No extra users granted yet.</li>`;

  section.innerHTML = `
    <h2 class="settings-territory">Analytics Access</h2>
    <p class="settings-desc">Directors and the “${esc(FINANCE_TEAM_NAME)}” team can already see the Analytics page. Grant access to anyone else below.</p>
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

  const contractFields = isContract ? `
    <td><input type="number" class="contract-input contract-figure" data-field="margin_ytd"
         placeholder="0" step="1"
         value="${ov.crbb7_marginytd != null ? ov.crbb7_marginytd : ""}"></td>
    <td><input type="number" class="contract-input contract-figure" data-field="contract_last12m"
         placeholder="0" step="1"
         value="${ov.crbb7_contractlast12m != null ? ov.crbb7_contractlast12m : ""}"></td>
    <td><input type="number" class="contract-input contract-figure" data-field="rolling_3m"
         placeholder="0" step="1"
         value="${ov.crbb7_rolling3m != null ? ov.crbb7_rolling3m : ""}"></td>
  ` : "";

  const targetVal = ov.crbb7_target != null ? ov.crbb7_target : "";
  const sym = (territory === "Chicago" || territory === "New York" || territory === "Chicago Contract") ? "$" : "£";

  // HPB controls (US perm only): Team Lead toggle + grade selector.
  // Team Lead defaults to the title when never explicitly set.
  const tlOv       = ov.crbb7_isteamlead;
  const isTeamLead = tlOv === true || (tlOv == null && /team lead/i.test(u.role || ""));
  const HPB_GRADE_CHOICES = [
    ["", "Auto"],
    ["none", "Doesn't qualify"],
    ["associate", "Associate"],
    ["consultant", "Consultant"],
    ["senior", "Senior"],
    ["principal", "Principal"],
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
    ${contractFields}
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
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
