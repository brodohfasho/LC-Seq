# LC-Seq v2.0 Release Checklist

Companion soft release for the *Journal of Medicinal Chemistry* paper. Use this before tagging **v2.0.0** and publishing the Windows zip.

---

## Critical — before an official v2.0 release

### Version, changelog, and GitHub release
- [x] Confirm `src/__init__.py` `__version__` is `2.0.0` (and matches the zip / tag name)
- [x] Confirm `CHANGELOG.md` `[2.0.0]` lists every user-facing feature that appears in the paper or README
- [x] Confirm known limitations in `CHANGELOG.md` are honest (Windows-first, unsigned exe, optional Graphviz, large-library runtime/disk)
- [x] Confirm `main` on GitHub matches the release commit you intend to tag
- [ ] Create annotated tag `v2.0.0` and GitHub Release; upload `LC-Seq-v2.0.0-windows.zip` *(you — browser, after zip is built)*
- [ ] Paste SmartScreen / antivirus guidance into the GitHub Release body (see `docs/RELEASE.md`) *(you — with the release)*

### Automated quality gates
- [x] `pytest tests/` is fully green on the release commit *(228 passed after Graphviz API fix)*
- [x] Rebuild Rust extension (`maturin develop --release` in `LC-Seq-New-master/`) and pass `tests/test_lcseq_backend_parity.py`
- [ ] Confirm packaged build reports Rust engine in Peak Analysis (`lcseq (Rust)`, not Python fallback) after a clean `build_windows.ps1` *(you — after Windows package build)*

### Windows package (clean-machine proof)
- [ ] Run `scripts/build_windows.ps1` then `scripts/package_release.ps1` on a clean Windows build environment
- [ ] Zip contains only `dist/LC-Seq/` (exe + `_internal/`) — no tests, venv, notebooks, or personal configs
- [ ] On a machine **without** the repo or Python: download zip → extract whole folder → launch `LC-Seq.exe`
- [ ] Record exact SmartScreen / AV prompts and adjust release notes if wording differs

### End-to-end smoke test (source *and* packaged exe)
Use a real DEL library spreadsheet representative of the paper workflow:

- [ ] Load spreadsheet → Configure (compound ID, chromatogram parsing, metadata)
- [ ] Configure DEL fields: BB columns, null token, cycle count; optional BB index (UTF-8 **and** Excel); Validate → Accept
- [ ] Save named preset → reload preset → confirm BB index path and mappings persist
- [ ] Build index DB → open Chromatogram Visualizer → search → plot → export PNG/PDF/SVG
- [ ] Run Library Analysis scan (signal quality on); confirm metrics/plots; cancel mid-scan once and confirm clean recovery
- [ ] Run Pedigree analysis → tier slider → export CSV + tree (with Graphviz installed **and** without it)
- [ ] Run Lineage on a selected class → confirm overlays export
- [ ] Run Split-tree visualization → full tree + branch views → pass-rate coloring responds to cutoff
- [ ] Export analysis bundle → confirm core CSVs/XLSX, audit metadata, `grids/`, flagged BBs; spot-check grid colors
- [ ] Generate library report PDF: pedigree-only, DEL-only, and both sections
- [ ] Switch to a second database / library and confirm pedigree, DEL tree, and exports do not retain stale labels/data

### Paper-facing correctness (airtight)
- [x] Pedigree and split-tree BB numbering agree after full-library scan (and after restoring a pedigree/session snapshot without a full re-scan)
- [x] Non-ASCII BB names (e.g. β characters) survive configure → tree labels → CSV/Excel export end-to-end
- [x] Engine label and analysis outputs match what the paper Methods claim (Rust when bundled; Graphviz optional; Python fallback documented) *(help/docs note: paper = Old-school + Direct pick; Modern/Pedigree are post-paper)*
- [x] Example or documented data paths in README / INSTALL / CONFIGURATION match the shipped UI labels (Library Analysis, etc.)
- [x] No personal configs, session outputs, or databases under `output/` are committed (`config/configs/`, `scan.pkl`, plot PNGs, etc. remain gitignored)

### Docs must match the shipped product
- [x] `README.md` install link points at the v2.0.0 zip and describes the full DEL workflow
- [x] `docs/INSTALL.md` covers first-run, SmartScreen, Graphviz optional note, and Library Analysis path
- [x] `docs/CONFIGURATION.md` covers BB columns, null token, cycle count, and BB index CSV
- [x] `docs/RELEASE.md` smoke list includes pedigree, split-tree, and export bundle (not only basic visualizer)
- [x] In-app Help topics open and render for peak picking, pedigree, lineage, split-tree / export bundle, signal quality, and glossary

---

## Optional — QoL, polish, and “dot the i’s”

### User experience & UI consistency
- [x] Add Help topics dedicated to Library Analysis dashboard overview and DEL-library setup checklist (BB → validate → accept)
- [x] Audit every long-running action for cancel / progress parity (scan, pedigree, split-tree build, all exports)
- [x] Standardize busy overlays and error dialogs (encoding failures, index mismatches, missing Graphviz)
- [ ] Soften first-run friction: short “DEL library setup” path from main or Library Analysis
- [ ] Clarify report PDF prerequisites in UI when only pedigree or only split-tree sections are available
- [ ] Optional analysis-bundle toggles (e.g. skip saturation grids; pass-rate threshold for flagged BB CSVs)

### Documentation polish
- [x] Align INSTALL / CONFIGURATION / APPLICATION_WORKFLOW wording with paper figure captions and term choices
- [x] Add a short “reproducing paper analyses” note (settings that matter: null token, cycle count, picker mode, pass cutoffs) *(in-app help + README / CHANGELOG / workflow)*
- [x] Document session folder layout and approximate disk use for large libraries (`output/library_data/`) *(INSTALL.md first-run table)*
- [x] Document moving `.session` folders between machines (what travels, what doesn’t) *(INSTALL.md)*
- [x] Trim or archive completed roadmap phases so `docs/ROADMAP.md` reflects post-2.0 priorities only
- [x] Maintain a concise architecture / data-flow page (spreadsheet → DB → scan → pedigree → split-tree → exports) *(APPLICATION_WORKFLOW.md)*
### Interface & maintainability (non-blocking)
- [ ] Split `library_data_window.py` into tab/panel modules for easier review and future fixes
- [ ] Reduce duplicate DEL analysis paths; document the single source of truth
- [ ] Add GitHub Actions CI: `pytest` on push/PR; optional Windows job with maturin + parity
- [ ] Add lint/type-check gate on `src/core` (`ruff` and/or `mypy`)
- [ ] Improve library-scan performance messaging (ETA / chunk progress) on large DELs
- [ ] Profile and document typical runtimes for paper-sized libraries (scan, pedigree, full grid export)

### Nice-to-have scientific extras
- [ ] Ship or link a small anonymized example spreadsheet + BB index for install verification
- [ ] Freeze a “methods defaults” preset name/docs alignment with the paper’s analysis parameters
- [ ] Capture checksum / file list of the release zip in RELEASE notes for integrity checking
- [ ] Code-sign the Windows executable if institutional signing becomes available (removes SmartScreen friction)
