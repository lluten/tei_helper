# Deploy TEI-edit on PythonAnywhere (with your own domain)

Step-by-step for deploying TEI-edit on PythonAnywhere and connecting a domain you’ve already bought.

**Quick summary:** Get code onto PA (upload a zip of the `tei-helper` folder — no git/SSH needed) → create virtualenv, `pip install -r requirements.txt` + `python-dotenv` → create `.env` with `TEI_HELPER_WEB=1` and `SECRET_KEY` → Web tab: Manual config, set virtualenv, edit WSGI to load `.env` and `from app import app as application` → Reload. Then (paid) add domain: CNAME `www` → value from Web tab, enable HTTPS.

**Note:** Your own domain (e.g. `www.yourdomain.com`) requires a **paid** PythonAnywhere account. You can start on the free tier at `yourusername.pythonanywhere.com` to test, then add the domain after upgrading.

---

## Updating an existing deployment (no need to redo everything)

When you have new code (e.g. after changes locally), you only need to **replace the code** on PA. Do **not** redo virtualenv, .env, WSGI, or the domain.

1. **On your computer**, zip the project (same as in section 2): a zip whose top level is a folder `tei-helper` with all files inside, excluding `.git`, `.venv`, `__pycache__`. Do **not** put `.env` in the zip (it should not be in the repo).
2. On PythonAnywhere **Files** tab, upload that zip to your home directory.
3. In a **Bash** console run:
   ```bash
   cd ~
   unzip -o tei-helper.zip
   rm tei-helper.zip
   ```
   This overwrites the existing `~/tei-helper` files (e.g. `app.py`, `templates/`, `static/`) with the new ones. Your existing `.env` in `~/tei-helper` is **not** in the zip, so it is left unchanged.
4. In the **Web** tab, click **Reload** for your web app.

If you added new dependencies in `requirements.txt`, run `pip install -r requirements.txt` in your virtualenv (e.g. `workon tei-edit` then `pip install -r requirements.txt`) before reloading.

---

## 1. Account and project path

- Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free is fine to start).
- Note your **username**; your project will live at `/home/YOUR_USERNAME/tei-helper` (or another name you choose).

---

## 2. Get the code onto PythonAnywhere

**Option A: Upload a zip (no SSH or git needed)**

1. **On your computer**, create a zip that contains a single folder `tei-helper` with everything inside it, **without** `.git` (not needed on PA and wastes space):
   - Go to the **parent** of your project (e.g. if the project is in `Documents/tei-helper`, go to `Documents`).
   - **Windows:** In File Explorer, select the contents of `tei-helper` (not the folder itself), or use 7‑Zip/WinRAR “Add to archive” and exclude `.git`. Or zip the folder, then the next step (delete on PA) still works.
   - **macOS:** In Terminal, from the parent dir:  
     `zip -r tei-helper.zip tei-helper -x "tei-helper/.git/*" -x "tei-helper/.venv/*" -x "tei-helper/__pycache__/*" -x "*.pyc"`  
     (Or right‑click → Compress, then remove `.git` on PA after unzip.)
   - **Linux:** From the parent dir:  
     `zip -r tei-helper.zip tei-helper -x "tei-helper/.git/*" -x "tei-helper/.venv/*" -x "tei-helper/__pycache__/*" -x "*.pyc"`.
2. On PythonAnywhere, open the **Files** tab and go to your home directory (`/home/YOUR_USERNAME/`).
3. Click **Upload a file**, select `tei-helper.zip`, and wait for the upload to finish.
4. Open a **Bash** console (Consoles → Bash). Run:
   ```bash
   cd ~
   unzip tei-helper.zip
   rm tei-helper.zip
   ```
   You should now have `~/tei-helper/` with `app.py`, `requirements.txt`, `templates/`, `static/`, etc. inside it.
5. Check: `ls ~/tei-helper` should list `app.py`, `requirements.txt`, `templates`, `static`, `deploy`, `scripts`, `docs`.

**Option B: Git (if the repo is public and you’re okay with HTTPS or have SSH set up)**

- In a **Bash** console:
  ```bash
  cd ~
  git clone https://github.com/YOUR_USERNAME/tei-helper.git
  cd tei-helper
  ```

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
   - **Source code** (if the form asks for it): enter the path to your project directory, e.g. `/home/YOUR_USERNAME/tei-helper` (replace `YOUR_USERNAME` with your PythonAnywhere username).
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

## 7. Static files and uploads (so CSS and images work)

In the **Web** tab, in the **Static files** section, add **both** of these (replace `YOUR_USERNAME` with your PythonAnywhere username):

| URL           | Directory                                  |
|---------------|--------------------------------------------|
| `/static/`    | `/home/YOUR_USERNAME/tei-helper/static`     |
| `/uploads/`   | `/home/YOUR_USERNAME/tei-helper/uploads`   |

- `/static/` serves CSS and JS.
- `/uploads/` is where the app stores uploaded images/XML; mapping it here makes those files load correctly in the browser. If the `uploads` folder doesn’t exist yet, create it in a Bash console: `mkdir -p ~/tei-helper/uploads`.

---

## 8. Scheduled task (cleanup) — required for your legal text

**The 24-hour deletion is not automatic.** Your privacy page says uploads and session data are deleted after 24 hours. To actually do that, you must set up a scheduled task on PythonAnywhere; otherwise the promise in the legal text is not being kept.

1. Open the **Tasks** tab (Dashboard → Tasks; on paid accounts this may be under “Schedule”).
2. Add a new task:
   - **Command:**  
     `$HOME/.virtualenvs/tei-edit/bin/python $HOME/tei-helper/scripts/cleanup_sessions_and_uploads.py --quiet`  
     (Replace with your actual paths if different. Get the Python path by running `which python` in a Bash console with your virtualenv active.)
   - **Schedule:** Daily (or hourly if your plan allows). Running once per day is enough to keep the “deleted after 24 hours” promise, since the script deletes files older than 24 hours.

The script does not need `SECRET_KEY` or other app env vars; it only deletes files in `uploads/` and `flask_session/` older than 24 hours (or the value of `CLEANUP_MAX_AGE_HOURS` if you set it in the task’s environment).

**Note:** On **free** PythonAnywhere accounts, scheduled tasks may be unavailable (e.g. for accounts created in 2026). If you have no Tasks tab or cannot add a task, you either need a paid account to run the cleanup, or you must change the privacy text (e.g. to say data is deleted “when possible” or “periodically”) so it matches what actually happens. Do not promise 24-hour deletion in the legal text unless the cleanup task is running.

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
- [ ] **Scheduled task:** run `scripts/cleanup_sessions_and_uploads.py` daily (required for the “24h deletion” in your privacy text)
- [ ] (Paid) Domain: CNAME `www` → `webapp-XXXX.pythonanywhere.com`, SSL and Force HTTPS

If you see **502** or **504**: check the **Error log** on the Web tab; usually the WSGI file path is wrong, the virtualenv is wrong, or `SECRET_KEY` is missing and the app raises at import.
