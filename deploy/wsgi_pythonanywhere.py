# PythonAnywhere WSGI file for TEI-edit.
# 1. Copy this to your project root as wsgi.py (or keep in deploy/ and fix the path below).
# 2. In the Web tab, set "WSGI configuration file" to point to this file.
# 3. Set PROJECT_HOME to your project directory, e.g. /home/YOUR_USERNAME/tei-helper
# 4. Create a .env file in the project root with at least:
#      TEI_HELPER_WEB=1
#      SECRET_KEY=your-strong-secret-at-least-32-chars
#    (Optional: PRIVACY_CONTACT_EMAIL, PRIVACY_OPERATOR, PRIVACY_RETENTION, etc.)
# 5. Install python-dotenv in your virtualenv: pip install python-dotenv

import os
import sys

# Adjust this to your project path on PythonAnywhere (e.g. /home/yourusername/tei-helper)
PROJECT_HOME = os.environ.get('TEI_EDIT_HOME', '/home/yourusername/tei-helper')
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# Load .env before importing app (so SECRET_KEY and TEI_HELPER_WEB are set)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_HOME, '.env'))
except ImportError:
    pass  # Set env vars in Web tab or system instead

os.environ.setdefault('TEI_HELPER_WEB', '1')

from app import app as application
