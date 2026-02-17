#!/usr/bin/env bash
# Run TEI-Helper as a web app with Gunicorn (production WSGI server).
# Set SECRET_KEY, UPLOAD_FOLDER, etc. in the environment before running.
# For production behind a reverse proxy, set BIND_ADDR=127.0.0.1 (see DEPLOY.md).
# Example: PORT=8000 SECRET_KEY=your-secret ./run_web.sh
set -e
cd "$(dirname "$0")"
export TEI_HELPER_WEB=1
bind="${BIND_ADDR:-0.0.0.0}:${PORT:-5000}"
exec gunicorn -w 4 -b "$bind" 'app:app'
