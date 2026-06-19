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

let allUsers = [];
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
  (data.overrides || []).forEach(o => { overrideMap[o.crbb7_userid] = o; });

  renderSettings();
})();


function renderSettings() {
  const container = document.getElementById("settings-content");
  container.innerHTML = "";

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
      ${isContract ? "<th>Total Margin YTD</th><th>Contract Last 12M</th><th>Rolling 3M</th>" : ""}
      <th>Annual Target</th>
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

function buildUserRow(u, territory) {
  const ov = overrideMap[u.uid] || {};
  const isHidden     = ov.crbb7_ishidden || false;
  const currentTeam  = ov.crbb7_team || "";
  const teams        = TEAMS_BY_TERRITORY[territory] || [];
  const isContract   = CONTRACT_TERRITORIES.has(territory);

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
    <td><input type="number" class="contract-input" data-field="margin_ytd"
         placeholder="0" step="1"
         value="${ov.crbb7_marginytd != null ? ov.crbb7_marginytd : ""}"></td>
    <td><input type="number" class="contract-input" data-field="contract_last12m"
         placeholder="0" step="1"
         value="${ov.crbb7_contractlast12m != null ? ov.crbb7_contractlast12m : ""}"></td>
    <td><input type="number" class="contract-input" data-field="rolling_3m"
         placeholder="0" step="1"
         value="${ov.crbb7_rolling3m != null ? ov.crbb7_rolling3m : ""}"></td>
  ` : "";

  const targetVal = ov.crbb7_target != null ? ov.crbb7_target : "";
  const sym = (territory === "Chicago" || territory === "New York" || territory === "Chicago Contract") ? "$" : "£";

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
    <td>
      <input type="number" class="contract-input target-input" data-field="target"
             placeholder="${sym}0" step="1000" min="0"
             value="${targetVal}">
    </td>
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
    await saveOverride(uid, btn.dataset.name, btn.dataset.territory, team, hidden, contractData, moveData, tr);
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

async function saveOverride(uid, name, territory, team, isHidden, contractData, moveData, tr) {
  const btn = tr.querySelector(".save-btn");
  btn.textContent = "Saving…";
  btn.disabled = true;

  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userid: uid, name, territory, team, is_hidden: isHidden, ...contractData, ...moveData }),
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
