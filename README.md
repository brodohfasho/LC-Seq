# LC-Seq

Desktop application for loading chromatographic data from spreadsheets, building a searchable SQLite database, and analyzing DNA-encoded library (DEL) cyclic-peptide screens — from single-compound plots through pedigree null-truncation analysis and split-tree export bundles.

**Platform:** Windows (primary). Python 3.10+ recommended for development (Rust extension).

---

## Install (Windows executable)

**Recommended for most users:** download **`LC-Seq-v2.0.0-windows.zip`** from [GitHub Releases](https://github.com/brodohfasho/LC-Seq/releases), extract the whole `LC-Seq` folder, and run `LC-Seq.exe`. No Python or Rust install required — pedigree and lineage analysis are included in the zip.

Step-by-step instructions: **[dev/INSTALL.md](dev/INSTALL.md)**.

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

**Pedigree and lineage analysis** require the Rust `lcseq` extension — see **[dev/DEVELOPER_SETUP.md](dev/DEVELOPER_SETUP.md)** (`maturin develop` in `LC-Seq-New-master/`). Peak picking works with a Python fallback when Rust is not built.

On Linux/macOS, use `source venv/bin/activate` instead of `venv\Scripts\activate`.

---

## What it does

LC-Seq is built for large compound-by-compound chromatogram tables (e.g. DEL library screens). You point the app at a spreadsheet, define how each row’s chromatogram string is parsed (including building-block columns for DEL libraries), materialize a local database, then search, plot, and run library-wide analyses without re-reading the whole sheet each time.

**v2.0** adds pedigree null-truncation analysis, per-class lineage diagnostics, combinatorial split-tree visualization, and a multi-file analysis export bundle (CSVs, audit metadata, Excel saturation grids, optional PDF report).

The accompanying paper used **Old-school** peak picking with **Direct pick** RT assignment; **Modern** picking and **Pedigree** mode are later improvements (see in-app help).

---

## Basic workflow

### Core (all libraries)

1. **Load Spreadsheet** — CSV or Excel file.
2. **Configure Spreadsheet** — compound ID, chromatogram column, delimiters, time/count fields, metadata columns. Save named presets for reuse.
3. **Create / Load database** — under `output/databases/`:
   - **Index database** — metadata + raw chromatogram text; smaller; parses on plot.
   - **Full database** — all time/count points stored; larger; fastest repeat plotting.
4. **Chromatogram Visualizer** — compound list or metadata **Search**, overlay plots, **Peak Analysis** (modern or old-school picker), export plots (PNG/PDF/SVG).

### DEL library analysis (optional)

5. **Configure DEL fields** — BB1…BBn columns, null token, cycle count; optional **BB index CSV** for display indices; validate and accept configuration.
6. **Library Analysis** — library scan (signal quality, metrics, fraction plots); session cache under `output/library_data/`.
7. **Pedigree** — run null-truncation analysis (Pedigree RT assignment mode); tier slider; export CSV and pedigree figure (Graphviz or matplotlib fallback).
8. **Lineage** — per-class diagnostic plots for selected nodes.
9. **Split-tree** — combinatorial tree with pass-rate coloring; full-tree and BB1 branch views (after Pedigree or Direct pick RT assignment).
10. **Export analysis bundle** — folder with products CSV, audit metadata, summary/flagged building blocks, `grids/` Excel files, optional prominence CSV and PDF report.

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
| **DEL pedigree** | BB1…BBn columns (coupling order), null token, and cycle count in Configure Spreadsheet. |
| **BB index (optional)** | UTF-8 or Excel CSV mapping building-block names to display indices. |
| **Variants** | Optional variant column (e.g. linear vs cyclized) for multiple rows sharing one library ID. |

Delimiter and column mapping are data-specific—use **Configure Spreadsheet** preview to confirm parsing before building a database. Very large sheets are supported via chunked processing for full database builds.

---

## System notes

| Component | Release zip users | Source / dev installs |
|-----------|-------------------|------------------------|
| Windows 10/11 x64 | Yes | Yes |
| Rust toolchain | **Not needed** (bundled) | Needed once to `maturin develop` |
| Graphviz (`dot` on PATH) | Optional — better pedigree split-tree layout | Optional |
| Python + scipy | Not needed | Dev only — Python fallback peak picker |

---

## Future development

Planned and in-progress work is tracked in [dev/ROADMAP.md](dev/ROADMAP.md).

Maintainer docs (build, release, engine setup, etc.) live under **[dev/](dev/README.md)**.

---

## Contact

**Grant Koch** grantkoch2319@gmail.com — questions, bugs, or feature requests:

- Open a [GitHub Issue](https://github.com/brodohfasho/LC-Seq/issues) on this repository (preferred).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Building the executable (maintainers)

See [dev/BUILD.md](dev/BUILD.md) and [dev/RELEASE.md](dev/RELEASE.md). Package a release zip with `.\scripts\package_release.ps1` after `.\scripts\build_windows.ps1`.

## Development (optional)

```bash
pytest tests/
```

Maintainer docs (Rust engine, config formats, release process): **[dev/](dev/README.md)**. Changelog: [CHANGELOG.md](CHANGELOG.md).
