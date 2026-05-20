# LC-Seq

Desktop application for loading chromatographic data from spreadsheets, building a searchable SQLite database, and exploring compounds in an interactive chromatogram viewer (overlay plots, metadata search, export).

**Platform:** Windows (primary). Python 3.8+ for development.

---

## Install (Windows executable)

**Recommended for most users:** download **`LC-Seq-v1.0.0-windows.zip`** from [GitHub Releases](https://github.com/brodohfasho/LC-Seq/releases), extract, and run `LC-Seq.exe`. No Python install required.

Step-by-step instructions: **[docs/INSTALL.md](docs/INSTALL.md)**.

---

## Quick start (from source)

```bash
git clone https://github.com/brodohfasho/LC-Seq.git
cd LC-Seq
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m src.main
```

(Or `python src/main.py` from the repo root.)

On Linux/macOS, use `source venv/bin/activate` instead of `venv\Scripts\activate`.

---

## What it does

LC-Seq is built for large compound-by-compound chromatogram tables (e.g. DNA-encoded library screens). You point the app at a spreadsheet, define how each row’s chromatogram string is parsed, materialize a local database, then search and plot selected compounds without re-reading the whole sheet each time.

---

## Basic workflow

1. **Load Spreadsheet** — CSV or Excel file.
2. **Configure Spreadsheet** — compound ID column, chromatogram text column, delimiters, time/count fields, and metadata columns to index. Save the configuration for reuse.
3. **Create / Load database** — under `output/databases/`:
   - **Index database** — metadata + raw chromatogram text; smaller files; parses on plot.
   - **Full database** — all time/count points stored; larger files; fastest repeat plotting.
4. **Enter Chromatogram Visualizer** — compound list or metadata **Search**, load rows into the table, select rows to plot overlays, toggle count series, click traces to focus, **Export plot** (PNG/PDF/SVG).

The status line on the main window reflects load/configure/database state.

---

## Data file requirements

| Item | Requirement |
|------|-------------|
| **Formats** | `.csv`, `.xlsx`, `.xls` |
| **Layout** | One row per compound (or per variant if you configure a variant column). |
| **Compound ID** | Single column with a unique identifier per row (or per primary+variant pair). |
| **Chromatogram data** | One column containing encoded time/count series as text, split by delimiters you define in Configure (order matters). |
| **Metadata** | Optional additional columns; choose which to index for search. |
| **Variants** | Optional variant column (e.g. linear vs cyclized) for multiple rows sharing one library ID. |

Delimiter and column mapping are data-specific—use **Configure Spreadsheet** preview to confirm parsing before building a database. Very large sheets are supported via chunked processing for full database builds.

---

## Future development

Planned and in-progress work is tracked in [ROADMAP.md](ROADMAP.md). Post-release ideas (multi-panel views, additional export options, etc.) are listed under **Future Enhancements** there.

---

## Contact

**Grant Koch** grantkoch2319@gmail.com — questions, bugs, or feature requests:

- Open a [GitHub Issue](https://github.com/brodohfasho/LC-Seq/issues) on this repository (preferred).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Building the executable (maintainers)

See [docs/BUILD.md](docs/BUILD.md) and [docs/RELEASE.md](docs/RELEASE.md). Package a release zip with `.\scripts\package_release.ps1` after `.\scripts\build_windows.ps1`.

## Development (optional)

```bash
pytest
```

See [ROADMAP.md](ROADMAP.md) for phase history. Config file formats: [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Dependency notes: [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).
