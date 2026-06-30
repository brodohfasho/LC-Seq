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

## Without Rust

The app runs with a **Python fallback** picker (same algorithm, requires `scipy`). The Peak Analysis panel shows `Engine: Python fallback` until the Rust extension is built.

## Graphviz (pedigree tree PNG export — coming in Library Data)

Install [Graphviz](https://graphviz.org/download/) and ensure `dot` is on PATH for `render_pruned_tree`.
