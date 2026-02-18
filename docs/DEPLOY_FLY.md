# Deploy TEI-edit on Fly.io

1. **App name**: App names are **globally unique** on Fly.io. If you get "failed to create app", the name in `fly.toml` (e.g. `tei-edit`) is likely taken. Edit `fly.toml` and set `app = "tei-edit-YOURUSERNAME"` (or another unique name), then try again.
2. **Connect GitHub** in the Fly.io dashboard and select this repo (or run `fly launch` locally and link the app).
2. **Set secrets** (required): In Fly dashboard → your app → Secrets, or run:
   ```bash
   fly secrets set SECRET_KEY="your-strong-secret-at-least-32-characters"
   ```
   Optional: `PRIVACY_CONTACT_EMAIL`, `PRIVACY_OPERATOR`, `PRIVACY_RETENTION`.
3. **Deploy**: If you connected GitHub, push to the linked branch to trigger a deploy. Or run `fly deploy` from the project directory.
4. **Cleanup (24h deletion)**: Fly.io has [cron jobs](https://fly.io/docs/flyctl/cron/) or you can use an external cron (e.g. cron-job.org) to call a small endpoint that runs the cleanup script. Alternatively add a worker process or scheduled machine that runs the script periodically.

The app listens on port 8080; `fly.toml` and the Dockerfile are already in the repo.
