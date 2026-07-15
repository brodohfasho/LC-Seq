# Publishing a GitHub release (maintainers)

Use this checklist for Phase 14.2–14.3 when shipping a new version.

## 1. Version bump

Update `__version__` in `src/__init__.py` (e.g. `2.0.0`).

## 2. Build the Windows package

Requires **Rust on the build machine** (`rustup`) — end users do not need Rust.

```powershell
.\venv\Scripts\activate
.\scripts\build_windows.ps1
.\scripts\package_release.ps1
```

`build_windows.ps1` compiles `lcseq` via maturin, runs parity tests, then PyInstaller bundles the extension into `_internal/`.

Output: `release\LC-Seq-vX.Y.Z-windows.zip`

## 3. Source tree readiness

- [ ] No secrets in git (`config/settings.json` and `config/configs/` are gitignored)
- [ ] Dev-only docs (`docs/AGENT_INSTRUCTIONS.md`, `docs/archive/`, `docs/LC-Seq-New-master-ANALYSIS.md`) stay in the git repo only — the release zip contains only `dist/LC-Seq/` (exe + bundled config example)
- [ ] `CHANGELOG.md` updated for this version
- [ ] README and [INSTALL.md](INSTALL.md) accurate
- [ ] Commit and push to `main`

## 4. Tag and GitHub Release

```powershell
git tag -a v2.0.0 -m "LC-Seq v2.0.0"
git push origin v2.0.0
```

On GitHub: **Releases** → **Draft a new release**

| Field | Content |
|-------|---------|
| Tag | `v2.0.0` |
| Title | `LC-Seq v2.0.0` |
| Description | Copy the `[2.0.0]` section from [CHANGELOG.md](../CHANGELOG.md) (includes SmartScreen FAQ) |
| Assets | Upload `release/LC-Seq-v2.0.0-windows.zip` |

### GitHub Release description (paste template)

Copy the full `[2.0.0]` block from CHANGELOG, or use this shorter body plus the changelog link:

```markdown
## LC-Seq v2.0.0

Library Analysis, pedigree/lineage, DEL-cycle tree, and export bundle. Rust analysis engine (`lcseq`) is **bundled** — no Rust or Python install required.

### Windows install notes

- Extract the full zip; keep `LC-Seq.exe` and `_internal/` together.
- **SmartScreen:** Unsigned app — if you see “Windows protected your PC”, choose **More info** → **Run anyway**.
- **Antivirus:** Some tools flag PyInstaller apps; restore/quarantine exceptions for the extracted folder if needed.
- Optional: [Graphviz](https://graphviz.org/download/) for higher-quality pedigree split-tree figures.

See [INSTALL.md](docs/INSTALL.md) and the full [CHANGELOG](CHANGELOG.md).
```

After the first test download (step 5), adjust wording if your machine shows different prompt text.

## 5. Test download (14.2 / 14.3)

On a machine **without** the dev repo:

- [ ] Download only the release zip from GitHub
- [ ] Extract and run `LC-Seq.exe`
- [ ] Load spreadsheet → configure → create/load DB → visualizer → plot → export
- [ ] Note any SmartScreen or antivirus prompts during test download; tweak RELEASE.md template if wording differs

## Release asset layout

```
LC-Seq-v2.0.0-windows.zip
└── LC-Seq/
    ├── LC-Seq.exe
    ├── _internal/          # PyInstaller bundle (required)
    ├── config/             # created on first run (optional template in zip)
    └── output/
        └── databases/      # created on first run
```

Users should unzip the whole `LC-Seq` folder, not only the `.exe`.

## What is NOT in the release zip

`package_release.ps1` zips **only** `dist/LC-Seq/` (PyInstaller output). The following stay in the git repo for developers and are **not** shipped to end users:

| Category | Examples |
|----------|----------|
| Source tree | `src/` (except what PyInstaller traces into `_internal/`), `LC-Seq-New-master/` Rust sources |
| Tests | `tests/`, `LC-Seq-New-master/python/tests/`, `LC-Seq-New-master/tests/` |
| Dev scripts | `scripts/assess_peak_picker_compound.py`, `scripts/full_fraction_nonzero_coverage.py`, `LC-Seq-New-master/scripts/extract_real_fixture.py` |
| Build scripts | `scripts/build_windows.ps1`, `scripts/package_release.ps1`, `lc_seq.spec` |
| Dev docs | `docs/archive/`, `docs/AGENT_INSTRUCTIONS.md`, `docs/LC-Seq-New-master-ANALYSIS.md`, `release_checklist.md` |
| User data patterns | `output/library_data/`, `output/pedigree_analysis/`, `config/configs/` (created locally beside the exe) |

PyInstaller bundles only imported runtime dependencies (CustomTkinter, matplotlib, **lcseq** + `_native.pyd`). It does not copy the full repository.

**End users** who download the release zip do **not** need Rust, Python, or maturin. Only **maintainers** building the zip need Rust installed.
