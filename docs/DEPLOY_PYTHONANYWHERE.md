# Deploy TEI-edit on PythonAnywhere (with your own domain)

Step-by-step for deploying TEI-edit on PythonAnywhere and connecting a domain you’ve already bought.

**Quick summary:** Get code onto PA → create virtualenv, `pip install -r requirements.txt` + `python-dotenv` → create `.env` with `TEI_HELPER_WEB=1` and `SECRET_KEY` → Web tab: Manual config, set virtualenv, edit WSGI to load `.env` and `from app import app as application` → Reload. Then (paid) add domain: CNAME `www` → value from Web tab, enable HTTPS.

**Note:** Your own domain (e.g. `www.yourdomain.com`) requires a **paid** PythonAnywhere account. You can start on the free tier at `yourusername.pythonanywhere.com` to test, then add the domain after upgrading.

---

## 1. Account and project path

- Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free is fine to start).
- Note your **username**; your project will live at `/home/YOUR_USERNAME/tei-helper` (or another name you choose).

---

## 2. Get the code onto PythonAnywhere

**Option A: Git (if the repo is public or you use SSH keys)**

- Open a **Bash** console on PythonAnywhere (Consoles → Bash).
- Run:
  ```bash
  cd ~
  git clone https://github.com/YOUR_USERNAME/tei-helper.git
  # or: git clone git@github.com:YOUR_USERNAME/tei-helper.git
  cd tei-helper
  ```

**Option B: Upload**

- In the **Files** tab, create a folder (e.g. `tei-helper`) under your home directory.
- Upload your project files (drag-and-drop or upload zip then unzip in Bash): at least `app.py`, `requirements.txt`, `templates/`, `static/`, `deploy/`, `scripts/`, and optionally `tags.json`, `tei_layout_template.xml`.

---

## 3. Virtualenv and dependencies

In a **Bash** console:

```bash
cd ~/tei-helper
mkvirtualenv --python=/usr/bin/python3.10 tei-edit
# (or python3.11 if available: /usr/bin/python3.11)
pip install -r requirements.txt
pip install python-dotenv
```

Use the Python version that matches what you’ll choose in the Web app (step 5). You can see available versions with `ls /usr/bin/python*`.

---

## 4. Where to set the email and SECRET_KEY (not in app.py)

**Do not put `SECRET_KEY` or `PRIVACY_CONTACT_EMAIL` in `app.py` or any file you push to git.** Anyone with the repo could see them. Set them **only on the server** in a `.env` file (see below). The app already reads these from the environment; you just create `.env` on PythonAnywhere after you clone.

---

## 5. Create a `.env` file on PythonAnywhere (secrets, not in git)

Still in Bash, **on the PythonAnywhere server**, in the project directory:

```bash
cd ~/tei-helper
nano .env
```

Add at least (replace the secret with your own):

```
TEI_HELPER_WEB=1
SECRET_KEY=your-strong-random-secret-at-least-32-characters
```

Optional, for the privacy page:

```
PRIVACY_OPERATOR=Your University Name
PRIVACY_CONTACT_EMAIL=your.name@university.edu
PRIVACY_RETENTION=24 hours
```

Save (Ctrl+O, Enter, Ctrl+X). **Do not** commit `.env`; it’s already in `.gitignore`. You can copy from the repo’s `.env.example` (no secrets in it) and then edit: `cp .env.example .env` then `nano .env`.

Generate a strong `SECRET_KEY` locally if you like:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 6. Create the Web app and WSGI

1. Open the **Web** tab and click **Add a new web app**.
2. Choose **Manual configuration** (not the “Flask” wizard) and pick the same Python version as your virtualenv (e.g. 3.10).
3. After it’s created:
   - **Virtualenv:** Click the link, enter `tei-edit` (or the full path, e.g. `/home/YOUR_USERNAME/.virtualenvs/tei-edit`), and save.
   - **WSGI configuration file:** Click the WSGI file link (e.g. `/var/www/yourusername_pythonanywhere_com_wsgi.py` or similar).

