# Saragossa Weekly Report

Live consultant performance report pulling from Mercury (Dataverse).
Deployed as an Azure Static Web App with Entra ID authentication.

---

## Architecture

```
GitHub repo
  └── push to main → GitHub Actions → Azure SWA

Azure SWA (Free tier)
  ├── /public          Static HTML/JS/CSS
  ├── /api             Azure Functions (Python 3.11)
  │     ├── GET /api/report-data   → full report JSON
  │     ├── GET /api/settings      → admin: user list + overrides
  │     ├── POST /api/settings     → admin: upsert override
  │     └── DELETE /api/settings/{id} → admin: remove override
  └── Entra ID auth    built-in, all routes protected
```

---

## One-time setup

### Step 1 — Create the Dataverse override table

In Power Apps (make.powerapps.com → your Saragossa environment → Tables → New table):

**Table**
- Display name: `Report User Override`
- Name (will auto-fill): `crbb7_useroverride`
- Primary column display name: `Name` (this will hold the consultant's display name)

**Add these columns:**

| Display name   | Name (auto)          | Type         | Required | Notes                              |
|----------------|----------------------|--------------|----------|------------------------------------|
| User ID        | crbb7_userid         | Text (255)   | Yes      | The systemuser GUID from Mercury   |
| Team           | crbb7_team           | Text (100)   | No       | Override team name; blank = default|
| Is Hidden      | crbb7_ishidden       | Yes/No       | Yes      | Default: No                        |
| Territory      | crbb7_territory      | Text (50)    | No       | e.g. "Bristol"                     |
| Updated By     | crbb7_updatedby      | Text (255)   | No       | Email of admin who made the change |
| Updated On     | crbb7_updatedon      | Date & Time  | No       | Auto-set by the API                |

Save the table. You don't need any views or forms — the API handles everything.

**Give the service principal access:**
After creating the app registration in Step 2, go to:
Power Apps → Settings → Security → Users → Add the service principal user →
Assign the **System Customizer** role (or a custom role with Create/Read/Write/Delete on `crbb7_useroverride`
and Read on `systemuser`, `territory`, `team`, `teammembership`, `crimson_placement`, `transactioncurrency`).


### Step 2 — Register an Entra app

In portal.azure.com → Azure Active Directory → App registrations → New registration:

- Name: `Saragossa Report`
- Supported account types: **Accounts in this organizational directory only**
- Redirect URI: leave blank for now (SWA will set this)

After creation:
1. Note the **Application (client) ID** and **Directory (tenant) ID**
2. Go to **Certificates & secrets** → New client secret → note the value immediately
3. Go to **API permissions** → Add permission → APIs my organisation uses →
   search `Dataverse` → select **user_impersonation** → Grant admin consent

The same app registration covers both the SWA login flow and the API's Dataverse calls.


### Step 3 — Create the Azure Static Web App

In portal.azure.com → Static Web Apps → Create:

- Subscription / Resource Group: your choice
- Name: `saragossa-report` (or similar)
- Plan type: **Free**
- Region: UK South (or nearest)
- Deployment source: **GitHub**
  - Authorise → select your org/repo → branch: `main`
  - Build preset: **Custom**
  - App location: `public`
  - Api location: `api`
  - Output location: *(leave blank)*

After creation, note the **default domain** (e.g. `gentle-rock-abc123.azurestaticapps.net`).

**Add the SWA redirect URI to your Entra app:**
- Portal → App registrations → Saragossa Report → Authentication → Add platform → Web
- Redirect URI: `https://YOUR_SWA_DOMAIN/.auth/login/aad/callback`
- Also add: `https://YOUR_SWA_DOMAIN/.auth/logout`


### Step 4 — Configure environment variables

In the SWA resource → Configuration → Application settings, add:

| Name                         | Value                                      |
|------------------------------|--------------------------------------------|
| `DATAVERSE_URL`              | `https://saragossa.crm11.dynamics.com`     |
| `DATAVERSE_TENANT_ID`        | Your Entra tenant ID (from Step 2)         |
| `DATAVERSE_CLIENT_ID`        | Your app client ID (from Step 2)           |
| `DATAVERSE_CLIENT_SECRET`    | Your client secret value (from Step 2)     |
| `AZURE_CLIENT_ID`            | Same as DATAVERSE_CLIENT_ID               |
| `AZURE_CLIENT_SECRET`        | Same as DATAVERSE_CLIENT_SECRET           |

These are securely stored and injected into the Azure Functions at runtime. Never put them in the repo.


### Step 5 — Update staticwebapp.config.json

Replace `REPLACE_WITH_TENANT_ID` in `staticwebapp.config.json` with your actual Entra tenant ID:

```json
"openIdIssuer": "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0"
```

Commit and push — GitHub Actions will redeploy automatically.


### Step 6 — Add the deployment token to GitHub

In the SWA resource → Overview → **Manage deployment token** → copy it.

In your GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
- Name: `AZURE_STATIC_WEB_APPS_API_TOKEN`
- Value: the token you just copied


### Step 7 — Add the logo

Copy your logo file into `public/logo.png`. The white horizontal version works best on the dark background.

```bash
cp Logo_Horizontal_White_With_Marque.png public/logo.png
```


### Step 8 — Deploy

Push to `main`. GitHub Actions runs, deploys the app. Check the Actions tab for status.

Visit `https://YOUR_SWA_DOMAIN` — you'll be redirected to Entra login. Sign in with your Saragossa account.

---

## How user management works

### New starters
When someone is added to Mercury with a territory from the six report territories, they appear on the next report load automatically. No action needed.

### Leavers
When someone is disabled in Mercury (`isdisabled = true`), they disappear from the report automatically.

### Team assignments
The app uses a built-in default team map (in `api/shared/calc.py`). If Mercury gets a team field added in future, update `_default_team()` in calc.py to read it.

For one-off corrections without touching code, use the Settings page.

### Settings page (admin only)
Visit `/settings`. Accessible to:
- Users with "Director" in their Mercury job title
- Members of the "Bristol Finance and Compliance" team in Mercury

From Settings you can:
- Change a consultant's team (overrides the default)
- Hide a consultant from the report (e.g. if they're on extended leave)
- Clear an override to revert to defaults

---

## Updating the report

**New metric or column** → edit `api/shared/calc.py` and `public/app.js`

**New territory** → add to `TERRITORY_IDS` in `api/shared/dataverse.py` and `TERRITORY_ORDER` in `public/app.js`

**New team within a territory** → add to `TEAM_ORDER` in `api/shared/calc.py` and `TEAMS_BY_TERRITORY` in `public/settings.js`

**FX rates** → update `TO_GBP` / `TO_USD` in `api/shared/calc.py` each year when HMRC publishes annual averages. Alternatively, wire it up to read from the existing `crbb7_fxrate` Dataverse table (same pattern as the Commission Calculator).

---

## Local development

```bash
# Install Azure Functions Core Tools
npm install -g azure-functions-core-tools@4

# Install Python deps
cd api && pip install -r requirements.txt

# Create local.settings.json (not committed — in .gitignore)
cat > api/local.settings.json << 'EOF'
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "DATAVERSE_URL": "https://saragossa.crm11.dynamics.com",
    "DATAVERSE_TENANT_ID": "your-tenant-id",
    "DATAVERSE_CLIENT_ID": "your-client-id",
    "DATAVERSE_CLIENT_SECRET": "your-client-secret"
  }
}
EOF

# Run the Functions locally
cd api && func start

# Serve static files (any static server)
cd public && npx serve .
```

Note: local auth is not wired up (SWA auth only works in Azure). For local testing, temporarily comment out the `require_auth` call in `function_app.py` and hardcode a test email.

---

## File structure

```
saragossa-report/
├── .github/
│   └── workflows/
│       └── azure-static-web-apps.yml    # CI/CD
├── api/
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── auth.py                      # SWA principal header parsing
│   │   ├── calc.py                      # Split calculation logic
│   │   └── dataverse.py                 # Mercury Web API client
│   ├── function_app.py                  # All API routes
│   ├── host.json
│   └── requirements.txt
├── public/
│   ├── index.html                       # Main report page
│   ├── settings.html                    # Admin settings page
│   ├── 403.html                         # Access denied page
│   ├── app.js                           # Report rendering
│   ├── settings.js                      # Settings page logic
│   ├── style.css                        # Shared styles
│   └── logo.png                         # Add this manually
├── staticwebapp.config.json             # SWA auth + routing config
└── README.md
```
