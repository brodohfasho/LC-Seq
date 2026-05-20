# Publishing a GitHub release (maintainers)

Use this checklist for Phase 14.2–14.3 when shipping a new version.

## 1. Version bump

Update `__version__` in `src/__init__.py` (e.g. `1.0.0`).

## 2. Build the Windows package

```powershell
.\venv\Scripts\activate
.\scripts\build_windows.ps1
.\scripts\package_release.ps1
```

Output: `release\LC-Seq-vX.Y.Z-windows.zip`

## 3. Source tree readiness

- [ ] No secrets in git (`config/settings.json` is gitignored)
- [ ] `CHANGELOG.md` updated for this version
- [ ] README and [INSTALL.md](INSTALL.md) accurate
- [ ] Commit and push to `main`

## 4. Tag and GitHub Release

```powershell
git tag -a v1.0.0 -m "LC-Seq v1.0.0"
git push origin v1.0.0
```

On GitHub: **Releases** → **Draft a new release**

| Field | Content |
|-------|---------|
| Tag | `v1.0.0` |
| Title | `LC-Seq v1.0.0` |
| Description | Copy the `[1.0.0]` section from [CHANGELOG.md](../CHANGELOG.md) |
| Assets | Upload `release/LC-Seq-v1.0.0-windows.zip` |

## 5. Test download (14.2 / 14.3)

On a machine **without** the dev repo:

- [ ] Download only the release zip from GitHub
- [ ] Extract and run `LC-Seq.exe`
- [ ] Load spreadsheet → configure → create/load DB → visualizer → plot → export
- [ ] Note any SmartScreen or antivirus prompts for the release notes FAQ

## Release asset layout

```
LC-Seq-v1.0.0-windows.zip
└── LC-Seq/
    ├── LC-Seq.exe
    ├── _internal/          # PyInstaller bundle (required)
    ├── config/             # created on first run (optional template in zip)
    └── output/
        └── databases/      # created on first run
```

Users should unzip the whole `LC-Seq` folder, not only the `.exe`.
