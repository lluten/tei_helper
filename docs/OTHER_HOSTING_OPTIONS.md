# Other hosting options (when leaving PythonAnywhere)

If you hit PA limits or need scheduled tasks (paid on PA), here are alternatives that work with your Flask app and optional **free** tiers.

---

## Always-free or long-term free

| Provider | What you get | Good for |
|---------|----------------|----------|
| **Oracle Cloud Free Tier** | Always-free small VPS (AMD or ARM). Full control: install Python, Caddy/nginx, gunicorn, cron for 24h cleanup. | You’re okay with a bit of server setup; no monthly cost. |
| **Fly.io** | Free allowance: a few small VMs, limited bandwidth. Deploy with `fly launch`; they run your app. | You want “deploy and go” without managing a raw server. |
| **Render** | Free web service tier. Deploys from GitHub; **spins down when idle** (first request after idle can be slow). | Low traffic; cold starts are acceptable. |

## Free with limits

| Provider | Notes |
|----------|--------|
| **Railway** | Monthly free credit; when it runs out you pay or the app stops. |
| **Google Cloud / AWS / Azure** | Free tiers are time-limited (e.g. 12 months) or easy to outgrow; watch for unexpected charges. |

---

## Practical choice after PA

- **No server admin, minimal setup:** Try **Fly.io** or **Render** (both have free tiers; Render has spin-down, Fly.io has usage limits).
- **No monthly cost, you’re fine with a server:** **Oracle Cloud Free Tier** — create an “Always Free” VM, then follow the same idea as a normal VPS: clone your repo, virtualenv, gunicorn behind Caddy/nginx, cron for `scripts/cleanup_sessions_and_uploads.py`.

Your app is already set up for a generic deployment: `requirements.txt`, `run_web.sh`-style gunicorn, and the cleanup script. On a VPS you’d:
- Bind gunicorn to `127.0.0.1:5000`
- Put Caddy or nginx in front (HTTPS, optional rate limiting)
- Add a cron job for the cleanup script (e.g. daily)

No code changes are required to move; only the host and how you run the app + cron differ.
