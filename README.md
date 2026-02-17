# TEI-edit

Web app for editing and annotating TEI/PageXML documents (e.g. from Transkribus).

## Deploy on PythonAnywhere

1. Clone this repo (or upload the project) to your PythonAnywhere account.
2. Create a virtualenv, install dependencies: `pip install -r requirements.txt` and `pip install python-dotenv`.
3. Create a `.env` file in the project root with `TEI_HELPER_WEB=1`, `SECRET_KEY` (strong, ≥32 chars), and optionally `PRIVACY_CONTACT_EMAIL`, `PRIVACY_OPERATOR`. See `.env.example`.
4. In the Web tab: Manual configuration, set virtualenv, edit the WSGI file to load `.env` and `from app import app as application`. Reload.

Full step-by-step: **[docs/DEPLOY_PYTHONANYWHERE.md](docs/DEPLOY_PYTHONANYWHERE.md)**.

## Local run (development)

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
# No TEI_HELPER_WEB or SECRET_KEY needed for local; app runs in desktop mode
python app.py
```

Opens a local window (FlaskWebGUI). For web mode locally, set `TEI_HELPER_WEB=1` and `SECRET_KEY` in the environment and run `python app.py` or use a WSGI server.
