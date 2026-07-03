# LC-Seq Release Checklist

Prepared for the next release after Library Data, pedigree/split-tree, lineage, DEL-cycle analysis, and DEL export bundle work. **No code changes were made** — this is a triage guide only.

**Current snapshot (2026-07-03):**

| Item | Status |
|------|--------|
| `__version__` | `1.0.0` (unchanged since May 2026 public release) |
| Test suite | **196 passed**, 1 skipped (`pytest tests/`) |
| Line coverage | ~**31%** overall (`pytest` + `--cov=src`) |
| CI / GitHub Actions | **None** configured |
| Largest module | `src/ui/library_data_window.py` (~5,500 lines) |

---

## Part 1 — Potential files to remove or stop tracking

> **Important:** The **test suite should not be removed.** Tests are non-essential for *end-user runtime* but essential for release confidence. Below, “remove” means from the **git repo** and/or **release zip**, not “delete testing as a practice.”

### P0 — Remove from git (dev artifacts; bloat / wrong place)

These are tracked today but are not source code. They inflate clones and confuse history.

| Path | Why |
|------|-----|
| `output/library_data/**` (PNGs, JSON snapshots, `scan.pkl`, report assets) | Local session outputs; ~80+ files. Should live only on disk beside the app. |
| `output/pedigree_analysis/.session/**/*.png` | Same — generated pedigree previews. |
| `_pedigree_analysis_out.json` (repo root) | One-off debug/export output. |
| `docs/Untitled` | Empty / stray editor buffer. |

**Recommended follow-up:** Extend `.gitignore` with e.g. `output/library_data/`, `output/pedigree_analysis/`, `output/**/*.pkl`, `output/**/*.png`, `output/**/*.json` (keep `output/databases/.gitkeep` only).

### P1 — Archive or move out of main tree (historical / personal)

| Path | Why | Suggested action |
|------|-----|------------------|
| `old-school/*.ipynb` (5 notebooks) | Pre-app Jupyter prototypes (`Null_Tree_Analysis`, chromatogram plotting, etc.). Logic largely ported into `src/`. | Move to `docs/archive/notebooks/` or external archive repo; remove from default clone. |
| `config/configs/Atta.json`, `config/configs/Brodoh.json` | Personal spreadsheet presets (gitignored pattern is `config/*.json` but these are **tracked**). | Untrack; keep locally or document as examples under `config/examples/`. |
| `docs/INTEGRATION_PLAN_LCSEQ_ANALYSIS.md` | ~1,100-line implementation plan; most items are **done**. | Archive or replace with a short “Architecture” doc; keep only if agents/devs still reference it. |
| `docs/LC-Seq-New-master-ANALYSIS.md` | Rust engine inventory; useful for devs, stale risk. | Keep for devs; exclude from user-facing release notes. |
| `docs/AGENT_INSTRUCTIONS.md` | AI/agent workflow only. | Keep in repo; exclude from release zip. |

### P2 — Dev-only scripts (keep in repo; exclude from release zip)

| Path | Purpose |
|------|---------|
| `scripts/assess_peak_picker_compound.py` | One-off compound peak-picker debugging (hardcoded compound ID). |
| `scripts/full_fraction_nonzero_coverage.py` | Ad-hoc library coverage CLI. |
| `LC-Seq-New-master/scripts/extract_real_fixture.py` | Rust fixture extraction for tests. |

### Keep — required for build, runtime, or quality

| Path | Role |
|------|------|
| `tests/` (40 modules) | Regression safety; **196 tests** covering parsing, pedigree, DEL tree, export, metrics, etc. |
| `scripts/build_windows.ps1`, `scripts/package_release.ps1`, `scripts/pyi_rth_mpl_tkagg.py` | Windows release build. |
| `LC-Seq-New-master/` | Rust `lcseq` engine (peak picking, pedigree kernel). |
| `htmlcov/` | Already gitignored; local coverage reports only. |
| `docs/INSTALL.md`, `docs/BUILD.md`, `docs/RELEASE.md`, `docs/DEVELOPER_SETUP.md` | Release and onboarding. |
| `src/help/*.md` | In-app Help topics. |

### Tests — gaps (add, don’t remove)

Coverage is thin on UI and some integration paths. Notable **missing or light** areas:

- No automated tests for `src/ui/library_data_window.py` (largest surface area).
- No end-to-end GUI smoke test.
- DEL export bundle: covered (`tests/test_del_cycle_export.py`); good recent addition.
- BB index CSV / Configure Spreadsheet UI: partial (`tests/test_bb_index_csv.py` only).

---

## Part 2 — Pre-release upgrades (triaged)

