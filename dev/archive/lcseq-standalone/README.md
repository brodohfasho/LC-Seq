# dev/archive/lcseq-standalone

**Standalone** LC-Seq tooling from before integration into the main CustomTkinter app. Not used by the GUI at runtime.

| File | Purpose |
|------|---------|
| `lcseq_io.py` | Parse fixed-schema LDEL master xlsx → `bbs_per_position` + chromatogram dict |
| `cli.py` | Command-line: `parse_xlsx → evaluate_library → render_pruned_tree` |
| `debug.py` | Matplotlib per-class / lineage diagnostic figures |
| `COLLEAGUE_README.md` | Original standalone project README (uv workflow, data layout) — historical filename |
| `uv.lock` | Historical uv lockfile |
| `tests/` | pytest for xlsx I/O and CLI (slow tests need master xlsx under `LC-Seq-New-master/data/`) |

## Running the archived CLI (optional)

Requires a built `lcseq` extension (`maturin develop` in `LC-Seq-New-master/`) and Graphviz on PATH for tree output:

```powershell
cd dev/archive/lcseq-standalone
..\..\..\venv\Scripts\python.exe cli.py run path\to\master.xlsx --bbs Val Phe Leu --out tree --unit minutes --tolerance 0.5
```

## Why archived

The main LC-Seq app loads spreadsheets via Configure Spreadsheet, stores compounds in SQLite, and adapts data through `src/core/pedigree_adapter.py`. Keeping duplicate xlsx ingestion and a separate CLI in the active package caused confusion without adding runtime value.
