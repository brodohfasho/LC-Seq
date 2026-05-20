# Changelog

All notable releases of LC-Seq are documented here.

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
- [docs/INSTALL.md](docs/INSTALL.md), [docs/BUILD.md](docs/BUILD.md), [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

### Known limitations

- Windows-first; packaged build is tested on Windows 10/11 x64
- Executable uses its own data directory (see INSTALL.md)
- Very large spreadsheets: prefer index databases; full DB builds can take time and disk space

[1.0.0]: https://github.com/brodohfasho/LC-Seq/releases/tag/v1.0.0
