---
description: "Reset the persistent browser auth session — clears saved login state and guides through re-authenticating from scratch"
argument-hint: "Optional: reason for reset (e.g. expired creds, SSO cert change, corrupt profile)"
agent: "agent"
tools: ["run_in_terminal", "read_file"]
---

Reset the dashboard-agent auth session for **$ARGUMENTS**.

## Background

The session lives in `.auth_session/` (inside `dashboard-agent/`) and contains:
- The persistent Chromium profile (cookies, local storage, cached SSO tokens)
- `.auth_session/.setup_complete` — a marker that tells the orchestrator whether to run first-run manual login or automated login

Deleting this directory forces a full re-authentication on the next run.

## Step 1 — Confirm intent

Before deleting, check whether `.auth_session/` exists and what's in it:

```bash
ls -la dashboard-agent/.auth_session/ 2>/dev/null && echo "Session exists" || echo "No session found — nothing to reset"
```

If no session exists, stop here and tell the user there is nothing to reset.

## Step 2 — Delete the session

```bash
rm -rf dashboard-agent/.auth_session/
echo "Session cleared."
```

## Step 3 — Explain what happens next

Inform the user of the exact first-run sequence they need to complete:

1. **Run the orchestrator** from inside `dashboard-agent/`:
   ```bash
   cd dashboard-agent && python -m src.orchestrator
   ```
2. **A browser window will open.** The first login will trigger Microsoft device authentication — a browser prompt will appear asking to select a certificate or complete device auth.
3. **Complete it manually** — the script waits. Do not close the browser or interrupt the process.
4. **Each service (Tableau, SharePoint, JIRA, AI Pro, CloudHealth) will go through its login flow** in sequence. Some may require accepting "Stay signed in?" prompts.
5. **Once all tabs are open**, the `.setup_complete` marker is written automatically. Future runs will be fully automated.

## Step 4 — Verify credentials are still valid

Check that the required env vars are set (they live in `.env` at the repo root, not inside `dashboard-agent/`):

```bash
grep -E "^(TABLEAU_EMAIL|SSO_USERNAME|SSO_PASSWORD)" "$(git rev-parse --show-toplevel)/.env" | sed 's/=.*/=<set>/'
```

If any are missing or if this was triggered by a credential change, remind the user to update `.env` before the first run.

## Step 5 — Summary

Print a one-line confirmation:
```
Auth session cleared. Run `python -m src.orchestrator` from dashboard-agent/ to re-authenticate.
```
