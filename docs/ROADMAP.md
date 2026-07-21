# LC-Seq roadmap

**Status (v2.0):** Core chromatogram workflow, Library Analysis (scan, RT assignment, pedigree, split-tree, exports), and Windows packaging are shipped. See [CHANGELOG.md](../CHANGELOG.md).

Historical phase checklists from early development are archived in [archive/INTEGRATION_PLAN_LCSEQ_ANALYSIS.md](archive/INTEGRATION_PLAN_LCSEQ_ANALYSIS.md) and older notes under [archive/](archive/).

## Current product workflow

1. Load spreadsheet → **Configure Spreadsheet** (including DEL BB columns when needed)
2. Create or load a SQLite database under `output/databases/`
3. **Chromatogram Visualizer** — search, plot, Peak Analysis
4. **Library Analysis** — library scan, RT assignment (**Direct pick** or **Pedigree**), visualizations, exports

Paper Methods used **Old-school** peak picking with **Direct pick** RT assignment. **Modern** picking and **Pedigree** mode were added after submission (documented in in-app help).

## Near-term priorities

- [ ] Publish signed or clearly documented unsigned Windows zip for v2.0.0 (see [RELEASE.md](RELEASE.md))
- [ ] CI: `pytest` on push/PR; optional Windows job with `maturin` + parity
- [ ] Split large UI modules (e.g. `library_data_window.py`) for maintainability
- [ ] Optional analysis-bundle toggles (skip saturation grids; pass-rate thresholds)
- [ ] Example anonymized spreadsheet + BB index for install verification

## Longer-term ideas

- Session portability documentation (moving `.session` folders between machines)
- Additional Library Analysis metrics cards beyond the current QC set
- Code signing for the Windows executable when available

## References

| Doc | Audience |
|-----|----------|
| [README.md](../README.md) | Users — install and workflow |
| [INSTALL.md](INSTALL.md) | Users — Windows zip |
| [APPLICATION_WORKFLOW.md](APPLICATION_WORKFLOW.md) | Developers — data flow |
| [DEVELOPER_SETUP.md](DEVELOPER_SETUP.md) | Developers — Rust engine |
| [release_checklist.md](../release_checklist.md) | Maintainers — pre-tag QA |