Priorities: **P0** = before tagging release · **P1** = strongly recommended · **P2** = foundational / next milestone.

---

### P0 — Release blockers

#### Versioning & changelog
- [ ] Bump `src/__init__.py` `__version__` (suggest **2.0.0** — pedigree, lineage, Library Data, DEL-cycle, and export bundle are major additions since 1.0.0).
- [ ] Add `[2.0.0]` section to `CHANGELOG.md` (feature list, Rust vs Python fallback note, known limits).
- [ ] Update README “Install” link and feature list (still describes **v1.0.0** zip and omits most new workflows).

#### Repository hygiene
- [ ] Stop tracking generated files under `output/` (see Part 1).
- [ ] Confirm `.gitignore` covers session pickles, plot PNGs, report assets, local CSV/XLSX exports.
- [ ] Remove or untrack personal config JSONs under `config/configs/`.

#### Release build verification (`docs/RELEASE.md`)
- [ ] Run `scripts/build_windows.ps1` + `scripts/package_release.ps1` on a clean Windows VM.
- [ ] Fresh-machine test: load spreadsheet → configure (incl. BB columns + optional index CSV) → index/full DB → visualizer → **Library Data** scan → pedigree → DEL cycle → **Export DEL cycle bundle**.
- [ ] Document SmartScreen / antivirus expectations in release notes.
- [ ] Decide release strategy for **Rust extension**: ship with `lcseq` built-in vs document Python fallback-only build (performance + parity implications).

#### Quality gate
- [ ] Full `pytest tests/` green on release branch.
- [ ] Run `tests/test_lcseq_backend_parity.py` after `maturin develop --release`.
- [ ] Manual pass on BB index CSV with **UTF-8 / Excel** and special characters (e.g. βHomoleu).
- [ ] Manual pass: configure spreadsheet → validate index → **Accept configuration** (recent bug fix area).

---

### P1 — Performance

| Area | Issue | Upgrade |
|------|--------|---------|
| **Library scan** | Full-library signal quality + metrics can take minutes on large DEL libraries. | Profile scan pipeline; ensure progress/cancel on all heavy steps; consider batching/compound chunk tuning in `library_metrics` / `library_signal_quality`. |
| **Pedigree analysis** | Rust kernel is fast; UI still blocks during tree render / Graphviz / matplotlib fallbacks. | Already uses workers for main run; audit remaining synchronous paths in `pedigree_render.py` / export. |
| **DEL cycle tree build** | Rebuilds on DEL button / view switch. | Cache invalidation is intentional; document when rebuild is required; avoid redundant rebuilds on tab switch if any remain. |
| **DEL export bundle** | 32+ `.xlsx` grid files — CPU/disk heavy. | **Done:** background thread + progress UI. **Next:** optional “skip grids” or parallel grid writes for very large libraries. |
| **SQLite / session** | `scan.pkl` session files can grow large. | Document disk use; consider compression or storing only metrics hashes for restore validation. |
| **Monolithic UI** | `library_data_window.py` ~5,500 lines. | Hard to optimize or test; split into pedigree / DEL / metrics submodules (P2 refactor enables perf work). |

---

### P1 — User experience

| Area | Gap | Upgrade |
|------|-----|---------|
| **Help system** | No Help topics for **Library Data** dashboard, **DEL-cycle analysis**, **DEL export bundle**, or **BB index CSV**. | Add `src/help/del_cycle_analysis.md`, `library_data.md`; register in `help_content.py`. |
| **README / INSTALL** | Workflow stops at basic visualizer + one Library Data bullet. | Document full DEL workflow: BB columns → pedigree → DEL cycle → export bundle folder layout. |
| **Configure Spreadsheet** | Multi-step wizard is powerful but dense. | Short “DEL library setup” checklist in UI or help (null token, BB columns, index CSV, validate, accept). |
| **Busy / cancel consistency** | Scan, pedigree, DEL build, export use loading overlay; some exports (pedigree CSV, tree PNG) may still block briefly. | Audit all export buttons; standardize on worker + progress. |
| **Error messages** | Encoding / index mismatch can confuse users. | Surface UTF-8 / Excel guidance in validation box (partially done for BB index). |
| **Report export** | Split pedigree vs DEL-cycle sections — new. | User doc: what each PDF section contains; prerequisites when only one analysis was run. |
| **First-run** | No guided path for DEL-specific libraries. | Optional welcome link to help topics from Library Data tab. |

---

### P1 — Documentation

