# Deploying TEI-edit (web)

Production deployment checklist: env vars, process, reverse proxy, cleanup, and optional Cloudflare.

## 1. Environment variables

Set these in production (e.g. in systemd, `.env`, or your host’s config):

| Variable | Required | Description |
|----------|----------|-------------|
| `TEI_HELPER_WEB` | Yes | Set to `1` so the app runs as a web server. |
| `SECRET_KEY` | Yes | Strong random string (≥32 characters). Never use the default. |
| `UPLOAD_FOLDER` | Recommended | Absolute path to uploads directory (persistent volume). |
| `SESSION_FILE_DIR` | Recommended | Absolute path for flask-session files (persistent). |
| `PRIVACY_OPERATOR` | Optional | e.g. "The Foo University Project" (shown on Privacy page). |
| `PRIVACY_CONTACT_EMAIL` | Optional | Contact email for privacy/terms (shown on Privacy page). |
| `PRIVACY_RETENTION` | Optional | Retention text, e.g. "24 hours" (default). |
| `MAX_CONTENT_LENGTH_MB` | Optional | Max request body in MB (default 50). |
| `RATELIMIT_DEFAULT` | Optional | e.g. "60 per minute". |
| `RATELIMIT_UPLOAD` | Optional | e.g. "15 per minute" for upload routes. |
| `CLEANUP_MAX_AGE_HOURS` | Optional | For cleanup script (default 24). |

## 2. Run the app (behind a reverse proxy)

Do **not** expose Gunicorn directly to the internet. Bind to `127.0.0.1` and put a reverse proxy in front.

```bash
export TEI_HELPER_WEB=1
export SECRET_KEY="your-strong-random-secret-at-least-32-chars"
# Optional: UPLOAD_FOLDER, SESSION_FILE_DIR, etc.

# Bind to localhost only; proxy will be the public face
gunicorn -w 4 -b 127.0.0.1:5000 'app:app'
```

Or use `run_web.sh` with `BIND_ADDR=127.0.0.1` (see below).

## 3. Reverse proxy (HTTPS, body limit, timeouts)

Use **Caddy** or **nginx** in front of Gunicorn:

- **TLS**: Redirect HTTP to HTTPS; set HSTS.
- **Body size**: e.g. `client_max_body_size 50m` (nginx) so large uploads are rejected at the proxy.
- **Timeouts**: e.g. 60s read/send so slow clients don’t hold connections.

Example configs:

- **nginx**: [deploy/nginx.conf.example](deploy/nginx.conf.example)
- **Caddy**: [deploy/Caddyfile.example](deploy/Caddyfile.example)

Replace `YOUR_DOMAIN` and paths as needed.

## 4. Cleanup (retention)

To match the Privacy page (“Session data and uploaded files are deleted after …”):

1. Run the cleanup script periodically (e.g. cron every hour):

   ```bash
   # Same env as the app (at least UPLOAD_FOLDER, SESSION_FILE_DIR if set)
   /path/to/venv/bin/python /path/to/tei-helper/scripts/cleanup_sessions_and_uploads.py
   ```

2. Set `CLEANUP_MAX_AGE_HOURS` (default 24) to match `PRIVACY_RETENTION` (e.g. "24 hours").

3. Cron example (run as the app user):

   ```cron
   0 * * * * TEI_HELPER_WEB=1 SECRET_KEY=... /path/to/venv/bin/python /path/to/tei-helper/scripts/cleanup_sessions_and_uploads.py --quiet
   ```

## 5. Optional: Cloudflare

Put Cloudflare (or similar) in front of your domain for:

- DDoS protection
- Optional rate limiting at the edge

Then only traffic that passed Cloudflare hits your server.

## 6. Security summary

- **App**: `MAX_CONTENT_LENGTH`, enforced `SECRET_KEY`, Flask-Limiter on upload routes.
- **Proxy**: HTTPS, client body size limit, timeouts, security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
- **Optional**: Cloudflare in front.
