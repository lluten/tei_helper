#!/usr/bin/env python3
"""
Delete old upload and session files so retention matches the privacy policy.
Run via cron, e.g. every hour: 0 * * * * TEI_HELPER_WEB=1 SECRET_KEY=... /path/to/venv/bin/python /path/to/scripts/cleanup_sessions_and_uploads.py
Uses the same env as the app: UPLOAD_FOLDER, SESSION_FILE_DIR (optional).
"""
import os
import sys
import time

# Reuse app's default paths (no Flask import to avoid loading the app)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE, 'uploads'))
SESSION_FILE_DIR = os.environ.get('SESSION_FILE_DIR', os.path.join(BASE, 'flask_session'))

DEFAULT_MAX_AGE_HOURS = 24


def cleanup_dir(path: str, max_age_seconds: float) -> int:
    if not os.path.isdir(path):
        return 0
    now = time.time()
    removed = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) and (now - os.path.getmtime(full)) > max_age_seconds:
                os.remove(full)
                removed += 1
        except OSError:
            pass
    return removed


def main():
    max_age_hours = float(os.environ.get('CLEANUP_MAX_AGE_HOURS', DEFAULT_MAX_AGE_HOURS))
    max_age_seconds = max_age_hours * 3600

    n_uploads = cleanup_dir(UPLOAD_FOLDER, max_age_seconds)
    n_sessions = cleanup_dir(SESSION_FILE_DIR, max_age_seconds)

    if '--quiet' not in sys.argv and (n_uploads or n_sessions):
        print('Removed {} upload(s) and {} session file(s) older than {:.0f}h.'.format(
            n_uploads, n_sessions, max_age_hours))


if __name__ == '__main__':
    main()
