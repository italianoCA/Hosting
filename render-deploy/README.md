# WFM Forecast Generator + Dual MCP Servers on Render

Deploy the WFM forecast HTML app, ServiceNow MCP server, and Zoom Virtual Agent MCP server to Render using a single `render.yaml` blueprint.

## What's included

- **Web Service** (`wfm-forecast-web`): Static site hosting the forecast generator (HTML/JS, runs entirely client-side)
- **ServiceNow MCP Server** (`snow-mcp-server`): Python FastMCP server for ServiceNow ITSM operations (hardened with TLS, PORT env support, optional bearer-token auth)
- **Zoom MCP Server** (`zoom-mcp-server`): Python FastMCP server for Zoom Virtual Agent insights and diagnostics

All three services are free-tier eligible and share a single git repo.

## Prerequisites

1. **GitHub account** — Render deploys from git repos
2. **Render account** (free) — https://render.com
3. **ServiceNow credentials** (for ServiceNow MCP):
   - `SNOW_BASE_URL` — your instance URL (e.g. `https://ven05620.service-now.com`)
   - `SNOW_CREDENTIAL` — base64-encoded `username:password`
   - `SNOW_VA_SYS_ID` — virtual agent system ID
4. **Zoom credentials** (for Zoom MCP):
   - `ZOOM_ACCOUNT_ID` — your Zoom account ID
   - `ZOOM_CLIENT_ID` — OAuth client ID (from Zoom Marketplace)
   - `ZOOM_CLIENT_SECRET` — OAuth client secret

## Deployment Steps

### 1. Push to GitHub

```bash
cd /path/to/your/repo
git init                    # if not already a repo
git add render-deploy/
git commit -m "Add Render deployment for WFM forecast + ServiceNow MCP"
git push origin main
```

Ensure `render-deploy/` is in your repo root.

### 2. Create a Render Blueprint

Go to https://dashboard.render.com/ and click **+ New** → **Blueprint**.

- **Repository**: Select your GitHub repo
- **Branch**: `main` (or your branch)
- **Blueprint path**: `render-deploy/render.yaml`

Click **Create Blueprint**.

Render will parse `render.yaml` and show a summary: 2 services (web + web).

### 3. Configure Environment Variables

On the blueprint deploy page, Render will ask for environment variables for each service. Set these:

**ServiceNow MCP (`snow-mcp-server`):**

