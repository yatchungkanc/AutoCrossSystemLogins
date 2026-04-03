---
description: "Add a new dashboard entry or URL to dashboards.yaml — no code changes needed"
argument-hint: "Dashboard name, URL(s), and auth type (email_only, sso, atlassian, cloudhealth)"
agent: "agent"
tools: ["read_file", "replace_string_in_file"]
---

Add a new dashboard to **$ARGUMENTS** in [dashboards.yaml](../../dashboard-agent/config/dashboards.yaml).

## Step 1 — Read the file first

Read [dashboards.yaml](../../dashboard-agent/config/dashboards.yaml) in full before making any changes.

## Step 2 — Determine the change type

**Option A — Adding a URL to an existing group**: If the URL belongs to an existing `id` group (same topic/service), append it under that group's `urls:` list.

**Option B — Creating a new dashboard group**: If this is a new service or topic, append a new entry at the bottom of the `dashboards:` list with the structure below.

## Step 3 — Apply the correct YAML structure

**Single URL** (use `url:`, not `urls:`):
```yaml
  - id: <kebab-case-id>
    name: "<Human Readable Name>"
    auth_type: <email_only|sso|atlassian|cloudhealth>
    url: "<https://...>"
```

**Multiple URLs** (use `urls:`, not `url:`):
```yaml
  - id: <kebab-case-id>
    name: "<Human Readable Name>"
    auth_type: <email_only|sso|atlassian|cloudhealth>
    urls:
      - name: "<Tab Label>"
        url: "<https://...>"
      - name: "<Tab Label>"
        url: "<https://...>"
```

**Rules — do not break these:**
- Never use both `url:` and `urls:` on the same entry.
- `id` must be unique, lowercase, hyphenated.
- `auth_type` must match one of the existing values in the file — do not invent new ones. If the auth type needed doesn't exist yet, stop and tell the user to run `/add-auth-strategy` first.
- Preserve the existing file indentation (2 spaces).
- Add new groups above the `# Add more dashboards below...` comment if present.

## Step 4 — Confirm

After editing, print a summary:
- What was added (group or URL)
- The `id` and `auth_type` used
- A reminder: no code changes are needed — the orchestrator reads this file at runtime automatically.
