# Installing LC-Seq (Windows executable)

Use this guide if you downloaded **`LC-Seq-*-windows.zip`** from [GitHub Releases](https://github.com/brodohfasho/LC-Seq/releases). You do **not** need Python or Rust installed.

## Requirements

- Windows 10 or 11 (64-bit)
- ~150 MB free disk space for the app folder (more for your spreadsheets and SQLite databases)

The release zip includes the pedigree analysis engine (`lcseq`) precompiled — no separate Rust install.

## Steps

1. **Download** the latest `LC-Seq-vX.Y.Z-windows.zip` from the [Releases](https://github.com/brodohfasho/LC-Seq/releases) page.

2. **Extract** the zip to a folder you can keep (e.g. `C:\Tools\LC-Seq` or `Documents\LC-Seq`).  
   Do not run the app from inside the zip viewer—extract first.

3. **Open** the extracted folder. You should see `LC-Seq.exe` and an `_internal` folder.

4. **Launch** `LC-Seq.exe`.  
   - Windows may show “Windows protected your PC” for unsigned academic software. Choose **More info** → **Run anyway**.

5. **Optional:** Right-click `LC-Seq.exe` → **Create shortcut** → move the shortcut to the Desktop.

## First run

The app creates data folders **next to the executable**:

| Folder | Purpose |
|--------|---------|
| `config\` | Settings and saved spreadsheet configurations |
| `output\databases\` | SQLite databases you create or load |
| `logs\` | Log file (if enabled) |

These are separate from a developer install cloned from GitHub. Copy your own `config\` or `output\databases\` into this folder if you are migrating from a source install.

## Basic use

See the [README](../README.md) sections **What it does**, **Basic workflow**, and **Data file requirements**.

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| **“Windows protected your PC”** (SmartScreen) | Expected for unsigned software. **More info** → **Run anyway**. LC-Seq is open source — see [BUILD.md](BUILD.md) for how the zip is built. |
| **Antivirus blocked or deleted files** | Restore from quarantine; add an exclusion for the extracted `LC-Seq` folder. PyInstaller apps and native `.pyd` extensions are sometimes flagged heuristically. |
| App won’t start | Extract the full zip; keep `_internal` beside `LC-Seq.exe`. |
| “Missing DLL” | Install [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) (x64), then retry. |
| Blank window | Re-download the zip; rebuild from source only if you are a developer ([BUILD.md](BUILD.md)). |
| Old databases not visible | Databases must live in `output\databases\` next to **this** `LC-Seq.exe`, not in a Git clone elsewhere. |

## Install from source (developers)

If you prefer Python over the zip, see [README — Quick start (from source)](../README.md#quick-start-from-source).
