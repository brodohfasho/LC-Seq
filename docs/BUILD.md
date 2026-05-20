# Building LC-Seq for Windows (PyInstaller)

The packaged app is a **folder** with `LC-Seq.exe` you can pin to the taskbar or place a shortcut on the desktop. Double-click launches the GUI (no terminal window).

## Prerequisites

- Windows 10/11
- **Use the project virtual environment** with all runtime dependencies installed:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-build.txt
```

The build will fail fast if `customtkinter` is missing from the active Python environment.

## Build

From the repository root:

```powershell
.\scripts\build_windows.ps1
```

Or manually:

```powershell
pip install -r requirements-build.txt
pyinstaller lc_seq.spec --noconfirm
```

Output: `dist\LC-Seq\LC-Seq.exe` (plus `_internal\` support files).

## First run (packaged app)

- **`config/`** and **`output/databases/`** are created **next to `LC-Seq.exe`** (not inside `_internal`), usually:
  - `dist\LC-Seq\config\`
  - `dist\LC-Seq\output\databases\`
- This is **separate** from the folders used when you run from source (`LC-Seq\config\` and `LC-Seq\output\databases\` at the repository root). The `.exe` will look empty until you build or load databases there.

### Use existing dev data with the packaged app

Copy (or move) from the repo into the `dist\LC-Seq` folder:

- `config\` → `dist\LC-Seq\config\`
- `output\databases\*.db` → `dist\LC-Seq\output\databases\`

Then restart `LC-Seq.exe`. Paths inside `settings.json` that pointed at old absolute locations may need a one-time re-load of spreadsheet/database from the UI.

### Use the repo copy while developing

From the repository root with venv active:

```powershell
python -m src.main
```

That uses `config/` and `output/` at the **repo root**, not `dist\LC-Seq\`.

## Desktop shortcut

1. Open `dist\LC-Seq\`
2. Right-click `LC-Seq.exe` → **Show more options** → **Create shortcut**
3. Move the shortcut to the Desktop (or drag while holding Alt)

## Distribution zip

```powershell
.\scripts\package_release.ps1
```

Creates `release\LC-Seq-v1.0.0-windows.zip` (version from `src/__init__.py`). Upload that file to [GitHub Releases](https://github.com/brodohfasho/LC-Seq/releases). See [RELEASE.md](RELEASE.md).

## Troubleshooting

- **Missing DLL / import errors:** Rebuild on the same Windows architecture (64-bit) as the target machine; ensure `pip install -r requirements.txt` succeeded before building.
- **Blank window / matplotlib:** Rebuild after upgrading PyInstaller; the spec collects `customtkinter` and `matplotlib` data files automatically.
- **Logs:** `logs\lc_seq.log` next to the executable (after first run with file logging enabled).
