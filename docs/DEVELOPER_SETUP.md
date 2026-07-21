# Developer setup: Rust analysis engine

Peak picking and pedigree algorithms live in `LC-Seq-New-master/` (Rust crate with Python bindings via maturin).

## One-time setup

1. Install [Rust](https://rustup.rs/) (`rustup` adds `rustc` and `cargo` to PATH).
2. From the repo root:

```powershell
cd LC-Seq-New-master
..\venv\Scripts\python.exe -m pip install maturin numpy
..\venv\Scripts\maturin.exe develop --release
```

3. Verify:

```powershell
..\venv\Scripts\python.exe -c "import lcseq; print(lcseq.find_peaks)"
```

## Troubleshooting (Windows)

### `rustc is not installed or not in PATH`

Rust is often installed, but **terminals that were already open** do not see the updated PATH.

1. **Close and reopen** PowerShell / Cursor terminal (or restart Cursor).
2. Confirm Rust is visible:

```powershell
rustc --version
```

If that fails, open a **new** terminal and try again. Rust installs to `%USERPROFILE%\.cargo\bin`.

3. Activate the project venv **before** `maturin develop` (maturin needs `VIRTUAL_ENV`):

```powershell
cd <repo-root>
.\venv\Scripts\Activate.ps1
cd LC-Seq-New-master
maturin develop --release
```

If `rustc` works in a new terminal but an old one still fails, run once in that session:

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;" + $env:PATH
```

## Without Rust

The app runs with a **Python fallback** peak picker (same Modern algorithm; requires `scipy`). The Peak Analysis panel shows `Engine: Python fallback` until the Rust extension is built.

On startup, LC-Seq runs a **parity check** between the installed `lcseq` extension and the Python reference picker. If they disagree (for example after pulling new Rust code without rebuilding), peak picking automatically falls back to Python so results stay correct.

**Pedigree** and **lineage** analysis require the Rust extension (`evaluate_library` / `diagnose_class` have no Python port).

## Rebuild after changing `LC-Seq-New-master`

Whenever Rust peak-picking or pedigree code changes:

1. **Close LC-Seq** (and any Python process importing `lcseq`) so the `.pyd` is not locked.
2. Rebuild:

```powershell
cd LC-Seq-New-master
..\venv\Scripts\maturin.exe develop --release
```

3. Verify parity:

```powershell
..\venv\Scripts\python.exe -m pytest ..\tests\test_lcseq_backend_parity.py -q
```

If maturin reports `The process cannot access the file because it is being used by another process`, the app is still running — close it and retry.

## Folder layout

The active crate contains Rust source, `python/lcseq/render.py`, and tests. Earlier standalone xlsx/CLI tooling is archived under `docs/archive/lcseq-standalone/`. See [LC-Seq-New-master-ANALYSIS.md](LC-Seq-New-master-ANALYSIS.md) for the API map.

## Feature split: what still requires Rust

| Feature | Python fallback | Rust required |
|---------|-----------------|---------------|
| Peak picking (single compound) | Yes | Optional (faster / bundled in release zip) |
| Library signal quality / SNR | Yes | Optional |
| Pedigree / lineage | No | **Yes** |

## Graphviz (pedigree figure export in Library Analysis)

Full-library pedigree analysis can export a radial pedigree PNG/SVG/PDF. Install:

1. [Graphviz](https://graphviz.org/download/) — ensure the `dot` executable is on PATH.
2. Python package (included in `requirements.txt`): `pip install graphviz`

Verify:

```powershell
dot -V
..\venv\Scripts\python.exe -c "import graphviz; print(graphviz.__version__)"
```

Without Graphviz, pedigree **evaluation** still runs; the app draws a **matplotlib tier-ring preview** automatically. Install Graphviz for the higher-quality native radial layout (`twopi`).

**Note:** The **Split-tree visualization** tab (combinatorial BB tree) uses matplotlib and does not require Graphviz.