4. Edit the WSGI file. **Replace its contents** with the config below, and fix the path:

```python
import os
import sys

PROJECT_HOME = '/home/YOUR_USERNAME/tei-helper'   # <-- change YOUR_USERNAME
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_HOME, '.env'))
except ImportError:
    pass

os.environ.setdefault('TEI_HELPER_WEB', '1')

from app import app as application
```

Save the file.

5. In the Web tab, click **Reload** for your web app.

You should see the app at `https://YOUR_USERNAME.pythonanywhere.com` (or the URL shown there).

---

## 7. Static files (optional but recommended)

In the **Web** tab, in the **Static files** section, add:

| URL           | Directory                          |
|---------------|------------------------------------|
| `/static/`    | `/home/YOUR_USERNAME/tei-helper/static` |

This serves CSS/JS from disk instead of through Flask. Uploads are still served by the app.

---

## 8. Scheduled task (cleanup)

To match the privacy policy (delete old uploads and sessions):

1. Open the **Tasks** tab (or “Schedule” on paid accounts).
2. Add a **daily** or **hourly** task:
   - **Command:**  
     `$HOME/.virtualenvs/tei-edit/bin/python $HOME/tei-helper/scripts/cleanup_sessions_and_uploads.py --quiet`  
     (If your virtualenv path is different, run `which python` in a Bash console with the venv active and use that path.)
   - Set the same env as the app (e.g. put `export TEI_HELPER_WEB=1` and `export SECRET_KEY=...` in a small script that then runs the Python command, and call that script from the task; or set env in the task if the UI allows it.)

On free accounts, scheduled tasks may be limited; use the highest frequency you’re allowed (e.g. daily).

---

## 9. Use your own domain (paid account only)

Custom domains (e.g. `www.yourdomain.com`) require a **paid** PythonAnywhere plan.

1. **Upgrade** to a paid account if you haven’t.
2. **Web** tab → **Add a new web app** (or use “Add domain” for an existing app). When asked for the domain, enter the **full** name: **`www.yourdomain.com`** (not `yourdomain.com`).
3. PythonAnywhere will show a target like **`webapp-XXXX.pythonanywhere.com`**.
4. **At your domain registrar** (where you bought the domain), add a **CNAME** record:
   - **Name / Host / Alias:** `www`
   - **Target / Value / Points to:** `webapp-XXXX.pythonanywhere.com` (the value from the Web tab)
5. Wait for DNS (minutes to a few hours). On the Web tab, PythonAnywhere will show when the CNAME is correct.
6. **HTTPS:** In the Web tab, open **SSL** and request a certificate (e.g. Let’s Encrypt) for `www.yourdomain.com`. Then enable **Force HTTPS**.
7. **Naked domain:** If you want `yourdomain.com` (without `www`) to work, set a redirect from `yourdomain.com` to `www.yourdomain.com` at your registrar (or use PythonAnywhere’s “Naked domain” help if they offer it).

Detailed instructions: [PythonAnywhere – Custom domains](https://help.pythonanywhere.com/pages/CustomDomains/).

---

## 10. Checklist

- [ ] Code in `/home/YOUR_USERNAME/tei-helper`
- [ ] Virtualenv created, `pip install -r requirements.txt` and `pip install python-dotenv`
- [ ] `.env` with `TEI_HELPER_WEB=1` and `SECRET_KEY` (and optional privacy vars)
- [ ] Web app: Manual config, virtualenv set, WSGI file loads `.env` and does `from app import app as application`
- [ ] Reload web app; test at `yourusername.pythonanywhere.com`
- [ ] Static files: `/static/` → project `static` folder
- [ ] Task: run `scripts/cleanup_sessions_and_uploads.py` daily/hourly
- [ ] (Paid) Domain: CNAME `www` → `webapp-XXXX.pythonanywhere.com`, SSL and Force HTTPS

If you see **502** or **504**: check the **Error log** on the Web tab; usually the WSGI file path is wrong, the virtualenv is wrong, or `SECRET_KEY` is missing and the app raises at import.
