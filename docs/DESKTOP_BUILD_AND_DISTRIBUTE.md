# Desktop build and distribution

This doc covers building and distributing the TEI-edit desktop app for **Windows, macOS, and Linux**.

## Run locally (no build)

From the repo root, with dependencies installed (`pip install -r requirements.txt`):

```bash
python app.py
```

A local window opens; no browser needed. Use this for day-to-day testing — no need to push or build on GitHub.

## Test the built executable locally

To test the same kind of binary that gets shipped in a release (e.g. before you push a tag):

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller app.spec
```

Then run the output: `./dist/TEI-edit` (macOS/Linux) or `dist\TEI-edit.exe` (Windows). This uses the same `app.spec` as the GitHub workflow.

## Build executables (PyInstaller)

PyInstaller builds a **native binary for the OS you run it on**. To get builds for all three platforms, either use **GitHub Actions** (recommended) or build on each OS (or in VMs) yourself.

### Prerequisites (on the OS you’re building for)

- Python 3.10+
- Install deps and PyInstaller:

  ```bash
  pip install -r requirements.txt
  pip install pyinstaller
  ```

### Build on this machine

From the repo root:

```bash
pyinstaller app.spec
```

Output:

| OS      | Output path        |
|---------|---------------------|
| Windows | `dist/TEI-edit.exe` |
| macOS   | `dist/TEI-edit`     |
| Linux   | `dist/TEI-edit`     |

The bundle includes the app, templates, static files, `tags.json`, and `tei_layout_template.xml`. On first run the app creates an `uploads` and `flask_session` directory next to the executable if needed.

### Build for all three OSes via GitHub (on tag push)

1. Create and push a **version tag** (e.g. `v1.0.0`):
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
2. The **Build desktop** workflow runs automatically: it builds on Windows, macOS, and Linux, then **creates a release** for that tag and attaches:
   - **TEI-edit-Windows.exe**
   - **TEI-edit-macOS** (on macOS you may need to allow it in System Preferences → Security if it’s from an unidentified developer)
   - **TEI-edit-Linux**
3. Check the **Actions** tab for progress; when done, the new release and downloads appear under **Releases**.

No need to build locally or to draft a release in the UI; pushing the tag is enough.

### itch.io (optional)

1. Download the three artifacts from a GitHub release (or build them locally).
2. Create a project on [itch.io](https://itch.io), set kind to **Downloadable**.
3. Upload **TEI-edit-Windows.exe** for Windows, **TEI-edit-macOS** for macOS, and **TEI-edit-Linux** for Linux.
4. Add a short run instruction (e.g. “Download the file for your OS and run it”).

## .gitignore

Keep `app.spec` in the repo. Ignore build artifacts, e.g.:

- `dist/`
- `build/`

So do **not** add `*.spec` to `.gitignore`; the desktop workflow and local builds rely on `app.spec`.
