# Deploy TEI-edit on Fly.io

## Dashboard: create app and connect GitHub

When creating an app in the Fly.io dashboard and connecting your GitHub repo, use these values (everything is at the **repo root**):

| Field | What to enter |
|-------|----------------|
| **Name** | A unique app name (e.g. `tei-edit-lluten`). Must be globally unique on Fly.io. |
| **Organization** | Your personal org (default). |
| **Region** | Any region (e.g. Amsterdam, Frankfurt). |
| **Working directory** | Leave **empty** or put **`.`** — the app and Dockerfile are at the repo root. |
| **Config path** | Leave **empty** so Fly uses `fly.toml` at the repo root. If there is a field for config file, enter **`fly.toml`**. |
| **Dockerfile path** | Leave **empty** so Fly uses `Dockerfile` at the repo root. |

If the form has a “Root directory” or “Source directory” instead of “Working directory”, leave it empty or `.` for repo root.

If deploy still fails after a unique name and correct paths, check the **build logs** in the dashboard (or the “Deployments” / “Logs” tab) — the error message there will say whether the problem is build (Dockerfile) or runtime (missing SECRET_KEY, etc.).

---

## After the app is created

1. **Set secrets** (required): In the app → **Secrets**, add:
   - `SECRET_KEY` = your strong secret (at least 32 characters).
   - Optional: `PRIVACY_CONTACT_EMAIL`, `PRIVACY_OPERATOR`, `PRIVACY_RETENTION`.
2. **Redeploy** if the first deploy ran before secrets were set (or push a small commit to trigger a new deploy).
3. **Cleanup (24h deletion)**: Use [Fly cron](https://fly.io/docs/flyctl/cron/) or an external cron to run the cleanup script periodically.

The app listens on port 8080; `fly.toml` and the Dockerfile in the repo are set up for that.