| Doc | Action |
|-----|--------|
| `CHANGELOG.md` | Major update for 2.0. |
| `README.md` | Features, workflow, system requirements (Graphviz optional, Rust optional). |
| `docs/INSTALL.md` | Library Data, pedigree, DEL-cycle, export bundle. |
| `docs/CONFIGURATION.md` | BB columns, null token, cycle count, BB index CSV. |
| `docs/ROADMAP.md` | Mark phases 15+ complete; trim or move historical phase checklist to archive. |
| `docs/DEVELOPER_SETUP.md` | Already good for Rust/maturin; add “run full test suite before release.” |
| `docs/RELEASE.md` | Extend smoke test for DEL + export bundle. |
| In-app help | See UX table above. |

---

### P1 — Bugs & risk areas (manual + automated focus)

| Risk | Notes |
|------|--------|
| **Rust vs Python picker drift** | Parity test exists; must run before release build. UI shows engine label — verify in packaged exe. |
| **Pedigree ↔ DEL numbering** | Fixed via shared index build from full library; regression-test when loading pedigree snapshot without re-scan. |
| **Graphviz optional** | Tier-ring matplotlib fallback vs native split-tree; test both paths in release QA. |
| **State when switching databases** | Clear pedigree/DEL/session when DB changes; verify no stale tree labels or export from wrong library. |
| **Spreadsheet config persistence** | BB index map round-trip (`SpreadsheetConfig`); test save/load preset with index CSV path. |
| **Unicode BB names** | Tree labels, CSV export, index validation; test non-ASCII BB names end-to-end. |
| **31% coverage** | High bug risk in untested UI paths; prioritize manual QA checklist over deleting tests. |

---

### P2 — Foundational (post-release or parallel if time)

#### Engineering
- [ ] **GitHub Actions CI**: `pytest` on push/PR; optional job with `maturin develop` + parity tests on Windows runner.
- [ ] **Split `library_data_window.py`** into tab modules (`pedigree_panel`, `del_cycle_panel`, `metrics_panel`, export handlers).
- [ ] **Reduce duplicate analysis paths** (`del_cycle_tree/analyzer.py` vs `notebook_analyzer.py` — document single source of truth).
- [ ] **Type checking / lint** in CI (`ruff` or `mypy` on `src/core`).

#### Product
- [ ] **Session portability**: document moving `.session` folders between machines.
- [ ] **Export conventions**: standard output folder naming under `output/library_data/`.
- [ ] **Optional DEL export settings**: skip grids, pass-rate threshold for summary/flagged CSVs.

#### Documentation / planning
- [ ] Replace long `INTEGRATION_PLAN` with maintained **Architecture** (data flow: spreadsheet → DB → scan → pedigree → DEL tree → exports).
- [ ] **`release_checklist.md`** → fold recurring items into `docs/RELEASE.md` after first use.

---

## Part 3 — Suggested manual QA script (pre-tag)

Use as a minimum bar before `v2.0.0`:

1. **Spreadsheet** — Load real DEL library XLSX; configure BB1–BB3, null token, time/count, metadata.
2. **BB index** — Load UTF-8 or `.xlsx` index; validate; accept configuration; save preset; reload preset.
3. **Database** — Build index DB; open visualizer; search/plot sample compounds.
4. **Library scan** — Run with signal quality options; confirm metrics + plots; cancel mid-scan once.
5. **Pedigree** — Run analysis; tier slider; export CSV + tree PNG/SVG.
6. **DEL cycle** — Run DEL cycle analysis (not during pedigree); full tree + BB1 branch views; pass % cutoff coloring.
7. **DEL export** — Export bundle to folder; confirm 4 CSV/XLSX core files + `grids/`; open flagged building blocks CSV; spot-check saturated grid colors.
8. **Report PDF** — Generate with pedigree-only, DEL-only, and both sections.
9. **Packaged exe** — Repeat steps 1–4 (and ideally 6–7) on release zip without Python installed.

---

## Part 4 — What not to do before release

- **Do not delete `tests/`** to “clean up” — coverage is already modest.
- **Do not remove `LC-Seq-New-master/`** — required to build the Rust engine.
- **Do not remove build scripts** — required for Windows release.
- **Do not commit** new `output/` session data or local database files.
- **Avoid large refactors** (e.g. full UI split) in the same release branch as bug fixes unless schedule allows hard QA.

---

## Summary recommendation

**Minimum path to release:** P0 hygiene (untrack `output/`, version bump, changelog, README/INSTALL/help for new features) + full manual QA script + Windows package smoke test.

**Highest ROI after that:** CI with pytest, Help topics for DEL/Library Data, and splitting `library_data_window.py` for maintainability.

**Safe cleanup wins:** Remove tracked artifacts in `output/`, root `_pedigree_analysis_out.json`, `docs/Untitled`, and archive `old-school/` notebooks — no impact on application behavior.