| Key | Value | Description |
|-----|-------|-------------|
| `SNOW_BASE_URL` | `https://ven05620.service-now.com` | Your ServiceNow instance URL |
| `SNOW_CREDENTIAL` | `base64-encoded-user:pass` | Base64-encode your `username:password` [here](https://www.base64encode.org/) |
| `SNOW_VA_SYS_ID` | `6020f8848715e110ecd7b9d6cebb35c5` | Virtual agent system ID from ServiceNow |
| `MCP_AUTH_TOKEN` | `your-secret-token` | (Optional) Bearer token for auth. If empty, runs unauthenticated. |

**Zoom MCP (`zoom-mcp-server`):**

| Key | Value | Description |
|-----|-------|-------------|
| `ZOOM_ACCOUNT_ID` | `your-zoom-account-id` | Your Zoom account ID |
| `ZOOM_CLIENT_ID` | `your-zoom-client-id` | OAuth client ID from Zoom Marketplace |
| `ZOOM_CLIENT_SECRET` | `your-zoom-client-secret` | OAuth client secret from Zoom Marketplace |

**Web Service (`wfm-forecast-web`):**

Leave all env vars blank (none needed for static site).

### 4. Deploy

Click **Deploy**.

Render will:
1. Detect `render.yaml`
2. Spin up 3 services in parallel
3. Build and start both MCP servers (install dependencies, run)
4. Host the static site
5. Give you three URLs:
   - **Web**: `https://wfm-forecast-web.onrender.com/` (static site)
   - **ServiceNow MCP**: `https://snow-mcp-server.onrender.com/` (FastMCP HTTP server)
   - **Zoom MCP**: `https://zoom-mcp-server.onrender.com/` (FastMCP HTTP server)

All will be live in 3–5 minutes.

---

## Using the Deployed Services

### Forecast Generator

Open `https://wfm-forecast-web.onrender.com/` in your browser. No auth required.

- Fill in the form, select date from calendar, generate CSV, download.
- Runs 100% client-side; no backend calls needed.
- Outputs: `start_time_interval, end_time_interval, scheduling_group_name, channel, volume, average_handle_time, campaign_name`

### ServiceNow MCP Server

Available at `https://snow-mcp-server.onrender.com/`.

**Tools available:**
- `get_userID_by_contact(phone_number, email)` — Find user by phone or email
- `get_open_incidents_by_user(user_sys_id)` — List open incidents
- `get_open_interactions_by_user(user_sys_id)` — List open interactions
- `create_incident(contact_sys_id, short_desc, full_desc, issue_type, preferred_name)` — Create incident
- `create_interaction(contact_sys_id, short_desc, full_desc, preferred_name)` — Create interaction
- `update_incident(incident_sys_id, short_desc, state, work_notes)` — Update incident
- `update_interaction(interaction_sys_id, work_notes, state)` — Update interaction
- `close_incident(incident_sys_id, close_code, resolution_notes)` — Close incident
- `close_interaction(interaction_sys_id, work_notes, close_notes, state)` — Close interaction

### Zoom Virtual Agent MCP Server

Available at `https://zoom-mcp-server.onrender.com/`.

**Tools available:**
- `get_zva_sessions(start_date, end_date, ai_type, limit)` — Retrieve ZVA engagements within a date range
- `get_zva_transcript(engagement_ids, start_date, end_date, ai_type, limit)` — Get detailed transcript for a specific engagement
- `analyze_zva_behavior(engagement_ids, start_date, end_date, ai_type, limit)` — Analyze why ZVA gave a specific answer or failed (examines transcripts, variables, query details)

---

## Important Notes

### Cold Starts

**Free tier**: Render spins down idle services after 15 minutes of inactivity. The first request after sleep takes 30–50 seconds.

If you need always-on, upgrade to **Starter** tier (~$7/month per service).

### TLS & Security

- All services are **HTTPS by default** (Render provides TLS certificates).
- The MCP server now has `verify=True` on all ServiceNow API calls (validates HTTPS certs).
- `MCP_AUTH_TOKEN` is optional — if set, requests must include `Authorization: Bearer <token>`.
- If unset, the server runs open (useful for testing; **don't expose publicly without auth**).

### Monitoring

In the Render dashboard, each service has logs. Check the MCP server logs to debug ServiceNow API issues.

---

## Local Testing (Optional)

To test locally before pushing:

```bash
# Terminal 1: MCP server
cd render-deploy/mcp
python -m pip install -r requirements.txt
export SNOW_BASE_URL="https://your-instance.service-now.com"
export SNOW_CREDENTIAL="your-base64-cred"
export SNOW_VA_SYS_ID="your-sysid"
export MCP_AUTH_TOKEN="test-token"
python snow_mcp.py
```

The server listens on `http://localhost:8086`.

```bash
# Terminal 2: Web server
cd render-deploy/web
python -m http.server 8080
# Open http://localhost:8080/
```

---

## Troubleshooting

### MCP server won't start
- **Check logs**: Render dashboard → `snow-mcp-server` → **Logs**
- **Verify env vars**: Make sure all four are set (at least SNOW_BASE_URL, SNOW_CREDENTIAL, SNOW_VA_SYS_ID)
- **Port binding**: The server reads `PORT` from the Render environment; should work automatically

### ServiceNow API errors
- Verify `SNOW_CREDENTIAL` is correct base64 (decode it, check username:password)
- Verify `SNOW_BASE_URL` has no trailing `/`
- Check ServiceNow instance is reachable: `curl https://your-instance.service-now.com/api/now/table/sys_user` (you'll get a 401 without auth, which is fine)

### "Unauthorized" from MCP
- If `MCP_AUTH_TOKEN` is set, all requests must include `Authorization: Bearer <token>`
- If you want open access, remove `MCP_AUTH_TOKEN` from env vars (or set it to empty string)

---

## Next Steps

- **Connect to Claude**: Once the MCP is running, you can add it as a custom MCP in Claude Code
- **Connect to Zoom Flows**: Wire the MCP URL into a Zoom Flows tool to call ServiceNow from a virtual agent
- **Scale up**: If you need always-on, upgrade to a paid tier (Starter is $7/mo per service)
