# Developer setup: Rust analysis engine

The production peak-picking and pedigree algorithms live in `LC-Seq-New-master/` (Rust).

## One-time setup (developers)

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

The app runs with a **Python fallback** picker (same algorithm, requires `scipy`). The Peak Analysis panel shows `Engine: Python fallback` until the Rust extension is built.

## Graphviz (pedigree split-tree export in Library Data)

Full-library pedigree analysis can export a split-tree PNG/SVG/PDF. Install:

1. [Graphviz](https://graphviz.org/download/) — ensure the `dot` executable is on PATH.
2. Python package (included in `requirements.txt`): `pip install graphviz`

Verify:

```powershell
dot -V
..\venv\Scripts\python.exe -c "import graphviz; print(graphviz.__version__)"
```

Without Graphviz, pedigree **evaluation** still runs; the app draws a **matplotlib tier-ring preview** automatically. Install Graphviz for the higher-quality native split-tree layout (`twopi`).
