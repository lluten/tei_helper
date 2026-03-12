# TEI-edit

Desktop app for TEI annotation: link images, transcribe text, and export TEI XML.

## For users

### Download

1. Open the **Releases** page of this repository (on GitHub: repo → **Releases**).
2. Download the file for your system:
   - **Windows:** `TEI-edit-Windows.exe`
   - **macOS:** `TEI-edit-macOS` (if macOS blocks it: **System Preferences → Security & Privacy → Open Anyway**, or right‑click → Open)
   - **Linux:** `TEI-edit-Linux`
3. Run the file. A window opens; no browser or install needed.

### Using the app

- **New project:** paste image URLs or upload images, then start transcribing and adding TEI markup.
- **Export:** use the export option to save your work as TEI XML.
- Data is stored next to the app (e.g. `uploads/`, `flask_session/`). You can delete those folders to clear local data.

---

## For developers / building from source

### Run locally (no build)

```bash
pip install -r requirements.txt
python app.py
```

### Build executables

**Option A — Let GitHub build when you push a tag**

1. Commit and push your code.
2. Create and push a version tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. The **Build desktop** workflow runs and builds Windows, macOS, and Linux binaries, then creates a release and attaches them. Check the **Actions** tab, then the new release under **Releases**.

**Option B — Build on your machine**

On the OS you want to target (or a VM):

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller app.spec
```

- Windows → `dist/TEI-edit.exe`
- macOS / Linux → `dist/TEI-edit`
