# Changelog

All notable releases of LC-Seq are documented here.

## [2.0.0] - 2026-07-05

Major release: Library Analysis, pedigree and lineage workflows, split-tree visualization, and export bundle — built on the Rust `lcseq` analysis engine with Python fallbacks where noted.

### Features

#### Spreadsheet and DEL library setup
- Configure Spreadsheet: BB position columns, null token, library cycle count, optional **BB index CSV** (UTF-8 / Excel) with validation
- Named spreadsheet presets (`config/configs/`, local only)
- Saved configurations round-trip through `SpreadsheetConfig`

#### Chromatogram database and visualizer (from 1.0.0, refined)
- Index and full SQLite database builds under `output/databases/`
- Multi-compound overlay plots, metadata search, plot export (PNG, PDF, SVG)

#### Peak analysis
- **Modern** negative-binomial peak picker (Rust when built; Python fallback with parity check)
- **Old-school** Gaussian peak picker (scipy; used in the accompanying *J. Med. Chem.* paper; Rust path for pedigree when extension is rebuilt)
- Peak Analysis panel: integration bounds, prominence, engine label (`lcseq (Rust)` vs `Python fallback`)

#### Library Analysis (formerly Library Data)
- Library-wide scan: signal quality, metrics, fraction plots, session cache (`scan.pkl`)
- **RT assignment** — **Direct pick** (paper Methods) or **Pedigree** (post-paper improvement)
- **Pedigree analysis** — null-truncation pedigree via Rust `evaluate_library`; pass/fail per tier; CSV and tree PNG/SVG/PDF export
- **Lineage analysis** — per-class diagnostics (`diagnose_class`) with matplotlib overlays
- **Split-tree visualization** — combinatorial tree build after RT assignment (Pedigree or Direct pick), pass-rate coloring, branch views
- **Export analysis bundle** — products CSV, audit metadata, summary/flagged building blocks, optional product prominence, Excel saturation grids (background export + progress UI)
- Library report PDF (pedigree and/or split-tree sections)

#### Help
- In-app Help topics for peak picking, pedigree, lineage, split-tree / export bundle, signal quality, and glossary
- Markdown rendering in the Help window (headings, tables, bold, code)

### Analysis engine

- **Rust `lcseq` extension** bundled in the Windows release zip (pedigree and lineage work without a user Rust install)
- **Python fallback** peak picker in source installs when the extension is missing or fails startup parity check
- **Graphviz** (optional): high-quality pedigree radial layout; matplotlib tier-ring fallback when `dot` is not on PATH

### Windows executable

- PyInstaller one-folder build (`LC-Seq.exe`); versioned zip `LC-Seq-v2.0.0-windows.zip`
- Release zip contains only `dist/LC-Seq/` (exe + bundled runtime) — not the full git tree, tests, or dev scripts

### Windows install (SmartScreen / antivirus)

LC-Seq is **not code-signed**. On first launch, Windows Defender SmartScreen may show **“Windows protected your PC”** or **“Unknown publisher”**. This is expected for unsigned academic software.

1. Extract the **entire** zip (keep `LC-Seq.exe` and `_internal/` in the same folder).
2. Double-click `LC-Seq.exe`.
3. If SmartScreen blocks the app: **More info** → **Run anyway**.

Some third-party antivirus tools may flag PyInstaller bundles or the bundled Rust extension (`lcseq._native`). If quarantined, restore the file and allowlist the extracted `LC-Seq` folder. The project is open source; build steps are in [dev/BUILD.md](dev/BUILD.md).

No Rust or Python install is required for the release zip.

### Documentation

- [dev/LC-Seq-New-master-ANALYSIS.md](dev/LC-Seq-New-master-ANALYSIS.md) — Rust engine integration guide
- Updated in-app help under `src/help/`
- [dev/INSTALL.md](dev/INSTALL.md), [dev/BUILD.md](dev/BUILD.md), [dev/RELEASE.md](dev/RELEASE.md)

### Known limitations

- Windows-first; packaged build tested on Windows 10/11 x64
- Release zip bundles `lcseq` (Rust) — maintainers need Rust only when **building** the zip, not end users
- No automated GUI smoke tests; manual QA recommended for BB index CSV, pedigree ↔ DEL numbering, and export bundle on large libraries
- Split-tree visualization and export logic are Python (`src/core/del_cycle_tree/`); only peak picking inside that path uses the Rust engine when available
- Very large libraries: full scan and grid export can take significant time and disk; session caches grow under `output/library_data/`

## [1.0.0] - 2026-05-19

First public release (companion to publication).

### Features

- Load and configure CSV/Excel chromatogram spreadsheets
- Index and full SQLite database builds with managed `output/databases/` storage
- Chromatogram visualizer: multi-compound overlay plots, count-series toggles, trace focus
- Metadata search with visual query builder and virtual result list
- Plot export (PNG, PDF, SVG)
- Saved spreadsheet configurations and application settings

### Windows executable

- PyInstaller one-folder build (`LC-Seq.exe`, ~118 MB installed)
- Fast startup; no Python required on target machines
- User data (`config/`, `output/`, `logs/`) stored beside the executable

### Documentation

- README (workflow, data formats, contact)
- [dev/INSTALL.md](dev/INSTALL.md), [dev/BUILD.md](dev/BUILD.md), [dev/CONFIGURATION.md](dev/CONFIGURATION.md)

### Known limitations

- Windows-first; packaged build is tested on Windows 10/11 x64
- Executable uses its own data directory (see INSTALL.md)
- Very large spreadsheets: prefer index databases; full DB builds can take time and disk space

[2.0.0]: https://github.com/brodohfasho/LC-Seq/releases/tag/v2.0.0
[1.0.0]: https://github.com/brodohfasho/LC-Seq/releases/tag/v1.0.0
