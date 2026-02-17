# Next steps for actual deployment

What you need and in what order. You do **not** need to reorganize the git repo structure; the project is deployment-ready as-is. A few hygiene steps are recommended below.

---

## What you need

| Need | Notes |
|------|--------|
| **A host** | VPS (e.g. Hetzner CX11, Oracle Cloud free tier) or PaaS (Fly.io, Railway). **No monthly cost:** see [Free hosting options](FREE_HOSTING_OPTIONS.md) (Oracle, PythonAnywhere, Fly.io). |
| **A domain (or subdomain)** | e.g. `tei-edit.youruniversity.org` or a domain you buy. The host will need to get HTTPS for this. |
| **SSH access** | For a VPS: you need SSH keys to log in. For PaaS: you use their CLI and dashboard. |
| **A strong SECRET_KEY** | Generate once and keep it secret, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`. |

---

## Repo: do you need to reorganize?

**No.** The layout is fine for deployment. You only need to:

1. **Avoid committing secrets and runtime data**  
   A [`.gitignore`](../.gitignore) has been added so that `uploads/`, `flask_session/`, `.env`, and `.venv/` are never committed. If you already committed `uploads/` or `flask_session/` in the past, run:
   - `git rm -r --cached uploads/ flask_session/` (if they were tracked), then commit.
   - Do **not** put `SECRET_KEY` or other secrets in the repo; set them only on the server (env or host’s secrets).

2. **Keep deployment config out of the main code**  
   Use environment variables for everything secret or host-specific (you already do). Example configs live in `deploy/*.example`; copy and customize them on the server, don’t commit real secrets.

No need to move app code, rename folders, or split the repo unless you have other requirements (e.g. monorepo).

---

## Deployment sequence (high level)

1. **Choose host and create a machine/app**  
   - VPS: create a small Linux instance, note its IP.  
   - PaaS: create an app (e.g. Fly.io `fly launch`), note the URL they give you.

2. **Point the domain at the host**  
   - Add an A record (or CNAME if the host says so) so your domain resolves to the host’s IP or target.  
   - Wait for DNS to propagate (minutes to hours).

3. **Put the code on the host**  
   - VPS: clone the repo (e.g. `git clone <your-repo-url>`, then `cd tei-helper`).  
   - PaaS: connect the repo in the dashboard or use their CLI so they deploy from git.

4. **Install runtime and dependencies**  
   - VPS: install Python 3.11+, create a venv, `pip install -r requirements.txt`.  
   - PaaS: usually automatic from `requirements.txt`.

5. **Set environment variables**  
   - At least: `TEI_HELPER_WEB=1`, `SECRET_KEY=<your-strong-key>`.  
   - Recommended: `UPLOAD_FOLDER` and `SESSION_FILE_DIR` as absolute paths to persistent storage (so restarts don’t wipe data).  
   - Optional: `PRIVACY_OPERATOR`, `PRIVACY_CONTACT_EMAIL`, `PRIVACY_RETENTION`.  
   - Never commit these; set them in the host’s UI or in a file that’s not in git (e.g. systemd unit, or `.env` on the server only).

6. **Run the app (behind a proxy)**  
   - Run Gunicorn bound to `127.0.0.1:5000` (e.g. `BIND_ADDR=127.0.0.1 ./run_web.sh` or the gunicorn command from [DEPLOY.md](../DEPLOY.md)).  
   - On PaaS, they often start the process for you; ensure the start command is `gunicorn -w 4 -b 0.0.0.0:$PORT 'app:app'` and that `PORT` and `TEI_HELPER_WEB`, `SECRET_KEY` are set.

7. **Put a reverse proxy in front (VPS)**  
   - Install Caddy or nginx, use [deploy/nginx.conf.example](../deploy/nginx.conf.example) or [deploy/Caddyfile.example](../deploy/Caddyfile.example), replace `YOUR_DOMAIN`, then enable the config.  
   - Caddy will get HTTPS automatically; with nginx you typically use certbot.  
   - PaaS usually provides TLS and a reverse proxy; you may not need this step.

8. **Schedule cleanup**  
   - On a VPS: add a cron job that runs `scripts/cleanup_sessions_and_uploads.py` every hour (see [DEPLOY.md](../DEPLOY.md)).  
   - On PaaS: use their cron/scheduler feature with the same script and the same env (or a small one-off task).

9. **Optional: Cloudflare**  
   - Point your domain through Cloudflare (change nameservers or use their CNAME). Then your server only sees traffic that passed Cloudflare (DDoS and optional rate limiting).

---

## One-line “do I have everything?”

- **Host** (VPS or PaaS)  
- **Domain** pointing at that host  
- **Code** on the host (git clone or PaaS deploy)  
- **Env** set (`TEI_HELPER_WEB`, `SECRET_KEY`, and optionally `UPLOAD_FOLDER`, `SESSION_FILE_DIR`, privacy vars)  
- **Process** running (Gunicorn on 127.0.0.1 for VPS, or PaaS process)  
- **Proxy + HTTPS** (Caddy/nginx on VPS, or built-in on PaaS)  
- **Cleanup** cron/scheduler for uploads and sessions  

No repo reorganization required; keep using the same repo and add the `.gitignore` (and stop tracking `uploads/`/`flask_session/` if they were ever committed).
